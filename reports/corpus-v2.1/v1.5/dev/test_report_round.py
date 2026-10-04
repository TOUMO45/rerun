"""Tests of the DEV round report generator (report_round.py). Kept beside it (the batch preflight refuses files outside its data allowlist that changed since a tag). Run with
`backend/.venv/Scripts/python.exe -m pytest reports/corpus-v2.1/v1.5/dev/test_report_round.py -q`. The one real record used is gate entry 7's v1.4.3 record (a gate entry: allowed)."""
from __future__ import annotations

import collections
import copy
import importlib.util
import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
sys.path.insert(0, str(HERE.parent / "devtest"))
import budget  # noqa: E402
import firewall  # noqa: E402


def _mod():
    spec = importlib.util.spec_from_file_location("report_round", HERE / "report_round.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


GATE7 = ROOT / "runs" / "corpus_v2_batch" / "harness-v1.4.3" / "gate" / "07_albertometelli__pfqi.json"


def _record(entry_id=4, verdict=None, round_no=1):
    rec = json.loads(GATE7.read_text(encoding="utf-8"))
    rec["batch"]["entry_id"] = entry_id
    rec["batch"]["dev_round"] = round_no
    rec["corpus_entry"]["name"] = f"o__r{entry_id}"
    if verdict:
        rec["result"]["verdict"] = verdict
    return rec


def test_the_report_has_every_section_and_reads_the_real_record_fields():
    r = _mod()
    text = r.build_report(1, {1: [_record(4), _record(5)]}, spend=budget.Spend(entries_usd=1.6), history=collections.Counter({"BLOCKED DEP_MISSING": 3}))
    for heading in ("## Verdict per entry", "## Failure classes", "## Deterministic rules that fired", "## What the model contributed", "## Stream flags (D-41)", "## Cost per entry"):
        assert heading in text
    assert "DEV count (smoke level, D2): 0 of 2" in text
    assert "BILLED: AWAITED" in text and "{'BLOCKED DEP_MISSING': 3}" in text
    assert "no TEST" not in text and "TEST entries are not in this report" in text


def test_a_runs_verdict_is_counted_with_its_kind_and_a_first_time_entry_adds_something():
    r = _mod()
    rec = _record(4, verdict="RUNS_AFTER_REPAIR")
    rounds = {1: [rec], 2: [copy.deepcopy(rec), _record(5, verdict="RUNS_AFTER_REPAIR", round_no=2)]}
    assert r.adds_something(rounds, 1)[0] is True  # best earlier count is 0
    adds, why = r.adds_something(rounds, 2)
    assert adds and "count 2 exceeds" in why
    rounds_same = {1: [rec], 2: [copy.deepcopy(rec)]}
    assert r.adds_something(rounds_same, 2)[0] is False
    text = r.build_report(1, {1: [rec]}, spend=budget.Spend(), history=collections.Counter())
    assert "DEV count (smoke level, D2): 1 of 1" in text


def test_a_round_with_a_new_entry_but_no_higher_count_still_adds():
    r = _mod()
    a, b = _record(4, verdict="RUNS_CLEAN"), _record(5, verdict="RUNS_CLEAN", round_no=2)
    adds, why = r.adds_something({1: [a], 2: [b]}, 2)
    assert adds and "first time" in why


def test_rules_model_streams_and_costs_come_from_the_record():
    r = _mod()
    rec = _record()
    assert any("time machine" in x for x in r.rules_fired(rec))
    m = r.model_contribution(rec)
    assert m["attempts"] > 0 and sum(m["model_calls"].values()) == len(rec["model_calls"])
    assert r.stream_flags(rec)["operations"] == len(rec["operations"])
    c = r.cost_of(rec)
    assert abs(c["total"] - rec["cost_guard"]["spent_usd"]) < 1e-12
    assert r.classifier_codes(rec) == [e["line"].split("]")[1].split(":")[0].strip() for e in rec["events"] if e["line"].startswith("[classifier]")]


def test_dev_records_never_opens_a_test_record(tmp_path, monkeypatch):
    monkeypatch.delenv(firewall.FROZEN_ENV, raising=False)
    r = _mod()
    dev = tmp_path / "corpus_v2_batch" / "harness-v1.5.0" / "dev"
    dev.mkdir(parents=True)
    test_id = sorted(firewall.TEST_ENTRIES)[0]
    (dev / f"{test_id:02d}_x__y.json").write_text("NOT JSON: would raise if opened", encoding="utf-8")
    (dev / "04_x__y.json").write_text(json.dumps(_record(4)), encoding="utf-8")
    got = r.dev_records(tmp_path)
    assert list(got) == [1] and [x["batch"]["entry_id"] for x in got[1]] == [4]


def test_historical_histogram_skips_test_records_and_the_v15_rounds(tmp_path, monkeypatch):
    monkeypatch.delenv(firewall.FROZEN_ENV, raising=False)
    r = _mod()
    monkeypatch.setattr(r, "ROOT", tmp_path)
    d = tmp_path / "runs" / "corpus_v2_batch" / "harness-v1.3.2" / "control"
    d.mkdir(parents=True)
    test_id = sorted(firewall.TEST_ENTRIES)[0]
    (d / f"{test_id:02d}_a__b.json").write_text("NOT JSON", encoding="utf-8")
    (d / "04_a__b.json").write_text(json.dumps({"result": {"verdict": "BLOCKED", "taxonomy_code": "DEP_MISSING"}}), encoding="utf-8")
    (d / "07_a__b.json").write_text(json.dumps({"result": {"verdict": "BLOCKED", "taxonomy_code": "DEP_MISSING"}}), encoding="utf-8")
    assert r.historical_histogram() == collections.Counter({"BLOCKED DEP_MISSING": 2})


def test_dev_rounds_at_any_tag_are_read_and_kept_out_of_the_history(tmp_path, monkeypatch):
    """A DEV round under a later tag (harness-v1.6.0/dev, harness-v1.7.0/dev) is a round of this program: read as a round, counted in the ledger, never in the history."""
    r = _mod()
    for tag, rnd in (("harness-v1.5.2", 3), ("harness-v1.6.0", 4), ("harness-v1.7.0", 5)):
        d = tmp_path / "runs" / "corpus_v2_batch" / tag / "dev"
        d.mkdir(parents=True)
        rec = _record(4, round_no=rnd)
        rec["cost_guard"] = {"spent_usd": 1.0, "estimated_sandbox_spent_usd": 0.0}
        (d / "04_o__r4.json").write_text(json.dumps(rec), encoding="utf-8")
    assert sorted(r.dev_records(tmp_path / "runs")) == [3, 4, 5]
    assert budget.read_spend(tmp_path).entries_usd == 3.0
    monkeypatch.setattr(r, "ROOT", tmp_path)
    assert sum(r.historical_histogram().values()) == 0


def test_the_ladder_and_blocker_sections_read_the_stored_v16_fields():
    r = _mod()
    a, b = _record(4), _record(5, verdict="RUNS_AFTER_REPAIR")
    a["result"]["outcome_levels"] = {"first_error_cleared": True, "first_error_cleared_by": "time_machine", "env_resolved": True, "entrypoint_runs": False}
    a["result"]["blocker"] = {"class": "DATA_MISSING", "family": "Data", "phase": "repo_run", "attribution": "REPO", "evidence": "AssertionError: Download x | y",
                              "fixable_by": "human", "what_a_human_must_supply": "the dataset", "sources": {"query": "q", "sources": [{"title": "t", "url": "https://e.org/d"}], "reason": None}}
    b["result"]["outcome_levels"] = {"first_error_cleared": True, "first_error_cleared_by": "model", "env_resolved": True, "entrypoint_runs": True}
    b["result"]["blocker"] = None
    text = "\n".join(r.ladder_and_blocker([a, b]))
    assert "first error cleared **2 of 2**" in text and "entrypoint runs (RUNS_*, smoke level) **1 of 2**" in text
    assert "| 4 | DATA_MISSING | Data | repo_run | REPO | human | `AssertionError: Download x \\| y` | the dataset | https://e.org/d |" in text
    assert "| 5 | (none) |" in text
    old = _record(4)
    old["result"].pop("outcome_levels", None)
    old["result"].pop("blocker", None)
    text_old = "\n".join(r.ladder_and_blocker([old]))
    assert "stored on 0 of 1 records, computed from the stored fields" in text_old
    assert text_old.count("## Outcome ladder") == 1 and "| 4 |" in text_old  # the older record's ladder is computed by the same pure function
