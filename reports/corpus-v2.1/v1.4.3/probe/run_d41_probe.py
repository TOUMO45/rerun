"""D-41 probe (owner, chat 2026-10-02): does the SDK's output truncation hide #3's error?

    backend/.venv/Scripts/python.exe reports/corpus-v2.1/v1.4.3/probe/run_d41_probe.py                    # PLAN: the command, the image, ESTIMATED cost
    backend/.venv/Scripts/python.exe reports/corpus-v2.1/v1.4.3/probe/run_d41_probe.py --go --max-usd 0.05 # one live operation

The recorded failing operation: harness-v1.4.2 gate entry 3 (autumn9999__vmtl), operation 5 ("exit wrapper with evidence"), which ran the documented command
`python feature_vgg16.py #gpu_id #split` through the exit wrapper, the evidence suffix and the 60 s smoke launcher, on the kept image 31ff7d2a-841d-45fb-8f1f-2dc3ee8961fa
(tree + python:3.6-slim + torch 1.5.1 + the lock + the exit hook), and ended exit code 1 with a stderr that is all `17.x%` progress up to the stored tail.

This probe reruns EXACTLY that command (built by the same functions the orchestrator used: runner_hooks.wrap_entry_command, runner_hooks.evidence_command,
smoke_exec.wrap) on the same kept image, once, with the stream of the original operation redirected to a file inside the run:

  1. the command's stdout and stderr go to files (stdout and stderr stay separate);
  2. the run prints, on its own stdout (small, far below the limit): the exit status, the byte size and sha256 of both files, every line of the stderr file that is not
     a bare progress line (with its byte offset), and the last lines of the stderr file;
  3. the stderr file is then replayed on the run's own stderr, so the SDK returns what it returns for an unredirected operation: the `truncated` flags of the raw API
     result (stdout and stderr separately) and the length of the returned stderr are read here, beside the file's true size.

Nothing about the repository, the image or the harness changes: the command is the recorded one, on the recorded image, disposable.

Cost: the recorded operation cost $0.047575 API-reported (4.144 sandbox seconds); a faithful rerun costs about the same, so the cap is nearly the whole expected cost
(the owner's $0.05 cap: an earlier ~$0.002 estimate in chat was for a smaller read and was wrong for the full command). The script starts only if the cap is at least the
recorded operation's cost, uses an operation timeout of 8 s, and records any overshoot instead of hiding it. Never runs without --go and --max-usd.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "backend"))
OUT = ROOT / "runs" / "sandbox_verification" / "d41-probe"

RECORD = "runs/corpus_v2_batch/harness-v1.4.2/gate/03_autumn9999__vmtl.json"
OPERATION = 5
KEPT_IMAGE = "31ff7d2a-841d-45fb-8f1f-2dc3ee8961fa"
DOCUMENTED_COMMAND = "python feature_vgg16.py #gpu_id #split"
SMOKE_SECONDS = 60
RECORDED_OPERATION_COST_USD = 0.047575
OPERATION_TIMEOUT_S = 8
MAX_PROBE_USD = 0.05

STDERR_FILE = "/tmp/rerun_d41_stderr.txt"
STDOUT_FILE = "/tmp/rerun_d41_stdout.txt"

# `tr '\r' '\n'` turns the progress stream (carriage returns) into lines. The grep -v drops bare progress lines (`17.8%`), leaving anything else with its line number.
PROBE_TEMPLATE = r"""(
__COMMAND__
) >__OUT__ 2>__ERR__; rc=$?
echo "D41_PROBE exit_status=$rc"
echo "D41_PROBE stderr_bytes=$(wc -c < __ERR__) stdout_bytes=$(wc -c < __OUT__)"
echo "D41_PROBE stderr_sha256=$(sha256sum __ERR__ | cut -d' ' -f1)"
echo "D41_PROBE stdout_sha256=$(sha256sum __OUT__ | cut -d' ' -f1)"
echo "D41_PROBE progress_lines=$(tr '\r' '\n' < __ERR__ | grep -a -c -E '^[0-9.]+%$') other_lines=$(tr '\r' '\n' < __ERR__ | grep -a -v -E '^[0-9.]+%$' | wc -l)"
echo "D41_PROBE other_lines_begin"
tr '\r' '\n' < __ERR__ | grep -a -n -v -E '^[0-9.]+%$' | head -n 80 | cut -c1-400
echo "D41_PROBE other_lines_end"
echo "D41_PROBE last_progress=$(tr '\r' '\n' < __ERR__ | grep -a -E '^[0-9.]+%$' | tail -n 1)"
echo "D41_PROBE stderr_tail_begin"
tail -c 3000 __ERR__ | tr '\r' '\n' | tail -n 40 | cut -c1-400
echo "D41_PROBE stderr_tail_end"
echo "D41_PROBE stdout_tail_begin"
tail -c 2000 __OUT__ | cut -c1-400
echo "D41_PROBE stdout_tail_end"
cat __ERR__ >&2
exit $rc
"""


def probe_command() -> str:
    """The recorded operation 5 command (wrapper, evidence, smoke launcher), inside the redirecting probe script."""
    from app.services import runner_hooks, smoke_exec

    wrapped, why = runner_hooks.wrap_entry_command(DOCUMENTED_COMMAND)
    if wrapped is None:
        raise SystemExit(f"cannot rebuild the recorded command: {why}")
    recorded = smoke_exec.wrap(runner_hooks.evidence_command(wrapped), SMOKE_SECONDS)
    return PROBE_TEMPLATE.replace("__COMMAND__", recorded).replace("__ERR__", STDERR_FILE).replace("__OUT__", STDOUT_FILE), recorded


def recorded_operation() -> dict:
    doc = json.loads((ROOT / RECORD).read_text(encoding="utf-8"))
    op = next(o for o in doc["operations"] if o["n"] == OPERATION)
    assert op["role"] == "exit wrapper with evidence" and op["exit_code"] == 1, op["role"]
    assert op["branch_from_image"] == KEPT_IMAGE, op["branch_from_image"]
    assert abs(op["cost_usd"] - RECORDED_OPERATION_COST_USD) < 1e-9, op["cost_usd"]
    return op


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--go", action="store_true")
    ap.add_argument("--max-usd", type=float)
    args = ap.parse_args()
    op = recorded_operation()
    command, recorded = probe_command()
    print(f"recorded operation: {RECORD} operation {OPERATION} ({op['role']}), exit code {op['exit_code']}, ${op['cost_usd']:.6f} API-reported, "
          f"{op['sandbox_seconds']} sandbox seconds, branched from {op['branch_from_image']}")
    print(f"probe: one run of the same command on the same kept image; ESTIMATED cost ~${op['cost_usd']:.4f} (the recorded operation's cost); cap ${MAX_PROBE_USD}")
    if not args.go:
        print("PLAN ONLY: nothing was run and nothing was spent (pass --go and --max-usd to run).")
        return 0
    if args.max_usd is None or args.max_usd <= 0 or args.max_usd > MAX_PROBE_USD + 1e-9:
        print(f"REFUSED: --max-usd is required and must be at most ${MAX_PROBE_USD}", file=sys.stderr)
        return 2
    if args.max_usd + 1e-9 < op["cost_usd"]:
        print(f"REFUSED: the cap ${args.max_usd} is below the recorded operation's cost ${op['cost_usd']}", file=sys.stderr)
        return 2
    from app.config import get_settings
    from contree_sdk import ContreeSync
    from contree_sdk.auth import IAMAuth
    from contree_sdk.config import ContreeConfig

    settings = get_settings()
    client = ContreeSync(config=ContreeConfig(auth=IAMAuth(token=settings.nebius_api_key, project_id=settings.nebius_project_id),
                                              transport_timeout=60, operation_timeout=OPERATION_TIMEOUT_S + 30))
    started = datetime.now(timezone.utc)
    image = client.images.use(KEPT_IMAGE, strict=True)
    done = image.run(shell=command, timeout=OPERATION_TIMEOUT_S, disposable=True, preserve_env=False).wait()
    result = done.result
    raw = getattr(result, "_raw", None)
    raw_result = getattr(raw, "result", None)
    stdout, stderr = result.stdout or "", result.stderr or ""
    flags = {
        "sdk_result_truncated": bool(result.truncated),
        "raw_stdout_truncated": bool(getattr(getattr(raw_result, "stdout", None), "truncated", False)),
        "raw_stderr_truncated": bool(getattr(getattr(raw_result, "stderr", None), "truncated", False)),
        "raw_stdout_encoding": str(getattr(getattr(raw_result, "stdout", None), "encoding", "")),
        "raw_stderr_encoding": str(getattr(getattr(raw_result, "stderr", None), "encoding", "")),
        "state_timed_out": getattr(getattr(raw_result, "state", None), "timed_out", None),
    }
    doc = {
        "record_kind": "d41 probe: the recorded failing operation of harness-v1.4.2 gate entry 3 rerun once on its kept image",
        "started_at": started.isoformat(),
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "recorded_operation": {"record": RECORD, "operation": OPERATION, "role": op["role"], "image": KEPT_IMAGE, "exit_code": op["exit_code"],
                               "cost_usd": op["cost_usd"], "sandbox_seconds": op["sandbox_seconds"]},
        "documented_command": DOCUMENTED_COMMAND,
        "recorded_command_sha256": sha(recorded),
        "probe_command": command,
        "sdk_default_truncate_output_at": 65535,
        "exit_code": result.exit_code,
        "cost_usd": result.cost,
        "elapsed_seconds": result.elapsed_time.total_seconds(),
        "flags": flags,
        "returned_stdout_bytes": len(stdout.encode("utf-8")),
        "returned_stderr_bytes": len(stderr.encode("utf-8")),
        "returned_stderr_sha256": sha(stderr),
        "returned_stderr_head": stderr[:400],
        "returned_stderr_tail": stderr[-400:],
        "probe_stdout": stdout,
        "spend_cap_usd": args.max_usd,
        "cost_over_cap_usd": round(max(0.0, float(result.cost) - args.max_usd), 6),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "probe_03_vmtl_op5.json"
    path.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({k: doc[k] for k in ("exit_code", "cost_usd", "elapsed_seconds", "flags", "returned_stdout_bytes", "returned_stderr_bytes", "cost_over_cap_usd")}, indent=2))
    print("---- probe stdout (what the run printed about its own stderr file) ----")
    print(stdout)
    print(f"record written: {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
