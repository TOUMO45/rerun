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

import dataclasses
import hashlib
import json
import os
import re
import subprocess
import tempfile
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path

from app.services import (
    adjudicator,
    api_removals,
    blocker,
    classifier,
    command_shell,
    dep_resolver,
    env_repair,
    passport,
    planner,
    recon,
    repairer,
    tavily,
    time_machine,
    tree_integrity,
)
from app.services import (
    behaviour,
    compute_sandbox,
    data_prep,
    resource_adapt,
    dep_scan,
    entry_blockers,
    error_chain,
    exit_zero_check,
    import_names,
    indentation,
    infra,
    install_repair,
    prerelease_pin,
    outcome_levels,
    output_dir,
    patch_pipeline,
    python_policy,
    resource_limits,
    runner_env,
    runner_hooks,
    sandbox_limits,
    smoke_exec,
    system_packages,
    timeouts,
    torch_wheels,
)
from app.services.cost_guard import (
    MIN_OPERATION_SECONDS,
    SANDBOX_COST_RATE_USD_PER_S,
    CostGuard,
    CostLimitExceeded,
    OperationBudgetExhausted,
)
from app.services.intake import RepoIntake, read_text_capped
from app.services.model_client import NebiusChatClient
from app.services.sandbox import (
    OUTPUT_LIMIT_BYTES,
    Checkpoint,
    SandboxCredentialsError,
    SandboxError,
    SandboxRunResult,
    SandboxTimeoutError,
    UploadIntegrityError,
    UploadTooLargeError,
    file_mode_for,
    release_images,
    run_build_and_execute,
    setup_commands,
)

# harness-v1.2: the repository's upload archive exceeds the pre-declared cap —
# a harness limitation, not a verdict about the repository.
UPLOAD_TOO_LARGE = "UPLOAD_TOO_LARGE"
from app.services.tamper_gate import (
    GateRule,
    check_patch,
    diagnostics_only_violation,
    documented_scripts,
    heuristic_eval_call_names,
    heuristic_model_call_names,
    injected_default,
    patched_sources,
    prepare_patch,
    py_compile_violations,
    semantic_change_calls,
)


class OrchestratorError(RuntimeError):
    pass


def _classify_run(exit_code, stderr, stdout="", **kwargs) -> classifier.Classification:
    """classifier.classify for a run's final step. harness-v1.7.2 (D-46): a run whose exit code 0 the exit-zero check overruled
    (exit_zero_check) is classified from its output like any failed run; classify() refuses 0 by contract, so it is given
    exit_zero_check.CLASSIFY_EXIT_CODE (the recorded exit code stays 0). No earlier call could pass 0 (it raised), so every
    earlier classification is unchanged."""
    return classifier.classify(exit_zero_check.classify_exit_code(exit_code), stderr, stdout, **kwargs)


APT_ARCHIVE_RULE = "apt_archive"


def _apt_archive_note() -> str:
    """harness-v1.7 (R4): the build-plan note of the archive rewrite (main loop, or an adopted candidate since harness-v1.7.2, D-48)."""
    return ("apt_archive (harness-v1.7, R4): apt sources of an end-of-life Debian release rewritten to its archive before every apt command: "
            + "; ".join(f"{codename}: {', '.join(lines)}" for codename, lines in sorted(runner_env.EOL_APT_SOURCES.items())))


def _apt_archive_action(matched: str, fires_on: str) -> dict:
    """harness-v1.7 (R4): the recorded time-machine action of the archive rewrite."""
    return {"rule": APT_ARCHIVE_RULE, "matched_error": matched[:500], "phase": "repair", "fires_on": fires_on,
            "step": runner_env.apt_archive_step(), "sources": {k: list(v) for k, v in sorted(runner_env.EOL_APT_SOURCES.items())},
            "limit": "only the codenames in runner_env.EOL_APT_SOURCES are rewritten; a live release is left alone"}


def _archive_rewrote(result) -> list[str]:
    """harness-v1.7.2 (D-45): the codenames the archive step rewrote, read from EVERY step of the operation. The step prints its marker in the
    install step that carries it; reading the final (execute) step only recorded `rewrote: []` although the step ran (round 5, entry #16).
    Known limit: still `[]` when this operation reopened a kept image whose prefixed apt step ran in an EARLIER operation (the marker printed there)."""
    return runner_env.apt_archive_rewrote(*(text for step in result.steps for text in (step.stderr, step.stdout)))


def _self_inflicted(cand_class, env_delta_dicts, declared_deps) -> str | None:
    """harness-v1.7.2: the package a candidate's NEW error names when that package was added by the candidate's own env delta (op add / pin /
    pip_git) and the repository does not declare it, else None. Live: insta-dl, a candidate added `python3-tk` (an apt package name) as a pip
    requirement and the run then failed `Could not find a version that satisfies the requirement python3-tk`."""
    evidence = (getattr(cand_class, "evidence", "") or "").lower()
    declared = {re.sub(r"[-_.]+", "-", d).lower() for d in (declared_deps or ())}
    for change in env_delta_dicts:
        package = str(change.get("package") or "")
        if change.get("op") not in ("add", "pin", "pip_git") or not package:
            continue
        norm = re.sub(r"[-_.]+", "-", package).lower()
        if norm in declared:
            continue
        if re.search(rf"(?<![\w.-]){re.escape(package.lower())}(?![\w.-])", evidence) or re.search(rf"(?<![\w.-]){re.escape(norm)}(?![\w.-])", evidence):
            return package
    return None


def apt_layer_command(packages) -> str:
    """harness-v1.4.1-rc (D-34): the setup command of an additive apt layer. It starts with `export DEBIAN_FRONTEND=noninteractive &&`, so
    sandbox_limits.split_setup_ops does NOT file it with the system-package operations (which always run first): it keeps its place
    among the plan's own install commands, after the kept layers it is added onto."""
    return "export DEBIAN_FRONTEND=noninteractive && apt-get update && apt-get install -y " + " ".join(sorted(packages))


# harness-v1.4.1-rc (D-31): how many times one logical operation may be resumed from a kept image after budget-limited stops.
MAX_RESUMES = 2


class _BudgetStopResumable(Exception):
    """Internal. An operation stopped at its budget-derived limit, the entry can still fund one operation and `layer` (a kept image)
    holds part of the environment: `_execute` runs the next operation from it."""

    def __init__(self, layer: dict, operation: int, reason: str):
        super().__init__(reason)
        self.layer, self.operation = layer, operation


# Reason codes that mean "RERUN itself failed", not "the repo failed". Runs
# ending with one of these are reported separately and excluded from the
# Batch Lab reproducibility denominator (runner.aggregate_batch_results) —
# counting our own crash against a paper repo would be a false measurement.
PIPELINE_ERROR = "PIPELINE_ERROR"
OUR_FAULT_CODES: tuple[str, ...] = (
    PIPELINE_ERROR,
    recon.RECON_MODEL_ERROR,
    tree_integrity.INVALID_HARNESS,
    infra.INFRA_ERROR,  # an external service failed (harness-v1.1)
    UPLOAD_TOO_LARGE,  # the archive exceeds the pre-declared upload cap (harness-v1.2)
    # Phase 2: infrastructure limits and platform refusals say nothing about the paper's code.
    "SANDBOX_QUOTA",
    "SANDBOX_INCOMPAT",
    # harness-v1.3.2: RERUN's own runner setup op failed before the repo's first command ran.
    "RUNNER_SETUP_FAILED",
    # harness-v1.3.3: the per-entry / per-operation spend cap stopped the run (RERUN's budget, not the repository).
    "COST_CAP",
    # harness-v1.4.2: the process was killed by SIGKILL (the sandbox's resource limit): a platform limit says nothing about the paper's code.
    "RESOURCE_LIMIT",
    # harness-v1.6: the base image RERUN chose has a distribution the apt mirrors no longer serve; attribution ENV, the run ends
    # INDETERMINATE (`_note_failure`) and is excluded from the denominator like every other runner-side failure.
    "APT_MIRROR_GONE",
)

_REASON_CODE_RE = re.compile(r"^([A-Z][A-Z_]*(?::[A-Za-z0-9_.-]+)*): ")


def _companion_requirements(plan, swap, requirements: str | None, evidence: str):
    """harness-v1.7.1 (R5): the swap's pins written into RERUN's copy of requirements.txt (env_repair.apply_env_delta; the repository's file is never edited).
    Only a package the file already names is pinned there; one it does not name is left to the runner's torch step, which pins it. Returns
    (plan, the copy's text or None, [{"package", "from", "to"}] for each line replaced, `from` being the line as the repository wrote it)."""
    if requirements is None:
        return plan, None, []
    lines = requirements.splitlines()
    pins, changes = [], []
    for name, release in swap.overrides().items():
        held = [line.strip() for line in lines if env_repair._requirement_name(line) == env_repair._norm(name)]
        if not held:
            continue
        pins.append({"package": name, "from": held[0], "to": release})
        changes.append(env_repair.EnvChange(op="pin", package=name, version=release, evidence=evidence[:300],
                                            justification=f"deterministic: companion_relax (R5) pins {name}=={release}; the repository's line was {held[0]}"[:300]))
    if not changes:
        return plan, None, []
    plan, text = env_repair.apply_env_delta(plan, tuple(changes), requirements)
    return plan, text, pins


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


# harness-v1.4.3-rc (D-41): the API cut a failed command's output and the part it returned says nothing: the absence of an error text is then not evidence.
OUTPUT_TRUNCATED_REASON_CODE = "OUTPUT_TRUNCATED"


def output_cut_without_error(result) -> str | None:
    """The INDETERMINATE reason when `result` failed, the API returned only the START of a stream of its last step (the step's `truncated` flag) and that start holds no
    error text, else None. Before v1.4.3 every stream was cut at 65,535 bytes and nobody read the flag: corpus-v2 #3's CUDA traceback sat behind 400,939 bytes of
    progress output and the run ended EXIT_OUTSIDE_PYTHON in every version (D-41). A failure whose error IS in the returned part is classified as before."""
    steps = getattr(result, "steps", ())
    if not steps or result.succeeded:
        return None
    final = steps[-1]
    if not getattr(final, "truncated", False) or classifier.has_actionable_error(final.stderr, final.stdout):
        return None
    cut = [name for name in ("stdout", "stderr") if getattr(final, f"{name}_truncated", False)]
    sizes = ", ".join(f"{name} {len(getattr(final, name).encode('utf-8'))} bytes returned" for name in cut)
    return (f"{OUTPUT_TRUNCATED_REASON_CODE}: the command exited with code {final.exit_code} and the API returned only the start of its {' and '.join(cut)} stream "
            f"({sizes}; RERUN asks for up to {OUTPUT_LIMIT_BYTES} bytes), with no error text in it; what the command printed last, a traceback or an evidence block, was "
            "not returned. The stream was cut, so the absence of an error says nothing: not a verdict on the repository, and no model attempt was spent on it.")


def command_image(result) -> str | None:
    """harness-v1.4.3-rc (D-42): the kept image the operation's command ran on, when that image holds everything the command needs (the tree, the applied changes and
    the environment), else None: the result image when it was kept; otherwise the layer holding every setup command, unless a patch overlay ran on top of it (that
    layer lacks the patch) or the operation started from an image that already held them all. The sustained-run line reopens this image."""
    if getattr(result, "result_image", None):
        return result.result_image
    if any(s.phase == "rerun_branch" for s in getattr(result, "rerun_steps", ())):
        return None
    setup = tuple(getattr(result, "setup_commands", ()))
    layer = next((image for ops, image in getattr(result, "layers", ()) if tuple(ops) == setup), None)
    if layer is None and getattr(result, "branch_from_image", None) and not getattr(result, "ran_setup", ()):
        layer = result.branch_from_image
    return layer


@dataclass
class _RunState:
    """Mutable progress of one run, kept outside the stage code so the
    exception boundary in `run_pipeline` can still report where it failed
    and everything recorded up to that point."""

    stage: str = "intake"
    log_lines: list[str] = field(default_factory=list)
    attempts: list = field(default_factory=list)
    build_plan_dict: dict | None = None
    # The naive, as-is run (declared install + documented command), recorded
    # before RERUN changes anything. Stays NOT_RUN if the run never got there.
    baseline: dict = field(default_factory=lambda: {"result": "NOT_RUN"})
    # Clone integrity: the latest verification record, and the paths that
    # gate-approved patches changed (expected to differ from the commit).
    tree_integrity: dict = field(default_factory=lambda: {"status": "not_checked"})
    patched_paths: set = field(default_factory=set)
    corpus_hash: str | None = None
    # Every classified failure of the run, in order, with attribution (error_chain.py).
    error_chain: "error_chain.ErrorChain" = field(default_factory=error_chain.ErrorChain)
    # Set when the spend cap stopped a sandbox operation (harness-v1.3.3): the run ends INDETERMINATE COST_CAP.
    cost_capped: str = ""
    # harness-v1.4.0-rc (D-23): every image a checkpoint operation kept ({"base_image", "ops", "image", "op", "patched"}), the current
    # environment image (`env_image_id`: the image holding the whole current environment), and RERUN's runner hooks installed so far.
    layers: list = field(default_factory=list)
    env_image: dict | None = None
    runner_extras: list = field(default_factory=list)
    # harness-v1.4.1-rc (D-34): apt packages added at repair time, each as an additive layer on top of the kept environment image
    # ({"packages", "after_rest"}: see `_apt_layer_for`), in the order they were added.
    apt_layers: list = field(default_factory=list)
    # harness-v1.4.1-rc (D-35): the entry command runs through RERUN's exit-site wrapper (runner_hooks.wrap_entry_command) from here on.
    exit_wrapper: bool = False
    # harness-v1.4.2-rc (D-38 / D-40): the one resource-evidence run of this entry ({"collected", "evidence", "kill_evidenced", "limit_quote", ...}), and a
    # stop decided by it: (reason code, INDETERMINATE reason) for RESOURCE_LIMIT or EXIT_OUTSIDE_PYTHON. No model attempt follows a stop.
    resource_evidence: dict | None = None
    resource_stop: tuple | None = None
    # harness-v1.7 (R5, companion_relax): torch-family pins the runner replaced at repair time ({package: version}), applied by runner_env.plan_torch_setup.
    torch_overrides: dict = field(default_factory=dict)
    pipefail: bool = False  # harness-v1.8 (T11): the documented command has a pipe and runs under `bash -o pipefail`
    # harness-v1.7.1 (R5): RERUN's copy of requirements.txt with the swap's pins (None: the repository's file pins none of them, or has no requirements.txt).
    companion_requirements: str | None = None
    # harness-v1.7 (R4, apt_archive): every apt command of the run is preceded by runner_env.apt_archive_step() from here on.
    apt_archive: bool = False
    # harness-v1.7 (R3, data_prep): what the rule decided ({"decision", "readmes", "step"?}); set once per run, on the first DATA_MISSING at repair time.
    data_prep: dict | None = None
    # harness-v1.9 (D-72, output_dir): what the missing-output-directory rule did ({"decision", "directory"?, "command"?}); set once per run.
    output_dir: dict | None = None
    # harness-v1.7 (R1): the memory hook is installed and the memory environment applies to every re-execution from here on; `resource_adapt` is
    # the last adaptation applied ({"round", "changes", "label", "command"}), None while the documented command runs as published.
    memory_hook: bool = False
    resource_adapt: dict | None = None


def _cost_cap_reason(message: str) -> str:
    return f"COST_CAP: {message} — RERUN's per-entry / per-operation spend cap stopped the run; not a verdict on the repository."


def derived_record(verdict: str, chain: list[dict], attempts: list[dict], indeterminate_reason: str = "", baseline: dict | None = None) -> dict:
    """harness-v1.6: the two records READ OFF the verdict record, never hashed (bundle v4 is unchanged: both are
    recomputable from the hashed fields by anyone holding the certificate). `outcome_levels` is the four-rung ladder
    (outcome_levels.compute), `blocker` what the last failure needs (blocker.report). `attempts` are attempt dicts
    (AttemptRecord.as_dict()).

    harness-v1.8: the record handed to `blocker.report` also carries `indeterminate_reason` and `baseline`, both certificate fields, so an INDETERMINATE stop on
    something the run did not have (arguments, a display, docker, an unclear entry point) reaches the stored blocker (until v1.7.2 it never did: the
    out-of-sample scan's mud-pi and AutoDoc records have `blocker: null`), and the diagnosis can quote the baseline's own evidence line."""
    record = {"verdict": verdict, "error_chain": list(chain), "attempts": list(attempts)}
    if indeterminate_reason:
        record["indeterminate_reason"] = indeterminate_reason
    if baseline:
        record["baseline"] = baseline
    out = {"outcome_levels": outcome_levels.compute(record), "blocker": blocker.report(record)}
    flag = outcome_levels.review(record)  # harness-v1.10 flag mode: present only when an adopted patch was flagged (advisory, never hashed)
    if flag is not None:
        out["review"] = flag
    return out


def _verdict_record(
    state: "_RunState | None", taxonomy_code: str | None, indeterminate_reason: str,
    verdict: str | None = None, attempts: tuple = (),
) -> dict:
    """The verdict-record fields the passport hash covers (bundle v4), plus, when the caller gives the verdict, the
    v1.6 derived records (`derived_record`), which the hash does not cover."""
    chain = state.error_chain if state is not None else error_chain.ErrorChain()
    record = {
        "taxonomy_code": taxonomy_code,
        "indeterminate_reason": indeterminate_reason,
        "error_chain": chain.as_list(),
        "first_repo_error": chain.first_repo_error,
        "last_error": chain.last_error,
    }
    if verdict is not None:
        record.update(derived_record(verdict, record["error_chain"], [a.as_dict() for a in attempts], indeterminate_reason,
                                     state.baseline if state is not None else None))
    return record


def _chain_kwargs(state: "_RunState | None") -> dict:
    chain = state.error_chain if state is not None else error_chain.ErrorChain()
    return {"error_chain": tuple(chain.as_list()), "first_repo_error": chain.first_repo_error, "last_error": chain.last_error}


_MISSING_COMPILER = re.compile(r"\b(gcc|cc|g\+\+|x86_64-linux-gnu-gcc)\b")
BUILD_ESSENTIAL_RULE = "missing_compiler_build_essential"


def missing_compiler_error(classification) -> str | None:
    """The error string of a SYS_LIB_MISSING failure that names a missing C compiler, else None. The deterministic
    "missing compiler -> apt build-essential" rule is keyed on it: at the baseline classification (since harness-v1.1) and,
    harness-v1.3.5-unvalidated (D-24), on any classification at repair time. Any other SYS_LIB_MISSING does not match."""
    if classification.code != classifier.TaxonomyCode.SYS_LIB_MISSING:
        return None
    evidence = classification.evidence or ""
    return evidence if _MISSING_COMPILER.search(evidence) else None


