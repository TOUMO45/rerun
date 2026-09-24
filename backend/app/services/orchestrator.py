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
import re
import subprocess
import traceback
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from app.services import (
    adjudicator,
    classifier,
    dep_resolver,
    env_repair,
    passport,
    planner,
    recon,
    repairer,
    tavily,
    time_machine,
)
from app.services import compute_sandbox
from app.services.cost_guard import CostGuard, CostLimitExceeded
from app.services.intake import RepoIntake, read_text_capped
from app.services.model_client import NebiusChatClient
from app.services.sandbox import SandboxError, SandboxRunResult, run_build_and_execute
from app.services.tamper_gate import (
    check_patch,
    heuristic_eval_call_names,
    heuristic_model_call_names,
    prepare_patch,
)


class OrchestratorError(RuntimeError):
    pass


# Reason codes that mean "RERUN itself failed", not "the repo failed". Runs
# ending with one of these are reported separately and excluded from the
# Batch Lab reproducibility denominator (runner.aggregate_batch_results) —
# counting our own crash against a paper repo would be a false measurement.
PIPELINE_ERROR = "PIPELINE_ERROR"
OUR_FAULT_CODES: tuple[str, ...] = (PIPELINE_ERROR, recon.RECON_MODEL_ERROR)

_REASON_CODE_RE = re.compile(r"^([A-Z][A-Z_]*(?::[A-Za-z0-9_.]+)*): ")


def reason_code_of(indeterminate_reason: str | None) -> str | None:
    """The stable code prefix of an `indeterminate_reason`
    ("ENTRYPOINT_UNCLEAR: ...", "PIPELINE_ERROR:recon:ValueError: ..."), or
    None if the reason carries no code."""
    match = _REASON_CODE_RE.match(indeterminate_reason or "")
    return match.group(1) if match else None


def is_our_fault(reason_code: str | None) -> bool:
    if not reason_code:
        return False
    return reason_code.split(":", 1)[0] in OUR_FAULT_CODES


@dataclass
class _RunState:
    """Mutable progress of one run, kept outside the stage code so the
    exception boundary in `run_pipeline` can still report where it failed
    and everything recorded up to that point."""

    stage: str = "intake"
    log_lines: list[str] = field(default_factory=list)
    attempts: list = field(default_factory=list)
    build_plan_dict: dict | None = None


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
    # Structured build-plan edits (env_repair.EnvChange.as_dict()), shown on
    # the certificate as "Environment Delta" separately from the code diff
    # (`diff_text`); both are inside `diffs`, so the passport hashes both.
    env_delta: tuple[dict, ...] = ()
    # RERUN-verified sources from dep_resolver (git repos pinned to a real
    # commit, PyPI release history) offered to the repairer this attempt.
    resolved_sources: tuple[dict, ...] = ()
    # "model" (a repairer proposal, counts toward max_attempts) or
    # "time_machine" (RERUN's deterministic era environment, attempt 0).
    origin: str = "model"
    time_machine: dict | None = None

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
            "env_delta": list(self.env_delta),
            "resolved_sources": list(self.resolved_sources),
            "origin": self.origin,
            "time_machine": self.time_machine,
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
    # Full traceback when the run ended via the stage exception boundary
    # (PIPELINE_ERROR); empty otherwise. Also written into full_log.
    error_traceback: str = ""


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


