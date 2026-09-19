"""§4 architecture: `POST /runs`. Real S1 intake validation + repo clone +
dependency parsing runs synchronously today; recon/planning/sandbox/repair
(Nemotron + Token Factory Sandboxes) are wired in as those services become
credential-backed — this endpoint never fakes those later stages.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Run
from app.schemas import RunCreate, RunOut
from app.services import intake

router = APIRouter()


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
