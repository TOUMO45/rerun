"""harness-v1.8 (T11): a documented command with a pipe runs under `bash -o pipefail`; the certificate keeps the documented text.

Evidence: TEST #18 aam-at/adversary_critic (now DEV-CONTAMINATED), `python generate_script.py --train=True | bash`: the script died at its first import, `bash` at the end of
the pipe read nothing and exited 0, the entry was RUNS_CLEAN for a run that did nothing (`reports/dev/TEST_RESULT.md`, the D-46 audit). Offline: a scripted sandbox that records
the command it was handed; the real classifier and orchestrator run. On the harness-v1.7.2 code the sandbox is handed the documented text unchanged."""

from __future__ import annotations

import subprocess

import pytest

from app.services import command_shell
from app.services.cost_guard import CostGuard
from app.services.intake import RepoIntake
from app.services.orchestrator import PipelineDeps, run_pipeline
from app.services.sandbox import SandboxRunResult, StepResult
from app.services.time_machine import LockResult
from test_d24_build_essential import _Chat

DOCUMENTED = "python generate_script.py --train=True | bash"


@pytest.mark.parametrize("command, piped", [
    ("python generate_script.py --train=True | bash", True),
    ("python a.py | sh -s", True),
    ("gen | python3 -", True),
    ("gen | FOO=1 /bin/bash", True),
    ("gen | bash && echo ok", True),
    # harness-v1.8 review, finding 3: a pipe that ends in head / tee / grep / wc keeps the documented semantics (pipefail would turn a producer's SIGPIPE into a failure)
    ("python x.py 2>&1 | tee run.log", False),
    ("cat a | grep b | wc -l", False),
    ("yes | head -1", False),
    ("python a.py || true", False),
    ("python a.py 'x|y'", False),
    ('python a.py --expr="a|b"', False),
    ("python a.py > log.txt", False),
    ("python a.py && python b.py", False),
    ("python 'unterminated", False),
])
def test_only_a_pipe_into_an_interpreter_counts(command, piped):
    assert command_shell.pipes_into_interpreter(command) is piped
    assert (command_shell.with_pipefail(command) != command) is piped
    assert command_shell.with_pipefail(command_shell.with_pipefail(command)) == command_shell.with_pipefail(command)  # idempotent


def test_the_wrapped_command_is_one_quoted_argument():
    command = "python x.py | bash -c 'echo a b'"
    assert command_shell.with_pipefail(command) == "bash -o pipefail -c " + command_shell.shlex.quote(command)
    assert command_shell.shlex.split(command_shell.with_pipefail(command)) == ["bash", "-o", "pipefail", "-c", command]  # one argument, quotes intact


def _run(tmp_path, command, results):
    (tmp_path / "generate_script.py").write_text("import decorator\n", encoding="utf-8", newline="\n")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True, capture_output=True)
    for k, v in (("core.autocrlf", "false"), ("user.email", "t@e.st"), ("user.name", "t")):
        subprocess.run(["git", "config", k, v], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-q", "-m", "x"], cwd=tmp_path, check=True, capture_output=True)
    handed: list[str] = []
    queue = list(results)

    def runner(**kw):
        handed.append(kw["execute_command"])
        return queue.pop(0)

    deps = PipelineDeps(
        recon_client=_Chat([{"entrypoint": "generate_script.py", "confidence": 0.9}]), recon_model="r", repair_client=_Chat([]), repair_model="p",
        adjudicator_client=None, adjudicator_model=None, sandbox_api_key="k", sandbox_wall_clock_seconds=100, sandbox_runner=runner,
        tavily_client=None, smoke_seconds=0, max_attempts=1, lock_compiler=lambda *a: LockResult(True, ("decorator==4.4.2",), ("decorator",)),
    )
    intake = RepoIntake(tmp_path, "a" * 40, {}, frozenset(), (), ("generate_script.py",), None)
    result = run_pipeline(repo_url="https://example.com/r", commit_sha="a" * 40, workdir=tmp_path, intake_result=intake, deps=deps,
                          cost_guard=CostGuard(daily_cost_ceiling_usd=100), run_id="t11", documented_command=command)
    return result, handed


def _step(command, code, stdout="", stderr=""):
    return SandboxRunResult(steps=(StepResult(command, code, stdout, stderr, 1.0, 0.01),))


def test_a_piped_documented_command_is_handed_to_the_sandbox_under_pipefail_and_the_certificate_keeps_the_documented_text(tmp_path):
    ok = _step("x", 0, "done\n")
    result, handed = _run(tmp_path, DOCUMENTED, [ok])
    assert handed == [f"bash -o pipefail -c {command_shell.shlex.quote(DOCUMENTED)}"]
    cert = result.certificate()
    assert cert["build_plan"]["execute_command"] == DOCUMENTED and cert["baseline"]["execute_command"] == DOCUMENTED  # as documented
    assert cert["baseline"]["pipefail"] is True and command_shell.PIPEFAIL_NOTE in cert["build_plan"]["notes"]


def test_the_pipeline_status_is_now_the_first_failure(tmp_path):
    """With pipefail the sandbox's exit status for the TEST #18 run is the python script's 1, not bash's 0: the baseline FAILS and the loop sees the import error."""
    boom = _step("x", 1, "", "Traceback (most recent call last):\n  File \"generate_script.py\", line 8, in <module>\n    import decorator\nModuleNotFoundError: No module named 'decorator'\n")
    fixed = _step("x", 0, "ran\n")
    result, handed = _run(tmp_path, DOCUMENTED, [boom, fixed])
    assert result.baseline["result"] == "FAILS" and result.baseline["exit_code"] == 1
    assert result.first_repo_error == "ModuleNotFoundError: No module named 'decorator'"
    assert all(h.startswith("bash -o pipefail -c ") for h in handed)  # every re-execution runs the same way


def test_a_command_without_a_pipe_is_handed_over_exactly_as_before(tmp_path):
    result, handed = _run(tmp_path, "python generate_script.py --train=True > out.txt", [_step("x", 0, "ok\n")])
    assert handed == ["python generate_script.py --train=True > out.txt"]
    assert "pipefail" not in result.certificate()["baseline"]