def system_need(classification, log: str = "") -> "system_packages.SystemNeed | None":
    """harness-v1.8 (T5): what a failed build or run needs from apt, deterministically: a missing C compiler (the v1.1 / D-24 rule, unchanged),
    a missing C header (`ft2build.h` -> `libfreetype6-dev`), or a missing tool (`which g++`, `Cannot find command 'git'`).

    Fires on SYS_LIB_MISSING and, new in v1.8, on DEP_BUILD_FAILED: pip's wrapper hides the inner cause from the classification
    (TEST #13 neo_gnns: `Command '['which', 'g++']' returned non-zero exit status 1` was DEP_BUILD_FAILED, so the compiler rule never fired and
    a candidate compiled torch-scatter from source for 257 s). The classification's own evidence line is read first; for a build the whole failing
    `log` is read and the LAST thing it could not find wins (an earlier miss that a fallback recovered from is not the failure the run ended on).
    A header or tool the tables (`system_packages`) do not know returns None, exactly as before: the repairer keeps it."""
    code = classification.code
    if code not in (classifier.TaxonomyCode.SYS_LIB_MISSING, classifier.TaxonomyCode.DEP_BUILD_FAILED):
        return None
    compiler = missing_compiler_error(classification)
    if compiler:
        return system_packages.SystemNeed(("build-essential",), compiler, "compiler", system_packages.COMPILER_RULE, "compiler")
    return system_packages.need_in(classification.evidence or "") or system_packages.need_in(log or "", last=True)


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
    # harness-v1.3.3, each only serialized when set (older records and their passport hashes are unchanged):
    # `execution` = how the re-execution ran ({"mode": "smoke", "seconds", "outcome"}: a pass means "ran for that long without
    # failing", smoke_exec); `patch_notes` = how each hunk was located in the real file (patch_pipeline); `model_patch` = what the
    # model actually sent when `diff_text` (the canonical, applied diff) differs from it.
    execution: dict | None = None
    patch_notes: tuple[str, ...] = ()
    model_patch: str = ""
    # harness-v1.3.4 (D-21): every reference offered to the model this attempt (numbered as in its prompt); `tavily_sources` holds the
    # CITED ones (with `cited_via`). `reason_no_citation` is the model's stated reason for an empty citation. (D-19) `silent_exit`: the
    # failure being repaired printed no error text.
    consulted: tuple[dict, ...] = ()
    reason_no_citation: str = ""
    silent_exit: bool = False
    # harness-v1.3.5-unvalidated (D-24, post-gate): a deterministic step RERUN took at repair time instead of asking the model
    # ({"rule", "matched_error", "apt_added", "phase"}). Only serialized when set, so older records are unchanged.
    time_machine_action: dict | None = None
    # harness-v1.4.0-rc, each only serialized when set: `candidate` = the candidate's number within its round (several candidates per
    # failure, each run in its own branch of the environment image); `branch` = {"branch_from_image", "result_image", "image_kept"};
    # `adjudication` = the round's adjudication (qualifying candidates, chosen, reasoning, released images); `chosen` = this candidate won.
    candidate: int | None = None
    branch: dict | None = None
    adjudication: dict | None = None
    chosen: bool | None = None
    # harness-v1.7.2 (D-47), only serialized when set: the patch's added lines were re-indented to the file's convention before the gate
    # ([{"file", "from", "to", "lines", "parse_error"}], indentation.normalise_patch); `diff_text` is the normalised diff, `model_patch` what the model sent.
    indentation_normalised: tuple[dict, ...] | list | None = None
    # harness-v1.8 (T1), only serialized when set: for a candidate that was NOT adopted and whose run did not succeed, what became of each env change:
    # {"apt libfreetype6-dev": "failed" | "untested"} (see `_settle_moves`). "failed": the line the change cited as its target is still in the new run's output.
    env_outcome: dict | None = None
    # harness-v1.10, only serialized when set: what the behavioural checks (behaviour.py) found for this candidate: {"static": [findings], "trace": {"status": "ok" | "missing" |
    # "no_plan", "findings": [...], "plan": {...}}, "refused": bool}. A candidate refused here is not adopted (its `chosen` stays false).
    behaviour: dict | None = None

    def as_dict(self) -> dict:
        record = {
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
        if self.execution is not None:
            record["execution"] = self.execution
        if self.patch_notes:
            record["patch_notes"] = list(self.patch_notes)
        if self.model_patch:
            record["model_patch"] = self.model_patch
        if self.consulted:
            record["consulted"] = list(self.consulted)
        if self.reason_no_citation:
            record["reason_no_citation"] = self.reason_no_citation
        if self.silent_exit:
            record["silent_exit"] = True
        if self.time_machine_action is not None:
            record["time_machine_action"] = self.time_machine_action
        if self.candidate is not None:
            record["candidate"] = self.candidate
        if self.branch is not None:
            record["branch"] = self.branch
        if self.adjudication is not None:
            record["adjudication"] = self.adjudication
        if self.chosen is not None:
            record["chosen"] = self.chosen
        if self.indentation_normalised:
            record["indentation_normalised"] = [dict(x) for x in self.indentation_normalised]
        if self.env_outcome:
            record["env_outcome"] = dict(self.env_outcome)
        if self.behaviour:
            record["behaviour"] = self.behaviour
        if self.origin == "model" and self.gate_decision == "PASS" and self.diff_text.strip():
            # harness-v1.7 (R6, D-44): a gated model patch that touches a call whose replacement changes a result; only serialized when set.
            # harness-v1.7.2: plus an injected default input (tamper_gate.injected_default), stored from this version on only
            flagged = semantic_change_calls(self.diff_text) + injected_default(self.diff_text)
            if flagged:
                record["semantic_change"] = list(flagged)
        return record


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
    # Passport bundle v2: the naive run's own result, and whether RERUN
    # turned a failing baseline into a run that completed.
    bundle_version: int = passport.CURRENT_BUNDLE_VERSION
    baseline: dict | None = None
    recovery: bool = False
    tree_integrity: dict | None = None
    corpus_hash: str | None = None
    # Bundle v4: the ordered failures with attribution, the first REPO-attributed one, the last one.
    error_chain: tuple[dict, ...] = ()
    first_repo_error: str | None = None
    last_error: str | None = None
    # harness-v1.6 (item S): the Tavily lookup for a DATA_MISSING blocker (`tavily.dataset_sources`), stored because it
    # is not derivable from the record; None when the blocker is not DATA_MISSING. Outside the passport hash.
    blocker_sources: dict | None = None

    @property
    def repair_mode(self) -> str:
        """"model_assisted" iff the repair model was consulted in any attempt;
        otherwise "deterministic" (no repair, or only the time machine)."""
        return "model_assisted" if any(a.origin == "model" for a in self.attempts) else "deterministic"

    def derived(self) -> dict:
        """harness-v1.6: `{"outcome_levels", "blocker"}`, read off the verdict record (see `derived_record`), with the
        stored Tavily lookup (`blocker_sources`) placed on `blocker["sources"]` when there is a blocker."""
        out = derived_record(self.verdict, list(self.error_chain), [a.as_dict() for a in self.attempts], self.indeterminate_reason, self.baseline)
        if out["blocker"] is not None:
            out["blocker"] = {**out["blocker"], "sources": self.blocker_sources}
        return out

    @property
    def outcome_levels(self) -> dict:
        return self.derived()["outcome_levels"]

    @property
    def blocker(self) -> dict | None:
        return self.derived()["blocker"]

    def certificate(self) -> dict:
        """The exact downloadable certificate (what S3 exports and
        scripts/verify_passport.py checks) — one definition for everyone."""
        return {
            "repo_url": self.repo_url,
            "commit_sha": self.commit_sha,
            "build_plan": self.build_plan or {},
            "full_log": self.full_log,
            "diffs": [a.as_dict() for a in self.attempts],
            "verdict": self.verdict,
            "timestamp": self.timestamp,
            "bundle_version": self.bundle_version,
            "baseline": self.baseline,
            "recovery": self.recovery,
            "tree_integrity": self.tree_integrity,
            "corpus_hash": self.corpus_hash,
            "taxonomy_code": self.taxonomy_code,
            "indeterminate_reason": self.indeterminate_reason,
            "error_chain": list(self.error_chain),
            "first_repo_error": self.first_repo_error,
            "last_error": self.last_error,
            # harness-v1.6: derived from the fields above; not in the hash (bundle v4 unchanged, see `derived_record`).
            **self.derived(),
            "reproduction_passport_hash": self.reproduction_passport_hash,
        }


_PROJECT_FILES = ("setup.py", "setup.cfg", "pyproject.toml")
_VOLATILE = re.compile(r"/tmp/\S+|\b[0-9a-f]{7,}\b|\d+")
MAX_UNTESTED_ATTEMPTS = 2  # harness-v1.8 (T1): an env change that died elsewhere is allowed ONE retry; the second untested outcome bars it


def _norm_line(text: str) -> str:
    return re.sub(r"\s+", " ", _VOLATILE.sub("#", text or "")).strip().lower()


def evidence_persists(evidence: str, output: str) -> bool:
    """harness-v1.8 (T1): is the line an env change cited as its target (`EnvChange.evidence`, copied verbatim from the failing log; the gate requires it) still in
    the output of the run made after applying it? Compared with digits, hex ids and /tmp paths blanked, whitespace collapsed, case ignored, so a pip build directory
    that differs from run to run is not a different error. No cited evidence counts as persisting (the old behaviour: the move is judged failed)."""
    lines = [ln for ln in (evidence or "").splitlines() if ln.strip()]
    if not lines:
        return True
    probe = _norm_line(lines[0])
    if len(probe) < 8:
        probe = _norm_line(evidence)
    return probe in _norm_line(output)


def own_install_failed(change, output: str, self_inflicted_package: str | None) -> bool:
    """harness-v1.8 (T1, review finding 7): did the env change's OWN install fail (a pin that does not exist, an apt name Debian does not know)? Then the run never reached
    the error the change was for, and the change is at fault: "failed", not "untested". `self_inflicted_package` is `_self_inflicted`'s answer for the new run."""
    package = getattr(change, "package", None)
    if not package:
        return False
    if str(package) == self_inflicted_package:
        return True
    pkg = re.escape(str(package))
    return getattr(change, "op", "") == "apt" and bool(
        re.search(rf"Unable to locate package {pkg}\b|Package '{pkg}' has no installation candidate", output or ""))


def move_status(change, output: str, self_inflicted_package: str | None = None) -> str:
    """harness-v1.8 (T1): "failed" when the change's own install failed or the line it cited is still in the new output, else "untested"."""
    return "failed" if own_install_failed(change, output, self_inflicted_package) or evidence_persists(getattr(change, "evidence", ""), output) else "untested"


def move_barred(key, failed: set, untested: dict) -> bool:
    """harness-v1.8 (T1): a failed move is barred; an untested one is allowed again until its second untested outcome (`MAX_UNTESTED_ATTEMPTS`)."""
    return key in failed or untested.get(key, 0) >= MAX_UNTESTED_ATTEMPTS


STREAM_TAIL_CHARS = 2000  # harness-v1.8 (T19): the tail of each stream a step that exited 0 keeps in `operations[].streams.tail`
RAW_PATCH_MAX_CHARS = 200_000  # harness-v1.8 (T19): a model's file_edits / file_replacements JSON is stored whole up to this size
# harness-v1.4.0-rc: seconds a candidate branch needs beyond the smoke limit (reopening the image, the overlay step, start-up).
CANDIDATE_START_MARGIN_S = 45.0
# harness-v1.4.1-rc (D-31): what a RESUME from a kept environment image needs beyond the smoke run (reopen the image, start the command):
# at most 10.0 s of wall time in the 22 harness-v1.4.0 gate operations that ran no setup step (#3 op 4: 14.2 s wall for 4.2 s billed;
# the other branch runs 7-9 s), doubled.
RESUME_START_MARGIN_S = 20.0
_PIP_PROJECT_RE = re.compile(r"pip3? install[^&|;]*(\s-e\s|\s\.(\s|$|\[)|\s\./)|setup\.py\s+(install|develop)")


_PROJECT_INSTALL_RE = re.compile(
    r"pip3? install(?![^&|;]*\s-e\s)[^&|;]*\s\.(\s|$|\[)|pip3? install(?![^&|;]*\s-e\s)[^&|;]*\s\./(\s|$)"
    r"|setup\.py\s+(install|build|build_ext|bdist\w*)"
)


def _candidate_action_record(actions: list) -> dict | None:
    """harness-v1.4.1-rc (D-33): the deterministic steps taken on a candidate's branch, as one `time_machine_action`: the first step, with
    any later ones under `then`. None when no rule fired (older records are unchanged)."""
    if not actions:
        return None
    return {**actions[0], **({"then": list(actions[1:])} if len(actions) > 1 else {})}


def _candidate_stage(result: SandboxRunResult, outcome: str) -> dict:
    """harness-v1.4.1-rc (D-32): how far a candidate's run got, from what its operation recorded: the phase of its final step, the
    setup steps that finished, the smoke record's outcome and how long the final step ran (adjudicator.stage_rank orders these)."""
    final = result.final
    stage = {
        "phase": final.phase,
        "setup_completed": sum(1 for s in result.steps if s.phase in ("runner_setup", "repo_install") and s.exit_code == 0),
        "outcome": outcome,
        "seconds": round(final.elapsed_seconds, 3),
        "exit_code": final.exit_code,
    }
    overruled = exit_zero_check.finding_of(result)
    if overruled:
        stage["exit_zero_check"] = overruled  # harness-v1.7.2 (D-46): an exit code 0 that is not a pass (adjudicator.stage_rank reads it)
    return stage


def _installs_project_copy(command: str) -> bool:
    """harness-v1.4.0-rc: True if a setup command installs the repository itself NON-editably (`pip install .`, `pip install
    --no-deps .`, `setup.py install`, `build_ext`): the installed copy then holds every repository file as it was at that step, so a
    patch to ANY file must be in the tree before the setup steps, or the command would run the unpatched installed package."""
    return bool(_PROJECT_INSTALL_RE.search(command))


def _setup_reads(command: str, path: str) -> bool:
    """harness-v1.4.0-rc: True if a setup command may read repository file `path` (it names the file, or installs the project itself
    and `path` is a project definition). Such a patch must be in the tree BEFORE the setup commands, not on top of a kept environment."""
    name = path.rsplit("/", 1)[-1]
    if path in command:
        return True
    if len(name) > 3 and re.search(r"(^|[\s/'\"=<])" + re.escape(name) + r"($|[\s'\";&|)])", command):
        return True
    return name in _PROJECT_FILES and bool(_PIP_PROJECT_RE.search(command))


def _committed_bytes(workdir: Path, commit: str, rel: str) -> bytes | None:
    """The committed content of `rel` at `commit` (git cat-file), or None if the path is not in the commit or git cannot say."""
    try:
        out = subprocess.run(["git", "-C", str(workdir), "cat-file", "blob", f"{commit}:{rel}"], capture_output=True,
                             timeout=timeouts.GIT_LOCAL_S)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout if out.returncode == 0 else None


def _pristine_upload_files(workdir: Path, commit: str, upload_files: dict, overlay: dict) -> dict:
    """harness-v1.4.0-rc: the files of the COMMITTED tree for a fresh checkpoint operation: every patched path is put back to its
    committed bytes (or left out if the patch added it). Kept images then always hold the pristine tree, and every change travels in
    the branch overlay, on both routes (this replaces the D-20 download-route overlay in the live flow)."""
    files = dict(upload_files)
    for rel in overlay:
        files.pop(rel, None)
        original = _committed_bytes(workdir, commit, rel)
        if original is not None:
            files[rel] = original
    return files


def _candidate_files(workdir: Path, patched_paths, diff_text: str) -> dict[str, bytes | None]:
    """harness-v1.4.0-rc: the bytes every file touched by `diff_text` would have, applied with `git apply` to copies of the current
    files in a scratch directory (the real checkout is not touched: only the adjudicated winner is applied to it)."""
    from app.services.tamper_gate import prepare_patch as _prepare

    touched = _prepare(diff_text).paths
    with tempfile.TemporaryDirectory(prefix="rerun_candidate_") as tmp:
        scratch = Path(tmp)
        for rel in touched:
            source = workdir / rel
            if source.is_file() and not source.is_symlink():
                target = scratch / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(source.read_bytes())
        _apply_diff_with_git(scratch, diff_text)
        out: dict[str, bytes | None] = {}
        for rel in touched:
            target = scratch / rel
            out[rel] = target.read_bytes() if target.is_file() else None
    return out


def _apply_diff_with_git(workdir: Path, diff_text: str) -> None:
    """Apply a unified diff to the real checkout using `git apply` — the
    standard, boring tool for this, rather than reimplementing a patch
    applier. Raises OrchestratorError if the patch doesn't apply cleanly
    (which should never happen for a gate-PASSed diff generated against
    this exact file content, but a corrupted/stale diff must not be
    silently ignored)."""
    # harness-v1.3.3 (D-15): the patch goes in as BYTES. With text=True, Windows turns every LF into CR LF on stdin and
    # `git apply` then finds no context line in an LF file: "patch failed: main_optim.py:138 ... patch does not apply"
    # for a patch that applies cleanly (found by replaying corpus-v2 entry 14's gate-approved diff both ways).
    result = subprocess.run(
        ["git", "apply", "--whitespace=nowarn", "-"],
        cwd=workdir,
        input=diff_text.encode("utf-8"),
        capture_output=True,
        timeout=timeouts.GIT_LOCAL_S,
    )
    if result.returncode != 0:
        raise OrchestratorError(f"gate-approved patch failed to apply: {result.stderr.decode('utf-8', 'replace').strip()}")


def _script_in_command(command: str | None) -> str | None:
    """The first .py script a documented command runs (repair target)."""
    for token in (command or "").split():
        if token.endswith(".py"):
            return token
    return None


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
    # False = the CONTROL arm of the ablation: no time machine, no repair loop, no Tavily. The
    # verdict is what the repository does as-is inside the fixed runner.
    repair_enabled: bool = True
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
    # tree_integrity.verify_upload-compatible callable; None = the real gate,
    # resolved at call time.
    tree_verifier: callable = None
    # NEBIUS_SANDBOX_IMAGE — the base image planner.build_plan() falls back
    # to when recon can't pin an exact Python version from the repo.
    default_sandbox_image: str = python_policy.DEFAULT_IMAGE
    # Repair re-executions (never the as-published baseline run) run the documented command under smoke_exec for this many
    # seconds; 0 disables (the command then runs to completion or the wall clock).
    smoke_seconds: int = smoke_exec.DEFAULT_SECONDS
    # harness-v1.4.0-rc: repair candidates per failure (1 = the harness-v1.3.x flow; more needs a checkpoint-capable runner), and the
    # callable that releases kept candidate images the adjudication did not choose (sandbox.release_images-compatible; None = keep them).
    candidates_per_round: int = 1
    image_releaser: callable = None
    # harness-v1.10 (behaviour.py): the behavioural checks on a repair candidate (static: what the patch changes; trace: what the patched run does). Off in the dataclass like
    # `candidates_per_round` (a hand-built deps keeps the v1.9 flow), a deployment follows Settings.behaviour_checks (default False since harness-v1.10.0-rc5: the measured false-refusal rate).
    behaviour_checks: bool = False
    # harness-v1.10 flag mode: "off" | "refuse" | "flag". `behaviour_checks=True` is "refuse" (the measured mode). "flag" refuses nothing: findings are recorded on the
    # candidate's attempt as advisory and the adopted patch's certificate carries REVIEW_REQUIRED (outcome_levels.review_required); the verdict is v1.9.0's.
    behaviour_mode: str = "off"


def _accepts_kwarg(fn: Callable, name: str) -> bool:
    """True if `fn` takes keyword `name` (or **kwargs): lets the download route be
    passed to the real runner without breaking injected test runners."""
    import inspect

    try:
        params = inspect.signature(fn).parameters.values()
    except (TypeError, ValueError):
        return False
    return any(p.name == name or p.kind is inspect.Parameter.VAR_KEYWORD for p in params)


def _declares_kwarg(fn: Callable, name: str) -> bool:
    """True only if `fn` names keyword `name` explicitly (a `**kwargs` catch-all does not count). harness-v1.4.0-rc capabilities (kept
    images, runner hooks) change what the runner must do, so a runner has to declare them; older runners and test doubles that take
    `**kwargs` keep the harness-v1.3.x behaviour."""
    import inspect

    try:
        return name in inspect.signature(fn).parameters and inspect.signature(fn).parameters[name].kind is not inspect.Parameter.VAR_KEYWORD
    except (TypeError, ValueError):
        return False


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
        file_modes=None,  # noqa: ARG001 - the Compute backend uploads by its own path
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
    image_releaser = release_images
    if settings.nebius_sandbox_backend == "compute":
        sandbox_runner = _make_compute_sandbox_runner(settings)
        image_releaser = None
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
        candidates_per_round=getattr(settings, "repair_candidates_per_round", 1),
        image_releaser=image_releaser,
        behaviour_checks=bool(getattr(settings, "behaviour_checks", False)),
        behaviour_mode=str(getattr(settings, "behaviour_mode", "off") or "off"),
    )


BEHAVIOUR_MODES = ("off", "refuse", "flag")


def behaviour_mode_of(deps) -> str:
    """harness-v1.10: the mode the behavioural checks run in for these deps. `behaviour_checks=True` (the measured v1.10 setting) is "refuse"; otherwise
    `behaviour_mode`, and anything unknown is "off" (a typo never turns a check on)."""
    if getattr(deps, "behaviour_checks", False):
        return "refuse"
    mode = str(getattr(deps, "behaviour_mode", "off") or "off")
    return mode if mode in BEHAVIOUR_MODES else "off"


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
    documented_command: str | None = None,
    corpus_hash: str | None = None,
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
    state.corpus_hash = corpus_hash
    return _with_blocker_sources(
        _run_pipeline_stages(repo_url=repo_url, commit_sha=commit_sha, workdir=workdir, intake_result=intake_result, deps=deps,
                             cost_guard=cost_guard, run_id=run_id, on_event=on_event, documented_command=documented_command,
                             state=state),
        deps, repo_url, on_event, dataset_name=((state.data_prep or {}).get("dataset_name") or ""))


def _with_blocker_sources(result: PipelineResult, deps: PipelineDeps, repo_url: str, on_event, dataset_name: str = "") -> PipelineResult:
    """harness-v1.6 (item S): after the verdict, one Tavily search for a DATA_MISSING blocker, stored on the result. It
    runs after every finalizer so the verdict is already fixed; it can neither change a verdict nor raise (a failed
    search is stored as its reason)."""
    if result.verdict != "BLOCKED":
        # v1.6 review, defect 9: only a BLOCKED run has a blocker a person must act on; an INDETERMINATE one (cost cap,
        # invalid harness, a platform stop) carries a chain but no claim, and no search is spent on it.
        return result
    sources = tavily.dataset_sources(getattr(deps, "tavily_client", None), repo_url, result.blocker, dataset_name)
    if sources is None:
        return result
    if on_event is not None:
        n = len(sources["sources"] or [])
        on_event(f"[blocker] DATA_MISSING: Tavily dataset lookup '{sources['query']}' -> {n} source(s)"
                 + (f" ({sources['reason']})" if sources.get("reason") else ""))
    return dataclasses.replace(result, blocker_sources=sources)


