"""harness-v1.4.3-rc, D-42: the sustained-run line. A RUNS_* verdict after a repair is a 60 s smoke verdict; after the gate's entries, each RUNS_* entry whose smoke run was still
alive at its limit is re-executed once from the image the smoke command ran on, for up to 600 s, and the outcome is stored beside the verdict. Non-gating, changes no verdict.

The runner is a fake (`sandbox.run_on_image` has its own tests in test_v143_output_limit.py and a live seal check); the record shapes are the committed gate records."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services import sandbox, sustained_run
from app.services.sandbox import StepResult

ROOT = Path(__file__).resolve().parents[2]
GATE_V142 = ROOT / "runs" / "corpus_v2_batch" / "harness-v1.4.2" / "gate"
IMAGE = "458e2298-282f-42b3-bc70-a57db36aae5e"


def _record(verdict="RUNS_AFTER_REPAIR", outcome="alive_at_limit", image=IMAGE, chosen=True, command="python main.py") -> dict:
    execution = {"mode": "smoke", "seconds": 60, "outcome": outcome, **({"image": image} if image else {})}
    attempts = [{"attempt_number": 0, "origin": "time_machine", "exit_code": 1, "execution": {"mode": "smoke", "seconds": 60, "outcome": "exited"}},
                {"attempt_number": 3, "origin": "model", "candidate": 1, "chosen": chosen, "exit_code": 0, "execution": execution}]
    return {"batch": {"entry_id": 7}, "corpus_entry": {"name": "x__y", "command": command}, "result": {"verdict": verdict, "attempts": attempts}}


def _step(code=0, seconds=200.0, cost=2.0, timed_out=False, stdout="", stderr="") -> StepResult:
    return StepResult("python main.py", code, stdout, stderr, seconds, cost, timed_out=timed_out)


class _Runner:
    def __init__(self, step=None, exc=None):
        self.step, self.exc, self.calls = step, exc, []

    def __call__(self, **kw):
        self.calls.append(kw)
        if self.exc:
            raise self.exc
        return self.step


def _run(record, runner, remaining=3.0, left=1):
    return sustained_run.run_sustained(record, api_key="k", project_id="p", remaining_usd=remaining, entries_left=left, runner=runner)


# --- which records are sustained ----------------------------------------------------------------------------------------

def test_only_runs_verdicts_are_sustained():
    assert sustained_run.final_run_of(_record(verdict="BLOCKED")) is None
    assert sustained_run.final_run_of(_record(verdict="INDETERMINATE")) is None
    assert _run(_record(verdict="COST_CAP"), _Runner()) is None


def test_a_smoke_run_still_alive_names_the_image_the_chosen_attempt_ran_on():
    final = sustained_run.final_run_of(_record())
    assert final["kind"] == "smoke_alive" and final["image"] == IMAGE and final["attempt_number"] == 3 and final["candidate"] == 1


def test_the_chosen_attempt_wins_over_a_later_passing_one():
    record = _record()
    record["result"]["attempts"].append({"attempt_number": 3, "origin": "model", "candidate": 3, "chosen": False, "exit_code": 0,
                                         "execution": {"mode": "smoke", "seconds": 60, "outcome": "alive_at_limit", "image": "other-image"}})
    assert sustained_run.final_run_of(record)["image"] == IMAGE


def test_a_command_that_finished_inside_the_smoke_window_or_a_complete_baseline_needs_no_sustained_run():
    runner = _Runner()
    exited = _run(_record(outcome="exited"), runner)
    assert exited["outcome"] == "not_needed" and "finished by itself" in exited["label"] and exited["ran"] is False
    baseline = _record(verdict="RUNS_CLEAN")
    baseline["result"]["attempts"] = []
    done = _run(baseline, runner)
    assert done["outcome"] == "not_needed" and "ran to completion" in done["label"]
    assert runner.calls == []


def test_the_recorded_v142_entry_7_names_no_image_so_the_line_says_it_was_not_made():
    """harness-v1.4.2's #7 predates D-42: its `execution` has no image. The line is stored as not made, with the reason, never silently skipped."""
    record = json.loads((GATE_V142 / "07_albertometelli__pfqi.json").read_text(encoding="utf-8"))
    final = sustained_run.final_run_of(record)
    assert final["kind"] == "smoke_alive" and final["image"] is None and final["attempt_number"] == 3
    runner = _Runner()
    doc = _run(record, runner)
    assert doc["outcome"] == "not_run" and "no kept image" in doc["reason"] and runner.calls == [] and "unlabelled" in doc["label"]


