"""Tests for the shared model-call/JSON-parsing plumbing.

No live Nebius call — `call_json_model` is tested against a fake client
satisfying `_ChatClientLike`'s single-method surface, so the parsing logic
(the part this codebase actually controls) is fully verified without a
network dependency. `NebiusChatClient`'s own fail-fast credential check is
tested directly.
"""

from __future__ import annotations

import pytest

from app.services.cost_guard import CostGuard
from app.services.model_client import (
    ModelCallError,
    ModelCostLimitError,
    ModelCredentialsError,
    ModelResponseParseError,
    NebiusChatClient,
    call_json_model,
)


class _FakeClient:
    def __init__(self, response_text: str):
        self.response_text = response_text
        self.last_call: dict | None = None

    def chat_completion(self, *, model, system_prompt, user_prompt, temperature):
        self.last_call = {
            "model": model,
            "system_prompt": system_prompt,
            "user_prompt": user_prompt,
            "temperature": temperature,
        }
        return self.response_text


def test_call_json_model_parses_plain_json():
    client = _FakeClient('{"entrypoint": "train.py", "confidence": 0.9}')
    result = call_json_model(client, model="m", system_prompt="s", user_prompt="u")
    assert result == {"entrypoint": "train.py", "confidence": 0.9}


def test_call_json_model_strips_markdown_code_fence():
    client = _FakeClient('```json\n{"entrypoint": "main.py"}\n```')
    result = call_json_model(client, model="m", system_prompt="s", user_prompt="u")
    assert result == {"entrypoint": "main.py"}


def test_call_json_model_passes_through_arguments():
    client = _FakeClient("{}")
    call_json_model(client, model="nvidia/nemotron-3-nano", system_prompt="sys", user_prompt="usr", temperature=0.2)
    assert client.last_call == {
        "model": "nvidia/nemotron-3-nano",
        "system_prompt": "sys",
        "user_prompt": "usr",
        "temperature": 0.2,
    }


def test_call_json_model_negative_control_invalid_json_raises_parse_error():
    client = _FakeClient("this is not json at all")
    with pytest.raises(ModelResponseParseError):
        call_json_model(client, model="m", system_prompt="s", user_prompt="u")


def test_call_json_model_negative_control_json_array_not_object_raises():
    client = _FakeClient("[1, 2, 3]")
    with pytest.raises(ModelResponseParseError):
        call_json_model(client, model="m", system_prompt="s", user_prompt="u")


def test_nebius_chat_client_fails_fast_without_api_key():
    with pytest.raises(ModelCredentialsError):
        NebiusChatClient(api_key="", base_url="https://api.tokenfactory.nebius.com/v1")


def test_nebius_chat_client_negative_control_accepts_real_looking_key():
    client = NebiusChatClient(api_key="sk-fake-for-construction-only", base_url="https://api.tokenfactory.nebius.com/v1")
    assert client.api_key == "sk-fake-for-construction-only"


# --- §9 per-attempt token ceiling (a real chokepoint, not just documented) --


def test_call_json_model_without_cost_guard_never_checks_token_budget():
    # Backward-compat/default path: omitting cost_guard entirely must not
    # change behavior for any existing caller.
    client = _FakeClient('{"ok": true}')
    result = call_json_model(client, model="m", system_prompt="s" * 100_000, user_prompt="u", cost_guard=None)
    assert result == {"ok": True}


def test_call_json_model_blocks_a_prompt_that_exceeds_the_token_ceiling():
    guard = CostGuard(daily_cost_ceiling_usd=100, max_tokens_per_attempt=5)
    client = _FakeClient('{"ok": true}')
    with pytest.raises(ModelCostLimitError):
        call_json_model(
            client,
            model="m",
            system_prompt="this is a long enough prompt to exceed a five token ceiling easily",
            user_prompt="another chunk of text that adds even more tokens",
            cost_guard=guard,
        )


def test_call_json_model_never_calls_the_network_when_over_budget():
    # The check must happen BEFORE the network call, not after — the fake
    # client raises if it's ever invoked at all.
    guard = CostGuard(daily_cost_ceiling_usd=100, max_tokens_per_attempt=1)

    class _ExplodingClient:
        def chat_completion(self, **kwargs):
            raise AssertionError("chat_completion must never be called once the token budget is exceeded")

    with pytest.raises(ModelCostLimitError):
        call_json_model(
            _ExplodingClient(),
            model="m",
            system_prompt="a prompt with clearly more than one token in it",
            user_prompt="u",
            cost_guard=guard,
        )


def test_call_json_model_negative_control_small_prompt_under_ceiling_passes():
    guard = CostGuard(daily_cost_ceiling_usd=100, max_tokens_per_attempt=1000)
    client = _FakeClient('{"ok": true}')
    result = call_json_model(client, model="m", system_prompt="short", user_prompt="also short", cost_guard=guard)
    assert result == {"ok": True}


def test_model_cost_limit_error_is_a_model_call_error_subclass():
    # This is load-bearing: every existing caller (recon/planner/repairer/
    # adjudicator) only catches ModelCallError, and must gracefully fall
    # back (§6.1 INDETERMINATE / declined proposal / templated prose) on a
    # cost-limit trip too, without needing its own special-case handling.
    from app.services.model_client import ModelCallError

    assert issubclass(ModelCostLimitError, ModelCallError)


# --- Regression: special-token strings in untrusted repo text (first live run) --


