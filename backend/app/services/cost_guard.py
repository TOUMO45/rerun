"""Cost guard (RERUN directive §9).

PURE arithmetic/state bookkeeping — no network, no model call. Enforces a
hard daily USD cost ceiling, a per-run repair-attempt ceiling, and a
per-attempt token ceiling, *in code*, not just in documentation. A denial
must actually stop the caller, not just log a warning.

This module tracks spend in-process for a single guard instance. The
orchestrator is responsible for persisting/loading the day's running total
across process restarts (e.g. via the SQLite store) if that durability is
needed — this module only owns the arithmetic and the refusal decision.

**Update 2026-09-24:** model spend IS now counted. Token Factory's own
`/v1/models?verbose=true` exposes per-token prices (config
`model_prices_usd_per_1m`); `NebiusChatClient` records each response's
`usage`, and `call_json_model` calls `record_model_usage`, which adds the
priced cost to the same daily total and refuses further model calls once
the ceiling is reached. The paragraph below describes the earlier state.

**Corrected, found live during this session's audit (see DECISIONS.md):**
this docstring previously claimed the daily USD ceiling covers "model +
sandbox spend." It doesn't. `record_spend`/`check_daily_budget` are only
ever called from `orchestrator.py` for real, measured *sandbox* cost
(`ContreeResult.cost`, a real number the SDK returns). Every Nemotron
model call (recon, planner, up to `max_attempts_per_run` repairer calls,
adjudicator) is bounded only by `check_token_budget` — a per-call TOKEN
COUNT ceiling, not a USD cost tracked against the daily total — because
no per-token USD pricing for these models exists anywhere in this
codebase to convert one into the other, and fabricating a pricing table
without a verified source would be worse than leaving this honestly
documented. A run with heavy, repeated model usage and zero/cheap sandbox
time is not actually capped by `daily_cost_ceiling_usd` at all today.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from functools import lru_cache

from app.config import get_settings


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
    # model id -> (input, output) USD per 1M tokens. Empty = nothing priced.
    model_prices_usd_per_1m: dict = field(default_factory=dict, repr=False)
    # Every model call's usage and priced cost (None when unpriced), for the
    # run record. Also sums sandbox vs model spend separately.
    model_usage: list = field(default_factory=list, repr=False)
    model_spent_usd: float = field(default=0.0, repr=False)
    sandbox_spent_usd: float = field(default=0.0, repr=False)

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

        Known limitation, found live and documented rather than silently
        left (see DECISIONS.md): this check and `record_spend` are two
        separate calls with real, non-trivial work (a real sandbox run)
        happening in between. Reproduced with two real threads and a
        simulated delay: two concurrent runs can each pass this check
        before either calls `record_spend`, together exceeding the
        ceiling by up to one run's worth of spend. Closing this properly
        would need an atomic "reserve the estimate, then adjust once the
        real cost is known" pattern — not implementable for the sandbox
        spend path specifically, since there is no pre-flight cost quote
        to reserve (see orchestrator.py's `_execute`, which already
        passes `estimated_cost_usd=0.0` for exactly this reason). Judged
        an acceptable residual risk for §4.1's single-tenant, zero-ops
        deployment target, not silently ignored.
        """
        self._roll_day_if_needed()
        # `>=` for "nothing left": callers with no pre-flight quote pass an
        # estimate of 0.0, and `spent + 0 > ceiling` let them through when
        # spend was exactly AT the ceiling (found by a model-cost test).
        if (
            self._spent_today_usd >= self.daily_cost_ceiling_usd
            or self._spent_today_usd + estimated_cost_usd > self.daily_cost_ceiling_usd
        ):
            raise CostLimitExceeded(
                f"daily cost ceiling would be exceeded: "
                f"${self._spent_today_usd:.4f} spent + ${estimated_cost_usd:.4f} "
                f"requested > ${self.daily_cost_ceiling_usd:.4f} ceiling"
            )

    def record_spend(self, actual_cost_usd: float) -> None:
        """Sandbox spend (the SDK's measured per-run cost)."""
        self._roll_day_if_needed()
        self._spent_today_usd += actual_cost_usd
        self.sandbox_spent_usd += actual_cost_usd

    def record_model_usage(self, model: str, prompt_tokens: int, completion_tokens: int) -> float | None:
        """Price one model call from the configured table and add it to the
        daily total. Returns the cost, or None if the model is unpriced (the
        tokens are still recorded — never a guessed price)."""
        self._roll_day_if_needed()
        price = self.model_prices_usd_per_1m.get(model)
        cost = None
        if price is not None:
            cost = (prompt_tokens * price[0] + completion_tokens * price[1]) / 1_000_000
            self._spent_today_usd += cost
            self.model_spent_usd += cost
        self.model_usage.append(
            {"model": model, "prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens, "cost_usd": cost}
        )
        return cost

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


@lru_cache
def get_shared_cost_guard() -> CostGuard:
    """The one `CostGuard` instance the whole app shares for the process's
    lifetime — a *daily* ceiling means nothing if every caller constructs
    its own fresh guard (this module's docstring always said callers must
    keep "a single guard instance"; nothing did until this function
    existed, per DECISIONS.md). `lru_cache` gives a process-wide singleton
    the same way `app.config.get_settings()` already does. This is
    sufficient for the directive's fixed single-tenant, zero-ops SQLite
    deployment (§4.1) — a multi-process/multi-worker deployment would need
    the running total persisted somewhere shared (e.g. the SQLite store),
    which is out of scope here and would be a real, separate piece of work,
    not a one-line change.

    Tests that need isolation should call `get_shared_cost_guard.cache_clear()`
    (an `lru_cache`-provided method) between cases — see `conftest.py`.
    """
    settings = get_settings()
    return CostGuard(
        daily_cost_ceiling_usd=settings.daily_cost_ceiling_usd,
        max_attempts_per_run=settings.max_attempts_per_run,
        model_prices_usd_per_1m=dict(settings.model_prices_usd_per_1m),
    )
