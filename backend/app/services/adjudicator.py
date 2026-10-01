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

from app.services.infra import InfraError
from app.services.model_client import (
    UNTRUSTED_CONTENT_NOTICE,
    ModelCallError,
    ModelResponseParseError,
    call_json_model,
    untrusted_block,
)

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
    # INVALID_HARNESS is deliberately absent: it is never adjudicated (there
    # is no repo evidence), and a model proposing it for a real run is
    # rejected by the clamp like any unknown verdict — a model must never be
    # able to void a real measurement.
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
        "INVALID_HARNESS": "RERUN's harness could not prove the uploaded files were the committed ones, so nothing is claimed about the repository.",
        "INFRA_ERROR": "An external service RERUN depends on failed during this run, so nothing is claimed about the repository.",
        "UPLOAD_TOO_LARGE": "The repository exceeds RERUN's pre-declared upload size limit, so it was not run and nothing is claimed about it.",
    }.get(verdict, f"Verdict: {verdict}.")
    if verdict == "INDETERMINATE" and taxonomy_code in ("SANDBOX_QUOTA", "SANDBOX_INCOMPAT"):
        base = (
            "The Nebius sandbox refused to load or store something the run needed "
            f"({taxonomy_code}); a platform limit is not evidence about the repository's code, so nothing is claimed about it."
        )
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


# --- harness-v1.4.0-rc: adjudication between repair candidates ---------------------------------------------------
# Super proposes up to three candidates per failure; each ran in its own branch of the checkpoint image. The candidates that passed the
# tamper gate AND changed the exit outcome are shown to Ultra, which picks the one whose change most plausibly fixes the failure without
# weakening what the repository's command does, or none. Ultra's choice is checked in code (it must be one of the qualifying numbers);
# when the call fails, RERUN picks deterministically (the first qualifying candidate whose run passed, else the first qualifying one)
# and the record says so.

CANDIDATE_ADJUDICATOR_MAX_TOKENS = 2048

_CANDIDATE_SYSTEM_PROMPT = """You adjudicate between candidate repairs of a research repository that failed to run. Each candidate
was proposed by another model, passed a deterministic tamper gate, and was executed in its own sandbox branch; you see its change and
what its run printed. Choose the ONE candidate whose change most plausibly fixes the failure while leaving the repository's documented
command doing the same work (no skipped steps, no reduced data or epochs, no swallowed errors, no edited evaluation). A run that passed
is not automatically the best: it may have passed by doing less. Choose null if no candidate is acceptable.

Respond with ONLY a JSON object, no prose, no markdown fences:
{"chosen": <candidate number or null>, "reasoning": "<2-4 sentences citing the specific evidence>"}""" + UNTRUSTED_CONTENT_NOTICE


@dataclass(frozen=True)
class CandidateAdjudication:
    chosen: int | None
    reasoning: str
    qualifying: tuple[int, ...]
    model_called: bool
    fallback: str = ""  # why RERUN decided instead of the model, when it did
    # harness-v1.4.1-rc (D-32), each only serialized when set: every raw reply the adjudicator gave, in order (a first reply that was not
    # valid JSON is followed by the re-ask's reply); and, when RERUN chose, the recorded stage of each qualifying candidate that the
    # choice was made from.
    replies: tuple[str, ...] = ()
    reasked: bool = False
    fallback_basis: dict | None = None

    def as_dict(self) -> dict:
        record = {"chosen": self.chosen, "reasoning": self.reasoning, "qualifying": list(self.qualifying),
                  "model_called": self.model_called}
        if self.fallback:
            record["fallback"] = self.fallback
        if self.replies:
            record["replies"] = list(self.replies)
        if self.reasked:
            record["reasked"] = True
        if self.fallback_basis is not None:
            record["fallback_basis"] = self.fallback_basis
        return record


# harness-v1.4.1-rc (D-32): how far a candidate's run got, from what its operation recorded (no model involved).
_PHASE_RANK = {"runner_setup": 0, "repo_install": 1, "repo_run": 2}


def stage_rank(stage: dict | None) -> tuple:
    """Order of candidate runs by the furthest recorded stage, larger = further. `stage` = {"phase": the phase of the run's final step
    ("runner_setup" < "repo_install" < "repo_run"), "setup_completed": setup steps that finished before it, "outcome": the smoke record's
    outcome ("exited" | "alive_at_limit" | "failed_while_running"), "seconds": how long the final step ran, "exit_code"}. A run that
    exited 0 is furthest; a failure in setup counts the setup steps completed; a failure in the repository's own command counts whether
    it was still running when it failed, then how long it ran. A candidate with no stage ranks lowest (ties go to the lowest number)."""
    if not stage:
        return (0, -1, 0, 0, 0.0)
    if stage.get("exit_code") == 0:
        return (1, 3, 0, 0, 0.0)
    phase = _PHASE_RANK.get(stage.get("phase"), -1)
    ran = 1 if stage.get("outcome") == "failed_while_running" else 0
    return (0, phase, int(stage.get("setup_completed") or 0), ran, float(stage.get("seconds") or 0.0))


