"""harness-v1.9, task 4: ValvePython/steamctl, 3 runs at harness-v1.7.2 and 3 at harness-v1.8.0, through RERUN's own API, exactly as the OOS scans ran it.

    backend/.venv/Scripts/pythonw.exe -u reports/v1.9/steamctl/run_steamctl.py --go --log-file runs/v1.9/steamctl/run_stdout.log

Owner (chat, 2026-10-08): "3 runs on harness-v1.7.2 and 3 on harness-v1.8.0, $12 cap. Report raw counts. Bisect only if v1.7.2 runs at least 2/3 and v1.8.0 runs 0/3;
otherwise record it as variance in the defects register."

How (fixed before the first run, see PLAN.md):
* Each tag is checked out as its own git worktree (`.claude/worktrees/v19-steamctl-<tag>`, detached at the tag's commit). The driver refuses a worktree whose HEAD is not the tag's
  commit or whose harness paths differ from the tag. The backend is started from that worktree's `backend/` with this repository's venv interpreter; `python -m uvicorn` puts the
  working directory first on sys.path, and a preflight in the same directory prints `app.__file__`, which must lie inside the worktree.
* One fresh backend process per run with DAILY_COST_CEILING_USD=2.00 (the cost guard is a process-wide singleton, so this is a per-run cap): 6 x $2.00 = $12.00 worst case.
* The runs alternate tags (v1.7.2, v1.8.0, v1.7.2, ...) so that time of day and model-endpoint drift fall on both sides alike.
* No arguments are passed to the entrypoint (the UI passes none, as in the OOS scans). Every certificate is written in the form the UI's download button gives, plus the API's.
* "Runs" = the verdict as the certificate states it is RUNS_CLEAN or RUNS_AFTER_REPAIR, counted raw; the D-51 caveat (an exit 0 after argcomplete's notice) is stated beside it.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PY = ROOT / "backend" / ".venv" / "Scripts" / "python.exe"
OUT = ROOT / "runs" / "v1.9" / "steamctl"
URL = "https://github.com/ValvePython/steamctl"
EXPECTED_COMMIT = "274a8db0ccedb7cf1f80546581916874c20dc317"  # the commit all three earlier runs used (OOS v1.7.2, v1.8 DEV round 1 and its repeat)
API = "http://127.0.0.1:8010"
CAP_USD = 2.00
HARNESS_PATHS = ("backend/app", "backend/pyproject.toml", "scripts", "frontend/src", ".gitattributes")
TAGS = ("harness-v1.7.2", "harness-v1.8.0")
ORDER = ("harness-v1.7.2", "harness-v1.8.0", "harness-v1.7.2", "harness-v1.8.0", "harness-v1.7.2", "harness-v1.8.0")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def worktree(tag: str) -> Path:
    return ROOT / ".claude" / "worktrees" / f"v19-steamctl-{tag}"


def _git(*args: str, cwd: Path = ROOT) -> str:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


def preflight(tag: str) -> dict:
    wt = worktree(tag)
    if not wt.is_dir():
        raise SystemExit(f"{wt} missing: git worktree add --detach {wt} {tag}")
    head = _git("rev-parse", "HEAD", cwd=wt)
    want = _git("rev-parse", f"{tag}^{{commit}}")
    if head != want:
        raise SystemExit(f"{wt} HEAD {head} is not {tag} = {want}")
    if _git("status", "--porcelain", "--", *HARNESS_PATHS, cwd=wt):
        raise SystemExit(f"{wt}: harness paths are not clean")
    if not (wt / ".env").is_file():
        raise SystemExit(f"{wt}/.env missing (config reads the .env beside the worktree's own backend)")
    app_file = subprocess.run([str(PY), "-c", "import app, sys; print(app.__file__)"], cwd=wt / "backend", capture_output=True, text=True, check=True).stdout.strip()
    if not Path(app_file).resolve().is_relative_to(wt.resolve()):
        raise SystemExit(f"{tag}: app imports from {app_file}, not from the worktree")
    return {"tag": tag, "commit": head, "worktree": wt.relative_to(ROOT).as_posix(), "app_file": app_file}


def _call(method: str, path: str, body: dict | None = None, timeout: float = 60):
    req = urllib.request.Request(API + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _start_backend(tag: str, db: Path) -> subprocess.Popen:
    env = dict(os.environ, DEMO_MODE="0", DAILY_COST_CEILING_USD=f"{CAP_USD:.2f}", DATABASE_URL=f"sqlite:///{db.as_posix()}")
    proc = subprocess.Popen([str(PY), "-m", "uvicorn", "app.main:app", "--port", "8010"], cwd=worktree(tag) / "backend", env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    for _ in range(90):
        try:
            health = _call("GET", "/healthz", timeout=3)
            if health.get("demo_mode") is False and health.get("nebius_configured"):
                return proc
        except Exception:  # noqa: BLE001 - not up yet
            pass
        time.sleep(1)
    proc.kill()
    raise RuntimeError("backend did not start in live mode")


def _button_payload(run: dict, cert: dict) -> dict:
    """The Certificate page's downloadCertificate() payload, field for field (same as reports/live_scan/run_live_scan.py)."""
    p = {"repo_url": run["repo_url"], "commit_sha": run["commit_sha"]}
    p.update({k: cert.get(k) for k in ("build_plan", "full_log", "diffs", "verdict", "timestamp", "reproduction_passport_hash")})
    bv = cert.get("bundle_version") or 0
    if bv >= 2:
        p.update(bundle_version=bv, baseline=cert.get("baseline"), recovery=cert.get("recovery"))
    if bv >= 3:
        p.update(tree_integrity=cert.get("tree_integrity"), corpus_hash=cert.get("corpus_hash"))
    if bv >= 4:
        p.update({k: cert.get(k) for k in ("taxonomy_code", "indeterminate_reason", "error_chain", "first_repo_error", "last_error")})
    if cert.get("outcome_levels"):
        p["outcome_levels"] = cert["outcome_levels"]
    if "blocker" in cert:
        p["blocker"] = cert["blocker"]
    return p


