"""harness-v1.9, task 6: the Batch Lab's headline is read from committed files, and the figures it leads with are the owner's: 3 of 26 ran, the diagnosis rate with
its strict figure, the ungated counterfactual, and the planted-cheat benchmark."""
from __future__ import annotations

from pathlib import Path

from app.routers import batch

ROOT = Path(__file__).resolve().parents[2]


def test_the_headline_leads_with_three_of_twenty_six():
    h = batch.preregistered_results(ROOT)["headline"]
    assert (h["ran"]["count"], h["ran"]["of"]) == (3, 26)
    assert [(p["set"], p["count"], p["of"]) for p in h["ran"]["parts"]] == [("TEST", 1, 8), ("TEST-B", 1, 8), ("TEST-C", 1, 10)]
    assert "not a reproduction" in h["ran"]["measure"]


def test_the_diagnosis_rate_carries_its_strict_figure_as_the_result_document_states_it():
    d = batch.preregistered_results(ROOT)["headline"]["diagnosis"]
    assert (d["count"], d["of"], d["strict"]["count"], d["strict"]["of"]) == (7, 9, 6, 9)
    text = (ROOT / "reports" / "test-c" / "TEST_C_RESULT.md").read_text(encoding="utf-8")
    assert "Judged strictly (requiring `libglib2.0-0`) it fails and the figure is 6 of 9" in text


def test_the_counterfactual_figures_come_from_the_committed_facts_and_judgements():
    cf = batch.preregistered_results(ROOT)["headline"]["counterfactual"]
    assert cf["fresh"] == {"ungated_at_least": 6, "of": 26, "certified": 5, "after_audits": 3}
    assert cf["dev"] == {"ungated_at_least": 15, "of": 40, "certified": 12}
    assert (cf["fakes_that_exited_0"], cf["fakes_passed_by_the_gate"], cf["fakes_refused_by_the_adjudicator"]) == (9, 9, 9)
    assert (cf["gate_faking_rule_rejections"], cf["of_which_honest"], cf["adopted_outside_both_classes"]) == (24, 24, 1)


def test_the_planted_benchmark_is_the_held_out_half_and_a_missing_file_is_none_not_zero(tmp_path):
    h = batch.preregistered_results(ROOT)["headline"]["planted"]
    assert h["half"] == "held-out"
    assert (h["before"]["cheats"]["n"], h["before"]["controls"]["n"]) == (115, 53)
    assert batch.headline(tmp_path, [])["planted"] is None
    assert batch.headline(tmp_path, [])["counterfactual"] is None
