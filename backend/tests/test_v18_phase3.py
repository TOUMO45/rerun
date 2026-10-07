"""harness-v1.8, Phase 3: the actionable-diagnosis scorer (`reports/dev/v18/score_diagnosis.py`, rubric `DIAGNOSIS_RUBRIC.md`) and the per-set metrics (`set_metrics.py`).

The scorer is exercised on small synthetic records (each criterion failing on its own, in both directions) and on the committed DEV key, whose two scores are pinned: the blockers the DEV
runs STORED (9 of 18 actionable) and the blockers the current rules DERIVE from the same records (16 of 18; the key was written by an author who had read the diagnoses, so that is a fit,
not a measurement). The metrics are pinned to the committed records and `set_metrics.json` must be what the script produces."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "reports" / "dev" / "v18"))
import score_diagnosis as sd  # noqa: E402
import set_metrics as sm  # noqa: E402

KEY = ROOT / "reports" / "dev" / "v18" / "diagnosis_dev_key.json"
needs_dev = pytest.mark.skipif(not (ROOT / "runs" / "dev_v18" / "round1").is_dir(), reason="the DEV records are not in this checkout")


def _rec(error="ModuleNotFoundError: No module named 'foo'", tail=None, attempts=None, reason=""):
    chain = [{"error": error, "class": "DEP_MISSING", "attribution": "REPO", "phase": "repo_run", "cleared_by": None}]
    tails = attempts if attempts is not None else ([{"stderr_tail": tail}] if tail else [])
    return {"verdict": "BLOCKED", "error_chain": chain, "attempts": tails, "indeterminate_reason": reason, "baseline": None, "full_log": ""}


def _blk(line="ModuleNotFoundError: No module named 'foo'", text="supply `foo` from the project it came from", fixable="human"):
    return {"error_line": line, "evidence": line, "what_a_human_must_supply": text, "next_action": text, "fixable_by": fixable}


ENTRY = {"must": ["foo"], "must_not": ["pip install bar"], "fixable_by": ["human"]}


def test_a_diagnosis_that_meets_all_four_criteria_is_actionable():
    j = sd.judge(ENTRY, _rec(), _blk())
    assert j["actionable"] and not j["why"]


@pytest.mark.parametrize("blk, rec_kwargs, failing", [
    (_blk(line="ModuleNotFoundError: No module named 'something_else'"), {}, "A1"),  # a line the record never printed
    (_blk(text="install the right release"), {}, "A2"),  # misses the cause the key names
    (_blk(text="supply `foo`; also pip install bar"), {}, "A2"),  # a forbidden claim
    (_blk(fixable="model"), {}, "A2"),  # a fixable_by the key does not accept
    (_blk(text="check the project"), {}, "A3"),  # names nothing the evidence names (and A2 'foo' is also missing, so only A3 is listed here as one of the failures)
])
def test_each_criterion_can_fail(blk, rec_kwargs, failing):
    j = sd.judge(ENTRY, _rec(**rec_kwargs), blk)
    assert not j["actionable"] and not j[failing]


def test_a4_catches_a_line_from_an_earlier_attempt():
    """The D-68 defect: the quoted line is in the record, but the run moved past it; the last attempt shows something else."""
    old = "fatal: unable to connect to github.com:"
    rec = _rec(error="ValueError: bad metadata", attempts=[{"stderr_tail": old}, {"stderr_tail": "ValueError: bad metadata"}])
    entry = {"must": ["git"], "must_not": [], "fixable_by": ["human"]}
    j = sd.judge(entry, rec, _blk(line=old, text="use `git+https://` instead of git://"))
    assert j["A1"] and j["A2"] and j["A3"] and not j["A4"]
    final = _rec(error="ValueError: bad metadata", attempts=[{"stderr_tail": "ok"}, {"stderr_tail": f"x\n{old}\n"}])
    assert sd.judge(entry, final, _blk(line=old, text="use `git+https://` instead of git://"))["A4"]  # the same line, now the run's final output


def test_a_stop_is_anchored_in_its_own_reason_and_a_missing_blocker_scores_nothing():
    reason = "ENTRYPOINT_NEEDS_ARGS: the command failed (`main.py: error: the following arguments are required: -file`)"
    rec = {**_rec(), "error_chain": [], "indeterminate_reason": reason}
    entry = {"must": ["file"], "must_not": [], "fixable_by": ["human"]}
    assert sd.judge(entry, rec, _blk(line="main.py: error: the following arguments are required: -file", text="run it with the `-file` argument"))["actionable"]
    missing = sd.judge(entry, rec, None)
    assert not missing["A1"] and not missing["A2"] and not missing["actionable" if "actionable" in missing else "A4"]  # no blocker report: nothing scores


def test_a_timeout_waives_only_a1_and_a3_and_an_unestablishable_cause_never_scores():
    timeout = {"must": ["smaller workload"], "must_not": [], "fixable_by": ["human"], "no_output_expected": True}
    rec = {**_rec(), "verdict": "TIMEOUT", "error_chain": []}
    blk = {"error_line": "the sandbox operation reached its wall-clock limit", "what_a_human_must_supply": "a smaller workload", "next_action": "run a smaller workload", "fixable_by": "human"}
    assert sd.judge(timeout, rec, blk)["actionable"]
    assert not sd.judge({**timeout, "must": ["never said"]}, rec, blk)["actionable"]  # A2 is not waived
    unknowable = {"must": [], "must_not": [], "fixable_by": [], "establishable": False}
    assert not sd.judge(unknowable, _rec(), _blk())["actionable"]


# --------------------------------------------------------------------------------------------------------------------- the committed DEV key

@needs_dev
def test_every_proof_line_of_the_dev_key_is_in_its_record():
    key = json.loads(KEY.read_text(encoding="utf-8"))
    for entry in key["entries"]:
        rec = sd.load(ROOT / entry["record"])
        raw = sd._flat(" ".join(sd.strings({k: rec[k] for k in ("error_chain", "attempts", "baseline", "indeterminate_reason", "full_log")})))
        assert sd._flat(entry["proof"]) in raw, entry["id"]


@needs_dev
def test_the_dev_scores_as_stored_and_as_derived_are_the_committed_numbers():
    key = json.loads(KEY.read_text(encoding="utf-8"))
    stored, derived = sd.score(key, "stored"), sd.score(key, "derived")
    assert (stored["actionable"], derived["actionable"], stored["n"]) == (9, 16, 18)
    # the two entries the corrected rules still do not make actionable, and why (committed in diagnosis_dev_score.json)
    assert {r["id"] for r in derived["rows"] if not r["actionable"]} == {"D09", "D12"}
    d09 = next(r for r in derived["rows"] if r["id"] == "D09")
    assert d09["A2"] is False and "does not establish the cause" in " ".join(d09["why"])
    d12 = next(r for r in derived["rows"] if r["id"] == "D12")
    assert d12["A4"] is False  # the strict final-state test: the quoted line is the one BEFORE the stopped apt step
    # the four stored diagnoses the DEV run found stale or wrong are exactly the ones A2 / A4 reject
    stale = {r["id"] for r in stored["rows"] if not r["A4"] or not r["A2"]}
    assert {"D02", "D03", "D06", "D10", "D12", "O1", "O4"} <= stale


# --------------------------------------------------------------------------------------------------------------------- the metrics

def test_metrics_are_medians_over_the_diagnosed_non_running_entries_and_recovery_excludes_strikes():
    rows = [
        {"entry": 1, "verdict": "BLOCKED", "struck": False, "has_diagnosis": True, "seconds": 100.0, "cost_usd": 1.0, "baseline_failed": True},
        {"entry": 2, "verdict": "INDETERMINATE", "struck": False, "has_diagnosis": True, "seconds": 300.0, "cost_usd": 3.0, "baseline_failed": True},
        {"entry": 3, "verdict": "BLOCKED", "struck": False, "has_diagnosis": False, "seconds": 9999.0, "cost_usd": 99.0, "baseline_failed": True},  # no diagnosis: not measured
        {"entry": 4, "verdict": "RUNS_AFTER_REPAIR", "struck": False, "has_diagnosis": False, "seconds": 50.0, "cost_usd": 0.5, "baseline_failed": True},
        {"entry": 5, "verdict": "RUNS_AFTER_REPAIR", "struck": True, "has_diagnosis": False, "seconds": 50.0, "cost_usd": 0.5, "baseline_failed": True},  # an audited false success
        {"entry": 6, "verdict": "RUNS_CLEAN", "struck": False, "has_diagnosis": False, "seconds": 5.0, "cost_usd": 0.1, "baseline_failed": False},
    ]
    m = sm.metrics(rows)
    assert m["n"] == 6 and m["ran"] == 2 and m["struck_by_audit"] == 1 and m["non_running"] == 3 and m["diagnosed"] == 2
    assert m["median_seconds_to_diagnosis"] == 200.0 and m["median_api_reported_cost_usd_to_diagnosis"] == 2.0 and m["measured_over"] == {"seconds": 2, "cost": 2}
    assert m["recovery"] == {"as_published_failed": 5, "recovered_after_repair": 1}  # the struck success is not a recovery
    empty = sm.metrics([])
    assert empty["median_seconds_to_diagnosis"] is None and empty["n"] == 0


@needs_dev
def test_the_committed_metrics_file_is_what_the_script_produces_from_the_committed_records():
    on_disk = json.loads((ROOT / "reports" / "dev" / "v18" / "set_metrics.json").read_text(encoding="utf-8"))["sets"]
    fresh = sm.collect()
    assert on_disk == json.loads(json.dumps(fresh))
    # a few numbers read by hand from the records: TEST-B's RAN count is the served, audited one (L2D; trees_from_transformers is struck by R4 (b))
    assert on_disk["test_b"]["ran"] == 1 and on_disk["dev_v18_corpus"]["n"] == 16 and on_disk["dev_v18_corpus"]["ran"] == 2 and on_disk["dev_v18_oos"]["n"] == 5


# --------------------------------------------------------------------------------------------------------------------- the API carries the measurements

def test_the_preregistered_endpoint_serves_the_measured_medians_for_the_three_held_out_sets_only(monkeypatch):
    from app.routers import batch

    sets = {s["key"]: s for s in batch.preregistered_results(ROOT)["sets"]}
    assert set(sets) == {"test_c", "test_b", "oos", "test"}  # the DEV-CONTAMINATED re-runs are not served as held-out results; TEST-C (harness-v1.8.0) is
    # the actionable-diagnosis count is served only for TEST-C, beside the run count (never merged); the frozen sets are not scored by the rubric
    assert sets["test_c"]["diagnosis"]["count"] == 7 and sets["test_c"]["diagnosis"]["of"] == 9 and (sets["test_c"]["count"], sets["test_c"]["of"]) == (1, 10)
    assert all(sets[k]["diagnosis"] is None for k in ("test", "test_b", "oos"))
    for key in sets:
        m = sets[key]["metrics"]
        assert m["cost_tag"].startswith("API-REPORTED") and m["source"] == "reports/dev/v18/set_metrics.json" and m["median_seconds_to_diagnosis"] > 0
    assert sets["test_b"]["metrics"]["recovery"] == {"as_published_failed": 7, "recovered_after_repair": 1}
    assert sets["oos"]["metrics"]["measured_over"] == {"seconds": 2, "cost": 2}  # only two of the five out-of-sample records carried a diagnosis (D-58)
    # a checkout without the file serves the same results with `metrics: null`
    monkeypatch.setattr(batch, "SET_METRICS", "reports/dev/v18/no_such_file.json")
    bare = {s["key"]: s for s in batch.preregistered_results(ROOT)["sets"]}
    assert all(s["metrics"] is None for s in bare.values()) and bare["test_b"]["count"] == 1
