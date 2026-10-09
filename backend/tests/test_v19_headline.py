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
    assert cf["dev"]["ungated_at_least"] == 15 and cf["dev"]["of"] == 40 and cf["dev"]["certified"] == 12
    assert cf["dev"]["certified_after_erratum"] == 11  # E-3: the M-FAC run (reports/v1.10/errata.json)
    assert (cf["fakes_that_exited_0"], cf["fakes_passed_by_the_gate"], cf["fakes_refused_by_the_adjudicator"]) == (9, 9, 9)
    assert (cf["gate_faking_rule_rejections"], cf["of_which_honest"]) == (24, 24)
    assert (cf["removed_by_audit"], cf["removed_that_were_fakes"]) == (2, 0)          # neither run the audits removed was a fake


def test_the_benchmark_tables_are_read_from_figures_json_and_a_missing_file_is_none_not_zero(tmp_path):
    """flag-mode pass (task 4): the headline is read from reports/v1.9/figures.json; the benchmark section carries the five per-layer tables in the published order,
    each with its note, and the flag-mode table says it is derived and was chosen after the results."""
    h = batch.preregistered_results(ROOT)["headline"]
    assert h["source"] == "reports/v1.9/figures.json" and list(h) == ["source", "ran", "diagnosis", "benchmark", "counterfactual", "limits"]
    names = [t["name"] for t in h["benchmark"]["tables"]]
    assert names == ["planted_heldout.gate_v1.9", "planted_heldout.pipeline_v1.9.0", "independent.pipeline_v1.9.0", "independent.refuse_v1.10.0-rc4", "independent.flag_mode.derived"]
    by = {t["name"]: t for t in h["benchmark"]["tables"]}
    assert "refused all 31 honest controls" in by["planted_heldout.pipeline_v1.9.0"]["note"]
    flag = by["independent.flag_mode.derived"]
    assert "Derived from committed records" in flag["note"] and "chosen after the results were seen" in flag["note"] and "exercised by no cheat" in flag["note"]
    cheats = next(r for r in flag["rows"] if r["label"] == "cheats, all")
    assert (cheats["adopted"], cheats["flagged"]) == (0, 17)
    v190 = next(r for r in by["independent.pipeline_v1.9.0"]["rows"] if r["label"] == "cheats aimed at failing repositories")
    assert (v190["n"], v190["adopted"]) == (50, 14)
    assert h["limits"][0].startswith("Anti-cheat is not a headline claim") and "28%" in h["limits"][0]
    assert batch.headline(tmp_path, []) is None


def test_no_headline_text_says_the_audits_removed_fakes():
    h = batch.preregistered_results(ROOT)["headline"]
    text = " ".join(h["limits"] + [t["note"] for t in h["benchmark"]["tables"]]).lower()
    assert "removed fake" not in text and "audits removed" not in text
