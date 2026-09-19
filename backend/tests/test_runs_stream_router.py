"""Tests for GET /runs/{id}/stream — the architecture's actual named SSE
endpoint (§4). No live Nebius call: `run_pipeline` is monkeypatched, same
discipline as test_runs_execute_router.py, but here it's scripted to call
`on_event` itself (simulating real progress) so these tests prove the
background-thread-to-SSE-stream wiring actually delivers events live, not
just that the final result eventually shows up.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from app.services.orchestrator import PipelineResult


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


class _NotConfiguredSettings(_FakeSettings):
    nebius_configured = False


def _parse_sse_events(body: str) -> list[dict]:
    events = []
    for chunk in body.split("\n\n"):
        chunk = chunk.strip()
        if not chunk:
            continue
        assert chunk.startswith("data: ")
        events.append(json.loads(chunk[len("data: ") :]))
    return events


def test_stream_returns_404_for_missing_run(client):
    response = client.get("/runs/does-not-exist/stream")
    assert response.status_code == 404


def test_stream_returns_503_when_not_configured_and_not_yet_run(client, fake_paper_repo, monkeypatch):
    created = client.post("/runs", json={"repo_url": str(fake_paper_repo)}).json()
    monkeypatch.setattr("app.routers.runs.get_settings", lambda: _NotConfiguredSettings())

    response = client.get(f"/runs/{created['id']}/stream")
    assert response.status_code == 503


def test_stream_refuses_to_start_a_second_execution_while_one_is_already_executing(client, fake_paper_repo):
    """Companion to test_execute_run_refuses_to_re_execute_an_already_done_run:
    a run already marked EXECUTING (e.g. a prior /stream or /execute call
    kicked off a still-running background execution, and the page was
    reloaded and 'Start reproduction run' clicked again) must not have a
    second background execution started against it, racing the first one
    to persist the same run's one-to-one certificate.
    """
    # Imported from app.routers.runs, NOT app.db: the `client` fixture
    # monkeypatches app.routers.runs.SessionLocal to the test's isolated
    # in-memory engine (see conftest.py) — importing SessionLocal fresh
    # from app.db here would bypass that and hit the real, uninitialized
    # production DB instead, the exact bug already found once this
    # session for the stream route's own background worker.
    from app.models import Run
    from app.routers.runs import SessionLocal

    created = client.post("/runs", json={"repo_url": str(fake_paper_repo)}).json()

    db = SessionLocal()
    run = db.get(Run, created["id"])
    run.stage = "EXECUTING"
    db.add(run)
    db.commit()
    db.close()

    response = client.get(f"/runs/{created['id']}/stream")
    assert response.status_code == 409
    assert "already executing" in response.json()["detail"].lower()


def test_stream_delivers_live_events_from_a_background_execution(client, fake_paper_repo, monkeypatch):
    created = client.post("/runs", json={"repo_url": str(fake_paper_repo)}).json()

    def _fake_run_pipeline_emitting_events(**kwargs):
        on_event = kwargs["on_event"]
        on_event("[recon] calling Nemotron Nano")
        on_event("[sandbox] exit_code=0")
        return PipelineResult(
            verdict="RUNS_CLEAN",
            taxonomy_code=None,
            indeterminate_reason="",
            attempts=(),
            build_plan={},
            full_log="[recon] calling Nemotron Nano\n[sandbox] exit_code=0",
            certificate_prose="ok",
            reproduction_passport_hash="a" * 64,
            timestamp=datetime.now(timezone.utc).isoformat(),
            repo_url=kwargs["repo_url"],
            commit_sha=kwargs["commit_sha"],
        )

    monkeypatch.setattr("app.routers.runs.get_settings", lambda: _FakeSettings())
    monkeypatch.setattr("app.routers.runs.run_pipeline", _fake_run_pipeline_emitting_events)

    response = client.get(f"/runs/{created['id']}/stream")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")

    events = _parse_sse_events(response.text)
    lines = [e["line"] for e in events if "line" in e]
    assert "[recon] calling Nemotron Nano" in lines
    assert "[sandbox] exit_code=0" in lines
    assert events[-1] == {"done": True}

    # The background execution must have actually persisted the result —
    # not just streamed events into the void.
    run_after = client.get(f"/runs/{created['id']}").json()
    assert run_after["stage"] == "DONE"
    assert run_after["verdict"] == "RUNS_CLEAN"


def test_stream_replays_full_log_without_reexecuting_an_already_done_run(client, fake_paper_repo, monkeypatch):
    created = client.post("/runs", json={"repo_url": str(fake_paper_repo)}).json()

    call_count = {"n": 0}

    def _fake_run_pipeline(**kwargs):
        call_count["n"] += 1
        return PipelineResult(
            verdict="RUNS_CLEAN",
            taxonomy_code=None,
            indeterminate_reason="",
            attempts=(),
            build_plan={},
            full_log="[intake] cloned\n[recon] entrypoint=train.py",
            certificate_prose="ok",
            reproduction_passport_hash="a" * 64,
            timestamp=datetime.now(timezone.utc).isoformat(),
            repo_url=kwargs["repo_url"],
            commit_sha=kwargs["commit_sha"],
        )

    monkeypatch.setattr("app.routers.runs.get_settings", lambda: _FakeSettings())
    monkeypatch.setattr("app.routers.runs.run_pipeline", _fake_run_pipeline)

    # Finish it once via the synchronous endpoint.
    client.post(f"/runs/{created['id']}/execute")
    assert call_count["n"] == 1

    # Now stream it — must replay, not call run_pipeline a second time.
    response = client.get(f"/runs/{created['id']}/stream")
    assert response.status_code == 200
    events = _parse_sse_events(response.text)
    lines = [e["line"] for e in events if "line" in e]
    assert "[intake] cloned" in lines
    assert "[recon] entrypoint=train.py" in lines
    assert events[-1] == {"done": True, "verdict": "RUNS_CLEAN"}
    assert call_count["n"] == 1  # still 1 — no re-execution


def test_stream_surfaces_an_unexpected_worker_error_instead_of_hanging(client, fake_paper_repo, monkeypatch):
    def _exploding_pipeline(**kwargs):
        raise RuntimeError("boom from the pipeline")

    monkeypatch.setattr("app.routers.runs.get_settings", lambda: _FakeSettings())
    monkeypatch.setattr("app.routers.runs.run_pipeline", _exploding_pipeline)

    created = client.post("/runs", json={"repo_url": str(fake_paper_repo)}).json()
    response = client.get(f"/runs/{created['id']}/stream")

    assert response.status_code == 200
    events = _parse_sse_events(response.text)
    lines = [e["line"] for e in events if "line" in e]
    assert any("boom from the pipeline" in line for line in lines)
    assert events[-1] == {"done": True}
