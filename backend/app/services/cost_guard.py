"""Cost guard (RERUN directive §9).

PURE arithmetic/state bookkeeping — no network, no model call. Enforces a
hard daily cost ceiling on model + sandbox spend, and per-run token/attempt
caps, *in code*, not just in documentation. Every model call and every
sandbox-second the orchestrator wants to spend must be checked against a
`CostGuard` instance first; a denial must actually stop the caller, not
just log a warning.

This module tracks spend in-process for a single guard instance. The
orchestrator is responsible for persisting/loading the day's running total
across process restarts (e.g. via the SQLite store) if that durability is
needed — this module only owns the arithmetic and the refusal decision.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


class CostLimitExceeded(RuntimeError):
    """Raised when a spend request would exceed a configured ceiling."""


@dataclass
class CostGuard:
    daily_cost_ceiling_usd: float
    max_attempts_per_run: int = 3
    max_tokens_per_attempt: int = 20_000
    _today: date = field(default_factory=date.today, repr=False)
    _spent_today_usd: float = field(default=0.0, repr=False)
    _attempts_by_run: dict[str, int] = field(default_factory=dict, repr=False)

    def _roll_day_if_needed(self) -> None:
        current = date.today()
        if current != self._today:
            self._today = current
            self._spent_today_usd = 0.0

    @property
    def spent_today_usd(self) -> float:
        self._roll_day_if_needed()
        return self._spent_today_usd

    @property
    def remaining_today_usd(self) -> float:
        return max(self.daily_cost_ceiling_usd - self.spent_today_usd, 0.0)

    def check_daily_budget(self, estimated_cost_usd: float) -> None:
        """Raise CostLimitExceeded if spending `estimated_cost_usd` more
        would breach the daily ceiling. Does not record the spend — call
        `record_spend` only after the call/sandbox time actually happened.
        """
        self._roll_day_if_needed()
        if self._spent_today_usd + estimated_cost_usd > self.daily_cost_ceiling_usd:
            raise CostLimitExceeded(
                f"daily cost ceiling would be exceeded: "
                f"${self._spent_today_usd:.4f} spent + ${estimated_cost_usd:.4f} "
                f"requested > ${self.daily_cost_ceiling_usd:.4f} ceiling"
            )

    def record_spend(self, actual_cost_usd: float) -> None:
        self._roll_day_if_needed()
        self._spent_today_usd += actual_cost_usd

    def check_attempt_budget(self, run_id: str) -> None:
        """Raise CostLimitExceeded if `run_id` has already used its full
        repair-attempt budget (§5.4: max 3 attempts total, regardless of
        PASS/REJECT outcome)."""
        used = self._attempts_by_run.get(run_id, 0)
        if used >= self.max_attempts_per_run:
            raise CostLimitExceeded(
                f"run '{run_id}' has already used {used}/{self.max_attempts_per_run} "
                f"repair attempts"
            )

    def record_attempt(self, run_id: str) -> int:
        """Record that `run_id` consumed one repair attempt (whether the
        tamper gate PASSed or REJECTed it — both consume the ceiling per
        §5.4). Returns the new attempt count."""
        self.check_attempt_budget(run_id)
        self._attempts_by_run[run_id] = self._attempts_by_run.get(run_id, 0) + 1
        return self._attempts_by_run[run_id]

    def attempts_used(self, run_id: str) -> int:
        return self._attempts_by_run.get(run_id, 0)

    def check_token_budget(self, requested_tokens: int) -> None:
        if requested_tokens > self.max_tokens_per_attempt:
            raise CostLimitExceeded(
                f"requested {requested_tokens} tokens exceeds the "
                f"{self.max_tokens_per_attempt}-token per-attempt ceiling"
            )
