"""scripts/compare_batches.py: every entry in exactly one category, the rate's denominator, regressions, integrity."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("compare_batches", ROOT / "scripts" / "compare_batches.py")
cmp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cmp)

HASH, TAG, COMMIT = "h" * 64, "harness-v1.3", "c" * 40


def rec(i, verdict, *, chain=(), reason_code="", taxonomy=None, attempts=(), spent=0.1, hash_=HASH):
    return {
        "batch": {"entry_id": i, "corpus_hash": hash_, "harness_tag": TAG, "harness_commit": COMMIT},
        "corpus_entry": {"name": f"e{i}"},
        "result": {"verdict": verdict, "taxonomy_code": taxonomy, "reason_code": reason_code,
                   "error_chain": [{"error": e, "class": "X", "attribution": a, "cleared_by": None} for e, a in chain],
                   "attempts": list(attempts)},
        "cost_guard": {"spent_usd": spent},
    }


REPO = (("ModuleNotFoundError: No module named 'foo'", "REPO"),)
ENV = (("ModuleNotFoundError: No module named 'torch'", "ENV"),)
CITED = ({"origin": "model", "tavily_sources": [{"url": "u"}]},)


def compare(pairs):
    control = [rec(i, *c[:1], **c[1]) for i, (c, _) in enumerate(pairs, 1)]
    treatment = [rec(i, *t[:1], **t[1]) for i, (_, t) in enumerate(pairs, 1)]
    return cmp.compare(control, treatment)


def test_every_category_and_the_rate():
    result = compare([
        (("RUNS_CLEAN", {}), ("RUNS_CLEAN", {})),                                                     # 1 CONTROL_PASS
        (("BLOCKED", {"chain": REPO}), ("RUNS_AFTER_REPAIR", {"attempts": CITED})),                    # 2 REPO_RECOVERED
        (("BLOCKED", {"chain": REPO}), ("RUNS_AFTER_REPAIR", {})),                                     # 3 REPO_RECOVERED
        (("BLOCKED", {"chain": REPO}), ("BLOCKED", {"chain": REPO})),                                  # 4 REPO_STILL_FAILING
        (("BLOCKED", {"chain": REPO}), ("RUNS_CLEAN", {})),                                            # 5 UNSTABLE_AS_IS
        (("BLOCKED", {"chain": ENV}), ("RUNS_AFTER_REPAIR", {})),                                      # 6 ENV_ONLY (passes)
        (("BLOCKED", {"chain": ENV}), ("BLOCKED", {"chain": ENV})),                                    # 7 ENV_ONLY
        (("INDETERMINATE", {"reason_code": "SANDBOX_INCOMPAT"}), ("INDETERMINATE", {"reason_code": "SANDBOX_INCOMPAT"})),  # 8
        (("INFRA_ERROR", {"reason_code": "INFRA_ERROR:sandbox"}), ("BLOCKED", {"chain": REPO})),       # 9 NOT_MEASURED
    ])
    assert [r["category"] for r in result["rows"]] == [
        "CONTROL_PASS", "REPO_RECOVERED", "REPO_RECOVERED", "REPO_STILL_FAILING", "UNSTABLE_AS_IS", "ENV_ONLY", "ENV_ONLY",
        "SANDBOX_SIDE", "NOT_MEASURED"]
    assert sum(result["counts"].values()) == 9  # each entry in exactly one category
    assert (result["numerator"], result["denominator"]) == (2, 4)  # 2 / (2 recovered + 1 failing + 1 unstable)
    assert result["rate"] == 0.5
    assert result["rows"][5]["env_passes_in_treatment"] and not result["rows"][6]["env_passes_in_treatment"]
    assert result["regressions"] == []


def test_env_and_sandbox_never_enter_the_rate():
    result = compare([(("BLOCKED", {"chain": ENV}), ("RUNS_AFTER_REPAIR", {})),
                      (("INDETERMINATE", {"reason_code": "SANDBOX_QUOTA"}), ("RUNS_AFTER_REPAIR", {}))])
    assert result["denominator"] == 0 and result["numerator"] == 0 and result["rate"] is None and result["ci95"] is None


def test_a_control_pass_that_the_treatment_does_not_pass_is_a_regression():
    result = compare([(("RUNS_CLEAN", {}), ("BLOCKED", {"chain": REPO}))])
    assert result["rows"][0]["category"] == "CONTROL_PASS" and result["rows"][0]["regression"]
    assert len(result["regressions"]) == 1
    assert "REGRESSION" in cmp.render(result, "c", "t")


def test_arms_on_different_corpora_or_entry_sets_are_flagged():
    a = [rec(1, "BLOCKED", chain=REPO)]
    b = [rec(1, "BLOCKED", chain=REPO, hash_="x" * 64)]
    assert any("corpus hash" in p for p in cmp.compare(a, b)["problems"])
    assert any("entry sets differ" in p for p in cmp.compare(a, a + [rec(2, "BLOCKED", chain=REPO)])["problems"])


def test_wilson_interval_is_the_textbook_one():
    lo, hi = cmp.wilson(5, 10)
    assert lo == pytest.approx(0.2366, abs=1e-3) and hi == pytest.approx(0.7634, abs=1e-3)
    assert cmp.wilson(0, 0) is None
    lo, hi = cmp.wilson(0, 4)
    assert lo == 0.0 and 0.3 < hi < 0.5


def test_report_states_the_denominator_marks_the_estimate_and_lists_spend():
    result = compare([(("BLOCKED", {"chain": REPO, "spent": 0.5}), ("RUNS_AFTER_REPAIR", {"attempts": CITED, "spent": 1.5}))])
    text = cmp.render(result, "runs/c", "runs/t")
    assert "1/1 = 100%" in text and "REPO_RECOVERED + REPO_STILL_FAILING + UNSTABLE_AS_IS" in text
    assert "ESTIMATE, not measured" in text and "× 3 h/repo" in text
    assert "CONTROL $0.50 · TREATMENT $1.50 · total $2.00" in text


def test_main_writes_the_report_and_exits_2_on_regression(tmp_path):
    for name, records in (("control", [rec(1, "RUNS_CLEAN")]), ("treatment", [rec(1, "BLOCKED", chain=REPO)])):
        d = tmp_path / name
        d.mkdir()
        for r in records:
            (d / f"{r['batch']['entry_id']:02d}_e1.json").write_text(json.dumps(r), encoding="utf-8")
    out = tmp_path / "report.md"
    assert cmp.main(["--control", str(tmp_path / "control"), "--treatment", str(tmp_path / "treatment"), "--out", str(out)]) == 2
    assert "REGRESSION" in out.read_text(encoding="utf-8")