def _load_touched_originals(workdir: Path, paths: tuple[str, ...]) -> dict[str, str]:
    """Original content of each touched path that exists as a regular,
    non-symlinked file inside `workdir`. Anything else is simply left out,
    so the gate REJECTs it (UNVERIFIED_FILE / UNSAFE_PATH) rather than this
    loader deciding. Newly added files need no original."""
    root = workdir.resolve()
    originals: dict[str, str] = {}
    for rel in paths:
        candidate = workdir / rel
        if candidate.is_symlink() or not candidate.is_file():
            continue
        resolved = candidate.resolve()
        if root not in resolved.parents:
            continue
        content = read_text_capped(candidate)
        if content is not None:
            originals[rel] = content
    return originals


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
    # GET callable for the dependency resolver's GitHub/PyPI verification
    # (url -> (status, json)); None = real HTTP. Tests inject a fake.
    http_get: callable = None
    # time_machine.compile_lock-compatible callable; None = the real uv
    # resolver. Tests inject a fake (no uv, no network).
    lock_compiler: callable = None
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

    Invariant: every call returns a PipelineResult with a verdict and a
    certificate. Any unexpected exception in any stage ends the run as
    INDETERMINATE with reason code PIPELINE_ERROR:<stage>:<ExceptionType>
    and the traceback recorded — never an unhandled crash. Sandboxes are
    never left behind: each sandbox_runner call owns its sandbox's whole
    lifecycle (sandbox.run_build_and_execute destroys it in `finally`).
    """
    state = _RunState()
    try:
        return _run_stages(
            repo_url=repo_url,
            commit_sha=commit_sha,
            workdir=workdir,
            intake_result=intake_result,
            deps=deps,
            cost_guard=cost_guard,
            run_id=run_id,
            on_event=on_event,
            state=state,
        )
    except Exception as exc:  # noqa: BLE001 - this IS the boundary
        return _finalize_pipeline_error(
            exc,
            state=state,
            deps=deps,
            cost_guard=cost_guard,
            repo_url=repo_url,
            commit_sha=commit_sha,
            on_event=on_event,
        )


def _run_stages(
    *,
    repo_url: str,
    commit_sha: str,
    workdir: Path,
    intake_result: RepoIntake,
    deps: PipelineDeps,
    cost_guard: CostGuard,
    run_id: str,
    on_event: Callable[[str], None] | None,
    state: _RunState,
) -> PipelineResult:
    log_lines = state.log_lines

    def _log(line: str) -> None:
        log_lines.append(line)
        if on_event is not None:
            on_event(line)

    state.stage = "intake"
    _log(f"[intake] cloned {repo_url}@{commit_sha}")

    entrypoint_source = {}
    for candidate in intake_result.entrypoint_candidates:
        candidate_path = workdir / candidate
        if candidate_path.is_file():
            content = read_text_capped(candidate_path)
            if content is not None:
                entrypoint_source[candidate] = content

    state.stage = "recon"
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
            state=state,
        )
    _log(f"[recon] entrypoint={recon_result.entrypoint} confidence={recon_result.confidence:.2f}")

    state.stage = "planner"
    plan = planner.build_plan(
        intake_result,
        recon_result,
        client=deps.planner_client,
        model=deps.planner_model,
        cost_guard=cost_guard,
        default_image=deps.default_sandbox_image,
    )
    state.build_plan_dict = plan.as_dict()
    _log(f"[planner] build plan: {plan.as_dict()}")

    def _execute(current_workdir: Path) -> SandboxRunResult:
        # §9: the daily cost ceiling must actually stop spend, not just be
        # documented. There's no pre-flight cost quote from the sandbox
        # API, so this refuses to start a step at all once today's real
        # recorded spend has already reached the ceiling, and records the
        # step's real cost (SandboxRunResult.total_cost_usd, sourced from
        # Nebius's own per-run ContreeResult.cost) immediately after.
        state.stage = "sandbox"
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
            state=state,
        )

    _log(f"[sandbox] id={sandbox_result.sandbox_id} exit_code={sandbox_result.final.exit_code}")

    attempts: list[AttemptRecord] = state.attempts
    verdict = "RUNS_CLEAN" if sandbox_result.succeeded else None
    taxonomy_code: str | None = None

    if not sandbox_result.succeeded:
        state.stage = "classifier"
        classification = classifier.classify(
            sandbox_result.final.exit_code,
            sandbox_result.final.stderr,
            sandbox_result.final.stdout,
            declared_deps=intake_result.declared_dependencies,
        )
        taxonomy_code = classification.code
        _log(f"[classifier] {classification.code}: {classification.evidence}")

        # Env repair edits a RERUN-owned copy of requirements.txt (never the
        # repo's file); this tracks it across attempts. Imports are scanned
        # lazily, only if an env change needs checking.
        current_requirements = intake_result.dependency_files.get("requirements.txt")
        imported_modules: frozenset[str] | None = None
        era_cache: list = []

        def _era():
            """The repo's era (dependency-file history), looked up once."""
            if not era_cache:
                state.stage = "era"
                era = time_machine.era_date(repo_url, commit_sha, workdir, deps.http_get or dep_resolver._default_http_get)
                era_cache.append(era)
                if era is not None:
                    _log(f"[era] {era.date} from {era.source} {era.detail}")
                else:
                    _log("[era] unknown (no dependency-file history and no commit date)")
            return era_cache[0]

        # --- Time machine (attempt 0): the repo's own era, deterministically --
        if classifier.repair_layer_for(classification.code) == "env":
            state.stage = "time_machine"
            era = _era()
            if era is not None:
                py_version, py_reason = time_machine.python_for_era(era.date, intake_result.python_version_hint)
                if imported_modules is None:
                    imported_modules = env_repair.imported_top_level_modules(workdir)
                undeclared = time_machine.undeclared_third_party_imports(workdir, intake_result.declared_dependencies)
                lock = (deps.lock_compiler or time_machine.compile_lock)(
                    (current_requirements or "").splitlines(), undeclared, era.date, py_version
                )
                apt_added = ()
                if classification.code == classifier.TaxonomyCode.SYS_LIB_MISSING and re.search(
                    r"\b(gcc|cc|g\+\+|x86_64-linux-gnu-gcc)\b", classification.evidence
                ):
                    # Deterministic known need: a missing C compiler.
                    apt_added = ("build-essential",)
                tm_record = {
                    "era": era.as_dict(),
                    "python": {"version": py_version, "reason": py_reason, "source": time_machine.PYTHON_RELEASES_SOURCE},
                    "undeclared_imports": list(undeclared),
                    "apt_added": list(apt_added),
                    "apt_reason": classification.evidence if apt_added else "",
                    "lock": lock.as_dict(),
                }
                if lock.ok:
                    _log(
                        f"[time-machine] era {era.date} ({era.source}) -> python {py_version}; "
                        f"locked {len(lock.lock_lines)} package(s) with uv --exclude-newer; "
                        f"not on the index: {list(lock.not_on_index) or 'none'}"
                    )
                    lock_lines = list(lock.lock_lines)
                    plan = time_machine.apply_lock(plan, py_version, lock_lines, apt_added)
                    current_requirements = "\n".join(lock_lines) + "\n"
                    try:
                        tm_result = _execute(workdir)
                    except CostLimitExceeded as exc:
                        _log(f"[time-machine] stopped: daily cost ceiling reached: {exc}")
                        tm_result = None
                    if tm_result is not None:
                        _log(f"[time-machine] re-execution id={tm_result.sandbox_id} exit_code={tm_result.final.exit_code}")
                        attempts.append(
                            AttemptRecord(
                                0, "", "PASS", (), tm_result.final.exit_code, tm_result.final.stdout[-2000:],
                                tm_result.final.stderr[-2000:], (), (), (), origin="time_machine", time_machine=tm_record,
                            )
                        )
                        sandbox_result = tm_result
                        if tm_result.succeeded:
                            verdict = "RUNS_AFTER_REPAIR"
                        else:
                            state.stage = "classifier"
                            classification = classifier.classify(
                                tm_result.final.exit_code,
                                tm_result.final.stderr,
                                tm_result.final.stdout,
                                declared_deps=intake_result.declared_dependencies,
                            )
                            taxonomy_code = classification.code
                            _log(f"[classifier] {classification.code}: {classification.evidence}")
                else:
                    _log(f"[time-machine] could not lock the era environment: {lock.error[-300:]}")
                    attempts.append(
                        AttemptRecord(0, "", "DECLINED", (), None, "", lock.error[-2000:], origin="time_machine", time_machine=tm_record)
                    )

        for attempt_number in range(1, deps.max_attempts + 1):
            if verdict is not None:
                break
            try:
                cost_guard.check_attempt_budget(run_id)
            except CostLimitExceeded:
                break

            state.stage = "repairer"
            target_file = _target_file_for(classification, recon_result.entrypoint, intake_result.dependency_files)
            target_path = workdir / target_file
            target_content = (read_text_capped(target_path) or "") if target_path.is_file() else ""
            repair_layer = classifier.repair_layer_for(classification.code)
            # The full output of the step that failed: the env gate checks
            # every env change's `evidence` against it verbatim.
            failure_log = f"{sandbox_result.final.stderr}\n{sandbox_result.final.stdout}"

            state.stage = "tavily"
            resolution = None
            if deps.tavily_client is not None and classification.code in dep_resolver.RESOLVER_CODES:
                # Dependency failures: Tavily finds the real source / era
                # versions, RERUN verifies them (GitHub commit, PyPI history).
                era = _era()
                resolution = dep_resolver.resolve(
                    deps.tavily_client,
                    classification.code,
                    classification.evidence,
                    era.date if era else None,
                    http_get=deps.http_get,
                )
            if resolution is not None:
                tavily_context = resolution.context
                external_context = resolution.as_prompt_context()
                offered_sources = resolution.resolved_sources()
                verified_git = resolution.verified_git_pairs
                _log(
                    f"[resolver] {resolution.package}: {len(resolution.git_sources)} verified git source(s), "
                    f"PyPI {resolution.pypi_status} ({len(resolution.pypi_releases)} release(s) shown), "
                    f"era {resolution.repo_date}; query: {resolution.context.query!r}"
                )
                for note in resolution.notes:
                    _log(f"[resolver] {note}")
            else:
                try:
                    tavily_context = tavily.fetch_context(deps.tavily_client, classification.code, classification.evidence)
                except tavily.TavilyError as exc:
                    _log(f"[tavily] search failed, continuing without cited context: {exc}")
                    tavily_context = tavily.TavilyContext(query="", sources=())
                external_context = tavily_context.as_prompt_context()
                offered_sources = ()
                verified_git = frozenset()
            offered_tavily = tuple(s.as_dict() for s in tavily_context.sources)
            if tavily_context.has_sources:
                _log(f"[tavily] {len(tavily_context.sources)} result(s) for '{tavily_context.query}'")

            def _cite(env_changes_applied) -> tuple[tuple, tuple]:
                """Only sources actually used in a decision are cited: a
                verified git source a pip_git change installed (plus the
                Tavily result it was found in), a PyPI release a pin/add
                chose. Everything else offered is logged, not cited."""
                used_git = {
                    ((c.git_url or "").rstrip("/").removesuffix(".git").lower(), c.commit)
                    for c in env_changes_applied
                    if c.op == "pip_git"
                }
                used_pypi = {
                    (re.sub(r"[-_.]+", "-", c.package or "").lower(), c.version)
                    for c in env_changes_applied
                    if c.op in ("pin", "add") and c.version
                }
                cited_resolved = tuple(
                    s for s in offered_sources
                    if (s["kind"] == "git" and (s["url"].lower(), s["commit"]) in used_git)
                    or (s["kind"] == "pypi" and (re.sub(r"[-_.]+", "-", s["package"]).lower(), s["version"]) in used_pypi)
                )
                cited_urls = {s.get("cited_by") for s in cited_resolved if s["kind"] == "git"}
                cited_tavily = tuple(t for t in offered_tavily if t["url"] in cited_urls)
                for t in offered_tavily:
                    if t not in cited_tavily:
                        _log(f"[citations] not cited (not used in a decision): {t['url']}")
                for r in offered_sources:
                    if r not in cited_resolved:
                        _log(f"[citations] not cited (offered, not used): {r.get('url')}")
                return cited_tavily, cited_resolved

            state.stage = "repairer"
            dependency_view = dict(intake_result.dependency_files)
            if current_requirements is not None:
                dependency_view["requirements.txt"] = current_requirements
            if imported_modules is None:
                imported_modules = env_repair.imported_top_level_modules(workdir)

            def _propose(followup: str | None = None):
                return repairer.propose_repair(
                    deps.repair_client,
                    deps.repair_model,
                    classification,
                    target_file,
                    target_content,
                    external_context=external_context or None,
                    cost_guard=cost_guard,
                    repair_layer=repair_layer,
                    build_plan=plan.as_dict(),
                    dependency_files=dependency_view,
                    log_tail=failure_log[-4000:],
                    imported_modules=sorted(imported_modules),
                    followup=followup,
                )

            proposal = _propose()
            cost_guard.record_attempt(run_id)
            if proposal.parse_retried:
                _log(f"[repair {attempt_number}] first reply was not valid JSON; re-asked once (same attempt)")

            if not proposal.has_change:
                _log(f"[repair {attempt_number}] declined: {proposal.explanation}")
                _cite(())
                attempts.append(AttemptRecord(attempt_number, "", "DECLINED", (), None, "", ""))
                continue

            # --- Environment gate (deterministic, like the tamper gate) ------
            state.stage = "env_gate"

            def _env_check(prop):
                changes, violations = env_repair.parse_env_delta(list(prop.env_delta))
                if changes:
                    violations = violations + env_repair.check_env_delta(
                        changes,
                        log_text=failure_log,
                        imported_modules=imported_modules,
                        has_requirements_txt=current_requirements is not None,
                        verified_git_sources=verified_git,
                    )
                return changes, violations

            env_changes, env_violations = _env_check(proposal)
            if env_violations and all(v.rule == env_repair.EnvRule.ENV_UNJUSTIFIED for v in env_violations):
                # Found live (TTPT v3): the model dropped the required
                # justification/evidence and a whole attempt was lost. One
                # re-ask inside the same attempt, like the JSON re-ask.
                _log(f"[repair {attempt_number}] env change lacked justification/evidence; re-asked once (same attempt)")
                proposal = _propose(
                    "Your previous reply was rejected: "
                    + "; ".join(v.reason for v in env_violations)
                    + ". Every env change needs a one-line \"justification\" and an \"evidence\" string copied "
                    "VERBATIM from the failing run's log shown above. Reply again with the complete JSON object."
                )
                if proposal.has_change:
                    env_changes, env_violations = _env_check(proposal)
                else:
                    _log(f"[repair {attempt_number}] declined after re-ask: {proposal.explanation}")
                    _cite(())
                    attempts.append(AttemptRecord(attempt_number, "", "DECLINED", (), None, "", ""))
                    continue
            env_delta_dicts = tuple(c.as_dict() for c in env_changes)

            # --- Tamper gate on the code diff (every touched file) ------------
            checked_diff = ""
            code_violations: tuple = ()
            if proposal.diff_text:
                state.stage = "tamper_gate"
                # The gate must see the original of EVERY file the diff touches,
                # not just the file the repairer was shown (the hole found live on
                # 2026-09-24). Paths come from the same normalizer the gate uses.
                touched_originals = _load_touched_originals(workdir, prepare_patch(proposal.diff_text).paths)
                touched_sources = "\n".join(touched_originals.values())
                # Recon's names come from a model that reads untrusted repo text;
                # the AST-derived floor keeps rules 1-2 armed even if recon was
                # prompt-injected into returning none.
                gate_result = check_patch(
                    proposal.diff_text,
                    touched_originals,
                    eval_call_names=frozenset(recon_result.eval_call_names) | heuristic_eval_call_names(touched_sources),
                    model_call_names=frozenset(recon_result.model_call_names) | heuristic_model_call_names(touched_sources),
                    repo_root=workdir,
                )
                # From here on, the diff that is recorded and applied is exactly
                # the canonical one the gate analyzed.
                checked_diff = gate_result.canonical_diff or proposal.diff_text
                code_violations = gate_result.violations

            all_violations = tuple(env_violations) + tuple(code_violations)
            if all_violations:
                reasons = "; ".join(v.reason for v in all_violations)
                _log(f"[repair {attempt_number}] tamper gate REJECT: {reasons}")
                _cite(())
                attempts.append(
                    AttemptRecord(
                        attempt_number,
                        checked_diff,
                        "REJECT",
                        tuple(v.as_dict() for v in all_violations),
                        None,
                        "",
                        "",
                        (),
                        env_delta_dicts,
                    )
                )
                continue

            layers = " + ".join(x for x, present in (("env", bool(env_changes)), ("code", bool(checked_diff))) if present)
            _log(f"[repair {attempt_number}] tamper gate PASS ({layers}) — applying and re-executing")
            if checked_diff:
                state.stage = "apply_diff"
                try:
                    deps.apply_diff(workdir, checked_diff)
                except OrchestratorError as exc:
                    # Found live: the tamper gate's own AST reconstruction
                    # (_apply_patched_file) never cross-validates a diff's
                    # claimed context/removed lines against the real file —
                    # it just trusts the diff's structure. A diff based on a
                    # model's slightly-stale or misremembered view of the
                    # file can therefore PASS the gate yet still be rejected
                    # by the real `git apply` this line runs. Recorded as a
                    # failed application; the bounded loop moves on. The env
                    # half of this attempt is NOT applied either (all or
                    # nothing per attempt).
                    _log(f"[repair {attempt_number}] gate-approved patch failed to apply cleanly: {exc}")
                    _cite(())
                    attempts.append(
                        AttemptRecord(attempt_number, checked_diff, "PASS", (), None, "", str(exc)[-2000:], (), env_delta_dicts)
                    )
                    continue
            if env_changes:
                state.stage = "apply_env"
                plan, new_requirements = env_repair.apply_env_delta(plan, env_changes, current_requirements)
                if new_requirements is not None:
                    current_requirements = new_requirements
                _log(f"[repair {attempt_number}] env delta applied; build plan now: {plan.as_dict()}")
            cited_tavily, cited_resolved = _cite(env_changes)
            try:
                rerun_result = _execute(workdir)
            except CostLimitExceeded as exc:
                _log(f"[repair {attempt_number}] stopped: daily cost ceiling reached: {exc}")
                attempts.append(
                    AttemptRecord(attempt_number, checked_diff, "PASS", (), None, "", "", cited_tavily, env_delta_dicts, cited_resolved)
                )
                break
            _log(
                f"[repair {attempt_number}] re-execution id={rerun_result.sandbox_id} "
                f"exit_code={rerun_result.final.exit_code}"
            )

            attempts.append(
                AttemptRecord(
                    attempt_number,
                    checked_diff,
                    "PASS",
                    (),
                    rerun_result.final.exit_code,
                    rerun_result.final.stdout[-2000:],
                    rerun_result.final.stderr[-2000:],
                    cited_tavily,
                    env_delta_dicts,
                    cited_resolved,
                )
            )

            if rerun_result.succeeded:
                verdict = "RUNS_AFTER_REPAIR"
                sandbox_result = rerun_result
                break

            state.stage = "classifier"
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
            model_attempts = sum(1 for a in attempts if a.origin == "model")
            _log(f"[verdict] BLOCKED after {model_attempts} repair attempt(s): {taxonomy_code}")

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
        state=state,
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
    state: _RunState | None = None,
) -> PipelineResult:
    def _log(line: str) -> None:
        log_lines.append(line)
        if on_event is not None:
            on_event(line)

    if state is not None:
        state.stage = "adjudicator"
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

    if state is not None:
        state.stage = "passport"
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


