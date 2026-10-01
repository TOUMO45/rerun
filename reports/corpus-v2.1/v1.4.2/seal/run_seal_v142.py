"""Seal of harness-v1.4.2 (option B over CHANGED files only; owner, chat 2026-10-01): live checks of what v1.4.2 changed in the sandbox-touching files, through the
REAL runner (`sandbox.run_build_and_execute`).

    backend/.venv/Scripts/python.exe reports/corpus-v2.1/v1.4.2/seal/run_seal_v142.py                        # PLAN: what would run, ESTIMATED cost
    backend/.venv/Scripts/python.exe reports/corpus-v2.1/v1.4.2/seal/run_seal_v142.py --go --max-usd X        # spends money (owner's cap)

What changed among the sandbox-touching files (scripts/run_corpus_v1_batch.py SANDBOX_TOUCHING_FILES): `runner_hooks.py` only (the extended CPU shim, the evidence
command and its parser). `sandbox.py`, `sandbox_limits.py`, `runner_env.py` and `smoke_exec.py` are byte-identical to harness-v1.4.1 (and to v1.4.0), so every v1.4.1
entry whose code files are all unchanged stays valid (scripts/write_seal_verification_v142.py carries them over only if the blobs match). Re-verified or new, each a live run:

  Run 1  the hooks on a kept image (every entry that lists runner_hooks.py is re-verified).
         A ready image, B one branch run (the measured branch-run cost for the seal -> gate rule), C the exit hook and the CPU shim installed on A's image,
         W0 a bare `raise SystemExit(1)` with the hook alone (stderr empty), W1 the same through the exit wrapper (the raise site), W2 the wrapper on python:3.6-slim.
  Run 2  the evidence command (D-38 / D-40), the first time anything reads the sandbox's own limits.
         E0 a calm run (exit 3) with the evidence block: what the sandbox shows (MemTotal, nproc, cgroup files, kernel, dmesg); the exit status is kept.
         E1a a process that SIGKILLs itself: exit 137, the shell says Killed, the evidence shows the kill.
         E1b informational: a process that allocates memory in 64 MiB chunks until it is killed or reaches 48 GiB, printing the total as it goes, with the evidence
             block: how much memory a process can hold in this sandbox before the kernel stops it (the figure no document gives). Bounded by a 25 s operation clock.

The CPU shim's `.cuda()` / `.to` / `torch.device` paths are checked against REAL torch offline in a throwaway venv (RERUN_REAL_TORCH_PYTHON,
backend/tests/test_v142_cpu_shim.py), not here: a torch install would cost more than the rest of the seal.

Every operation's record goes to runs/sandbox_verification/v1.4.2-seal/. Never runs without --go and --max-usd (at most $0.49: the owner's $25.00 ledger ceiling
minus the ledger $18.5083 minus the $6.00 gate cap; the owner's seal bound is $1.00). A timeout is recorded with its measured completed cost and the killed step's
estimate at $0.0152/s (D-27). An operation starts only while 1.5 x its estimate is left under the cap.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "backend"))
OUT = ROOT / "runs" / "sandbox_verification" / "v1.4.2-seal"
MAX_SEAL_USD = 0.49  # $25.00 ceiling - $18.5083 ledger - $6.00 gate cap = $0.4917; the owner's own seal bound is $1.00
HEADROOM_FACTOR = 1.5
PIP_STEP = "pip install six==1.16.0"
OOM_OP_SECONDS = 25.0
OOM_CAP_MB = 48 * 1024

BARE_EXIT = b"import sys\n\n\ndef main():\n    print('working')\n    raise SystemExit(1)\n\n\nmain()\n"
CALM_EXIT = b"import sys\nprint('calm run')\nsys.exit(3)\n"
SELF_KILL = b"import os, signal\nprint('about to be killed', flush=True)\nos.kill(os.getpid(), signal.SIGKILL)\n"
ALLOCATE = (b"import sys\nchunks = []\nmb = 0\nwhile mb < %d:\n    chunks.append(bytearray(b'\\x01') * (64 * 1024 * 1024))\n    mb += 64\n"
            b"    print('ALLOCATED_MB', mb, flush=True)\nprint('NO_KILL_UP_TO_MB', mb, flush=True)\n" % OOM_CAP_MB)

# ESTIMATED per-operation costs from API-reported records of the harness-v1.4.1 seal and gate (the source named for each): plan only.
ESTIMATES = {
    "A": (0.0124, "run1_A_ready_image.json of the v1.4.1 seal, $0.012413 API-reported"),
    "B": (0.0011, "run1_B_branch_run.json of the v1.4.1 seal, $0.000628 API-reported (rounded up)"),
    "C": (0.0012, "run1_C_runner_hooks.json of the v1.4.1 seal, $0.001165 API-reported"),
    "W0": (0.0010, "run1_W0 of the v1.4.1 seal, $0.000901 API-reported"),
    "W1": (0.0010, "run1_W1 of the v1.4.1 seal, $0.000924 API-reported"),
    "W2": (0.0014, "run1_W2 of the v1.4.1 seal, $0.001338 API-reported"),
    "E0": (0.0020, "a run on a ready image plus a few reads: as C"),
    "E1a": (0.0020, "as E0"),
    "E1b": (0.2600, "ESTIMATED upper bound: the 25 s operation clock at the sandbox's observed $0.0103 per billed second (D-36); a kill ends it sooner"),
}
RUNS = {1: ("A", "B", "C", "W0", "W1", "W2"), 2: ("E0", "E1a", "E1b")}


def planned_operations(runs: list[int]) -> list[dict]:
    ops = [{"run": r, "op": k} for r in runs for k in RUNS[r]]
    for op in ops:
        op["estimated_usd"], op["source"] = ESTIMATES[op["op"]]
    return ops


def _code_blobs() -> dict:
    """The git blob of each sandbox-touching file this seal verifies, taken when the record is written: scripts/write_seal_verification_v142.py refuses a record whose
    blob is not the file's blob now (the independent review: an edit of runner_hooks.py between the live seal and the writer would otherwise be accepted)."""
    sys.path.insert(0, str(ROOT / "scripts"))
    from write_seal_verification import SB, blob

    return {f: blob(f) for f in (SB, "backend/app/services/runner_hooks.py")}


