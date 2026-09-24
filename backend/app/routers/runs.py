"""§4 architecture: `POST /runs` (S1 intake), `GET /runs/{id}/stream` (the
SSE live-progress endpoint the architecture diagram actually names), and
`POST /runs/{id}/execute` (a synchronous alternative — useful for the
batch runner, curl, and tests — kept working exactly as before). Both
execution paths run the identical pipeline via `orchestrator.run_pipeline`
and persist through the same `_execute_pipeline_for_run` helper.
Execution requires real Nebius Token Factory credentials — a clear 503
rather than crashing or faking a result when they're absent, per §0's
"never fake a result."
"""

from __future__ import annotations

import json
import queue
import tempfile
import threading
from collections.abc import Callable
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import SessionLocal, get_db
from app.models import Certificate, RepairAttempt, Run
from app.schemas import CertificateOut, RunCreate, RunOut
from app.services import intake
from app.services.cost_guard import get_shared_cost_guard
from app.services.orchestrator import PipelineResult, build_pipeline_deps, run_pipeline

router = APIRouter()


def _sse_event(data: dict) -> str:
    return f"data: {json.dumps(data)}\n\n"


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
            certificate_prose=result.certificate_prose,
            full_log=result.full_log,
            build_plan=result.build_plan or {},
            diffs=[a.as_dict() for a in result.attempts],
            reproduction_passport_hash=result.reproduction_passport_hash,
            timestamp=result.timestamp,
            bundle_version=result.bundle_version,
            baseline=result.baseline,
            recovery=result.recovery,
            tree_integrity=result.tree_integrity,
            corpus_hash=result.corpus_hash,
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
    finally:
        # This clone was only ever needed to build the build_plan summary
        # above — POST /runs/{id}/execute clones fresh again later.
        # Leaving it on disk would leak a full git clone per S1 intake,
        # unbounded, on every real request.
        intake.cleanup_workdir(workdir)


@router.get("/runs/{run_id}", response_model=RunOut)
def get_run(run_id: str, db: Session = Depends(get_db)) -> Run:
    run = db.get(Run, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"run '{run_id}' not found")
    return run


def _execute_pipeline_for_run(
    run: Run,
    db: Session,
    on_event: Callable[[str], None] | None = None,
) -> Run:
    """The real execute-and-persist logic, shared by the synchronous
    `POST /execute` route (passes its own request-scoped `db`) and the
    `GET /stream` route's background thread (passes its own freshly
    created session, since a background thread must never touch a
    request-scoped session that FastAPI may close the moment the route
    handler returns). `on_event`, if given, is forwarded straight into
    `orchestrator.run_pipeline` for real-time progress.

    Refuses to run a second time for a run that is already `DONE` or
    already `EXECUTING`: `Certificate.run_id` is a one-to-one DB column
    (`unique=True`), so a second execution's `_persist_pipeline_result`
    would crash with an unhandled `IntegrityError` on insert — reproduced
    live by simply calling `POST /execute` twice on the same run, no
    concurrency even required. The `EXECUTING` marker is set and committed
    immediately, before any real work starts, and reset back to
    `RECON_PENDING` if execution fails for any reason, so a genuine
    failure can still be retried. This narrows, but does not perfectly
    eliminate, the window for two truly simultaneous requests to both pass
    the check before either commits — closing that completely would need
    a compare-and-swap UPDATE or row-level locking, out of scope for this
    fix; see DECISIONS.md.
    """
    if run.stage in ("EXECUTING", "DONE"):
        raise HTTPException(
            status_code=409,
            detail=(
                f"run '{run.id}' is already {'executing' if run.stage == 'EXECUTING' else 'done'} — "
                "refusing a duplicate/overlapping execution"
            ),
        )

    settings = get_settings()
    if not settings.nebius_configured:
        raise HTTPException(
            status_code=503,
            detail="Nebius Token Factory is not configured (NEBIUS_API_KEY missing) — cannot execute this run",
        )

    run.stage = "EXECUTING"
    db.add(run)
    db.commit()

    workdir = Path(tempfile.mkdtemp(prefix="rerun_exec_"))
    try:
        try:
            intake_result = intake.run_intake(run.repo_url, workdir)
        except intake.IntakeError as exc:
            raise HTTPException(status_code=422, detail=f"re-clone for execution failed: {exc}") from exc

        deps = build_pipeline_deps(settings)
        # A process-wide singleton — a *daily* ceiling means nothing if
        # every request gets its own fresh guard (see
        # cost_guard.get_shared_cost_guard).
        cost_guard = get_shared_cost_guard()

        result = run_pipeline(
            repo_url=run.repo_url,
            commit_sha=intake_result.commit_sha,
            workdir=workdir,
            intake_result=intake_result,
            deps=deps,
            cost_guard=cost_guard,
            run_id=run.id,
            on_event=on_event,
        )

        run.commit_sha = intake_result.commit_sha
        _persist_pipeline_result(run, result, db)
        return run
    except Exception:
        # A failed commit (e.g. a genuinely concurrent execution losing
        # the narrow race noted above) leaves the session in a state that
        # requires a rollback before it can be used again — without this,
        # the recovery commit below would itself raise (a
        # PendingRollbackError), masking the real error instead of
        # resetting the run for a clean retry.
        db.rollback()
        run.stage = "RECON_PENDING"
        db.add(run)
        db.commit()
        raise
    finally:
        # The whole pipeline's file-level work happens against this
        # checkout (including applying gate-approved patches) — once
        # run_pipeline has returned and the certificate is persisted,
        # nothing needs the clone on disk anymore. Leaving it would leak
        # a full git clone per execution, unbounded, on every real run.
        intake.cleanup_workdir(workdir)


