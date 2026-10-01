"""harness-v1.4.1-rc, directive items 1 and 2 (D-30, D-31), tested against what the harness-v1.4.0 gate RECORDED for corpus-v2 #11.

Item 1 (D-30): the guard funds an operation at the rolling rate this entry's completed operations cost per wall second x 1.5, between a
floor of $0.0030/s and a ceiling of $0.0085/s, and records the rate and its source operations on every operation.
Item 2 (D-31): a budget-limited stop does not end the entry while money left funds one operation AND an environment image is kept: the
next operation resumes from that image.
"""

from __future__ import annotations

import functools
import json
import types
from pathlib import Path

import pytest

import v140_cloud
from app.services import orchestrator, sandbox
from app.services.cost_guard import (
    FUNDING_RATE_CEILING_USD_PER_S,
    FUNDING_RATE_FLOOR_USD_PER_S,
    FUNDING_SAFETY,
    SANDBOX_COST_RATE_USD_PER_S,
    CostGuard,
)
from test_v140_pipeline import EXEC, TQDM_MISSING, _repo, _run

ROOT = Path(__file__).resolve().parents[2]
GATE_V140 = ROOT / "runs" / "corpus_v2_batch" / "harness-v1.4.0" / "gate"


def _record_11() -> dict:
    return json.loads((GATE_V140 / "11_JindongGu__VoteAttack.json").read_text(encoding="utf-8"))


def _guard_after_the_recorded_baseline(entry_cap: float) -> tuple[CostGuard, dict, dict]:
    """A guard in the state #11's era operation started from: the recorded baseline operation and the model calls made before it
    (recon and planner; the third model call, Ultra's certificate prose, came after)."""
    record = _record_11()
    baseline, era = record["operations"]
    guard = CostGuard(daily_cost_ceiling_usd=entry_cap, model_prices_usd_per_1m={k: tuple(v) for k, v in record["cost_guard"]["prices_usd_per_1m"].items()})
    for usage in record["cost_guard"]["model_usage"][:2]:
        guard.record_model_usage(usage["model"], usage["prompt_tokens"], usage["completion_tokens"])
    guard.record_spend(baseline["cost_usd"])
    guard.record_operation({k: v for k, v in baseline.items() if k != "n"})
    return guard, baseline, era


# --- item 1: the funding rate -------------------------------------------------------------------------------------------

def test_the_recorded_stop_of_entry_11_would_have_been_funded_for_the_full_smoke_run():
    """v1.4.0 #11: the era operation was funded 108.2 s at the fixed $0.0085/s, built the whole environment, and was stopped as its final
    command (the smoke launcher) was about to start (`killed_step` is the launcher, `killed_seconds` 0.0): the 60 s smoke run was not
    funded. At the rolling rate of the entry's completed baseline ($0.329938 over 78.52 s) x 1.5 and the v1.4.1 entry cap of $1.50, the
    same operation is funded for more than the 108.2 s it needed to reach the smoke run plus the 60 s of the smoke run."""
    record = _record_11()
    baseline, era = record["operations"]
    assert era["outcome"] == "killed" and era["killed_step"].startswith('python3 -c "import base64;exec(') and era["killed_seconds"] == 0.0
    reached_the_smoke_run_at = era["funded_seconds"]
    assert reached_the_smoke_run_at == pytest.approx(108.2)

    guard, _, _ = _guard_after_the_recorded_baseline(1.50)
    rate = guard.funding_rate()
    assert rate.basis == "measured x safety" and rate.source_operations == (1,)
    assert rate.measured == pytest.approx(baseline["cost_usd"] / baseline["wall_seconds"])
    assert rate.rate == pytest.approx(FUNDING_SAFETY * baseline["cost_usd"] / baseline["wall_seconds"])
    funded = guard.operation_seconds_budget()
    assert funded >= reached_the_smoke_run_at + 60, (funded, reached_the_smoke_run_at + 60)
    # the old rule, for the record: the same money at the fixed rate funds fewer seconds than the operation needed
    assert guard.operation_seconds_budget(rate_usd_per_s=SANDBOX_COST_RATE_USD_PER_S) < reached_the_smoke_run_at + 60