def _run_pipeline_stages(
    *, repo_url: str, commit_sha: str, workdir: Path, intake_result: RepoIntake, deps: PipelineDeps, cost_guard: CostGuard,
    run_id: str, on_event, documented_command: str | None, state: "_RunState",
) -> PipelineResult:
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
            documented_command=documented_command,
        )
    except tree_integrity.HarnessIntegrityError as exc:
        return _finalize_invalid_harness(
            exc, state=state, repo_url=repo_url, commit_sha=commit_sha, on_event=on_event
        )
    except infra.InfraError as exc:
        return _finalize_infra_error(exc, state=state, repo_url=repo_url, commit_sha=commit_sha, on_event=on_event)
    except SandboxTimeoutError as exc:
        # A re-execution (time machine / repair) reached the wall clock: a TIMEOUT result about the run, recorded with the
        # attempts so far, never a PIPELINE_ERROR (harness-v1.3.3, D-3).
        return _finalize_timeout(exc, state=state, deps=deps, cost_guard=cost_guard, repo_url=repo_url,
                                 commit_sha=commit_sha, on_event=on_event)
    except (UploadTooLargeError, sandbox_limits.FsDeltaExceeded) as exc:
        # Phase 2: an infrastructure limit, not evidence about the repository.
        return _finalize_not_measured(
            "INDETERMINATE",
            f"SANDBOX_QUOTA: {exc} — a Nebius sandbox limit; nothing was uploaded/run past it and this is "
            "not a verdict on the repository.",
            state=state, repo_url=repo_url, commit_sha=commit_sha, on_event=on_event,
            taxonomy_code="SANDBOX_QUOTA",
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
    documented_command: str | None = None,
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

    if recon_result.is_indeterminate and documented_command:
        # The corpus documents the command, so no entrypoint has to be
        # guessed: recon's abstention doesn't stop the run (recon's eval/model
        # names are simply unavailable; the tamper gate's AST floor still applies).
        _log(
            f"[recon] {recon_result.indeterminate_code}: {recon_result.indeterminate_reason} — "
            f"proceeding with the documented command: {documented_command}"
        )
    elif recon_result.is_indeterminate:
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
    else:
        _log(f"[recon] entrypoint={recon_result.entrypoint} confidence={recon_result.confidence:.2f}")

    state.stage = "planner"
    # Python policy: 3.10 unless the repo declares otherwise; the reason is logged and kept in the plan notes.
    python_choice = python_policy.resolve_from_repo(workdir)
    # harness-v1.5.1 (F1): the interpreter follows the repository's torch pin (a pin the chosen Python has no wheel for failed the runner's own setup, no repair attempt).
    python_choice = torch_wheels.python_for_pin(python_choice, torch_wheels.torch_pin(intake_result.dependency_files.values()))
    # A repo that declares nothing gets the operator-configured default image (NEBIUS_SANDBOX_IMAGE; the
    # sealed default is python:3.10-slim, and the batch driver's preflight refuses any other value).
    plan_image = python_choice.image if python_choice.is_declared else deps.default_sandbox_image
    _log(f"[python] {plan_image} ({python_choice.source}): {python_choice.reason}")
    plan = planner.build_plan(
        intake_result,
        recon_result,
        client=deps.planner_client,
        model=deps.planner_model,
        cost_guard=cost_guard,
        default_image=plan_image,
        base_image_override=plan_image,
        extra_notes=(f"base image {plan_image}: {python_choice.reason}",),
        documented_command=documented_command,
    )
    state.build_plan_dict = plan.as_dict()
    _log(f"[planner] build plan: {plan.as_dict()}")

    def _execution_of(result: SandboxRunResult, smoke: bool) -> dict | None:
        overruled = exit_zero_check.finding_of(result)  # harness-v1.7.2 (D-46): only on a run the exit-zero check overruled
        if not (smoke and deps.smoke_seconds):
            return {"exit_zero_check": overruled} if overruled else None
        record = smoke_exec.execution_record(deps.smoke_seconds, result.final.exit_code, result.final.stdout, result.final.stderr)
        if overruled:
            record = {**record, "exit_zero_check": overruled}
        image = command_image(result)  # harness-v1.4.3-rc (D-42): the image the sustained-run line reopens for a RUNS_* entry
        if image:
            record = {**record, "image": image}
        if getattr(result, "base_command", ""):
            record = {**record, "command": result.base_command}  # the command the smoke run executed: the sustained run re-executes THIS one
        cut = [name for name in ("stdout", "stderr") if getattr(result.final, f"{name}_truncated", False)]
        if cut:
            # the stored tails of a cut stream are the end of what the API RETURNED, not of what the command printed (harness-v1.4.3-rc, D-41)
            record = {**record, "output_cut": cut}
            if record["outcome"] == "exited" and result.final.exit_code == 0 and "stdout" in cut:
                # the launcher prints its ALIVE line last on stdout: a cut stdout without it cannot tell "finished by itself" from "still running at the limit"
                record = {**record, "outcome": "alive_or_exited_unknown"}
        return record

    op_lock = threading.Lock()

    def _register_layers(base_image: str, layers, op_n: int, *, patched: bool = False) -> None:
        with op_lock:
            for ops, image in layers:
                state.layers.append({"base_image": base_image, "ops": tuple(ops), "image": image, "op": op_n, "patched": patched})

    def _best_layer(base_image: str, cmds: tuple[str, ...]) -> dict | None:
        """The kept image with this base image whose setup commands are the longest prefix of `cmds` (latest wins a tie)."""
        best = None
        with op_lock:
            for layer in state.layers:
                ops = layer["ops"]
                if layer["base_image"] != base_image or len(ops) > len(cmds) or tuple(cmds[: len(ops)]) != ops:
                    continue
                if best is None or len(ops) >= len(best["ops"]):
                    best = layer
        return best

    def _sandbox_steps(use_plan, extra_layers: tuple = ()) -> tuple[str, ...]:
        """harness-v1.4.1-rc (D-34): the setup steps the sandbox runs for `use_plan`. The apt packages a repair added after an environment
        image had been kept are left out of the first (apt) step and installed by their own layer, placed right after the part of the
        plan's install commands that the kept image already holds (`after_rest`; the front of that list if the commands changed). With
        no layer this is exactly `use_plan.as_shell_steps()`."""
        layers = [*state.apt_layers, *extra_layers]
        if not layers:
            return use_plan.as_shell_steps()
        late = {p for layer in layers for p in layer["packages"]}
        first = tuple(p for p in use_plan.apt_install if p not in late)
        rest = _rest_with_layers(use_plan.install_commands, layers)
        head = ["apt-get update && apt-get install -y " + " ".join(first)] if first else []
        return tuple([*head, *rest])

    def _rest_with_layers(install_commands, layers) -> list[str]:
        """The plan's install commands with each apt layer inserted, in the order the layers were added. A layer's `after_rest` is the
        exact list of commands (earlier layers' included) that must precede it; if they no longer do, it goes to the front."""
        rest = list(install_commands)
        for layer in layers:
            after = tuple(layer["after_rest"])
            rest.insert(len(after) if tuple(rest[: len(after)]) == after else 0, apt_layer_command(layer["packages"]))
        return rest

    def _apt_layer_for(plan_before, plan_after, existing: tuple = (), extra_extras: tuple = ()) -> dict | None:
        """harness-v1.4.1-rc (D-34): the additive layer for the apt packages `plan_after` has and `plan_before` lacked, or None when
        there are none or nothing is kept to add them onto (a fresh build then installs them in its first apt step, as before).
        The layer goes after the deepest kept image of the environment WITHOUT those packages: the setup steps that image holds stay
        where they are, and only what it lacks (the new packages, then the remaining steps) runs on top of it."""
        added = tuple(sorted(set(plan_after.apt_install) - set(plan_before.apt_install)))
        if not added or not (deps.repair_enabled and _declares_kwarg(deps.sandbox_runner, "checkpoint")):
            return None
        probe = replace(plan_after, apt_install=plan_before.apt_install)
        steps = _sandbox_steps(probe, existing)
        torch_setup = (runner_env.plan_torch_setup([*probe.as_shell_steps(), *intake_result.dependency_files.values()], workdir)
                       if _accepts_kwarg(deps.sandbox_runner, "torch_setup") else None)
        extras = (*state.runner_extras, *extra_extras) if _declares_kwarg(deps.sandbox_runner, "runner_extras") else ()
        kept = _best_layer(plan_after.base_image, setup_commands(steps, torch_setup, extras))
        if kept is None or not kept["ops"]:
            return None
        held = set(kept["ops"])
        after: list[str] = []
        for command in _rest_with_layers(plan_after.install_commands, [*state.apt_layers, *existing]):
            if command not in held:
                break
            after.append(command)
        return {"packages": added, "after_rest": tuple(after), "after_image": kept["image"], "after_ops": len(kept["ops"])}

    def _operation_record(outcome: str, *, use_plan, funded: float, wall: float, start: dict | None, cmds: tuple[str, ...],
                          torch_setup, role: str, candidate: int | None, share: int, result: SandboxRunResult | None = None,
                          exc: BaseException | None = None, cost_usd: float = 0.0, estimated_usd: float = 0.0) -> dict:
        """One sandbox operation, as the record stores it (harness-v1.4.0-rc). Seconds and costs are the API's per-step values."""
        steps = list(result.steps) if result is not None else list(getattr(exc, "completed_steps", ()) or ())
        rerun = list(result.rerun_steps) if result is not None else list(getattr(exc, "rerun_steps", ()) or ())
        torch_cmd = torch_setup.install_command if torch_setup is not None else None
        installs = [
            {"command": s.command[:160], "phase": s.phase, "seconds": round(s.elapsed_seconds, 3), "exit_code": s.exit_code,
             "cost_usd": round(s.cost_usd, 6), "torch": s.command == torch_cmd}
            for s in steps if s.phase in ("runner_setup", "repo_install")
        ]
        start_ops = tuple(start["ops"]) if start else ()
        layers = tuple(result.layers) if result is not None else tuple(getattr(exc, "layers", ()) or ())
        result_image = result.result_image if result is not None else None
        kept = [image for _, image in layers] + ([result_image] if result_image else [])
        torch_key = None
        if torch_cmd and torch_cmd in cmds:
            through = cmds[: cmds.index(torch_cmd) + 1]
            torch_key = hashlib.sha256("\n".join((use_plan.base_image, *through)).encode("utf-8")).hexdigest()[:16]
        env_layer = next((image for ops, image in layers if tuple(ops) == tuple(cmds)), None)
        if env_layer is None and start is not None and tuple(start_ops) == tuple(cmds):
            env_layer = start["image"]
        return {
            "role": role,
            "candidate": candidate,
            "concurrent": share,
            "base_image": use_plan.base_image,
            "funded_seconds": round(funded, 1),
            "wall_seconds": round(wall, 2),
            "sandbox_seconds": round(sum(s.elapsed_seconds for s in steps + rerun), 3),
            "install_seconds": installs,
            "rerun_steps": [{"phase": s.phase, "seconds": round(s.elapsed_seconds, 3), "cost_usd": round(s.cost_usd, 6)} for s in rerun],
            "branch_from_image": start["image"] if start else None,
            "start_setup_commands": len(start_ops),
            "setup_commands": len(cmds),
            "torch_in_start_image": bool(torch_cmd and torch_cmd in start_ops),
            "torch_installed": any(i["torch"] and i["exit_code"] == 0 for i in installs),
            "torch_env_key": torch_key,
            "result_image": result_image,
            "image_kept": bool(kept),
            "kept_images": kept,
            "env_image_id": env_layer,
            "cost_usd": round(cost_usd, 6),
            "cost_estimated_usd": round(estimated_usd, 6),
            "outcome": outcome,
            "resource_limits": resource_limits.record(),
            "exit_code": result.final.exit_code if result is not None and result.steps else None,
            # harness-v1.4.3-rc (D-40): the largest peak-memory figure the API returned for any step of the operation, as returned (unit not documented)
            "max_rss": max((s.max_rss for s in steps if getattr(s, "max_rss", None) is not None), default=None),
            # harness-v1.4.3-rc (D-41): size, sha-256 and the API's truncated flag of each stream of the last step (what classification read)
            **({"streams": _streams_with_tail(result.final)} if result is not None and result.steps and hasattr(result.final, "streams") else {}),
            "killed_step": (getattr(exc, "command", "") or "")[:160] if outcome == "killed" else None,
            "killed_seconds": round(getattr(exc, "killed_seconds", 0.0) or 0.0, 1) if outcome == "killed" else None,
        }

    def _streams_with_tail(step) -> dict:
        """harness-v1.8 (T19, D-53): `streams()` plus, for a step that exited 0, the last 2,000 characters of each stream. A clean as-published run kept only
        sizes and SHA-256 hashes, so the TEST-B audit could not read what the command printed: it took the missing text for empty and struck #6 under the wrong
        rule (the right one was proven by reproducing the stream byte for byte). A failed run's tails are already in the attempt records."""
        streams = step.streams()
        if step.exit_code == 0:
            streams["tail"] = {"stdout": (step.stdout or "")[-STREAM_TAIL_CHARS:], "stderr": (step.stderr or "")[-STREAM_TAIL_CHARS:], "cap_chars": STREAM_TAIL_CHARS}
        return streams

    def _one_operation_seconds() -> float:
        """harness-v1.4.1-rc (D-31): what ONE funded operation needs: the smoke run plus the start-up margin (a resume from a kept image
        runs the command and little else); without a smoke run, the guard's minimum."""
        return (deps.smoke_seconds + RESUME_START_MARGIN_S) if deps.smoke_seconds else MIN_OPERATION_SECONDS

    def _execute(current_workdir: Path, **kwargs) -> SandboxRunResult:
        """harness-v1.4.1-rc (D-31). One sandbox operation, resumed after a budget-limited stop. Until v1.4.0 a stop at the operation's
        budget-derived limit always ended the entry COST_CAP, even when the stopped operation had kept every layer it built and the
        entry could fund another operation (corpus-v2 #11, v1.4.0 gate: the era environment complete, $0.62 left). Now such a stop
        is followed by the next operation, which reopens the deepest kept image and runs what the image lacks. The entry ends COST_CAP
        only when money left cannot fund one operation or no environment image is kept. At most MAX_RESUMES per call."""
        resumed_after = None
        for resumes in range(MAX_RESUMES + 1):
            try:
                return _execute_once(current_workdir, resumed_after=resumed_after, may_resume=resumes < MAX_RESUMES, **kwargs)
            except _BudgetStopResumable as stop:
                resumed_after = stop.operation
                _log(f"[cost_guard] resuming after the budget-limited stop of operation {stop.operation}: image {stop.layer['image']} "
                     f"holds {len(stop.layer['ops'])} setup command(s); ${cost_guard.remaining_today_usd:.4f} left funds "
                     f"{cost_guard.operation_seconds_budget(share=max(kwargs.get('share', 1), 1)):.0f}s, one operation needs "
                     f"{_one_operation_seconds():.0f}s")
        raise AssertionError("unreachable: the last pass cannot resume")  # pragma: no cover

    def _execute_once(current_workdir: Path, *, smoke: bool = False, baseline: bool = False, plan_used=None,
                      extra_files: dict | None = None, keep_result: bool = False, share: int = 1, role: str = "",
                      candidate: int | None = None, resumed_after: int | None = None, may_resume: bool = False,
                      extra_apt_layers: tuple = (), extra_extras: tuple = (), exec_wrapper: bool | None = None,
                      evidence: bool = False, apt_archive: bool = False, trace_env: dict | None = None) -> SandboxRunResult:
        # §9: the daily cost ceiling must actually stop spend, not just be
        # documented. There's no pre-flight cost quote from the sandbox
        # API, so this refuses to start a step at all once today's real
        # recorded spend has already reached the ceiling, and records the
        # step's real cost (SandboxRunResult.total_cost_usd, sourced from
        # Nebius's own per-run ContreeResult.cost) immediately after.
        use_plan = plan_used or plan
        role = role or ("baseline" if baseline else "re-execution")
        state.stage = "sandbox"
        cost_guard.check_daily_budget(0.0)
        # harness-v1.3.3 (D-7): Nebius returns an operation's cost only when it completes, so the guard bounds the
        # operation's DURATION: it may run for what the entry can still fund (capped per operation), and the sandbox
        # kills it at that limit. The configured wall clock still applies when it is the smaller bound.
        if baseline:
            # The as-published run keeps the pre-registered wall clock, unshortened by the budget rule: CONTROL comparability, and a
            # transient slow install (3 of 20 v1.3.2 CONTROL operations took 195-494 s at normal cost) must never turn the only passing
            # entry into a false regression. Its spend is recorded, counts against the entry cap, and an entry whose baseline used the cap
            # ends COST_CAP before any repair (the pre-check above). Observed baseline cost: at most $0.35 in 40 operations.
            operation_seconds = deps.sandbox_wall_clock_seconds
            funding = {"basis": "baseline: the pre-registered wall clock, not budget-limited", "rate_used_usd_per_s": None,
                       "source_operations": []}
        else:
            # harness-v1.4.0-rc: `share` operations run at the same time (repair candidates); each may use its share of what is left.
            # harness-v1.4.1-rc (D-30): funded at the rolling rate this entry's completed operations measured (x1.5, floor, ceiling).
            rate = cost_guard.funding_rate()
            funding = rate.as_dict()
            budget_seconds = cost_guard.operation_seconds_budget(rate_usd_per_s=rate.rate, share=max(share, 1))
            if budget_seconds < MIN_OPERATION_SECONDS:
                state.cost_capped = (
                    f"${cost_guard.remaining_today_usd:.2f} left funds only {budget_seconds:.0f}s of sandbox time "
                    f"(minimum {MIN_OPERATION_SECONDS:.0f}s at ${rate.rate:.4f}/s, {rate.basis})"
                    + (f" per concurrent operation ({share} at once)" if share > 1 else "")
                )
                raise OperationBudgetExhausted(state.cost_capped)
            operation_seconds = min(deps.sandbox_wall_clock_seconds, budget_seconds)
        # §8 S2: "Live sandbox badge (id, elapsed time, wall-clock
        # remaining)" — the wall-clock ceiling is logged here, before the
        # (blocking) sandbox call, specifically so a client watching the
        # SSE stream can start counting down "remaining" the instant this
        # line arrives, rather than only after the whole build+execute
        # step finishes.
        upload_files = _collect_upload_files(current_workdir)
        base_command, wrapper_note = use_plan.execute_command, None
        if not baseline and (state.exit_wrapper if exec_wrapper is None else exec_wrapper):
            # harness-v1.4.1-rc (D-35): the entry script runs through RERUN's exit-site wrapper (a bare `raise SystemExit(n)` leaves a
            # traceback); the documented command is otherwise unchanged (same program, arguments, working directory).
            wrapped, why = runner_hooks.wrap_entry_command(use_plan.execute_command)
            if wrapped is not None:
                base_command, wrapper_note = wrapped, "applied"
            else:
                wrapper_note = f"not applicable: {why}"
            _log(f"[exit-wrapper] {role or 're-execution'}: {wrapper_note}")
        if not baseline and state.memory_hook:
            base_command = runner_env.with_memory_env(base_command)  # harness-v1.7 (R1 c): MALLOC_ARENA_MAX / OMP_NUM_THREADS for every process of the run
        if command_shell.pipes_into_interpreter(base_command):
            # harness-v1.8 (T11, TEST #18 adversary_critic): `python generate_script.py --train=True | bash` died at its first import and the pipe's status was bash's
            # (0): RUNS_CLEAN for a run that did nothing. The certificate keeps the documented text; the sandbox is handed it inside `bash -o pipefail -c`.
            base_command = command_shell.with_pipefail(base_command)
            state.pipefail = True
        if evidence:
            # harness-v1.4.2-rc: the command (wrapped when the exit wrapper is on) runs unchanged, then the sandbox's own limits and any kill are read.
            base_command = runner_hooks.evidence_command(base_command)
        execute_command = base_command
        if smoke and deps.smoke_seconds:
            # harness-v1.3.3: a repair re-execution asks "does it run", not "does it finish" (smoke_exec).
            execute_command = smoke_exec.wrap(base_command, deps.smoke_seconds, env=trace_env)  # harness-v1.10: trace_env only on a candidate's behavioural trace
            _log(f"[smoke] re-execution of the documented command under a {deps.smoke_seconds}s smoke limit")
        # Clone integrity gate: the uploaded bytes must be the committed bytes
        # (except files changed by gate-approved patches). Raises
        # HarnessIntegrityError -> INVALID_HARNESS, never a repo verdict.
        verifier = deps.tree_verifier or tree_integrity.verify_upload
        record = verifier(current_workdir, commit_sha, upload_files, frozenset(state.patched_paths))
        state.tree_integrity = record.as_dict()
        _log(
            f"[integrity] verified {record.files_checked} file(s) against tree {record.tree_sha or '?'}"
            + (f"; excluded patched: {sorted(state.patched_paths)}" if state.patched_paths else "")
        )
        modes = dict(getattr(record, "modes", None) or {})
        runner_kwargs = {}
        # Torch is provided by the runner (CPU wheels, exec-stack fix, verified import): runner_env.
        torch_setup = None
        if _accepts_kwarg(deps.sandbox_runner, "torch_setup"):
            torch_setup = runner_env.plan_torch_setup(
                [*use_plan.as_shell_steps(), *intake_result.dependency_files.values()], current_workdir,
                overrides=state.torch_overrides or None,  # harness-v1.7 (R5): never on the baseline (no override exists before it)
            )
            if torch_setup is not None:
                _log(f"[runner] torch: {torch_setup.reason}")
            runner_kwargs["torch_setup"] = torch_setup
        extras = (*state.runner_extras, *extra_extras) if _declares_kwarg(deps.sandbox_runner, "runner_extras") else ()
        if extras:
            runner_kwargs["runner_extras"] = extras
        # harness-v1.4.1-rc (D-34): apt packages added at repair time are additive layers inside the setup list, not part of its first step.
        steps = _sandbox_steps(use_plan, extra_apt_layers)
        # harness-v1.7 (R4): the apt-archive step goes in front of every apt command (never on the baseline: nothing sets it before).
        # harness-v1.7.2 (D-48): or on one repair candidate's branch only (`apt_archive`), when that candidate's own apt install met the gone mirror.
        if (state.apt_archive or apt_archive) and not baseline:
            steps = tuple(runner_env.with_apt_archive(command) for command in steps)
        cmds = setup_commands(steps, torch_setup, extras)
        # harness-v1.4.0-rc (D-23): TREATMENT operations reuse kept images instead of rebuilding the environment every time.
        checkpoint_mode = deps.repair_enabled and _declares_kwarg(deps.sandbox_runner, "checkpoint")
        start, fresh = None, True
        if checkpoint_mode:
            overlay: dict[str, bytes | None] = {}
            for rel in sorted(state.patched_paths):
                path = current_workdir / rel
                overlay[rel] = path.read_bytes() if path.is_file() else None
            overlay.update(extra_files or {})
            early = bool(overlay) and (any(_installs_project_copy(command) for command in cmds)
                                       or any(_setup_reads(command, rel) for command in cmds for rel in overlay))
            start = None if early else _best_layer(use_plan.base_image, cmds)
            fresh = start is None
            if fresh:
                upload_files = _pristine_upload_files(current_workdir, commit_sha, upload_files, overlay)
            runner_kwargs["checkpoint"] = Checkpoint(
                start_image=start["image"] if start else None,
                start_ops=tuple(start["ops"]) if start else (),
                keep_layers=not early,
                branch_files=tuple((rel, data, file_mode_for(modes.get(rel))) for rel, data in sorted(overlay.items()) if data is not None),
                branch_deleted=tuple(rel for rel, data in sorted(overlay.items()) if data is None),
                branch_before_setup=early,
                keep_result=keep_result,
            )
            if start is not None:
                _log(f"[checkpoint] {role}: branching from image {start['image']} ({len(start['ops'])} of {len(cmds)} setup command(s) "
                     f"already in it, kept by operation {start['op']}); no reinstall of what it contains")
            elif early:
                _log(f"[checkpoint] {role}: a setup command reads a patched file, so the patch goes in right after the tree; "
                     "no image reused or kept")
            else:
                _log(f"[checkpoint] {role}: no kept image holds this environment yet; building it from {use_plan.base_image} and keeping "
                     "every layer")
        elif extra_files:
            raise OrchestratorError("candidate files can only be run by a checkpoint-capable sandbox runner")
        if fresh:
            # Over-limit repos are fetched inside the sandbox, never uploaded (sandbox_limits).
            if _accepts_kwarg(deps.sandbox_runner, "download_source"):
                runner_kwargs["download_source"] = sandbox_limits.DownloadSource.from_repo_url(repo_url, commit_sha)
            if not checkpoint_mode and _accepts_kwarg(deps.sandbox_runner, "overlay_paths"):
                # harness-v1.3.4 (D-20): patched files travel as an overlay on the download route (legacy path only; a checkpoint
                # operation sends every change in its branch archive).
                runner_kwargs["overlay_paths"] = frozenset(state.patched_paths)
        _log(f"[sandbox] starting build+execute (wall_clock_seconds={operation_seconds:.0f})")
        started = time.monotonic()

        def _record_op(outcome: str, **kwargs) -> dict:
            op = cost_guard.record_operation({**_operation_record(
                outcome, use_plan=use_plan, funded=operation_seconds, wall=time.monotonic() - started, start=start, cmds=cmds,
                torch_setup=torch_setup, role=role, candidate=candidate, share=share, **kwargs),
                "funding": funding, **({"resumed_after_operation": resumed_after} if resumed_after is not None else {}),
                **({"apt_layers": [{"packages": list(L["packages"]), "after_rest_commands": len(L["after_rest"])}
                                   for L in (*state.apt_layers, *extra_apt_layers)]} if (state.apt_layers or extra_apt_layers) else {}),
                **({"exit_wrapper": wrapper_note} if wrapper_note else {})})
            if checkpoint_mode or op["install_seconds"]:
                torch_note = ("torch installed" if op["torch_installed"] else
                              ("torch already in the start image" if op["torch_in_start_image"] else "no torch install"))
                _log(f"[operation {op['n']}] {role}: {outcome}; {op['sandbox_seconds']:.1f}s of sandbox time; {torch_note}; "
                     f"branch_from_image={op['branch_from_image']}; result_image={op['result_image']}; "
                     f"{len(op['kept_images'])} image(s) kept")
            return op

        try:
            result = deps.sandbox_runner(
                **runner_kwargs,
                api_key=deps.sandbox_api_key,
                project_id=deps.sandbox_project_id,
                base_image=use_plan.base_image,
                install_commands=steps,
                execute_command=execute_command,
                wall_clock_seconds=operation_seconds,
                upload_files=upload_files if fresh else None,
                # Git modes from the pinned commit (harness-v1.1): an executable
                # script stays executable in the sandbox.
                file_modes=modes,
            )
        except UploadIntegrityError as exc:
            # The bytes extracted in the sandbox are not the bytes uploaded (or the patch overlay did not land). What the completed
            # steps cost is spend (harness-v1.4.0-rc: the overlay check runs after the setup steps).
            spent = float(getattr(exc, "completed_cost_usd", 0.0) or 0.0)
            cost_guard.record_spend(spent)
            _record_op("void", exc=exc, cost_usd=spent)
            raise tree_integrity.HarnessIntegrityError(
                f"post-extraction check failed in the sandbox: {exc}",
                {**state.tree_integrity, "status": "post_extraction_mismatch", "sandbox_stderr": exc.stderr},
            ) from exc
        except SandboxCredentialsError as exc:
            raise infra.InfraError("sandbox", f"credentials: {exc}", cause=exc) from exc
        except SandboxTimeoutError as exc:
            # The killed step has no cost from the API: completed steps at their measured cost, the killed step at the
            # budget rate (an estimate, flagged in the record). Recorded BEFORE anything else can raise.
            recorded = cost_guard.record_killed_operation(
                exc.completed_cost_usd, exc.killed_seconds, note=f"killed after {exc.killed_seconds:.0f}s: {exc.command[:80]}"
            )
            killed_op = _record_op("killed", exc=exc, cost_usd=recorded, estimated_usd=recorded - exc.completed_cost_usd)
            if checkpoint_mode:
                _register_layers(use_plan.base_image, getattr(exc, "layers", ()) or (), killed_op["n"],
                                 patched=bool(start and start.get("patched")))
            _log(
                f"[cost_guard] operation stopped at {operation_seconds:.0f}s; recorded ${recorded:.4f} "
                f"({exc.completed_cost_usd:.4f} measured + estimate for the killed step), "
                f"${cost_guard.remaining_today_usd:.4f} left"
            )
            if operation_seconds < deps.sandbox_wall_clock_seconds - 1e-6:
                reason = f"a sandbox operation reached its budget-derived limit of {operation_seconds:.0f}s"
                # harness-v1.4.1-rc (D-31): the entry goes on while money left funds one operation AND an environment image is kept.
                kept = _best_layer(use_plan.base_image, cmds) if checkpoint_mode else None
                funds_now = cost_guard.operation_seconds_budget(share=max(share, 1))
                needed = _one_operation_seconds()
                if kept is not None and (kept["ops"] or not cmds) and funds_now >= needed and may_resume:
                    raise _BudgetStopResumable(kept, killed_op["n"], reason) from exc
                why = ("no environment image is kept" if kept is None or not (kept["ops"] or not cmds) else
                       f"${cost_guard.remaining_today_usd:.4f} left funds {funds_now:.0f}s, below one operation ({needed:.0f}s)"
                       if funds_now < needed else "the resume limit of this operation was reached")
                state.cost_capped = f"{reason}; not resumed: {why}"
                raise OperationBudgetExhausted(state.cost_capped) from exc
            raise
        if isinstance(result, SandboxRunResult):
            # harness-v1.4.3-rc (D-42): what THIS plan ran (a model's env delta may change it). harness-v1.8 (T11, review finding 3): as it ran, i.e. under
            # `bash -o pipefail -c` when it pipes into an interpreter, so the sustained run re-executes the same command.
            result = replace(result, base_command=command_shell.with_pipefail(use_plan.execute_command))
            if not evidence:
                # harness-v1.7.2 (D-46): an exit code 0 whose output is an uncaught traceback or only a usage message is not a pass (exit_zero_check).
                result = exit_zero_check.overrule(result)
                overruled = exit_zero_check.finding_of(result)
                if overruled:
                    _log(f"[exit-0 check] {role}: exit code 0 overruled ({overruled['kind']}: {overruled['evidence'][:200]}); {overruled['rule']} — "
                         "not a pass (harness-v1.7.2, D-46)")
        cost_guard.record_spend(result.total_cost_usd)
        op = _record_op("completed", result=result, cost_usd=result.total_cost_usd)
        if checkpoint_mode:
            # Layers built on top of an adopted (patched) image hold that patch too: their lineage is recorded. (Correctness does not
            # depend on it: every operation re-applies the full overlay of the checkout's changes.)
            _register_layers(use_plan.base_image, result.layers, op["n"], patched=bool(start and start.get("patched")))
        if checkpoint_mode and op["env_image_id"] and not keep_result:
            with op_lock:
                state.env_image = {"image": op["env_image_id"], "base_image": use_plan.base_image, "ops": tuple(cmds), "op": op["n"]}
        _log(
            f"[cost_guard] recorded ${result.total_cost_usd:.4f} sandbox spend, "
            f"${cost_guard.remaining_today_usd:.4f} remaining today"
        )
        return result

    try:
        sandbox_result = _execute(workdir, baseline=True)
    except (SandboxError, CostLimitExceeded) as exc:
        # harness-v1.1 audit: the only sandbox outcome attributable to the
        # repository here is the wall-clock ceiling (TIMEOUT). External API
        # failures are InfraError (-> INFRA_ERROR at the boundary); any other
        # SandboxError is RERUN's own bug (-> PIPELINE_ERROR). NOT_ATTEMPTABLE
        # remains only for RERUN's own spend cap being already exhausted.
        if isinstance(exc, SandboxError) and "wall clock" not in str(exc):
            raise
        _log(f"[sandbox] execution error: {exc}")
        return _finalize(
            verdict="INDETERMINATE" if state.cost_capped else ("TIMEOUT" if isinstance(exc, SandboxError) else "NOT_ATTEMPTABLE"),
            taxonomy_code=None,
            indeterminate_reason=_cost_cap_reason(state.cost_capped) if state.cost_capped else "",
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
    state.baseline = {
        "result": "RUNS_CLEAN" if sandbox_result.succeeded else "FAILS",
        "exit_code": sandbox_result.final.exit_code,
        "base_image": plan.base_image,
        "install_commands": list(plan.as_shell_steps()),
        "execute_command": plan.execute_command,
        "sandbox_id": sandbox_result.sandbox_id,
        "taxonomy_code": None,
        "evidence": "",
    }
    if state.pipefail:
        state.baseline["pipefail"] = True  # harness-v1.8 (T11); only when set (older records unchanged)
        plan = replace(plan, notes=(*plan.notes, command_shell.PIPEFAIL_NOTE))
    if exit_zero_check.finding_of(sandbox_result):
        state.baseline["exit_zero_check"] = exit_zero_check.finding_of(sandbox_result)  # harness-v1.7.2 (D-46); only when set (older records unchanged)
    _log(f"[baseline] as-is run: {state.baseline['result']} (exit code {sandbox_result.final.exit_code}"
         + (", overruled by the exit-0 check" if exit_zero_check.finding_of(sandbox_result) else "") + ")")

    attempts: list[AttemptRecord] = state.attempts
    verdict = "RUNS_CLEAN" if sandbox_result.succeeded else None
    taxonomy_code: str | None = None
    indeterminate_reason = ""

    def _collect_resource_evidence(role: str, why: str, phase: str = error_chain.PHASE_REPO_RUN) -> dict:
        """harness-v1.4.2-rc (D-38 / D-40). ONE evidence run per entry (TREATMENT only): the current command (through the exit wrapper if it is on) runs
        again with the sandbox's own limits and kill traces read after it (`runner_hooks.evidence_command`); recorded as attempt 0 / origin time_machine with
        `time_machine_action` {rule resource_evidence, evidence, kill_evidenced, limit_quote}. Never raises: a run that cannot be made leaves `collected` False
        and says why (the independent review found three ways it could raise or cost money for nothing: a kill during SETUP, where the sandbox stops before the
        command and no block can print; an evidence run the entry cannot afford, whose budget stop would then end the entry COST_CAP instead of the kill's
        verdict; an infrastructure or sandbox error, which would turn a decided RESOURCE_LIMIT into INFRA_ERROR)."""
        if state.resource_evidence is not None:
            return state.resource_evidence
        action = {"rule": "resource_evidence", "matched_error": why[:500], "phase": "repair",
                  "fires_on": "a failure classified RESOURCE_LIMIT, or a silent exit the exit hook and the exit wrapper could not explain (D-38, D-40)",
                  "limit": "reads what the sandbox shows after the command (/proc/meminfo, nproc, cgroup memory files, dmesg, ulimit): none of these is guaranteed to "
                           "exist or be readable; the run repeats the command, so a kill that depends on timing may not repeat"}
        found: dict = {"collected": False, "evidence": None, "kill_evidenced": False, "limit_quote": ""}
        if not deps.repair_enabled:
            found["reason"] = "repair is off for this arm: no extra operation is run"
        elif phase != error_chain.PHASE_REPO_RUN:
            found["reason"] = (f"the kill happened in the {phase} phase; the evidence is read after the repository's own command, which the sandbox "
                               "never reached, so no evidence run was made")
        else:
            capped_before = state.cost_capped
            try:
                result = _execute(workdir, smoke=True, role=role, evidence=True)
            except Exception as exc:  # noqa: BLE001 - the kill is already decided; a failed evidence run only means no evidence
                state.cost_capped = capped_before  # an evidence run the entry cannot fund must not end the entry COST_CAP
                found["reason"] = f"the evidence run did not complete: {type(exc).__name__}: {str(exc)[:300]}"
                action["stopped"] = found["reason"]
                attempts.append(AttemptRecord(0, "", "PASS", (), None, "", found["reason"][-2000:], origin="time_machine", time_machine_action=action))
            else:
                parsed = runner_hooks.parse_evidence(result.final.stderr, result.final.stdout)
                found.update(collected=parsed is not None, evidence=parsed, kill_evidenced=runner_hooks.kill_evidenced(parsed),
                             limit_quote=runner_hooks.limit_quote(parsed), exit_code=result.final.exit_code)
                if parsed is None:
                    found["reason"] = ("the run's output was cut by the API and the evidence block, printed last, was not returned"
                                       if getattr(result.final, "truncated", False) else "the run printed no evidence block")
                action.update(evidence=parsed, kill_evidenced=found["kill_evidenced"], limit_quote=found["limit_quote"])
                _log(f"[time-machine] resource evidence: kill evidenced={found['kill_evidenced']}; {found['limit_quote'] or found.get('reason', '')}")
                attempts.append(AttemptRecord(0, "", "PASS", (), result.final.exit_code, result.final.stdout[-2000:], result.final.stderr[-2000:],
                                              origin="time_machine", execution=_execution_of(result, True), time_machine_action=action))
        state.resource_evidence = found
        return found

    adapt_cache: list = []

    def _adaptation(round_no: int):
        """harness-v1.7 (R1 d): the resource_adapt rewrite of the documented command for `round_no`, or None (with the reason logged once)."""
        if not adapt_cache:
            entry, why = resource_adapt.entry_of(state.baseline.get("execute_command") or plan.execute_command)
            options = resource_adapt.option_groups(workdir, entry) if entry is not None else {}
            adapt_cache.append((entry, why if entry is None else ("no batch-size option" if not options else "ok"), options))
        entry, why, options = adapt_cache[0]
        if entry is None or not options:
            return None
        found, _ = resource_adapt.adapt(state.baseline.get("execute_command") or plan.execute_command, options, round_no)
        return found

    def _memory_rule_next(phase: str = error_chain.PHASE_REPO_RUN) -> str | None:
        """harness-v1.7 (R1): the next memory rule for a RESOURCE_LIMIT, in the pre-registered order, or None when both are spent (then the stop).
        Only for a kill of the documented command itself (phase repo_run): a kill while installing is not something a DataLoader or a batch size
        changes (v1.7 review, L5). resource_adapt only once swap_file is decided (runner_env.SWAP_FILE_DECIDED; v1.7 review, M6)."""
        if not deps.repair_enabled or not _declares_kwarg(deps.sandbox_runner, "runner_extras") or phase != error_chain.PHASE_REPO_RUN:
            return None
        if not state.memory_hook:
            return "hook"
        done = (state.resource_adapt or {}).get("round", 0)
        if runner_env.SWAP_FILE_DECIDED and done < resource_adapt.MAX_ROUNDS and _adaptation(done + 1) is not None:
            return "adapt"
        return None

    def _resource_reason(classification, phase: str = error_chain.PHASE_REPO_RUN) -> str:
        """The INDETERMINATE reason of a RESOURCE_LIMIT: the kill, the limits as the sandbox showed them (else as documented), and that no model attempt was made."""
        found = _collect_resource_evidence("resource evidence", classification.evidence, phase)
        quote = found.get("limit_quote") or resource_limits.quote()
        no_evidence = f" No evidence was read: {found['reason']}." if not found.get("collected") and found.get("reason") else ""
        return (f"RESOURCE_LIMIT: {classification.evidence}; limits ({quote}) — the sandbox killed the process; not a verdict on the repository, "
                f"and no repair attempt was made.{no_evidence}")

    def _note_failure(attempt_number: int, classification, phase: str = "repo_run", *, record: bool = True, may_defer: bool = True,
                      result=None) -> str | None:
        """Record a classified failure in the run's error chain. Returns an
        INDETERMINATE reason if the failure is sandbox-side (a limit or a platform
        refusal): no repair can fix it and it is not evidence about the code.
        `record=False` (harness-v1.7): the link is already in the chain; only the stop is decided. `may_defer` (harness-v1.7): a deterministic
        pass is still ahead (the loop at the top of a model attempt), so a v1.7 rule may take the failure first; False after the LAST model
        attempt, where a deferred stop would otherwise end the run BLOCKED (found by the v1.4.2 kill tests).
        `result` (harness-v1.7.2, D-46): the run classified; when the exit-zero check overruled its exit code 0, the new link carries it."""
        links_before = len(state.error_chain.links)
        if record:
            state.error_chain.record(
                attempt_number,
                classification.code,
                classification.evidence,
                error_chain.attribute(
                    classification.code,
                    classification.evidence,
                    declared_deps=intake_result.declared_dependencies,
                    python_claim=intake_result.python_version_hint,
                    base_image=plan.base_image,
                    phase=phase,
                ),
                phase,
            )
        overruled = exit_zero_check.finding_of(result)
        if overruled and len(state.error_chain.links) > links_before:
            state.error_chain.links[-1]["exit_zero_check"] = overruled  # only on a link this overruled run added (older chains unchanged)
        if classification.code == classifier.TaxonomyCode.RESOURCE_LIMIT and may_defer and _memory_rule_next(phase) is not None:
            return None  # harness-v1.7 (R1): the memory hook, then resource_adapt, get their turn (the deterministic loop) before the stop below
        if classification.code == classifier.TaxonomyCode.RESOURCE_LIMIT:
            return _resource_reason(classification, phase)
        if classification.code in classifier.TaxonomyCode.SANDBOX_CODES:
            return f"{classification.code}: {classification.evidence} — a sandbox-side failure, not a verdict on the repository."
        if classification.code == classifier.TaxonomyCode.APT_MIRROR_GONE and may_defer and deps.repair_enabled and not state.apt_archive:
            return None  # harness-v1.7 (R4): the apt-archive rule gets one try (the deterministic loop) before the stop below
        if classification.code == classifier.TaxonomyCode.APT_MIRROR_GONE:
            # harness-v1.6: ENV attribution alone does not end a run (a declared package the runner failed to install is ENV
            # too, and the time machine may still fix it); the INDETERMINATE stop is decided here, by the code, exactly as
            # for the sandbox classes. No repair can bring a distribution back to the mirrors, in any phase.
            return (f"APT_MIRROR_GONE: {classification.evidence} — the base image's distribution is no longer on the apt "
                    "mirrors; RERUN chose the image, so this is not a verdict on the repository and no repair attempt was made.")
        if phase == error_chain.PHASE_RUNNER_SETUP:
            return (f"RUNNER_SETUP_FAILED: {classification.evidence} — RERUN's own setup step failed before the "
                    "repository's first command ran; not a verdict on the repository.")
        return None

    internal_modules_cache: list[frozenset[str]] = []

    def _internal_modules() -> frozenset[str]:
        """Names that resolve inside the repository (dep_scan): never installed from PyPI (D-1, D-12). harness-v1.6: also
        handed to every classification as `repo_modules`, so an `ImportError: cannot import name` from the repository's
        own package is a code bug and not API_REMOVED. Walked once per run, on the first failure."""
        if not internal_modules_cache:
            internal_modules_cache.append(dep_scan.internal_module_names(workdir))
        return internal_modules_cache[0]

    baseline_result = sandbox_result
    # harness-v1.7 (R5, companion_relax): the runner's torch-family install failed because the repository pins torch and torchvision exactly, to
    # releases that cannot be installed together (DEV #5: torch==1.2.0 with torchvision==0.5.0, which requires torch 1.4.0). Deterministic, in the
    # TREATMENT arm only, once, before the RUNNER_SETUP_FAILED stop: the torch pin is kept and torchvision becomes the release made for it
    # (runner_env.companion_swap, a dated snapshot of PyPI's metadata). The as-published failure stays the baseline's and the chain's first link.
    if not sandbox_result.succeeded and deps.repair_enabled and sandbox_result.final.phase == error_chain.PHASE_RUNNER_SETUP \
            and _accepts_kwarg(deps.sandbox_runner, "torch_setup"):
        baseline_cls = _classify_run(sandbox_result.final.exit_code, sandbox_result.final.stderr, sandbox_result.final.stdout,
                                           declared_deps=intake_result.declared_dependencies, repo_modules=_internal_modules())
        swap = None
        relax_rule = "companion_relax"
        if baseline_cls.code == classifier.TaxonomyCode.DEP_UNPINNED_CONFLICT and "ResolutionImpossible" in (
                f"{sandbox_result.final.stderr}\n{sandbox_result.final.stdout}"):
            baseline_torch = runner_env.plan_torch_setup([*plan.as_shell_steps(), *intake_result.dependency_files.values()], workdir)
            swap = runner_env.companion_swap(baseline_torch.specs) if baseline_torch is not None else None
        elif baseline_cls.code == classifier.TaxonomyCode.DEP_YANKED:
            # harness-v1.8 (T2, TEST-B #2 ovis): the repository pins `torchvision==0.6.0a0`, a pre-release the index never served; the runner's own install
            # failed before the baseline ran. The same deterministic path as R5: the final release is pinned instead, labelled a dependency change.
            baseline_torch = runner_env.plan_torch_setup([*plan.as_shell_steps(), *intake_result.dependency_files.values()], workdir)
            swap = (prerelease_pin.relax_for(f"{sandbox_result.final.stderr}\n{sandbox_result.final.stdout}", baseline_torch.specs)
                    if baseline_torch is not None else None)
            relax_rule = prerelease_pin.RULE
        if swap is not None:
            state.baseline["taxonomy_code"] = baseline_cls.code
            state.baseline["evidence"] = baseline_cls.evidence
            _log(f"[classifier] {baseline_cls.code}: {baseline_cls.evidence}")
            _note_failure(0, baseline_cls, sandbox_result.final.phase)  # the as-published failure is the chain's first link; its stop is deferred
            state.torch_overrides = swap.overrides()
            plan = replace(plan, notes=(*plan.notes, f"{relax_rule} ({'harness-v1.7, R5' if relax_rule == 'companion_relax' else 'harness-v1.8, T2'}; a DEPENDENCY CHANGE, labelled): "
                                                      f"{swap.as_dict()['reason']}; {swap.package}=={swap.replacement} instead of {swap.pinned}"))
            relax_action = {"rule": relax_rule, "matched_error": baseline_cls.evidence[:500], "phase": "repair",
                            "fires_on": ("DEP_UNPINNED_CONFLICT in the runner's torch-family install, exact torch and torchvision pins that cannot coexist"
                                         if relax_rule == "companion_relax" else
                                         "DEP_YANKED in the runner's torch-family install: an exact pin to a pre-release the index does not serve"),
                            **swap.as_dict()}
            # harness-v1.7.1: the repository's own `pip install -r requirements.txt` runs after the runner's torch step and would put its pins back (DEV #5's
            # file pins torchvision==0.5.0 and Pillow==9.0.0). The swap's pins go into RERUN's copy of the file (env_repair; the repository's file is never edited).
            plan, state.companion_requirements, relax_action["requirements_pins"] = _companion_requirements(
                plan, swap, intake_result.dependency_files.get("requirements.txt"), baseline_cls.evidence)
            for pin in relax_action["requirements_pins"]:
                for also in relax_action["also"]:
                    if also["package"].lower() == pin["package"].lower():
                        also["from"] = pin["from"]
            _log(f"[time-machine] deterministic step: {relax_rule} ({swap.package} {swap.pinned} -> {swap.replacement}"
                 + (f", {swap.primary}=={swap.primary_version} kept" if swap.primary else "") + f": {swap.as_dict()['reason']}); no model call")
            try:
                relaxed = _execute(workdir, smoke=True, role=f"time machine: {relax_rule}")
            except CostLimitExceeded as exc:
                _log(f"[time-machine] stopped: {exc}")
                attempts.append(AttemptRecord(0, "", "PASS", (), None, "", f"stopped before completion: {exc}"[-2000:], origin="time_machine",
                                              time_machine_action=relax_action))
            else:
                _log(f"[time-machine] re-execution id={relaxed.sandbox_id} exit_code={relaxed.final.exit_code}")
                attempts.append(AttemptRecord(0, "", "PASS", (), relaxed.final.exit_code, relaxed.final.stdout[-2000:], relaxed.final.stderr[-2000:],
                                              origin="time_machine", execution=_execution_of(relaxed, True), time_machine_action=relax_action))
                sandbox_result = relaxed
                taxonomy_code = baseline_cls.code
                if relaxed.succeeded:
                    state.error_chain.clear_last(0)
                    verdict = "RUNS_AFTER_REPAIR"

    if not sandbox_result.succeeded and exit_zero_check.stop_of(sandbox_result):
        # harness-v1.7.2 (D-46): the command exited 0 after printing only a usage message: the entry point did not get the arguments it needs and
        # nothing ran. INDETERMINATE ENTRYPOINT_NEEDS_ARGS, with the usage line as evidence; no classification, no repair, no model call (a code
        # change cannot supply a command's arguments).
        stop = exit_zero_check.stop_of(sandbox_result)
        if sandbox_result is baseline_result and state.baseline.get("taxonomy_code") is None:
            state.baseline["evidence"] = stop["evidence"]
        reason = exit_zero_check.stop_reason(stop)
        _log(f"[verdict] INDETERMINATE: {reason}")
        return _finalize(
            verdict="INDETERMINATE",
            taxonomy_code=None,
            indeterminate_reason=reason,
            attempts=tuple(attempts),
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

    entry_stop = None if sandbox_result.succeeded else entry_blockers.stop_of(
        sandbox_result.final.exit_code, sandbox_result.final.stdout, sandbox_result.final.stderr)
    if entry_stop is not None:
        # harness-v1.7.2 (live scan 2026-10-05): the run failed because the entry point did not get the arguments it reads, or because it opens a
        # window and the sandbox has no display. INDETERMINATE with the evidence line; no classification, no repair, no model call (a code change
        # could only invent the input, or cannot supply a display at all).
        if sandbox_result is baseline_result and state.baseline.get("taxonomy_code") is None:
            state.baseline["evidence"] = entry_stop["evidence"]
        reason = entry_blockers.stop_reason(entry_stop)
        _log(f"[verdict] INDETERMINATE: {reason}")
        return _finalize(
            verdict="INDETERMINATE",
            taxonomy_code=None,
            indeterminate_reason=reason,
            attempts=tuple(attempts),
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

    if not sandbox_result.succeeded:
        state.stage = "classifier"
        classification = _classify_run(
            sandbox_result.final.exit_code,
            sandbox_result.final.stderr,
            sandbox_result.final.stdout,
            declared_deps=intake_result.declared_dependencies,
            repo_modules=_internal_modules(),
        )
        taxonomy_code = classification.code
        same_as_baseline = sandbox_result is baseline_result and state.baseline.get("taxonomy_code") is not None
        if state.baseline.get("taxonomy_code") is None:  # harness-v1.7 (R5): a step before this block may have recorded the baseline already
            state.baseline["taxonomy_code"] = classification.code
            state.baseline["evidence"] = classification.evidence
        if not same_as_baseline:
            _log(f"[classifier] {classification.code}: {classification.evidence}")
        sandbox_reason = _note_failure(0, classification, sandbox_result.final.phase, record=not same_as_baseline, may_defer=deps.max_attempts >= 1,
                                       result=sandbox_result)
        if sandbox_reason:
            _log(f"[verdict] INDETERMINATE: {sandbox_reason}")
            return _finalize(
                verdict="INDETERMINATE",
                taxonomy_code=classification.code,
                indeterminate_reason=sandbox_reason,
                attempts=tuple(attempts),  # the baseline-kill evidence run (D-40) is an operation and is recorded, not only quoted
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

        # Env repair edits a RERUN-owned copy of requirements.txt (never the
        # repo's file); this tracks it across attempts. Imports are scanned
        # lazily, only if an env change needs checking.
        current_requirements = state.companion_requirements or intake_result.dependency_files.get("requirements.txt")  # harness-v1.7.1 (R5)
        imported_modules: frozenset[str] | None = None

        resolved_lock: list[str] | None = None  # set by the time machine
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

        # Failed-move memory: normalized env changes this run applied and then
        # saw the re-execution fail. A proposal repeating one is re-asked once,
        # then rejected (found live: TTPT's repairer re-proposed a no-op numpy add).
        failed_moves: set[tuple] = set()
        untested_moves: dict[tuple, int] = {}  # harness-v1.8 (T1): env changes of a non-adopted candidate whose run died on some other error

        def _settle_moves(changes, result) -> dict[str, str]:
            """harness-v1.8 (T1, owner 2026-10-07: "a move is recorded failed only if the error it targeted is still present after applying it; if the run died on a
            different or earlier error, record it untested and allow exactly one retry on the winning branch"). Applies to the env changes of a candidate that was
            NOT adopted and whose run did not succeed. Before, every such change went into `failed_moves` and the gate-side repeat check then refused the model
            to propose it again: TEST-B #8 (gandissect) round 1, candidate 3's `apt libfreetype6-dev` cited the `ft2build.h` line, its run died on another error
            (the cited line was gone from its output), and in round 2 the same apt package was refused as 'already tried and failed', so the fix for the
            error the run ended on was never applied.

            Now: the cited line still in the new output -> "failed" (barred, as before). Anything else -> "untested": allowed again once (the next round starts
            from the adopted candidate's environment, the winning branch); the second untested outcome bars it like a failure. The gate's rules are not touched:
            only what this function puts into `failed_moves` / `untested_moves`, which `_repeats` reads, changes. Returns {"<op> <package>": status} for the record."""
            text = f"{result.final.stderr}\n{result.final.stdout}" if result is not None else ""
            outcome: dict[str, str] = {}
            # review (finding 7): a change whose OWN install is what failed (a pin that does not exist, an apt name Debian does not know) never reached its cited
            # error: that is the change's fault, so it is "failed", not "untested" (the same test the candidate flow already applies: `_self_inflicted`)
            own: str | None = None
            if result is not None and result.steps:
                try:
                    own = _self_inflicted(_classify_run(result.final.exit_code, result.final.stderr, result.final.stdout,
                                                        declared_deps=intake_result.declared_dependencies, repo_modules=_internal_modules()),
                                          [c.as_dict() for c in changes], intake_result.declared_dependencies)
                except Exception:  # noqa: BLE001 - a result the classifier cannot read (a killed step): judged by the cited line alone
                    own = None
            for c in changes:
                key = env_repair.change_key(c)
                label = f"{c.op} {c.package or c.command or c.version}"
                status = move_status(c, text, own)
                if status == "failed":
                    failed_moves.add(key)
                else:
                    untested_moves[key] = untested_moves.get(key, 0) + 1
                outcome[label] = status
            return outcome
        isolated_packages: set[str] = set()

        def _auto_build_isolation(failed: SandboxRunResult) -> SandboxRunResult | None:
            """Deterministic step (no model): when the failed run's log meets
            the env gate's own build-isolation rule for a locked package, build
            that package with --no-build-isolation and re-execute. Returns the
            re-execution's result, or None if the rule doesn't hold."""
            nonlocal plan, current_requirements
            if resolved_lock is None or current_requirements is None:
                return None
            locked = tuple(current_requirements.splitlines())
            log = f"{failed.final.stderr}\n{failed.final.stdout}"
            found = env_repair.find_build_isolation_candidate(log, locked, frozenset(isolated_packages))
            if found is None:
                return None
            package, module, evidence = found
            isolated_packages.add(package)
            change = env_repair.EnvChange(
                op="pip_no_build_isolation",
                package=package,
                justification=f"deterministic: {package}'s isolated build could not import {module}, which the lock installs",
                evidence=evidence,
            )
            step = {"step": "pip_no_build_isolation", "package": package, "module": module, "evidence": evidence}
            # The same gate a model proposal faces.
            violations = env_repair.check_env_delta(
                (change,), log_text=log, imported_modules=frozenset(), has_requirements_txt=True, locked_requirements=locked
            )
            if violations:
                _log(f"[time-machine] build-isolation step refused by the env gate: {'; '.join(v.reason for v in violations)}")
                return None
            plan, new_requirements = env_repair.apply_env_delta(plan, (change,), current_requirements)
            if new_requirements is not None:
                current_requirements = new_requirements
            _log(f"[time-machine] deterministic step: pip_no_build_isolation {package} (evidence: {evidence})")
            state.build_plan_dict = plan.as_dict()
            try:
                result = _execute(workdir, smoke=True)
            except CostLimitExceeded as exc:
                _log(f"[time-machine] stopped: daily cost ceiling reached: {exc}")
                return None
            except (SandboxTimeoutError, tree_integrity.HarnessIntegrityError) as exc:
                attempts.append(
                    AttemptRecord(0, "", "PASS", (), None, "", str(exc)[-2000:], (), (change.as_dict(),), (),
                                  origin="time_machine", time_machine=step)
                )
                raise
            _log(f"[time-machine] re-execution id={result.sandbox_id} exit_code={result.final.exit_code}")
            attempts.append(
                AttemptRecord(
                    0, "", "PASS", (), result.final.exit_code, result.final.stdout[-2000:], result.final.stderr[-2000:],
                    (), (change.as_dict(),), (), origin="time_machine", time_machine=step,
                    execution=_execution_of(result, True),
                )
            )
            if not result.succeeded:
                failed_moves.add(env_repair.change_key(change))
            return result

        def _auto_system_packages(failed: SandboxRunResult, need: "system_packages.SystemNeed") -> SandboxRunResult | None:
            """harness-v1.3.5-unvalidated (D-24, post-gate; no gate has validated it). Deterministic step (no model): the failure
            being repaired names a missing C compiler, so `build-essential` goes into the apt step and the command is re-executed.
            Before D-24 the rule only fired on the baseline classification, and a missing compiler found after a repair went to the
            model (corpus-v2 entry 7 in the v1.3.4 gate: the model proposed `gcc` as a pip package).

            harness-v1.8 (T5): the same step for a missing C header (`ft2build.h` -> libfreetype6-dev) or tool (`which g++`, `git`), from the
            `system_packages` tables, on SYS_LIB_MISSING and DEP_BUILD_FAILED (`system_need`). The compiler case keeps the v1.3.5 record and
            log text. Returns the re-execution's result, or None if the env gate refuses the step or the budget stops it."""
            nonlocal plan, current_requirements
            matched_error = need.evidence
            packages = tuple(p for p in need.packages if p not in plan.apt_install)
            log = f"{failed.final.stderr}\n{failed.final.stdout}"
            compiler_case = need.rule == BUILD_ESSENTIAL_RULE
            changes = tuple(
                env_repair.EnvChange(
                    op="apt",
                    package=pkg,
                    justification=("deterministic: the failing run could not execute a C compiler" if compiler_case else
                                   f"deterministic: the failing run could not find {need.item} ({need.kind}); apt package {pkg} provides it"),
                    evidence=matched_error,
                )
                for pkg in packages
            )
            what = "build-essential" if compiler_case else " ".join(packages)
            action = {"rule": need.rule, "matched_error": matched_error, "apt_added": list(packages), "phase": "repair"}
            if not compiler_case:
                action["needed"] = {"kind": need.kind, "item": need.item}
            # The same gate a model proposal faces (the evidence must be in the failing run's log, verbatim).
            violations = env_repair.check_env_delta(
                changes, log_text=log, imported_modules=frozenset(), has_requirements_txt=current_requirements is not None,
                locked_requirements=tuple(current_requirements.splitlines()) if resolved_lock is not None and current_requirements else None,
                apt_packages=frozenset(plan.apt_install),
            )
            if violations:
                _log(f"[time-machine] {what} step refused by the env gate: {'; '.join(v.reason for v in violations)}")
                return None
            plan_before = plan
            plan, new_requirements = env_repair.apply_env_delta(plan, changes, current_requirements)
            if new_requirements is not None:
                current_requirements = new_requirements
            # harness-v1.4.1-rc (D-34): an additive layer on the kept environment image, never a rebuild from the tree image.
            layer = _apt_layer_for(plan_before, plan)
            if layer is not None:
                state.apt_layers.append(layer)
                action["apt_layer"] = {"layering": "additive", "on_kept_image": layer["after_image"], "setup_commands_kept": layer["after_ops"]}
                _log(f"[time-machine] {what} goes in as an additive layer on kept image {layer['after_image']} "
                     f"({layer['after_ops']} setup command(s) stay in it)")
            _log(f"[time-machine] deterministic step: apt {what} (matched error: {matched_error}); no model call")
            state.build_plan_dict = plan.as_dict()

            def _record(exit_code, stdout, stderr, execution=None) -> None:
                attempts.append(
                    AttemptRecord(0, "", "PASS", (), exit_code, stdout, stderr, (), tuple(c.as_dict() for c in changes), (),
                                  origin="time_machine", execution=execution, time_machine_action=action)
                )

            try:
                result = _execute(workdir, smoke=True)
            except CostLimitExceeded as exc:
                _log(f"[time-machine] stopped: daily cost ceiling reached: {exc}")
                _record(None, "", f"stopped before completion: {exc}"[-2000:])
                return None
            except (SandboxTimeoutError, tree_integrity.HarnessIntegrityError) as exc:
                _record(None, "", str(exc)[-2000:])
                raise
            _log(f"[time-machine] re-execution id={result.sandbox_id} exit_code={result.final.exit_code}")
            _record(result.final.exit_code, result.final.stdout[-2000:], result.final.stderr[-2000:], _execution_of(result, True))
            if not result.succeeded:
                for _c in changes:
                    failed_moves.add(env_repair.change_key(_c))
            return result

        install_fixes: set[str] = set()

        def _auto_install_repair(failed: SandboxRunResult, fix: "install_repair.InstallFix") -> SandboxRunResult | None:
            """harness-v1.8 (T3). Deterministic step (no model): an install line the failing run shows cannot work any more, and the repair is a known one:
            a Debian package that has been renamed (`libgl1-mesa-glx` -> `libgl1`), or the retired `git://github.com/` protocol (-> `https://`, with `git`
            installed for pip's VCS support). The repository's own files are never edited: the rewrite goes into RERUN's copy of the requirements. Once per
            key per run; recorded as attempt 0 / origin time_machine with `time_machine_action`, and labelled a dependency change. Returns the
            re-execution's result, or None if the budget stops it."""
            nonlocal plan, current_requirements
            install_fixes.add(fix.key)
            plan = fix.plan
            if fix.requirements is not None:
                current_requirements = fix.requirements
            state.build_plan_dict = plan.as_dict()
            action = {"rule": fix.rule, "matched_error": fix.evidence, "phase": "repair", **fix.detail}
            plan = replace(plan, notes=(*plan.notes, f"{fix.rule} (harness-v1.8, T3; a DEPENDENCY CHANGE, labelled): {json.dumps(fix.detail)[:300]}"))
            state.build_plan_dict = plan.as_dict()
            _log(f"[time-machine] deterministic step: {fix.rule} (matched: {fix.evidence[:200]}); no model call")

            def _record(exit_code, stdout, stderr, execution=None) -> None:
                attempts.append(AttemptRecord(0, "", "PASS", (), exit_code, stdout, stderr, origin="time_machine",
                                              execution=execution, time_machine_action=action))

            try:
                result = _execute(workdir, smoke=True, role=f"time machine: {fix.rule}")
            except CostLimitExceeded as exc:
                _log(f"[time-machine] stopped: {exc}")
                _record(None, "", f"stopped before completion: {exc}"[-2000:])
                return None
            except (SandboxTimeoutError, tree_integrity.HarnessIntegrityError) as exc:
                _record(None, "", str(exc)[-2000:])
                raise
            _log(f"[time-machine] re-execution id={result.sandbox_id} exit_code={result.final.exit_code}")
            _record(result.final.exit_code, result.final.stdout[-2000:], result.final.stderr[-2000:], _execution_of(result, True))
            return result

        removals_applied: set[str] = set()

        def _auto_api_removal(failed: SandboxRunResult, rule: api_removals.Removal, evidence: str) -> SandboxRunResult | None:
            """harness-v1.5.1 (F2, failure class: the code uses an API a newer release removed). Deterministic step (no model): the failing run's log names a removed API
            that api_removals knows (torch's `zero_gradients`, TensorFlow 1's graph API), so the package is pinned to the one release that still has it and, when the current
            Python cannot install that release, the Python moves to one that can; the command is re-executed. The same env gate a model proposal faces checks it (the evidence
            is the matched log text, verbatim). Once per rule per run. Returns the re-execution's result, or None if no release fits, the gate refuses, the budget stops it, or
            the changed environment could not even be set up: then the build plan and the requirements are put back exactly as they were, so the model repairs the ORIGINAL
            failure and the step can never leave the run worse off than not taking it (the independent review: a companion pin such as `torchvision==0.10.0` conflicts with
            the older torch, and a failed setup would otherwise end the entry INDETERMINATE with no model attempt)."""
            nonlocal plan, current_requirements
            removals_applied.add(rule.rule)
            log = f"{failed.final.stderr}\n{failed.final.stdout}"
            current = re.match(r"^python:(\d+\.\d+)-slim$", plan.base_image)
            chosen = api_removals.plan(rule, current.group(1) if current else "")
            action = {"rule": rule.rule, "matched_error": evidence, "package": rule.package, "bound": rule.bound, "phase": "repair"}
            if chosen is None:
                _log(f"[time-machine] {rule.rule}: no release of {rule.package}{rule.bound} has a wheel for a Python image; the step is not taken")
                return None
            release, move, reason = chosen
            if move and resolved_lock is not None:
                _log(f"[time-machine] {rule.rule}: needs Python {move} but the era lock was compiled for another interpreter; the step is not taken")
                return None
            python_after = move or (current.group(1) if current else "")
            justification = f"deterministic: {reason}"[:300]
            changes = ((env_repair.EnvChange(op="python", version=move, justification=justification, evidence=evidence),) if move else ()) + (
                env_repair.EnvChange(op="pin", package=rule.package, version=release, justification=justification, evidence=evidence),)
            # what the release needs beside it, given the repository's requirements / the era lock: packages pinned to a release it cannot be installed with are swapped, a
            # protobuf it cannot import with is replaced, `tensorflow-gpu` / `-cpu` are removed (api_removals.companion_actions)
            for op, name, version in api_removals.companion_actions(rule, python_after, (current_requirements or "").splitlines()):
                changes += (env_repair.EnvChange(op=op, package=name, version=version,
                                                 justification=(f"deterministic: {rule.package}=={release} cannot be installed beside {name}" if op == "remove"
                                                                else f"deterministic: {rule.package}=={release} needs {name}=={version}")[:300], evidence=evidence),)
            if any(env_repair.change_key(c) in failed_moves for c in changes):
                _log(f"[time-machine] {rule.rule}: this change was applied before and failed; the step is not taken")
                return None
            violations = env_repair.check_env_delta(
                changes, log_text=log, imported_modules=frozenset(), has_requirements_txt=current_requirements is not None,
                locked_requirements=tuple(current_requirements.splitlines()) if resolved_lock is not None and current_requirements else None,
                repo_internal_modules=_internal_modules(), apt_packages=frozenset(plan.apt_install),
            )
            if violations:
                _log(f"[time-machine] {rule.rule}: step refused by the env gate: {'; '.join(v.reason for v in violations)}")
                return None
            plan_before, requirements_before, plan_dict_before = plan, current_requirements, state.build_plan_dict
            plan, new_requirements = env_repair.apply_env_delta(plan, changes, current_requirements)
            if new_requirements is not None:
                current_requirements = new_requirements
            action.update(pinned=release, python=python_after or None, python_changed=bool(move), reason=reason,
                          companions=[{"op": c.op, "package": c.package, "version": c.version} for c in changes if c.package not in (None, rule.package)])
            _log(f"[time-machine] deterministic step: {rule.rule} (matched: {evidence}); {reason}; no model call")
            state.build_plan_dict = plan.as_dict()

            def _record(exit_code, stdout, stderr, execution=None) -> None:
                attempts.append(AttemptRecord(0, "", "PASS", (), exit_code, stdout, stderr, (), tuple(c.as_dict() for c in changes), (),
                                              origin="time_machine", execution=execution, time_machine_action=action))

            def _put_back(why: str) -> None:
                nonlocal plan, current_requirements
                plan, current_requirements, state.build_plan_dict = plan_before, requirements_before, plan_dict_before
                action["put_back"] = why
                _log(f"[time-machine] {rule.rule}: {why}; the build plan is put back as it was and the failure goes on to the repair model")

            try:
                result = _execute(workdir, smoke=True, role=f"time machine: {rule.rule}")
            except CostLimitExceeded as exc:
                _log(f"[time-machine] stopped: daily cost ceiling reached: {exc}")
                _put_back("the budget stopped the re-execution")
                _record(None, "", f"stopped before completion: {exc}"[-2000:])
                return None
            except (SandboxTimeoutError, tree_integrity.HarnessIntegrityError) as exc:
                _record(None, "", str(exc)[-2000:])
                raise
            _log(f"[time-machine] re-execution id={result.sandbox_id} exit_code={result.final.exit_code}")
            if not result.succeeded and result.final.phase in (error_chain.PHASE_RUNNER_SETUP, error_chain.PHASE_REPO_INSTALL):
                _put_back("the changed environment failed in a setup step (" + result.final.phase + "), before the repository's command ran")
                _record(result.final.exit_code, result.final.stdout[-2000:], result.final.stderr[-2000:], None)
                return None
            _record(result.final.exit_code, result.final.stdout[-2000:], result.final.stderr[-2000:], _execution_of(result, True))
            if not result.succeeded and rule.pattern.search(f"{result.final.stderr}\n{result.final.stdout}"):
                # the same API is still missing: this change did not help. (A DIFFERENT later error does not poison the change for the model.)
                for c in changes:
                    failed_moves.add(env_repair.change_key(c))
            return result

        def _with_build_isolation(result: SandboxRunResult) -> SandboxRunResult:
            while not result.succeeded:
                next_result = _auto_build_isolation(result)
                if next_result is None:
                    break
                result = next_result
            return result

        # --- Time machine (attempt 0): the repo's own era, deterministically --
        era_first = classifier.repair_layer_for(classification.code) == "env"
        if era_first and classification.code == classifier.TaxonomyCode.APT_MIRROR_GONE:
            # harness-v1.7 (R4): with the mirrors gone every install fails, so the era lock would spend an operation for nothing; the apt-archive
            # step goes first (the deterministic loop). v1.6 stopped here, with no time machine either.
            era_first = False
            _log("[time-machine] skipped ahead of the apt-archive rule: nothing installs while the mirrors are gone")
        if era_first and deps.repair_enabled:
            # harness-v1.8 (T3): the install line itself cannot work (a renamed apt package, the retired git:// protocol); an era lock built on top of it would fail at
            # the same line, so the deterministic repair goes FIRST (it re-executes) and the era lock then runs on whatever the repaired plan fails on. (Independent review,
            # finding 2: the first version of this skipped the era lock for good.) An apt package with no known successor (`libjasper-dev`) is not repairable here: the era
            # lock would only fail at the same apt line, so the failure goes straight to the model (review, finding 8).
            _head_log = f"{sandbox_result.final.stderr}\n{sandbox_result.final.stdout}"
            _pre_fix = install_repair.fix_for(_head_log, plan, current_requirements, frozenset(install_fixes))
            if _pre_fix is not None:
                state.stage = "time_machine"
                _pre = _auto_install_repair(sandbox_result, _pre_fix)
                if _pre is None:  # the budget stopped it: the loop below sees state.cost_capped
                    era_first = False
                else:
                    if not _pre.succeeded:
                        _pre = _with_build_isolation(_pre)
                    sandbox_result = _pre
                    if _pre.succeeded:
                        verdict = "RUNS_AFTER_REPAIR"
                        state.error_chain.clear_last(0)  # the deterministic step cleared the failure
                        era_first = False
                    else:
                        classification = _classify_run(_pre.final.exit_code, _pre.final.stderr, _pre.final.stdout,
                                                       declared_deps=intake_result.declared_dependencies, repo_modules=_internal_modules())
                        taxonomy_code = classification.code
                        _log(f"[classifier] {classification.code}: {classification.evidence}")
                        _pre_reason = _note_failure(0, classification, _pre.final.phase, result=_pre)
                        if _pre_reason:
                            verdict, indeterminate_reason = "INDETERMINATE", _pre_reason
                            _log(f"[verdict] INDETERMINATE: {_pre_reason}")
                            era_first = False
                        else:
                            era_first = classifier.repair_layer_for(classification.code) == "env"
            elif re.search(r"has no installation candidate|Unable to locate package", _head_log):
                era_first = False
                _log("[time-machine] skipped the era lock: an apt package the plan names has no installation candidate and no known successor")
        if era_first and classification.code == classifier.TaxonomyCode.API_REMOVED and api_removals.match(
                f"{sandbox_result.final.stderr}\n{sandbox_result.final.stdout}"):
            # harness-v1.6: an API_REMOVED failure that a removed-API row (api_removals, F2) covers keeps the order validated at
            # v1.5.1/v1.5.2: the row's EXACT recorded release (and the Python that installs it) goes first, in the deterministic
            # loop below; the era lock, inferred from a date, is not run ahead of it. API_REMOVED failures no row covers still
            # take the era lock first.
            era_first = False
            _log(f"[time-machine] skipped ahead of the removed-API rule for {classification.code}: the rule's recorded release goes first")
        if deps.repair_enabled and era_first:
            state.stage = "time_machine"
            era = _era()
            if era is not None:
                # harness-v1.3.3 (D-11): a Python version the repository declares (incl. its README) wins over the era
                # inference; before, only dependency-file hints counted and README 3.6 became era 3.10.
                declared_python = python_choice.version if python_choice.is_declared else intake_result.python_version_hint
                py_version, py_reason = time_machine.python_for_era(era.date, declared_python)
                if python_choice.is_declared and declared_python == python_choice.version and py_reason == "declared by the repository":
                    py_reason = f"declared by {python_choice.source} ({python_choice.declared})"
                if imported_modules is None:
                    imported_modules = env_repair.imported_top_level_modules(workdir)
                batch = time_machine.batch_for(workdir, intake_result.declared_dependencies)
                undeclared_mapped = list(batch.distributions)
                undeclared = [dist for dist, _ in undeclared_mapped]
                import_mappings = [m.as_dict() for _, m in undeclared_mapped if m is not None]
                for m in import_mappings:
                    _log(f"[import-map] {m['import']} -> {m['distribution']} ({m['source']}, confidence {m['confidence']})")
                lock = (deps.lock_compiler or time_machine.compile_lock)(
                    (current_requirements or "").splitlines(), undeclared, era.date, py_version
                )
                apt_added = ()
                _need = system_need(classification, f"{sandbox_result.final.stderr}\n{sandbox_result.final.stdout}")
                if _need:
                    # Deterministic known need: a missing C compiler (build-essential), and since harness-v1.8 (T5) a missing header or tool.
                    apt_added = _need.packages
                tm_record = {
                    "era": era.as_dict(),
                    "python": {"version": py_version, "reason": py_reason, "source": time_machine.PYTHON_RELEASES_SOURCE},
                    "undeclared_imports": list(undeclared),
                    # The whole-tree scan behind it (harness-v1.3.3): what is excluded as the repo's own, skipped as optional.
                    "batch_scan": batch.as_dict(),
                    # Every import -> distribution mapping the era lock used (harness-v1.1).
                    "import_mappings": import_mappings,
                    "apt_added": list(apt_added),
                    "apt_reason": _need.evidence if _need else "",
                    "lock": lock.as_dict(),
                }
                # Fallback (D-5): if no era lock can be produced, the whole batch still goes in ONE unpinned pip step on the
                # policy's interpreter, instead of dropping the era work and repairing one name per attempt. The torch
                # family is the runner's (runner_env), never part of this step.
                # Names the lock attempt found no era-appropriate release for (e.g. `curves`, whose only release is
                # from 2025) are not installed unpinned either: they are almost certainly not the repo's dependency.
                fallback_names = tuple(
                    n for n in undeclared
                    if n.lower() not in runner_env.TORCH_FAMILY and n not in set(lock.not_on_index)
                ) if not lock.ok else ()
                if fallback_names and not lock.ok and classification.code == classifier.TaxonomyCode.API_REMOVED:
                    # harness-v1.6: the unpinned fallback installs the NEWEST releases, which are exactly the ones that lack the
                    # name; only an era lock can answer an API_REMOVED failure, so without one the step is not spent.
                    _log(f"[time-machine] era lock unavailable ({lock.error[-200:].strip()!r}); no unpinned fallback for "
                         f"{classification.code}: the newest releases are the ones without the name")
                    fallback_names = ()
                if lock.ok or fallback_names:
                    if lock.ok:
                        _log(
                            f"[time-machine] era {era.date} ({era.source}) -> python {py_version}; "
                            f"locked {len(lock.lock_lines)} package(s) with uv --exclude-newer; "
                            f"not on the index: {list(lock.not_on_index) or 'none'}"
                        )
                        lock_lines = list(lock.lock_lines)
                        resolved_lock = lock_lines
                        plan_before = plan
                        plan = time_machine.apply_lock(plan, py_version, lock_lines, apt_added)
                        _era_layer = _apt_layer_for(plan_before, plan)
                        if _era_layer is not None:
                            state.apt_layers.append(_era_layer)
                        current_requirements = "\n".join(lock_lines) + "\n"
                    else:
                        _cause = time_machine.lock_failure_cause(lock.error)
                        _log(
                            f"[time-machine] era lock unavailable ({_cause['id'] + ': ' + _cause['detail'] if _cause else lock.error[-200:].strip()!r}); fallback: one pip step for "
                            f"{len(fallback_names)} undeclared import(s), unpinned, on {plan.base_image}"
                        )
                        plan_before = plan
                        plan = time_machine.apply_batch_pip(plan, fallback_names, apt_added)
                        _era_layer = _apt_layer_for(plan_before, plan)
                        if _era_layer is not None:
                            state.apt_layers.append(_era_layer)
                        tm_record["fallback"] = {"kind": "batch_pip_unpinned", "packages": list(fallback_names), "base_image": plan.base_image}
                    state.build_plan_dict = plan.as_dict()
                    try:
                        tm_result = _execute(workdir, smoke=True)
                    except CostLimitExceeded as exc:
                        _log(f"[time-machine] stopped: daily cost ceiling reached: {exc}")
                        tm_result = None
                        attempts.append(
                            AttemptRecord(0, "", "PASS", (), None, "", f"stopped before completion: {exc}"[-2000:],
                                          (), (), (), origin="time_machine", time_machine=tm_record)
                        )
                    except SandboxTimeoutError as exc:
                        attempts.append(
                            AttemptRecord(0, "", "PASS", (), None, "", str(exc)[-2000:], (), (), (),
                                          origin="time_machine", time_machine=tm_record)
                        )
                        raise
                    except tree_integrity.HarnessIntegrityError as exc:
                        attempts.append(
                            AttemptRecord(0, "", "PASS", (), None, "", f"run void (INVALID_HARNESS): {exc}"[-2000:], (), (), (),
                                          origin="time_machine", time_machine=tm_record)
                        )
                        raise
                    if tm_result is not None:
                        _log(f"[time-machine] re-execution id={tm_result.sandbox_id} exit_code={tm_result.final.exit_code}")
                        attempts.append(
                            AttemptRecord(
                                0, "", "PASS", (), tm_result.final.exit_code, tm_result.final.stdout[-2000:],
                                tm_result.final.stderr[-2000:], (), (), (), origin="time_machine", time_machine=tm_record,
                                execution=_execution_of(tm_result, True),
                            )
                        )
                        tm_result = _with_build_isolation(tm_result)
                        sandbox_result = tm_result
                        if tm_result.succeeded:
                            verdict = "RUNS_AFTER_REPAIR"
                            state.error_chain.clear_last(0)  # harness-v1.6: the era environment cleared the failure
                        else:
                            state.stage = "classifier"
                            classification = _classify_run(
                                tm_result.final.exit_code,
                                tm_result.final.stderr,
                                tm_result.final.stdout,
                                declared_deps=intake_result.declared_dependencies,
                                repo_modules=_internal_modules(),
                            )
                            taxonomy_code = classification.code
                            _log(f"[classifier] {classification.code}: {classification.evidence}")
                            sandbox_reason = _note_failure(0, classification, tm_result.final.phase, may_defer=deps.max_attempts >= 1, result=tm_result)
                            if sandbox_reason:
                                verdict, indeterminate_reason = "INDETERMINATE", sandbox_reason
                                _log(f"[verdict] INDETERMINATE: {sandbox_reason}")
                else:
                    _log(f"[time-machine] could not lock the era environment: {lock.error[-300:]}")
                    attempts.append(
                        AttemptRecord(0, "", "DECLINED", (), None, "", lock.error[-2000:], origin="time_machine", time_machine=tm_record)
                    )

        # harness-v1.4.0-rc: repair candidates per failure (each runs in its own branch of the environment image; needs a
        # checkpoint-capable runner) and RERUN's runner hooks (CPU shim, exit-site hook; need a runner that takes `runner_extras`).
        hooks_ok = _declares_kwarg(deps.sandbox_runner, "runner_extras")
        branching_ok = deps.repair_enabled and _declares_kwarg(deps.sandbox_runner, "checkpoint")
        candidates_per_round = max(1, int(deps.candidates_per_round or 1)) if branching_ok else 1
        if deps.repair_enabled and int(deps.candidates_per_round or 1) > 1 and not branching_ok:
            _log(f"[repair] {deps.candidates_per_round} candidates per round need a checkpoint-capable sandbox runner; using 1")
        hooks_installed: set[str] = set()

        def _auto_runner_hook(name: str, matched: str) -> SandboxRunResult | None:
            """harness-v1.4.0-rc. Deterministic step (no model): install RERUN's runner hook `name` (runner_hooks) on top of the current
            environment image and re-execute. Recorded as attempt 0 / origin time_machine with `time_machine_action`; it does not use
            up a model attempt. Returns the re-execution's result, or None if the budget stops it."""
            hook = runner_hooks.HOOKS[name]
            hooks_installed.add(name)
            state.runner_extras.append(runner_hooks.install_command(name))
            action = {"rule": hook.rule, "matched_error": matched[:500], "hook": name, "fires_on": hook.fires_on, "phase": "repair"}
            if hook.limit:
                action["limit"] = hook.limit
            _log(f"[time-machine] deterministic step: {hook.rule} (matched: {matched[:200]}); no model call")

            def _record(exit_code, stdout, stderr, execution=None) -> None:
                attempts.append(AttemptRecord(0, "", "PASS", (), exit_code, stdout, stderr, origin="time_machine",
                                              execution=execution, time_machine_action=action))

            try:
                result = _execute(workdir, smoke=True, role=f"time machine: {hook.rule}")
            except CostLimitExceeded as exc:
                _log(f"[time-machine] stopped: daily cost ceiling reached: {exc}")
                _record(None, "", f"stopped before completion: {exc}"[-2000:])
                return None
            except (SandboxTimeoutError, tree_integrity.HarnessIntegrityError) as exc:
                _record(None, "", str(exc)[-2000:])
                raise
            if name == runner_hooks.CPU_SHIM:
                action["paths_fired"] = runner_hooks.shim_paths_fired(result.final.stderr, result.final.stdout)
            if name == runner_hooks.MEMORY_HOOK:
                action["changes"] = runner_hooks.memory_hook_changes(result.final.stderr, result.final.stdout)
                action["env"] = dict(runner_env.MEMORY_ENV)
                action["swap_file"] = "enabled" if runner_env.SWAP_FILE_ENABLED else "not built (the v1.7 probes: swapon refused both a fallocate'd and a dd-written file on virtiofs)"
            _log(f"[time-machine] re-execution id={result.sandbox_id} exit_code={result.final.exit_code}")
            _record(result.final.exit_code, result.final.stdout[-2000:], result.final.stderr[-2000:], _execution_of(result, True))
            return result

        wrapper_tried = False

        def _auto_resource_adapt(matched: str) -> SandboxRunResult | None:
            """harness-v1.7 (R1 d). Deterministic step, NOT semantics-preserving, always labelled: the memory hook is in place and the sandbox still
            killed the process for memory. Every batch-size option of the documented Python entry is set to 1/2 (round 1), then 1/4 (round 2) of its
            value (resource_adapt). The verdict, the ladder and the blocker carry RESOURCE-ADAPTED with the exact arguments."""
            nonlocal plan
            round_no = (state.resource_adapt or {}).get("round", 0) + 1
            adaptation = _adaptation(round_no)
            if adaptation is None:
                return None
            state.resource_adapt = {"round": round_no, "changes": [list(c) for c in adaptation.changes], "label": adaptation.label(),
                                    "command": adaptation.command}
            plan = replace(plan, execute_command=adaptation.command,
                           notes=(*plan.notes, f"resource_adapt round {round_no} (harness-v1.7, R1 d; NOT semantics-preserving): {adaptation.label()}"))
            action = {"rule": "resource_adapt", "matched_error": matched[:500], "phase": "repair", "round": round_no, "label": adaptation.label(),
                      "changes": [{"option": o, "from": a, "to": b} for o, a, b in adaptation.changes], "command": adaptation.command,
                      "semantics": "NOT preserved: a smaller batch changes the optimisation (and any batch-dependent result); labelled RESOURCE-ADAPTED",
                      "fires_on": "RESOURCE_LIMIT after the memory hook, a Python entry with a batch-size option"}
            _log(f"[time-machine] deterministic step: resource_adapt round {round_no} ({adaptation.label()}); NOT semantics-preserving; no model call")

            def _record(exit_code, stdout, stderr, execution=None) -> None:
                attempts.append(AttemptRecord(0, "", "PASS", (), exit_code, stdout, stderr, origin="time_machine",
                                              execution=execution, time_machine_action=action))

            try:
                result = _execute(workdir, smoke=True, role=f"time machine: resource_adapt {round_no}")
            except CostLimitExceeded as exc:
                _log(f"[time-machine] stopped: {exc}")
                _record(None, "", f"stopped before completion: {exc}"[-2000:])
                return None
            except (SandboxTimeoutError, tree_integrity.HarnessIntegrityError) as exc:
                _record(None, "", str(exc)[-2000:])
                raise
            _log(f"[time-machine] re-execution id={result.sandbox_id} exit_code={result.final.exit_code}")
            _record(result.final.exit_code, result.final.stdout[-2000:], result.final.stderr[-2000:], _execution_of(result, True))
            return result

        def _auto_data_prep(evidence: str) -> SandboxRunResult | None:
            """harness-v1.7 (R3). Deterministic step (no model): the failure is DATA_MISSING and the repository's README documents how to prepare the
            data (data_prep.decide: a documented script, else a documented archive). The step runs as a RERUN-owned setup command under the caps
            (runner_hooks.data_prep_command), then the documented command is re-executed. Attempt 0 / origin time_machine, once per run. None when
            the rule does not fire (the decision is logged and kept on the run) or the budget stops it. Never fabricates an input."""
            decision = data_prep.decide(workdir, evidence)
            state.data_prep = {"decision": decision.reason, "readmes": list(decision.readmes)}
            if decision.prep is None:
                _log(f"[time-machine] data_prep: not fired: {decision.reason}")
                return None
            prep = decision.prep
            state.data_prep.update(step=prep.as_dict(), dataset_name=prep.dataset_name)
            state.runner_extras.append(runner_hooks.data_prep_command(prep))
            action = {"rule": runner_hooks.DATA_PREP_RULE, "matched_error": evidence[:500], "phase": "repair",
                      "fires_on": "DATA_MISSING at repair time, when a README documents a data script or an archive URL", **prep.as_dict(),
                      "caps": {"seconds": runner_hooks.DATA_PREP_MAX_SECONDS, "bytes_written": runner_hooks.DATA_PREP_MAX_BYTES}}
            _log(f"[time-machine] deterministic step: data_prep ({prep.kind}: {prep.readme}:{prep.line} `{prep.quote[:160]}`"
                 f"{' in ' + prep.workdir if prep.workdir else ''}); no model call")

            def _record(exit_code, stdout, stderr, execution=None) -> None:
                attempts.append(AttemptRecord(0, "", "PASS", (), exit_code, stdout, stderr, origin="time_machine",
                                              execution=execution, time_machine_action=action))

            try:
                result = _execute(workdir, smoke=True, role="time machine: data_prep")
            except CostLimitExceeded as exc:
                _log(f"[time-machine] stopped: {exc}")
                _record(None, "", f"stopped before completion: {exc}"[-2000:])
                return None
            except (SandboxTimeoutError, tree_integrity.HarnessIntegrityError) as exc:
                _record(None, "", str(exc)[-2000:])
                raise
            done = runner_hooks.parse_data_prep(*(st.stdout for st in result.steps), *(st.stderr for st in result.steps))
            action["result"] = done if done is not None else {"error": "no RERUN_DATA_PREP line in the operation's output (the step may not have run)"}
            if done is not None:
                _log(f"[time-machine] data_prep result: exit {done.get('exit_code')}, {done.get('bytes_written')} bytes written, "
                     f"{done.get('seconds')} s{(', OVER CAP: ' + str(done.get('removed_files')) + ' new file(s) removed, ' + str(done.get('changed_files_not_restored')) + ' changed file(s) not restored') if done.get('over_cap') else ''}"
                     f"{', error: ' + str(done.get('error')) if done.get('error') else ''}")
            _log(f"[time-machine] re-execution id={result.sandbox_id} exit_code={result.final.exit_code}")
            _record(result.final.exit_code, result.final.stdout[-2000:], result.final.stderr[-2000:], _execution_of(result, True))
            return result

        def _auto_output_dir(failed: SandboxRunResult) -> SandboxRunResult | None:
            """harness-v1.9 (D-72). Deterministic step (no model): the failure is OUTPUT_DIR_MISSING (a write whose directory does not exist). RERUN
            creates that directory with one setup command (`mkdir -p -- <dir>`, output_dir.mkdir_command: inside the checkout only) and re-executes the
            documented command. Attempt 0 / origin time_machine, once per run. None when the rule does not fire (the reason is logged and kept in `state`) or the budget
            stops it. It creates a directory, never a file, and never touches an input."""
            miss = output_dir.detect(f"{classifier.denoise(failed.final.stderr)}\n{classifier.denoise(failed.final.stdout)}")  # the text the classifier read
            if miss is None:
                state.output_dir = {"decision": "no write call in the failing frame"}
                return None
            command, where = output_dir.mkdir_command(miss, state.baseline.get("execute_command") or plan.execute_command)
            state.output_dir = {"decision": "fired" if command else where, "path": miss.path, "write_line": miss.write_line}
            if command is None:
                _log(f"[time-machine] output_dir: not fired: {where}")
                return None
            state.output_dir.update(directory=where, command=command)
            state.runner_extras.append(command)
            action = {"rule": output_dir.RULE, "matched_error": miss.error_line, "write_line": miss.write_line, "directory": where, "command": command,
                      "phase": "repair", "fires_on": "OUTPUT_DIR_MISSING at repair time: a write whose directory does not exist"}
            _log(f"[time-machine] deterministic step: output_dir (`{command}`; the failing write: `{miss.write_line[:160]}`); no model call")

            def _record(exit_code, stdout, stderr, execution=None) -> None:
                attempts.append(AttemptRecord(0, "", "PASS", (), exit_code, stdout, stderr, origin="time_machine",
                                              execution=execution, time_machine_action=action))

            try:
                result = _execute(workdir, smoke=True, role="time machine: output_dir")
            except CostLimitExceeded as exc:
                _log(f"[time-machine] stopped: {exc}")
                _record(None, "", f"stopped before completion: {exc}"[-2000:])
                return None
            except (SandboxTimeoutError, tree_integrity.HarnessIntegrityError) as exc:
                _record(None, "", str(exc)[-2000:])
                raise
            _log(f"[time-machine] re-execution id={result.sandbox_id} exit_code={result.final.exit_code}")
            _record(result.final.exit_code, result.final.stdout[-2000:], result.final.stderr[-2000:], _execution_of(result, True))
            return result

        def _auto_apt_archive(matched: str) -> SandboxRunResult | None:
            """harness-v1.7 (R4). Deterministic step (no model): the base image's Debian release has left the mirrors (APT_MIRROR_GONE). From here on
            every apt command is preceded by runner_env.apt_archive_step() (only an end-of-life codename is rewritten), recorded in the build plan's
            notes; then re-execute. Attempt 0 / origin time_machine, once per run. None if the budget stops it."""
            nonlocal plan
            state.apt_archive = True
            plan = replace(plan, notes=(*plan.notes, _apt_archive_note()))
            action = _apt_archive_action(matched, "APT_MIRROR_GONE at repair time")
            _log(f"[time-machine] deterministic step: apt_archive (matched: {matched[:200]}); no model call")

            def _record(exit_code, stdout, stderr, execution=None) -> None:
                attempts.append(AttemptRecord(0, "", "PASS", (), exit_code, stdout, stderr, origin="time_machine",
                                              execution=execution, time_machine_action=action))

            try:
                result = _execute(workdir, smoke=True, role="time machine: apt_archive")
            except CostLimitExceeded as exc:
                _log(f"[time-machine] stopped: {exc}")
                _record(None, "", f"stopped before completion: {exc}"[-2000:])
                return None
            except (SandboxTimeoutError, tree_integrity.HarnessIntegrityError) as exc:
                _record(None, "", str(exc)[-2000:])
                raise
            action["rewrote"] = _archive_rewrote(result)
            _log(f"[time-machine] re-execution id={result.sandbox_id} exit_code={result.final.exit_code}")
            _record(result.final.exit_code, result.final.stdout[-2000:], result.final.stderr[-2000:], _execution_of(result, True))
            return result

        def _auto_exit_wrapper(failed: SandboxRunResult) -> SandboxRunResult | None:
            """harness-v1.4.1-rc (D-35). Deterministic step (no model): the exit-site hook was installed and printed nothing, so the entry
            script now runs through RERUN's wrapper (runpy.run_path inside a try/except SystemExit that prints the traceback and re-raises
            with the same code), which sees the bare `raise SystemExit(n)` the hook cannot. If the wrapper prints nothing either, the
            record says "exit outside Python". Recorded as attempt 0 / origin time_machine; it uses up no model attempt. Returns the
            re-execution's result, or None when the command cannot be wrapped or the budget stops it."""
            action = {"rule": runner_hooks.EXIT_WRAPPER_RULE,
                      "matched_error": f"exit code {failed.final.exit_code} with no error text; the exit-site hook printed nothing",
                      "fires_on": runner_hooks.EXIT_WRAPPER_FIRES_ON, "limit": runner_hooks.EXIT_WRAPPER_LIMIT, "phase": "repair"}

            def _record(exit_code, stdout, stderr, execution=None) -> None:
                attempts.append(AttemptRecord(0, "", "PASS", (), exit_code, stdout, stderr, origin="time_machine",
                                              execution=execution, time_machine_action=action))

            wrapped, why = runner_hooks.wrap_entry_command(plan.execute_command)
            if wrapped is None:
                action.update(applied=False, reason=why)
                _log(f"[time-machine] exit wrapper not applicable: {why}")
                _record(failed.final.exit_code, "", "", None)
                return None
            action["applied"] = True
            state.exit_wrapper = True
            _log("[time-machine] deterministic step: exit wrapper (the exit-site hook printed nothing); no model call")
            try:
                result = _execute(workdir, smoke=True, role="time machine: exit_wrapper")
            except CostLimitExceeded as exc:
                _log(f"[time-machine] stopped: daily cost ceiling reached: {exc}")
                _record(None, "", f"stopped before completion: {exc}"[-2000:])
                return None
            except (SandboxTimeoutError, tree_integrity.HarnessIntegrityError) as exc:
                _record(None, "", str(exc)[-2000:])
                raise
            printed = (runner_hooks.EXIT_WRAPPER_MARKER in f"{result.final.stderr}\n{result.final.stdout}"
                       or classifier.has_actionable_error(result.final.stderr, result.final.stdout))
            unseen = None if printed else output_cut_without_error(result)
            action["result"] = ("the wrapped run exited 0" if result.succeeded else
                                "the wrapper printed the traceback of the raise" if printed else
                                OUTPUT_TRUNCATED_REASON_CODE if unseen else runner_hooks.OUTSIDE_PYTHON)
            if unseen:  # harness-v1.4.3-rc (D-41): the wrapper's traceback prints last, so a cut stream proves nothing about it
                state.resource_stop = (OUTPUT_TRUNCATED_REASON_CODE, unseen)
            elif not printed and not result.succeeded:  # a run that passed has nothing to explain (found by the review: it was sent for evidence)
                _log(f"[time-machine] the wrapper printed nothing either: {runner_hooks.OUTSIDE_PYTHON}")
                # harness-v1.4.2-rc (D-38 / D-40): once more, with the sandbox's own evidence: a kill is RESOURCE_LIMIT, anything else stays "exit outside
                # Python"; either way the entry ends INDETERMINATE and no model attempt is spent on it.
                found = _collect_resource_evidence("exit wrapper with evidence", action["matched_error"])
                if found.get("kill_evidenced"):
                    state.resource_stop = ("RESOURCE_LIMIT", f"RESOURCE_LIMIT: the command exited with code {result.final.exit_code} and printed no error; the "
                                           f"exit hook and the exit wrapper printed nothing and the evidence run shows a kill ({found['limit_quote']}) — the "
                                           "sandbox killed the process; not a verdict on the repository, and no repair attempt was made.")
                    # The chain gets the kill as a link attributed to the sandbox (the silent exit before it was attributed REPO by default).
                    state.error_chain.record(0, classifier.TaxonomyCode.RESOURCE_LIMIT, state.resource_stop[1][:500],
                                             error_chain.attribute(classifier.TaxonomyCode.RESOURCE_LIMIT, found["limit_quote"],
                                                                   declared_deps=intake_result.declared_dependencies,
                                                                   python_claim=intake_result.python_version_hint, base_image=plan.base_image))
                else:
                    seen = found["limit_quote"] or found.get("reason") or "no evidence could be read"
                    state.resource_stop = (runner_hooks.OUTSIDE_PYTHON_REASON_CODE, f"{runner_hooks.OUTSIDE_PYTHON_REASON_CODE}: {runner_hooks.OUTSIDE_PYTHON} — the "
                                           f"command exited with code {result.final.exit_code} and printed no error; the exit-site hook and the exit wrapper printed "
                                           f"nothing and the evidence run shows no kill ({seen}). The exit is not a Python SystemExit and nothing says why; not a "
                                           "verdict on the repository, and no model attempt was spent on it.")
                    # No chain link is added: the chain's last link is the silent exit, attributed REPO by the classifier's default, and the harness has no
                    # attribution for "nothing says why". The reason code EXIT_OUTSIDE_PYTHON on the INDETERMINATE verdict is what says so; the summaries
                    # (compare_batches, run_corpus_v1_batch) read that code and keep the entry out of the repository's column.
            _log(f"[time-machine] re-execution id={result.sandbox_id} exit_code={result.final.exit_code}")
            _record(result.final.exit_code, result.final.stdout[-2000:], result.final.stderr[-2000:], _execution_of(result, True))
            return result

        for attempt_number in range(1, (deps.max_attempts if deps.repair_enabled else 0) + 1):
            if verdict is not None or state.cost_capped:
                break
            try:
                cost_guard.check_attempt_budget(run_id)
            except CostLimitExceeded:
                break

            # Deterministic first, model second. harness-v1.3.5-unvalidated (D-24): a missing C compiler found at repair time is fixed
            # by RERUN (apt build-essential). harness-v1.4.0-rc: a GPU_REQUIRED failure gets the CPU shim, and a non-zero exit with no
            # error text gets the exit-site hook (D-25), each once per run and before any model proposal. Every step is recorded as
            # attempt 0 / origin time_machine with `time_machine_action`, and none uses up a model attempt.
            stop_run = False
            while True:
                unseen = output_cut_without_error(sandbox_result)
                if unseen:  # harness-v1.4.3-rc (D-41): no hook, wrapper, evidence run or model attempt reads a missing error as "no error"
                    verdict, indeterminate_reason = "INDETERMINATE", unseen
                    _log(f"[verdict] INDETERMINATE: {unseen}")
                    stop_run = True
                    break
                if exit_zero_check.stop_of(sandbox_result):  # harness-v1.7.2 (D-46): a later run printed only a usage message and exited 0
                    verdict, indeterminate_reason = "INDETERMINATE", exit_zero_check.stop_reason(exit_zero_check.stop_of(sandbox_result))
                    _log(f"[verdict] INDETERMINATE: {indeterminate_reason}")
                    stop_run = True
                    break
                # harness-v1.7.2 (v1.7.2 re-scan of insta-dl): a blocker no code change can supply (missing arguments, no display, no keyboard)
                # can appear only after earlier steps fixed the environment, so it is checked on every failed run here, not only on the baseline
                late_stop = entry_blockers.stop_of(sandbox_result.final.exit_code, sandbox_result.final.stdout, sandbox_result.final.stderr)
                if late_stop is not None:
                    verdict, indeterminate_reason = "INDETERMINATE", entry_blockers.stop_reason(late_stop)
                    _log(f"[verdict] INDETERMINATE: {indeterminate_reason}")
                    stop_run = True
                    break
                sys_need = system_need(classification, f"{sandbox_result.final.stderr}\n{sandbox_result.final.stdout}")  # harness-v1.8 (T5)
                install_fix = install_repair.fix_for(f"{sandbox_result.final.stderr}\n{sandbox_result.final.stdout}", plan, current_requirements,
                                                     frozenset(install_fixes))  # harness-v1.8 (T3)
                removal_hit = api_removals.match(f"{sandbox_result.final.stderr}\n{sandbox_result.final.stdout}")  # harness-v1.5.1 (F2)
                memory_next = (_memory_rule_next(sandbox_result.final.phase) if classification.code == classifier.TaxonomyCode.RESOURCE_LIMIT
                               else None)
                if memory_next == "hook":
                    state.stage = "time_machine"  # harness-v1.7 (R1 c): the memory hook and the memory environment, before the RESOURCE_LIMIT stop
                    state.memory_hook = True
                    step_result = _auto_runner_hook(runner_hooks.MEMORY_HOOK, classification.evidence or classification.code)
                elif memory_next == "adapt":
                    state.stage = "time_machine"  # harness-v1.7 (R1 d): labelled, not semantics-preserving
                    step_result = _auto_resource_adapt(classification.evidence or classification.code)
                elif classification.code == classifier.TaxonomyCode.APT_MIRROR_GONE and not state.apt_archive:
                    state.stage = "time_machine"  # harness-v1.7 (R4): nothing else can install while the mirrors are gone
                    step_result = _auto_apt_archive(classification.evidence or classification.code)
                elif (classification.code == classifier.TaxonomyCode.OUTPUT_DIR_MISSING and hooks_ok and state.output_dir is None):
                    state.stage = "time_machine"  # harness-v1.9 (D-72): create the missing output directory, before any model call
                    step_result = _auto_output_dir(sandbox_result)
                    if step_result is None and not state.cost_capped:
                        continue  # not fired (the decision is kept, so it cannot come back): the other deterministic steps get their turn
                elif (classification.code == classifier.TaxonomyCode.DATA_MISSING and hooks_ok and state.data_prep is None
                      and not removal_hit):
                    state.stage = "time_machine"  # harness-v1.7 (R3): the repository's documented data step, before any model call
                    step_result = _auto_data_prep(classification.evidence or "")
                    if step_result is None and not state.cost_capped:
                        continue  # not fired (the decision is kept, so it cannot come back): the other deterministic steps get their turn
                elif removal_hit and removal_hit[0].rule not in removals_applied:
                    state.stage = "time_machine"
                    step_result = _auto_api_removal(sandbox_result, *removal_hit)
                    if step_result is None and not state.cost_capped:
                        continue  # not taken (the rule is marked, so it cannot come back): the other deterministic steps still get their turn for this same failure
                elif install_fix is not None:
                    state.stage = "time_machine"  # harness-v1.8 (T3): a renamed Debian package, or the retired git:// protocol
                    step_result = _auto_install_repair(sandbox_result, install_fix)
                elif sys_need and not set(sys_need.packages) <= set(plan.apt_install):
                    state.stage = "time_machine"
                    step_result = _auto_system_packages(sandbox_result, sys_need)
                elif (hooks_ok and classification.code == classifier.TaxonomyCode.GPU_REQUIRED
                      and runner_hooks.CPU_SHIM not in hooks_installed):
                    state.stage = "time_machine"
                    step_result = _auto_runner_hook(runner_hooks.CPU_SHIM, classification.evidence or classification.code)
                elif (hooks_ok and runner_hooks.EXIT_HOOK not in hooks_installed
                      and not classifier.has_actionable_error(sandbox_result.final.stderr, sandbox_result.final.stdout)):
                    state.stage = "time_machine"
                    step_result = _auto_runner_hook(runner_hooks.EXIT_HOOK,
                                                    f"exit code {sandbox_result.final.exit_code} with no error text")
                elif (hooks_ok and runner_hooks.EXIT_HOOK in hooks_installed and not wrapper_tried
                      and not classifier.has_actionable_error(sandbox_result.final.stderr, sandbox_result.final.stdout)
                      and runner_hooks.EXIT_HOOK_MARKER not in f"{sandbox_result.final.stderr}\n{sandbox_result.final.stdout}"):
                    state.stage = "time_machine"
                    wrapper_tried = True
                    step_result = _auto_exit_wrapper(sandbox_result)
                else:
                    break
                if state.cost_capped:
                    stop_run = True
                    break
                if step_result is None and classification.code in (classifier.TaxonomyCode.RESOURCE_LIMIT, classifier.TaxonomyCode.APT_MIRROR_GONE):
                    # harness-v1.7 (v1.7 review, L3): the deferred rule could not run (the daily ceiling stopped it): the stop it deferred applies now
                    reason = _note_failure(0, classification, sandbox_result.final.phase, record=False, may_defer=False)
                    if reason:
                        verdict, indeterminate_reason = "INDETERMINATE", reason
                        _log(f"[verdict] INDETERMINATE: {reason}")
                        stop_run = True
                        break
                if step_result is None:
                    break
                if not step_result.succeeded:
                    step_result = _with_build_isolation(step_result)
                sandbox_result = step_result
                if step_result.succeeded:
                    verdict = "RUNS_AFTER_REPAIR"
                    state.error_chain.clear_last(0)  # harness-v1.6: a deterministic step (attempt 0) cleared the failure
                    stop_run = True
                    break
                if state.resource_stop:
                    stop_code, stop_reason = state.resource_stop
                    verdict, indeterminate_reason = "INDETERMINATE", stop_reason
                    if stop_code == "RESOURCE_LIMIT":
                        taxonomy_code = classifier.TaxonomyCode.RESOURCE_LIMIT
                    _log(f"[verdict] INDETERMINATE: {stop_reason}")
                    stop_run = True
                    break
                state.stage = "classifier"
                classification = _classify_run(
                    step_result.final.exit_code,
                    step_result.final.stderr,
                    step_result.final.stdout,
                    declared_deps=intake_result.declared_dependencies,
                    repo_modules=_internal_modules(),
                )
                taxonomy_code = classification.code
                _log(f"[classifier] {classification.code}: {classification.evidence}")
                sandbox_reason = _note_failure(0, classification, step_result.final.phase, result=step_result)
                if sandbox_reason:
                    verdict, indeterminate_reason = "INDETERMINATE", sandbox_reason
                    _log(f"[verdict] INDETERMINATE: {sandbox_reason}")
                    stop_run = True
                    break
            if stop_run:
                break

            state.stage = "repairer"
            target_file = _target_file_for(
                classification,
                recon_result.entrypoint or _script_in_command(documented_command) or "",
                intake_result.dependency_files,
            )
            target_path = workdir / target_file
            target_content = (read_text_capped(target_path) or "") if target_path.is_file() else ""
            repair_layer = classifier.repair_layer_for(classification.code)
            # The full output of the step that failed: the env gate checks
            # every env change's `evidence` against it verbatim.
            failure_log = f"{sandbox_result.final.stderr}\n{sandbox_result.final.stdout}"
            # harness-v1.3.4 (D-19): a non-zero exit with no error text is a SILENT failure: the repairer gets head+tail of both
            # streams and the exit code, and a code patch that does more than add diagnostics is refused by the gate.
            silent_exit = not classifier.has_actionable_error(sandbox_result.final.stderr, sandbox_result.final.stdout)
            silent_failure = None
            if silent_exit:
                silent_failure = {
                    "exit_code": sandbox_result.final.exit_code,
                    "stdout": classifier.head_and_tail(sandbox_result.final.stdout),
                    "stderr": classifier.head_and_tail(sandbox_result.final.stderr),
                }
                _log(f"[repair {attempt_number}] silent failure: exit {sandbox_result.final.exit_code} with no error text; the repairer is told not to guess")

            state.stage = "tavily"
            if imported_modules is None:
                imported_modules = env_repair.imported_top_level_modules(workdir)
            # harness-v1.3.3: the query carries the repository's framework and Python version next to the error, and what
            # this run already tried (a repeated error must not repeat an identical search).
            search_framework = tavily.detect_framework(imported_modules)
            search_python = tavily.python_minor(plan.base_image)
            search_tried = tuple(
                sorted(f"{key[0]} {key[1] or key[5]}{('==' + key[2]) if key[2] else ''}".strip() for key in failed_moves)
            )
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
                    framework=search_framework,
                    python_version=search_python,
                )
            if resolution is not None:
                missing = re.search(r"No module named ['\"]([\w.]+)['\"]", classification.evidence or "")
                used = import_names.mapping_for(missing.group(1)) if missing else None
                if used is not None:
                    _log(f"[import-map] {used.module} -> {used.distribution} ({used.source}, confidence {used.confidence}) for the resolver")
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
                    tavily_context = tavily.fetch_context(
                        deps.tavily_client, classification.code, classification.evidence,
                        framework=search_framework, python_version=search_python, tried=search_tried,
                    )
                except tavily.TavilyError as exc:
                    _log(f"[tavily] search failed, continuing without cited context: {exc}")
                    tavily_context = tavily.TavilyContext(query="", sources=())
                external_context = tavily_context.as_prompt_context()
                offered_sources = ()
                verified_git = frozenset()
            offered_tavily = tuple(s.as_dict() for s in tavily_context.sources)
            consulted = tuple({"number": n, **t} for n, t in enumerate(offered_tavily, start=1))
            if tavily_context.has_sources:
                _log(f"[tavily] {len(tavily_context.sources)} result(s) for '{tavily_context.query}'")

            def _cite(env_changes_applied, declared: tuple = (), change_text: str = "") -> tuple[tuple, tuple]:
                """Only sources actually used in a decision are cited: a
                verified git source a pip_git change installed (plus the
                Tavily result it was found in), a PyPI release a pin/add
                chose, and (harness-v1.3.3, D-3/Best Use of Tavily) every search result the model DECLARED it used
                (`cited_sources`, 1-based as numbered in its prompt) for the change that was applied. A number outside
                what was offered is ignored and logged. Everything else offered is logged, not cited."""
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
                cited_list = [dict(t, cited_via="git_source") for t in offered_tavily if t["url"] in cited_urls]
                for number in dict.fromkeys(declared):
                    if not 1 <= number <= len(offered_tavily):
                        _log(f"[citations] ignored: the model cited source [{number}] but only {len(offered_tavily)} were offered")
                        continue
                    source = offered_tavily[number - 1]
                    if source["url"] in {c["url"] for c in cited_list}:
                        continue
                    cited_list.append(dict(source, cited_via="model_declared"))
                    _log(f"[citations] cited (model declared it used source [{number}]): {source['url']}")
                # harness-v1.3.4 (D-21): a reference whose snippet contains the text of the applied change is cited as
                # `content_match` even when the model did not declare it (deterministic; labelled as such, never as the model's word).
                signatures = [
                    ln[1:].strip() for ln in (change_text or "").splitlines()
                    if ln.startswith("+") and not ln.startswith("+++") and len(ln[1:].strip()) >= 12
                ] + [f"{c.package}=={c.version}" for c in env_changes_applied if c.op in ("pin", "add") and c.package and c.version]
                for number, source in enumerate(offered_tavily, start=1):
                    if source["url"] in {c["url"] for c in cited_list}:
                        continue
                    hit = next((sig for sig in signatures if sig and sig in (source.get("content") or "")), None)
                    if hit:
                        cited_list.append(dict(source, cited_via="content_match", matched_text=hit[:120]))
                        _log(f"[citations] cited (the applied change's text appears in reference [{number}]): {source['url']}")
                cited_tavily = tuple(cited_list)
                cited_url_set = {c["url"] for c in cited_tavily}
                for t in offered_tavily:
                    if t["url"] not in cited_url_set:
                        _log(f"[citations] not cited (not used in a decision): {t['url']}")
                for r in offered_sources:
                    if r not in cited_resolved:
                        _log(f"[citations] not cited (offered, not used): {r.get('url')}")
                return cited_tavily, cited_resolved

            state.stage = "repairer"
            dependency_view = dict(intake_result.dependency_files)
            if current_requirements is not None and current_requirements != intake_result.dependency_files.get("requirements.txt"):
                # harness-v1.3.4 (D-18): RERUN's lock / edited copy is never shown under the repository file's name (corpus-v2 entry 7:
                # the model tried to file_edit "requirements.txt", which did not exist, and lost two attempts).
                dependency_view["RERUN-managed lock (edit via env_delta only)"] = current_requirements
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
                    resolved_lock=resolved_lock,
                    silent_failure=silent_failure,
                    n_references=len(offered_tavily),
                )

            shadow_cache: dict = {}  # the packages the repository imports, read once per round (the checkout does not change inside a round)
            bmode = behaviour_mode_of(deps)  # harness-v1.10: "off" | "refuse" | "flag"

            def _flag_record(static_flags, trace_record) -> dict | None:
                """harness-v1.10 flag mode: the advisory record of one candidate (None in the other modes, or when there is nothing to record). `flagged` is true when
                the static half or the trace found something; the verdict is not touched (outcome_levels.review_required reads it for the adopted patch)."""
                if bmode != "flag" or (not static_flags and trace_record is None):
                    return None
                record = {"mode": "flag", "static": list(static_flags or ())}
                if trace_record is not None:
                    record["trace"] = trace_record
                record["flagged"] = bool(record["static"] or (trace_record or {}).get("findings"))
                return record

            def _behaviour_static(diff: str, originals: dict, env_changes_) -> list:
                """harness-v1.10 (behaviour.py): the static findings of one gate-approved candidate: what its patch changes (computation, workload, entrypoint, arguments)
                and whether its environment change redirects the command. Pure; the same text the gate analyzed."""
                try:
                    new_sources = patched_sources(diff, originals) if diff else {}
                    candidate_command = plan.execute_command
                    if env_changes_:
                        candidate_command = env_repair.apply_env_delta(plan, env_changes_, current_requirements)[0].execute_command
                    if diff and "roots" not in shadow_cache:
                        shadow_cache["roots"] = behaviour.external_import_roots({q.relative_to(workdir).as_posix(): read_text_capped(q) or ""
                                                                                 for q in behaviour.repo_python_files(workdir)})
                    shadow = shadow_cache.get("roots", frozenset())
                    return behaviour.candidate_findings(originals, {p: new_sources[p] for p in new_sources}, command_before=plan.execute_command, command_after=candidate_command,
                                                        shadow_names=shadow)
                except Exception as exc:  # noqa: BLE001 - a check that cannot judge a patch refuses it by name; it never ends the run
                    return [behaviour.Finding(behaviour.COMPUTATION_CHANGED, f"the behavioural check failed on this patch and refuses it: {type(exc).__name__}: {str(exc)[:160]}")]

            def _candidate(cand_no: int | None, base_followup: str | None, first: bool, summaries: list) -> dict | None:
                """One repair candidate for this failure: the model's proposal, its re-asks (same attempt), the env gate, the patch
                pipeline, the tamper gate and (harness-v1.4.0-rc) py_compile. Records the attempt itself when the candidate is
                declined or rejected (returns None); returns the gate-approved candidate otherwise. `cand_no` is None when there is
                one candidate per round (harness-v1.3.x records are unchanged)."""

                def _append(record: AttemptRecord) -> None:
                    attempts.append(replace(record, candidate=cand_no) if cand_no is not None else record)

                def _ask(extra: str | None = None):
                    return _propose("\n\n".join(x for x in (base_followup, extra) if x) or None)

                proposal = _ask()
                if first:
                    cost_guard.record_attempt(run_id)
                label = f"{attempt_number}" if cand_no is None else f"{attempt_number}.{cand_no}"
                if proposal.parse_retried:
                    _log(f"[repair {label}] first reply was not valid JSON; re-asked once (same attempt)")

                if not proposal.has_change:
                    _log(f"[repair {label}] declined: {proposal.explanation}")
                    _cite(())
                    _append(AttemptRecord(attempt_number, "", "DECLINED", (), None, "", "", consulted=consulted,
                                          reason_no_citation=proposal.reason_no_citation, silent_exit=silent_exit))
                    return None

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
                            current_command=plan.execute_command,
                            # The era lock as currently installed (incl. earlier
                            # env deltas); None when the time machine resolved none.
                            locked_requirements=(
                                tuple((current_requirements or "").splitlines()) if resolved_lock is not None else None
                            ),
                            repo_internal_modules=_internal_modules(),
                            apt_packages=frozenset(p.lower() for p in plan.apt_install),
                        )
                    return changes, violations

                env_changes, env_violations = _env_check(proposal)
                if env_violations and all(v.rule == env_repair.EnvRule.ENV_UNJUSTIFIED for v in env_violations):
                    # Found live (TTPT v3): the model dropped the required
                    # justification/evidence and a whole attempt was lost. One
                    # re-ask inside the same attempt, like the JSON re-ask.
                    _log(f"[repair {label}] env change lacked justification/evidence; re-asked once (same attempt)")
                    proposal = _ask(
                        "Your previous reply was rejected: "
                        + "; ".join(v.reason for v in env_violations)
                        + ". Every env change needs a one-line \"justification\" and an \"evidence\" string copied "
                        "VERBATIM from the failing run's log shown above. Reply again with the complete JSON object."
                    )
                    if proposal.has_change:
                        env_changes, env_violations = _env_check(proposal)
                    else:
                        _log(f"[repair {label}] declined after re-ask: {proposal.explanation}")
                        _cite(())
                        _append(AttemptRecord(attempt_number, "", "DECLINED", (), None, "", "", consulted=consulted,
                                              reason_no_citation=proposal.reason_no_citation, silent_exit=silent_exit))
                        return None

                def _repeats(changes):
                    return [c for c in changes if move_barred(env_repair.change_key(c), failed_moves, untested_moves)]

                repeated = _repeats(env_changes)
                if repeated:
                    described = ", ".join(f"{c.op} {c.package or c.command or c.version}" for c in repeated)
                    _log(f"[repair {label}] proposal repeats change(s) already tried and failed this run ({described}); re-asked once (same attempt)")
                    untested_twice = [c for c in repeated if env_repair.change_key(c) not in failed_moves]  # harness-v1.8 (T1, review finding 7)
                    proposal = _ask(
                        "Your previous reply was rejected: it repeats environment change(s) this run already applied "
                        f"and then saw fail ({described}). They are already in effect, so repeating them cannot help. "
                        + (f"({', '.join(f'{c.op} {c.package}' for c in untested_twice)}: tried twice on branches where the run died before reaching the error it was for; "
                           "a third try is not offered.) " if untested_twice else "")
                        + "Propose a DIFFERENT fix, or decline. Reply again with the complete JSON object."
                    )
                    if not proposal.has_change:
                        _log(f"[repair {label}] declined after re-ask: {proposal.explanation}")
                        _cite(())
                        _append(AttemptRecord(attempt_number, "", "DECLINED", (), None, "", "", consulted=consulted,
                                              reason_no_citation=proposal.reason_no_citation, silent_exit=silent_exit))
                        return None
                    env_changes, env_violations = _env_check(proposal)
                    repeated = _repeats(env_changes)
                    if repeated:
                        # Repeated again: the attempt (already counted) is used up.
                        env_violations = tuple(env_violations) + tuple(
                            env_repair.Violation(
                                rule=env_repair.EnvRule.ENV_REPEATS_FAILED_CHANGE,
                                reason=f"repeats '{c.op} {c.package or c.command or c.version}', already tried and failed this run",
                            )
                            for c in repeated
                        )
                env_delta_dicts = tuple(c.as_dict() for c in env_changes)

                # --- Tamper gate on the code diff (every touched file) ------------
                checked_diff = ""
                code_violations: tuple = ()
                patch_notes: tuple[str, ...] = ()
                model_patch = ""
                indentation_normalised: list[dict] | None = None  # harness-v1.7.2 (D-47)

                def _resolve_code(prop) -> "patch_pipeline.PatchResolution":
                    return patch_pipeline.resolve_patch(
                        workdir,
                        diff_text=prop.diff_text,
                        file_edits=list(prop.file_edits) or None,
                        file_replacements=list(prop.file_replacements) or None,
                    )

                def _raw_patch(prop) -> str:
                    if prop.diff_text:
                        return prop.diff_text
                    raw = json.dumps({"file_edits": list(prop.file_edits), "file_replacements": list(prop.file_replacements)})
                    if len(raw) <= RAW_PATCH_MAX_CHARS:
                        return raw
                    # harness-v1.8 (T19, TEST #6 rocgan): until v1.7.2 this was `raw[:6000]`, a JSON string cut in the middle, which no replay can parse.
                    # A patch too large to store is recorded as valid JSON that says so, with the size, the hash and the first 6,000 characters.
                    return json.dumps({"truncated": True, "chars": len(raw), "sha256": hashlib.sha256(raw.encode("utf-8")).hexdigest(), "head": raw[:6000]})

                candidate_diff: str | None = None
                if proposal.has_code:
                    # harness-v1.3.3 (D-1/D-2): the model's intent is rebuilt into a canonical diff that passes `git apply --check`
                    # BEFORE the tamper gate; the gate then sees exactly what will be applied. One re-ask shows the model the error.
                    state.stage = "patch_pipeline"
                    try:
                        resolution_ = _resolve_code(proposal)
                    except patch_pipeline.PatchProblem as exc:
                        _log(f"[repair {label}] code change is not applicable: {str(exc).splitlines()[0][:200]}; re-asked once (same attempt)")
                        first_raw = _raw_patch(proposal)
                        proposal = _ask(
                            "Your previous code change could not be applied: " + str(exc) + "\nReply again with the complete JSON "
                            "object. Prefer file_edits (copy `old` exactly from the file shown above), or decline."
                        )
                        resolution_ = None
                        if not proposal.has_change:
                            _log(f"[repair {label}] declined after re-ask: {proposal.explanation}")
                            _cite(())
                            _append(AttemptRecord(attempt_number, "", "DECLINED", (), None, "", "", model_patch=first_raw,
                                                  consulted=consulted, reason_no_citation=proposal.reason_no_citation, silent_exit=silent_exit))
                            return None
                        env_changes, env_violations = _env_check(proposal)
                        env_delta_dicts = tuple(c.as_dict() for c in env_changes)
                        if proposal.has_code:
                            try:
                                resolution_ = _resolve_code(proposal)
                            except patch_pipeline.PatchProblem as exc2:
                                code_violations = (
                                    env_repair.Violation(rule=GateRule.UNAPPLICABLE_PATCH, reason=str(exc2)[:600]),
                                )
                                checked_diff = _raw_patch(proposal)[:4000]
                    if resolution_ is not None:
                        candidate_diff = resolution_.diff
                        patch_notes = resolution_.notes
                        model_patch = _raw_patch(proposal) if resolution_.diff != (proposal.diff_text or "") else ""
                        for note in patch_notes:
                            _log(f"[patch] {note}")
                if candidate_diff:
                    state.stage = "tamper_gate"
                    # The gate must see the original of EVERY file the diff touches,
                    # not just the file the repairer was shown (the hole found live on
                    # 2026-09-24). Paths come from the same normalizer the gate uses.
                    touched_originals = _load_touched_originals(workdir, prepare_patch(candidate_diff).paths)
                    # harness-v1.7.2 (D-47): a patch whose added lines use another indentation than the file (spaces in a tab-indented file) and
                    # fails to parse ONLY for that is re-indented to the file's convention, parsed once more, and checked by the gate as normalised.
                    normalised = indentation.normalise_patch(candidate_diff, touched_originals)
                    if normalised is not None and patch_pipeline.git_apply_check(workdir, normalised[0]) is None:
                        if not model_patch:
                            model_patch = _raw_patch(proposal)
                        candidate_diff, indentation_normalised = normalised
                        for found in indentation_normalised:
                            note = (f"{found['file']}: indentation normalised from {found['from']} to {found['to']} ({found['lines']} added line(s); "
                                    f"the patch as written failed to parse: {found['parse_error']}) (harness-v1.7.2, D-47)")
                            patch_notes = (*patch_notes, note)
                            _log(f"[patch] {note}")
                    touched_sources = "\n".join(touched_originals.values())
                    # Recon's names come from a model that reads untrusted repo text;
                    # the AST-derived floor keeps rules 1-2 armed even if recon was
                    # prompt-injected into returning none.
                    gate_result = check_patch(
                        candidate_diff,
                        touched_originals,
                        eval_call_names=frozenset(recon_result.eval_call_names) | heuristic_eval_call_names(touched_sources),
                        model_call_names=frozenset(recon_result.model_call_names) | heuristic_model_call_names(touched_sources),
                        repo_root=workdir,
                        # harness-v1.9 (D-55): the documented command's own script is the program, not a test, even when it is named test_*.py
                        documented_files=documented_scripts(state.baseline.get("execute_command") or plan.execute_command),
                    )
                    # From here on, the diff that is recorded and applied is exactly
                    # the canonical one the gate analyzed.
                    checked_diff = gate_result.canonical_diff or candidate_diff
                    code_violations = gate_result.violations
                    if silent_exit and not code_violations:
                        blind = diagnostics_only_violation(checked_diff)
                        if blind is not None:
                            code_violations = (blind,)
                    if not code_violations:
                        # harness-v1.4.0-rc: every candidate is py_compile-checked after the patch.
                        code_violations = py_compile_violations(checked_diff, touched_originals)

                behaviour_static: list = []
                behaviour_flags: list = []
                if bmode != "off" and not env_violations and not code_violations and (candidate_diff or env_changes):
                    # harness-v1.10: the behavioural checks, static half. Refuse mode: a finding is recorded as a violation whose rule is the reason's name
                    # (behaviour.STATIC_REASONS). Flag mode: nothing is refused; the findings travel with the candidate and are recorded on its attempt.
                    found_static = _behaviour_static(checked_diff if candidate_diff else "", touched_originals if candidate_diff else {}, env_changes)
                    if bmode == "refuse":
                        behaviour_static = found_static
                        code_violations = behaviour.violations_of(behaviour_static)
                    elif found_static:
                        behaviour_flags = [f.as_dict() for f in found_static]
                        _log(f"[repair {label}] behaviour check FLAGGED before the run (advisory, nothing refused): "
                             + "; ".join(f"{f.reason} ({f.detail[:140]})" for f in found_static))
                summary = (proposal.explanation or "").strip()
                if env_delta_dicts:
                    summary += " | env: " + "; ".join(f"{d.get('op')} {d.get('package') or d.get('version') or ''}".strip() for d in env_delta_dicts)
                if checked_diff:
                    changed = [ln for ln in checked_diff.splitlines() if ln[:1] in "+-" and not ln.startswith(("+++", "---"))]
                    summary += " | diff: " + " / ".join(changed[:6])
                summaries.append(summary)

                all_violations = tuple(env_violations) + tuple(code_violations)
                if all_violations:
                    reasons = "; ".join(v.reason for v in all_violations)
                    _log(f"[repair {label}] " + ("behaviour check REFUSED before the run" if behaviour_static else "tamper gate REJECT") + f": {reasons}")
                    _cite(())
                    _append(
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
                            patch_notes=patch_notes, indentation_normalised=indentation_normalised,
                            model_patch=model_patch,
                            consulted=consulted,
                            reason_no_citation=proposal.reason_no_citation,
                            silent_exit=silent_exit,
                            behaviour={"static": [f.as_dict() for f in behaviour_static], "refused": True} if behaviour_static else None,
                        )
                    )
                    return None
                return {"number": cand_no, "label": label, "proposal": proposal, "env_changes": env_changes,
                        "env_delta_dicts": env_delta_dicts, "checked_diff": checked_diff, "patch_notes": patch_notes, "indentation_normalised": indentation_normalised,
                        "model_patch": model_patch, "behaviour_flags": behaviour_flags}

            summaries: list[str] = []
            gated: list[dict] = []
            for cand_k in range(1, candidates_per_round + 1):
                if state.cost_capped:
                    break
                one = _candidate(
                    cand_k if candidates_per_round > 1 else None,
                    repairer.candidate_followup(summaries, cand_k) if cand_k > 1 else None,
                    first=cand_k == 1,
                    summaries=summaries,
                )
                if one is not None:
                    gated.append(one)

            if candidates_per_round == 1:
                # One candidate per round: the harness-v1.3.x flow (the gate-approved change is applied to the checkout and kept).
                if not gated:
                    continue
                chosen_one = gated[0]
                proposal = chosen_one["proposal"]
                env_changes = chosen_one["env_changes"]
                env_delta_dicts = chosen_one["env_delta_dicts"]
                checked_diff = chosen_one["checked_diff"]
                patch_notes = chosen_one["patch_notes"]; chosen_indentation = chosen_one.get("indentation_normalised")
                model_patch = chosen_one["model_patch"]
                layers = " + ".join(x for x, present in (("env", bool(env_changes)), ("code", bool(checked_diff))) if present)
                _log(f"[repair {attempt_number}] tamper gate PASS ({layers}) — applying and re-executing")
                if checked_diff:
                    state.stage = "apply_diff"
                    try:
                        deps.apply_diff(workdir, checked_diff)
                        state.patched_paths.update(prepare_patch(checked_diff).paths)
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
                            AttemptRecord(attempt_number, checked_diff, "PASS", (), None, "", str(exc)[-2000:], (), env_delta_dicts,
                                          patch_notes=patch_notes, indentation_normalised=chosen_indentation, model_patch=model_patch, consulted=consulted,
                                          reason_no_citation=proposal.reason_no_citation, silent_exit=silent_exit)
                        )
                        continue
                plan_kept, requirements_kept, layers_kept = plan, current_requirements, len(state.apt_layers)  # harness-v1.7.2: for a put-back
                if env_changes:
                    state.stage = "apply_env"
                    plan_before = plan
                    plan, new_requirements = env_repair.apply_env_delta(plan, env_changes, current_requirements)
                    if new_requirements is not None:
                        current_requirements = new_requirements
                    _layer = _apt_layer_for(plan_before, plan)
                    if _layer is not None:
                        state.apt_layers.append(_layer)
                    _log(f"[repair {attempt_number}] env delta applied; build plan now: {plan.as_dict()}")
                cited_tavily, cited_resolved = _cite(env_changes, proposal.cited_sources, checked_diff)
                state.build_plan_dict = plan.as_dict()
                try:
                    rerun_result = _execute(workdir, smoke=True, role=f"repair {attempt_number}")
                except CostLimitExceeded as exc:
                    _log(f"[repair {attempt_number}] stopped: daily cost ceiling reached: {exc}")
                    attempts.append(
                        AttemptRecord(attempt_number, checked_diff, "PASS", (), None, "", "", cited_tavily, env_delta_dicts, cited_resolved)
                    )
                    break
                except SandboxTimeoutError as exc:
                    attempts.append(
                        AttemptRecord(attempt_number, checked_diff, "PASS", (), None, "", str(exc)[-2000:], cited_tavily,
                                      env_delta_dicts, cited_resolved, consulted=consulted, reason_no_citation=proposal.reason_no_citation,
                                      silent_exit=silent_exit)
                    )
                    raise
                except tree_integrity.HarnessIntegrityError as exc:
                    # harness-v1.3.4 (D-22): the run is void, but the attempt (patch, gate verdict, what the sandbox said) is recorded first.
                    attempts.append(
                        AttemptRecord(attempt_number, checked_diff, "PASS", (), None, "",
                                      f"run void (INVALID_HARNESS): {exc}; sandbox: {str(exc.record.get('sandbox_stderr', ''))[-800:]}"[-2000:],
                                      cited_tavily, env_delta_dicts, cited_resolved, patch_notes=patch_notes, indentation_normalised=chosen_indentation, model_patch=model_patch,
                                      consulted=consulted, reason_no_citation=proposal.reason_no_citation, silent_exit=silent_exit)
                    )
                    raise
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
                        execution=_execution_of(rerun_result, True),
                        patch_notes=patch_notes, indentation_normalised=chosen_indentation,
                        model_patch=model_patch,
                        consulted=consulted,
                        reason_no_citation=proposal.reason_no_citation,
                        silent_exit=silent_exit,
                        behaviour=_flag_record(chosen_one.get("behaviour_flags"), None),
                    )
                )
                if not rerun_result.succeeded:
                    failed_moves.update(env_repair.change_key(c) for c in env_changes)
                    rerun_result = _with_build_isolation(rerun_result)
                    # harness-v1.7.2 (v1.7.2 re-scan of insta-dl): a change whose own added package is what the new error names made that error;
                    # it is put back, and the run keeps the failure it had (the same rule the multi-candidate flow applies when it qualifies).
                    rerun_cls = _classify_run(rerun_result.final.exit_code, rerun_result.final.stderr, rerun_result.final.stdout,
                                              declared_deps=intake_result.declared_dependencies, repo_modules=_internal_modules())
                    own = _self_inflicted(rerun_cls, env_delta_dicts, intake_result.declared_dependencies)
                    if own and env_changes and not checked_diff:
                        plan, current_requirements = plan_kept, requirements_kept
                        del state.apt_layers[layers_kept:]
                        state.build_plan_dict = plan.as_dict()
                        _log(f"[repair {attempt_number}] change put back: its new error names {own!r}, which the change added and the repository "
                             "does not declare; the run keeps its previous failure")
                        rerun_result = sandbox_result
            else:
                # harness-v1.4.0-rc: every gate-approved candidate runs at the same time, each in its own branch of the environment image
                # (nothing is applied to the checkout yet). The candidates that changed the exit outcome go to the adjudicator (Ultra);
                # the chosen one is applied to the checkout and its image becomes the environment image; the others are released.
                trace_reports: dict[int, list] = {}

                def _trace_plan(cand_plan, files: dict):
                    """harness-v1.10 (behaviour.py): what the tracer is told for one candidate: the entry of the command it will run, the failure site being repaired (mapped
                    into the patched file), the lines the patch added and the entry's __main__ body."""
                    repo_files = {q.relative_to(workdir).as_posix() for q in behaviour.repo_python_files(workdir)}
                    new_sources = {p: (data.decode("utf-8", "replace") if data is not None else None) for p, data in files.items()}
                    old_sources = _load_touched_originals(workdir, tuple(files))
                    entry = behaviour.entry_of(cand_plan.execute_command, repo_files)
                    entry_source = read_text_capped(workdir / entry) if entry else None
                    failing = sandbox_result.final
                    failure_text = failing.stderr if behaviour.has_frames(failing.stderr) else f"{failing.stderr}\n{failing.stdout}"
                    return behaviour.plan_trace(command=cand_plan.execute_command, failure_text=failure_text, old_sources=old_sources, new_sources=new_sources,
                                                repo_files=repo_files, entry_source=entry_source, read_source=lambda rel: read_text_capped(workdir / rel))

                runnable: list[dict] = []
                for cand in gated:
                    files: dict = {}
                    if cand["checked_diff"]:
                        try:
                            files = _candidate_files(workdir, state.patched_paths, cand["checked_diff"])
                        except OrchestratorError as exc:
                            _log(f"[repair {cand['label']}] gate-approved patch failed to apply cleanly: {exc}")
                            _cite(())
                            attempts.append(
                                AttemptRecord(attempt_number, cand["checked_diff"], "PASS", (), None, "", str(exc)[-2000:], (),
                                              cand["env_delta_dicts"], patch_notes=cand["patch_notes"], indentation_normalised=cand.get("indentation_normalised"), model_patch=cand["model_patch"],
                                              consulted=consulted, reason_no_citation=cand["proposal"].reason_no_citation,
                                              silent_exit=silent_exit, candidate=cand["number"])
                            )
                            continue
                    cand_plan, cand_requirements, cand_layers = plan, current_requirements, ()
                    if cand["env_changes"]:
                        cand_plan, new_requirements = env_repair.apply_env_delta(plan, cand["env_changes"], current_requirements)
                        if new_requirements is not None:
                            cand_requirements = new_requirements
                        _cand_layer = _apt_layer_for(plan, cand_plan)  # harness-v1.4.1-rc (D-34): apt packages go in as an additive layer
                        cand_layers = (_cand_layer,) if _cand_layer is not None else ()
                    # harness-v1.4.1-rc (D-33): what the deterministic rules add to THIS candidate's branch (they act on every candidate's
                    # failure): apt layers, runner hooks, the exit wrapper, and the actions taken (recorded on the candidate's attempt).
                    trace_plan = None
                    try:
                        trace_plan = _trace_plan(cand_plan, files) if bmode != "off" else None
                    except Exception as exc:  # noqa: BLE001 - the trace is evidence; failing to plan it never stops the candidate
                        _log(f"[repair {cand['label']}] behaviour trace not planned: {type(exc).__name__}: {str(exc)[:200]}")
                    runnable.append({**cand, "files": files, "plan": cand_plan, "requirements": cand_requirements,
                                     "apt_layers": cand_layers, "extras": (), "wrapper": False, "wrapper_tried": False, "actions": [],
                                     "trace_plan": trace_plan,
                                     "trace_extras": (behaviour.install_command(trace_plan.spec_b64),) if trace_plan is not None else (),
                                     "trace_env": dict(behaviour.TRACE_ENV) if trace_plan is not None else None})
                if not runnable:
                    continue
                # Run them at the same time only when each one's share of what is left still funds the smoke run plus start-up and the
                # overlay; otherwise one after another, each funded from what is left when it starts (a candidate must never be killed
                # because its siblings ran beside it).
                needed_seconds = (deps.smoke_seconds or 0) + CANDIDATE_START_MARGIN_S
                concurrent = len(runnable)
                if concurrent > 1 and cost_guard.operation_seconds_budget(share=concurrent) < needed_seconds:
                    concurrent = 1
                _log(f"[repair {attempt_number}] tamper gate PASS for candidate(s) {[c['number'] for c in runnable]}; running them "
                     + ("concurrently" if concurrent > 1 else "one after another (the budget left cannot fund "
                        f"{len(runnable)} concurrent branches of {needed_seconds:.0f}s each)")
                     + ", each in its own branch of the environment image")

                def _candidate_run(cand: dict, role: str):
                    result = _execute(workdir, smoke=True, plan_used=cand["plan"], extra_files=cand["files"], keep_result=True,
                                      share=concurrent, role=role, candidate=cand["number"], extra_apt_layers=tuple(cand["apt_layers"]),
                                      extra_extras=(*cand["extras"], *cand["trace_extras"]), exec_wrapper=True if cand["wrapper"] else None,
                                      apt_archive=bool(cand.get("apt_archive")), trace_env=cand["trace_env"])
                    if cand["trace_plan"] is not None:
                        # the tracer's line is RERUN's, not the repository's: out of the stderr the classifier and the adjudicator read, into the candidate's record
                        clean, reports = behaviour.split_report(result.final.stderr, cand["trace_plan"].nonce)
                        trace_reports[cand["number"]] = reports
                        if clean != result.final.stderr:
                            result = replace(result, steps=(*result.steps[:-1], replace(result.final, stderr=clean)))
                    return result

                def _observe_candidate(cand: dict, result: SandboxRunResult):
                    """harness-v1.4.1-rc (D-33). The deterministic rules (D-24 build-essential, the CPU shim, the exit-site hook, the exit
                    wrapper) observe EVERY candidate's failure, not only the adopted one: before, a rule keyed on a failure that a candidate
                    produced but the adjudicator did not adopt never fired (corpus-v2 #7, harness-v1.4.0 round 2: a candidate's run reached
                    `unable to execute 'gcc'`, D-24 never saw it). A rule that matches fires on THIS candidate's branch (an additive layer
                    or a runner hook on its image, then its command again); the action is recorded as `time_machine_action` on the
                    candidate's attempt, and the candidate's outcome is the run after the rules."""
                    label = f"repair {attempt_number} candidate {cand['number']}"
                    for _ in range(4):
                        if result.succeeded or exit_zero_check.stop_of(result):  # harness-v1.7.2 (D-46): a usage / "missing" exit 0 is not a silent exit
                            break
                        cls = _classify_run(result.final.exit_code, result.final.stderr, result.final.stdout,
                                                  declared_deps=intake_result.declared_dependencies, repo_modules=_internal_modules())
                        output = f"{result.final.stderr}\n{result.final.stdout}"
                        installed = hooks_installed | {runner_hooks.hook_of_command(c) for c in cand["extras"]}
                        silent = (not classifier.has_actionable_error(result.final.stderr, result.final.stdout)
                                  and cls.code != classifier.TaxonomyCode.RESOURCE_LIMIT  # a SIGKILL is not a silent exit (D-38)
                                  and not getattr(result.final, "truncated", False))  # nor is a stream the API cut (D-41)
                        sys_need = system_need(cls, output)  # harness-v1.8 (T5): header and tool needs as well as the compiler
                        action: dict | None = None
                        if (cls.code == classifier.TaxonomyCode.APT_MIRROR_GONE and not state.apt_archive
                                and not cand.get("apt_archive")):
                            # harness-v1.7.2 (D-48): R4 fired only in the main loop, so a candidate's own `apt install` on an end-of-life
                            # Debian image met the 404 mirror and the candidate was judged on RERUN's missing rewrite (live scan v1.7.2b,
                            # insta-dl: `apt python3-tk`, the right idea, failed that way). The same step now runs on this candidate's branch.
                            cand = {**cand, "apt_archive": True}
                            action = {**_apt_archive_action(cls.evidence or cls.code, "APT_MIRROR_GONE on a repair candidate's branch"),
                                      "on_candidate": cand["number"]}
                        elif sys_need and not set(sys_need.packages) <= set(cand["plan"].apt_install):
                            compiler_case = sys_need.rule == BUILD_ESSENTIAL_RULE
                            what = "build-essential" if compiler_case else " ".join(sys_need.packages)
                            changes = tuple(
                                env_repair.EnvChange(
                                    op="apt", package=pkg, evidence=sys_need.evidence,
                                    justification=("deterministic: the failing run could not execute a C compiler" if compiler_case else
                                                   f"deterministic: the failing run could not find {sys_need.item} ({sys_need.kind}); "
                                                   f"apt package {pkg} provides it"))
                                for pkg in sys_need.packages if pkg not in cand["plan"].apt_install
                            )
                            violations = env_repair.check_env_delta(
                                changes, log_text=output, imported_modules=frozenset(),
                                has_requirements_txt=cand["requirements"] is not None,
                                locked_requirements=(tuple(cand["requirements"].splitlines())
                                                     if resolved_lock is not None and cand["requirements"] else None),
                                apt_packages=frozenset(cand["plan"].apt_install))
                            if violations:
                                _log(f"[time-machine] {label}: {what} step refused by the env gate: "
                                     f"{'; '.join(v.reason for v in violations)}")
                                break
                            plan_after, requirements_after = env_repair.apply_env_delta(cand["plan"], changes, cand["requirements"])
                            layer = _apt_layer_for(cand["plan"], plan_after, existing=tuple(cand["apt_layers"]),
                                                   extra_extras=tuple(cand["extras"]))
                            cand = {**cand, "plan": plan_after, "requirements": requirements_after,
                                    "apt_layers": (*cand["apt_layers"], *((layer,) if layer is not None else ()))}
                            action = {"rule": sys_need.rule, "matched_error": sys_need.evidence, "apt_added": [c.package for c in changes],
                                      "phase": "repair", "on_candidate": cand["number"]}
                            if not compiler_case:
                                action["needed"] = {"kind": sys_need.kind, "item": sys_need.item}
                            if layer is not None:
                                action["apt_layer"] = {"layering": "additive", "on_kept_image": layer["after_image"],
                                                       "setup_commands_kept": layer["after_ops"]}
                        elif hooks_ok and cls.code == classifier.TaxonomyCode.GPU_REQUIRED and runner_hooks.CPU_SHIM not in installed:
                            hook = runner_hooks.HOOKS[runner_hooks.CPU_SHIM]
                            cand = {**cand, "extras": (*cand["extras"], runner_hooks.install_command(runner_hooks.CPU_SHIM))}
                            action = {"rule": hook.rule, "matched_error": (cls.evidence or cls.code)[:500], "hook": hook.name,
                                      "fires_on": hook.fires_on, "phase": "repair", "on_candidate": cand["number"]}
                        elif hooks_ok and runner_hooks.EXIT_HOOK not in installed and silent:
                            hook = runner_hooks.HOOKS[runner_hooks.EXIT_HOOK]
                            cand = {**cand, "extras": (*cand["extras"], runner_hooks.install_command(runner_hooks.EXIT_HOOK))}
                            action = {"rule": hook.rule, "matched_error": f"exit code {result.final.exit_code} with no error text",
                                      "hook": hook.name, "fires_on": hook.fires_on, "limit": hook.limit, "phase": "repair",
                                      "on_candidate": cand["number"]}
                        elif (hooks_ok and runner_hooks.EXIT_HOOK in installed and silent and not cand["wrapper_tried"]
                              and not (state.exit_wrapper or cand["wrapper"]) and runner_hooks.EXIT_HOOK_MARKER not in output):
                            wrapped, why = runner_hooks.wrap_entry_command(cand["plan"].execute_command)
                            action = {"rule": runner_hooks.EXIT_WRAPPER_RULE, "applied": wrapped is not None, "phase": "repair",
                                      "matched_error": f"exit code {result.final.exit_code} with no error text; the exit-site hook printed nothing",
                                      "fires_on": runner_hooks.EXIT_WRAPPER_FIRES_ON, "limit": runner_hooks.EXIT_WRAPPER_LIMIT,
                                      "on_candidate": cand["number"]}
                            cand = {**cand, "wrapper_tried": True, "wrapper": wrapped is not None}
                            if wrapped is None:
                                action["reason"] = why
                                cand["actions"] = [*cand["actions"], action]
                                _log(f"[time-machine] {label}: exit wrapper not applicable: {why}")
                                break
                        if action is None:
                            break
                        _log(f"[time-machine] {label}: deterministic step {action['rule']} (matched: {action['matched_error'][:160]}); "
                             "no model call")
                        try:
                            again = _candidate_run(cand, f"{label}: {action['rule']}")
                        except CostLimitExceeded as exc:
                            action["stopped"] = f"stopped before completion: {str(exc)[:300]}"
                            cand = {**cand, "actions": [*cand["actions"], action]}
                            break
                        if action["rule"] == runner_hooks.HOOKS[runner_hooks.CPU_SHIM].rule:
                            action["paths_fired"] = runner_hooks.shim_paths_fired(again.final.stderr, again.final.stdout)
                        if action["rule"] == APT_ARCHIVE_RULE:
                            action["rewrote"] = _archive_rewrote(again)
                        if action["rule"] == runner_hooks.EXIT_WRAPPER_RULE:
                            printed = (runner_hooks.EXIT_WRAPPER_MARKER in f"{again.final.stderr}\n{again.final.stdout}"
                                       or classifier.has_actionable_error(again.final.stderr, again.final.stdout))
                            action["result"] = ("the wrapper printed the traceback of the raise" if printed
                                                else OUTPUT_TRUNCATED_REASON_CODE if output_cut_without_error(again)
                                                else runner_hooks.OUTSIDE_PYTHON)
                        cand = {**cand, "actions": [*cand["actions"], action]}
                        result = again
                    return result, cand

                def _run_candidate(cand: dict):
                    try:
                        result = _candidate_run(cand, f"repair {attempt_number} candidate {cand['number']}")
                        result, cand = _observe_candidate(cand, result)
                        return cand, result, None
                    except Exception as exc:  # noqa: BLE001 - every candidate's outcome is recorded before anything is raised
                        return cand, None, exc

                with ThreadPoolExecutor(max_workers=concurrent) as pool:
                    outcomes = list(pool.map(_run_candidate, runnable))
                if (concurrent > 1 and state.cost_capped
                        and cost_guard.operation_seconds_budget() >= needed_seconds):
                    # A candidate stopped at its SHARE of the budget; the entry itself can still fund a whole operation.
                    _log(f"[repair {attempt_number}] a candidate stopped at its share of the budget ({state.cost_capped}); "
                         "the entry still has funding, so the run continues")
                    state.cost_capped = ""

                fatal = next((exc for _, _, exc in outcomes if exc is not None and not isinstance(exc, CostLimitExceeded)), None)
                executed: list[dict] = []
                for cand, result, exc in outcomes:
                    entry = {**cand, "result": result, "error": exc, "changed": False, "classification": None}
                    if result is not None:
                        if result.succeeded:
                            entry["changed"] = True
                        else:
                            cand_class = _classify_run(result.final.exit_code, result.final.stderr, result.final.stdout,
                                                             declared_deps=intake_result.declared_dependencies, repo_modules=_internal_modules())
                            entry["classification"] = cand_class
                            entry["changed"] = (cand_class.code, cand_class.evidence) != (classification.code, classification.evidence)
                            own = _self_inflicted(cand_class, entry.get("env_delta_dicts") or (), intake_result.declared_dependencies)
                            if entry["changed"] and own:
                                # harness-v1.7.2 (v1.7.2 re-scan of insta-dl): the candidate's new failure is about a package the candidate itself
                                # added and the repository never declared (`pip install python3-tk`, an apt name): the candidate made that error,
                                # so it is no progress and must not be adopted (it had ended the run BLOCKED on an error attributed to the repo).
                                entry["changed"] = False
                                entry["self_inflicted"] = own
                                _log(f"[repair {cand['label']}] not a qualifying change: its new error names {own!r}, which this candidate added "
                                     "and the repository does not declare")
                        if cand["trace_plan"] is not None:
                            # harness-v1.10: the behavioural checks, trace half. A candidate they refuse does not qualify; a missing report vetoes nothing and is recorded as such.
                            try:
                                report = behaviour.entry_report(trace_reports.get(cand["number"], []))
                                found = behaviour.trace_findings(report, cand["trace_plan"], succeeded=bool(result.succeeded), smoke_seconds=deps.smoke_seconds or 60)
                                status = "ok" if report is not None else "missing"
                            except Exception as exc:  # noqa: BLE001 - a report that cannot be read is a report that is missing, never a crash
                                report, found, status = None, [], f"unreadable: {type(exc).__name__}"
                            trace_record = {"status": status, "findings": [f.as_dict() for f in found], "plan": cand["trace_plan"].as_dict()}
                            if bmode == "flag":
                                # flag mode: the trace refuses nothing; its findings join the static ones on the attempt (advisory)
                                entry["behaviour"] = _flag_record(cand.get("behaviour_flags"), trace_record)
                                if found:
                                    _log(f"[repair {cand['label']}] behaviour check FLAGGED after the run (advisory, nothing refused): "
                                         + "; ".join(f"{f.reason} ({f.detail[:140]})" for f in found))
                            else:
                                entry["behaviour"] = {"static": [], "trace": trace_record}
                                if found and entry["changed"]:
                                    entry["changed"] = False
                                    entry["behaviour"]["refused"] = True
                                    _log(f"[repair {cand['label']}] behaviour check REFUSED after the run: " + "; ".join(f"{f.reason} ({f.detail[:140]})" for f in found))
                        _log(f"[repair {cand['label']}] re-execution id={result.sandbox_id} exit_code={result.final.exit_code}; "
                             f"exit outcome {'changed' if entry['changed'] else 'unchanged'}")
                    else:
                        _log(f"[repair {cand['label']}] not completed: {str(exc)[:200]}")
                    executed.append(entry)

                adjudication = None
                if fatal is None:
                    qualifying = [e for e in executed if e["result"] is not None and e["changed"]]
                    state.stage = "adjudicator"
                    adjudication = adjudicator.adjudicate_candidates(
                        deps.adjudicator_client, deps.adjudicator_model,
                        f"{classification.code}: {classification.evidence}",
                        [{"number": e["number"], "diff": e["checked_diff"], "env_delta": json.dumps(list(e["env_delta_dicts"])),
                          "exit_code": e["result"].final.exit_code,
                          **({"exit_zero_check": exit_zero_check.finding_of(e["result"])} if exit_zero_check.finding_of(e["result"]) else {}),
                          "outcome": (_execution_of(e["result"], True) or {}).get("outcome", "exited"),
                          "stage": _candidate_stage(e["result"], (_execution_of(e["result"], True) or {}).get("outcome", "exited")),
                          # harness-v1.4.2-rc (D-38): a candidate whose run the sandbox killed (SIGKILL) ends the entry INDETERMINATE once adopted
                          "resource_kill": (e["classification"] is not None
                                            and e["classification"].code == classifier.TaxonomyCode.RESOURCE_LIMIT),
                          "output_tail": f"{e['result'].final.stderr[-1200:]}\n{e['result'].final.stdout[-800:]}",
                          "explanation": e["proposal"].explanation} for e in qualifying],
                        cost_guard=cost_guard,
                        # harness-v1.4.2-rc (D-37): the failure being repaired, for the partial-progress rule
                        current_stage=_candidate_stage(sandbox_result, (_execution_of(sandbox_result, True) or {}).get("outcome", "exited")),
                    )
                    _log(f"[adjudicator] qualifying candidate(s) {list(adjudication.qualifying)}; chosen: {adjudication.chosen}"
                         + (f" ({adjudication.adopted_reason})" if adjudication.adopted_reason else "")
                         + (f" (model not called: {adjudication.reasoning})" if not adjudication.model_called else
                            f"; reasoning: {adjudication.reasoning[:300]}"))
                winner = next((e for e in executed if adjudication is not None and e["number"] == adjudication.chosen), None)
                released = [e["result"].result_image for e in executed
                            if e is not winner and e["result"] is not None and e["result"].result_image]
                adjudication_record = dict(adjudication.as_dict(), released_images=released) if adjudication is not None else None

                for e in executed:
                    cited_tavily, cited_resolved = _cite(e["env_changes"], e["proposal"].cited_sources, e["checked_diff"])
                    result, exc = e["result"], e["error"]
                    branch = None
                    if result is not None:
                        branch = {"branch_from_image": result.branch_from_image, "result_image": result.result_image,
                                  "image_kept": e is winner and bool(result.result_image)}
                    env_outcome = (_settle_moves(e["env_changes"], result)  # harness-v1.8 (T1)
                                   if result is not None and not result.succeeded and e is not winner and e["env_changes"] else None)
                    attempts.append(
                        AttemptRecord(
                            attempt_number,
                            e["checked_diff"],
                            "PASS",
                            (),
                            result.final.exit_code if result is not None else None,
                            result.final.stdout[-2000:] if result is not None else "",
                            (result.final.stderr[-2000:] if result is not None else
                             (f"stopped before completion: {exc}" if isinstance(exc, CostLimitExceeded) else str(exc))[-2000:]),
                            cited_tavily,
                            e["env_delta_dicts"],
                            cited_resolved,
                            execution=_execution_of(result, True) if result is not None else None,
                            patch_notes=e["patch_notes"], indentation_normalised=e.get("indentation_normalised"),
                            model_patch=e["model_patch"],
                            consulted=consulted,
                            reason_no_citation=e["proposal"].reason_no_citation,
                            silent_exit=silent_exit,
                            candidate=e["number"],
                            branch=branch,
                            adjudication=adjudication_record,
                            chosen=(e is winner) if adjudication is not None else None,
                            time_machine_action=_candidate_action_record(e["actions"]),
                            env_outcome=env_outcome,
                            behaviour=e.get("behaviour") or _flag_record(e.get("behaviour_flags"), None),
                        )
                    )
                with op_lock:
                    layer_images = {layer["image"] for layer in state.layers}
                released = [image for image in released if image not in layer_images]  # never a layer a later operation may reopen
                if adjudication_record is not None:
                    adjudication_record["released_images"] = released
                if released and deps.image_releaser is not None:
                    try:
                        outcome = deps.image_releaser(api_key=deps.sandbox_api_key, project_id=deps.sandbox_project_id, image_ids=released)
                        outcome = outcome if isinstance(outcome, dict) else {"released": int(outcome or 0), "cost_usd": 0.0, "seconds": 0.0}
                        # The disposal runs are sandbox runs: their measured cost is spend, recorded like any other operation's.
                        cost_guard.record_spend(float(outcome.get("cost_usd") or 0.0))
                        cost_guard.record_operation({
                            "role": f"repair {attempt_number}: release candidate images not chosen", "candidate": None, "concurrent": 1,
                            "released_images": released, "released": outcome.get("released"),
                            "note": "a disposable run on each image, as the sandbox's own cleanup; the SDK has no delete call",
                            "sandbox_seconds": round(float(outcome.get("seconds") or 0.0), 3), "install_seconds": [],
                            "branch_from_image": None, "result_image": None, "image_kept": False, "kept_images": [],
                            "torch_installed": False, "torch_in_start_image": False, "torch_env_key": None,
                            "cost_usd": round(float(outcome.get("cost_usd") or 0.0), 6), "cost_estimated_usd": 0.0, "outcome": "completed",
                        })
                        with op_lock:
                            for op in cost_guard.operations:
                                if op.get("result_image") in released:
                                    op["kept_images"] = [i for i in op.get("kept_images", []) if i != op["result_image"]]
                                    op["image_kept"] = bool(op["kept_images"])
                                    op["result_image_released"] = True
                        _log(f"[checkpoint] ran the disposal step on {outcome.get('released')} of {len(released)} candidate image(s) "
                             f"that were not chosen (${float(outcome.get('cost_usd') or 0.0):.4f} recorded; the SDK has no delete call, "
                             "so whether this frees storage is not known)")
                    except Exception as exc:  # noqa: BLE001 - best effort, like the sandbox's own cleanup
                        _log(f"[checkpoint] releasing the candidate images that were not chosen failed: {exc}")
                if fatal is not None:
                    raise fatal
                if winner is None:
                    _log(f"[repair {attempt_number}] no candidate adopted; the checkout and the environment image are unchanged")
                    if any(isinstance(e["error"], CostLimitExceeded) for e in executed):
                        break
                    continue
                proposal = winner["proposal"]
                env_changes = winner["env_changes"]
                if winner["checked_diff"]:
                    state.stage = "apply_diff"
                    try:
                        deps.apply_diff(workdir, winner["checked_diff"])
                        state.patched_paths.update(prepare_patch(winner["checked_diff"]).paths)
                    except OrchestratorError as exc:
                        # It applied in the scratch copy a moment ago; failing here means the checkout changed under RERUN.
                        raise OrchestratorError(f"the adjudicated candidate's patch no longer applies to the checkout: {exc}") from exc
                if env_changes or winner["plan"] != plan or winner["requirements"] != current_requirements:
                    plan, current_requirements = winner["plan"], winner["requirements"]
                    _log(f"[repair {attempt_number}] candidate {winner['number']}'s env delta applied; build plan now: {plan.as_dict()}")
                # harness-v1.4.1-rc (D-33/D-34/D-35): what the rules added to the winner's branch is now the run's environment.
                state.apt_layers.extend(winner["apt_layers"])
                for command in winner["extras"]:
                    state.runner_extras.append(command)
                    adopted_hook = runner_hooks.hook_of_command(command)
                    if adopted_hook:
                        hooks_installed.add(adopted_hook)
                if winner["wrapper"]:
                    state.exit_wrapper = True
                if (winner.get("apt_archive") and not state.apt_archive
                        and any(a.get("rule") == APT_ARCHIVE_RULE and a.get("rewrote") for a in winner["actions"])):
                    # harness-v1.7.2 (D-48): the adopted candidate needed the archive rewrite; every later apt command of the run keeps it. Only when the
                    # step actually rewrote a release: on a live release (or a dead third-party source) it does nothing, and the note would be untrue.
                    # Known limit: if the plan's FIRST apt step is prefixed, the candidate's branch cannot reuse the kept image for it and rebuilds from
                    # there; in practice a plan's own apt step on an end-of-life image fails at the baseline, where the main-loop step fires first.
                    state.apt_archive = True
                    plan = replace(plan, notes=(*plan.notes, _apt_archive_note()))
                state.build_plan_dict = plan.as_dict()
                rerun_result = winner["result"]
                if rerun_result.result_image:
                    winner_cmds = tuple(rerun_result.setup_commands) or setup_commands(_sandbox_steps(plan), None, tuple(state.runner_extras))
                    _register_layers(plan.base_image, ((winner_cmds, rerun_result.result_image),), len(cost_guard.operations), patched=True)
                    state.env_image = {"image": rerun_result.result_image, "base_image": plan.base_image, "ops": winner_cmds,
                                       "op": len(cost_guard.operations), "adopted_from_candidate": winner["number"]}
                    _log(f"[checkpoint] candidate {winner['number']}'s image {rerun_result.result_image} is the new environment image "
                         "(env_image_id)")
                if not rerun_result.succeeded:
                    failed_moves.update(env_repair.change_key(c) for c in env_changes)
                    rerun_result = _with_build_isolation(rerun_result)

            if rerun_result.succeeded:
                verdict = "RUNS_AFTER_REPAIR"
                state.error_chain.clear_last(attempt_number)  # harness-v1.6: this model attempt cleared the failure
                sandbox_result = rerun_result
                break

            state.stage = "classifier"
            classification = _classify_run(
                rerun_result.final.exit_code,
                rerun_result.final.stderr,
                rerun_result.final.stdout,
                declared_deps=intake_result.declared_dependencies,
                repo_modules=_internal_modules(),
            )
            taxonomy_code = classification.code
            sandbox_result = rerun_result
            _log(f"[classifier] {classification.code}: {classification.evidence}")
            sandbox_reason = _note_failure(attempt_number, classification, rerun_result.final.phase, may_defer=attempt_number < deps.max_attempts,
                                          result=rerun_result)
            if sandbox_reason:
                verdict, indeterminate_reason = "INDETERMINATE", sandbox_reason
                _log(f"[verdict] INDETERMINATE: {sandbox_reason}")
                break

        deferred_reason = None
        if verdict is None and not state.cost_capped and classification.code in (classifier.TaxonomyCode.RESOURCE_LIMIT,
                                                                                 classifier.TaxonomyCode.APT_MIRROR_GONE):
            # harness-v1.7 (v1.7 review, L3): the attempts ended (or the attempt budget stopped them) before a deferred rule ran: the stop applies
            deferred_reason = _note_failure(0, classification, sandbox_result.final.phase, record=False, may_defer=False)
        if verdict is None and deferred_reason:
            verdict, indeterminate_reason = "INDETERMINATE", deferred_reason
            _log(f"[verdict] INDETERMINATE: {indeterminate_reason}")
        elif verdict is None and state.cost_capped:
            verdict, indeterminate_reason = "INDETERMINATE", _cost_cap_reason(state.cost_capped)
            _log(f"[verdict] INDETERMINATE: {indeterminate_reason}")
        elif verdict is None and exit_zero_check.stop_of(sandbox_result):
            # harness-v1.7.2 (D-46): the last run exited 0 after printing only a usage message (the loop-top check covers the runs a further attempt reads)
            verdict, indeterminate_reason = "INDETERMINATE", exit_zero_check.stop_reason(exit_zero_check.stop_of(sandbox_result))
            _log(f"[verdict] INDETERMINATE: {indeterminate_reason}")
        elif verdict is None and output_cut_without_error(sandbox_result):
            # harness-v1.4.3-rc (D-41): the loop-top check covers every failure a further attempt would have read; the LAST attempt's result (and a repair-off arm's baseline) end here
            indeterminate_reason = output_cut_without_error(sandbox_result)
            verdict = "INDETERMINATE"
            _log(f"[verdict] INDETERMINATE: {indeterminate_reason}")
        elif verdict is None:
            verdict = "BLOCKED"
            model_attempts = sum(1 for a in attempts if a.origin == "model")
            _log(f"[verdict] BLOCKED after {model_attempts} repair attempt(s): {taxonomy_code}")

    return _finalize(
        verdict=verdict,
        taxonomy_code=taxonomy_code,
        indeterminate_reason=indeterminate_reason,
        attempts=tuple(attempts),
        build_plan_dict=plan.as_dict(),
        log_lines=log_lines,
        deps=deps,
        cost_guard=cost_guard,
        on_event=on_event,
        attempts_used=sum(1 for a in attempts if a.origin == "model"),
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
        reason=indeterminate_reason,
    )
    if adjudication.was_downgraded:
        _log(f"[adjudicator] downgraded verdict to {adjudication.verdict}: {adjudication.downgrade_reason}")
    elif adjudication.model_attempted_upgrade:
        _log("[adjudicator] model attempted to upgrade the verdict — rejected by the fixed clamp")

    if state is not None:
        state.stage = "passport"
    timestamp = datetime.now(timezone.utc).isoformat()
    full_log = "\n".join(log_lines)

    baseline = dict(state.baseline) if state is not None else {"result": "NOT_RUN"}
    recovery = baseline.get("result") == "FAILS" and adjudication.verdict == "RUNS_AFTER_REPAIR"
    certificate_for_hash = {
        "repo_url": repo_url,
        "commit_sha": commit_sha,
        "build_plan": build_plan_dict or {},
        "full_log": full_log,
        "diffs": [a.as_dict() for a in attempts],
        "verdict": adjudication.verdict,
        "timestamp": timestamp,
        "bundle_version": passport.CURRENT_BUNDLE_VERSION,
        "baseline": baseline,
        "recovery": recovery,
        "tree_integrity": dict(state.tree_integrity) if state is not None else {"status": "not_checked"},
        "corpus_hash": getattr(state, "corpus_hash", None),
        **_verdict_record(state, taxonomy_code, indeterminate_reason, adjudication.verdict, attempts),
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
        baseline=baseline,
        recovery=recovery,
        tree_integrity=certificate_for_hash["tree_integrity"],
        corpus_hash=certificate_for_hash["corpus_hash"],
        **_chain_kwargs(state),
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
    baseline = dict(state.baseline)
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
                "bundle_version": passport.CURRENT_BUNDLE_VERSION,
                "baseline": baseline,
                "recovery": False,
                "tree_integrity": dict(state.tree_integrity),
                "corpus_hash": getattr(state, "corpus_hash", None),
                **_verdict_record(state, None, reason, verdict, attempts),
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
        baseline=baseline,
        recovery=False,
        tree_integrity=dict(state.tree_integrity),
        corpus_hash=getattr(state, "corpus_hash", None),
        **_chain_kwargs(state),
    )