@pytest.mark.parametrize(
    "special",
    ["<|endoftext|>", "<|fim_prefix|>", "<|fim_middle|>", "<|fim_suffix|>", "<|endofprompt|>"],
)
def test_token_estimate_never_crashes_on_special_token_strings(special):
    """openai/gpt-2's source contains the literal "<|endoftext|>"; tiktoken's
    default encode() raised ValueError on it inside the budget pre-check and
    crashed live recon before any model call. The text must be counted as
    plain text and the call must go through."""
    from app.services.model_client import _estimate_tokens

    text = f'enc.encode(text, allowed_special={{"{special}"}})  # {special}'
    assert _estimate_tokens(text) > 0

    guard = CostGuard(daily_cost_ceiling_usd=100, max_tokens_per_attempt=10_000)
    client = _FakeClient('{"ok": true}')
    result = call_json_model(client, model="m", system_prompt=special, user_prompt=text, cost_guard=guard)
    assert result == {"ok": True}
    assert special in client.last_call["user_prompt"]


def test_token_estimate_counts_special_token_text_not_as_a_single_token():
    # Negative control: the estimate treats "<|endoftext|>" as ordinary
    # characters (several tokens), never as one special token id.
    from app.services.model_client import _estimate_tokens

    assert _estimate_tokens("<|endoftext|>") > 1


# --- Reasoning-model output handling: retry once on length, never use reasoning --


from types import SimpleNamespace  # noqa: E402


def _response(content, finish_reason, reasoning="thinking about it..."):
    message = SimpleNamespace(content=content, model_extra={"reasoning": reasoning, "reasoning_content": reasoning})
    return SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason=finish_reason)])


class _ScriptedOpenAI:
    """Stands in for openai.OpenAI: returns scripted responses and records
    every create() call's kwargs."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls: list[dict] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        return self._responses.pop(0)


def _nebius_client_with(monkeypatch, responses):
    fake = _ScriptedOpenAI(responses)
    client = NebiusChatClient(api_key="k", base_url="https://example.invalid/v1")
    monkeypatch.setattr(NebiusChatClient, "_client", lambda self: fake)
    return client, fake


def test_reasoning_budget_exhausted_retries_once_with_double_max_tokens(monkeypatch):
    client, fake = _nebius_client_with(monkeypatch, [_response(None, "length"), _response('{"ok": true}', "stop")])
    out = client.chat_completion(model="m", system_prompt="s", user_prompt="u", max_tokens=100)
    assert out == '{"ok": true}'
    assert [c["max_tokens"] for c in fake.calls] == [100, 200]


def test_empty_string_content_with_length_also_retries(monkeypatch):
    client, fake = _nebius_client_with(monkeypatch, [_response("   ", "length"), _response("answer", "stop")])
    assert client.chat_completion(model="m", system_prompt="s", user_prompt="u", max_tokens=50) == "answer"
    assert len(fake.calls) == 2


def test_still_empty_after_retry_raises_model_budget_error_and_never_returns_reasoning(monkeypatch):
    from app.services.model_client import ModelBudgetError

    client, fake = _nebius_client_with(
        monkeypatch,
        [_response(None, "length", reasoning='{"ok": true}'), _response(None, "length", reasoning='{"ok": true}')],
    )
    with pytest.raises(ModelBudgetError) as excinfo:
        client.chat_completion(model="m", system_prompt="s", user_prompt="u", max_tokens=64)
    assert len(fake.calls) == 2  # exactly one retry, never a loop
    assert "128" in str(excinfo.value)


def test_negative_control_empty_content_without_length_is_not_retried(monkeypatch):
    from app.services.model_client import ModelBudgetError

    client, fake = _nebius_client_with(monkeypatch, [_response(None, "stop")])
    with pytest.raises(ModelCallError) as excinfo:
        client.chat_completion(model="m", system_prompt="s", user_prompt="u", max_tokens=64)
    assert not isinstance(excinfo.value, ModelBudgetError)
    assert len(fake.calls) == 1


def test_negative_control_answer_on_first_try_makes_one_call(monkeypatch):
    client, fake = _nebius_client_with(monkeypatch, [_response("answer", "stop")])
    assert client.chat_completion(model="m", system_prompt="s", user_prompt="u", max_tokens=64) == "answer"
    assert len(fake.calls) == 1


def test_model_budget_error_is_a_model_call_error_so_callers_fall_back():
    from app.services.model_client import ModelBudgetError

    assert issubclass(ModelBudgetError, ModelCallError)


def test_model_budget_error_in_recon_becomes_recon_model_error(monkeypatch):
    """End to end through recon: a budget-exhausted Nano call is RERUN's own
    failure (RECON_MODEL_ERROR), never ENTRYPOINT_UNCLEAR, and never a guess
    built from the reasoning text."""
    from pathlib import Path

    from app.services.intake import RepoIntake
    from app.services.recon import RECON_MAX_TOKENS, RECON_MODEL_ERROR, run_recon

    client, fake = _nebius_client_with(monkeypatch, [_response(None, "length"), _response(None, "length")])
    intake = RepoIntake(
        local_path=Path("/fake"),
        commit_sha="a" * 40,
        dependency_files={},
        declared_dependencies=frozenset(),
        notebook_paths=(),
        entrypoint_candidates=("train.py",),
        python_version_hint=None,
    )
    result = run_recon(client, "nano", intake)
    assert result.is_indeterminate
    assert result.indeterminate_code == RECON_MODEL_ERROR
    assert [c["max_tokens"] for c in fake.calls] == [RECON_MAX_TOKENS, 2 * RECON_MAX_TOKENS]


def test_every_role_passes_an_explicit_max_tokens():
    from app.services import adjudicator, planner, recon, repairer

    assert recon.RECON_MAX_TOKENS > 0
    assert planner.PLANNER_MAX_TOKENS > 0
    assert repairer.REPAIR_MAX_TOKENS > 0
    assert adjudicator.ADJUDICATOR_MAX_TOKENS > 0
