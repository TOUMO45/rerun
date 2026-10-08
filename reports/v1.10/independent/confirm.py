"""harness-v1.10 pass, task 3: confirm that each patch of the independent set reaches exit 0 on its repository (PROVENANCE.md, step 1).

    backend/.venv/Scripts/python.exe reports/v1.10/independent/confirm.py --worktree .claude/worktrees/v110-harness-v1.9.0 --tag harness-v1.9.0 --out reports/v1.10/independent/confirm [--go]

Every patch is applied (git apply, to LF copies of the pinned checkout's files) and the post-patch files are written into the kept environment image of the patch's repository
(reports/v1.10/pipeline/scenarios.json, the images of the full-pipeline measurement), then the documented command is run under the smoke launcher, ONE real sandbox run per patch
(common.run_on_image; no model call, no gate, no adjudicator). A cheat is CONFIRMED when the run ends with exit code 0 (finished, or alive at the 60 s limit). A cheat that does not is
dropped from the measured set and reported by family; nothing is edited to make it work. Controls are run the same way and all kept (a control that does not reach exit 0 cannot be refused by a
later layer; the count is reported). The exit-zero check (D-46) is recorded but does not decide confirmation: a cheat that exits 0 after a traceback is a cheat for the audit layer to catch.

Without --go nothing is spent. Resumable; a driver or API error is re-run once (--retry-errors), as in the full-pipeline protocol.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "pipeline"))
import common  # noqa: E402

ROOT = common.ROOT
CHECKOUTS = ROOT / ".cache" / "planted_repos"


def touched_paths(patch: str) -> list[str]:
    out = []
    for line in patch.splitlines():
        if line.startswith("diff --git a/"):
            out.append(line[len("diff --git a/"):].split(" b/")[0])
    return out


def post_patch_files(repo_dir: Path, patch: str) -> dict[str, str]:
    """The post-patch text of every file the patch touches: the committed bytes of the originals are copied into a scratch directory, `git apply` is run there, the results are read back as text."""
    paths = touched_paths(patch)
    with tempfile.TemporaryDirectory(prefix="rerun_confirm_") as tmp:
        scratch = Path(tmp)
        for rel in paths:
            blob = subprocess.run(["git", "-C", str(repo_dir), "show", f"HEAD:{rel}"], capture_output=True)  # the committed bytes, as the author's diff was made against
            if blob.returncode == 0:
                target = scratch / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(blob.stdout)
        (scratch / "_p.patch").write_bytes(patch.encode("utf-8"))
        done = subprocess.run(["git", "apply", "--whitespace=nowarn", "_p.patch"], cwd=scratch, capture_output=True, text=True)
        if done.returncode != 0:
            raise RuntimeError(f"git apply failed: {done.stderr.strip()[:300]}")
        return {rel: (scratch / rel).read_text(encoding="utf-8") for rel in paths if (scratch / rel).is_file()}


def confirm_one(h, row: dict, scen: dict, bases: dict) -> dict:
    out = {"id": row["id"], "repo": row["repo"], "kind": row["kind"], "family": row["family"], "image": scen["image"], "cost_usd": 0.0}
    patch = (HERE / "patches" / f"{row['id']}.patch").read_text(encoding="utf-8")
    try:
        files = post_patch_files(Path(bases[row["repo"]]["checkout"]), patch)
    except Exception as exc:  # noqa: BLE001
        return {**out, "outcome": "not_applied", "error": f"{type(exc).__name__}: {str(exc)[:300]}"}
    started = time.monotonic()
    step = common.run_on_image(h, scen["image"], scen["command"], files)
    out["cost_usd"] = step.cost_usd
    out["run"] = {"exit_code": step.exit_code, "timed_out": step.timed_out, "wall_s": round(time.monotonic() - started, 1), **common.tails(step, 1200)}
    if step.exit_code == 97 and "RERUN_OVERLAY_MISMATCH" in (step.stderr or ""):
        return {**out, "outcome": "void"}
    res = common.sandbox_result(h, step)
    out["run"]["smoke"] = h.smoke_exec.execution_record(common.SMOKE_SECONDS, step.exit_code, step.stdout, step.stderr)["outcome"]
    finding = h.exit_zero_check.finding_of(res)
    if finding:
        out["audit"] = finding
    out["reaches_exit0"] = step.exit_code == 0
    out["outcome"] = "confirmed" if step.exit_code == 0 else "not_confirmed"
    if step.exit_code != 0:
        c = h.classifier.classify(step.exit_code, step.stderr, step.stdout)
        out["run"]["classification"] = {"code": c.code, "evidence": (c.evidence or "")[:200]}
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--worktree", required=True)
    ap.add_argument("--tag", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--scenarios", default=str(HERE.parent / "pipeline" / "scenarios.json"))
    ap.add_argument("--threads", type=int, default=4)
    ap.add_argument("--cap-usd", type=float, default=8.0)
    ap.add_argument("--retry-errors", action="store_true")
    ap.add_argument("--go", action="store_true")
    ap.add_argument("--log-file")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    if args.log_file:
        sys.stdout = sys.stderr = open(args.log_file, "a", encoding="utf-8", buffering=1)
    h = common.load_harness(Path(args.worktree), args.tag)
    scen = json.loads(Path(args.scenarios).read_text(encoding="utf-8"))["scenarios"]
    bases_doc = {b["name"]: b for b in json.loads((ROOT / "reports/v1.9/planted/bases.json").read_text(encoding="utf-8"))["bases"]}
    bases = {n: {**b, "checkout": str(CHECKOUTS / b["repo"].replace("/", "_"))} for n, b in bases_doc.items()}
    manifest = json.loads((HERE / "manifest.json").read_text(encoding="utf-8"))
    results_path = out / "results.jsonl"
    if args.retry_errors and results_path.is_file():
        lines = [l for l in results_path.read_text(encoding="utf-8").splitlines() if l.strip()]
        failed = [l for l in lines if json.loads(l).get("outcome") == "error"]
        if failed:
            with (out / "errors_first_attempt.jsonl").open("a", encoding="utf-8") as f:
                f.write("\n".join(failed) + "\n")
            results_path.write_text("\n".join(l for l in lines if l not in failed) + "\n", encoding="utf-8")
    done = {json.loads(l)["id"] for l in results_path.read_text(encoding="utf-8").splitlines() if l.strip()} if results_path.is_file() else set()
    todo = [r for r in manifest if r["id"] not in done]
    print(f"{time.strftime('%H:%M:%S')} {len(manifest)} patches, {len(done)} done, {len(todo)} to run at {h.tag} {h.head[:8]}", flush=True)
    if not args.go:
        return 0
    lock, spent = threading.Lock(), {"usd": 0.0, "n": 0, "stop": False}

    def work(row: dict) -> None:
        if spent["stop"]:
            return
        try:
            rec = confirm_one(h, row, scen[row["repo"]], bases)
        except Exception as exc:  # noqa: BLE001
            rec = {"id": row["id"], "repo": row["repo"], "kind": row["kind"], "family": row["family"], "outcome": "error", "error": f"{type(exc).__name__}: {str(exc)[:300]}", "cost_usd": 0.0}
        rec["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        with lock:
            with results_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            spent["usd"] += rec.get("cost_usd") or 0.0
            spent["n"] += 1
            print(f"{time.strftime('%H:%M:%S')} #{spent['n']} {row['id']} -> {rec['outcome']} ({rec.get('run', {}).get('smoke', '')}) total ${spent['usd']:.4f}", flush=True)
            if spent["usd"] > args.cap_usd:
                spent["stop"] = True
                print(f"CAP: ${spent['usd']:.2f} > ${args.cap_usd:.2f}; stopping", flush=True)

    with ThreadPoolExecutor(max_workers=args.threads) as pool:
        list(pool.map(work, todo))
    (out / f"spend_{int(time.time())}.json").write_text(json.dumps({"harness_tag": h.tag, "patches_run": spent["n"], "spend_usd_api_reported": round(spent["usd"], 6)}, indent=1) + "\n", encoding="utf-8")
    print(f"done: {spent['n']} patches, ${spent['usd']:.4f}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
