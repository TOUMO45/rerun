"""Live scan of public repositories through RERUN's own web API: exactly what the UI does (POST /runs = intake, then POST /runs/{id}/execute).

    backend/.venv/Scripts/pythonw.exe reports/live_scan/run_live_scan.py --log-file runs/live_scan/scan_stdout.log URL [URL ...]

Owner's request in chat (2026-10-05): scan five small, older repositories live. REAL runs, outside the dev/test protocol (no tuning, no count). Each repository
gets a FRESH backend process with DAILY_COST_CEILING_USD=2.50, because the cost guard is a process-wide singleton (cost_guard.get_cost_guard): one process per
repository makes $2.50 a per-run cap. The UI passes no arguments to the entrypoint, so neither does this. For every run it writes the certificate in the
exact form the Certificate page's "Download certificate JSON" button produces (verifiable with scripts/verify_passport.py), the API's certificate, and a
summary line with the cost read from the cost guard's own log lines. Run it detached (a paid run is never a child of a session, D-43).
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

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "runs" / "live_scan"
API = "http://127.0.0.1:8010"  # not 8000: the owner may be running their own backend there
CAP_USD = 2.50


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _call(method: str, path: str, body: dict | None = None, timeout: float = 60):
    req = urllib.request.Request(API + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _start_backend() -> subprocess.Popen:
    env = dict(os.environ, DEMO_MODE="0", DAILY_COST_CEILING_USD=f"{CAP_USD:.2f}", DATABASE_URL="sqlite:///./data/rerun_live_scan.db")
    proc = subprocess.Popen([str(ROOT / "backend" / ".venv" / "Scripts" / "python.exe"), "-m", "uvicorn", "app.main:app", "--port", "8010"],
                            cwd=ROOT / "backend", env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    for _ in range(60):
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
    """The Certificate page's downloadCertificate() payload (frontend/src/screens/Certificate.tsx), field for field."""
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


def scan(url: str) -> dict:
    name = url.rstrip("/").split("/")[-2] + "__" + url.rstrip("/").split("/")[-1]
    row = {"repo_url": url, "name": name, "started_at": _now(), "cap_usd": CAP_USD}
    proc = _start_backend()
    try:
        try:
            run = _call("POST", "/runs", {"repo_url": url}, timeout=300)
        except urllib.error.HTTPError as exc:
            row.update(stage="intake_refused", http=exc.code, detail=exc.read().decode("utf-8", "replace")[:500])
            return row
        row["run_id"] = run["id"]
        print(f"{_now()} {name}: intake ok, commit {run.get('commit_sha')}; executing", flush=True)
        try:
            run = _call("POST", f"/runs/{run['id']}/execute", timeout=3600)
        except urllib.error.HTTPError as exc:
            row.update(stage="execute_refused", http=exc.code, detail=exc.read().decode("utf-8", "replace")[:500])
            return row
        cert = _call("GET", f"/runs/{run['id']}/certificate", timeout=120)
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        (OUT / f"{stamp}_{name}_certificate.json").write_text(json.dumps(_button_payload(run, cert), indent=2), encoding="utf-8")
        (OUT / f"{stamp}_{name}_api_certificate.json").write_text(json.dumps(cert, indent=2), encoding="utf-8")
        row.update(stage=run.get("stage"), verdict=cert["verdict"], label=cert.get("verdict_label"), taxonomy_code=cert.get("taxonomy_code"),
                   indeterminate_reason=cert.get("indeterminate_reason"), outcome_levels=cert.get("outcome_levels"), blocker=cert.get("blocker"),
                   execute_command=(cert.get("build_plan") or {}).get("execute_command"), passport=cert.get("reproduction_passport_hash"),
                   cost=_cost(cert.get("full_log") or ""), certificate=f"runs/live_scan/{stamp}_{name}_certificate.json")
        return row
    finally:
        proc.kill()
        proc.wait(timeout=30)
        row["finished_at"] = _now()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("urls", nargs="+")
    ap.add_argument("--log-file")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)  # before the log file, which lives in it (a pythonw process cannot report the error otherwise)
    if args.log_file:
        sys.stdout = sys.stderr = open(args.log_file, "a", encoding="utf-8", buffering=1)
    summary_path = OUT / "scan_summary.json"
    rows = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.is_file() else []
    print(f"{_now()} live scan of {len(args.urls)} repositories; ${CAP_USD:.2f} cap each; worst case ${CAP_USD * len(args.urls):.2f}", flush=True)
    for url in args.urls:
        try:
            row = scan(url)
        except Exception as exc:  # noqa: BLE001 - recorded, the next repository still runs
            row = {"repo_url": url, "stage": "error", "error": f"{type(exc).__name__}: {exc}"[:500], "finished_at": _now()}
        rows.append(row)
        summary_path.write_text(json.dumps(rows, indent=2), encoding="utf-8")
        print(f"{_now()} {row.get('name', url)}: {row.get('verdict') or row.get('stage')} {row.get('label') or ''} cost {row.get('cost')}", flush=True)
    print(f"{_now()} done", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
