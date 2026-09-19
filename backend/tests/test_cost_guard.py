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