def _record(name: str, **fields) -> dict:
    OUT.mkdir(parents=True, exist_ok=True)
    doc = {"written_at": datetime.now(timezone.utc).isoformat(), "harness": "harness-v1.4.2-rc", "code_blobs": _code_blobs(), **fields}
    (OUT / f"{name}.json").write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8", newline="\n")
    return doc


def _result_doc(result) -> dict:
    return {
        "run_id": result.sandbox_id,
        "cost_usd": result.total_cost_usd,
        "steps": [{"phase": s.phase, "command": s.command[:160], "exit": s.exit_code, "seconds": s.elapsed_seconds, "cost_usd": s.cost_usd}
                  for s in (*result.rerun_steps, *result.steps)],
        "layers": [{"setup_commands": len(ops), "image": image} for ops, image in result.layers],
        "branch_from_image": result.branch_from_image,
        "result_image": result.result_image,
        "stdout": result.final.stdout[-1500:],
        "stderr": result.final.stderr[-3000:],
    }


def _spend_guard(max_usd: float):
    from app.services.cost_guard import CostGuard

    return CostGuard(daily_cost_ceiling_usd=max_usd)


def _seconds(guard, name: str, fixed: float = 120.0) -> float:
    """The wall clock of one operation: a FIXED figure (never derived from the guard's worst-case rate: D-29). An operation starts only while what the seal cap
    has left is at least HEADROOM_FACTOR times its ESTIMATE; otherwise nothing more is started."""
    needed = HEADROOM_FACTOR * ESTIMATES[name][0]
    if guard.remaining_today_usd < needed:
        raise SystemExit(f"STOP: ${guard.remaining_today_usd:.4f} left under the seal cap, below {HEADROOM_FACTOR} x the ${ESTIMATES[name][0]:.4f} estimate of "
                         f"{name}; it is not started")
    return fixed


def _guarded(name: str, guard, call, **extra):
    """Run one sandbox operation; a timeout is RECORDED (completed steps at their measured cost, the killed step at the D-27 rate) instead of escaping with its
    cost (D-29). Returns (result, None), or (None, the SandboxTimeoutError) after writing the record."""
    from app.services import sandbox

    try:
        return call(), None
    except sandbox.SandboxTimeoutError as exc:
        recorded = guard.record_killed_operation(exc.completed_cost_usd, exc.killed_seconds, note=f"{name}: {exc.command[:80]}")
        _record(name, ok=False, killed=True, **extra, message=str(exc)[:400], measured_completed_usd=exc.completed_cost_usd,
                killed_seconds=exc.killed_seconds, estimated_killed_usd=recorded - exc.completed_cost_usd, cost_usd=recorded,
                cost_tag="API-REPORTED completed steps + ESTIMATED killed step (computed at $0.0152/s)",
                run_id=exc.sandbox_id or next((image for _, image in reversed(getattr(exc, "layers", ()) or ())), None),
                layers=[{"setup_commands": len(ops), "image": image} for ops, image in getattr(exc, "layers", ())])
        print(f"{name}: KILLED at its wall clock; ${recorded:.4f} recorded ({exc.completed_cost_usd:.4f} API-reported completed steps)")
        return None, exc


