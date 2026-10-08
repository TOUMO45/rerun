"""Seal of harness-v1.10: live checks of what the behavioural checks changed in the sandbox-touching files.

    backend/.venv/Scripts/python.exe reports/corpus-v2.1/v1.10/seal/run_seal_v110.py                                    # PLAN: what would run, ESTIMATED cost
    backend/.venv/Scripts/pythonw.exe reports/corpus-v2.1/v1.10/seal/run_seal_v110.py --go --max-usd 1.50 --log-file F  # live (launch_seal.cmd, Task Scheduler)

harness-v1.10 changes `smoke_exec.py` (the launcher can set environment variables for the command it runs, and only for it) and adds a sixth sandbox-touching file, `behaviour.py` (a tracer
installed as a `.pth` hook like the runner hooks, active only under RERUN_BEHAVIOUR=1). `sandbox.py`, `sandbox_limits.py`, `runner_env.py` and `runner_hooks.py` are byte-identical to
harness-v1.8.0. Stages, in order:

  v140   the v1.4.3 seal's `v140` stage, unchanged, against the new smoke_exec.py: it re-verifies `checkpoint_real_entry` (corpus-v2 entry 7 built as a checkpoint, reopened, patch applied,
         executed under the smoke launcher), the entry that lists smoke_exec.py among the kept-image paths.
  smoke  the six smoke-launcher records of the v1.4.3 seal's `final` stage (alive / exits ok / fails / silent on Python 3.10, alive / fails on 3.6), through scripts/verify_*.py with the same
         argv: it re-verifies `smoke_launcher`.
  v110   the new paths, on python:3.6-slim, 3.7-slim and 3.10-slim, through the real runner (`sandbox.run_build_and_execute`), each with the tracer installed by its real installer
         (behaviour.install_command, a `.pth` hook) and the command run under the smoke launcher with RERUN_BEHAVIOUR=1:
           T1 exited:  a program that ends by itself writes one report (entry_main true, the failure site's lines hit, no finding);
           T2 alive:   a program still running at the launcher's limit is stopped with SIGTERM and still writes its report (lines > 0);
           T3 cheat:   a program whose patch added `sys.exit(0)` at the top: exit code 0, the report names the exit and its line, EXIT_FROM_ADDED_LINE and FAILURE_SITE_NOT_EXECUTED are found;
           T4 inert:   the same program as T1 with the tracer installed and the variable NOT set: exit 0, no report line;
           T5 forged:  a repository that prints a report line with the wrong nonce: the line is taken out of the text and counted as nothing.

Every record goes to runs/sandbox_verification/v1.10-seal/<stage>/; SEAL_RUN.json says which commit and which blobs of the six files the stages ran against. Reuses the v1.4.3 seal driver
(precondition against the release-candidate tag, a stage that fails stops the seal, SEAL_RUN.json after every stage). Never runs without --go and --max-usd.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
_spec = importlib.util.spec_from_file_location("run_seal_v143", ROOT / "reports" / "corpus-v2.1" / "v1.4.3" / "seal" / "run_seal_v143.py")
base = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(base)

OUT = ROOT / "runs" / "sandbox_verification" / "v1.10-seal"
RC_TAG = os.environ.get("RERUN_V110_RC_TAG", "harness-v1.10.0-rc")
MAX_SEAL_USD = 1.50  # the owner's seal bound since v1.4.3
SANDBOX_FILES = (*base.SANDBOX_FILES, "backend/app/services/behaviour.py")
SMOKE_RECORDS = ("smoke_alive_py310.json", "smoke_exits_ok_py310.json", "smoke_fails_py310.json", "smoke_silent_py310.json", "smoke_alive_py36.json", "smoke_fails_py36.json")
IMAGES = ("python:3.6-slim", "python:3.7-slim", "python:3.10-slim")
V110_ESTIMATES = {"T1_T5_per_image": 0.02}  # ESTIMATED: five small operations on each of three images (the v1.4.2 seal's small operations cost $0.001-0.012)
ROUND = 12  # a line of the tracer's own report is at most a few hundred bytes

TRAIN = ("import sys\nimport lib\n\ndef main():\n    total = lib.work(3)\n    print('total', total)\n\nif __name__ == '__main__':\n    main()\n    sys.exit(0)\n")
LIB = "def work(n):\n    acc = 0\n    for i in range(n):\n        acc += step(i)\n    return acc\n\ndef step(i):\n    return i * 2\n"
LOOP = ("import sys\nimport time\nimport lib\n\ndef main():\n    print('total', lib.work(3), flush=True)\n    while True:\n        print('tick', flush=True)\n        time.sleep(0.2)\n\n"
        "if __name__ == '__main__':\n    main()\n    sys.exit(0)\n")
FAILURE = 'Traceback (most recent call last):\n  File "/w/train.py", line 5, in main\n    total = lib.work(3)\n  File "/w/lib.py", line 4, in work\n    acc += step(i)\nTypeError: boom\n'


def run_smoke(api_key, project_id, guard, blobs_now):
    """The six smoke-launcher records of the v1.4.3 seal's `final` stage, each in its own process through scripts/verify_*.py, written to runs/sandbox_verification/v1.10-seal/smoke/."""
    mod = base._load("scripts/run_seal_verification_v140.py", "run_seal_verification_v140")
    mod.OUT = (OUT / "smoke").relative_to(ROOT).as_posix()
    (ROOT / mod.OUT).mkdir(parents=True, exist_ok=True)
    plan = [p for p in mod.PLAN if p[0] in SMOKE_RECORDS]
    assert sorted(p[0] for p in plan) == sorted(SMOKE_RECORDS), [p[0] for p in plan]
    docs = []
    for record, argv, env, what in plan:
        done = ROOT / mod.OUT / record
        if done.is_file() and json.loads(done.read_text(encoding="utf-8")).get("ok") is True:
            print(f"-> {record}: already passed in an earlier invocation, not run again", flush=True)
            docs.append({"ok": True, "cost_usd": 0.0, "run_id": json.loads(done.read_text(encoding="utf-8")).get("run_id"), "skipped": True})
            continue
        expected = base.previous_cost(f"runs/sandbox_verification/v1.4.3-seal/final/{record}")
        if guard.remaining_today_usd < expected:
            raise SystemExit(f"STOP: ${guard.remaining_today_usd:.4f} left under the seal cap, below the ${expected:.4f} this check cost in the v1.4.3 seal; {record} is not started")
        print(f"-> {record}: {what}", flush=True)
        ok, cost, rec = mod._run(record, argv, env)
        guard.record_spend(cost)
        docs.append({"ok": ok, "cost_usd": cost, "run_id": rec.get("run_id")})
        print(f"   ok={ok} cost ${cost:.4f}", flush=True)
        if not ok:
            return docs
    return docs


