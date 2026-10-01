"""Seal of harness-v1.4.1 (option B over CHANGED files only; owner, chat 2026-10-01): live checks of what v1.4.1 changed in or around the
sandbox-touching files, through the REAL runner (`sandbox.run_build_and_execute`).

    backend/.venv/Scripts/python.exe reports/corpus-v2.1/v1.4.1/seal/run_seal_v141.py                        # PLAN: what would run, ESTIMATED cost
    backend/.venv/Scripts/python.exe reports/corpus-v2.1/v1.4.1/seal/run_seal_v141.py --go --max-usd X        # spends money (owner's cap)

What changed among the sandbox-touching files (scripts/run_corpus_v1_batch.py SANDBOX_TOUCHING_FILES): `runner_hooks.py` only (the exit
wrapper, D-35). `sandbox.py`, `sandbox_limits.py`, `runner_env.py` and `smoke_exec.py` are byte-identical to harness-v1.4.0, so the
v1.4.0 verifications whose code files are all unchanged stay valid (scripts/write_seal_verification_v141.py carries them over only if the
blobs match). Re-verified or new, each a live Nebius run:

  Run 1  hooks and the exit wrapper on a kept image.
         A  a ready image on python:3.10-slim (one pip step), every layer kept.
         B  ONE branch run from A's deepest layer (overlay one file, run it): the measured branch-run cost the seal -> gate rule compares with
            its $0.15 limit (the same operation as the v1.4.0 seal's B, $0.00054618).
         C  the exit-site hook and the CPU shim installed on A's image (runner_hooks.py changed, so v1.4.0's check is re-done); the hook
            prints the exit site of `sys.exit(3)`.
         W0 the bare `raise SystemExit(1)` script with the hook installed: exit 1 and NOTHING on stderr (the gap, D-35).
         W1 the same script through the exit wrapper: the traceback of the raise on stderr, the same exit code.
         W2 the wrapper on python:3.6-slim (the oldest sandbox image): the wrapper source is 3.6-compatible and prints the raise site.
  Run 2  the additive apt layer (D-34, orchestrator.apt_layer_command) on a kept image.
         L1 python:3.10-slim, one pip step kept; `gcc` is not there.
         L2 the layer `export DEBIAN_FRONTEND=noninteractive && apt-get update && apt-get install -y build-essential` on L1's deepest layer:
            only the layer runs (the pip step is NOT run again) and `gcc --version` works.
  Run 3  resume after a budget-limited stop (D-31).
         K1 an operation whose second setup step is stopped at the operation limit: the layer built before it is kept and reported.
         K2 a new operation reopens that layer by id, runs the rest and the command: the kept layer of a KILLED operation is usable.

Every operation's record goes to runs/sandbox_verification/v1.4.1-seal/ (run_id = the image id the operation ran on, `ok`, steps with
seconds and cost, layers kept). Never runs without --go and --max-usd (at most $1.00, the owner's seal bound). A timeout is recorded with
its measured completed cost and the killed step's estimate (D-29: no cost is lost with the exception).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "backend"))
OUT = ROOT / "runs" / "sandbox_verification" / "v1.4.1-seal"
MAX_SEAL_USD = 1.00  # the owner's seal bound (chat, 2026-10-01); the actual cap is --max-usd and may only be lower
PIP_STEP = "pip install six==1.16.0"
KILL_OP_SECONDS = 30.0
SLEEP_STEP = "sleep 120"

BARE_EXIT = b"import sys\n\n\ndef main():\n    print('working')\n    raise SystemExit(1)\n\n\nmain()\n"

# ESTIMATED per-operation costs from API-reported records of the harness-v1.4.0 seal and gate (the source named for each): plan only.
ESTIMATES = {
    "A": (0.0120, "run1_A_ready_image.json of the v1.4.0 seal, $0.0120 API-reported"),
    "B": (0.0011, "run1_B_branch_run.json of the v1.4.0 seal, $0.00054618 API-reported (the dearest v1.4.0 smoke run on a ready image: $0.0011)"),
    "C": (0.0012, "run1_C_runner_hooks.json of the v1.4.0 seal, $0.0012 API-reported"),
    "W0": (0.0012, "a run on a ready image: as C"),
    "W1": (0.0012, "a run on a ready image: as C"),
    "W2": (0.0030, "python:3.6-slim smoke runs of the v1.4.0 seal, about $0.0011 each, plus the image import: ESTIMATED"),
    "L1": (0.0120, "as A"),
    "L2": (0.1000, "the apt-get step of #8 in the v1.4.0 gate, operation 11: $0.0775 API-reported for build-essential (7.7 s), plus the extract/overlay steps"),
    "K1": (0.2200, "ESTIMATED: the killed step runs about 20 s of the 30 s operation limit at the sandbox's observed $0.0103 per billed second "
                   "(D-36: 21 steps >= 3 s, median $0.01013/s); a kill may bill less"),
    "K2": (0.0120, "as A (one reopen, the rest of the setup, one run)"),
}
RUNS = {1: ("A", "B", "C", "W0", "W1", "W2"), 2: ("L1", "L2"), 3: ("K1", "K2")}


def planned_operations(runs: list[int]) -> list[dict]:
    ops = [{"run": r, "op": k} for r in runs for k in RUNS[r]]
    for op in ops:
        op["estimated_usd"], op["source"] = ESTIMATES[op["op"]]
    return ops


def _record(name: str, **fields) -> dict:
    OUT.mkdir(parents=True, exist_ok=True)
    doc = {"written_at": datetime.now(timezone.utc).isoformat(), "harness": "harness-v1.4.1-rc", **fields}
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
        "stderr": result.final.stderr[-1500:],
    }


def _spend_guard(max_usd: float):
    from app.services.cost_guard import CostGuard

    return CostGuard(daily_cost_ceiling_usd=max_usd)


def _guarded(name: str, guard, call):
    """Run one sandbox operation; a timeout is RECORDED (completed steps at their measured cost, the killed step at the guard's bound)
    instead of escaping with its cost (the defect D-29). Returns (result, None), or (None, the SandboxTimeoutError) after writing the record."""
    from app.services import sandbox

    try:
        return call(), None
    except sandbox.SandboxTimeoutError as exc:
        recorded = guard.record_killed_operation(exc.completed_cost_usd, exc.killed_seconds, note=f"{name}: {exc.command[:80]}")
        _record(name, ok=False, killed=True, message=str(exc)[:400], measured_completed_usd=exc.completed_cost_usd,
                killed_seconds=exc.killed_seconds, estimated_killed_usd=recorded - exc.completed_cost_usd, cost_usd=recorded,
                cost_tag="API-REPORTED completed steps + ESTIMATED killed step",
                run_id=exc.sandbox_id or next((image for _, image in reversed(getattr(exc, "layers", ()) or ())), None),
                layers=[{"setup_commands": len(ops), "image": image} for ops, image in getattr(exc, "layers", ())])
        print(f"{name}: KILLED at its wall clock; ${recorded:.4f} recorded ({exc.completed_cost_usd:.4f} API-reported completed steps)")
        return None, exc


def _seconds(guard, name: str, fixed: float = 120.0) -> float:
    """The wall clock of one operation: a FIXED figure (never derived from the guard's worst-case rate: that was D-29). An operation is
    started only while what the seal cap has left is at least three times its ESTIMATE; otherwise nothing more is started."""
    needed = 3 * ESTIMATES[name][0]
    if guard.remaining_today_usd < needed:
        raise SystemExit(f"STOP: ${guard.remaining_today_usd:.4f} left under the seal cap, below 3 x the ${ESTIMATES[name][0]:.4f} estimate of "
                         f"{name}; it is not started")
    return fixed


def run_1(api_key: str, project_id: str, guard) -> list[dict]:
    from app.services import runner_hooks, sandbox

    docs = []

    def op(name, base="python:3.10-slim", install=(PIP_STEP,), **kw):
        result = sandbox.run_build_and_execute(api_key=api_key, project_id=project_id, base_image=base, install_commands=list(install),
                                               wall_clock_seconds=_seconds(guard, name), **kw)
        guard.record_spend(result.total_cost_usd)
        return result

    a = op("A", execute_command="python3 probe.py", upload_files={"probe.py": b"print('ready')\n"},
           checkpoint=sandbox.Checkpoint(keep_layers=True))
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
    from app.services import sandbox
    from app.services.orchestrator import apt_layer_command

    layer = apt_layer_command(["build-essential"])
    which_gcc = "python3 -c \"import shutil; print(shutil.which('gcc'))\""
    l1 = sandbox.run_build_and_execute(api_key=api_key, project_id=project_id, base_image="python:3.10-slim", install_commands=[PIP_STEP],
                                       execute_command=which_gcc, wall_clock_seconds=_seconds(guard, "L1"),
                                       upload_files={"probe.py": b"print('ready')\n"}, checkpoint=sandbox.Checkpoint(keep_layers=True))
    guard.record_spend(l1.total_cost_usd)
    env_ops, env_image = l1.layers[-1]
    docs = [_record("run2_L1_image_without_a_compiler", ok=l1.succeeded and l1.final.stdout.strip() == "None" and len(l1.layers) >= 2,
                    **_result_doc(l1))]
    l2, _ = _guarded("run2_L2_additive_apt_layer", guard, lambda: sandbox.run_build_and_execute(
        api_key=api_key, project_id=project_id, base_image="python:3.10-slim", install_commands=[PIP_STEP, layer],
        execute_command="gcc --version", wall_clock_seconds=_seconds(guard, "L2", fixed=180.0),
        checkpoint=sandbox.Checkpoint(start_image=env_image, start_ops=env_ops, keep_layers=True)))
    if l2 is None:
        return docs
    guard.record_spend(l2.total_cost_usd)
    ran_only_the_layer = tuple(l2.ran_setup) == (layer,) and not any("pip install" in s.command for s in l2.steps)
    docs.append(_record("run2_L2_additive_apt_layer", ok=l2.succeeded and "gcc" in l2.final.stdout.lower() and ran_only_the_layer
                        and l2.branch_from_image == env_image, start_setup_commands=len(env_ops), **_result_doc(l2)))
    return docs


def run_3(api_key: str, project_id: str, guard, op_seconds: float = KILL_OP_SECONDS) -> list[dict]:
    from app.services import sandbox

    steps = [PIP_STEP, SLEEP_STEP]
    _seconds(guard, "K1")  # the refusal to start; K1's own clock is the operation limit it is stopped at
    spent_before = guard.spent_today_usd
    k1, killed = _guarded("run3_K1_operation_stopped_at_its_limit", guard, lambda: sandbox.run_build_and_execute(
        api_key=api_key, project_id=project_id, base_image="python:3.10-slim", install_commands=steps, execute_command="python3 probe.py",
        wall_clock_seconds=op_seconds, upload_files={"probe.py": b"print('after the resume')\n"},
        checkpoint=sandbox.Checkpoint(keep_layers=True)))
    if killed is None:
        # the step was not stopped: the check did not test anything
        guard.record_spend(k1.total_cost_usd)
        return [_record("run3_K1_operation_stopped_at_its_limit", ok=False, message="the sleep step was not stopped at the limit", **_result_doc(k1))]
    layers = list(getattr(killed, "layers", ()))
    # the record written by _guarded says ok=False (a killed operation); this check passes when the layer before the killed step was kept
    pip_layers = [(ops, image) for ops, image in layers if tuple(ops) == (PIP_STEP,)]
    doc = _record("run3_K1_operation_stopped_at_its_limit", ok=bool(pip_layers), killed=True, killed_command=killed.command[:80],
                  killed_seconds=killed.killed_seconds, measured_completed_usd=killed.completed_cost_usd,
                  cost_usd=guard.spent_today_usd - spent_before, run_id=killed.sandbox_id or pip_layers[-1][1], via=getattr(killed, "via", "") or "client_wait_timeout",
                  cost_tag="API-REPORTED completed steps + ESTIMATED killed step",
                  layers=[{"setup_commands": len(ops), "image": image} for ops, image in layers],
                  note="ok = the layer built before the stopped step is kept and reported")
    if not pip_layers:
        return [doc]
    env_ops, env_image = pip_layers[-1]
    k2, _ = _guarded("run3_K2_resume_from_the_kept_layer", guard, lambda: sandbox.run_build_and_execute(
        api_key=api_key, project_id=project_id, base_image="python:3.10-slim", install_commands=[PIP_STEP, "true"],
        execute_command="python3 probe.py", wall_clock_seconds=_seconds(guard, "K2"),
        checkpoint=sandbox.Checkpoint(start_image=env_image, start_ops=env_ops, branch_files=(("probe.py", b"print('after the resume')\n", 0o644),))))
    if k2 is None:
        return [doc]
    guard.record_spend(k2.total_cost_usd)
    resumed = (k2.branch_from_image == env_image and tuple(k2.ran_setup) == ("true",) and k2.succeeded and "after the resume" in k2.final.stdout)
    return [doc, _record("run3_K2_resume_from_the_kept_layer", ok=resumed, start_setup_commands=len(env_ops), **_result_doc(k2))]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", type=int, action="append", choices=(1, 2, 3))
    ap.add_argument("--go", action="store_true", help="actually run (spends money; needs the owner's seal cap)")
    ap.add_argument("--max-usd", type=float, help="the seal cap the owner wrote in chat")
    ap.add_argument("--kill-seconds", type=float, default=KILL_OP_SECONDS, help="run 3: the operation limit K1 is stopped at")
    args = ap.parse_args(argv)
    runs = sorted(set(args.run or [1, 2, 3]))
    ops = planned_operations(runs)
    print("v1.4.1 seal plan (ESTIMATED costs, sources listed):")
    for op in ops:
        print(f"  run {op['run']} op {op['op']}: ~${op['estimated_usd']:.4f}  ({op['source']})")
    print(f"  total ~${sum(o['estimated_usd'] for o in ops):.4f} [ESTIMATED]")
    if not args.go:
        print("PLAN ONLY: nothing was run and nothing was spent (pass --go and --max-usd to run).")
        return 0
    if args.max_usd is None or args.max_usd <= 0 or args.max_usd > MAX_SEAL_USD:
        print(f"REFUSED: --max-usd is required and must be at most ${MAX_SEAL_USD:.2f} (the owner's seal bound)", file=sys.stderr)
        return 2
    from app.config import get_settings

    settings = get_settings()
    guard = _spend_guard(args.max_usd)
    docs = []
    for number, runner in ((1, run_1), (2, run_2), (3, run_3)):
        if number in runs:
            docs += runner(settings.nebius_api_key, settings.nebius_project_id, guard, *((args.kill_seconds,) if number == 3 else ()))
    print(json.dumps([{k: d.get(k) for k in ("ok", "run_id", "cost_usd", "result_image")} for d in docs], indent=2))
    print(f"seal spend ${guard.spent_today_usd:.4f} [sum of operation costs: API-reported, plus the estimate of any killed step]; "
          f"all ok: {all(d['ok'] for d in docs)}")
    return 0 if all(d["ok"] for d in docs) else 1


if __name__ == "__main__":
    raise SystemExit(main())