def run_1(api_key: str, project_id: str, guard) -> list[dict]:
    from app.services import runner_hooks, sandbox

    docs = []

    def op(name, base="python:3.10-slim", install=(PIP_STEP,), **kw):
        result = sandbox.run_build_and_execute(api_key=api_key, project_id=project_id, base_image=base, install_commands=list(install),
                                               wall_clock_seconds=_seconds(guard, name), **kw)
        guard.record_spend(result.total_cost_usd)
        return result

    a = op("A", execute_command="python3 probe.py", upload_files={"probe.py": b"print('ready')\n"}, checkpoint=sandbox.Checkpoint(keep_layers=True))
    env_ops, env_image = a.layers[-1]
    docs.append(_record("run1_A_ready_image", ok=a.succeeded and "ready" in a.final.stdout and len(a.layers) >= 2, **_result_doc(a)))
    b = op("B", execute_command="python3 probe.py",
           checkpoint=sandbox.Checkpoint(start_image=env_image, start_ops=env_ops, branch_files=(("probe.py", b"print('branch')\n", 0o644),)))
    docs.append(_record("run1_B_branch_run", ok=b.succeeded and "branch" in b.final.stdout and not b.ran_setup,
                        measured_branch_run_usd=b.total_cost_usd, **_result_doc(b)))

    probe = b"import sys\n\ndef leave():\n    sys.exit(3)\n\nleave()\n"
    both = (runner_hooks.install_command(runner_hooks.EXIT_HOOK), runner_hooks.install_command(runner_hooks.CPU_SHIM))
    c = op("C", execute_command="python3 exit_probe.py", runner_extras=both,
           checkpoint=sandbox.Checkpoint(start_image=env_image, start_ops=env_ops, branch_files=(("exit_probe.py", probe, 0o644),)))
    hook_ok = c.final.exit_code == 3 and "RERUN_EXIT_HOOK: sys.exit(3) was called" in c.final.stderr and "in leave" in c.final.stderr
    docs.append(_record("run1_C_runner_hooks", ok=hook_ok and tuple(c.ran_setup) == both, **_result_doc(c)))

    hook = (runner_hooks.install_command(runner_hooks.EXIT_HOOK),)
    w0 = op("W0", execute_command="python3 bare.py", runner_extras=hook,
            checkpoint=sandbox.Checkpoint(start_image=env_image, start_ops=env_ops, branch_files=(("bare.py", BARE_EXIT, 0o644),)))
    docs.append(_record("run1_W0_hook_alone_sees_nothing", ok=w0.final.exit_code == 1 and w0.final.stderr.strip() == "" and "working" in w0.final.stdout
                        and tuple(w0.ran_setup) == hook, **_result_doc(w0)))
    wrapped, why = runner_hooks.wrap_entry_command("python3 bare.py")
    assert wrapped is not None, why
    w1 = op("W1", execute_command=wrapped, runner_extras=hook,
            checkpoint=sandbox.Checkpoint(start_image=env_image, start_ops=env_ops, branch_files=(("bare.py", BARE_EXIT, 0o644),)))
    w1_ok = (w1.final.exit_code == 1 and "RERUN_EXIT_WRAPPER: the entry script raised SystemExit(1)" in w1.final.stderr
             and "raise SystemExit(1)" in w1.final.stderr and "in main" in w1.final.stderr and w1.final.stderr.rstrip().endswith("SystemExit: 1"))
    docs.append(_record("run1_W1_wrapper_prints_the_raise_site", ok=w1_ok, **_result_doc(w1)))
    w2 = op("W2", base="python:3.6-slim", install=("true",), execute_command=wrapped, upload_files={"bare.py": BARE_EXIT})
    w2_ok = w2.final.exit_code == 1 and "RERUN_EXIT_WRAPPER" in w2.final.stderr and "raise SystemExit(1)" in w2.final.stderr
    docs.append(_record("run1_W2_wrapper_on_python36", ok=w2_ok, **_result_doc(w2)))
    return docs