def _cost(log: str) -> dict:
    spends = [float(x) for x in re.findall(r"\[cost_guard\] recorded \$([0-9.]+) sandbox spend", log)]
    remaining = re.findall(r"\$([0-9.]+) remaining today", log)
    return {"sandbox_api_reported_usd": round(sum(spends), 6), "operations": len(spends),
            "guard_total_usd": round(CAP_USD - float(remaining[-1]), 6) if remaining else None,
            "estimated_lines": [line for line in log.splitlines() if "cost_guard" in line and "estimate" in line]}


def one_run(tag: str, k: int, pre: dict) -> dict:
    tag_dir = OUT / tag
    tag_dir.mkdir(parents=True, exist_ok=True)
    db = tag_dir / f"run{k}.db"
    row = {"tag": tag, "run": k, "repo_url": URL, "started_at": _now(), "cap_usd": CAP_USD, **{f"preflight_{x}": y for x, y in pre.items() if x != "tag"}}
    proc = _start_backend(tag, db)
    try:
        try:
            run = _call("POST", "/runs", {"repo_url": URL}, timeout=300)
        except urllib.error.HTTPError as exc:
            row.update(stage="intake_refused", http=exc.code, detail=exc.read().decode("utf-8", "replace")[:500])
            return row
        row.update(run_id=run["id"], commit_sha=run.get("commit_sha"), commit_matches_earlier_runs=run.get("commit_sha") == EXPECTED_COMMIT)
        print(f"{_now()} {tag} run {k}: intake ok, commit {run.get('commit_sha')}; executing", flush=True)
        try:
            run = _call("POST", f"/runs/{run['id']}/execute", timeout=3600)
        except urllib.error.HTTPError as exc:
            row.update(stage="execute_refused", http=exc.code, detail=exc.read().decode("utf-8", "replace")[:500])
            return row
        cert = _call("GET", f"/runs/{run['id']}/certificate", timeout=120)
        (tag_dir / f"run{k}_certificate.json").write_text(json.dumps(_button_payload(run, cert), indent=2), encoding="utf-8")
        (tag_dir / f"run{k}_api_certificate.json").write_text(json.dumps(cert, indent=2), encoding="utf-8")
        row.update(stage=run.get("stage"), verdict=cert["verdict"], label=cert.get("verdict_label"), taxonomy_code=cert.get("taxonomy_code"),
                   indeterminate_reason=cert.get("indeterminate_reason"), outcome_levels=cert.get("outcome_levels"),
                   execute_command=(cert.get("build_plan") or {}).get("execute_command"), passport=cert.get("reproduction_passport_hash"),
                   attempts=len(cert.get("diffs") or []), cost=_cost(cert.get("full_log") or ""),
                   certificate=(tag_dir / f"run{k}_certificate.json").relative_to(ROOT).as_posix())
        return row
    finally:
        proc.kill()
        proc.wait(timeout=30)
        row["finished_at"] = _now()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--go", action="store_true", help="without it: preflight only, nothing paid")
    ap.add_argument("--log-file")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    if args.log_file:
        sys.stdout = sys.stderr = open(args.log_file, "a", encoding="utf-8", buffering=1)
    pres = {tag: preflight(tag) for tag in TAGS}
    print(f"{_now()} preflight ok: {json.dumps(pres)}", flush=True)
    print(f"{_now()} worst case {len(ORDER)} x ${CAP_USD:.2f} = ${CAP_USD * len(ORDER):.2f}", flush=True)
    if not args.go:
        return 0
    summary = OUT / "summary.json"
    rows = json.loads(summary.read_text(encoding="utf-8")) if summary.is_file() else []
    done = {(r["tag"], r["run"]) for r in rows}
    counters = {tag: 0 for tag in TAGS}
    for tag in ORDER:
        counters[tag] += 1
        if (tag, counters[tag]) in done:
            continue
        try:
            row = one_run(tag, counters[tag], pres[tag])
        except Exception as exc:  # noqa: BLE001 - recorded; the next run still goes
            row = {"tag": tag, "run": counters[tag], "stage": "error", "error": f"{type(exc).__name__}: {exc}"[:500], "finished_at": _now()}
        rows.append(row)
        summary.write_text(json.dumps(rows, indent=2), encoding="utf-8")
        print(f"{_now()} {tag} run {row['run']} -> {row.get('verdict') or row.get('stage')} cost {row.get('cost')}", flush=True)
    print(f"{_now()} done", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
