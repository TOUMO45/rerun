"""Recon (RERUN directive §3 must-have #1, second half; §6.1 calibrated
abstention). Nemotron Nano looks at what `intake.py` already gathered
(dependency files, entrypoint candidates, notebooks) and decides:

  - which entrypoint is actually the one to run, and how confident it is;
  - the Python version to target;
  - a short list of data requirements it can infer from the repo surface.

If Nemotron can't identify a runnable entrypoint with reasonable
confidence, or the model call itself fails/returns unparseable JSON, recon
returns `ReconResult(is_indeterminate=True, ...)` — the run must terminate
as `INDETERMINATE`, not `BLOCKED`, per §6.1: nothing was actually attempted,
so it must never count as a taxonomy failure against the repo.

The confidence threshold and the "which candidate did the model pick"
check are enforced here in plain code, not left to the model's own
say-so — a model claiming confidence=0.95 for an entrypoint that isn't
even in the candidate list recon.py itself found is still INDETERMINATE.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from app.services.intake import RepoIntake
from app.services.model_client import ModelCallError, call_json_model

MIN_CONFIDENCE = 0.6

_SYSTEM_PROMPT = """You are a careful research-software recon assistant. You are given \
structured facts about a cloned paper repository (dependency files found, candidate \
entrypoint scripts, notebooks, a python version hint). Decide which single entrypoint \
script should be executed to reproduce the paper's main result, and estimate your \
confidence honestly.

Respond with ONLY a single JSON object, no prose, no markdown fences, with exactly \
these keys:
{
  "entrypoint": "<one of the candidate paths, or null if none look right>",
  "confidence": <float 0.0-1.0>,
  "python_version": "<a python version string like '3.10', or null if unclear>",
  "data_requirements": ["<short phrases describing any data/credentials the repo seems to need>"],
  "reasoning": "<one sentence>"
}

If you are not reasonably confident (e.g. multiple equally-plausible candidates, or \
none look like the real entrypoint), set confidence low and entrypoint to null rather \
than guessing. A wrong confident guess is worse than an honest low-confidence answer."""


@dataclass(frozen=True)
class ReconResult:
    is_indeterminate: bool
    entrypoint: str | None = None
    confidence: float = 0.0
    python_version: str | None = None
    data_requirements: tuple[str, ...] = ()
    reasoning: str = ""
    indeterminate_reason: str = ""

    def as_dict(self) -> dict:
        return {
            "is_indeterminate": self.is_indeterminate,
            "entrypoint": self.entrypoint,
            "confidence": self.confidence,
            "python_version": self.python_version,
            "data_requirements": list(self.data_requirements),
            "reasoning": self.reasoning,
            "indeterminate_reason": self.indeterminate_reason,
        }


def _indeterminate(reason: str) -> ReconResult:
    return ReconResult(is_indeterminate=True, indeterminate_reason=reason)


def build_recon_user_prompt(intake: RepoIntake) -> str:
    facts = {
        "dependency_files_found": sorted(intake.dependency_files.keys()),
        "declared_dependencies": sorted(intake.declared_dependencies),
        "entrypoint_candidates": list(intake.entrypoint_candidates),
        "notebook_paths": list(intake.notebook_paths),
        "python_version_hint_from_files": intake.python_version_hint,
    }
    return json.dumps(facts, indent=2)


def parse_recon_response(raw: dict, candidates: tuple[str, ...]) -> ReconResult:
    """Pure validation of an already-JSON-parsed model response against the
    candidates recon.py itself found. Never trusts the model's entrypoint
    choice blindly."""
    entrypoint = raw.get("entrypoint")
    try:
        confidence = float(raw.get("confidence", 0.0))
    except (TypeError, ValueError):
        return _indeterminate("model returned a non-numeric confidence value")

    if not candidates:
        return _indeterminate("no entrypoint candidates were found in the repo at all")

    if entrypoint is None:
        return _indeterminate("model could not identify a confident entrypoint among the candidates")

    if entrypoint not in candidates:
        return _indeterminate(
            f"model chose '{entrypoint}', which is not among the entrypoint candidates "
            f"recon actually found ({list(candidates)}) — treating as unreliable"
        )

    if confidence < MIN_CONFIDENCE:
        return _indeterminate(
            f"model's confidence ({confidence:.2f}) in entrypoint '{entrypoint}' is below "
            f"the {MIN_CONFIDENCE} threshold — candidates were {list(candidates)}"
        )

    data_reqs = raw.get("data_requirements") or []
    if not isinstance(data_reqs, list):
        data_reqs = []

    return ReconResult(
        is_indeterminate=False,
        entrypoint=entrypoint,
        confidence=confidence,
        python_version=raw.get("python_version"),
        data_requirements=tuple(str(d) for d in data_reqs),
        reasoning=str(raw.get("reasoning", "")),
    )


def run_recon(client, model: str, intake: RepoIntake) -> ReconResult:
    """Full recon: build the prompt from real intake facts, call Nemotron
    Nano, and validate the response. Any model-call failure (bad
    credentials, unparseable JSON, network error) becomes INDETERMINATE,
    never a crash and never a silent guess — per §6.1, nothing was
    actually attempted yet, so this must not be reported as a repo
    failure.
    """
    if not intake.entrypoint_candidates:
        return _indeterminate(
            "no runnable entrypoint discoverable in recon: no candidate scripts found "
            "(no train.py/main.py/run.py-style file, and no file with a __main__ guard)"
        )

    try:
        raw = call_json_model(
            client,
            model=model,
            system_prompt=_SYSTEM_PROMPT,
            user_prompt=build_recon_user_prompt(intake),
        )
    except ModelCallError as exc:
        return _indeterminate(f"recon model call failed: {exc}")

    return parse_recon_response(raw, intake.entrypoint_candidates)
