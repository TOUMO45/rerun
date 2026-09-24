"""Repairer (RERUN directive §3 must-have #5, §5.4 repair loop). Nemotron
Super proposes a minimal unified diff to fix a classified failure.

This module NEVER decides whether a proposed patch is acceptable — that
is `tamper_gate.check_patch()`'s job, and only its job (§2.1: the gate is
pure/deterministic/no model call). `repairer.py`'s only responsibility is
turning (failure classification + the one file most likely at fault) into
a candidate diff for the gate to check. A rejected proposal still consumes
one of the 3 attempts in §5.4 — that bookkeeping belongs to whatever
orchestrates the loop (not yet built), using `cost_guard.py`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace

from app.services.classifier import Classification
from app.services.model_client import (
    UNTRUSTED_CONTENT_NOTICE,
    ModelCallError,
    ModelResponseParseError,
    call_json_model,
    untrusted_block,
)

# Output budget incl. reasoning tokens (model_client retries once at 2x).
# Largest of the roles: the answer itself is a unified diff.
REPAIR_MAX_TOKENS = 8192

_SYSTEM_PROMPT = """You are a careful, minimal-diff software repair assistant fixing a \
single classified failure in someone else's research code so it can execute. You will \
be shown the failure's taxonomy code, the evidence line, the tail of the failing run's \
log, the current build plan and dependency file(s), and the content of the one file \
most likely responsible.

You can repair at two layers — use whichever actually addresses the failure:
- CODE: a unified diff to the repository's own files ("code_diff").
- ENVIRONMENT: structured edits to the build plan ("env_delta") — the right layer for \
missing system libraries, compilers, unavailable or incompatible package versions, \
packages that are not on PyPI, or the wrong Python version. The repository's files are \
never edited for these; RERUN rebuilds the environment from your delta.
When the repair layer hint says ENVIRONMENT, strongly prefer an env_delta.

Rules, non-negotiable:
- Propose the SMALLEST possible change that could plausibly fix this specific failure.
- NEVER delete or comment out a call to an evaluation/metric/assertion function.
- NEVER replace a real model/inference call with a stub, mock, or hardcoded value.
- NEVER reduce a dataset size, epoch count, or sample count from its declared default.
- NEVER add a broad `except:`/`except Exception: pass` around code that previously ran
  to completion.
- Prefer changing the target file shown to you. You may touch another file in the
  repository if the fix genuinely needs it, using repo-relative `a/<path>` / `b/<path>`
  headers — never absolute paths, `..`, renames, or deleting files. Never modify test
  files, the classifier, or the tamper gate. Every file you touch is checked.
- Keep the diff under 40 changed lines.
- env_delta ops (each change is an object):
  {"op": "pin", "package": "<pip name>", "version": "<exact version>"}
  {"op": "unpin", "package": "<pip name>"}
  {"op": "add", "package": "<pip name>", "version": "<exact version or null>"}
  {"op": "remove", "package": "<pip name>"}   (never a package the code imports)
  {"op": "pip_git", "package": "<name>", "git_url": "https://github.com/<owner>/<repo>", "commit": "<full 40-hex sha>"}
  {"op": "apt", "package": "<debian package, e.g. build-essential>"}
  {"op": "python", "version": "3.7|3.8|3.9|3.10|3.11|3.12|3.13"}
  EVERY change also needs "justification" (one line) and "evidence": a string copied
  VERBATIM from the failing run's log shown to you. Never use any other URL (no data,
  weights, or archives); git sources must be pinned to a full commit sha. Only use a
  git URL and commit you were actually given as evidence — never invent one.

A separate deterministic system will reject your patch outright if it violates any of
these — so follow them exactly, don't rely on the checker to catch a shortcut.

