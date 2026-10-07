"""harness-v1.8, Phase 4 (preparation): the TEST-C registration (`backend/app/batch/corpus_v4/prereg.json`), its draw (`scripts/draw_corpus.py draw-v4`), the batch driver's corpus-v4 support and
the runner (`reports/test-c/run_test_c.py`). Offline: nothing here draws, runs or spends; the draw and the run happen after the harness-v1.8.0 tag.

What these tests pin: the registration is the committed one (its sha256), the draw order follows from the seed, the firewall knows every earlier set and every DEV entry, NOTHING in the
eligibility rules looks at what a command needs (the owner's requirement: no filter on fixability), and the runner's constants are the registration's."""

from __future__ import annotations

import json
import random
import re
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "reports" / "test-c"))
import draw_corpus as dc  # noqa: E402
import run_test_c as rc  # noqa: E402

PREREG = json.loads(dc.V4_PREREG.read_text(encoding="utf-8"))


def test_the_registration_is_the_committed_one():
    assert dc.sha256_file(dc.V4_PREREG) == dc.V4_PREREG_SHA.read_text(encoding="utf-8").split()[0]
    assert (PREREG["corpus_version"], PREREG["name"], PREREG["seed"], PREREG["target_eligible"], PREREG["registered"]) == ("corpus-v4", "TEST-C", 20261007, 10, "2026-10-07")
    frame = PREREG["frame_and_population"]
    assert dc.sha256_file(ROOT / frame["population_file"]) == frame["population_sha256"] and frame["population_size"] == 5485
    if not any(dc.V4_DIR.joinpath(name).exists() for name in PREREG["outputs"]):
        assert dc.check_v4_registration()["name"] == "TEST-C"  # the draw's own refusal check passes while nothing is drawn


def test_the_draw_order_follows_from_the_seed():
    order = list(range(5485))
    random.Random(PREREG["seed"]).shuffle(order)
    assert order[:8] == [693, 2650, 1862, 3245, 2547, 3304, 179, 1559]


def test_the_eligibility_is_corpus_v2s_and_looks_at_nothing_a_command_needs():
    """Owner, 2026-10-07: the selection rule must not filter on fixability (no excluding docker, conda or licensed-data repositories)."""
    v2 = json.loads((ROOT / "backend/app/batch/corpus_v2/prereg.json").read_text(encoding="utf-8"))["eligibility"]
    assert PREREG["eligibility"]["reference"] == "backend/app/batch/corpus_v2/prereg.json"
    assert "no_fixability_filter" in PREREG["eligibility"] and "docker" in PREREG["eligibility"]["no_fixability_filter"]
    # the exclusion regexes of the rules draw-v4 applies (corpus-v2's, which draw-v4 refuses to differ from) name no need, no resource, no data, no licence, no credential:
    rules = json.dumps(v2["exclusion_rules"]).lower() + v2["placeholder_regex"].lower() + v2["command_regex"].lower()
    for forbidden in ("docker", "conda", "gpu", "cuda", "dataset", "licen", "credential", "api_key", "display", "xvfb", "mujoco", "nltk"):
        assert forbidden not in rules, forbidden
    from app.batch import command_rules

    assert set(command_rules.RULES) == {"R1_INSTALL", "R2_DOWNLOAD", "R3_PREPROCESS", "R4_SETUP_SCRIPT", "R5_PLACEHOLDER"}  # only 'is this a RUN of the code', as in corpus-v1


def test_the_firewall_knows_every_earlier_set_and_every_dev_entry():
    papers, repos = dc.v4_firewall()
    for cdir in (dc.CORPUS_DIR, dc.V2_DIR, dc.V3_DIR):
        for row in yaml.safe_load((cdir / "corpus.yaml").read_text(encoding="utf-8"))["repos"]:
            assert dc._repo_key(row["repo_url"]) in repos and row["paper_url"] in papers, row["name"]
    dev = {p.stem[3:].replace("__", "/", 1).lower() for p in (ROOT / "runs" / "dev_v18" / "round1").glob("*/[0-9][0-9]_*.json")}
    assert len(dev) == 16 and dev <= repos
    picks = json.loads((ROOT / "reports/live_scan/oos_v172/selection.json").read_text(encoding="utf-8"))["picks"]
    assert all(dc._repo_key(u) in repos for u in picks)


def test_the_runner_constants_are_the_registrations():
    assert (rc.CORPUS, rc.TAG, rc.N_ENTRIES, rc.ENTRY_CAP_USD, rc.CAP_USD) == ("corpus-v4", "harness-v1.8.0", PREREG["target_eligible"], PREREG["run"]["entry_cap_usd"],
                                                                              PREREG["run"]["test_c_cap_usd"])
    assert rc.PREREG == dc.V4_PREREG
    assert rc._selftest() == 0
    cmd = (ROOT / "reports/test-c/launch_test_c.cmd").read_text(encoding="utf-8")
    assert "--cap-usd 100 --entry-cap-usd 2.50" in cmd and "harness-v1.8.0" in cmd and "RERUN_test_c" in cmd


def test_the_batch_driver_accepts_corpus_v4_and_its_sealed_files():
    import run_corpus_v1_batch as drv

    assert "backend/app/batch/corpus_v4/prereg.json" in drv.SEALED_FILES and "backend/app/batch/corpus_v4/prereg.sha256" in drv.SEALED_FILES
    assert any(rx.match("backend/app/batch/corpus_v4/corpus.yaml") for rx in drv.DATA_ALLOWLIST)  # the draw outputs may be committed after the tag, as TEST-B's were
    assert not any(rx.match("backend/app/batch/corpus_v4/prereg.json") for rx in drv.DATA_ALLOWLIST)  # the registration may not
    assert drv.corpus_dir("corpus-v4") == dc.V4_DIR and drv.out_dir("corpus-v4", "harness-v1.8.0", "treatment").as_posix().endswith("runs/corpus_v4_batch/harness-v1.8.0/treatment")


def test_the_thresholds_are_the_dev_evidence_and_the_rubric_and_scorer_exist_before_the_draw():
    t = PREREG["analysis"]["thresholds_from_dev_evidence"]
    assert re.search(r"9 of 18", t["dev_evidence"]["actionable_diagnosis_as_the_dev_runs_stored_it"]) and re.search(r"16 of 18", t["dev_evidence"]["actionable_diagnosis_as_the_current_rules_derive_it"])
    assert any("50 percent" in c and "DIAGNOSIS" in c for c in t["claims"]) and any("3 of 10" in c for c in t["claims"])
    for rel in ("reports/dev/v18/DIAGNOSIS_RUBRIC.md", "reports/dev/v18/score_diagnosis.py", "reports/dev/v18/set_metrics.py", "reports/dev/v18/diagnosis_dev_key.json"):
        assert (ROOT / rel).is_file(), rel
    dev = json.loads((ROOT / "reports/dev/v18/diagnosis_dev_score.json").read_text(encoding="utf-8"))["results"]
    assert (dev["stored"]["actionable"], dev["derived"]["actionable"], dev["stored"]["n"]) == (9, 16, 18)  # the figures the registration quotes
    m = json.loads((ROOT / "reports/dev/v18/set_metrics.json").read_text(encoding="utf-8"))["sets"]
    assert m["dev_v18_corpus"]["ran"] == 2 and m["dev_v18_corpus"]["n"] == 16 and m["test"]["ran"] == 1 and m["test_b"]["ran"] == 1
