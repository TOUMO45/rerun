"""harness-v1.3.2: the runner-setup phase invariant (attempt 1, entry 3), phase tagging in the sandbox runner, and the
runner's own failures never reaching the REPO attribution."""

from __future__ import annotations

import datetime
import importlib.util
import json
from pathlib import Path

import pytest

from app.services import classifier, error_chain as ec, runner_env, sandbox
from app.services.orchestrator import is_our_fault, reason_code_of
from app.services.sandbox import SandboxRunResult, StepResult

ROOT = Path(__file__).resolve().parents[2]
ATTEMPT1_ENTRY3 = (ROOT / "runs" / "corpus_v2_batch" / "attempt1_harness-v1.3.1_aborted_4of20" / "control"
                   / "03_autumn9999__vmtl.json")


def _chain_test_module():
    spec = importlib.util.spec_from_file_location("t_chain", Path(__file__).with_name("test_error_chain.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def attr(code, evidence, phase, declared=frozenset()):
    return ec.attribute(code, evidence, declared_deps=frozenset(declared), python_claim=None,
                        base_image="python:3.6-slim", phase=phase)


EVIDENCES = (
    "patchelf: getting info about '--clear-execstack': No such file or directory",
    "ModuleNotFoundError: No module named 'tabulate'",  # undeclared: REPO in a repo phase
    "ModuleNotFoundError: No module named 'torchvision'",
    "FileNotFoundError: [Errno 2] No such file or directory: 'data/x.csv'",
    "SyntaxError: Missing parentheses in call to 'print'",
    "ImportError: libGL.so.1: cannot open shared object file",
    "",
)


@pytest.mark.parametrize("code", classifier.TaxonomyCode.ALL)
@pytest.mark.parametrize("evidence", EVIDENCES)
def test_a_runner_setup_failure_is_never_attributed_to_the_repo(code, evidence):
    assert attr(code, evidence, ec.PHASE_RUNNER_SETUP) in (ec.ENV, ec.PLATFORM, ec.SANDBOX_QUOTA)


def test_the_same_text_in_a_repo_phase_is_still_a_repo_error():
    """The phase is what decides; the text alone is not enough (and repo phases keep their text-based rules)."""
    assert attr("DEP_MISSING", "ModuleNotFoundError: No module named 'tabulate'", ec.PHASE_REPO_RUN) == ec.REPO
    assert attr("DEP_MISSING", "ModuleNotFoundError: No module named 'tabulate'", ec.PHASE_REPO_INSTALL) == ec.REPO
    assert attr("DATA_MISSING", EVIDENCES[0], ec.PHASE_REPO_RUN) == ec.REPO


def test_runner_setup_keeps_platform_and_quota_classes():
    assert attr("SANDBOX_INCOMPAT", "x", ec.PHASE_RUNNER_SETUP) == ec.PLATFORM
    assert attr("SANDBOX_QUOTA", "x", ec.PHASE_RUNNER_SETUP) == ec.SANDBOX_QUOTA


def test_links_carry_their_phase():
    chain = ec.ErrorChain()
    chain.record(0, "DEP_MISSING", "e", ec.ENV, ec.PHASE_RUNNER_SETUP)
    chain.record(1, "DEP_MISSING", "f", ec.REPO)
    assert [l["phase"] for l in chain.as_list()] == ["runner_setup", "repo_run"]


def test_the_incompat_marker_of_the_fix_script_is_classified_as_a_platform_refusal():
    err = "RERUN_SANDBOX_INCOMPAT: patchelf 0.17.2 has no --clear-execstack; cannot make this torch build loadable here"
    assert classifier.classify(98, err).code == "SANDBOX_INCOMPAT"
    assert is_our_fault("RUNNER_SETUP_FAILED")


# --- the real entry-3 log from attempt 1 ------------------------------------------------------------------

def test_attempt1_entry3_regression_is_env_and_indeterminate(tmp_path):
    record = json.loads(ATTEMPT1_ENTRY3.read_text(encoding="utf-8"))
    link = record["result"]["error_chain"][0]
    # what attempt 1 recorded: the runner's failure charged to the repository
    assert (link["class"], link["attribution"]) == ("DATA_MISSING", "REPO")
    error = link["error"]
    assert error.startswith("patchelf: getting info about '--clear-execstack'")
    # the same failure now, arriving from a runner-setup step
    step = StepResult("python -c fix", 1, "", f"Traceback ...\n{error}\n", 1.0, 0.0, phase=ec.PHASE_RUNNER_SETUP)
    result = _chain_test_module()._run(tmp_path, [SandboxRunResult(steps=(step,))])
    assert result.verdict == "INDETERMINATE"
    assert reason_code_of(result.indeterminate_reason) == "RUNNER_SETUP_FAILED" and is_our_fault("RUNNER_SETUP_FAILED")
    assert [(l["attribution"], l["phase"]) for l in result.error_chain] == [("ENV", "runner_setup")]
    assert result.first_repo_error is None and result.attempts == ()


def test_the_same_failure_from_the_repos_own_command_is_still_blocked_as_repo(tmp_path):
    step = StepResult("python gen.py", 1, "", "ModuleNotFoundError: No module named 'tabulate'", 1.0, 0.0)
    result = _chain_test_module()._run(tmp_path, [SandboxRunResult(steps=(step,))], declared=frozenset())
    assert reason_code_of(result.indeterminate_reason) != "RUNNER_SETUP_FAILED" and result.first_repo_error is not None
    assert result.error_chain[0]["attribution"] == "REPO" and result.error_chain[0]["phase"] == "repo_run"


# --- phase tagging in the sandbox runner (fake SDK) -------------------------------------------------------

class _FakeResult:
    def __init__(self, code):
        self.exit_code, self.stdout, self.stderr, self.cost = code, "", "", 0.0
        self.elapsed_time = datetime.timedelta(seconds=1)


class _FakeImage:
    def __init__(self, ledger, fail_on=None, uuid=None):
        self._ledger, self._fail_on, self.uuid = ledger, fail_on, uuid
        self.result, self.exit_code = None, 0

    def run(self, shell, timeout, disposable, preserve_env=False):
        self._ledger.append(shell)
        nxt = _FakeImage(self._ledger, self._fail_on)
        nxt.exit_code = 1 if (self._fail_on is not None and shell.startswith(self._fail_on)) else 0
        nxt.result = _FakeResult(nxt.exit_code)
        return nxt

    def wait(self):
        return self

    def apply_files(self, files):
        return self


class _FakeClient:
    def __init__(self, ledger, fail_on):
        self.images = type("I", (), {"docker": staticmethod(lambda name: _FakeImage(ledger, fail_on))})()


@pytest.fixture
def fake_sdk(monkeypatch):
    ledger: list[str] = []
    state = {"fail_on": None}
    monkeypatch.setattr(sandbox, "ContreeSync", lambda config: _FakeClient(ledger, state["fail_on"]))
    return ledger, state


def test_steps_are_tagged_with_their_phase(fake_sdk):
    ledger, state = fake_sdk
    setup = runner_env.plan_torch_setup(["pip install torch==2.0.0"], None)
    result = sandbox.run_build_and_execute(api_key="k", base_image="python:3.10-slim",
                                           install_commands=["pip install -r r.txt"], execute_command="python t.py",
                                           wall_clock_seconds=60, torch_setup=setup)
    assert [s.phase for s in result.steps] == ["runner_setup", "runner_setup", "repo_install", "repo_run"]
    assert [s.command for s in result.steps] == [setup.install_command, setup.fix_command, "pip install -r r.txt", "python t.py"]


def test_a_failing_runner_op_ends_the_run_with_that_phase_as_the_final_step(fake_sdk):
    ledger, state = fake_sdk
    setup = runner_env.plan_torch_setup(["pip install torch==2.0.0"], None)
    state["fail_on"] = "python -c"  # the exec-stack fix op
    result = sandbox.run_build_and_execute(api_key="k", base_image="python:3.6-slim", install_commands=[],
                                           execute_command="./run.sh", wall_clock_seconds=60, torch_setup=setup)
    assert result.final.phase == "runner_setup" and result.final.exit_code == 1
    assert "./run.sh" not in ledger  # nothing of the repo ran


def test_a_failing_repo_install_is_tagged_repo_install(fake_sdk):
    ledger, state = fake_sdk
    state["fail_on"] = "pip install -r"
    result = sandbox.run_build_and_execute(api_key="k", base_image="python:3.10-slim",
                                           install_commands=["pip install -r r.txt"], execute_command="python t.py",
                                           wall_clock_seconds=60)
    assert result.final.phase == "repo_install"
