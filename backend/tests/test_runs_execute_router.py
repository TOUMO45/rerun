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

from app.services.cost_guard import get_shared_cost_guard
from app.services.orchestrator import AttemptRecord, PipelineResult
from app.services.passport import verify_certificate


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
        tavily_configured = False
        nebius_sandbox_image = "python:3.11-slim"

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


def test_certificate_fetched_via_api_still_verifies_against_its_own_passport_hash(client, fake_paper_repo, monkeypatch):
    """§13 definition-of-done item 6: a downloaded certificate's hash must
    verify independently. This specifically guards against the timestamp
    silently being reformatted on its way through the DB and back out as
    JSON (e.g. a DateTime column re-serializing microseconds/timezone
    differently than the exact string that was originally hashed) —
    which would make every real certificate fail its own verification.
    """
    created = client.post("/runs", json={"repo_url": str(fake_paper_repo)}).json()
    # execute_run() always re-clones and overwrites run.commit_sha with
    # whatever that real clone reports — under real (non-monkeypatched)
    # operation this is always identical to what it passes into
    # run_pipeline() as commit_sha, which the orchestrator just echoes
    # back unchanged in PipelineResult.commit_sha. To keep that same
    # invariant true here (only run_pipeline itself is being replaced),
    # this test uses the real commit sha rather than an arbitrary one.
    import subprocess

    real_commit_sha = subprocess.run(
        ["git", "-C", str(fake_paper_repo), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

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
        tavily_configured = False
        nebius_sandbox_image = "python:3.11-slim"

    fake_result = PipelineResult(
        verdict="RUNS_CLEAN",
        taxonomy_code=None,
        indeterminate_reason="",
        attempts=(),
        build_plan={"base_image": "python:3.11-slim"},
        full_log="[intake] cloned\n[recon] entrypoint=train.py",
        certificate_prose="Ran cleanly. Verifies that the artifact executes.",
        reproduction_passport_hash="placeholder",  # recomputed below to match this exact result
        timestamp=datetime.now(timezone.utc).isoformat(),
        repo_url=str(fake_paper_repo),
        commit_sha=real_commit_sha,
    )
    # Compute the real hash the same way orchestrator._finalize does, so
    # this test doesn't hand-wave the hash value.
    from app.services.passport import compute_passport_hash

    bundle = {
        "repo_url": fake_result.repo_url,
        "commit_sha": fake_result.commit_sha,
        "build_plan": fake_result.build_plan,
        "full_log": fake_result.full_log,
        "diffs": [],
        "verdict": fake_result.verdict,
        "timestamp": fake_result.timestamp,
    }
    fake_result = PipelineResult(**{**fake_result.__dict__, "reproduction_passport_hash": compute_passport_hash(bundle)})

    monkeypatch.setattr("app.routers.runs.get_settings", lambda: _FakeSettings())
    monkeypatch.setattr("app.routers.runs.run_pipeline", lambda **kwargs: fake_result)

    client.post(f"/runs/{created['id']}/execute")
    run = client.get(f"/runs/{created['id']}").json()
    cert = client.get(f"/runs/{created['id']}/certificate").json()

    reconstructed = {
        "repo_url": run["repo_url"],
        "commit_sha": run["commit_sha"],
        "build_plan": cert["build_plan"],
        "full_log": cert["full_log"],
        "diffs": cert["diffs"],
        "verdict": cert["verdict"],
        "timestamp": cert["timestamp"],
        "reproduction_passport_hash": cert["reproduction_passport_hash"],
    }
    assert verify_certificate(reconstructed) is True


def test_get_certificate_404_before_execution(client, fake_paper_repo):
    created = client.post("/runs", json={"repo_url": str(fake_paper_repo)}).json()
    response = client.get(f"/runs/{created['id']}/certificate")
    assert response.status_code == 404


def test_daily_cost_ceiling_is_shared_across_separate_execute_requests(client, fake_paper_repo, monkeypatch):
    """A *daily* ceiling means nothing if every request builds its own
    fresh CostGuard — this proves execute_run() uses the process-wide
    shared instance (cost_guard.get_shared_cost_guard()), not a new one
    per call, by recording real spend on the first request and asserting
    it's still visible to the guard on a second, independent request.
    """

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
        daily_cost_ceiling_usd = 100.0
        tavily_configured = False
        nebius_sandbox_image = "python:3.11-slim"

    def _fake_run_pipeline_that_spends(**kwargs):
        # Simulates what the real orchestrator does: record real spend
        # against whatever cost_guard it was actually handed.
        kwargs["cost_guard"].record_spend(3.0)
        return PipelineResult(
            verdict="RUNS_CLEAN",
            taxonomy_code=None,
            indeterminate_reason="",
            attempts=(),
            build_plan={},
            full_log="[fake]",
            certificate_prose="ok. Verifies that the artifact executes.",
            reproduction_passport_hash="a" * 64,
            timestamp=datetime.now(timezone.utc).isoformat(),
            repo_url=kwargs["repo_url"],
            commit_sha=kwargs["commit_sha"],
        )

    monkeypatch.setattr("app.routers.runs.get_settings", lambda: _FakeSettings())
    monkeypatch.setattr("app.routers.runs.run_pipeline", _fake_run_pipeline_that_spends)

    run_a = client.post("/runs", json={"repo_url": str(fake_paper_repo)}).json()
    run_b = client.post("/runs", json={"repo_url": str(fake_paper_repo)}).json()

    client.post(f"/runs/{run_a['id']}/execute")
    assert get_shared_cost_guard().spent_today_usd == 3.0

    client.post(f"/runs/{run_b['id']}/execute")
    # If execute_run built a fresh CostGuard each time, this would still
    # read 3.0 (or reset to 3.0) instead of accumulating — the whole point
    # of this test.
    assert get_shared_cost_guard().spent_today_usd == 6.0
