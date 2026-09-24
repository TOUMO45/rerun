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

from dataclasses import dataclass

from app.services.classifier import Classification
from app.services.model_client import UNTRUSTED_CONTENT_NOTICE, ModelCallError, call_json_model, untrusted_block

# Output budget incl. reasoning tokens (model_client retries once at 2x).
# Largest of the roles: the answer itself is a unified diff.
REPAIR_MAX_TOKENS = 8192

_SYSTEM_PROMPT = """You are a careful, minimal-diff software repair assistant fixing a \
single classified failure in someone else's research code so it can execute. You will \
be shown the failure's taxonomy code, the evidence line, and the current content of \
the one file most likely responsible.

Rules, non-negotiable:
- Propose the SMALLEST possible change that could plausibly fix this specific failure.
- NEVER delete or comment out a call to an evaluation/metric/assertion function.
- NEVER replace a real model/inference call with a stub, mock, or hardcoded value.
- NEVER reduce a dataset size, epoch count, or sample count from its declared default.
- NEVER add a broad `except:`/`except Exception: pass` around code that previously ran
  to completion.
- Only touch the target file shown to you — never modify test files, the classifier,
  or the tamper gate.
- Keep the diff under 40 changed lines.

A separate deterministic system will reject your patch outright if it violates any of
these — so follow them exactly, don't rely on the checker to catch a shortcut.

Respond with ONLY a single JSON object, no prose, no markdown fences:
{
  "diff": "<a valid unified diff (---/+++/@@ hunks) against the file shown, or null if you cannot propose a safe minimal fix>",
  "explanation": "<one sentence: what you changed and why it addresses the evidence>"
}""" + UNTRUSTED_CONTENT_NOTICE


@dataclass(frozen=True)
class RepairProposal:
    diff_text: str | None
    explanation: str
    declined: bool = False

    @property
    def has_diff(self) -> bool:
        return bool(self.diff_text) and not self.declined


def build_repair_user_prompt(
    classification: Classification,
    target_file_path: str,
    target_file_content: str,
    external_context: str | None = None,
) -> str:
    parts = [
        f"Taxonomy code: {classification.code} ({classification.family})",
        # Evidence is a line of the repo's own stderr/stdout.
        "Evidence:",
        untrusted_block("failure evidence from the run's output", classification.evidence),
        f"Target file: {target_file_path}",
        "Current file content:",
        untrusted_block(f"content of {target_file_path}", target_file_content),
    ]
    if external_context:
        parts.append("Additional context (cited dependency/environment evidence):")
        parts.append(untrusted_block("web search results (Tavily)", external_context))
    return "\n".join(parts)


def parse_repair_response(raw: dict) -> RepairProposal:
    diff_text = raw.get("diff")
    explanation = str(raw.get("explanation", ""))
    if diff_text is None or not str(diff_text).strip():
        return RepairProposal(diff_text=None, explanation=explanation or "model declined to propose a fix", declined=True)
    return RepairProposal(diff_text=str(diff_text), explanation=explanation)


def propose_repair(
    client,
    model: str,
    classification: Classification,
    target_file_path: str,
    target_file_content: str,
    external_context: str | None = None,
    cost_guard=None,
) -> RepairProposal:
    """Ask Nemotron Super for one candidate patch. A model-call failure
    (bad credentials, timeout, unparseable JSON) is surfaced as a declined
    proposal rather than a crash, so the orchestrator can record the
    attempt and either retry or move toward BLOCKED per §5.4 — it must
    never silently retry forever or fabricate a diff.
    """
    try:
        raw = call_json_model(
            client,
            model=model,
            system_prompt=_SYSTEM_PROMPT,
            user_prompt=build_repair_user_prompt(classification, target_file_path, target_file_content, external_context),
            cost_guard=cost_guard,
            max_tokens=REPAIR_MAX_TOKENS,
        )
    except ModelCallError as exc:
        return RepairProposal(diff_text=None, explanation=f"repair model call failed: {exc}", declined=True)

    return parse_repair_response(raw)