def run_2(api_key: str, project_id: str, guard) -> list[dict]:
    from app.services import runner_hooks, sandbox

    docs = []

    def op(key: str, label: str, script: bytes, seconds: float | None = None, **extra):
        clock = _seconds(guard, key)  # the refusal to start without headroom
        return _guarded(f"run2_{label}", guard, lambda: sandbox.run_build_and_execute(
            api_key=api_key, project_id=project_id, base_image="python:3.10-slim", install_commands=["true"],
            execute_command=runner_hooks.evidence_command("python3 probe.py"), wall_clock_seconds=seconds or clock,
            upload_files={"probe.py": script}), **extra)

    e0, _ = op("E0", "E0_calm_run_with_evidence", CALM_EXIT)
    if e0 is None:
        return docs
    guard.record_spend(e0.total_cost_usd)
    ev0 = runner_hooks.parse_evidence(e0.final.stderr, e0.final.stdout)
    docs.append(_record("run2_E0_calm_run_with_evidence", ok=e0.final.exit_code == 3 and ev0 is not None and ev0["exit_status"] == 3
                        and bool(ev0["mem_total_kb"]) and not runner_hooks.kill_evidenced(ev0),
                        evidence=ev0, limit_quote=runner_hooks.limit_quote(ev0), **_result_doc(e0)))

    e1a, _ = op("E1a", "E1a_self_sigkill_with_evidence", SELF_KILL)
    if e1a is None:
        return docs
    guard.record_spend(e1a.total_cost_usd)
    ev1 = runner_hooks.parse_evidence(e1a.final.stderr, e1a.final.stdout)
    killed = e1a.final.exit_code == 137 and ev1 is not None and runner_hooks.kill_evidenced(ev1)
    docs.append(_record("run2_E1a_self_sigkill_with_evidence", ok=killed and "Killed" in e1a.final.stderr and classify_137(e1a),
                        evidence=ev1, limit_quote=runner_hooks.limit_quote(ev1), **_result_doc(e1a)))

    e1b, _ = op("E1b", "E1b_allocate_until_killed_with_evidence", ALLOCATE, seconds=OOM_OP_SECONDS, informational=True)
    if e1b is None:
        return docs  # stopped by the operation clock: _guarded wrote the record (informational): the VM held more than it could allocate in the clock
    guard.record_spend(e1b.total_cost_usd)
    ev2 = runner_hooks.parse_evidence(e1b.final.stderr, e1b.final.stdout)
    allocated = [int(x) for x in re.findall(r"ALLOCATED_MB (\d+)", e1b.final.stdout)]
    docs.append(_record("run2_E1b_allocate_until_killed_with_evidence", ok=ev2 is not None, informational=True,
                        allocated_mb_before_the_end=max(allocated, default=0), reached_cap="NO_KILL_UP_TO_MB" in e1b.final.stdout,
                        killed=e1b.final.exit_code == 137, kill_evidenced=runner_hooks.kill_evidenced(ev2), evidence=ev2,
                        limit_quote=runner_hooks.limit_quote(ev2), **_result_doc(e1b)))
    return docs


def classify_137(result) -> bool:
    """The harness's own classifier agrees: a SIGKILL is RESOURCE_LIMIT."""
    from app.services import classifier

    return classifier.classify(result.final.exit_code, result.final.stderr, result.final.stdout).code == "RESOURCE_LIMIT"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", type=int, action="append", choices=(1, 2))
    ap.add_argument("--go", action="store_true", help="actually run (spends money; needs the owner's seal cap)")
    ap.add_argument("--max-usd", type=float, help="the seal cap (at most $0.49)")
    args = ap.parse_args(argv)
    runs = sorted(set(args.run or [1, 2]))
    ops = planned_operations(runs)
    print("v1.4.2 seal plan (ESTIMATED costs, sources listed):")
    for op in ops:
        print(f"  run {op['run']} op {op['op']}: ~${op['estimated_usd']:.4f}  ({op['source']})")
    print(f"  total ~${sum(o['estimated_usd'] for o in ops):.4f} [ESTIMATED]")
    if not args.go:
        print("PLAN ONLY: nothing was run and nothing was spent (pass --go and --max-usd to run).")
        return 0
    if args.max_usd is None or args.max_usd <= 0 or args.max_usd > MAX_SEAL_USD + 1e-9:
        print(f"REFUSED: --max-usd is required and must be at most ${MAX_SEAL_USD:.2f} (the $25.00 ceiling minus the ledger minus the gate cap)", file=sys.stderr)
        return 2
    from app.config import get_settings

    settings = get_settings()
    guard = _spend_guard(args.max_usd)
    docs = []
    for number, runner in ((1, run_1), (2, run_2)):
        if number in runs:
            docs += runner(settings.nebius_api_key, settings.nebius_project_id, guard)
    print(json.dumps([{k: d.get(k) for k in ("ok", "run_id", "cost_usd", "result_image")} for d in docs], indent=2))
    required = [d for d in docs if not d.get("informational")]
    print(f"seal spend ${guard.spent_today_usd:.4f} [sum of operation costs: API-reported, plus the estimate of any killed step]; all required ok: "
          f"{all(d['ok'] for d in required)}")
    return 0 if all(d["ok"] for d in required) else 1


if __name__ == "__main__":
    raise SystemExit(main())
