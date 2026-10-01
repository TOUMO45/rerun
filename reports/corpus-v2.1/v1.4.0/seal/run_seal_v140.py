"""v1.4.0 seal design (directive Step 1, "so Step 2 can set its cap from a measurement"): at most three live runs, each a short chain of
sandbox operations through the REAL harness-v1.4.0-rc runner (`sandbox.run_build_and_execute` with `checkpoint=`).

    backend/.venv/Scripts/python.exe reports/corpus-v2.1/v1.4.0/seal/run_seal_v140.py                      # PLAN: what would run, ESTIMATED cost
    backend/.venv/Scripts/python.exe reports/corpus-v2.1/v1.4.0/seal/run_seal_v140.py --run 1 --go --max-usd X  # spends money (owner's cap)

  Run 1, ready image / branch / kept image. A: build a small ready image on python:3.10-slim (one pip step), keeping every layer.
         B: ONE branch run from it (overlay one file, run it): the measured branch-run cost R the gate cap is set from; its result image
            is kept. C: the runner hooks installed on top of the same image (exit-site hook + CPU shim) and an exit probe: the live check
            that the hook prints the exit site (the hook code is sandbox-touching). D: after `--wait-seconds`, reopen B's kept image and
            run it again: proves a kept image survives and can be reopened; its cost is the reopen cost.
            Whether a KEPT image is billed while it is kept is not visible in any operation's cost: the record lists every kept image id
            with timestamps, so the owner can match them against the account's billing page.
  Run 2, entry #07's recorded chain on a checkpoint. E: the last environment harness-v1.3.4 built for corpus-v2 entry 7 (python 3.8,
            its era lock and the apt packages its repairs added, from the record's certificate build plan) built fresh as a
            checkpoint, the documented command smoke-run.
            F: "reopen + apply + execute": a branch from E's environment image with a one-file overlay and the smoke-run command; F's
            cost is a full repair operation on a real entry under v1.4.0.
  Run 3, only if run 1 or 2 is ambiguous: `--run 3 --repeat 1|2` repeats it once.

Every operation's record goes to runs/sandbox_verification/v1.4.0-seal/ (run_id = the image id the operation ran on, `ok`, steps with
their seconds and cost, layers kept, branch_from_image, result_image). This script never runs without --go and --max-usd; the seal cap
is the owner's figure, written in chat first. It does not write seal_verification.json (see the report: the seal rule also asks for
the harness-v1.3.4 verifications to be repeated against the changed sandbox.py).
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "backend"))
OUT = ROOT / "runs" / "sandbox_verification" / "v1.4.0-seal"
ENTRY_07 = ROOT / "runs" / "corpus_v2_batch" / "harness-v1.3.4" / "smoke" / "07_albertometelli__pfqi.json"
MAX_SEAL_USD = 1.50  # the owner's proposed upper bound for the seal; the actual cap is --max-usd and may only be lower
SMOKE_SECONDS = 60

# ESTIMATED per-operation costs, from MEASURED records (see each source): used only to print the plan.
ESTIMATES = {
    "A": (0.02, "a pip step on python:3.10-slim: below the smallest torch-free operation of entry 7 in v1.3.4 ($0.0447, events[17])"),
    "B": (0.0011, "the dearest smoke run on a ready image in the v1.3.4 seal (smoke_exits_ok_py310.json, $0.0011)"),
    "C": (0.005, "two small setup steps + one probe on a ready image (ESTIMATED from B)"),
    "D": (0.0011, "one run on a kept image (as B)"),
    "E": (0.2338, "entry 7's v1.3.4 repair-3 operation, the same build plan from scratch ($0.2338, events[54] of that record)"),
    "F": (0.2338, "upper bound: E itself (a branch skips the setup steps E completed)"),
}


def entry07_plan():
    """The last environment harness-v1.3.4 built for entry 7 (the time machine's python 3.8 era lock plus the apt packages its repairs
    added), rebuilt from the committed record's certificate build plan. No network."""
    from app.services import planner

    record = json.loads(ENTRY_07.read_text(encoding="utf-8"))
    bp = record["certificate"]["build_plan"]
    plan = planner.BuildPlan(bp["base_image"], tuple(bp["apt_install"]), tuple(bp["install_commands"]), bp["execute_command"])
    return plan, record["corpus_entry"]


def planned_operations(runs: list[int]) -> list[dict]:
    ops = []
    if 1 in runs:
        ops += [{"run": 1, "op": k} for k in "ABCD"]
    if 2 in runs:
        ops += [{"run": 2, "op": k} for k in "EF"]
    for op in ops:
        op["estimated_usd"], op["source"] = ESTIMATES[op["op"]]
    return ops


def _record(name: str, **fields) -> dict:
    OUT.mkdir(parents=True, exist_ok=True)
    doc = {"written_at": datetime.now(timezone.utc).isoformat(), "harness": "harness-v1.4.0-rc", **fields}
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


