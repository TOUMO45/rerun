"""Tests for recon.py's §6.1 calibrated abstention logic.

No live Nemotron call. `run_recon` is exercised against a fake chat client
(same `_ChatClientLike` shape as test_model_client.py) so the actual
decision logic — does a given model answer earn a confident verdict or
fall back to INDETERMINATE — is fully verified without a network
dependency.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.services.intake import RepoIntake
from app.services.model_client import ModelCallError
from app.services.recon import parse_recon_response, run_recon


class _FakeClient:
    def __init__(self, response_text: str | None = None, raise_error: Exception | None = None):
        self.response_text = response_text
        self.raise_error = raise_error

    def chat_completion(self, **kwargs):
        if self.raise_error:
            raise self.raise_error
        return self.response_text


def _intake_with_candidates(*candidates: str) -> RepoIntake:
    return RepoIntake(
        local_path=Path("/fake"),
        commit_sha="a" * 40,
        dependency_files={"requirements.txt": "numpy\n"},
        declared_dependencies=frozenset({"numpy"}),
        notebook_paths=(),
        entrypoint_candidates=candidates,
        python_version_hint=None,
    )


# --- parse_recon_response: pure validation logic ----------------------------


def test_parse_recon_response_accepts_confident_valid_choice():
    raw = {"entrypoint": "train.py", "confidence": 0.9, "python_version": "3.10", "data_requirements": ["a CSV in data/"]}
    result = parse_recon_response(raw, candidates=("train.py", "eval.py"))
    assert result.is_indeterminate is False
    assert result.entrypoint == "train.py"
    assert result.confidence == 0.9
    assert result.data_requirements == ("a CSV in data/",)


def test_parse_recon_response_negative_control_low_confidence_is_indeterminate():
    raw = {"entrypoint": "train.py", "confidence": 0.3}
    result = parse_recon_response(raw, candidates=("train.py",))
    assert result.is_indeterminate is True
    assert "0.30" in result.indeterminate_reason


def test_parse_recon_response_rejects_hallucinated_entrypoint_not_in_candidates():
    # The model claims high confidence in a file recon never actually found —
    # must not be trusted just because confidence looks high.
    raw = {"entrypoint": "totally_made_up.py", "confidence": 0.99}
    result = parse_recon_response(raw, candidates=("train.py", "eval.py"))
    assert result.is_indeterminate is True
    assert "not among the entrypoint candidates" in result.indeterminate_reason


def test_parse_recon_response_null_entrypoint_is_indeterminate():
    raw = {"entrypoint": None, "confidence": 0.1}
    result = parse_recon_response(raw, candidates=("train.py",))
    assert result.is_indeterminate is True


def test_parse_recon_response_no_candidates_at_all_is_indeterminate():
    raw = {"entrypoint": "train.py", "confidence": 0.99}
    result = parse_recon_response(raw, candidates=())
    assert result.is_indeterminate is True
    assert "no entrypoint candidates" in result.indeterminate_reason


def test_parse_recon_response_negative_control_exact_threshold_is_accepted():
    from app.services.recon import MIN_CONFIDENCE

    raw = {"entrypoint": "train.py", "confidence": MIN_CONFIDENCE}
    result = parse_recon_response(raw, candidates=("train.py",))
    assert result.is_indeterminate is False


def test_parse_recon_response_non_numeric_confidence_is_indeterminate():
    raw = {"entrypoint": "train.py", "confidence": "very sure"}
    result = parse_recon_response(raw, candidates=("train.py",))
    assert result.is_indeterminate is True


# --- run_recon: end-to-end against a fake client ----------------------------


def test_run_recon_no_candidates_short_circuits_without_calling_model():
    intake = _intake_with_candidates()  # empty
    client = _FakeClient(raise_error=RuntimeError("should never be called"))
    result = run_recon(client, "nvidia/nemotron-3-nano", intake)
    assert result.is_indeterminate is True
    assert "no runnable entrypoint discoverable" in result.indeterminate_reason


def test_run_recon_notebook_only_repo_gets_a_specific_honest_reason():
    """Found live during this session's audit: find_entrypoint_candidates
    only scans for *.py files, so a repo whose only code is a Jupyter
    notebook (a common, realistic shape for paper repos) always has zero
    entrypoint candidates - there is no notebook execution path anywhere
    in this pipeline (planner.py's execute_command only ever runs
    `python <file>.py`). Before this fix, that repo got the exact same
    generic "no candidate scripts found" message as a repo with no code
    at all, actively hiding the fact that real code (a notebook) WAS
    found. Still correctly INDETERMINATE, never a crash and never a
    silent guess - just an honest, specific reason instead of a
    misleading generic one.
    """
    intake = RepoIntake(
        local_path=Path("/fake"),
        commit_sha="a" * 40,
        dependency_files={"requirements.txt": "numpy\n"},
        declared_dependencies=frozenset({"numpy"}),
        notebook_paths=("analysis.ipynb",),
        entrypoint_candidates=(),
        python_version_hint=None,
    )
    client = _FakeClient(raise_error=RuntimeError("should never be called"))
    result = run_recon(client, "nvidia/nemotron-3-nano", intake)
    assert result.is_indeterminate is True
    assert "analysis.ipynb" in result.indeterminate_reason
    assert "notebook execution is not yet supported" in result.indeterminate_reason


def test_run_recon_happy_path():
    intake = _intake_with_candidates("train.py")
    client = _FakeClient(response_text=json.dumps({"entrypoint": "train.py", "confidence": 0.85}))
    result = run_recon(client, "nvidia/nemotron-3-nano", intake)
    assert result.is_indeterminate is False
    assert result.entrypoint == "train.py"


def test_run_recon_model_call_failure_becomes_indeterminate_not_a_crash():
    intake = _intake_with_candidates("train.py")
    client = _FakeClient(raise_error=ModelCallError("connection refused"))
    result = run_recon(client, "nvidia/nemotron-3-nano", intake)
    assert result.is_indeterminate is True
    assert "recon model call failed" in result.indeterminate_reason


def test_run_recon_unparseable_response_becomes_indeterminate():
    intake = _intake_with_candidates("train.py")
    client = _FakeClient(response_text="not json")
    result = run_recon(client, "nvidia/nemotron-3-nano", intake)
    assert result.is_indeterminate is True


# --- eval_call_names / model_call_names extraction + validation ------------


def test_parse_recon_response_extracts_and_validates_call_names_against_source():
    raw = {
        "entrypoint": "train.py",
        "confidence": 0.9,
        "eval_call_names": ["evaluate"],
        "model_call_names": ["generate"],
    }
    source = {"train.py": "def evaluate(m): pass\ndef run():\n    generate(x)\n    evaluate(m)\n"}
    result = parse_recon_response(raw, candidates=("train.py",), source_by_path=source)
    assert result.eval_call_names == ("evaluate",)
    assert result.model_call_names == ("generate",)


def test_parse_recon_response_drops_hallucinated_call_name_not_in_source():
    raw = {
        "entrypoint": "train.py",
        "confidence": 0.9,
        "eval_call_names": ["evaluate", "totally_made_up_function"],
    }
    source = {"train.py": "def evaluate(m): pass\nevaluate(m)\n"}
    result = parse_recon_response(raw, candidates=("train.py",), source_by_path=source)
    assert result.eval_call_names == ("evaluate",)


def test_parse_recon_response_trusts_names_when_no_source_was_shown():
    # If the caller never passed entrypoint source at all, there's nothing
    # to validate against — names pass through rather than being wiped out.
    raw = {"entrypoint": "train.py", "confidence": 0.9, "eval_call_names": ["evaluate"]}
    result = parse_recon_response(raw, candidates=("train.py",), source_by_path=None)
    assert result.eval_call_names == ("evaluate",)


def test_run_recon_passes_entrypoint_source_into_the_prompt_and_validates_names():
    intake = _intake_with_candidates("train.py")
    response = json.dumps(
        {
            "entrypoint": "train.py",
            "confidence": 0.9,
            "eval_call_names": ["evaluate", "hallucinated_eval"],
            "model_call_names": ["generate"],
        }
    )
    client = _FakeClient(response_text=response)
    source = {"train.py": "def evaluate(m): pass\ndef generate(x): pass\nevaluate(1)\ngenerate(2)\n"}
    result = run_recon(client, "nvidia/nemotron-3-nano", intake, entrypoint_file_contents=source)
    assert result.eval_call_names == ("evaluate",)
    assert result.model_call_names == ("generate",)
