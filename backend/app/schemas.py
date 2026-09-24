"""Pydantic request/response schemas for the FastAPI routes."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


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
    created_at: datetime
    updated_at: datetime


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


class HealthOut(BaseModel):
    status: str
    nebius_configured: bool
    tavily_configured: bool
    demo_mode: bool