def run_1(api_key: str, project_id: str, guard, wait_seconds: int) -> list[dict]:
    from app.services import runner_hooks, sandbox

    docs = []

    def op(name, **kw):
        seconds = min(300.0, guard.operation_seconds_budget())
        if seconds < 30:
            raise SystemExit(f"STOP: the seal cap leaves {seconds:.0f}s of sandbox time; {name} not started")
        result = sandbox.run_build_and_execute(api_key=api_key, project_id=project_id, base_image="python:3.10-slim",
                                               install_commands=["pip install six==1.16.0"], wall_clock_seconds=seconds, **kw)
        guard.record_spend(result.total_cost_usd)
        return result

    a = op("A", execute_command="python3 probe.py", upload_files={"probe.py": b"print('ready')\n"},
           checkpoint=sandbox.Checkpoint(keep_layers=True))
    env_ops, env_image = a.layers[-1]
    docs.append(_record("run1_A_ready_image", ok=a.succeeded and "ready" in a.final.stdout and len(a.layers) >= 2, **_result_doc(a)))
    b = op("B", execute_command="python3 probe.py",
           checkpoint=sandbox.Checkpoint(start_image=env_image, start_ops=env_ops, branch_files=(("probe.py", b"print('branch')\n", 0o644),),
                                         keep_result=True))
    docs.append(_record("run1_B_branch_run", ok=b.succeeded and "branch" in b.final.stdout and not b.ran_setup, measured_branch_run_usd=b.total_cost_usd,
                        **_result_doc(b)))
    probe = b"import sys\n\ndef leave():\n    sys.exit(3)\n\nleave()\n"
    hooks = (runner_hooks.install_command(runner_hooks.EXIT_HOOK), runner_hooks.install_command(runner_hooks.CPU_SHIM))
    c = op("C", execute_command="python3 exit_probe.py", runner_extras=hooks,
           checkpoint=sandbox.Checkpoint(start_image=env_image, start_ops=env_ops, branch_files=(("exit_probe.py", probe, 0o644),)))
    hook_ok = c.final.exit_code == 3 and "RERUN_EXIT_HOOK: sys.exit(3) was called" in c.final.stderr and "in leave" in c.final.stderr
    docs.append(_record("run1_C_runner_hooks", ok=hook_ok and tuple(c.ran_setup) == hooks, **_result_doc(c)))
    time.sleep(max(0, wait_seconds))
    d_seconds = min(120.0, guard.operation_seconds_budget())
    d = sandbox.run_build_and_execute(api_key=api_key, project_id=project_id, base_image="python:3.10-slim",
                                      install_commands=["pip install six==1.16.0"], execute_command="python3 probe.py",
                                      wall_clock_seconds=d_seconds,
                                      checkpoint=sandbox.Checkpoint(start_image=b.result_image, start_ops=env_ops, keep_layers=False))
    guard.record_spend(d.total_cost_usd)
    docs.append(_record("run1_D_reopen_kept_image", ok=d.succeeded and "branch" in d.final.stdout, waited_seconds=wait_seconds,
                        kept_images=[*(img for _, img in a.layers), b.result_image],
                        billing_note="kept-image storage is not in any operation's cost; match these ids and times against the billing page",
                        **_result_doc(d)))
    return docs


def _guarded(name: str, guard, call):
    """Run one sandbox operation; a timeout is RECORDED (completed steps at their measured cost, the killed step at the guard's bound)
    instead of escaping with its cost (the defect of run 2's first attempt). Returns the result, or None after writing the record."""
    from app.services import sandbox

    try:
        return call()
    except sandbox.SandboxTimeoutError as exc:
        recorded = guard.record_killed_operation(exc.completed_cost_usd, exc.killed_seconds, note=f"{name}: {exc.command[:80]}")
        _record(name, ok=False, killed=True, message=str(exc)[:400], measured_completed_usd=exc.completed_cost_usd,
                killed_seconds=exc.killed_seconds, estimated_killed_usd=recorded - exc.completed_cost_usd, cost_usd=recorded,
                cost_tag="MEASURED completed steps + ESTIMATED killed step", run_id=exc.sandbox_id,
                layers=[{"setup_commands": len(ops), "image": image} for ops, image in getattr(exc, "layers", ())])
        print(f"{name}: KILLED at its wall clock; ${recorded:.4f} recorded ({exc.completed_cost_usd:.4f} measured)")
        return None


