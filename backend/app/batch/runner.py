"""Batch Lab runner (RERUN directive §7): runs the 20-repo corpus via
Nebius Serverless Jobs and aggregates results into `batch_results.json`.

**Confidence level, stated honestly (unlike sandbox.py and model_client.py,
which were verified against real installed SDK source per §2.4):** no
Python SDK with ready-made Job-management bindings was found installed
(the `nebius` PyPI package's `nebius.api.nebius.ai.v1` module exists but
is an empty stub in the installed version — inspected directly, not
assumed). This module's REST request shape is instead sourced from
`docs.nebius.com/serverless/jobs/manage`'s own quoted curl examples:

    POST https://api.nebius.cloud/ai/v1/jobs
    Authorization: Bearer <access_token>
    {"metadata": {"parentId": "<project_id>", "name": "..."},
     "spec": {"image": "...", "containerCommand": ..., "args": [...],
              "resources": {"platform": "...", "preset": "..."},
              "timeout": "..."}}

    GET https://api.nebius.cloud/ai/v1/jobs?parentId=<project_id>
    Authorization: Bearer <access_token>

This has NOT been exercised against a live account — the exact response
field names for job status/state were not shown in the documentation
fetched during this session. Treat `NebiusJobsClient` as a best-effort,
real-shaped client that needs a live smoke test (create one job, poll it,
read its logs) before the first real Batch Lab run, not as verified
integration code the way sandbox.py is.

**Also not yet built:** the actual job container entrypoint — a script
that, inside the Nebius Job's container, clones one corpus repo and runs
RERUN's own single-repo pipeline (`orchestrator.run_pipeline`), then
prints a JSON verdict RERUN can read back. `run_single_repo_job()` below
is the seam where that would plug in; `aggregate_batch_results()` is the
part that IS fully real and tested today — it only needs a list of
per-repo result dicts (however they were obtained) to produce a valid,
internally-consistent `batch_results.json`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.batch.corpus import CorpusEntry


class JobsApiError(RuntimeError):
    pass


@dataclass(frozen=True)
class JobSpec:
    name: str
    image: str
    container_command: str
    args: tuple[str, ...]
    platform: str = "cpu-e2"
    preset: str = "4vcpu-16gb"
    timeout: str = "1h"
    env: dict[str, str] | None = None


class _HttpClientLike(Protocol):
    """The minimal surface this module needs from an HTTP client — real
    `httpx.Client` satisfies this; tests inject a small fake."""

    def post(self, url: str, *, headers: dict, json: dict) -> "_HttpResponseLike": ...
    def get(self, url: str, *, headers: dict) -> "_HttpResponseLike": ...


class _HttpResponseLike(Protocol):
    status_code: int

    def json(self) -> dict: ...


@dataclass(frozen=True)
class NebiusJobsClient:
    http: _HttpClientLike
    access_token: str
    project_id: str
    base_url: str = "https://api.nebius.cloud/ai/v1"

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.access_token}", "Content-Type": "application/json"}

    def create_job(self, spec: JobSpec) -> str:
        payload = {
            "metadata": {"parentId": self.project_id, "name": spec.name},
            "spec": {
                "image": spec.image,
                "containerCommand": spec.container_command,
                "args": list(spec.args),
                "resources": {"platform": spec.platform, "preset": spec.preset},
                "timeout": spec.timeout,
                **({"env": spec.env} if spec.env else {}),
            },
        }
        response = self.http.post(f"{self.base_url}/jobs", headers=self._headers(), json=payload)
        if response.status_code >= 400:
            raise JobsApiError(f"job creation failed ({response.status_code}): {response.json()}")
        body = response.json()
        job_id = body.get("metadata", {}).get("id")
        if not job_id:
            raise JobsApiError(f"job creation response had no metadata.id: {body}")
        return job_id

    def get_job(self, job_id: str) -> dict:
        response = self.http.get(f"{self.base_url}/jobs/{job_id}", headers=self._headers())
        if response.status_code >= 400:
            raise JobsApiError(f"could not fetch job '{job_id}' ({response.status_code}): {response.json()}")
        return response.json()


def run_single_repo_job(client: NebiusJobsClient, entry: CorpusEntry, rerun_image: str) -> str:
    """Submit one Nebius Job that runs RERUN's own pipeline against a
    single corpus entry, pinned to its recorded commit SHA. Returns the
    job id. See module docstring: the container's actual entrypoint
    script (clone at `entry.commit_sha`, run `orchestrator.run_pipeline`,
    print a JSON verdict) does not exist yet — this only submits the job
    request in the real, documented shape.
    """
    spec = JobSpec(
        name=f"rerun-batch-{entry.name}",
        image=rerun_image,
        container_command="python",
        args=("-m", "app.batch.run_single_repo", "--repo-url", entry.repo_url, "--commit-sha", entry.commit_sha),
    )
    return client.create_job(spec)


def aggregate_batch_results(per_repo_results: list[dict]) -> dict:
    """Pure aggregation: turn a list of per-repo result dicts (each with
    at minimum `name` and `verdict`, and optionally `taxonomy_code`,
    `attempts_used`, `duration_seconds`) into the exact `batch_results.json`
    shape `routers/batch.py::load_batch_results` validates and S4 renders.
    Fully real and tested regardless of how the per-repo results were
    obtained (a live Nebius Job today, a fixture in a test, or a future
    local-sandbox fallback).
    """
    n = len(per_repo_results)
    if n == 0:
        raise ValueError("cannot aggregate an empty batch — refuses to produce a fake 0/0 result")

    counts = {"RUNS_CLEAN": 0, "RUNS_AFTER_REPAIR": 0, "BLOCKED": 0, "INDETERMINATE": 0}
    failure_breakdown: dict[str, int] = {}
    durations: list[float] = []

    for repo in per_repo_results:
        verdict = repo["verdict"]
        if verdict in counts:
            counts[verdict] += 1
        taxonomy_code = repo.get("taxonomy_code")
        if taxonomy_code:
            failure_breakdown[taxonomy_code] = failure_breakdown.get(taxonomy_code, 0) + 1
        if repo.get("duration_seconds") is not None:
            durations.append(repo["duration_seconds"])

    recovered = counts["RUNS_CLEAN"] + counts["RUNS_AFTER_REPAIR"]
    durations.sort()
    median_duration = durations[len(durations) // 2] if durations else None

    return {
        "n": n,
        "recovery_rate": recovered / n,
        "runs_clean": counts["RUNS_CLEAN"],
        "runs_after_repair": counts["RUNS_AFTER_REPAIR"],
        "blocked": counts["BLOCKED"],
        "indeterminate": counts["INDETERMINATE"],
        "median_time_to_first_failure_seconds": median_duration,
        "estimated_researcher_hours_saved": counts["RUNS_AFTER_REPAIR"] * 3,
        "failure_breakdown": failure_breakdown,
        "repos": per_repo_results,
    }
