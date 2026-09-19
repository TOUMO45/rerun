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

import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from app.services import adjudicator, classifier, passport, planner, recon, repairer
from app.services.cost_guard import CostGuard, CostLimitExceeded
from app.services.intake import RepoIntake
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

    def as_dict(self) -> dict:
        return {
            "attempt_number": self.attempt_number,
            "diff_text": self.diff_text,
            "gate_decision": self.gate_decision,
            "gate_violations": list(self.gate_violations),
            "exit_code": self.exit_code,
            "stdout_tail": self.stdout_tail,
            "stderr_tail": self.stderr_tail,
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
    files: dict[str, Path] = {}
    for path in workdir.rglob("*"):
        if not path.is_file():
            continue
        if ".git" in path.relative_to(workdir).parts:
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
    planner_client: object = None
    planner_model: str | None = None
    max_attempts: int = 3
    sandbox_runner: callable = run_build_and_execute
    apply_diff: callable = _apply_diff_with_git
    tavily_context: str | None = None


def run_pipeline(
    *,
    repo_url: str,
    commit_sha: str,
    workdir: Path,
    intake_result: RepoIntake,
    deps: PipelineDeps,
    cost_guard: CostGuard,
    run_id: str,
) -> PipelineResult:
    log_lines: list[str] = [f"[intake] cloned {repo_url}@{commit_sha}"]

    entrypoint_source = {}
    for candidate in intake_result.entrypoint_candidates:
        candidate_path = workdir / candidate
        if candidate_path.is_file():
            entrypoint_source[candidate] = candidate_path.read_text(encoding="utf-8", errors="replace")

    log_lines.append("[recon] calling Nemotron Nano")
    recon_result = recon.run_recon(
        deps.recon_client, deps.recon_model, intake_result, entrypoint_source, cost_guard=cost_guard
    )

    if recon_result.is_indeterminate:
        log_lines.append(f"[recon] INDETERMINATE: {recon_result.indeterminate_reason}")
        return _finalize(
            verdict="INDETERMINATE",
            taxonomy_code=None,
            indeterminate_reason=recon_result.indeterminate_reason,
            attempts=(),
            build_plan_dict=None,
            log_lines=log_lines,
            deps=deps,
            cost_guard=cost_guard,
            attempts_used=0,
            repo_url=repo_url,
            commit_sha=commit_sha,
        )
    log_lines.append(f"[recon] entrypoint={recon_result.entrypoint} confidence={recon_result.confidence:.2f}")

    plan = planner.build_plan(
        intake_result, recon_result, client=deps.planner_client, model=deps.planner_model, cost_guard=cost_guard
    )
    log_lines.append(f"[planner] build plan: {plan.as_dict()}")

    def _execute(current_workdir: Path) -> SandboxRunResult:
        # §9: the daily cost ceiling must actually stop spend, not just be
        # documented. There's no pre-flight cost quote from the sandbox
        # API, so this refuses to start a step at all once today's real
        # recorded spend has already reached the ceiling, and records the
        # step's real cost (SandboxRunResult.total_cost_usd, sourced from
        # Nebius's own per-run ContreeResult.cost) immediately after.
        cost_guard.check_daily_budget(0.0)
        result = deps.sandbox_runner(
            api_key=deps.sandbox_api_key,
            base_image=plan.base_image,
            install_commands=plan.as_shell_steps(),
            execute_command=plan.execute_command,
            wall_clock_seconds=deps.sandbox_wall_clock_seconds,
            upload_files=_collect_upload_files(current_workdir),
        )
        cost_guard.record_spend(result.total_cost_usd)
        log_lines.append(
            f"[cost_guard] recorded ${result.total_cost_usd:.4f} sandbox spend, "
            f"${cost_guard.remaining_today_usd:.4f} remaining today"
        )
        return result

    try:
        sandbox_result = _execute(workdir)
    except (SandboxError, CostLimitExceeded) as exc:
        log_lines.append(f"[sandbox] execution error: {exc}")
        return _finalize(
            verdict="TIMEOUT" if "wall clock" in str(exc) else "NOT_ATTEMPTABLE",
            taxonomy_code=None,
            indeterminate_reason="",
            attempts=(),
            build_plan_dict=plan.as_dict(),
            log_lines=log_lines,
            deps=deps,
            cost_guard=cost_guard,
            attempts_used=0,
            repo_url=repo_url,
            commit_sha=commit_sha,
        )

    log_lines.append(f"[sandbox] exit_code={sandbox_result.final.exit_code}")

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
        log_lines.append(f"[classifier] {classification.code}: {classification.evidence}")

        for attempt_number in range(1, deps.max_attempts + 1):
            try:
                cost_guard.check_attempt_budget(run_id)
            except CostLimitExceeded:
                break

            target_file = _target_file_for(classification, recon_result.entrypoint, intake_result.dependency_files)
            target_path = workdir / target_file
            target_content = target_path.read_text(encoding="utf-8", errors="replace") if target_path.is_file() else ""

            proposal = repairer.propose_repair(
                deps.repair_client,
                deps.repair_model,
                classification,
                target_file,
                target_content,
                external_context=deps.tavily_context,
                cost_guard=cost_guard,
            )
            cost_guard.record_attempt(run_id)

            if not proposal.has_diff:
                log_lines.append(f"[repair {attempt_number}] declined: {proposal.explanation}")
                attempts.append(
                    AttemptRecord(attempt_number, "", "DECLINED", (), None, "", "")
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
                log_lines.append(f"[repair {attempt_number}] tamper gate REJECT: {reasons}")
                attempts.append(
                    AttemptRecord(
                        attempt_number,
                        proposal.diff_text,
                        "REJECT",
                        tuple(v.as_dict() for v in gate_result.violations),
                        None,
                        "",
                        "",
                    )
                )
                continue

            log_lines.append(f"[repair {attempt_number}] tamper gate PASS — applying and re-executing")
            deps.apply_diff(workdir, proposal.diff_text)
            try:
                rerun_result = _execute(workdir)
            except CostLimitExceeded as exc:
                log_lines.append(f"[repair {attempt_number}] stopped: daily cost ceiling reached: {exc}")
                attempts.append(
                    AttemptRecord(attempt_number, proposal.diff_text, "PASS", (), None, "", "")
                )
                break
            log_lines.append(f"[repair {attempt_number}] re-execution exit_code={rerun_result.final.exit_code}")

            attempts.append(
                AttemptRecord(
                    attempt_number,
                    proposal.diff_text,
                    "PASS",
                    (),
                    rerun_result.final.exit_code,
                    rerun_result.final.stdout[-2000:],
                    rerun_result.final.stderr[-2000:],
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
            log_lines.append(f"[classifier] {classification.code}: {classification.evidence}")

        if verdict is None:
            verdict = "BLOCKED"
            log_lines.append(f"[verdict] BLOCKED after {len(attempts)} attempt(s): {taxonomy_code}")

    return _finalize(
        verdict=verdict,
        taxonomy_code=taxonomy_code,
        indeterminate_reason="",
        attempts=tuple(attempts),
        build_plan_dict=plan.as_dict(),
        log_lines=log_lines,
        deps=deps,
        cost_guard=cost_guard,
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
) -> PipelineResult:
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
        log_lines.append(f"[adjudicator] downgraded verdict to {adjudication.verdict}: {adjudication.downgrade_reason}")
    elif adjudication.model_attempted_upgrade:
        log_lines.append("[adjudicator] model attempted to upgrade the verdict — rejected by the fixed clamp")

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