def _finalize_invalid_harness(
    exc: "tree_integrity.HarnessIntegrityError",
    *,
    state: _RunState,
    repo_url: str,
    commit_sha: str,
    on_event: Callable[[str], None] | None,
) -> PipelineResult:
    """The upload was not the committed tree: abort with INVALID_HARNESS.
    Nothing about the repository is claimed; the adjudicator is not asked
    (there is no repo evidence to summarise)."""
    log_lines = state.log_lines

    def _log(line: str) -> None:
        log_lines.append(line)
        if on_event is not None:
            try:
                on_event(line)
            except Exception:  # noqa: BLE001
                pass

    reason = f"{tree_integrity.INVALID_HARNESS}: {exc}"
    state.tree_integrity = dict(exc.record)
    _log(f"[integrity] FAILED — {exc}")
    _log(f"[verdict] INVALID_HARNESS — the run is void; this is RERUN's fault, not the repository's")
    verdict = tree_integrity.INVALID_HARNESS
    attempts = tuple(state.attempts)
    timestamp = datetime.now(timezone.utc).isoformat()
    full_log = "\n".join(log_lines)
    baseline = dict(state.baseline)
    cert = {
        "repo_url": repo_url,
        "commit_sha": commit_sha,
        "build_plan": state.build_plan_dict or {},
        "full_log": full_log,
        "diffs": [a.as_dict() for a in attempts],
        "verdict": verdict,
        "timestamp": timestamp,
        "bundle_version": passport.CURRENT_BUNDLE_VERSION,
        "baseline": baseline,
        "recovery": False,
        "tree_integrity": dict(state.tree_integrity),
        "corpus_hash": getattr(state, "corpus_hash", None),
        **_verdict_record(state, None, reason, verdict, attempts),
    }
    return PipelineResult(
        verdict=verdict,
        taxonomy_code=None,
        indeterminate_reason=reason,
        attempts=attempts,
        build_plan=state.build_plan_dict,
        full_log=full_log,
        certificate_prose=adjudicator.templated_certificate_prose(verdict, None, 0),
        reproduction_passport_hash=passport.compute_passport_hash(cert),
        timestamp=timestamp,
        repo_url=repo_url,
        commit_sha=commit_sha,
        baseline=baseline,
        recovery=False,
        tree_integrity=cert["tree_integrity"],
        corpus_hash=cert["corpus_hash"],
        **_chain_kwargs(state),
    )