def _deterministic_choice(candidates: list[dict]) -> int | None:
    """RERUN's choice when the model's answer is unusable: the first candidate whose run passed; otherwise the one whose run got
    furthest by its recorded stage (D-32; harness-v1.4.0 took the first qualifying one: on corpus-v2 #7 round 1 that was candidate 1,
    stopped in package metadata, while candidate 2 had finished the install and reached `No module named 'Box2D'`); ties go to the
    lowest number."""
    if not candidates:
        return None
    passed = [c["number"] for c in candidates if c.get("exit_code") == 0]
    if passed:
        return passed[0]
    return max(candidates, key=lambda c: (stage_rank(c.get("stage")), -c["number"]))["number"]


def _basis(candidates: list[dict], choice: int | None) -> dict:
    return {"rule": "first passing run, else furthest recorded stage, ties to the lowest number",
            "stages": {str(c["number"]): c.get("stage") for c in candidates}, "chosen": choice}


class _Tap:
    """Records every raw reply of the wrapped chat client, valid JSON or not (call_json_model returns only the parsed dict)."""

    def __init__(self, client):
        self._client, self.replies = client, []

    def chat_completion(self, **kwargs):
        text = self._client.chat_completion(**kwargs)
        self.replies.append(str(text)[:2000])
        return text

    def pop_usage(self):
        pop = getattr(self._client, "pop_usage", None)
        return pop() if callable(pop) else []


def adjudicate_candidates(client, model: str | None, failure: str, candidates: list[dict], cost_guard=None) -> CandidateAdjudication:
    """`candidates`: the qualifying ones, each {"number", "diff", "env_delta", "exit_code", "outcome", "output_tail", "explanation",
    "stage"} (`stage`: see `stage_rank`). harness-v1.4.1-rc (D-32): a reply that is not valid JSON is re-asked ONCE, and both replies are
    recorded; when the answer is still unusable RERUN chooses by `_deterministic_choice` and records what it chose from."""
    qualifying = tuple(c["number"] for c in candidates)
    if not candidates:
        return CandidateAdjudication(None, "no candidate passed the gate and changed the exit outcome", qualifying, False)

    def _by_rerun(why: str, fallback: str, *, replies=(), reasked=False, model_called=True) -> CandidateAdjudication:
        choice = _deterministic_choice(candidates)
        return CandidateAdjudication(choice, f"{why}; RERUN chose candidate {choice} deterministically (furthest recorded stage)",
                                     qualifying, model_called, fallback=fallback, replies=tuple(replies), reasked=reasked,
                                     fallback_basis=_basis(candidates, choice))

    if client is None or model is None:
        return _by_rerun("no adjudicator configured", "no adjudicator client", model_called=False)
    parts = ["The failure being repaired:", untrusted_block("failure evidence", failure[:2000])]
    for c in candidates:
        parts.append(f"Candidate {c['number']}: run exit code {c.get('exit_code')}, outcome {c.get('outcome')}")
        parts.append(untrusted_block(f"candidate {c['number']} explanation", str(c.get("explanation") or "")[:600]))
        parts.append(untrusted_block(f"candidate {c['number']} code diff", str(c.get("diff") or "(none)")[:4000]))
        parts.append(untrusted_block(f"candidate {c['number']} environment changes", str(c.get("env_delta") or "(none)")[:1500]))
        parts.append(untrusted_block(f"candidate {c['number']} run output tail", str(c.get("output_tail") or "")[-2000:]))
    prompt = "\n".join(parts)
    tap = _Tap(client)
    reasked = False
    try:
        try:
            raw = call_json_model(tap, model=model, system_prompt=_CANDIDATE_SYSTEM_PROMPT, user_prompt=prompt,
                                  cost_guard=cost_guard, max_tokens=CANDIDATE_ADJUDICATOR_MAX_TOKENS)
        except ModelResponseParseError as exc:
            reasked = True
            first_line = str(exc).splitlines()[0][:200]
            raw = call_json_model(
                tap, model=model, system_prompt=_CANDIDATE_SYSTEM_PROMPT, cost_guard=cost_guard,
                max_tokens=CANDIDATE_ADJUDICATOR_MAX_TOKENS,
                user_prompt=f"{prompt}\n\nYour previous reply could not be parsed as JSON ({first_line}). Reply again with ONLY the JSON "
                            'object {"chosen": <candidate number or null>, "reasoning": "<2-4 sentences>"}, no prose, no markdown fences.')
    except ModelResponseParseError:
        return _by_rerun("the adjudicator's reply was not valid JSON twice", "reply not valid JSON after a re-ask",
                         replies=tap.replies, reasked=True)
    except (ModelCallError, InfraError) as exc:
        return _by_rerun(f"adjudicator call failed ({str(exc)[:120]})", "model call failed", replies=tap.replies, reasked=reasked)
    chosen = raw.get("chosen")
    reasoning = str(raw.get("reasoning") or "").strip()
    common = {"replies": tuple(tap.replies), "reasked": reasked}
    if chosen is None:
        return CandidateAdjudication(None, reasoning or "the adjudicator chose none", qualifying, True, **common)
    if isinstance(chosen, bool) or not isinstance(chosen, int) or chosen not in qualifying:
        return _by_rerun(f"the adjudicator answered {chosen!r}, not a qualifying candidate {list(qualifying)}; "
                         f"model reasoning: {reasoning[:300]}", "answer outside the qualifying candidates", replies=tap.replies,
                         reasked=reasked)
    return CandidateAdjudication(chosen, reasoning, qualifying, True, **common)