def test_at_the_old_1_25_entry_cap_entry_11_would_still_end_cost_cap_after_a_late_stop():
    """Stated, not hidden. With $1.25 the new rate funds about 146 s, below the 168 s the operation needed: it would be stopped about 38 s
    into its smoke run, the guard's estimate for that killed step (v1.4.1: $0.0085/s, about $0.32 and $0.30 left; v1.4.2: $0.0152/s, about $0.57
    and $0.05 left) leaves less than one resumed operation needs (the smoke run plus the start-up margin): neither rule saves #11 at $1.25.
    At the pre-registered $1.50 the rate alone funds it."""
    guard, _, era = _guard_after_the_recorded_baseline(1.25)
    funded = guard.operation_seconds_budget()
    assert era["funded_seconds"] < funded < era["funded_seconds"] + 60
    guard.record_killed_operation(era["cost_usd"], funded - era["funded_seconds"])  # setup steps as recorded + the killed smoke step at the ceiling
    assert guard.operation_seconds_budget() < 60 + orchestrator.RESUME_START_MARGIN_S
    assert guard.remaining_today_usd == pytest.approx(0.05, abs=0.01)  # at $0.0152/s (harness-v1.4.1 estimated at $0.0085/s: about $0.30)


def test_the_stop_as_recorded_was_resumable_at_the_old_cap_the_scenario_the_resume_rule_was_written_for():
    """The recorded stop (funded 108.2 s at the fixed rate, stopped as the smoke launcher was about to start, $0.6219 left): what is left funds
    one resumed operation at the entry's measured rate."""
    guard, _, era = _guard_after_the_recorded_baseline(1.25)
    guard.record_spend(era["cost_usd"])
    assert guard.operation_seconds_budget() >= 60 + orchestrator.RESUME_START_MARGIN_S


def test_the_rate_is_clamped_between_the_floor_and_the_ceiling_and_a_killed_operation_is_not_a_source():
    guard = CostGuard(daily_cost_ceiling_usd=5.0)
    assert guard.funding_rate().rate == FUNDING_RATE_CEILING_USD_PER_S and guard.funding_rate().basis == "no completed operation: ceiling"
    guard.record_operation({"outcome": "completed", "cost_usd": 0.001, "wall_seconds": 100.0})  # $0.00001/s x 1.5: far below the floor
    assert (guard.funding_rate().rate, guard.funding_rate().basis) == (FUNDING_RATE_FLOOR_USD_PER_S, "floor")
    guard.record_operation({"outcome": "completed", "cost_usd": 5.0, "wall_seconds": 100.0})  # now far above the ceiling
    assert (guard.funding_rate().rate, guard.funding_rate().basis) == (FUNDING_RATE_CEILING_USD_PER_S, "ceiling")
    other = CostGuard(daily_cost_ceiling_usd=5.0)
    other.record_operation({"outcome": "killed", "cost_usd": 9.0, "wall_seconds": 1.0})  # estimated at the ceiling, not measured
    other.record_operation({"outcome": "completed", "cost_usd": 0.4, "wall_seconds": 100.0})
    other.record_operation({"role": "release", "outcome": "completed", "cost_usd": 3.0})  # no wall time: no rate
    rate = other.funding_rate()
    assert rate.source_operations == (2,) and rate.rate == pytest.approx(0.4 / 100.0 * FUNDING_SAFETY)
    assert (FUNDING_RATE_FLOOR_USD_PER_S, FUNDING_SAFETY, FUNDING_RATE_CEILING_USD_PER_S) == (0.0030, 1.5, 0.0085)


def test_the_rate_is_the_sum_of_cost_over_the_sum_of_wall_time_not_a_mean_of_rates():
    guard = CostGuard(daily_cost_ceiling_usd=5.0)
    guard.record_operation({"outcome": "completed", "cost_usd": 0.30, "wall_seconds": 60.0})   # $0.005/s
    guard.record_operation({"outcome": "completed", "cost_usd": 0.02, "wall_seconds": 20.0})   # $0.001/s
    assert guard.funding_rate().measured == pytest.approx(0.32 / 80.0)


# --- records and the pipeline --------------------------------------------------------------------------------------------

