"""§7: "Never render a zero or a placeholder if batch_results.json is
missing — fail loudly in the UI instead." Tested at the API boundary."""

from __future__ import annotations

import json

import pytest

from app.routers.batch import BatchResultsUnavailable, load_batch_results


def test_missing_batch_results_fails_loudly(client, monkeypatch):
    monkeypatch.setattr(
        "app.routers.batch.get_settings",
        lambda: type("S", (), {"batch_results_path": "/definitely/does/not/exist.json"})(),
    )
    response = client.get("/batch/results")
    assert response.status_code == 502
    assert "not found" in response.json()["detail"].lower()


def test_present_valid_batch_results_loads(tmp_path):
    payload = {
        "n": 2,
        "recovery_rate": 0.5,
        "repos": [{"name": "a", "verdict": "RUNS_CLEAN"}, {"name": "b", "verdict": "BLOCKED"}],
    }
    path = tmp_path / "batch_results.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    loaded = load_batch_results(path)
    assert loaded == payload


def test_malformed_json_fails_loudly(tmp_path):
    path = tmp_path / "batch_results.json"
    path.write_text("{not valid json", encoding="utf-8")
    with pytest.raises(BatchResultsUnavailable):
        load_batch_results(path)


def test_inconsistent_n_fails_loudly(tmp_path):
    # §14 red-team: N must never be allowed to drift from the actual repo count.
    payload = {"n": 20, "recovery_rate": 0.9, "repos": [{"name": "a"}]}
    path = tmp_path / "batch_results.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(BatchResultsUnavailable, match="inconsistent"):
        load_batch_results(path)
