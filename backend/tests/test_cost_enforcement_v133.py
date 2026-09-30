"""harness-v1.3.3, D-7/D-8/D-3: the spend caps are enforced DURING a sandbox operation, a killed operation's spend is
recorded, and a wall-clock overrun in a re-execution is a TIMEOUT, not a PIPELINE_ERROR.

Nothing here touches Nebius. The "long operation" is a fake sandbox whose clock jumps by the step's duration and that
raises the SDK's own OperationTimedOutError when the step's `timeout=` is shorter than its duration."""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from contree_sdk.sdk.exceptions import OperationTimedOutError

import app.services.sandbox as sandbox_module
from app.services.cost_guard import (
    MIN_OPERATION_SECONDS,
    PER_OPERATION_CAP_USD,
    SANDBOX_COST_RATE_USD_PER_S,
    CostGuard,
    CostLimitExceeded,
    OperationBudgetExhausted,
)
from app.services.intake import RepoIntake
from app.services.orchestrator import PipelineDeps, run_pipeline
from app.services.sandbox import SandboxRunResult, SandboxTimeoutError, StepResult, run_build_and_execute


# --- CostGuard arithmetic ---------------------------------------------------------------------------------------------


def test_operation_budget_is_bounded_by_the_per_operation_cap_and_by_what_the_entry_has_left():
    g = CostGuard(daily_cost_ceiling_usd=2.0)
    assert PER_OPERATION_CAP_USD == 2.0  # a repair may use everything the entry has left
    assert g.operation_seconds_budget() == pytest.approx(PER_OPERATION_CAP_USD / SANDBOX_COST_RATE_USD_PER_S)
    g.record_spend(1.75)
    assert g.operation_seconds_budget() == pytest.approx(0.25 / SANDBOX_COST_RATE_USD_PER_S)
    g.record_spend(0.25)
    assert g.operation_seconds_budget() == 0.0


def test_killed_operation_records_measured_steps_plus_a_flagged_estimate():
    g = CostGuard(daily_cost_ceiling_usd=2.0)
    total = g.record_killed_operation(completed_steps_usd=0.10, killed_seconds=100.0)
    assert total == pytest.approx(0.10 + 100.0 * SANDBOX_COST_RATE_USD_PER_S)
    assert g.spent_today_usd == pytest.approx(total)
    assert g.estimated_spent_usd == pytest.approx(100.0 * SANDBOX_COST_RATE_USD_PER_S)
    assert g.cost_events and g.cost_events[0]["kind"] == "estimated"


def test_a_measured_spend_is_not_flagged_as_an_estimate():
    g = CostGuard(daily_cost_ceiling_usd=2.0)
    g.record_spend(0.3)
    assert g.estimated_spent_usd == 0.0 and g.cost_events == []


# --- the sandbox kills a step at the limit it was given and reports what is known -------------------------------------


class _Result:
    def __init__(self, cost):
        self.exit_code, self.stdout, self.stderr, self.elapsed_time, self.cost = 0, "", "", timedelta(seconds=1), cost


class _LongOpImage:
    """image.run(...).wait(): advances the clock by `duration[cmd]`; raises OperationTimedOutError if that exceeds the
    step's timeout=, like the real sandbox killing an operation."""

    def __init__(self, clock, durations, timeouts_seen):
        self._clock, self._durations, self._timeouts = clock, durations, timeouts_seen
        self.uuid = None
        self.result = _Result(0.05)
        self.exit_code = 0

    def apply_files(self, files):
        return self

    def run(self, *, shell, timeout, disposable, preserve_env=None):
        self._timeouts.append((shell, timeout))
        duration = self._durations.get(shell, 10.0)
        if duration > timeout:
            self._clock[0] += timeout
            raise OperationTimedOutError(operation_uuid=uuid4())
        self._clock[0] += duration
        return self

    def wait(self):
        return self


