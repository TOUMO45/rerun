"""TEST-C (corpus-v4, harness-v1.8.0) as it came out, pinned to the committed records so that no text can say more (or less) than they do: the RAN count under the pre-registered rules, the
actionable-diagnosis score under the committed rubric and key, the two pre-registered claim thresholds and their outcomes, the counterfactual under harness-v1.7.2, and the order the
audit was done in (the key was committed before the score)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
TC = ROOT / "runs" / "corpus_v4_batch" / "harness-v1.8.0" / "treatment"
sys.path.insert(0, str(ROOT / "reports" / "dev" / "v18"))
import score_diagnosis as sd  # noqa: E402

needs = pytest.mark.skipif(not (TC / "test_c_result.json").is_file(), reason="the TEST-C records are not in this checkout")
PREREG = json.loads((ROOT / "backend/app/batch/corpus_v4/prereg.json").read_text(encoding="utf-8"))
KEY = ROOT / "reports" / "test-c" / "diagnosis_test_c_key.json"


@needs
def test_the_ran_count_and_the_claim_threshold():
    res = json.loads((TC / "test_c_result.json").read_text(encoding="utf-8"))
    assert (res["entries"], res["ran_entries"], res["ran_count"], res["tag"]) == (10, 10, 1, "harness-v1.8.0")
    ran = [r for r in res["rows"] if r["ran"]]
    assert [r["entry"] for r in ran] == [8] and ran[0]["why"].startswith("(iii)")
    # the registered RAN claim needs at least 3 of 10: not met
    assert res["ran_count"] < 3 and any("3 of 10" in c for c in PREREG["analysis"]["thresholds_from_dev_evidence"]["claims"])
    assert res["spend"]["total_usd"] < res["spend"]["cap_usd"] == 100.0


@needs
def test_the_strata_the_runner_wrote():
    res = json.loads((TC / "test_c_result.json").read_text(encoding="utf-8"))
    strata = {family: s["entries"] for family, s in res["by_blocker_family"].items()}
    assert strata == {"COST_CAP (stopped by the entry cap)": 2, "Data": 5, "Environment": 1, "Resources": 1} and sum(strata.values()) == 9


@needs
def test_the_diagnosis_score_the_registered_threshold_and_the_counterfactual():
    key = json.loads(KEY.read_text(encoding="utf-8"))
    assert [e["id"] for e in key["entries"]] == ["C01", "C02", "C03", "C04", "C05", "C06", "C07", "C09", "C10"]  # the nine non-running records; #8 ran
    stored = sd.score(key, "stored")
    assert (stored["actionable"], stored["n"]) == (7, 9)
    assert {r["id"] for r in stored["rows"] if not r["actionable"]} == {"C02", "C10"}
    assert stored["actionable"] / stored["n"] >= 0.5  # the registered diagnosis claim: at least 50 percent
    cf = json.loads((ROOT / "reports/test-c/diagnosis_test_c_score_as_v172.json").read_text(encoding="utf-8"))
    assert (cf["actionable"], cf["n"]) == (4, 9)
    gained = {r["id"] for r in stored["rows"] if r["actionable"]} - {r["id"] for r in cf["rows"] if r["actionable"]}
    assert gained == {"C03", "C06", "C09"}  # the TIMEOUT diagnosis and the spend-cap statement: the v1.8 additions
    evidence = [r["id"] for r in stored["rows"] if r["diagnosis"] == "evidence"]
    assert evidence == ["C03"]  # none of diagnosis.py's rules fired on TEST-C; the TIMEOUT report is blocker.py's


@needs
def test_every_proof_line_of_the_key_is_in_its_record():
    out = subprocess.run([sys.executable, str(ROOT / "reports/dev/v18/score_diagnosis.py"), "--key", str(KEY), "--check-key"], capture_output=True, text=True, encoding="utf-8", cwd=ROOT)
    assert out.returncode == 0 and "NOT FOUND" not in out.stdout


@needs
def test_the_key_was_committed_before_the_score():
    def first_commit(rel: str) -> str:
        return subprocess.run(["git", "log", "--diff-filter=A", "--format=%ct", "--", rel], capture_output=True, text=True, cwd=ROOT).stdout.split()[-1]

    try:
        key_t = int(first_commit("reports/test-c/diagnosis_test_c_key.json"))
        score_t = int(first_commit("reports/test-c/diagnosis_test_c_score.json"))
    except IndexError:
        pytest.skip("the score is not committed yet in this checkout")
    assert key_t <= score_t


@needs
def test_set_metrics_carries_test_c():
    m = json.loads((ROOT / "reports/dev/v18/set_metrics.json").read_text(encoding="utf-8"))["sets"]["test_c"]
    assert (m["n"], m["ran"], m["non_running"], m["diagnosed"]) == (10, 1, 9, 9) and m["recovery"] == {"as_published_failed": 9, "recovered_after_repair": 1}
