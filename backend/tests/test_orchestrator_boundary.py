"""The pipeline's stage exception boundary: every run ends with a verdict.

An unexpected exception is injected into each orchestrator stage in turn
(parametrized). For every stage the run must still return a PipelineResult
with verdict INDETERMINATE, a PIPELINE_ERROR:<stage>:<ExceptionType> reason
code, the traceback recorded, a certificate (prose + verifiable passport),
and every sandbox that was created must have been destroyed.

The base scenario walks through every stage: initial execution fails ->
classifier -> Tavily -> repairer proposes a fix -> tamper gate PASS ->
apply -> re-execute succeeds -> adjudicator -> passport. classifier.py and
tamper_gate.py run for real unless they are the injected stage.
"""

from __future__ import annotations

import difflib
import json
import textwrap
from pathlib import Path

import pytest

from app.services import orchestrator
from app.services.cost_guard import CostGuard
from app.services.intake import RepoIntake
from app.services.orchestrator import PipelineDeps, reason_code_of, run_pipeline
from app.services.passport import verify_certificate
from app.services.sandbox import SandboxRunResult, StepResult

TRAIN_PY = textwrap.dedent(
    """\
    def run():
        x = 1 / 0
        print(x)

    run()
    """
)
FIXED_PY = TRAIN_PY.replace("1 / 0", "1 / 1")


class _Boom(RuntimeError):
    pass


class _FakeChatClient:
    def __init__(self, responses: list[str]):
        self._responses = list(responses)

    def chat_completion(self, **kwargs):
        if not self._responses:
            raise AssertionError("fake chat client ran out of scripted responses")
        return self._responses.pop(0)


class _LifecycleSandboxRunner:
    """Models a real sandbox's lifecycle: create, run, destroy in `finally`
    — the same contract sandbox.run_build_and_execute implements. Can be
    told to blow up mid-execution (after create, before return)."""

    def __init__(self, results: list[SandboxRunResult], explode: bool = False):
        self._results = list(results)
        self.explode = explode
        self.created = 0
        self.destroyed = 0

    def __call__(self, **kwargs):
        self.created += 1
        try:
            if self.explode:
                raise _Boom("injected: sandbox exploded mid-execution")
            return self._results.pop(0)
        finally:
            self.destroyed += 1


class _FakeTavily:
    def search(self, *args, **kwargs):
        return {"results": []}


def _result(exit_code: int, stderr: str = "") -> SandboxRunResult:
    return SandboxRunResult(steps=(StepResult("run", exit_code, "", stderr, 1.0, 0.001),))


def _diff(old: str, new: str) -> str:
    return "".join(
        difflib.unified_diff(
            old.splitlines(keepends=True), new.splitlines(keepends=True), fromfile="a/train.py", tofile="b/train.py"
        )
    )


def _scenario(tmp_path: Path, explode_sandbox: bool = False):
    (tmp_path / "train.py").write_text(TRAIN_PY, encoding="utf-8")
    intake = RepoIntake(
        local_path=tmp_path,
        commit_sha="a" * 40,
        dependency_files={"requirements.txt": "numpy\n"},
        declared_dependencies=frozenset({"numpy"}),
        notebook_paths=(),
        entrypoint_candidates=("train.py",),
        python_version_hint=None,
    )
    recon_client = _FakeChatClient([json.dumps({"entrypoint": "train.py", "confidence": 0.9})])
    repair_client = _FakeChatClient(
        [json.dumps({"diff": _diff(TRAIN_PY, FIXED_PY), "explanation": "fix the division by zero"})]
    )
    runner = _LifecycleSandboxRunner(
        [_result(1, stderr="ZeroDivisionError: division by zero"), _result(0)], explode=explode_sandbox
    )
    deps = PipelineDeps(
        recon_client=recon_client,
        recon_model="recon-model",
        repair_client=repair_client,
        repair_model="repair-model",
        adjudicator_client=None,
        adjudicator_model=None,
        sandbox_api_key="fake",
        sandbox_wall_clock_seconds=60,
        sandbox_runner=runner,
        tavily_client=_FakeTavily(),
    )
    return intake, deps, runner


def _run(tmp_path, intake, deps):
    return run_pipeline(
        repo_url="https://example.com/repo",
        commit_sha="a" * 40,
        workdir=tmp_path,
        intake_result=intake,
        deps=deps,
        cost_guard=CostGuard(daily_cost_ceiling_usd=100),
        run_id="boundary",
    )


def _boom(*args, **kwargs):
    raise _Boom("injected failure")