class _Clock:
    """A scripted wall clock for the orchestrator's operation records: every sandbox call advances it by the next scripted duration."""

    def __init__(self, walls):
        self.now, self.walls = 0.0, list(walls)

    def monotonic(self) -> float:
        return self.now

    def advance(self) -> None:
        self.now += self.walls.pop(0) if self.walls else 1.0


def _pipeline_with_a_killed_era_operation(tmp_path, monkeypatch, *, entry_cap: float, kill_every_attempt: bool = False,
                                          cost: float = 0.0744):
    """#11's recorded sequence on the fake cloud: a baseline that fails on an undeclared import, an era environment of three setup
    commands whose last layer is built, and the command's first era execution stopped by the budget (the sandbox's operation-timeout
    error, as in the v1.4.0 record). Wall times are the record's (78.52 s, 112.56 s); step costs are synthetic ($0.0744 each: the
    killed operation then costs about the recorded $0.2975)."""
    from contree_sdk.sdk.exceptions import OperationTimedOutError
    import uuid as uuidlib

    _repo(tmp_path, {"main.py": "import torch\nimport tqdm\n"})
    clock = _Clock([_record_11()["operations"][0]["wall_seconds"], _record_11()["operations"][1]["wall_seconds"], 20.0, 20.0, 20.0])
    monkeypatch.setattr(orchestrator, "time", types.SimpleNamespace(monotonic=clock.monotonic, time=__import__("time").time,
                                                                    sleep=lambda s: None))
    real_runner = sandbox.run_build_and_execute

    @functools.wraps(real_runner)  # the orchestrator reads the declared parameters (checkpoint, runner_extras) from the signature
    def runner(*a, **kw):
        try:
            return real_runner(*a, **kw)
        finally:
            clock.advance()

    def behaviour(shell, built, files):
        if shell not in EXEC:
            return None
        if not any("numpy==1.19.5" in b for b in built):
            return 1, "", TQDM_MISSING
        return 0, "RERUN_SMOKE_ALIVE: still running after 60s with output and no traceback", ""

    cloud = v140_cloud.install(monkeypatch, behaviour, costs={"": cost})
    executions = []
    real_run = v140_cloud.Image.run

    def run(self, shell, timeout, disposable, preserve_env=False):
        if shell in EXEC:
            executions.append(shell)
            era_execution = len(executions) == 2 or (kill_every_attempt and len(executions) >= 2)
            if era_execution:
                raise OperationTimedOutError(operation_uuid=uuidlib.uuid4())
        return real_run(self, shell, timeout, disposable, preserve_env)

    monkeypatch.setattr(v140_cloud.Image, "run", run)
    monkeypatch.setattr(sandbox, "run_build_and_execute", runner)
    result, deps, guard = _run(tmp_path, cloud, cap=entry_cap)
    return result, guard, cloud


def test_entry_11s_recorded_stop_is_followed_by_a_resumed_operation_from_the_kept_era_image(tmp_path, monkeypatch):
    result, guard, cloud = _pipeline_with_a_killed_era_operation(tmp_path, monkeypatch, entry_cap=1.50)
    assert result.verdict == "RUNS_AFTER_REPAIR", result.full_log[-1500:]
    baseline, killed, resumed = guard.operations[:3]
    assert (baseline["outcome"], killed["outcome"], resumed["outcome"]) == ("completed", "killed", "completed")
    assert killed["image_kept"] and len(killed["kept_images"]) == 4  # the tree and the three setup layers
    # the resumed operation reopened the deepest kept image, ran no setup step and installed no torch
    assert resumed["resumed_after_operation"] == killed["n"] == 2
    assert resumed["branch_from_image"] == killed["env_image_id"] and resumed["branch_from_image"] in cloud.reopened
    assert resumed["start_setup_commands"] == resumed["setup_commands"] == 3 and not resumed["torch_installed"]
    assert resumed["torch_in_start_image"] and resumed["install_seconds"] == []
    torch_installs = [c for c in cloud.ran if c.startswith("pip install torch")]
    assert len(torch_installs) == 2  # the baseline's and the era's: not a third one
    assert "resuming after the budget-limited stop of operation 2" in result.full_log
    assert "COST_CAP" not in result.indeterminate_reason


