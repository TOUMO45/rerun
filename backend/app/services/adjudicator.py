"""Adjudicator (RERUN directive §4 architecture: "certificate prose; may
only downgrade"; §5 should-have "adjudicator prose polish").

Nemotron Ultra writes the human-readable certificate summary. It is
explicitly NOT trusted to decide the verdict — the verdict was already
fixed by deterministic upstream logic (classifier/tamper-gate/repair-loop
outcome) before this module ever runs. Ultra may *confirm* that verdict in
its prose, or propose a more conservative one if it spots something
upstream logic didn't (e.g. suspicious evidence), but it can never
upgrade a BLOCKED run into a clean pass — that's enforced here in plain
code (`_VERDICT_RANK` + a hard clamp), not left to the model's honesty.

Per the §5 cut ladder ("Adjudicator prose polish -> fall back to templated
certificate text"), a missing client or a failed model call always
produces valid, honest templated prose — this stage is a should-have
enhancement, never a dependency for producing a certificate.

The §8 S3 scope-boundary line is non-negotiable and is force-appended if
the model's prose omits it, so it is never possible for a certificate to
go out without it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.services.model_client import UNTRUSTED_CONTENT_NOTICE, ModelCallError, call_json_model, untrusted_block

# Output budget incl. reasoning tokens (model_client retries once at 2x).
ADJUDICATOR_MAX_TOKENS = 2048

SCOPE_BOUNDARY_LINE = (
    "Verifies that the artifact executes. Does not verify the paper's numerical results."
)

# Higher = more "successful". Used only to forbid the model from ever
# proposing something better than the deterministic verdict it was given.
_VERDICT_RANK: dict[str, int] = {
    "RUNS_CLEAN": 5,
    "RUNS_AFTER_REPAIR": 4,
    "INDETERMINATE": 3,
    "NOT_ATTEMPTABLE": 3,
    "TIMEOUT": 2,
    "BLOCKED": 1,
}

_SYSTEM_PROMPT = f"""You write the human-readable summary paragraph for an
execution certificate. RERUN only checks whether a repository's code runs to
completion; it never checks a paper's results. Describe the outcome only in
terms of whether the code executed / ran to completion — never say the code
or the paper "reproduces", "reproduced" or is "reproducible". You are given a VERDICT that has already been
determined by deterministic checks upstream — you may NOT change it to
anything more favorable. You may only confirm it, or (if the evidence
shown to you suggests real doubt) propose a MORE CONSERVATIVE verdict from
this ranked list (higher is better; you may only move down or stay):
{sorted(_VERDICT_RANK.items(), key=lambda kv: -kv[1])}

Respond with ONLY a JSON object, no prose, no markdown fences:
{{
  "verdict": "<the same verdict you were given, or a strictly more conservative one>",
  "prose": "<2-4 sentences, factual, citing the specific evidence you were given>",
  "downgrade_reason": "<empty string if you did not downgrade, otherwise why>"
}}

Always end the prose by including this exact sentence verbatim: "{SCOPE_BOUNDARY_LINE}\"""" + UNTRUSTED_CONTENT_NOTICE


@dataclass(frozen=True)
class AdjudicationResult:
    verdict: str
    certificate_prose: str
    was_downgraded: bool
    downgrade_reason: str = ""
    model_attempted_upgrade: bool = False
    used_templated_fallback: bool = False


def templated_certificate_prose(verdict: str, taxonomy_code: str | None, attempts_used: int) -> str:
    base = {
        "RUNS_CLEAN": "The repository's command ran to completion in its declared environment, with no changes.",
        "RUNS_AFTER_REPAIR": f"The repository's command ran to completion after {attempts_used} gate-approved change(s).",
        "BLOCKED": f"The repository's command did not run to completion after {attempts_used} repair attempt(s), classified as {taxonomy_code}.",
        "INDETERMINATE": "Recon could not establish enough confidence to attempt execution.",
        "NOT_ATTEMPTABLE": "The repository has no attemptable runnable code under RERUN's current scope.",
        "TIMEOUT": "Execution exceeded the sandbox's wall-clock ceiling.",
    }.get(verdict, f"Verdict: {verdict}.")
    return f"{base} {SCOPE_BOUNDARY_LINE}"


def _clamp_verdict(original: str, proposed: str) -> tuple[str, bool, bool]:
    """Returns (final_verdict, was_downgraded, model_attempted_upgrade)."""
    original_rank = _VERDICT_RANK.get(original, -1)
    proposed_rank = _VERDICT_RANK.get(proposed, -1)
    if proposed not in _VERDICT_RANK or proposed_rank > original_rank:
        return original, False, proposed != original
    if proposed_rank < original_rank:
        return proposed, True, False
    return original, False, False


# RERUN verifies that code EXECUTES / runs to completion. It never verifies
# that a paper's results were reproduced, so certificate prose may not say so.
_REPRODUCTION_CLAIM_RE = re.compile(r"\breproduc", re.IGNORECASE)


def makes_reproduction_claim(prose: str) -> bool:
    """True if the prose (minus the fixed scope line) uses reproduce-wording."""
    return bool(_REPRODUCTION_CLAIM_RE.search(prose.replace(SCOPE_BOUNDARY_LINE, "")))


def _ensure_scope_line(prose: str) -> str:
    if SCOPE_BOUNDARY_LINE not in prose:
        prose = f"{prose.rstrip()} {SCOPE_BOUNDARY_LINE}"
    return prose


def adjudicate(
    client,
    model: str,
    verdict: str,
    taxonomy_code: str | None = None,
    attempts_used: int = 0,
    evidence_summary: str = "",
    cost_guard=None,
) -> AdjudicationResult:
    if client is None or model is None:
        return AdjudicationResult(
            verdict=verdict,
            certificate_prose=templated_certificate_prose(verdict, taxonomy_code, attempts_used),
            was_downgraded=False,
            used_templated_fallback=True,
        )

    user_prompt = (
        f"Verdict: {verdict}\n"
        f"Taxonomy code: {taxonomy_code}\n"
        f"Repair attempts used: {attempts_used}\n"
        "Evidence (tail of the run log, which includes the repo's own output):\n"
        f"{untrusted_block('run log tail', evidence_summary)}"
    )
    try:
        raw = call_json_model(
            client,
            model=model,
            system_prompt=_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            cost_guard=cost_guard,
            max_tokens=ADJUDICATOR_MAX_TOKENS,
        )
    except ModelCallError:
        return AdjudicationResult(
            verdict=verdict,
            certificate_prose=templated_certificate_prose(verdict, taxonomy_code, attempts_used),
            was_downgraded=False,
            used_templated_fallback=True,
        )

    proposed_verdict = str(raw.get("verdict", verdict))
    final_verdict, was_downgraded, attempted_upgrade = _clamp_verdict(verdict, proposed_verdict)

    prose = str(raw.get("prose") or "").strip()
    if prose and makes_reproduction_claim(prose):
        # The model wrote "reproduces"/"reproducible"/...: the certificate may
        # only say the code executes, so fall back to the fixed wording.
        prose = ""
    if not prose:
        prose = templated_certificate_prose(final_verdict, taxonomy_code, attempts_used)
        used_fallback = True
    else:
        prose = _ensure_scope_line(prose)
        used_fallback = False

    return AdjudicationResult(
        verdict=final_verdict,
        certificate_prose=prose,
        was_downgraded=was_downgraded,
        downgrade_reason=str(raw.get("downgrade_reason", "")) if was_downgraded else "",
        model_attempted_upgrade=attempted_upgrade,
        used_templated_fallback=used_fallback,
    )
