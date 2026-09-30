"""Run the live seal verification of harness-v1.3.3: every sandbox-touching path, in a real Nebius sandbox, sequentially,
under a hard spend cap. Writes the records to runs/sandbox_verification/final-v1.3.3/ (the files scripts/write_seal_verification.py reads).

  backend/.venv/Scripts/python.exe scripts/run_seal_verification_v133.py --list                  # print the plan, run nothing
  backend/.venv/Scripts/python.exe scripts/run_seal_verification_v133.py --max-usd 2.5           # run it (needs approval: spends money)

Why all of it: the seal rule refuses a verification made against a code file whose git blob has since changed. v1.3.3 changed
sandbox.py (SandboxTimeoutError), runner_env.py (NumPy cap) and added smoke_exec.py, so every path that lists those files is
verified again, plus the three new paths (kill at the operation limit, the smoke launcher, the NumPy-capped torch install).
The cap is enforced between runs from each record's own cost (a record without one is charged a conservative $0.30), and a run
that fails stops the sequence.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = str(ROOT / "backend" / ".venv" / "Scripts" / "python.exe") if os.name == "nt" else str(ROOT / "backend" / ".venv" / "bin" / "python")
OUT = "runs/sandbox_verification/final-v1.3.3"
TORCH = "scripts/verify_runner_torch.py"
DL = "scripts/verify_download_route.py"
V133 = "scripts/verify_v133_paths.py"

# (record file, argv after the interpreter, extra environment, what it verifies)
PLAN = [
    ("download_git_entry2_py310.json", [DL, "https://github.com/DeformableFriends/NeuralTracking", "015256369a94a56b0e478fd100326b9aa97ec9a7", "python:3.10-slim"], {}, "download route (git)"),
    ("download_tarball_fallback_py36.json", [DL, "https://github.com/octocat/Hello-World", "7fd1a60b01f91b314f59955a4e4d4e80d8edf11d", "python:3.6-slim"], {}, "download route (tarball fallback)"),
    ("upload_archive_exec_bit_py36.json", ["scripts/verify_upload_route.py", "python:3.6-slim"], {}, "archive upload + exec-bit verify"),
    ("torch_py36_pin1.10.2.json", [TORCH, "python:3.6-slim", "{out}", "pin", "torch==1.10.2"], {}, "runner torch, py3.6, old pin"),
    ("torch_py38_pin1.12.1.json", [TORCH, "python:3.8-slim", "{out}", "pin", "torch==1.12.1"], {}, "runner torch, py3.8, old pin"),
    ("torch_py310_pin1.12.1.json", [TORCH, "python:3.10-slim", "{out}", "pin", "torch==1.12.1"], {}, "runner torch, py3.10, old pin"),
    ("torch_py310_imports_torchvision.json", [TORCH, "python:3.10-slim", "{out}", "imports", "torchvision.transforms"], {}, "matched torch family"),
    ("phase_runner_setup_failure_py310.json", [TORCH, "python:3.10-slim", "{out}", "pin", "torch==0.0.1"], {"VERIFY_EXPECT": "runner_setup_failure"}, "phase tag on a failing runner op"),
    ("patchelf_flag_absent_incompat_py310.json", [TORCH, "python:3.10-slim", "{out}", "pin", "torch==1.12.1"], {"VERIFY_EXPECT": "incompat", "VERIFY_PATCHELF_PIN": "patchelf==0.17.2.1"}, "flag-absent SANDBOX_INCOMPAT"),
    # --- new in v1.3.3 ---
    ("torch_py39_pin1.8.1_numpy_cap.json", [TORCH, "python:3.9-slim", "{out}", "pin", "torch==1.8.1", "numpy"], {}, "NumPy<2 with torch<2.3 (entry 11): import torch must work"),
    ("kill_at_operation_limit_py310.json", [V133, "kill", "python:3.10-slim", "{out}"], {}, "a step is killed at the operation limit"),
    ("smoke_alive_py310.json", [V133, "smoke", "alive", "python:3.10-slim", "{out}"], {}, "smoke launcher: still running with output -> pass"),
    ("smoke_exits_ok_py310.json", [V133, "smoke", "exits_ok", "python:3.10-slim", "{out}"], {}, "smoke launcher: finishes by itself"),
    ("smoke_fails_py310.json", [V133, "smoke", "fails", "python:3.10-slim", "{out}"], {}, "smoke launcher: failure forwarded unchanged"),
    ("smoke_silent_py310.json", [V133, "smoke", "silent", "python:3.10-slim", "{out}"], {}, "smoke launcher: silent -> fail"),
    ("smoke_alive_py36.json", [V133, "smoke", "alive", "python:3.6-slim", "{out}"], {}, "smoke launcher on Python 3.6"),
    ("smoke_fails_py36.json", [V133, "smoke", "fails", "python:3.6-slim", "{out}"], {}, "smoke launcher failure on Python 3.6"),
]
CONSERVATIVE_COST = 0.30


def command(record: str, argv: list[str]) -> list[str]:
    out = f"{OUT}/{record}"
    resolved = [a.replace("{out}", out) for a in argv]
    if argv[0] in ("scripts/verify_upload_route.py",) or argv[0] == DL:
        resolved.append(out)  # these two take the output path last
    return [PY, *resolved]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--max-usd", type=float, default=0.0)
    args = ap.parse_args()
    if args.list:
        for record, argv, env, what in PLAN:
            print(f"{record:48s} {what}  env={env or ''}")
        print(f"{len(PLAN)} live runs; estimated total $1.5-2.0 (previous matrix of 9: $1.07)")
        return 0
    if args.max_usd <= 0:
        print("refusing to spend: pass --max-usd (and have the operator's approval)")
        return 2
    (ROOT / OUT).mkdir(parents=True, exist_ok=True)
    spent = 0.0
    for record, argv, env, what in PLAN:
        if spent >= args.max_usd:
            print(f"STOP: ${spent:.2f} reached the ${args.max_usd} cap before {record}")
            return 3
        done = ROOT / OUT / record
        print(f"-> {record}: {what}", flush=True)
        proc = subprocess.run(command(record, argv), cwd=ROOT, env={**os.environ, **env, "PYTHONIOENCODING": "utf-8"},
                              capture_output=True, text=True, timeout=1500)
        cost = CONSERVATIVE_COST
        if done.is_file():
            rec = json.loads(done.read_text(encoding="utf-8"))
            value = rec.get("cost_usd", rec.get("cost"))
            cost = float(value) if isinstance(value, (int, float)) else CONSERVATIVE_COST
            ok = rec.get("ok") is True
        else:
            ok = False
        spent += cost
        print(f"   ok={ok} cost~${cost:.3f} total~${spent:.3f}", flush=True)
        if not ok:
            print(proc.stdout[-800:], proc.stderr[-800:])
            print(f"STOP: {record} did not pass; nothing further is run")
            return 1
    print(f"all {len(PLAN)} verification runs passed; ~${spent:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