def _tracer_run(api_key, project_id, guard, image, *, files, entry_cmd, plan, window, traced_env, seconds):
    from app.services import behaviour, sandbox, smoke_exec

    wrapped = smoke_exec.wrap(entry_cmd, window, env=behaviour.TRACE_ENV if traced_env else None)
    result = sandbox.run_build_and_execute(api_key=api_key, project_id=project_id, base_image=image, install_commands=["true"], wall_clock_seconds=seconds,
                                           upload_files={name: text.encode("utf-8") for name, text in files.items()}, runner_extras=(behaviour.install_command(plan.spec_b64),),
                                           execute_command=wrapped)
    guard.record_spend(result.total_cost_usd)
    return result


def run_v110(api_key, project_id, guard, blobs_now):
    from app.services import behaviour

    docs = []
    for image in IMAGES:
        tag = image.split(":")[1].split("-")[0].replace(".", "")
        old = {"train.py": TRAIN, "lib.py": LIB}
        repo_files = set(old)
        plan = behaviour.plan_trace(command="python3 train.py", failure_text=FAILURE, old_sources=old, new_sources=old, repo_files=repo_files)

        # T1 exited
        t1 = _tracer_run(api_key, project_id, guard, image, files=old, entry_cmd="python3 train.py", plan=plan, window=30, traced_env=True, seconds=120)
        clean, reports = behaviour.split_report(t1.final.stderr, plan.nonce)
        report = behaviour.entry_report(reports)
        findings = behaviour.trace_findings(report, plan) if report else None
        ok1 = (t1.final.exit_code == 0 and "total 6" in t1.final.stdout and report is not None and report["entry_main"] is True and report["sites"].get("lib.py:4", 0) >= 1
               and findings == [] and "RERUN_BEHAVIOUR" not in clean)
        docs.append(base._record("v110", f"T1_exited_{tag}", blobs_now, ok=ok1, image=image, report=report, findings=[f.as_dict() for f in findings or []], **base._result_doc(t1)))
        if not ok1:
            return docs

        # T2 alive at the launcher's limit: SIGTERM, and the report still arrives
        loop_files = {"loop.py": LOOP, "lib.py": LIB}
        plan2 = behaviour.plan_trace(command="python3 loop.py", failure_text=FAILURE.replace("train.py", "loop.py"), old_sources=loop_files, new_sources=loop_files,
                                     repo_files=set(loop_files))
        t2 = _tracer_run(api_key, project_id, guard, image, files=loop_files, entry_cmd="python3 loop.py", plan=plan2, window=8, traced_env=True, seconds=120)
        clean2, reports2 = behaviour.split_report(t2.final.stderr, plan2.nonce)
        report2 = behaviour.entry_report(reports2)
        ok2 = (t2.final.exit_code == 0 and "RERUN_SMOKE_ALIVE" in t2.final.stdout and report2 is not None and report2["lines"] > 0 and report2["entry_main"] is True
               and report2["sites"].get("lib.py:4", 0) >= 1 and "RERUN_BEHAVIOUR" not in clean2)
        docs.append(base._record("v110", f"T2_alive_sigterm_{tag}", blobs_now, ok=ok2, image=image, report=report2, **base._result_doc(t2)))
        if not ok2:
            return docs

        # T3 a patch that added `sys.exit(0)` at the top of main
        cheat = {"train.py": TRAIN.replace("def main():\n    total", "def main():\n    sys.exit(0)\n    total"), "lib.py": LIB}
        plan3 = behaviour.plan_trace(command="python3 train.py", failure_text=FAILURE, old_sources=old, new_sources=cheat, repo_files=repo_files)
        t3 = _tracer_run(api_key, project_id, guard, image, files=cheat, entry_cmd="python3 train.py", plan=plan3, window=30, traced_env=True, seconds=120)
        clean3, reports3 = behaviour.split_report(t3.final.stderr, plan3.nonce)
        report3 = behaviour.entry_report(reports3)
        found3 = {f.reason for f in behaviour.trace_findings(report3, plan3)} if report3 else set()
        ok3 = t3.final.exit_code == 0 and report3 is not None and {behaviour.EXIT_FROM_ADDED_LINE, behaviour.FAILURE_SITE_NOT_EXECUTED} <= found3
        docs.append(base._record("v110", f"T3_cheat_exit_from_an_added_line_{tag}", blobs_now, ok=ok3, image=image, report=report3, findings=sorted(found3), **base._result_doc(t3)))
        if not ok3:
            return docs

        # T4 inert: the tracer is installed, the variable is not set
        t4 = _tracer_run(api_key, project_id, guard, image, files=old, entry_cmd="python3 train.py", plan=plan, window=30, traced_env=False, seconds=120)
        ok4 = t4.final.exit_code == 0 and "total 6" in t4.final.stdout and "RERUN_BEHAVIOUR" not in t4.final.stderr
        docs.append(base._record("v110", f"T4_inert_without_the_variable_{tag}", blobs_now, ok=ok4, image=image, **base._result_doc(t4)))
        if not ok4:
            return docs

        # T5 forged: a repository prints a report line with the wrong nonce
        forged_src = TRAIN.replace("def main():\n    total", "def main():\n    print('RERUN_BEHAVIOUR {\"nonce\": \"guess\", \"entry_main\": true, \"lines\": 99, \"sites\": {\"lib.py:4\": 7}}', file=sys.stderr)\n    total")
        forged = {"train.py": forged_src, "lib.py": LIB}
        plan5 = behaviour.plan_trace(command="python3 train.py", failure_text=FAILURE, old_sources=old, new_sources=forged, repo_files=repo_files)
        t5 = _tracer_run(api_key, project_id, guard, image, files=forged, entry_cmd="python3 train.py", plan=plan5, window=30, traced_env=True, seconds=120)
        clean5, reports5 = behaviour.split_report(t5.final.stderr, plan5.nonce)
        report5 = behaviour.entry_report(reports5)
        ok5 = (t5.final.exit_code == 0 and report5 is not None and report5["processes"] == 1 and report5["lines"] < 99 and report5["sites"].get("lib.py:4", 0) < 7
               and "guess" not in clean5)
        docs.append(base._record("v110", f"T5_forged_line_is_not_a_report_{tag}", blobs_now, ok=ok5, image=image, report=report5, **base._result_doc(t5)))
        if not ok5:
            return docs
    return docs