def _finalize_pipeline_error(
    exc: BaseException,
    *,
    state: _RunState,
    deps: PipelineDeps,
    cost_guard: CostGuard,
    repo_url: str,
    commit_sha: str,
    on_event: Callable[[str], None] | None,
) -> PipelineResult:
    """The exception boundary's finalizer. Deliberately defensive: it must
    itself never raise, because it is what guarantees a verdict. The
    adjudicator is still consulted (it can only downgrade, and INDETERMINATE
    is already the floor) unless the adjudicator is the stage that failed;
    if the passport hash itself cannot be computed, the certificate carries
    an empty hash (honestly unverifiable) rather than no result at all."""
    log_lines = state.log_lines

    def _log(line: str) -> None:
        log_lines.append(line)
        if on_event is not None:
            try:
                on_event(line)
            except Exception:  # noqa: BLE001 - a broken listener must not block the verdict
                pass

    failed_stage = state.stage
    code = f"{PIPELINE_ERROR}:{failed_stage}:{type(exc).__name__}"
    text = str(exc).strip()
    message = text.splitlines()[0][:300] if text else "no message"
    reason = (
        f"{code}: RERUN's own pipeline failed during '{failed_stage}' ({message}) — "
        "this is not a verdict on the repository."
    )
    tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    _log(f"[pipeline] INDETERMINATE: {reason}")
    _log("[pipeline] traceback:\n" + tb.rstrip())

    attempts = tuple(state.attempts)
    verdict = "INDETERMINATE"
    prose = adjudicator.templated_certificate_prose(verdict, None, len(attempts))
    if failed_stage != "adjudicator":
        try:
            adjudication = adjudicator.adjudicate(
                deps.adjudicator_client,
                deps.adjudicator_model,
                verdict=verdict,
                taxonomy_code=None,
                attempts_used=len(attempts),
                evidence_summary=f"[pipeline] INDETERMINATE: {reason}",
                cost_guard=cost_guard,
            )
            verdict, prose = adjudication.verdict, adjudication.certificate_prose
        except Exception as adj_exc:  # noqa: BLE001
            _log(f"[adjudicator] skipped after pipeline error: {type(adj_exc).__name__}")

    timestamp = datetime.now(timezone.utc).isoformat()
    full_log = "\n".join(log_lines)
    try:
        passport_hash = passport.compute_passport_hash(
            {
                "repo_url": repo_url,
                "commit_sha": commit_sha,
                "build_plan": state.build_plan_dict or {},
                "full_log": full_log,
                "diffs": [a.as_dict() for a in attempts],
                "verdict": verdict,
                "timestamp": timestamp,
            }
        )
    except Exception:  # noqa: BLE001
        passport_hash = ""

    return PipelineResult(
        verdict=verdict,
        taxonomy_code=None,
        indeterminate_reason=reason,
        attempts=attempts,
        build_plan=state.build_plan_dict,
        full_log=full_log,
        certificate_prose=prose,
        reproduction_passport_hash=passport_hash,
        timestamp=timestamp,
        repo_url=repo_url,
        commit_sha=commit_sha,
        error_traceback=tb,
    )
