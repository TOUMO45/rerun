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