def _install_fake_long_sandbox(monkeypatch, durations):
    clock, timeouts_seen = [0.0], []

    class _Images:
        def docker(self, ref):
            return _LongOpImage(clock, durations, timeouts_seen)

    class _Sync:
        def __init__(self, config):
            self.images = _Images()

    monkeypatch.setattr(sandbox_module, "ContreeSync", _Sync)
    monkeypatch.setattr(sandbox_module.time, "monotonic", lambda: clock[0])
    return timeouts_seen


def test_a_600s_step_is_killed_at_its_limit_and_reports_completed_cost_and_killed_seconds(monkeypatch):
    seen = _install_fake_long_sandbox(monkeypatch, {"python train.py": 600.0})
    with pytest.raises(SandboxTimeoutError) as info:
        run_build_and_execute(
            api_key="k", base_image="python:3.10-slim", install_commands=["pip install numpy"],
            execute_command="python train.py", wall_clock_seconds=120.0,
        )
    exc = info.value
    assert "wall clock" in str(exc)  # the orchestrator's TIMEOUT mapping keys on this
    assert exc.command == "python train.py"
    assert exc.killed_seconds == pytest.approx(110.0)  # 120 s limit minus the 10 s install that completed
    assert exc.completed_cost_usd == pytest.approx(0.05)  # the install step completed at its measured cost
    assert [t for sh, t in seen if sh == "python train.py"] == [pytest.approx(110.0)]  # the step never got more than the limit


# --- orchestrator: budget-derived limit, recorded spend, verdicts ---------------------------------------------------


def _deps(runner, wall=600.0):
    class _Chat:
        def __init__(self, r):
            self.r = list(r)

        def chat_completion(self, **kw):
            return self.r.pop(0)

    return PipelineDeps(
        recon_client=_Chat([json.dumps({"entrypoint": "train.py", "confidence": 0.9})]), recon_model="r",
        repair_client=_Chat([]), repair_model="p", adjudicator_client=None, adjudicator_model=None,
        sandbox_api_key="k", sandbox_wall_clock_seconds=wall, sandbox_runner=runner,
    )


def _run(tmp_path, runner, guard, wall=600.0):
    (tmp_path / "train.py").write_text("print('x')\n", encoding="utf-8")
    intake = RepoIntake(Path(tmp_path), "a" * 40, {}, frozenset(), (), ("train.py",), None)
    return run_pipeline(repo_url="https://example.com/r", commit_sha="a" * 40, workdir=tmp_path, intake_result=intake,
                        deps=_deps(runner, wall), cost_guard=guard, run_id="cap")


def _repair_scenario(tmp_path, runner, guard, wall=600.0):
    """Baseline fails with a missing module, the model proposes `add pyyaml`, the repair re-execution is the runner's 2nd call."""
    (tmp_path / "train.py").write_text("import yaml\nprint('x')\n", encoding="utf-8")
    (tmp_path / "requirements.txt").write_text("\n", encoding="utf-8")
    intake = RepoIntake(Path(tmp_path), "a" * 40, {"requirements.txt": "\n"}, frozenset(), (), ("train.py",), None)

    class _Chat:
        def __init__(self, r):
            self.r = list(r)

        def chat_completion(self, **kw):
            return self.r.pop(0)

    add = {"code_diff": None, "explanation": "add yaml", "env_delta": [
        {"op": "add", "package": "pyyaml", "version": None, "justification": "yaml is imported",
         "evidence": "ModuleNotFoundError: No module named 'yaml'"}]}
    from app.services.time_machine import LockResult

    deps = PipelineDeps(
        recon_client=_Chat([json.dumps({"entrypoint": "train.py", "confidence": 0.9})]), recon_model="r",
        repair_client=_Chat([json.dumps(add)]), repair_model="p", adjudicator_client=None, adjudicator_model=None,
        sandbox_api_key="k", sandbox_wall_clock_seconds=wall, sandbox_runner=runner, smoke_seconds=0,
        lock_compiler=lambda *a: LockResult(False, (), (), (), "", "disabled"),
    )
    return run_pipeline(repo_url="https://example.com/r", commit_sha="a" * 40, workdir=tmp_path, intake_result=intake,
                        deps=deps, cost_guard=guard, run_id="cap")