Respond with ONLY a single JSON object, no prose, no markdown fences:
{
  "code_diff": "<a valid unified diff (---/+++/@@ hunks), or null>",
  "env_delta": [<zero or more env changes as above>],
  "explanation": "<one sentence: what you changed and why it addresses the evidence>"
}
Set code_diff to null and env_delta to [] if you cannot propose a safe minimal fix.""" + UNTRUSTED_CONTENT_NOTICE


@dataclass(frozen=True)
class RepairProposal:
    diff_text: str | None  # the code diff
    explanation: str
    declined: bool = False
    # Raw env_delta list from the model; parsed and gated by env_repair.
    env_delta: tuple = ()
    # True if the first reply was invalid JSON and the model was re-asked.
    parse_retried: bool = False

    @property
    def has_diff(self) -> bool:
        return bool(self.diff_text) and not self.declined

    @property
    def has_change(self) -> bool:
        return not self.declined and (bool(self.diff_text) or bool(self.env_delta))


def build_repair_user_prompt(
    classification: Classification,
    target_file_path: str,
    target_file_content: str,
    external_context: str | None = None,
    *,
    repair_layer: str = "code",
    build_plan: dict | None = None,
    dependency_files: dict[str, str] | None = None,
    log_tail: str = "",
    imported_modules: list[str] | None = None,
    followup: str | None = None,
) -> str:
    parts = [
        f"Taxonomy code: {classification.code} ({classification.family})",
        f"Repair layer hint: {repair_layer.upper()}",
        # Evidence is a line of the repo's own stderr/stdout.
        "Evidence:",
        untrusted_block("failure evidence from the run's output", classification.evidence),
        f"Target file: {target_file_path}",
        "Current file content:",
        untrusted_block(f"content of {target_file_path}", target_file_content),
    ]
    if build_plan is not None:
        # Our own plan, but it embeds repo-derived names — keep it delimited.
        parts.append("Current build plan:")
        parts.append(untrusted_block("current build plan", json.dumps(build_plan, indent=2)))
    for name, content in (dependency_files or {}).items():
        parts.append(f"Dependency file {name}:")
        parts.append(untrusted_block(f"dependency file {name}", content[:4000]))
    if log_tail:
        parts.append("Tail of the failing run's log (quote `evidence` from here verbatim):")
        parts.append(untrusted_block("failing run log tail", log_tail))
    if imported_modules:
        # Every top-level module the repo's code imports (AST, never run), so
        # one env_delta can add ALL missing packages at once instead of one per
        # attempt (gpt-2 needed numpy AND tensorflow; each cost an attempt).
        parts.append("Top-level modules imported anywhere in the repository's code:")
        parts.append(untrusted_block("imported modules", ", ".join(imported_modules)))
    if external_context:
        parts.append("Additional context (cited dependency/environment evidence):")
        parts.append(untrusted_block("web search results (Tavily)", external_context))
    if followup:
        parts.append(followup)
    return "\n".join(parts)


def parse_repair_response(raw: dict) -> RepairProposal:
    # "diff" is the pre-env-layer key; still accepted.
    diff_text = raw.get("code_diff", raw.get("diff"))
    explanation = str(raw.get("explanation", ""))
    env_delta = raw.get("env_delta")
    if env_delta in (None, "", {}, []):
        env_delta = []
    elif not isinstance(env_delta, list):
        # Malformed deltas are passed through so the env gate rejects them
        # visibly, rather than being dropped here.
        env_delta = [env_delta]
    has_code = diff_text is not None and bool(str(diff_text).strip())
    if not has_code and not env_delta:
        return RepairProposal(diff_text=None, explanation=explanation or "model declined to propose a fix", declined=True)
    return RepairProposal(diff_text=str(diff_text) if has_code else None, explanation=explanation, env_delta=tuple(env_delta))


def propose_repair(
    client,
    model: str,
    classification: Classification,
    target_file_path: str,
    target_file_content: str,
    external_context: str | None = None,
    cost_guard=None,
    *,
    repair_layer: str = "code",
    build_plan: dict | None = None,
    dependency_files: dict[str, str] | None = None,
    log_tail: str = "",
    imported_modules: list[str] | None = None,
    followup: str | None = None,
) -> RepairProposal:
    """Ask Nemotron Super for one candidate patch. A model-call failure
    (bad credentials, timeout, unparseable JSON) is surfaced as a declined
    proposal rather than a crash, so the orchestrator can record the
    attempt and either retry or move toward BLOCKED per §5.4 — it must
    never silently retry forever or fabricate a diff.
    """
    user_prompt = build_repair_user_prompt(
        classification,
        target_file_path,
        target_file_content,
        external_context,
        repair_layer=repair_layer,
        build_plan=build_plan,
        dependency_files=dependency_files,
        log_tail=log_tail,
        imported_modules=imported_modules,
        followup=followup,
    )
    parse_retried = False
    for try_number in (1, 2):
        try:
            raw = call_json_model(
                client,
                model=model,
                system_prompt=_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                cost_guard=cost_guard,
                max_tokens=REPAIR_MAX_TOKENS,
            )
            break
        except ModelResponseParseError as exc:
            # Found live (gpt-2, 2026-09-24): Super's reply was invalid JSON
            # and the whole repair attempt was lost. One re-ask, inside this
            # same attempt — it does NOT consume a repair attempt (the
            # orchestrator counts propose_repair calls, not model calls).
            # response_format=json_object was tested live and did not help
            # (DECISIONS.md 2026-09-24), so this is the mechanism.
            if try_number == 2:
                return RepairProposal(
                    diff_text=None,
                    explanation=f"repair model reply was not valid JSON twice: {exc}",
                    declined=True,
                    parse_retried=True,
                )
            parse_retried = True
            first_line = str(exc).splitlines()[0][:200]
            user_prompt = (
                f"{user_prompt}\n\nYour previous reply could not be parsed as JSON ({first_line}). "
                "Reply again with ONLY the single JSON object described in the instructions — "
                "escape every newline, quote and backslash inside the code_diff string."
            )
        except ModelCallError as exc:
            return RepairProposal(diff_text=None, explanation=f"repair model call failed: {exc}", declined=True)

    proposal = parse_repair_response(raw)
    return replace(proposal, parse_retried=parse_retried) if parse_retried else proposal