def test_base_scenario_reaches_every_stage_and_succeeds(tmp_path):
    """Control: without injection the scenario really does walk all the
    stages, so each injection below is actually reached."""
    intake, deps, runner = _scenario(tmp_path)
    result = _run(tmp_path, intake, deps)
    assert result.verdict == "RUNS_AFTER_REPAIR"
    assert result.error_traceback == ""
    assert reason_code_of(result.indeterminate_reason) is None
    assert runner.created == runner.destroyed == 2


def _inject(stage: str, monkeypatch, deps, runner):
    if stage == "intake":
        monkeypatch.setattr(orchestrator, "read_text_capped", _boom)
    elif stage == "recon":
        monkeypatch.setattr(orchestrator.recon, "run_recon", _boom)
    elif stage == "planner":
        monkeypatch.setattr(orchestrator.planner, "build_plan", _boom)
    elif stage == "sandbox":
        runner.explode = True
    elif stage == "classifier":
        monkeypatch.setattr(orchestrator.classifier, "classify", _boom)
    elif stage == "tavily":
        # A non-TavilyError exception: not the handled "search failed" path.
        monkeypatch.setattr(orchestrator.tavily, "fetch_context", _boom)
    elif stage == "repairer":
        monkeypatch.setattr(orchestrator.repairer, "propose_repair", _boom)
    elif stage == "tamper_gate":
        monkeypatch.setattr(orchestrator, "check_patch", _boom)
    elif stage == "apply_diff":
        # Not an OrchestratorError, so not the handled "failed to apply" path.
        deps.apply_diff = _boom
    elif stage == "adjudicator":
        monkeypatch.setattr(orchestrator.adjudicator, "adjudicate", _boom)
    elif stage == "passport":
        real = orchestrator.passport.compute_passport_hash
        calls = {"n": 0}

        def _fail_once(certificate):
            calls["n"] += 1
            if calls["n"] == 1:
                raise _Boom("injected failure")
            return real(certificate)

        monkeypatch.setattr(orchestrator.passport, "compute_passport_hash", _fail_once)
    else:  # pragma: no cover
        raise AssertionError(stage)


STAGES = [
    "intake",
    "recon",
    "planner",
    "sandbox",
    "classifier",
    "tavily",
    "repairer",
    "tamper_gate",
    "apply_diff",
    "adjudicator",
    "passport",
]


@pytest.mark.parametrize("stage", STAGES)
def test_exception_in_any_stage_still_ends_with_a_verdict(stage, tmp_path, monkeypatch):
    intake, deps, runner = _scenario(tmp_path)
    _inject(stage, monkeypatch, deps, runner)

    result = _run(tmp_path, intake, deps)  # must not raise

    assert result.verdict == "INDETERMINATE"
    assert reason_code_of(result.indeterminate_reason) == f"PIPELINE_ERROR:{stage}:_Boom"
    assert result.taxonomy_code is None
    assert "_Boom" in result.error_traceback and "Traceback" in result.error_traceback
    assert "Traceback" in result.full_log
    # A certificate is still produced and its passport verifies.
    assert result.certificate_prose
    assert len(result.reproduction_passport_hash) == 64
    assert verify_certificate(
        result.certificate()
    )
    # Every sandbox that was created was destroyed.
    assert runner.created == runner.destroyed
    if stage == "sandbox":
        assert runner.created == 1


def test_error_boundary_never_upgrades_or_hides_a_partial_repair(tmp_path, monkeypatch):
    """A crash after a gate-PASSed patch was applied must not surface as
    RUNS_AFTER_REPAIR; the attempt recorded so far is kept in the record."""
    intake, deps, runner = _scenario(tmp_path)
    _inject("adjudicator", monkeypatch, deps, runner)
    result = _run(tmp_path, intake, deps)
    assert result.verdict == "INDETERMINATE"
    assert [a.gate_decision for a in result.attempts] == ["PASS"]


def test_passport_failing_every_time_still_returns_a_verdict(tmp_path, monkeypatch):
    intake, deps, runner = _scenario(tmp_path)
    monkeypatch.setattr(orchestrator.passport, "compute_passport_hash", _boom)
    result = _run(tmp_path, intake, deps)
    assert result.verdict == "INDETERMINATE"
    assert reason_code_of(result.indeterminate_reason) == "PIPELINE_ERROR:passport:_Boom"
    # Honestly unverifiable rather than a fabricated hash.
    assert result.reproduction_passport_hash == ""


def test_pipeline_error_is_an_our_fault_code():
    assert orchestrator.is_our_fault("PIPELINE_ERROR:recon:ValueError")
    assert orchestrator.is_our_fault("RECON_MODEL_ERROR")
    assert not orchestrator.is_our_fault("ENTRYPOINT_UNCLEAR")
    assert not orchestrator.is_our_fault(None)