def _yaml_missing(cost=0.01):
    return SandboxRunResult(steps=(StepResult("python train.py", 1, "", "ModuleNotFoundError: No module named 'yaml'", 1.0, cost),))


def test_the_baseline_keeps_the_600s_wall_clock_and_a_repair_gets_only_what_the_entry_can_fund(tmp_path):
    """Revised rule (before any v1.3.3 run): three of the twenty v1.3.2 CONTROL operations took 195-494 s of wall time at a normal cost, so the
    as-published run is never shortened by the budget rule (entry 18 must not become a false regression); repairs are."""
    walls = []

    def runner(**kw):
        walls.append(kw["wall_clock_seconds"])
        return _yaml_missing() if len(walls) == 1 else SandboxRunResult(steps=(StepResult("python train.py", 0, "ok", "", 1.0, 0.01),))

    guard = CostGuard(daily_cost_ceiling_usd=2.0)
    result = _repair_scenario(tmp_path, runner, guard)
    assert result.verdict == "RUNS_AFTER_REPAIR", result.full_log
    assert walls[0] == 600.0  # baseline: the pre-registered wall clock, whatever the budget
    assert walls[1] == pytest.approx((2.0 - 0.01) / SANDBOX_COST_RATE_USD_PER_S)  # repair: everything the entry has left, at the worst rate
    assert walls[1] < 600.0


def test_even_with_most_of_the_budget_gone_the_baseline_still_gets_the_full_wall_clock(tmp_path):
    seen = {}

    def runner(**kw):
        seen["wall"] = kw["wall_clock_seconds"]
        return SandboxRunResult(steps=(StepResult("python train.py", 0, "ok", "", 1.0, 0.01),))

    guard = CostGuard(daily_cost_ceiling_usd=2.0)
    guard.record_spend(1.9)
    result = _run(tmp_path, runner, guard)
    assert result.verdict == "RUNS_CLEAN" and seen["wall"] == 600.0


def test_budget_kill_of_a_repair_records_an_estimate_and_ends_INDETERMINATE_COST_CAP_never_a_repo_verdict(tmp_path):
    calls = []

    def runner(**kw):
        calls.append(kw["wall_clock_seconds"])
        if len(calls) == 1:
            return _yaml_missing()
        raise SandboxTimeoutError("sandbox execution exceeded wall clock", command="pip install pyyaml",
                                  completed_cost_usd=0.05, killed_seconds=kw["wall_clock_seconds"] - 10.0)

    guard = CostGuard(daily_cost_ceiling_usd=2.0)
    result = _repair_scenario(tmp_path, runner, guard)
    assert result.verdict == "INDETERMINATE"
    assert result.indeterminate_reason.startswith("COST_CAP: ")
    assert guard.estimated_spent_usd > 0.0
    assert guard.spent_today_usd <= 2.0 + 0.06  # never more than the repair was funded for (plus the measured part)
    assert "operation stopped" in result.full_log
    assert result.attempts[-1].env_delta and result.attempts[-1].env_delta[0]["package"] == "pyyaml"  # the delta that was running is kept


def test_a_repair_with_too_little_budget_left_does_not_start(tmp_path):
    calls = []

    def runner(**kw):
        calls.append(kw)
        return _yaml_missing(cost=2.0 - (MIN_OPERATION_SECONDS - 1) * SANDBOX_COST_RATE_USD_PER_S)  # the baseline leaves < 30 s of funding

    guard = CostGuard(daily_cost_ceiling_usd=2.0)
    result = _repair_scenario(tmp_path, runner, guard)
    assert len(calls) == 1  # only the baseline ran; the repair never reached the sandbox
    assert result.verdict == "INDETERMINATE" and result.indeterminate_reason.startswith("COST_CAP: ")


