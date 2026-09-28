"""A2b (2026-09-28): failed-move memory. Within one run, an env change that
was already applied and then saw the re-execution fail is not accepted again:
the repairer is re-asked once inside the same attempt; if it repeats again,
the attempt is REJECTED (ENV_REPEATS_FAILED_CHANGE) and counts as used.

Found live: the TTPT dev run's repairer re-proposed `add numpy==2.1.0`, a
change that could not help. Identity is normalized (op, PEP 503 name,
version, git source, command) — justification/evidence wording is ignored."""

from __future__ import annotations

import json

from app.services.cost_guard import CostGuard
from app.services.env_repair import EnvChange, EnvRule, change_key
from app.services.intake import RepoIntake
from app.services.orchestrator import PipelineDeps, run_pipeline
from app.services.sandbox import SandboxRunResult, StepResult
from app.services.time_machine import LockResult

ERROR = "ModuleNotFoundError: No module named 'widget'"


def _add(package, version=None, why="widget is imported but missing"):
    return {"op": "add", "package": package, "version": version, "justification": why, "evidence": ERROR}


def _reply(*changes):
    return json.dumps({"code_diff": None, "env_delta": list(changes), "explanation": "env fix"})


class _Chat:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = 0

    def chat_completion(self, **kwargs):
        self.calls += 1
        return self._responses.pop(0)


class _Sandbox:
    """Runs only once `widget-real` is installed; every other attempt fails
    with the same missing-module error."""

    def __init__(self):
        self.calls = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        if "widget-real" in " ".join(kwargs["install_commands"]):
            return SandboxRunResult(steps=(StepResult("python train.py", 0, "ok", "", 1.0, 0.0),))
        return SandboxRunResult(steps=(StepResult("python train.py", 1, "", ERROR, 1.0, 0.0),))


def _run(tmp_path, responses, max_attempts):
    (tmp_path / "requirements.txt").write_text("\n", encoding="utf-8")
    (tmp_path / "train.py").write_text("import widget\n", encoding="utf-8")
    intake = RepoIntake(tmp_path, "a" * 40, {"requirements.txt": "\n"}, frozenset(), (), ("train.py",), None)
    repair = _Chat(responses)
    sandbox = _Sandbox()
    deps = PipelineDeps(
        recon_client=_Chat([json.dumps({"entrypoint": "train.py", "confidence": 0.9})]),
        recon_model="r",
        repair_client=repair,
        repair_model="p",
        adjudicator_client=None,
        adjudicator_model=None,
        sandbox_api_key="k",
        sandbox_wall_clock_seconds=60,
        sandbox_runner=sandbox,
        max_attempts=max_attempts,
        lock_compiler=lambda *a: LockResult(False, error="lock disabled for this test"),
    )
    cost_guard = CostGuard(daily_cost_ceiling_usd=100, max_attempts_per_run=max_attempts)
    result = run_pipeline(repo_url="https://example.com/r", commit_sha="a" * 40, workdir=tmp_path, intake_result=intake,
                          deps=deps, cost_guard=cost_guard, run_id="memory")
    return result, repair, sandbox


def _model_attempts(result):
    return [a for a in result.attempts if a.origin == "model"]


def test_change_key_is_normalized_and_ignores_wording():
    a = EnvChange(op="add", package="Widget_Lib", version="1.0", justification="x", evidence="y")
    b = EnvChange(op="add", package="widget-lib", version="1.0", justification="other words", evidence="z")
    assert change_key(a) == change_key(b)
    assert change_key(a) != change_key(EnvChange(op="add", package="widget-lib", version="2.0"))
    assert change_key(a) != change_key(EnvChange(op="pin", package="widget-lib", version="1.0"))


def test_repeat_is_rejected_and_a_different_proposal_is_accepted(tmp_path):
    """Attempt 1 tries `widget` (fails). Attempt 2 repeats it (normalized:
    `Widget`, reworded) -> re-asked inside the same attempt -> proposes
    `widget-real` -> accepted, runs. The re-ask did not consume an attempt."""
    responses = [
        _reply(_add("widget")),
        _reply(_add("Widget", why="try the widget package again")),
        _reply(_add("widget-real")),
    ]
    result, repair, sandbox = _run(tmp_path, responses, max_attempts=2)
    assert result.verdict == "RUNS_AFTER_REPAIR", result.full_log
    attempts = _model_attempts(result)
    assert [a.attempt_number for a in attempts] == [1, 2]
    assert attempts[1].env_delta[0]["package"] == "widget-real"
    assert repair.calls == 3  # 2 attempts + 1 re-ask
    # The log quotes the proposal as the model wrote it.
    assert "repeats change(s) already tried and failed this run (add Widget)" in result.full_log
    # The repeat was never executed: baseline + attempt 1 + attempt 2's accepted change.
    assert len(sandbox.calls) == 3


def test_repeating_again_after_the_reask_uses_up_the_attempt(tmp_path):
    """Re-ask limit: one per attempt. Repeating twice -> REJECT with
    ENV_REPEATS_FAILED_CHANGE, attempt counted; the next attempt proceeds
    normally."""
    responses = [
        _reply(_add("widget")),
        _reply(_add("widget")),  # attempt 2: repeat
        _reply(_add("WIDGET", why="really")),  # attempt 2 re-ask: repeat again
        _reply(_add("widget-real")),  # attempt 3
    ]
    result, repair, sandbox = _run(tmp_path, responses, max_attempts=3)
    attempts = _model_attempts(result)
    assert [a.gate_decision for a in attempts] == ["PASS", "REJECT", "PASS"]
    assert {v["rule"] for v in attempts[1].gate_violations} == {EnvRule.ENV_REPEATS_FAILED_CHANGE}
    assert repair.calls == 4  # exactly one re-ask in attempt 2, none elsewhere
    assert result.verdict == "RUNS_AFTER_REPAIR"
    assert len(sandbox.calls) == 3  # the rejected attempt never executed


def test_repeats_exhaust_the_attempt_budget(tmp_path):
    responses = [_reply(_add("widget"))] + [_reply(_add("widget"))] * 2
    result, repair, _ = _run(tmp_path, responses, max_attempts=2)
    assert result.verdict == "BLOCKED"
    assert [a.gate_decision for a in _model_attempts(result)] == ["PASS", "REJECT"]
    assert repair.calls == 3


def test_negative_control_a_change_that_was_never_tried_is_not_a_repeat(tmp_path):
    """Different version of the same package is a different move."""
    responses = [_reply(_add("widget", "1.0")), _reply(_add("widget", "2.0"))]
    result, repair, _ = _run(tmp_path, responses, max_attempts=2)
    assert [a.gate_decision for a in _model_attempts(result)] == ["PASS", "PASS"]
    assert repair.calls == 2
    assert "repeats change(s)" not in result.full_log