def _finalize_timeout(
    exc: SandboxTimeoutError,
    *,
    state: _RunState,
    deps: PipelineDeps,
    cost_guard: CostGuard,
    repo_url: str,
    commit_sha: str,
    on_event: Callable[[str], None] | None,
) -> PipelineResult:
    log_lines = state.log_lines
    line = f"[sandbox] re-execution hit the wall clock: {exc}"
    log_lines.append(line)
    if on_event is not None:
        try:
            on_event(line)
        except Exception:  # noqa: BLE001
            pass
    return _finalize(
        verdict="TIMEOUT",
        taxonomy_code=None,
        indeterminate_reason="",
        attempts=tuple(state.attempts),
        build_plan_dict=state.build_plan_dict,
        log_lines=log_lines,
        deps=deps,
        cost_guard=cost_guard,
        on_event=on_event,
        attempts_used=sum(1 for a in state.attempts if a.origin == "model"),
        repo_url=repo_url,
        commit_sha=commit_sha,
        state=state,
    )


def _finalize_infra_error(
    exc: infra.InfraError,
    *,
    state: _RunState,
    repo_url: str,
    commit_sha: str,
    on_event: Callable[[str], None] | None,
) -> PipelineResult:
    """An external service (Nebius sandbox or model API, GitHub, the package
    index) failed even after retries: verdict INFRA_ERROR, reason code
    INFRA_ERROR:<source>:<cause>. Nothing about the repository is claimed,
    the adjudicator is not asked (its API may be the one that failed), and
    the run is excluded from every reproducibility denominator."""
    log_lines = state.log_lines

    def _log(line: str) -> None:
        log_lines.append(line)
        if on_event is not None:
            try:
                on_event(line)
            except Exception:  # noqa: BLE001
                pass

    code = f"{infra.INFRA_ERROR}:{exc.source}" + (f":{exc.cause_type}" if exc.cause_type else "")
    reason = f"{code}: {exc} — an external service failed during '{state.stage}'; this is not a verdict on the repository."
    return _finalize_not_measured(
        infra.INFRA_ERROR, reason, state=state, repo_url=repo_url, commit_sha=commit_sha, on_event=on_event
    )


