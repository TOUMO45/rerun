"""The smoke launcher really runs here, in real subprocesses (no Nebius): it must pass a still-running program that has produced
output, propagate a program's own exit code and output unchanged, and fail a silent or already-failing one."""

from __future__ import annotations

import subprocess
import sys
import time

import pytest

from app.services import smoke_exec

PY = f'"{sys.executable}"'


def _run(command: str, seconds: int) -> subprocess.CompletedProcess:
    wrapped = smoke_exec.wrap(command, seconds, python=PY)
    return subprocess.run(wrapped, shell=True, capture_output=True, text=True, timeout=seconds + 40)


def test_a_command_that_finishes_keeps_its_own_exit_code_and_output():
    done = _run(f'{PY} -c "print(\'hello\')"', 10)
    assert done.returncode == 0 and "hello" in done.stdout and smoke_exec.ALIVE_MARKER not in done.stdout


def test_a_failing_command_keeps_its_exit_code_and_its_traceback_for_the_classifier():
    failed = _run(f'{PY} -c "import no_such_module_xyz"', 10)
    assert failed.returncode == 1
    assert "ModuleNotFoundError: No module named 'no_such_module_xyz'" in failed.stderr  # forwarded unchanged


def test_a_still_running_command_with_output_passes_and_is_stopped():
    started = time.time()
    done = _run(f'{PY} -c "import time; print(\'epoch 1 started\', flush=True); time.sleep(300)"', 2)
    assert time.time() - started < 30  # it did not wait for the 300 s program
    assert done.returncode == 0
    assert smoke_exec.ALIVE_MARKER in done.stdout and "epoch 1 started" in done.stdout


def test_a_still_running_silent_command_fails_nothing_shows_it_worked():
    done = _run(f'{PY} -c "import time; time.sleep(300)"', 2)
    assert done.returncode == 1 and smoke_exec.FAILED_MARKER in done.stderr and "no output" in done.stderr


def test_a_still_running_command_that_already_printed_a_traceback_fails():
    program = "import sys, time; sys.stderr.write('Traceback (most recent call last):\\n  boom\\n'); sys.stderr.flush(); time.sleep(300)"
    done = _run(f'{PY} -c "{program}"', 2)
    assert done.returncode == 1
    assert smoke_exec.FAILED_MARKER in done.stderr and "already printed a Python traceback" in done.stderr


def test_the_command_is_passed_unchanged_even_with_quotes_and_operators():
    done = _run(f'{PY} -c "print(\'a b\')" && {PY} -c "print(\'second\')"', 10)
    assert done.returncode == 0 and "a b" in done.stdout and "second" in done.stdout


def test_the_execution_record_says_what_a_pass_means():
    assert smoke_exec.execution_record(60, 0, f"{smoke_exec.ALIVE_MARKER}: x", "") == {"mode": "smoke", "seconds": 60, "outcome": "alive_at_limit"}
    assert smoke_exec.execution_record(60, 0, "done", "")["outcome"] == "exited"
    assert smoke_exec.execution_record(60, 1, "", f"{smoke_exec.FAILED_MARKER}: silent")["outcome"] == "failed_while_running"
    assert smoke_exec.execution_record(60, None, "", "")["outcome"] == "not_completed"


@pytest.mark.skipif(sys.platform == "win32", reason="the sandbox is Linux; process-group kill is POSIX")
def test_no_child_process_is_left_running_after_the_limit():
    marker = "rerun_smoke_leak_probe_7f3a"
    _run(f'{PY} -c "import time; print(1, flush=True); time.sleep(300)  # {marker}"', 2)
    left = subprocess.run(["pgrep", "-f", marker], capture_output=True, text=True).stdout.strip()
    assert left == ""


def test_the_launcher_is_valid_python_3_6_syntax():
    """The oldest sandbox image is python:3.6-slim; the launcher must parse there (no walrus, no f-strings, no 3.7+ APIs)."""
    import ast

    ast.parse(smoke_exec._LAUNCHER, feature_version=(3, 6))  # noqa: SLF001


def test_the_orchestrator_wraps_only_repair_reexecutions_never_the_baseline(tmp_path):
    """The as-published run stays comparable with CONTROL; every re-execution after a repair runs under the smoke limit and
    says so in its record."""
    import json

    from app.services.cost_guard import CostGuard
    from app.services.intake import RepoIntake
    from app.services.orchestrator import PipelineDeps, run_pipeline
    from app.services.sandbox import SandboxRunResult, StepResult
    from app.services.time_machine import LockResult

    (tmp_path / "train.py").write_text("import yaml\nprint('x')\n", encoding="utf-8")
    calls = []

    class Chat:
        def __init__(self, replies):
            self.replies = [json.dumps(r) for r in replies]

        def chat_completion(self, **kw):
            return self.replies.pop(0)

    def sandbox(**kw):
        calls.append(kw["execute_command"])
        if len(calls) == 1:
            return SandboxRunResult(steps=(StepResult("python train.py", 1, "", "ModuleNotFoundError: No module named 'yaml'", 1.0, 0.0),))
        return SandboxRunResult(steps=(StepResult("x", 0, smoke_exec.ALIVE_MARKER + ": still running", "", 1.0, 0.0),))

    add = {"env_delta": [{"op": "add", "package": "pyyaml", "version": None, "justification": "yaml is imported",
                          "evidence": "ModuleNotFoundError: No module named 'yaml'"}], "explanation": "add yaml"}
    deps = PipelineDeps(
        recon_client=Chat([{"entrypoint": "train.py", "confidence": 0.9}]), recon_model="r", repair_client=Chat([add]), repair_model="p",
        adjudicator_client=None, adjudicator_model=None, sandbox_api_key="k", sandbox_wall_clock_seconds=100,
        sandbox_runner=sandbox, lock_compiler=lambda *a: LockResult(False, (), (), (), "", "disabled"),
    )
    intake = RepoIntake(tmp_path, "a" * 40, {}, frozenset(), (), ("train.py",), None)
    result = run_pipeline(repo_url="https://example.com/r", commit_sha="a" * 40, workdir=tmp_path, intake_result=intake, deps=deps,
                          cost_guard=CostGuard(daily_cost_ceiling_usd=100), run_id="s")
    assert result.verdict == "RUNS_AFTER_REPAIR", result.full_log
    assert "base64" not in calls[0] and "train.py" in calls[0]  # the as-published baseline run is not wrapped
    assert "base64" in calls[1] and "import base64" in calls[1]  # the repair re-execution ran under the launcher
    # harness-v1.4.3-rc (D-42): the record also names the command the smoke run executed (the plan's, before the launcher)
    assert result.attempts[-1].execution == {"mode": "smoke", "seconds": smoke_exec.DEFAULT_SECONDS, "outcome": "alive_at_limit", "command": "python train.py"}
    assert result.certificate()["diffs"][-1]["execution"]["outcome"] == "alive_at_limit"  # and the passport carries it
