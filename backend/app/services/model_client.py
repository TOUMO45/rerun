"""Shared Nebius Token Factory inference client (§4.1: OpenAI-compatible API).

This is the ONLY place `openai.OpenAI(...)` gets constructed. Every
model-calling service (`recon.py`, `planner.py`, `repairer.py`,
`adjudicator.py`) takes a client as a constructor/function argument rather
than building its own — that's what makes `call_json_model`'s parsing
logic testable without a live API key: tests inject a fake client that
mimics `client.chat.completions.create(...).choices[0].message.content`
without touching the network.

Ground truth for the constructor and `chat.completions.create` signature
was read from the installed `openai` package
(`openai.OpenAI.__init__`, `openai.resources.chat.completions.completions.Completions.create`),
not guessed.

`call_json_model` is also the single chokepoint for §9's per-attempt token
ceiling (`cost_guard.CostGuard.check_token_budget`) — every caller gets
this for free rather than needing to remember to check it themselves. The
token count is an *estimate* (via `tiktoken`'s `cl100k_base` encoding,
counted over the combined system+user prompt) since Nemotron's own
tokenizer isn't available locally — good enough for a circuit-breaker
against a runaway prompt, not a billing-accurate count.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol

import tiktoken
from openai import OpenAI

from app.services.cost_guard import CostGuard, CostLimitExceeded

_ENCODING = None  # lazy singleton; loading the encoding table isn't free


def _estimate_tokens(text: str) -> int:
    global _ENCODING
    if _ENCODING is None:
        _ENCODING = tiktoken.get_encoding("cl100k_base")
    # disallowed_special=(): repo source is untrusted text and routinely
    # contains special-token strings (gpt-2's own code has the literal
    # "<|endoftext|>"). tiktoken's default *raises* on those, which crashed
    # the first live run inside this budget pre-check. Counting them as
    # ordinary text is also the honest estimate: that is how they are sent.
    return len(_ENCODING.encode(text, disallowed_special=()))


class ModelCallError(RuntimeError):
    pass


class ModelCredentialsError(ModelCallError):
    pass


class ModelResponseParseError(ModelCallError):
    """The model responded, but its content wasn't valid JSON matching what
    the caller asked for. Callers must treat this as a reason to fall back
    (e.g. §6.1 INDETERMINATE), never as a reason to guess."""


class ModelBudgetError(ModelCallError):
    """A reasoning model spent its whole output budget thinking and never
    produced an answer (`content` empty, `finish_reason == "length"`), even
    after one retry with double the budget. A ModelCallError subclass, so
    every caller's existing fallback applies (recon -> INDETERMINATE
    RECON_MODEL_ERROR, planner -> deterministic plan, repairer -> declined,
    adjudicator -> templated prose). The model's `reasoning` text is never
    used as a substitute answer."""


class ModelCostLimitError(ModelCallError):
    """The prompt's estimated token count would exceed cost_guard's
    per-attempt ceiling. Deliberately a ModelCallError subclass so every
    existing caller's `except ModelCallError:` fallback (§6.1
    INDETERMINATE, a declined repair proposal, templated adjudicator
    prose) already handles this correctly with zero extra code — a
    cost-guard trip must never crash the pipeline."""


class _ChatClientLike(Protocol):
    """The minimal surface every service actually uses — real `OpenAI()`
    satisfies this, and tests can inject a tiny fake satisfying just this."""

    def chat_completion(
        self, *, model: str, system_prompt: str, user_prompt: str, temperature: float, max_tokens: int | None = None
    ) -> str: ...


@dataclass(frozen=True)
class NebiusChatClient:
    """Thin, real wrapper around `openai.OpenAI` pointed at Nebius Token
    Factory. Exists so call sites depend on one small method
    (`chat_completion`) instead of the full OpenAI SDK surface."""

    api_key: str
    base_url: str

    def __post_init__(self):
        if not self.api_key:
            raise ModelCredentialsError(
                "NEBIUS_API_KEY is not set — cannot call Token Factory inference. "
                "Populate .env from .env.example first."
            )

    def _client(self) -> OpenAI:
        return OpenAI(api_key=self.api_key, base_url=self.base_url)

    def chat_completion(
        self,
        *,
        model: str,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> str:
        """Nemotron 3 on Token Factory are reasoning models: chain-of-thought
        arrives in `message.model_extra["reasoning"/"reasoning_content"]` and
        the answer in `message.content` only after reasoning ends (verified
        live, DECISIONS.md 2026-09-23). If the budget runs out mid-reasoning
        (`content` empty + `finish_reason == "length"`), retry once with
        double `max_tokens`; if still empty, raise ModelBudgetError. The
        reasoning field is never returned as the answer."""
        client = self._client()
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        budget = max_tokens
        for attempt in (1, 2):
            kwargs = {"model": model, "messages": messages, "temperature": temperature}
            if budget is not None:
                kwargs["max_tokens"] = budget
            response = client.chat.completions.create(**kwargs)
            choice = response.choices[0]
            content = choice.message.content
            if content and content.strip():
                return content
            if choice.finish_reason != "length":
                raise ModelCallError(
                    f"model '{model}' returned an empty message content (finish_reason={choice.finish_reason!r})"
                )
            if attempt == 1 and budget is not None:
                budget *= 2
                continue
            break
        raise ModelBudgetError(
            f"model '{model}' used its whole output budget (max_tokens={budget}) without producing an answer "
            "(finish_reason='length', content empty) — reasoning never finished"
        )


def call_json_model(
    client: _ChatClientLike,
    *,
    model: str,
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.0,
    cost_guard: CostGuard | None = None,
    max_tokens: int | None = None,
) -> dict[str, Any]:
    """Call a model expected to answer with a single JSON object, and parse
    it. Raises ModelResponseParseError (never guesses / never returns a
    partially-parsed dict) if the response isn't valid JSON — callers
    (recon.py in particular) are expected to treat that as grounds for
    §6.1's INDETERMINATE, not as a crash.

    If `cost_guard` is supplied, the prompt's estimated token count is
    checked against its per-attempt ceiling *before* the network call is
    made — refusing to spend on a call that's already known to be too
    large, rather than checking only after the fact.
    """
    if cost_guard is not None:
        estimated_tokens = _estimate_tokens(system_prompt) + _estimate_tokens(user_prompt)
        try:
            cost_guard.check_token_budget(estimated_tokens)
        except CostLimitExceeded as exc:
            raise ModelCostLimitError(
                f"prompt estimated at {estimated_tokens} tokens exceeds the per-attempt ceiling: {exc}"
            ) from exc

    # max_tokens is only forwarded when set, so minimal fakes/clients that
    # predate it keep working unchanged.
    extra = {"max_tokens": max_tokens} if max_tokens is not None else {}
    raw = client.chat_completion(
        model=model,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        temperature=temperature,
        **extra,
    )
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ModelResponseParseError(f"model response was not valid JSON: {exc}\n---\n{raw[:2000]}") from exc
    if not isinstance(parsed, dict):
        raise ModelResponseParseError(f"model response was valid JSON but not a JSON object: {type(parsed).__name__}")
    return parsed
