"""§4 architecture: `POST /runs` (S1 intake) and `POST /runs/{id}/execute`
(recon -> planner -> sandbox -> classifier -> repair loop -> adjudicator
-> passport, via `orchestrator.run_pipeline`). Execution requires real
Nebius Token Factory credentials — this endpoint returns a clear 503
rather than crashing or faking a result when they're absent, per §0's
"never fake a result."
"""

from __future__ import annotations

import tempfile
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_db
from app.models import Certificate, RepairAttempt, Run
from app.schemas import CertificateOut, RunCreate, RunOut
from app.services import intake
from app.services.cost_guard import CostGuard
from app.services.model_client import NebiusChatClient
from app.services.orchestrator import PipelineDeps, PipelineResult, run_pipeline

router = APIRouter()


def _build_pipeline_deps(settings: Settings) -> PipelineDeps:
    # One client instance is reused across roles: it's the same
    # base_url/api_key, only the `model` argument passed per-call differs
    # (NebiusChatClient.chat_completion takes model as a parameter).
    client = NebiusChatClient(api_key=settings.nebius_api_key, base_url=settings.nebius_base_url)
    return PipelineDeps(
        recon_client=client,
        recon_model=settings.nebius_model_recon,
        repair_client=client,
        repair_model=settings.nebius_model_repairer,
        adjudicator_client=client,
        adjudicator_model=settings.nebius_model_adjudicator,
        planner_client=client,
        planner_model=settings.nebius_model_planner,
        sandbox_api_key=settings.nebius_api_key,
        sandbox_wall_clock_seconds=settings.nebius_sandbox_wall_clock_seconds,
        max_attempts=settings.max_attempts_per_run,
    )


def _persist_pipeline_result(run: Run, result: PipelineResult, db: Session) -> None:
    run.stage = "DONE"
    run.verdict = result.verdict
    run.taxonomy_code = result.taxonomy_code
    run.indeterminate_reason = result.indeterminate_reason
    run.attempts_used = len(result.attempts)
    if result.build_plan is not None:
        run.build_plan = result.build_plan
    db.add(run)

    for attempt in result.attempts:
        db.add(
            RepairAttempt(
                run_id=run.id,
                attempt_number=attempt.attempt_number,
                diff_text=attempt.diff_text,
                gate_decision=attempt.gate_decision,
                gate_violations=list(attempt.gate_violations),
                exit_code=attempt.exit_code,
                stdout_tail=attempt.stdout_tail,
                stderr_tail=attempt.stderr_tail,
            )
        )

    db.add(
        Certificate(
            run_id=run.id,
            verdict=result.verdict,
            full_log=result.full_log,
            build_plan=result.build_plan or {},
            diffs=[a.as_dict() for a in result.attempts],
            reproduction_passport_hash=result.reproduction_passport_hash,
            timestamp=datetime.fromisoformat(result.timestamp),
        )
    )
    db.commit()
    db.refresh(run)


@router.post("/runs", response_model=RunOut, status_code=201)
def create_run(payload: RunCreate, db: Session = Depends(get_db)) -> Run:
    repo_url = payload.repo_url.strip()
    if not repo_url:
        raise HTTPException(status_code=422, detail="repo_url must not be empty")

    try:
        intake.validate_repo_accessible(repo_url)
    except intake.RepoPrivateError as exc:
        raise HTTPException(status_code=422, detail=f"private repo: {exc}") from exc
    except intake.RepoNotFoundError as exc:
        raise HTTPException(status_code=422, detail=f"repo not found: {exc}") from exc

    workdir = Path(tempfile.mkdtemp(prefix="rerun_run_"))
    try:
        result = intake.run_intake(repo_url, workdir)
    except intake.IntakeError as exc:
        raise HTTPException(status_code=422, detail=f"clone failed: {exc}") from exc

    if not intake.repo_has_python_code(workdir, result.dependency_files):
        raise HTTPException(status_code=422, detail="no Python code found in repo")

    run = Run(
        repo_url=repo_url,
        commit_sha=result.commit_sha,
        stage="RECON_PENDING",
        build_plan={
            "dependency_files": sorted(result.dependency_files.keys()),
            "declared_dependencies": sorted(result.declared_dependencies),
            "entrypoint_candidates": list(result.entrypoint_candidates),
            "notebook_paths": list(result.notebook_paths),
            "python_version_hint": result.python_version_hint,
        },
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


@router.get("/runs/{run_id}", response_model=RunOut)
def get_run(run_id: str, db: Session = Depends(get_db)) -> Run:
    run = db.get(Run, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"run '{run_id}' not found")
    return run


@router.post("/runs/{run_id}/execute", response_model=RunOut)
def execute_run(run_id: str, db: Session = Depends(get_db)) -> Run:
    run = db.get(Run, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"run '{run_id}' not found")

    settings = get_settings()
    if not settings.nebius_configured:
        raise HTTPException(
            status_code=503,
            detail="Nebius Token Factory is not configured (NEBIUS_API_KEY missing) — cannot execute this run",
        )

    workdir = Path(tempfile.mkdtemp(prefix="rerun_exec_"))
    try:
        intake_result = intake.run_intake(run.repo_url, workdir)
    except intake.IntakeError as exc:
        raise HTTPException(status_code=422, detail=f"re-clone for execution failed: {exc}") from exc

    deps = _build_pipeline_deps(settings)
    cost_guard = CostGuard(
        daily_cost_ceiling_usd=settings.daily_cost_ceiling_usd,
        max_attempts_per_run=settings.max_attempts_per_run,
    )

    result = run_pipeline(
        repo_url=run.repo_url,
        commit_sha=intake_result.commit_sha,
        workdir=workdir,
        intake_result=intake_result,
        deps=deps,
        cost_guard=cost_guard,
        run_id=run.id,
    )

    run.commit_sha = intake_result.commit_sha
    _persist_pipeline_result(run, result, db)
    return run


@router.get("/runs/{run_id}/certificate", response_model=CertificateOut)
def get_certificate(run_id: str, db: Session = Depends(get_db)) -> Certificate:
    run = db.get(Run, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"run '{run_id}' not found")
    if run.certificate is None:
        raise HTTPException(status_code=404, detail=f"run '{run_id}' has no certificate yet — has it been executed?")
    return run.certificate
