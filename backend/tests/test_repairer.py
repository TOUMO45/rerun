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


# --- Invalid-JSON reply: one re-ask that does not consume a repair attempt ---


class _ScriptedClient:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def chat_completion(self, **kwargs):
        self.calls.append(kwargs)
        return self._responses.pop(0)


def _classification():
    from app.services.classifier import classify

    return classify(exit_code=1, stderr="ModuleNotFoundError: No module named 'torch'")


def test_invalid_json_reply_is_re_asked_once_and_then_used():
    import json as _json

    from app.services.repairer import propose_repair

    client = _ScriptedClient(['{"code_diff": "--- a/x\n', _json.dumps({"code_diff": None, "env_delta": [{"op": "add"}], "explanation": "e"})])
    proposal = propose_repair(client, "m", _classification(), "train.py", "import torch\n")
    assert len(client.calls) == 2
    assert proposal.parse_retried and proposal.has_change
    assert "could not be parsed as JSON" in client.calls[1]["user_prompt"]


def test_invalid_json_twice_declines_without_a_third_call():
    from app.services.repairer import propose_repair

    client = _ScriptedClient(["not json", "still not json", "never asked"])
    proposal = propose_repair(client, "m", _classification(), "train.py", "import torch\n")
    assert proposal.declined and proposal.parse_retried
    assert len(client.calls) == 2


def test_negative_control_valid_json_first_time_makes_one_call():
    import json as _json

    from app.services.repairer import propose_repair

    client = _ScriptedClient([_json.dumps({"code_diff": None, "env_delta": [], "explanation": "no"})])
    proposal = propose_repair(client, "m", _classification(), "train.py", "import torch\n")
    assert len(client.calls) == 1 and not proposal.parse_retried


def test_parse_retry_does_not_consume_a_repair_attempt(tmp_path):
    """End to end: 1 allowed attempt; the first reply is invalid JSON, the
    re-ask produces a fix that works -> RUNS_AFTER_REPAIR within that one attempt."""
    import json as _json

    from app.services.cost_guard import CostGuard
    from app.services.intake import RepoIntake
    from app.services.orchestrator import PipelineDeps, run_pipeline
    from app.services.sandbox import SandboxRunResult, StepResult

    (tmp_path / "train.py").write_text("print(1 / 0)\n", encoding="utf-8")
    fixed = "--- a/train.py\n+++ b/train.py\n@@ -1 +1 @@\n-print(1 / 0)\n+print(1 / 1)\n"
    repair = _ScriptedClient(['{"code_diff": "broken', _json.dumps({"code_diff": fixed, "explanation": "fix"})])
    results = [
        SandboxRunResult(steps=(StepResult("run", 1, "", "ZeroDivisionError: division by zero", 1.0, 0.0),)),
        SandboxRunResult(steps=(StepResult("run", 0, "1.0", "", 1.0, 0.0),)),
    ]
    deps = PipelineDeps(
        recon_client=_ScriptedClient([_json.dumps({"entrypoint": "train.py", "confidence": 0.9})]),
        recon_model="r",
        repair_client=repair,
        repair_model="p",
        adjudicator_client=None,
        adjudicator_model=None,
        sandbox_api_key="k",
        sandbox_wall_clock_seconds=60,
        sandbox_runner=lambda **kw: results.pop(0),
        max_attempts=1,
    )
    intake = RepoIntake(tmp_path, "a" * 40, {}, frozenset(), (), ("train.py",), None)
    guard = CostGuard(daily_cost_ceiling_usd=100)
    result = run_pipeline(
        repo_url="https://e.com/r", commit_sha="a" * 40, workdir=tmp_path, intake_result=intake,
        deps=deps, cost_guard=guard, run_id="parse-retry",
    )
    assert result.verdict == "RUNS_AFTER_REPAIR", result.full_log
    assert len(result.attempts) == 1
    assert guard.attempts_used("parse-retry") == 1
    assert "re-asked once (same attempt)" in result.full_log
