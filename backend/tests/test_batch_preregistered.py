"""GET /batch/preregistered: the Batch Lab's held-out results, read from the committed result files. Its counts must be the ones the guarded number source
(reports/phase-d/dev_rounds.json) gives, so the page can never show a number the texts do not."""

from __future__ import annotations

import json
from pathlib import Path

from app.routers import batch

ROOT = Path(__file__).resolve().parents[2]


def _dev_rounds() -> dict:
    return json.loads((ROOT / "reports" / "phase-d" / "dev_rounds.json").read_text(encoding="utf-8"))


def test_the_counts_are_the_guarded_numbers():
    sets = {s["key"]: s for s in batch.preregistered_results(ROOT)["sets"]}
    d = _dev_rounds()
    assert (sets["test_b"]["count"], sets["test_b"]["of"]) == (d["test_b"]["ran_count"]["value"], d["test_b"]["entries_total"]["value"])
    assert (sets["test"]["count"], sets["test"]["preregistered_count"]) == (d["test"]["confirmed_that_ran"]["value"], d["test"]["confirmed_count"]["value"])
    oos = d["scans"]["out_of_sample"]
    assert (sets["oos"]["count"], sets["oos"]["of"]) == (oos["did_their_work"]["value"], oos["repositories"]["value"])


def test_every_audit_correction_is_attached_to_its_entry_and_never_counted():
    sets = {s["key"]: s for s in batch.preregistered_results(ROOT)["sets"]}
    for (key, entry), (_, source) in batch.AUDITS.items():
        row = next(r for r in sets[key]["rows"] if r["entry"] == entry)
        assert not row["counts"] and row["note_source"] == source and (ROOT / source).is_file()
    assert [r["name"] for r in sets["test_b"]["rows"] if r["counts"]] == ["zcajiayin/L2D"]
    assert [r["name"] for r in sets["test"]["rows"] if r["counts"]] == ["alevine0/patchSmoothing"]


def test_the_sets_are_never_pooled_and_each_names_its_harness():
    doc = batch.preregistered_results(ROOT)
    assert [s["key"] for s in doc["sets"]] == ["test_c", "test_b", "oos", "test"]  # harness-v1.8: TEST-C first, the three frozen sets as before
    assert {s["harness"].split()[0] for s in doc["sets"]} == {"harness-v1.8.0", "harness-v1.7.2", "harness-v1.7.1"}
    assert "not rates" in doc["note"] and "not that a paper's result was reproduced" in doc["note"]


def test_a_missing_result_file_is_a_loud_502_not_an_empty_page(client, tmp_path, monkeypatch):
    monkeypatch.setattr(batch, "_repo_root", lambda: tmp_path)
    response = client.get("/batch/preregistered")
    assert response.status_code == 502 and "not found" in response.json()["detail"]


def test_the_route_serves_the_committed_results(client, monkeypatch):
    monkeypatch.setattr(batch, "_repo_root", lambda: ROOT)
    body = client.get("/batch/preregistered").json()
    assert [s["count"] for s in body["sets"]] == [1, 1, 0, 1]  # TEST-C, TEST-B, the out-of-sample scan, TEST
