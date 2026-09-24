"""Tests for cost_guard.py (§9): the daily spend ceiling and per-run attempt
cap must actually stop the caller, not just log a warning."""

from __future__ import annotations

import pytest

from app.services.cost_guard import CostGuard, CostLimitExceeded


def test_daily_budget_allows_spend_under_ceiling():
    guard = CostGuard(daily_cost_ceiling_usd=10.0)
    guard.check_daily_budget(5.0)  # must not raise
    guard.record_spend(5.0)
    assert guard.spent_today_usd == 5.0
    assert guard.remaining_today_usd == 5.0


def test_daily_budget_rejects_spend_over_ceiling():
    guard = CostGuard(daily_cost_ceiling_usd=10.0)
    guard.record_spend(9.0)
    with pytest.raises(CostLimitExceeded):
        guard.check_daily_budget(2.0)


def test_daily_budget_negative_control_exact_ceiling_is_allowed():
    # Spending exactly up to the ceiling (not over it) must be permitted.
    guard = CostGuard(daily_cost_ceiling_usd=10.0)
    guard.check_daily_budget(10.0)  # must not raise


def test_attempt_budget_allows_up_to_max_attempts():
    guard = CostGuard(daily_cost_ceiling_usd=100.0, max_attempts_per_run=3)
    for _ in range(3):
        guard.check_attempt_budget("run-1")
        guard.record_attempt("run-1")
    assert guard.attempts_used("run-1") == 3


def test_attempt_budget_rejects_fourth_attempt():
    guard = CostGuard(daily_cost_ceiling_usd=100.0, max_attempts_per_run=3)
    for _ in range(3):
        guard.record_attempt("run-1")
    with pytest.raises(CostLimitExceeded):
        guard.check_attempt_budget("run-1")
    with pytest.raises(CostLimitExceeded):
        guard.record_attempt("run-1")


def test_attempt_budget_is_per_run_not_global():
    # A different run must not be blocked by another run's exhausted budget.
    guard = CostGuard(daily_cost_ceiling_usd=100.0, max_attempts_per_run=3)
    for _ in range(3):
        guard.record_attempt("run-1")
    guard.check_attempt_budget("run-2")  # must not raise
    assert guard.attempts_used("run-2") == 0


def test_attempt_counts_rejected_gate_outcomes_too():
    # §5.4: a tamper-gate REJECT still consumes an attempt — the guard only
    # tracks "was an attempt made", not whether it passed the gate. This is
    # the caller's responsibility to invoke record_attempt() on REJECT too;
    # this test just proves the counter itself doesn't distinguish.
    guard = CostGuard(daily_cost_ceiling_usd=100.0, max_attempts_per_run=3)
    guard.record_attempt("run-1")  # simulating a REJECT
    guard.record_attempt("run-1")  # simulating a REJECT
    guard.record_attempt("run-1")  # simulating a PASS
    assert guard.attempts_used("run-1") == 3
    with pytest.raises(CostLimitExceeded):
        guard.record_attempt("run-1")


def test_token_budget_allows_under_ceiling():
    guard = CostGuard(daily_cost_ceiling_usd=100.0, max_tokens_per_attempt=1000)
    guard.check_token_budget(999)  # must not raise


def test_token_budget_rejects_over_ceiling():
    guard = CostGuard(daily_cost_ceiling_usd=100.0, max_tokens_per_attempt=1000)
    with pytest.raises(CostLimitExceeded):
        guard.check_token_budget(1001)


# --- Model spend (priced from Token Factory's own /v1/models pricing) -------


def test_record_model_usage_prices_tokens_and_adds_to_the_daily_total():
    guard = CostGuard(daily_cost_ceiling_usd=10, model_prices_usd_per_1m={"super": (0.30, 0.90)})
    cost = guard.record_model_usage("super", prompt_tokens=1_000_000, completion_tokens=2_000_000)
    assert cost == pytest.approx(0.30 + 1.80)
    assert guard.spent_today_usd == pytest.approx(2.10)
    assert guard.model_spent_usd == pytest.approx(2.10) and guard.sandbox_spent_usd == 0


def test_unpriced_model_is_recorded_but_never_guessed():
    guard = CostGuard(daily_cost_ceiling_usd=10)
    assert guard.record_model_usage("unknown/model", 100, 100) is None
    assert guard.spent_today_usd == 0
    assert guard.model_usage == [{"model": "unknown/model", "prompt_tokens": 100, "completion_tokens": 100, "cost_usd": None}]


def test_shared_guard_uses_the_configured_price_table():
    from app.config import get_settings
    from app.services.cost_guard import get_shared_cost_guard

    get_shared_cost_guard.cache_clear()
    guard = get_shared_cost_guard()
    assert guard.model_prices_usd_per_1m == dict(get_settings().model_prices_usd_per_1m)
    assert guard.model_prices_usd_per_1m["nvidia/nemotron-3-super-120b-a12b"] == (0.30, 0.90)
    get_shared_cost_guard.cache_clear()


def test_call_json_model_records_usage_including_the_budget_retry(monkeypatch):
    from types import SimpleNamespace

    from app.services.model_client import NebiusChatClient, call_json_model

    def _resp(content, finish, p, c):
        msg = SimpleNamespace(content=content, model_extra={})
        return SimpleNamespace(
            choices=[SimpleNamespace(message=msg, finish_reason=finish)],
            usage=SimpleNamespace(prompt_tokens=p, completion_tokens=c),
        )

    responses = [_resp(None, "length", 1000, 100), _resp('{"ok": true}', "stop", 1000, 150)]
    fake = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **kw: responses.pop(0))))
    client = NebiusChatClient(api_key="k", base_url="https://example.invalid/v1")
    monkeypatch.setattr(NebiusChatClient, "_client", lambda self: fake)
    guard = CostGuard(daily_cost_ceiling_usd=10, model_prices_usd_per_1m={"m": (1.0, 2.0)})

    assert call_json_model(client, model="m", system_prompt="s", user_prompt="u", cost_guard=guard, max_tokens=100) == {"ok": True}
    assert [u["completion_tokens"] for u in guard.model_usage] == [100, 150]  # both paid responses
    assert guard.model_spent_usd == pytest.approx((2000 * 1.0 + 250 * 2.0) / 1_000_000)


def test_exhausted_daily_budget_refuses_a_model_call_before_the_network():
    from app.services.model_client import ModelCostLimitError, call_json_model

    class _Exploding:
        def chat_completion(self, **kwargs):
            raise AssertionError("must not be called")

    guard = CostGuard(daily_cost_ceiling_usd=1.0)
    guard.record_spend(1.0)
    with pytest.raises(ModelCostLimitError):
        call_json_model(_Exploding(), model="m", system_prompt="s", user_prompt="u", cost_guard=guard)
