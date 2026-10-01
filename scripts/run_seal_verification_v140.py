"""Seal verification of harness-v1.4.0, option B (owner decision 2026-10-01, METHODOLOGY "Seal of harness-v1.4.0"): the harness-v1.3.4
checks that the four gate entries (corpus-v2 #3, #7, #8, #11) exercise, repeated live against the changed sandbox-touching files. The new
checkpoint and runner-hook checks are runs 1 and 2 of reports/corpus-v2.1/v1.4.0/seal/run_seal_v140.py.

  backend/.venv/Scripts/python.exe scripts/run_seal_verification_v140.py --list
  backend/.venv/Scripts/python.exe scripts/run_seal_verification_v140.py --max-usd X      # spends money (owner's seal cap)

Not repeated for v1.4.0 (no gate entry uses them; listed in METHODOLOGY): the tarball fallback of the download route, torch pins on
Python 3.8 and the 3.10 1.12.1 pin, the patchelf-flag-absent case, and the D-20 download-route overlay (legacy, out of the live flow).
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import run_seal_verification_v133 as v133  # noqa: E402  (same verifier scripts and argument shapes)

TAG = "harness-v1.4.0"
OUT = "runs/sandbox_verification/final-v1.4.0"
KEEP = (
    "upload_archive_exec_bit_py36.json",          # #3 (python 3.6) and every small repo: the archive upload route
    "torch_py36_pin1.10.2.json",                  # #3: the era torch on python 3.6
    "torch_py310_imports_torchvision.json",       # #8, #11 baselines: newest matched torch family
    "torch_py39_pin1.8.1_numpy_cap.json",         # #11: the era torch with the NumPy cap
    "phase_runner_setup_failure_py310.json",      # every entry: a failing runner op is tagged runner_setup
    "smoke_alive_py310.json", "smoke_exits_ok_py310.json", "smoke_fails_py310.json", "smoke_silent_py310.json",
    "smoke_alive_py36.json", "smoke_fails_py36.json",  # every repair re-execution runs under the smoke launcher (smoke_exec changed)
)
PLAN = [p for p in v133.PLAN if p[0] in KEEP]
# #8's own repository (143 MB) by the download route, without the legacy overlay (its patches now travel in the branch overlay).
PLAN.insert(0, ("download_git_entry8_py310.json",
                [v133.DL, "https://github.com/edenton/svg", "3f19f0b581161614382b2d529f8d92c7d25999e5", "python:3.10-slim", "{out}"],
                {}, "download route (git), entry 8's repository"))
KILL = ("kill_at_operation_limit_py310{n}.json", [v133.V133, "kill", "python:3.10-slim", "{out}"], {}, "a step is killed at the operation limit")
MAX_KILL_RUNS = 4  # until both stop paths (server result timed_out, client wait timeout) have been seen live
CONSERVATIVE_COST = v133.CONSERVATIVE_COST


def _command(record: str, argv: list[str]) -> list[str]:
    return [v133.PY, *(a.replace("{out}", f"{OUT}/{record}") for a in argv)]


def _run(record: str, argv: list[str], env: dict) -> tuple[bool, float, dict]:
    proc = subprocess.run(_command(record, argv), cwd=ROOT, env={**os.environ, **env, "PYTHONIOENCODING": "utf-8"},
                          capture_output=True, text=True, timeout=1500)
    done = ROOT / OUT / record
    if not done.is_file():
        print(proc.stdout[-800:], proc.stderr[-800:])
        return False, CONSERVATIVE_COST, {}
    rec = json.loads(done.read_text(encoding="utf-8"))
    value = rec.get("cost_usd", rec.get("completed_cost_usd", rec.get("cost")))
    cost = float(value) if isinstance(value, (int, float)) else CONSERVATIVE_COST
    if rec.get("ok") is not True:
        print(proc.stdout[-800:], proc.stderr[-800:])
    return rec.get("ok") is True, cost, rec


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--max-usd", type=float, default=0.0)
    args = ap.parse_args(argv)
    if args.list:
        for record, _, env, what in PLAN:
            print(f"{record:48s} {what}  env={env or ''}")
        print(f"kill_at_operation_limit_py310*.json  {KILL[3]} (1 to {MAX_KILL_RUNS} runs, until both stop paths are seen)")
        return 0
    if args.max_usd <= 0:
        print("refusing to spend: pass --max-usd (the owner's seal cap, less what the new runs used)")
        return 2
    (ROOT / OUT).mkdir(parents=True, exist_ok=True)
    spent = 0.0
    for record, argv_, env, what in PLAN:
        if spent >= args.max_usd:
            print(f"STOP: ${spent:.4f} reached the ${args.max_usd} cap before {record}")
            return 3
        print(f"-> {record}: {what}", flush=True)
        ok, cost, _ = _run(record, argv_, env)
        spent += cost
        print(f"   ok={ok} cost ${cost:.4f} total ${spent:.4f}", flush=True)
        if not ok:
            print(f"STOP: {record} did not pass; nothing further is run")
            return 1
    vias = set()
    for n in range(MAX_KILL_RUNS):
        record = KILL[0].format(n="" if n == 0 else f"_extra{n}")
        print(f"-> {record}: {KILL[3]}", flush=True)
        ok, cost, rec = _run(record, KILL[1], KILL[2])
        spent += cost
        vias.add(rec.get("via"))
        print(f"   ok={ok} via={rec.get('via')} cost ${cost:.4f} total ${spent:.4f}", flush=True)
        if not ok:
            print(f"STOP: {record} did not pass")
            return 1
        if {"server_result_timed_out", "client_wait_timeout"} <= vias:
            break
    else:
        print(f"STOP: both stop paths not seen in {MAX_KILL_RUNS} runs ({sorted(map(str, vias))})")
        return 1
    print(f"all option-B verification runs passed; ${spent:.4f} (sum of each record's cost)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