def _finalize_not_measured(
    verdict: str,
    reason: str,
    *,
    state: _RunState,
    repo_url: str,
    commit_sha: str,
    on_event: Callable[[str], None] | None,
    taxonomy_code: str | None = None,
) -> PipelineResult:
    """End a run that measured nothing about the repository (INFRA_ERROR,
    UPLOAD_TOO_LARGE): a signed certificate carrying the reason; the
    adjudicator is not asked; excluded from every denominator."""
    log_lines = state.log_lines

    def _log(line: str) -> None:
        log_lines.append(line)
        if on_event is not None:
            try:
                on_event(line)
            except Exception:  # noqa: BLE001
                pass

    _log(f"[{'infra' if verdict == infra.INFRA_ERROR else 'sandbox-limit' if taxonomy_code else 'harness-limit'}] {reason}")
    if taxonomy_code:
        state.error_chain.record(0, taxonomy_code, reason, error_chain.SANDBOX_QUOTA if taxonomy_code == "SANDBOX_QUOTA" else error_chain.PLATFORM)
    attempts = tuple(state.attempts)
    timestamp = datetime.now(timezone.utc).isoformat()
    full_log = "\n".join(log_lines)
    baseline = dict(state.baseline)
    cert = {
        "repo_url": repo_url,
        "commit_sha": commit_sha,
        "build_plan": state.build_plan_dict or {},
        "full_log": full_log,
        "diffs": [a.as_dict() for a in attempts],
        "verdict": verdict,
        "timestamp": timestamp,
        "bundle_version": passport.CURRENT_BUNDLE_VERSION,
        "baseline": baseline,
        "recovery": False,
        "tree_integrity": dict(state.tree_integrity),
        "corpus_hash": getattr(state, "corpus_hash", None),
        **_verdict_record(state, taxonomy_code, reason, verdict, attempts),
    }
    return PipelineResult(
        verdict=verdict,
        taxonomy_code=taxonomy_code,
        indeterminate_reason=reason,
        attempts=attempts,
        build_plan=state.build_plan_dict,
        full_log=full_log,
        certificate_prose=adjudicator.templated_certificate_prose(verdict, None, 0),
        reproduction_passport_hash=passport.compute_passport_hash(cert),
        timestamp=timestamp,
        repo_url=repo_url,
        commit_sha=commit_sha,
        baseline=baseline,
        recovery=False,
        tree_integrity=cert["tree_integrity"],
        corpus_hash=cert["corpus_hash"],
        **_chain_kwargs(state),
    )