def configure() -> None:
    base.OUT = OUT
    base.RC_TAG = RC_TAG
    base.MAX_SEAL_USD = MAX_SEAL_USD
    base.SANDBOX_FILES = SANDBOX_FILES
    base.STAGES = ("v140", "smoke", "v110")
    base.RUNNERS = {"v140": base.run_v140, "smoke": run_smoke, "v110": run_v110}

    def plan():
        rows = []
        for name in ("run1_A_ready_image", "run1_B_branch_run", "run1_C_runner_hooks", "run1_D_reopen_kept_image", "run2_E_entry07_checkpoint", "run2_F_reopen_apply_execute"):
            rows.append({"stage": "v140", "op": name, "usd": base.previous_cost(f"runs/sandbox_verification/v1.4.0-seal/{name}.json"), "source": "v1.4.0 seal record, API-reported"})
        rows += [{"stage": "smoke", "op": rec, "usd": base.previous_cost(f"runs/sandbox_verification/v1.4.3-seal/final/{rec}"), "source": "v1.4.3 seal record, API-reported"} for rec in SMOKE_RECORDS]
        rows += [{"stage": "v110", "op": f"T1-T5 on {image}", "usd": V110_ESTIMATES["T1_T5_per_image"], "source": "ESTIMATED"} for image in IMAGES]
        return rows

    base.plan = plan


configure()


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--log-file" in argv:
        i = argv.index("--log-file")
        sys.stdout = sys.stderr = open(argv[i + 1], "a", encoding="utf-8", buffering=1)
        del argv[i:i + 2]
    return base.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
