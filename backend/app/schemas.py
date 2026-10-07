"""Pydantic request/response schemas for the FastAPI routes."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, computed_field


class RunCreate(BaseModel):
    repo_url: str = Field(..., description="Public GitHub repo URL to attempt reproduction on (S1 intake)")


class RepairAttemptOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    attempt_number: int
    gate_decision: str
    gate_violations: list[dict] | None
    exit_code: int | None
    diff_text: str


class RunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    repo_url: str
    commit_sha: str | None
    stage: str
    verdict: str | None
    taxonomy_code: str | None
    indeterminate_reason: str | None
    attempts_used: int
    # DEMO mode: the committed record this run replays (repository-relative path); null for a live run.
    demo_source: str | None = None
    created_at: datetime
    updated_at: datetime


class RunListItem(BaseModel):
    """One row of `GET /runs`: cheap (no certificate body), enough for the Gallery."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    repo_url: str
    commit_sha: str | None
    status: str
    verdict: str | None
    taxonomy_code: str | None
    demo_source: str | None
    created_at: datetime
    # harness-v1.7: the verdict with its labels (semantic change, RESOURCE-ADAPTED, memory hook, dependency change), from the certificate's attempts
    verdict_label: str | None = None


class RunListOut(BaseModel):
    runs: list[RunListItem]
    total: int
    limit: int
    offset: int


class CertificateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    run_id: str
    verdict: str
    certificate_prose: str
    full_log: str
    build_plan: dict
    diffs: list
    reproduction_passport_hash: str
    timestamp: str
    bundle_version: int | None = 1
    baseline: dict | None = None
    recovery: bool | None = None
    tree_integrity: dict | None = None
    corpus_hash: str | None = None
    taxonomy_code: str | None = None
    indeterminate_reason: str | None = None
    error_chain: list | None = None
    first_repo_error: str | None = None
    last_error: str | None = None
    blocker_sources: dict | None = None

    # harness-v1.6: read off the stored fields above at response time (no column, no migration): the same pure
    # functions the orchestrator's certificate() uses, so the API and the downloaded certificate agree.
    @computed_field  # type: ignore[prop-decorator]
    @property
    def outcome_levels(self) -> dict:
        from app.services import outcome_levels

        return outcome_levels.compute(self._record())

    @computed_field  # type: ignore[prop-decorator]
    @property
    def verdict_label(self) -> str:
        """harness-v1.7 (R6, D-44): the verdict as printed: "RUNS_AFTER_REPAIR (semantic change)" when a gated model patch touched a listed call."""
        from app.services import outcome_levels

        return outcome_levels.verdict_label(self._record())

    @computed_field  # type: ignore[prop-decorator]
    @property
    def blocker(self) -> dict | None:
        from app.services import blocker

        out = blocker.report(self._record())
        return {**out, "sources": self.blocker_sources} if out is not None else None

    def _record(self) -> dict:
        # harness-v1.8: the same fields `orchestrator.derived_record` gives `blocker.report`, so the API and the downloaded certificate agree
        out = {"verdict": self.verdict, "error_chain": self.error_chain or [], "attempts": self.diffs or []}
        if self.indeterminate_reason:
            out["indeterminate_reason"] = self.indeterminate_reason
        if self.baseline:
            out["baseline"] = self.baseline
        return out


class HealthOut(BaseModel):
    status: str
    nebius_configured: bool
    tavily_configured: bool
    demo_mode: bool
