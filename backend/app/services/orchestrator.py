"""The orchestrator (RERUN directive §4 architecture, §5.4 repair loop).

Wires every other service into the actual end-to-end pipeline:

    recon -> (INDETERMINATE short-circuit, §6.1)
    planner -> build plan
    sandbox execute -> classifier (on failure)
    repair loop (max attempts, §5.4):
        repairer proposes a diff
        tamper_gate checks it (PURE, §2.1) — PASS: apply + re-execute
                                              REJECT: record + ask again
    adjudicator -> certificate prose (§4: "may only downgrade")
    passport -> sign the certificate bundle (§6.3)

This module takes every model/sandbox/diff-application call as an
injected callable/client rather than importing concrete implementations
directly (beyond the defaults), which is what makes the full loop
testable end-to-end with fakes for the model/sandbox layer while still
running the REAL, unmocked `classifier.py` and `tamper_gate.py` — the two
modules whose correctness this whole project's credibility rests on. It
does not touch the database; the FastAPI layer is responsible for
persisting the `PipelineResult` it returns.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from app.services import adjudicator, classifier, passport, planner, recon, repairer, tavily
from app.services import compute_sandbox
from app.services.cost_guard import CostGuard, CostLimitExceeded
from app.services.intake import RepoIntake, read_text_capped
from app.services.model_client import NebiusChatClient
from app.services.sandbox import SandboxError, SandboxRunResult, run_build_and_execute
from app.services.tamper_gate import check_patch


class OrchestratorError(RuntimeError):
    pass


@dataclass(frozen=True)
class AttemptRecord:
    attempt_number: int
    diff_text: str
    gate_decision: str  # "PASS" | "REJECT" | "DECLINED"
    gate_violations: tuple[dict, ...]
    exit_code: int | None
    stdout_tail: str
    stderr_tail: str
    tavily_sources: tuple[dict, ...] = ()

    def as_dict(self) -> dict:
        return {
            "attempt_number": self.attempt_number,
            "diff_text": self.diff_text,
            "gate_decision": self.gate_decision,
            "gate_violations": list(self.gate_violations),
            "exit_code": self.exit_code,
            "stdout_tail": self.stdout_tail,
            "stderr_tail": self.stderr_tail,
            "tavily_sources": list(self.tavily_sources),
        }


@dataclass(frozen=True)
class PipelineResult:
    verdict: str
    taxonomy_code: str | None
    indeterminate_reason: str
    attempts: tuple[AttemptRecord, ...]
    build_plan: dict | None
    full_log: str
    certificate_prose: str
    reproduction_passport_hash: str
    timestamp: str
    repo_url: str
    commit_sha: str


def _apply_diff_with_git(workdir: Path, diff_text: str) -> None:
    """Apply a unified diff to the real checkout using `git apply` — the
    standard, boring tool for this, rather than reimplementing a patch
    applier. Raises OrchestratorError if the patch doesn't apply cleanly
    (which should never happen for a gate-PASSed diff generated against
    this exact file content, but a corrupted/stale diff must not be
    silently ignored)."""
    result = subprocess.run(
        ["git", "apply", "--whitespace=nowarn", "-"],
        cwd=workdir,
        input=diff_text,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        raise OrchestratorError(f"gate-approved patch failed to apply: {result.stderr.strip()}")


def _collect_upload_files(workdir: Path) -> dict[str, Path]:
    """Gathers every real file under `workdir` for upload into the
    sandbox. Deliberately never follows a symlink — same reasoning as
    intake.py's `_walk_real_files` (see its comment): a bare `rglob`
    follows symlinked directories by default, and a repo could commit one
    pointing outside the cloned checkout, uploading arbitrary backend-host
    files into a sandbox the user's own output could then echo back.
    `os.walk(..., followlinks=False)` refuses to descend into a symlinked
    directory; the explicit `is_symlink()` check below also excludes a
    symlinked *file* found directly within a real directory.
    """
    files: dict[str, Path] = {}
    for dirpath, _dirnames, filenames in os.walk(workdir, followlinks=False):
        current = Path(dirpath)
        if ".git" in current.relative_to(workdir).parts:
            continue
        for filename in filenames:
            path = current / filename
            if not path.is_file() or path.is_symlink():
                continue
            files[str(path.relative_to(workdir).as_posix())] = path
    return files


def _target_file_for(classification: classifier.Classification, entrypoint: str, dependency_files: dict[str, str]) -> str:
    """Heuristic (documented, not a claim of correctness for every failure
    mode): dependency-family failures usually need a dependency file
    fixed, everything else defaults to the chosen entrypoint. A future
    pass could ask recon/the classifier for a more targeted file; this is
    intentionally simple and explicit rather than a hidden guess."""
    if classification.family == "Dependencies":
        for name in ("requirements.txt", "setup.py", "environment.yml", "pyproject.toml"):
            if name in dependency_files:
                return name
    return entrypoint


@dataclass
class PipelineDeps:
    """Injected dependencies for one pipeline run — the seam tests use to
    replace the model/sandbox layer with fakes while keeping the real
    classifier and tamper_gate in the loop."""

    recon_client: object
    recon_model: str
    repair_client: object
    repair_model: str
    adjudicator_client: object
    adjudicator_model: str
    sandbox_api_key: str
    sandbox_wall_clock_seconds: float
    # Token Factory's project id, passed alongside sandbox_api_key. Unused
    # by the Compute backend (see _make_compute_sandbox_runner below) —
    # Compute is a separate Nebius product/credential (this session's
    # Nebius integration audit; see DECISIONS.md).
    sandbox_project_id: str = ""
    planner_client: object = None
    planner_model: str | None = None
    max_attempts: int = 3
    sandbox_runner: callable = run_build_and_execute
    apply_diff: callable = _apply_diff_with_git
    # A real tavily.TavilyClient (or a fake satisfying its one-method
    # surface in tests) — None means "no Tavily configured," which is a
    # supported, non-fatal state (§5 cut ladder: repair still functions
    # without cited context). Deliberately a client, not a precomputed
    # string: a real query needs the failure's classification, which only
    # exists mid-repair-loop, not before the pipeline starts.
    tavily_client: object = None
    # NEBIUS_SANDBOX_IMAGE — the base image planner.build_plan() falls back
    # to when recon can't pin an exact Python version from the repo.
    default_sandbox_image: str = "python:3.11-slim"


def _make_compute_sandbox_runner(settings) -> callable:
    """Adapter so the Compute backend can be dropped into
    `PipelineDeps.sandbox_runner` without changing run_pipeline's call
    site: it accepts the same (api_key, project_id, base_image,
    install_commands, execute_command, wall_clock_seconds, upload_files)
    shape as sandbox.run_build_and_execute, but api_key/project_id here are
    Token Factory's and are intentionally unused — Compute authenticates
    with a separate service-account credential (settings.nebius_compute_*),
    bound here via closure instead."""

    def _run(
        *,
        api_key: str,  # noqa: ARG001 - Token Factory credential, not used by Compute
        project_id: str,  # noqa: ARG001 - Token Factory credential, not used by Compute
        base_image: str,
        install_commands,
        execute_command: str,
        wall_clock_seconds: float,
        upload_files=None,
    ) -> SandboxRunResult:
        return compute_sandbox.run_build_and_execute(
            credentials_file=settings.nebius_compute_credentials_file,
            project_id=settings.nebius_compute_project_id,
            subnet_id=settings.nebius_compute_subnet_id,
            platform=settings.nebius_compute_platform,
            preset=settings.nebius_compute_preset,
            image_family=settings.nebius_compute_image_family,
            ssh_username=settings.nebius_compute_ssh_username,
            boot_disk_gib=settings.nebius_compute_boot_disk_gib,
            base_image=base_image,
            install_commands=install_commands,
            execute_command=execute_command,
            wall_clock_seconds=wall_clock_seconds,
            upload_files=upload_files,
        )

    return _run


def build_pipeline_deps(settings) -> PipelineDeps:
    """Build a real `PipelineDeps` from app settings — the one place that
    knows how to turn `.env` values into actual client objects. Shared by
    `routers/runs.py::execute_run` (one HTTP request) and
    `batch/run_single_repo.py` (one Batch Lab job), so a settings-to-deps
    wiring fix (like the `NEBIUS_SANDBOX_IMAGE`/Tavily fixes logged in
    DECISIONS.md) only ever needs to happen in one place. `settings` is
    untyped here rather than importing `app.config.Settings` directly, to
    keep this usable with the fake settings objects tests already inject.
    """
    # One client instance is reused across roles: it's the same
    # base_url/api_key, only the `model` argument passed per-call differs
    # (NebiusChatClient.chat_completion takes model as a parameter).
    client = NebiusChatClient(api_key=settings.nebius_api_key, base_url=settings.nebius_base_url)
    # Tavily is a should-have enrichment (§5 cut ladder): None when not
    # configured, and the repair loop already handles that as a normal,
    # non-fatal state (tavily.fetch_context returns an empty context).
    tavily_client = None
    if settings.tavily_configured:
        from tavily import TavilyClient

        tavily_client = TavilyClient(api_key=settings.tavily_api_key)
    # RERUN directive §3 must-have #3: which backend actually executes
    # untrusted repo code. "token_factory" (default) uses sandbox.py's
    # already-verified contree_sdk path; "compute" provisions a real
    # Nebius AI Cloud Compute VM per run (see compute_sandbox.py's module
    # docstring for what is and isn't live-verified about that path).
    sandbox_runner = run_build_and_execute
    if settings.nebius_sandbox_backend == "compute":
        sandbox_runner = _make_compute_sandbox_runner(settings)
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
        sandbox_project_id=settings.nebius_project_id,
        sandbox_wall_clock_seconds=settings.nebius_sandbox_wall_clock_seconds,
        sandbox_runner=sandbox_runner,
        max_attempts=settings.max_attempts_per_run,
        tavily_client=tavily_client,
        default_sandbox_image=settings.nebius_sandbox_image,
    )


def run_pipeline(
    *,
    repo_url: str,
    commit_sha: str,
    workdir: Path,
    intake_result: RepoIntake,
    deps: PipelineDeps,
    cost_guard: CostGuard,
    run_id: str,
    on_event: Callable[[str], None] | None = None,
) -> PipelineResult:
    """`on_event`, if given, is called with each log line the instant it
    happens — not just accumulated into the final `PipelineResult.full_log`
    — so a caller (the SSE route) can stream real progress to a client
    while this function is still running, rather than only after it
    returns. Optional and side-effect-only: omitting it changes nothing
    about `run_pipeline`'s own behavior or return value.
    """
    log_lines: list[str] = []

    def _log(line: str) -> None:
        log_lines.append(line)
        if on_event is not None:
            on_event(line)

    _log(f"[intake] cloned {repo_url}@{commit_sha}")

    entrypoint_source = {}
    for candidate in intake_result.entrypoint_candidates:
        candidate_path = workdir / candidate
        if candidate_path.is_file():
            content = read_text_capped(candidate_path)
            if content is not None:
                entrypoint_source[candidate] = content

    _log("[recon] calling Nemotron Nano")
    recon_result = recon.run_recon(
        deps.recon_client, deps.recon_model, intake_result, entrypoint_source, cost_guard=cost_guard
    )

    if recon_result.is_indeterminate:
        # Prefix the stable code so it survives into the stored run, the API,
        # the certificate (Certificate.tsx renders indeterminate_reason) and
        # the passport bundle without a schema change.
        reason = recon_result.indeterminate_reason
        if recon_result.indeterminate_code:
            reason = f"{recon_result.indeterminate_code}: {reason}"
        _log(f"[recon] INDETERMINATE: {reason}")
        return _finalize(
            verdict="INDETERMINATE",
            taxonomy_code=None,
            indeterminate_reason=reason,
            attempts=(),
            build_plan_dict=None,
            log_lines=log_lines,
            deps=deps,
            cost_guard=cost_guard,
            on_event=on_event,
            attempts_used=0,
            repo_url=repo_url,
            commit_sha=commit_sha,
        )
    _log(f"[recon] entrypoint={recon_result.entrypoint} confidence={recon_result.confidence:.2f}")

    plan = planner.build_plan(
        intake_result,
        recon_result,
        client=deps.planner_client,
        model=deps.planner_model,
        cost_guard=cost_guard,
        default_image=deps.default_sandbox_image,
    )
    _log(f"[planner] build plan: {plan.as_dict()}")

    def _execute(current_workdir: Path) -> SandboxRunResult:
        # §9: the daily cost ceiling must actually stop spend, not just be
        # documented. There's no pre-flight cost quote from the sandbox
        # API, so this refuses to start a step at all once today's real
        # recorded spend has already reached the ceiling, and records the
        # step's real cost (SandboxRunResult.total_cost_usd, sourced from
        # Nebius's own per-run ContreeResult.cost) immediately after.
        cost_guard.check_daily_budget(0.0)
        # §8 S2: "Live sandbox badge (id, elapsed time, wall-clock
        # remaining)" — the wall-clock ceiling is logged here, before the
        # (blocking) sandbox call, specifically so a client watching the
        # SSE stream can start counting down "remaining" the instant this
        # line arrives, rather than only after the whole build+execute
        # step finishes.
        _log(f"[sandbox] starting build+execute (wall_clock_seconds={deps.sandbox_wall_clock_seconds:.0f})")
        result = deps.sandbox_runner(
            api_key=deps.sandbox_api_key,
            project_id=deps.sandbox_project_id,
            base_image=plan.base_image,
            install_commands=plan.as_shell_steps(),
            execute_command=plan.execute_command,
            wall_clock_seconds=deps.sandbox_wall_clock_seconds,
            upload_files=_collect_upload_files(current_workdir),
        )
        cost_guard.record_spend(result.total_cost_usd)
        _log(
            f"[cost_guard] recorded ${result.total_cost_usd:.4f} sandbox spend, "
            f"${cost_guard.remaining_today_usd:.4f} remaining today"
        )
        return result

    try:
        sandbox_result = _execute(workdir)
    except (SandboxError, CostLimitExceeded) as exc:
        _log(f"[sandbox] execution error: {exc}")
        return _finalize(
            verdict="TIMEOUT" if "wall clock" in str(exc) else "NOT_ATTEMPTABLE",
            taxonomy_code=None,
            indeterminate_reason="",
            attempts=(),
            build_plan_dict=plan.as_dict(),
            log_lines=log_lines,
            deps=deps,
            cost_guard=cost_guard,
            on_event=on_event,
            attempts_used=0,
            repo_url=repo_url,
            commit_sha=commit_sha,
        )

    _log(f"[sandbox] id={sandbox_result.sandbox_id} exit_code={sandbox_result.final.exit_code}")

    attempts: list[AttemptRecord] = []
    verdict = "RUNS_CLEAN" if sandbox_result.succeeded else None
    taxonomy_code: str | None = None

    if not sandbox_result.succeeded:
        classification = classifier.classify(
            sandbox_result.final.exit_code,
            sandbox_result.final.stderr,
            sandbox_result.final.stdout,
            declared_deps=intake_result.declared_dependencies,
        )
        taxonomy_code = classification.code
        _log(f"[classifier] {classification.code}: {classification.evidence}")

        for attempt_number in range(1, deps.max_attempts + 1):
            try:
                cost_guard.check_attempt_budget(run_id)
            except CostLimitExceeded:
                break

            target_file = _target_file_for(classification, recon_result.entrypoint, intake_result.dependency_files)
            target_path = workdir / target_file
            target_content = (read_text_capped(target_path) or "") if target_path.is_file() else ""

            try:
                tavily_context = tavily.fetch_context(deps.tavily_client, classification.code, classification.evidence)
            except tavily.TavilyError as exc:
                _log(f"[tavily] search failed, continuing without cited context: {exc}")
                tavily_context = tavily.TavilyContext(query="", sources=())
            if tavily_context.has_sources:
                _log(
                    f"[tavily] {len(tavily_context.sources)} source(s) for '{tavily_context.query}'"
                )

            proposal = repairer.propose_repair(
                deps.repair_client,
                deps.repair_model,
                classification,
                target_file,
                target_content,
                external_context=tavily_context.as_prompt_context() or None,
                cost_guard=cost_guard,
            )
            cost_guard.record_attempt(run_id)
            tavily_sources = tuple(s.as_dict() for s in tavily_context.sources)

            if not proposal.has_diff:
                _log(f"[repair {attempt_number}] declined: {proposal.explanation}")
                attempts.append(
                    AttemptRecord(attempt_number, "", "DECLINED", (), None, "", "", tavily_sources)
                )
                continue

            gate_result = check_patch(
                proposal.diff_text,
                {target_file: target_content},
                eval_call_names=frozenset(recon_result.eval_call_names),
                model_call_names=frozenset(recon_result.model_call_names),
            )

            if gate_result.decision == "REJECT":
                reasons = "; ".join(v.reason for v in gate_result.violations)
                _log(f"[repair {attempt_number}] tamper gate REJECT: {reasons}")
                attempts.append(
                    AttemptRecord(
                        attempt_number,
                        proposal.diff_text,
                        "REJECT",
                        tuple(v.as_dict() for v in gate_result.violations),
                        None,
                        "",
                        "",
                        tavily_sources,
                    )
                )
                continue

            _log(f"[repair {attempt_number}] tamper gate PASS — applying and re-executing")
            try:
                deps.apply_diff(workdir, proposal.diff_text)
            except OrchestratorError as exc:
                # Found live: the tamper gate's own AST reconstruction
                # (_apply_patched_file) never cross-validates a diff's
                # claimed context/removed lines against the real file —
                # it just trusts the diff's structure. A diff based on a
                # model's slightly-stale or misremembered view of the
                # file (a realistic LLM failure mode, not a contrived
                # one) can therefore PASS the gate yet still be rejected
                # by the real `git apply` this line runs. Previously
                # uncaught here, this crashed the whole pipeline with an
                # unhandled OrchestratorError instead of producing an
                # honest verdict — this attempt is recorded as a failed
                # application and the bounded loop simply moves on,
                # exactly like a REJECT or a declined proposal does.
                _log(f"[repair {attempt_number}] gate-approved patch failed to apply cleanly: {exc}")
                attempts.append(
                    AttemptRecord(
                        attempt_number, proposal.diff_text, "PASS", (), None, "", str(exc)[-2000:], tavily_sources
                    )
                )
                continue
            try:
                rerun_result = _execute(workdir)
            except CostLimitExceeded as exc:
                _log(f"[repair {attempt_number}] stopped: daily cost ceiling reached: {exc}")
                attempts.append(
                    AttemptRecord(attempt_number, proposal.diff_text, "PASS", (), None, "", "", tavily_sources)
                )
                break
            _log(
                f"[repair {attempt_number}] re-execution id={rerun_result.sandbox_id} "
                f"exit_code={rerun_result.final.exit_code}"
            )

            attempts.append(
                AttemptRecord(
                    attempt_number,
                    proposal.diff_text,
                    "PASS",
                    (),
                    rerun_result.final.exit_code,
                    rerun_result.final.stdout[-2000:],
                    rerun_result.final.stderr[-2000:],
                    tavily_sources,
                )
            )

            if rerun_result.succeeded:
                verdict = "RUNS_AFTER_REPAIR"
                sandbox_result = rerun_result
                break

            classification = classifier.classify(
                rerun_result.final.exit_code,
                rerun_result.final.stderr,
                rerun_result.final.stdout,
                declared_deps=intake_result.declared_dependencies,
            )
            taxonomy_code = classification.code
            sandbox_result = rerun_result
            _log(f"[classifier] {classification.code}: {classification.evidence}")

        if verdict is None:
            verdict = "BLOCKED"
            _log(f"[verdict] BLOCKED after {len(attempts)} attempt(s): {taxonomy_code}")

    return _finalize(
        verdict=verdict,
        taxonomy_code=taxonomy_code,
        indeterminate_reason="",
        attempts=tuple(attempts),
        build_plan_dict=plan.as_dict(),
        log_lines=log_lines,
        deps=deps,
        cost_guard=cost_guard,
        on_event=on_event,
        attempts_used=len(attempts),
        repo_url=repo_url,
        commit_sha=commit_sha,
    )


def _finalize(
    *,
    verdict: str,
    taxonomy_code: str | None,
    indeterminate_reason: str,
    attempts: tuple[AttemptRecord, ...],
    build_plan_dict: dict | None,
    log_lines: list[str],
    deps: PipelineDeps,
    cost_guard: CostGuard,
    attempts_used: int,
    repo_url: str,
    commit_sha: str,
    on_event: Callable[[str], None] | None = None,
) -> PipelineResult:
    def _log(line: str) -> None:
        log_lines.append(line)
        if on_event is not None:
            on_event(line)

    evidence_summary = "; ".join(log_lines[-5:])
    adjudication = adjudicator.adjudicate(
        deps.adjudicator_client,
        deps.adjudicator_model,
        verdict=verdict,
        taxonomy_code=taxonomy_code,
        attempts_used=attempts_used,
        evidence_summary=evidence_summary,
        cost_guard=cost_guard,
    )
    if adjudication.was_downgraded:
        _log(f"[adjudicator] downgraded verdict to {adjudication.verdict}: {adjudication.downgrade_reason}")
    elif adjudication.model_attempted_upgrade:
        _log("[adjudicator] model attempted to upgrade the verdict — rejected by the fixed clamp")

    timestamp = datetime.now(timezone.utc).isoformat()
    full_log = "\n".join(log_lines)

    certificate_for_hash = {
        "repo_url": repo_url,
        "commit_sha": commit_sha,
        "build_plan": build_plan_dict or {},
        "full_log": full_log,
        "diffs": [a.as_dict() for a in attempts],
        "verdict": adjudication.verdict,
        "timestamp": timestamp,
    }
    passport_hash = passport.compute_passport_hash(certificate_for_hash)

    return PipelineResult(
        verdict=adjudication.verdict,
        taxonomy_code=taxonomy_code,
        indeterminate_reason=indeterminate_reason,
        attempts=attempts,
        build_plan=build_plan_dict,
        full_log=full_log,
        certificate_prose=adjudication.certificate_prose,
        reproduction_passport_hash=passport_hash,
        timestamp=timestamp,
        repo_url=repo_url,
        commit_sha=commit_sha,
    )
