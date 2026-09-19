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

Recon also identifies candidate evaluation/metric/assertion function names
and model/inference call names from the chosen entrypoint's own source —
these feed `tamper_gate.py`'s `eval_call_names`/`model_call_names`
parameters later in the pipeline. Without this, the gate's most important
rule (§5.3 rule 1: don't let a patch delete the eval call) would never
have a name to check against in a real end-to-end run. Names the model
claims are lightly validated against the actual file text (must appear as
a plausible call/def token) so an outright hallucinated name can't slip
through unchecked — though this is a name-presence check, not a
guarantee the name is semantically "the" eval function; it exists to
reduce noise, not to replace the gate's own reachability analysis.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from app.services.intake import RepoIntake
from app.services.model_client import ModelCallError, call_json_model

MIN_CONFIDENCE = 0.6
_MAX_FILE_CHARS_IN_PROMPT = 4000

_SYSTEM_PROMPT = """You are a careful research-software recon assistant. You are given \
structured facts about a cloned paper repository (dependency files found, candidate \
entrypoint scripts and their source, notebooks, a python version hint). Decide which \
single entrypoint script should be executed to reproduce the paper's main result, and \
estimate your confidence honestly. Also identify, from the entrypoint source shown to \
you: the function/method name(s) that compute or check the paper's final result (an \
evaluation, metric, or assertion call — e.g. "evaluate", "compute_accuracy"), and the \
function/method name(s) that perform the actual model inference or training forward \
pass (e.g. "generate", "forward", "predict"). These will be used to protect against a \
later automated patch that tries to delete or fake either of them — only name \
functions you actually saw called or defined in the source shown to you.

Respond with ONLY a single JSON object, no prose, no markdown fences, with exactly \
these keys:
{
  "entrypoint": "<one of the candidate paths, or null if none look right>",
  "confidence": <float 0.0-1.0>,
  "python_version": "<a python version string like '3.10', or null if unclear>",
  "data_requirements": ["<short phrases describing any data/credentials the repo seems to need>"],
  "eval_call_names": ["<function names that compute/check the final result, seen in the source>"],
  "model_call_names": ["<function names that perform real model inference/training, seen in the source>"],
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
    eval_call_names: tuple[str, ...] = ()
    model_call_names: tuple[str, ...] = ()
    reasoning: str = ""
    indeterminate_reason: str = ""

    def as_dict(self) -> dict:
        return {
            "is_indeterminate": self.is_indeterminate,
            "entrypoint": self.entrypoint,
            "confidence": self.confidence,
            "python_version": self.python_version,
            "data_requirements": list(self.data_requirements),
            "eval_call_names": list(self.eval_call_names),
            "model_call_names": list(self.model_call_names),
            "reasoning": self.reasoning,
            "indeterminate_reason": self.indeterminate_reason,
        }


def _indeterminate(reason: str) -> ReconResult:
    return ReconResult(is_indeterminate=True, indeterminate_reason=reason)


def build_recon_user_prompt(intake: RepoIntake, entrypoint_file_contents: dict[str, str] | None = None) -> str:
    facts = {
        "dependency_files_found": sorted(intake.dependency_files.keys()),
        "declared_dependencies": sorted(intake.declared_dependencies),
        "entrypoint_candidates": list(intake.entrypoint_candidates),
        "notebook_paths": list(intake.notebook_paths),
        "python_version_hint_from_files": intake.python_version_hint,
    }
    parts = [json.dumps(facts, indent=2)]
    for path, content in (entrypoint_file_contents or {}).items():
        truncated = content[:_MAX_FILE_CHARS_IN_PROMPT]
        parts.append(f"\n--- source of {path} ---\n{truncated}")
    return "\n".join(parts)


def _validate_names_against_source(names: list, source_by_path: dict[str, str]) -> tuple[str, ...]:
    """Keep only names that plausibly appear as a call or def in the
    source actually shown to the model — a cheap guard against an
    outright-hallucinated name (one the model invented with no textual
    basis at all) reaching the tamper gate."""
    if not source_by_path:
        # No source was shown to the model at all (e.g. caller didn't pass
        # entrypoint_file_contents) — nothing to validate against, so trust
        # the names as-is rather than discarding everything.
        return tuple(str(n) for n in names if str(n).strip())
    combined_source = "\n".join(source_by_path.values())
    validated = []
    for name in names:
        name = str(name).strip()
        if not name:
            continue
        if re.search(rf"\b{re.escape(name)}\s*\(", combined_source):
            validated.append(name)
    return tuple(validated)


def parse_recon_response(
    raw: dict,
    candidates: tuple[str, ...],
    source_by_path: dict[str, str] | None = None,
) -> ReconResult:
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
    eval_names = raw.get("eval_call_names") or []
    model_names = raw.get("model_call_names") or []

    return ReconResult(
        is_indeterminate=False,
        entrypoint=entrypoint,
        confidence=confidence,
        python_version=raw.get("python_version"),
        data_requirements=tuple(str(d) for d in data_reqs),
        eval_call_names=_validate_names_against_source(eval_names if isinstance(eval_names, list) else [], source_by_path or {}),
        model_call_names=_validate_names_against_source(model_names if isinstance(model_names, list) else [], source_by_path or {}),
        reasoning=str(raw.get("reasoning", "")),
    )


def run_recon(
    client,
    model: str,
    intake: RepoIntake,
    entrypoint_file_contents: dict[str, str] | None = None,
    cost_guard=None,
) -> ReconResult:
    """Full recon: build the prompt from real intake facts (optionally
    including entrypoint source, so the model can name eval/model call
    sites), call Nemotron Nano, and validate the response. Any model-call
    failure (bad credentials, unparseable JSON, network error) becomes
    INDETERMINATE, never a crash and never a silent guess — per §6.1,
    nothing was actually attempted yet, so this must not be reported as a
    repo failure.
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
            user_prompt=build_recon_user_prompt(intake, entrypoint_file_contents),
            cost_guard=cost_guard,
        )
    except ModelCallError as exc:
        return _indeterminate(f"recon model call failed: {exc}")

    return parse_recon_response(raw, intake.entrypoint_candidates, entrypoint_file_contents)
