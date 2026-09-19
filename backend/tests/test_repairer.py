"""Tests for repairer.py, including an end-to-end check that a proposal
this module produces is actually consumable by the real tamper_gate — the
loop these two modules form (§5.4) is exercised together, not just each
piece in isolation."""

from __future__ import annotations

import json
import textwrap

from app.services.classifier import Classification, TaxonomyCode
from app.services.model_client import ModelCallError
from app.services.repairer import parse_repair_response, propose_repair
from app.services.tamper_gate import GateRule, check_patch


class _FakeClient:
    def __init__(self, response_text: str | None = None, raise_error: Exception | None = None):
        self.response_text = response_text
        self.raise_error = raise_error

    def chat_completion(self, **kwargs):
        if self.raise_error:
            raise self.raise_error
        return self.response_text


def _classification() -> Classification:
    return Classification(
        code=TaxonomyCode.DEP_MISSING,
        family="Dependencies",
        evidence="ModuleNotFoundError: No module named 'yaml'",
    )


# --- parse_repair_response ----------------------------------------------------


def test_parse_repair_response_extracts_diff_and_explanation():
    raw = {"diff": "--- a/x.py\n+++ b/x.py\n", "explanation": "added missing import"}
    proposal = parse_repair_response(raw)
    assert proposal.has_diff
    assert proposal.diff_text == "--- a/x.py\n+++ b/x.py\n"


def test_parse_repair_response_negative_control_null_diff_is_declined():
    raw = {"diff": None, "explanation": "cannot safely fix this"}
    proposal = parse_repair_response(raw)
    assert proposal.has_diff is False
    assert proposal.declined is True


def test_parse_repair_response_negative_control_empty_string_diff_is_declined():
    raw = {"diff": "   ", "explanation": "nothing"}
    proposal = parse_repair_response(raw)
    assert proposal.declined is True


# --- propose_repair: model-call plumbing -------------------------------------


def test_propose_repair_happy_path():
    client = _FakeClient(response_text=json.dumps({"diff": "--- a/x.py\n+++ b/x.py\n", "explanation": "fix"}))
    proposal = propose_repair(client, "nvidia/nemotron-3-super", _classification(), "x.py", "old content\n")
    assert proposal.has_diff


def test_propose_repair_model_failure_declines_without_crashing():
    client = _FakeClient(raise_error=ModelCallError("rate limited"))
    proposal = propose_repair(client, "nvidia/nemotron-3-super", _classification(), "x.py", "old content\n")
    assert proposal.declined is True
    assert "repair model call failed" in proposal.explanation


# --- end-to-end: a repairer proposal actually flows through the real gate ---


def test_repair_proposal_that_deletes_eval_call_is_caught_by_the_real_gate():
    """If Nemotron proposed exactly the shortcut the system prompt forbids
    (delete the eval call to force a pass), the gate — not the prompt —
    must be what actually stops it from being applied."""
    old_source = textwrap.dedent(
        """\
        def train():
            model = build_model()
            fit(model)
            evaluate(model)

        train()
        """
    )
    raw_diff = "".join(
        __import__("difflib").unified_diff(
            old_source.splitlines(keepends=True),
            textwrap.dedent(
                """\
                def train():
                    model = build_model()
                    fit(model)

                train()
                """
            ).splitlines(keepends=True),
            fromfile="a/train.py",
            tofile="b/train.py",
        )
    )
    client = _FakeClient(response_text=json.dumps({"diff": raw_diff, "explanation": "removed a redundant call"}))
    proposal = propose_repair(client, "nvidia/nemotron-3-super", _classification(), "train.py", old_source)
    assert proposal.has_diff

    result = check_patch(proposal.diff_text, {"train.py": old_source}, eval_call_names=frozenset({"evaluate"}))
    assert result.decision == "REJECT"
    assert GateRule.DELETED_EVAL_CALL in {v.rule for v in result.violations}


def test_repair_proposal_legitimate_fix_passes_the_real_gate():
    old_source = "import yaml\nconfig = yaml.load(open('config.yaml'))\n"
    new_source = "import yaml\nconfig = yaml.safe_load(open('config.yaml'))\n"
    raw_diff = "".join(
        __import__("difflib").unified_diff(
            old_source.splitlines(keepends=True),
            new_source.splitlines(keepends=True),
            fromfile="a/main.py",
            tofile="b/main.py",
        )
    )
    client = _FakeClient(response_text=json.dumps({"diff": raw_diff, "explanation": "use safe_load"}))
    proposal = propose_repair(client, "nvidia/nemotron-3-super", _classification(), "main.py", old_source)

    result = check_patch(proposal.diff_text, {"main.py": old_source}, eval_call_names=frozenset({"evaluate"}))
    assert result.decision == "PASS"
