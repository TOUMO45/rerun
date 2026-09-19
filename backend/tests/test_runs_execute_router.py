"""Tests for POST /runs/{id}/execute and GET /runs/{id}/certificate.

No live Nebius call: `run_pipeline` itself is already proven end-to-end
against the real classifier/tamper_gate in test_orchestrator.py. What's
tested here is the router's OWN responsibility — the 503 fail-fast when
credentials are absent (real, no monkeypatch needed), and that a
successful PipelineResult is persisted into Run/RepairAttempt/Certificate
correctly (achieved by monkeypatching only the credential-gated boundary:
`run_pipeline` itself, plus `get_settings` to simulate credentials being
present without needing a real key).
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.services.orchestrator import AttemptRecord, PipelineResult


def test_execute_run_returns_503_when_nebius_not_configured(client, fake_paper_repo):
    created = client.post("/runs", json={"repo_url": str(fake_paper_repo)}).json()
    response = client.post(f"/runs/{created['id']}/execute")
    assert response.status_code == 503
    assert "not configured" in response.json()["detail"].lower()


def test_execute_run_negative_control_missing_run_404(client):
    response = client.post("/runs/does-not-exist/execute")
    assert response.status_code == 404


def test_execute_run_persists_pipeline_result(client, fake_paper_repo, monkeypatch):
    created = client.post("/runs", json={"repo_url": str(fake_paper_repo)}).json()

    class _FakeSettings:
        nebius_configured = True
        nebius_api_key = "fake-key-for-construction-only"
        nebius_base_url = "https://api.tokenfactory.nebius.com/v1"
        nebius_model_recon = "nvidia/nemotron-3-nano"
        nebius_model_repairer = "nvidia/nemotron-3-super"
        nebius_model_adjudicator = "nvidia/nemotron-3-ultra"
        nebius_model_planner = "nvidia/nemotron-3-super"
        nebius_sandbox_wall_clock_seconds = 60
        max_attempts_per_run = 3
        daily_cost_ceiling_usd = 25.0

    fake_result = PipelineResult(
        verdict="RUNS_AFTER_REPAIR",
        taxonomy_code="DEP_MISSING",
        indeterminate_reason="",
        attempts=(
            AttemptRecord(1, "--- a/x\n+++ b/x\n", "PASS", (), 0, "ok", ""),
        ),
        build_plan={"base_image": "python:3.11-slim"},
        full_log="[fake] pipeline ran",
        certificate_prose="It worked after one repair. Verifies that the artifact executes.",
        reproduction_passport_hash="a" * 64,
        timestamp=datetime.now(timezone.utc).isoformat(),
        repo_url=str(fake_paper_repo),
        commit_sha="b" * 40,
    )

    monkeypatch.setattr("app.routers.runs.get_settings", lambda: _FakeSettings())
    monkeypatch.setattr("app.routers.runs.run_pipeline", lambda **kwargs: fake_result)

    response = client.post(f"/runs/{created['id']}/execute")
    assert response.status_code == 200
    body = response.json()
    assert body["verdict"] == "RUNS_AFTER_REPAIR"
    assert body["attempts_used"] == 1
    assert body["stage"] == "DONE"

    cert_response = client.get(f"/runs/{created['id']}/certificate")
    assert cert_response.status_code == 200
    cert = cert_response.json()
    assert cert["verdict"] == "RUNS_AFTER_REPAIR"
    assert cert["reproduction_passport_hash"] == "a" * 64


def test_get_certificate_404_before_execution(client, fake_paper_repo):
    created = client.post("/runs", json={"repo_url": str(fake_paper_repo)}).json()
    response = client.get(f"/runs/{created['id']}/certificate")
    assert response.status_code == 404