def test_a_baseline_that_overruns_the_wall_clock_is_TIMEOUT_as_in_v132_with_its_spend_recorded(tmp_path):
    def runner(**kw):
        raise SandboxTimeoutError("sandbox execution exceeded 600s wall clock", command="python train.py",
                                  completed_cost_usd=0.02, killed_seconds=590.0)

    guard = CostGuard(daily_cost_ceiling_usd=2.0)
    result = _run(tmp_path, runner, guard)
    assert result.verdict == "TIMEOUT"
    assert guard.spent_today_usd == pytest.approx(0.02 + 590.0 * SANDBOX_COST_RATE_USD_PER_S)


def test_a_wall_clock_overrun_below_the_budget_limit_is_TIMEOUT_and_its_spend_is_recorded(tmp_path):
    def runner(**kw):
        raise SandboxTimeoutError("sandbox execution exceeded 50s wall clock", command="python train.py",
                                  completed_cost_usd=0.02, killed_seconds=40.0)

    guard = CostGuard(daily_cost_ceiling_usd=2.0)
    result = _run(tmp_path, runner, guard, wall=50.0)  # configured wall clock (50 s) is the smaller bound
    assert result.verdict == "TIMEOUT"
    assert guard.spent_today_usd == pytest.approx(0.02 + 40.0 * SANDBOX_COST_RATE_USD_PER_S)


def test_a_timeout_in_a_repair_reexecution_is_TIMEOUT_not_PIPELINE_ERROR(tmp_path):
    """Entry 15 of harness-v1.3.2: the baseline failed, the first repair's re-execution passed the wall clock, and the
    run ended PIPELINE_ERROR:sandbox. The attempt that timed out must be in the record and the verdict TIMEOUT.
    (With the default 600 s wall clock the budget-derived limit, 176 s, is the smaller bound, so an overrun there is
    COST_CAP, tested above; TIMEOUT is what remains when the configured wall clock is the smaller bound.)"""
    (tmp_path / "train.py").write_text("import yaml\nprint('x')\n", encoding="utf-8")
    (tmp_path / "requirements.txt").write_text("\n", encoding="utf-8")
    intake = RepoIntake(Path(tmp_path), "a" * 40, {"requirements.txt": "\n"}, frozenset(), (), ("train.py",), None)
    calls = []

    def runner(**kw):
        calls.append(kw)
        if len(calls) == 1:
            return SandboxRunResult(steps=(StepResult("python train.py", 1, "", "ModuleNotFoundError: No module named 'yaml'", 1.0, 0.01),))
        raise SandboxTimeoutError("sandbox execution exceeded 600s wall clock", command="pip install x",
                                  completed_cost_usd=0.0, killed_seconds=50.0)

    class _Chat:
        def __init__(self, r):
            self.r = list(r)

        def chat_completion(self, **kw):
            return self.r.pop(0)

    add = {"code_diff": None, "explanation": "add yaml", "env_delta": [
        {"op": "add", "package": "pyyaml", "version": None, "justification": "yaml is imported",
         "evidence": "ModuleNotFoundError: No module named 'yaml'"}]}
    from app.services.time_machine import LockResult

    deps = PipelineDeps(
        recon_client=_Chat([json.dumps({"entrypoint": "train.py", "confidence": 0.9})]), recon_model="r",
        repair_client=_Chat([json.dumps(add)]), repair_model="p", adjudicator_client=None, adjudicator_model=None,
        sandbox_api_key="k", sandbox_wall_clock_seconds=100, sandbox_runner=runner,  # wall clock < budget limit: TIMEOUT
        lock_compiler=lambda *a: LockResult(False, (), (), (), "", "disabled"),
    )
    result = run_pipeline(repo_url="https://example.com/r", commit_sha="a" * 40, workdir=tmp_path, intake_result=intake,
                          deps=deps, cost_guard=CostGuard(daily_cost_ceiling_usd=100), run_id="t")
    assert result.verdict == "TIMEOUT"
    assert not (result.indeterminate_reason or "").startswith("PIPELINE_ERROR")
    last = result.attempts[-1]
    assert last.env_delta and last.env_delta[0]["package"] == "pyyaml"  # the delta that was being run is kept
    assert last.exit_code is None and "wall clock" in last.stderr_tail
