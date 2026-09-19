"""Tests for the shared model-call/JSON-parsing plumbing.

No live Nebius call — `call_json_model` is tested against a fake client
satisfying `_ChatClientLike`'s single-method surface, so the parsing logic
(the part this codebase actually controls) is fully verified without a
network dependency. `NebiusChatClient`'s own fail-fast credential check is
tested directly.
"""

from __future__ import annotations

import pytest

from app.services.model_client import (
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