def run_2(api_key: str, project_id: str, guard, op_seconds: float | None = None, start_image: str | None = None) -> list[dict]:
    """E builds entry 7's recorded environment as a checkpoint (from scratch, or from `start_image`: a kept image that already holds the
    tree and the apt step, e.g. the one the first attempt left), F reopens E's deepest kept image, applies a one-file overlay and runs."""
    from app.services import intake, sandbox, smoke_exec

    plan, entry = entry07_plan()
    steps = plan.as_shell_steps()
    workdir = Path(tempfile.mkdtemp(prefix="rerun_seal_e07_"))
    try:
        intake.clone_repo_at_commit(entry["repo_url"], workdir, entry["commit_sha"])
        files = {p.relative_to(workdir).as_posix(): p for p in workdir.rglob("*") if p.is_file() and ".git" not in p.relative_to(workdir).parts}
        command = smoke_exec.wrap(entry["command"], SMOKE_SECONDS)

        def seconds() -> float:
            return op_seconds if op_seconds else min(600.0, guard.operation_seconds_budget())

        start_ops = tuple(sandbox.setup_commands(steps)[:1]) if start_image else ()
        e = _guarded("run2_E_entry07_checkpoint", guard, lambda: sandbox.run_build_and_execute(
            api_key=api_key, project_id=project_id, base_image=plan.base_image, install_commands=steps, execute_command=command,
            wall_clock_seconds=seconds(), upload_files=None if start_image else files,
            download_source=sandbox.sandbox_limits.DownloadSource.from_repo_url(entry["repo_url"], entry["commit_sha"]),
            checkpoint=sandbox.Checkpoint(start_image=start_image, start_ops=start_ops, keep_layers=True)))
        if e is None:
            return []
        guard.record_spend(e.total_cost_usd)
        # In v1.3.4 this environment never completed (repair 3 ended DEP_NOT_ON_PYPI in the install), so E is judged on what a
        # checkpoint operation must do whatever the repository does: it ran, from the image it was given, and kept every layer it built.
        started_right = e.branch_from_image == start_image if start_image else bool(e.layers) and e.layers[0][0] == ()
        docs = [_record("run2_E_entry07_checkpoint", ok=started_right, start_image=start_image, **_result_doc(e))]
        env_ops, env_image = e.layers[-1] if e.layers else (start_ops, start_image)  # the deepest image E has
        target = sorted(files)[0]
        f = _guarded("run2_F_reopen_apply_execute", guard, lambda: sandbox.run_build_and_execute(
            api_key=api_key, project_id=project_id, base_image=plan.base_image, install_commands=steps, execute_command=command,
            wall_clock_seconds=seconds(),
            checkpoint=sandbox.Checkpoint(start_image=env_image, start_ops=env_ops, branch_files=((target, files[target].read_bytes(), 0o644),))))
        if f is None:
            return docs
        guard.record_spend(f.total_cost_usd)
        same = (f.final.exit_code, f.final.stderr[-300:]) == (e.final.exit_code, e.final.stderr[-300:])
        expected_suffix = tuple(f.setup_commands[len(env_ops):])
        docs.append(_record("run2_F_reopen_apply_execute", ok=f.branch_from_image == env_image and tuple(f.ran_setup) == expected_suffix,
                            same_outcome_as_E=same, start_setup_commands=len(env_ops), measured_branch_operation_usd=f.total_cost_usd,
                            **_result_doc(f)))
        return docs
    finally:
        intake.cleanup_workdir(workdir)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", type=int, action="append", choices=(1, 2, 3))
    ap.add_argument("--repeat", type=int, choices=(1, 2))
    ap.add_argument("--go", action="store_true", help="actually run (spends money; needs the owner's seal cap)")
    ap.add_argument("--max-usd", type=float, help="the seal cap the owner wrote in chat")
    ap.add_argument("--wait-seconds", type=int, default=600, help="run 1: delay before reopening the kept image")
    ap.add_argument("--op-seconds", type=float, help="run 2: fixed wall clock per operation (else derived from the cap at the guard's bound)")
    ap.add_argument("--e-start-image", help="run 2: start E from this kept image (tree + apt step), e.g. the first attempt's")
    args = ap.parse_args(argv)
    runs = sorted(set(args.run or [1, 2]))
    if 3 in runs:
        if args.repeat is None:
            print("REFUSED: run 3 is a repeat of run 1 or 2 (--repeat 1|2), only when that run was ambiguous", file=sys.stderr)
            return 2
        runs = sorted({r for r in runs if r != 3} | {args.repeat})
    ops = planned_operations(runs)
    print("v1.4.0 seal plan (ESTIMATED costs, sources listed):")
    for op in ops:
        print(f"  run {op['run']} op {op['op']}: ~${op['estimated_usd']:.4f}  ({op['source']})")
    print(f"  total ~${sum(o['estimated_usd'] for o in ops):.4f} [ESTIMATED]")
    if 2 in runs:
        plan, entry = entry07_plan()
        print(f"  run 2 environment (the record's certificate build plan): {plan.base_image}, apt {list(plan.apt_install)}, "
              f"{len(plan.as_shell_steps())} setup step(s); "
              f"{entry['repo_url']}@{entry['commit_sha'][:12]}")
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
    if 1 in runs:
        docs += run_1(settings.nebius_api_key, settings.nebius_project_id, guard, args.wait_seconds)
    if 2 in runs:
        docs += run_2(settings.nebius_api_key, settings.nebius_project_id, guard, args.op_seconds, args.e_start_image)
    print(json.dumps([{k: d.get(k) for k in ("ok", "run_id", "cost_usd", "result_image")} for d in docs], indent=2))
    print(f"seal spend ${guard.spent_today_usd:.4f} [MEASURED, sum of operation costs]; all ok: {all(d['ok'] for d in docs)}")
    return 0 if all(d["ok"] for d in docs) else 1


if __name__ == "__main__":
    raise SystemExit(main())