# --- funding ----------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("remaining,left,expected", [(3.065, 1, 198), (3.065, 2, 97), (20.0, 1, 600), (0.05, 1, 0), (0.0, 1, 0), (-1.0, 1, 0), (6.2, 1, 404), (9.5, 1, 600), (1.0, 1, 62)])
def test_a_sustained_run_is_funded_with_its_share_of_what_the_gate_cap_has_left(remaining, left, expected):
    assert sustained_run.funded_seconds(remaining, left) == expected


def test_a_600_second_run_does_not_fit_what_a_gate_cap_leaves_after_four_entries():
    """The reason the line is funding-limited: 600 s at the owner's rate is $9.12 (about $6.2 at the observed $0.0104/s); the v1.4.2 gate left $3.065 of a $7.00 cap."""
    assert 600 * sustained_run.FUNDING_RATE_USD_PER_S == pytest.approx(9.12)
    assert sustained_run.funded_seconds(7.00 - 3.935, 1) < 600


def test_below_the_minimum_the_run_is_not_made_and_says_why():
    runner = _Runner()
    doc = _run(_record(), runner, remaining=0.5)
    assert doc["outcome"] == "not_run" and doc["ran"] is False and runner.calls == [] and "minimum is 90 s" in doc["reason"] and doc["funded_seconds"] == 29


# --- outcomes ---------------------------------------------------------------------------------------------------------------

def test_a_run_that_completes_is_labelled_completed_with_its_cost_and_stream_sizes():
    runner = _Runner(_step(code=0, seconds=312.4, cost=3.25, stdout="epoch 10 done\n"))
    doc = _run(_record(), runner, remaining=9.5)
    assert runner.calls == [{"api_key": "k", "project_id": "p", "image_id": IMAGE, "command": "python main.py", "timeout_seconds": 600.0}]
    assert (doc["outcome"], doc["ran"], doc["exit_code"], doc["cost_usd"], doc["cost_tag"]) == ("completed", True, 0, 3.25, "API-REPORTED")
    assert "ran to completion in 312 s" in doc["label"] and doc["streams"]["stdout"]["bytes"] == 14 and doc["streams"]["limit_bytes"] == sandbox.OUTPUT_LIMIT_BYTES
    assert doc["funded_seconds"] == 600 and doc["requested_seconds"] == 600 and doc["smoke_final"]["kind"] == "smoke_alive"


def test_a_run_stopped_by_the_sandbox_at_its_limit_is_running_at_limit_and_funding_limited_when_shorter():
    runner = _Runner(_step(code=137, seconds=198.1, cost=2.05, timed_out=True, stderr="\r12.0%\r12.1%"))
    doc = _run(_record(), runner, remaining=3.065)
    assert doc["funded_seconds"] == 198 and runner.calls[0]["timeout_seconds"] == 198.0
    assert doc["outcome"] == "running_at_limit" and "198 s limit (600 s requested" in doc["label"] and "funding-limited" in doc["label"]
    assert "had not failed" in doc["label"] and "not completion" in doc["label"]


def test_a_run_that_fails_is_labelled_failed_with_the_classifier_reading_and_the_tail():
    stderr = "Traceback (most recent call last):\n  File \"main.py\", line 9, in <module>\nModuleNotFoundError: No module named 'skimage'\n"
    runner = _Runner(_step(code=1, seconds=71.9, cost=0.75, stderr=stderr))
    doc = _run(_record(), runner, remaining=5.0)
    assert doc["outcome"] == "failed" and doc["exit_code"] == 1 and "failed after 72 s" in doc["label"] and "skimage" in doc["label"]
    assert doc["classification"]["code"] == "DEP_MISSING" and doc["stderr_tail"].endswith("'skimage'\n")


def test_a_client_side_wait_timeout_is_recorded_with_an_estimated_cost_and_never_raised():
    runner = _Runner(exc=sandbox.SandboxTimeoutError("sandbox execution exceeded 198s wall clock", command="python main.py", killed_seconds=198.0))
    doc = _run(_record(), runner, remaining=3.065)
    assert doc["outcome"] == "running_at_limit" and doc["via"] == "client_wait_timeout"
    assert doc["cost_usd"] == 0.0 and doc["cost_estimated_usd"] == pytest.approx(198 * 0.0152, abs=1e-6) and "ESTIMATED" in doc["cost_tag"]


def test_any_other_sandbox_failure_is_a_record_and_loses_no_other_record():
    doc = _run(_record(), _Runner(exc=RuntimeError("no image 458e2298")), remaining=5.0)
    assert doc["outcome"] == "error" and doc["ran"] is True and "RuntimeError" in doc["error"] and "unlabelled" in doc["label"]


def test_the_sustained_run_never_changes_the_record_it_labels():
    record = _record()
    before = json.dumps(record, sort_keys=True)
    _run(record, _Runner(_step()), remaining=9.5)
    assert json.dumps(record, sort_keys=True) == before
