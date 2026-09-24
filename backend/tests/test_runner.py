"""Tests for batch/runner.py.

NebiusJobsClient is tested against a fake HTTP client (same DI pattern
used everywhere else credentials are the boundary) — no live Nebius Jobs
API call, and this module's request shape has NOT been verified against
a real account (see its module docstring). aggregate_batch_results is
fully real, pure logic and is tested as such.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.batch.corpus import load_corpus
from app.batch.runner import (
    JobSpec,
    JobsApiError,
    NebiusJobsClient,
    aggregate_batch_results,
    run_single_repo_job,
)


class _FakeResponse:
    def __init__(self, status_code: int, body: dict):
        self.status_code = status_code
        self._body = body

    def json(self) -> dict:
        return self._body


class _FakeHttp:
    def __init__(self, post_response: _FakeResponse | None = None, get_response: _FakeResponse | None = None):
        self.post_response = post_response
        self.get_response = get_response
        self.last_post: dict | None = None

    def post(self, url, *, headers, json):
        self.last_post = {"url": url, "headers": headers, "json": json}
        return self.post_response

    def get(self, url, *, headers):
        return self.get_response


# --- NebiusJobsClient: request shape ------------------------------------------


def test_create_job_sends_documented_request_shape():
    http = _FakeHttp(post_response=_FakeResponse(200, {"metadata": {"id": "job-123"}}))
    client = NebiusJobsClient(http=http, access_token="tok", project_id="proj-1")
    job_id = client.create_job(
        JobSpec(name="test-job", image="rerun:latest", container_command="python", args=("-m", "app"))
    )
    assert job_id == "job-123"
    assert http.last_post["url"] == "https://api.nebius.cloud/ai/v1/jobs"
    assert http.last_post["headers"]["Authorization"] == "Bearer tok"
    assert http.last_post["json"]["metadata"] == {"parentId": "proj-1", "name": "test-job"}
    assert http.last_post["json"]["spec"]["image"] == "rerun:latest"


def test_create_job_negative_control_error_status_raises():
    http = _FakeHttp(post_response=_FakeResponse(403, {"error": "forbidden"}))
    client = NebiusJobsClient(http=http, access_token="tok", project_id="proj-1")
    with pytest.raises(JobsApiError):
        client.create_job(JobSpec(name="x", image="y", container_command="python", args=()))


def test_create_job_negative_control_missing_job_id_raises():
    http = _FakeHttp(post_response=_FakeResponse(200, {"metadata": {}}))
    client = NebiusJobsClient(http=http, access_token="tok", project_id="proj-1")
    with pytest.raises(JobsApiError):
        client.create_job(JobSpec(name="x", image="y", container_command="python", args=()))


def test_get_job_returns_body():
    http = _FakeHttp(get_response=_FakeResponse(200, {"metadata": {"id": "job-1"}, "status": {"state": "RUNNING"}}))
    client = NebiusJobsClient(http=http, access_token="tok", project_id="proj-1")
    assert client.get_job("job-1")["status"]["state"] == "RUNNING"


def test_run_single_repo_job_pins_the_corpus_commit_sha():
    entries = load_corpus()
    entry = entries[0]
    http = _FakeHttp(post_response=_FakeResponse(200, {"metadata": {"id": "job-x"}}))
    client = NebiusJobsClient(http=http, access_token="tok", project_id="proj-1")
    run_single_repo_job(client, entry, rerun_image="rerun:latest")
    assert "--commit-sha" in http.last_post["json"]["spec"]["args"]
    assert entry.commit_sha in http.last_post["json"]["spec"]["args"]


def test_job_args_are_accepted_by_the_job_cli(monkeypatch):
    """Regression: the runner never passed --name, which the job's own CLI
    requires. Parse the exact args the runner builds with the real parser."""
    from dataclasses import replace

    from app.batch import run_single_repo as job

    entry = replace(load_corpus()[0], command="python train.py --epochs 3", command_source="README")
    http = _FakeHttp(post_response=_FakeResponse(200, {"metadata": {"id": "job-x"}}))
    run_single_repo_job(NebiusJobsClient(http=http, access_token="tok", project_id="p"), entry, rerun_image="rerun:latest")
    args = list(http.last_post["json"]["spec"]["args"])
    assert args[:2] == ["-m", "app.batch.run_single_repo"]
    seen = {}
    monkeypatch.setattr(job, "run_one_repo", lambda url, sha, name, command=None: seen.update(url=url, sha=sha, name=name, command=command) or {"ok": 1})
    assert job.main(args[2:]) == 0
    assert seen == {"url": entry.repo_url, "sha": entry.commit_sha, "name": entry.name, "command": "python train.py --epochs 3"}


# --- aggregate_batch_results: pure, real logic -------------------------------


def test_aggregate_batch_results_computes_recovery_rate_and_counts():
    results = [
        {"name": "a", "verdict": "RUNS_CLEAN"},
        {"name": "b", "verdict": "RUNS_AFTER_REPAIR", "taxonomy_code": "DEP_MISSING"},
        {"name": "c", "verdict": "BLOCKED", "taxonomy_code": "DATA_MISSING"},
        {"name": "d", "verdict": "INDETERMINATE"},
    ]
    batch = aggregate_batch_results(results)
    assert batch["n"] == 4
    assert batch["recovery_rate"] == pytest.approx(0.5)
    assert batch["runs_clean"] == 1
    assert batch["runs_after_repair"] == 1
    assert batch["blocked"] == 1
    assert batch["indeterminate"] == 1
    assert batch["failure_breakdown"] == {"DEP_MISSING": 1, "DATA_MISSING": 1}
    assert batch["repos"] == results


def test_aggregate_batch_results_n_always_matches_repo_count():
    # §14 red-team: N must never drift from the actual repo count.
    results = [{"name": f"r{i}", "verdict": "RUNS_CLEAN"} for i in range(7)]
    batch = aggregate_batch_results(results)
    assert batch["n"] == len(batch["repos"]) == 7


def test_aggregate_batch_results_estimate_is_derived_from_repair_count_only():
    results = [
        {"name": "a", "verdict": "RUNS_CLEAN"},
        {"name": "b", "verdict": "RUNS_AFTER_REPAIR"},
        {"name": "c", "verdict": "RUNS_AFTER_REPAIR"},
    ]
    batch = aggregate_batch_results(results)
    assert batch["estimated_researcher_hours_saved"] == 2 * 3


def test_aggregate_batch_results_negative_control_refuses_empty_batch():
    with pytest.raises(ValueError):
        aggregate_batch_results([])


def test_aggregate_batch_results_output_passes_the_real_batch_router_validation(tmp_path):
    # End-to-end: the aggregator's output must satisfy the exact same
    # validation routers/batch.py applies before S4 will render it.
    import json

    from app.routers.batch import load_batch_results

    results = [{"name": "a", "verdict": "RUNS_CLEAN"}, {"name": "b", "verdict": "BLOCKED", "taxonomy_code": "TIMEOUT"}]
    batch = aggregate_batch_results(results)
    path = tmp_path / "batch_results.json"
    path.write_text(json.dumps(batch), encoding="utf-8")
    loaded = load_batch_results(path)
    assert loaded["n"] == 2


# --- "Our fault" runs are excluded from the reproducibility denominator ----


def test_aggregate_excludes_our_fault_codes_from_the_denominator():
    results = [
        {"name": "a", "verdict": "RUNS_CLEAN"},
        {"name": "b", "verdict": "BLOCKED", "taxonomy_code": "DEP_MISSING"},
        {"name": "c", "verdict": "INDETERMINATE", "reason_code": "ENTRYPOINT_UNCLEAR"},
        {"name": "d", "verdict": "INDETERMINATE", "reason_code": "PIPELINE_ERROR:recon:ValueError"},
        {"name": "e", "verdict": "INDETERMINATE", "reason_code": "PIPELINE_ERROR:sandbox:RuntimeError"},
        {"name": "f", "verdict": "INDETERMINATE", "reason_code": "RECON_MODEL_ERROR"},
    ]
    batch = aggregate_batch_results(results)
    assert batch["n"] == 6 == len(batch["repos"])
    assert batch["n_measured"] == 3
    assert batch["excluded_our_fault"] == 3
    assert batch["our_fault_breakdown"] == {"PIPELINE_ERROR": 2, "RECON_MODEL_ERROR": 1}
    # 1 clean out of 3 measured — not 1 out of 6.
    assert batch["recovery_rate"] == pytest.approx(1 / 3)
    # ENTRYPOINT_UNCLEAR is a genuine (repo-side) INDETERMINATE and still counts.
    assert batch["indeterminate"] == 1


def test_aggregate_negative_control_repo_side_codes_stay_in_the_denominator():
    results = [
        {"name": "a", "verdict": "RUNS_CLEAN"},
        {"name": "b", "verdict": "INDETERMINATE", "reason_code": "ENTRYPOINT_UNCLEAR"},
    ]
    batch = aggregate_batch_results(results)
    assert batch["n_measured"] == 2
    assert batch["excluded_our_fault"] == 0
    assert batch["recovery_rate"] == pytest.approx(0.5)


def test_aggregate_refuses_a_rate_when_every_run_was_our_fault():
    results = [{"name": "a", "verdict": "INDETERMINATE", "reason_code": "PIPELINE_ERROR:planner:KeyError"}]
    with pytest.raises(ValueError):
        aggregate_batch_results(results)
