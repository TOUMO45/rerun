"""Tests for adjudicator.py. The load-bearing property is "may only
downgrade": even a model response that tries to upgrade a real failure
into a fake success must never succeed — this is enforced in
_clamp_verdict, not by trusting the prompt, and is tested adversarially
here (a fake client deliberately returns an upgrade attempt)."""

from __future__ import annotations

import json

from app.services.adjudicator import (
    SCOPE_BOUNDARY_LINE,
    adjudicate,
    templated_certificate_prose,
)


class _FakeClient:
    def __init__(self, response_text: str):
        self.response_text = response_text

    def chat_completion(self, **kwargs):
        return self.response_text


# --- templated fallback (§5 cut ladder item 1) -------------------------------


def test_templated_fallback_used_when_no_client_supplied():
    result = adjudicate(None, None, verdict="BLOCKED", taxonomy_code="DEP_MISSING", attempts_used=3)
    assert result.used_templated_fallback is True
    assert result.verdict == "BLOCKED"
    assert SCOPE_BOUNDARY_LINE in result.certificate_prose


def test_templated_prose_always_includes_scope_boundary_line():
    for verdict in ("RUNS_CLEAN", "RUNS_AFTER_REPAIR", "BLOCKED", "INDETERMINATE", "NOT_ATTEMPTABLE", "TIMEOUT"):
        prose = templated_certificate_prose(verdict, "SOME_CODE", 1)
        assert SCOPE_BOUNDARY_LINE in prose


# --- the load-bearing guarantee: the model can never upgrade a verdict -----


def test_adjudicator_rejects_a_model_attempted_upgrade():
    # The model dishonestly tries to turn a real failure into a clean pass.
    client = _FakeClient(json.dumps({"verdict": "RUNS_CLEAN", "prose": "Everything worked great!"}))
    result = adjudicate(client, "nvidia/nemotron-3-ultra", verdict="BLOCKED", taxonomy_code="DEP_MISSING", attempts_used=3)
    assert result.verdict == "BLOCKED"  # clamped back, not RUNS_CLEAN
    assert result.model_attempted_upgrade is True
    assert result.was_downgraded is False


def test_adjudicator_allows_a_genuine_downgrade():
    client = _FakeClient(
        json.dumps({"verdict": "INDETERMINATE", "prose": "Evidence is too thin to trust this pass.", "downgrade_reason": "weak evidence"})
    )
    result = adjudicate(client, "nvidia/nemotron-3-ultra", verdict="RUNS_AFTER_REPAIR", attempts_used=1)
    assert result.verdict == "INDETERMINATE"
    assert result.was_downgraded is True
    assert result.downgrade_reason == "weak evidence"


def test_adjudicator_negative_control_confirming_same_verdict_is_not_a_downgrade():
    client = _FakeClient(json.dumps({"verdict": "RUNS_CLEAN", "prose": "Ran cleanly as expected."}))
    result = adjudicate(client, "nvidia/nemotron-3-ultra", verdict="RUNS_CLEAN", attempts_used=0)
    assert result.verdict == "RUNS_CLEAN"
    assert result.was_downgraded is False
    assert result.model_attempted_upgrade is False


def test_adjudicator_rejects_invalid_verdict_string_as_an_upgrade_attempt():
    # A nonsense verdict must not be accepted as "conservative" just because
    # it isn't in the known-good rank table.
    client = _FakeClient(json.dumps({"verdict": "TOTALLY_FINE", "prose": "..."}))
    result = adjudicate(client, "nvidia/nemotron-3-ultra", verdict="BLOCKED", attempts_used=3)
    assert result.verdict == "BLOCKED"
    assert result.model_attempted_upgrade is True


def test_adjudicator_model_failure_falls_back_to_template():
    client = _FakeClient("not valid json")
    result = adjudicate(client, "nvidia/nemotron-3-ultra", verdict="TIMEOUT", attempts_used=0)
    assert result.used_templated_fallback is True
    assert result.verdict == "TIMEOUT"


def test_adjudicator_force_appends_scope_line_if_model_omits_it():
    client = _FakeClient(json.dumps({"verdict": "RUNS_CLEAN", "prose": "It just worked."}))
    result = adjudicate(client, "nvidia/nemotron-3-ultra", verdict="RUNS_CLEAN", attempts_used=0)
    assert SCOPE_BOUNDARY_LINE in result.certificate_prose