def test_every_operation_records_the_rate_it_was_funded_at_and_the_operations_that_rate_came_from(tmp_path, monkeypatch):
    result, guard, _ = _pipeline_with_a_killed_era_operation(tmp_path, monkeypatch, entry_cap=1.50)
    baseline, killed, resumed = guard.operations[:3]
    assert baseline["funding"]["rate_used_usd_per_s"] is None and "not budget-limited" in baseline["funding"]["basis"]
    expected = FUNDING_SAFETY * baseline["cost_usd"] / baseline["wall_seconds"]
    for op in (killed, resumed):
        assert op["funding"]["source_operations"] == [1] and op["funding"]["basis"] == "measured x safety"
        assert op["funding"]["rate_used_usd_per_s"] == pytest.approx(expected, rel=1e-6)
        assert op["funding"]["safety"] == 1.5 and op["funding"]["floor_usd_per_s"] == 0.003 and op["funding"]["ceiling_usd_per_s"] == 0.0085
        assert op["funding"]["measured_usd_per_s"] == pytest.approx(baseline["cost_usd"] / baseline["wall_seconds"], rel=1e-6)
    assert killed["funded_seconds"] == pytest.approx(round((1.50 - baseline["cost_usd"] - guard.model_spent_usd) / expected, 1), abs=2.0)


def test_the_entry_ends_cost_cap_when_what_is_left_cannot_fund_one_operation(tmp_path, monkeypatch):
    """Item 2's other half: an image is kept, but the money left funds fewer seconds than one operation (the smoke run plus the start-up
    margin): INDETERMINATE COST_CAP, with the reason saying why it was not resumed."""
    result, guard, _ = _pipeline_with_a_killed_era_operation(tmp_path, monkeypatch, entry_cap=0.88)
    assert result.verdict == "INDETERMINATE" and result.indeterminate_reason.startswith("COST_CAP: ")
    assert "not resumed" in result.indeterminate_reason and "below one operation" in result.indeterminate_reason
    assert [op["outcome"] for op in guard.operations] == ["completed", "killed"]


def test_a_resume_that_is_stopped_again_is_resumed_at_most_twice_per_operation(tmp_path, monkeypatch):
    result, guard, _ = _pipeline_with_a_killed_era_operation(tmp_path, monkeypatch, entry_cap=3.0, kill_every_attempt=True)
    assert result.verdict == "INDETERMINATE" and "COST_CAP" in result.indeterminate_reason
    assert "resume limit" in result.indeterminate_reason
    era = [op for op in guard.operations if op["role"] == "re-execution" or op.get("resumed_after_operation")]
    assert len(era) == 1 + orchestrator.MAX_RESUMES and all(op["outcome"] == "killed" for op in era)


def test_nothing_kept_means_nothing_to_resume_and_the_entry_ends_cost_cap(tmp_path, monkeypatch):
    """A stop before the first setup layer exists (only the committed-tree layer is kept, which holds no environment) is not resumed
    even with money left: nothing to resume from."""
    from contree_sdk.sdk.exceptions import OperationTimedOutError
    import uuid as uuidlib

    _repo(tmp_path, {"main.py": "import torch\nimport tqdm\n"})

    def behaviour(shell, built, files):
        if shell not in EXEC:
            return None
        return (1, "", TQDM_MISSING) if not any("numpy==1.19.5" in b for b in built) else (0, "ok", "")

    cloud = v140_cloud.install(monkeypatch, behaviour)
    real_run = v140_cloud.Image.run
    stopped = []

    def run(self, shell, timeout, disposable, preserve_env=False):
        baseline_done = any(c in EXEC for c in cloud.ran)
        if baseline_done and not stopped and not shell.startswith("tar -xpf") and shell != "true":
            stopped.append(shell)  # the era operation's first setup command
            raise OperationTimedOutError(operation_uuid=uuidlib.uuid4())
        return real_run(self, shell, timeout, disposable, preserve_env)

    monkeypatch.setattr(v140_cloud.Image, "run", run)
    result, _, guard = _run(tmp_path, cloud, cap=3.0)
    assert stopped and [op["outcome"] for op in guard.operations] == ["completed", "killed"]
    assert result.verdict == "INDETERMINATE" and "not resumed: no environment image is kept" in result.indeterminate_reason