@router.post("/runs/{run_id}/execute", response_model=RunOut)
def execute_run(run_id: str, db: Session = Depends(get_db)) -> Run:
    run = db.get(Run, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"run '{run_id}' not found")
    return _execute_pipeline_for_run(run, db)


@router.get("/runs/{run_id}/stream")
def stream_run(run_id: str, db: Session = Depends(get_db)) -> StreamingResponse:
    """The architecture's actual named SSE endpoint (§4: `SSE
    /runs/{id}/stream`). If the run has already finished, replays its
    certificate's full_log as a burst of events instead of re-executing —
    a client that reloads S2 after completion still gets a real, honest
    timeline, not an error or an empty stream. If not yet executed, runs
    the real pipeline in a background thread and streams each log line as
    `orchestrator.run_pipeline`'s `on_event` callback produces it, live.

    If a previous call already kicked off a still-running execution for
    this run (e.g. the page was reloaded mid-run and "Start reproduction
    run" was clicked again), refuses with a 409 rather than starting a
    second background thread racing the first one to persist the same
    run's one-to-one certificate — see `_execute_pipeline_for_run`'s
    docstring. This does not (yet) reattach the new request to the
    already-running execution's live events; it just fails safely instead
    of corrupting state.
    """
    run = db.get(Run, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"run '{run_id}' not found")

    if run.stage == "EXECUTING":
        raise HTTPException(
            status_code=409,
            detail=f"run '{run.id}' is already executing — refusing to start a second, overlapping execution",
        )

    if run.stage == "DONE":
        # Extract plain values now, while this request's session is still
        # open — the generator below runs after this function returns,
        # by which point FastAPI may have already closed `db` and touching
        # a lazy-loaded ORM relationship then would raise.
        full_log = run.certificate.full_log if run.certificate else ""
        verdict = run.verdict

        def _replay():
            for line in full_log.split("\n"):
                if line:
                    yield _sse_event({"line": line})
            yield _sse_event({"done": True, "verdict": verdict})

        return StreamingResponse(_replay(), media_type="text/event-stream")

    settings = get_settings()
    if not settings.nebius_configured:
        raise HTTPException(
            status_code=503,
            detail="Nebius Token Factory is not configured (NEBIUS_API_KEY missing) — cannot execute this run",
        )

    event_queue: queue.Queue = queue.Queue()

    def _worker() -> None:
        worker_db = SessionLocal()
        try:
            worker_run = worker_db.get(Run, run_id)
            _execute_pipeline_for_run(worker_run, worker_db, on_event=event_queue.put)
        except HTTPException as exc:
            event_queue.put(f"[error] {exc.detail}")
        except Exception as exc:  # a live stream must never just hang forever on an unexpected error
            event_queue.put(f"[error] unexpected error: {exc}")
        finally:
            worker_db.close()
            event_queue.put(None)  # sentinel: no more events

    threading.Thread(target=_worker, daemon=True).start()

    def _stream():
        while True:
            item = event_queue.get()
            if item is None:
                break
            yield _sse_event({"line": item})
        yield _sse_event({"done": True})

    return StreamingResponse(_stream(), media_type="text/event-stream")


@router.get("/runs/{run_id}/certificate", response_model=CertificateOut)
def get_certificate(run_id: str, db: Session = Depends(get_db)) -> Certificate:
    run = db.get(Run, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"run '{run_id}' not found")
    if run.certificate is None:
        raise HTTPException(status_code=404, detail=f"run '{run_id}' has no certificate yet — has it been executed?")
    return run.certificate
