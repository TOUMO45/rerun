"""Budget rules of the v1.5 dev/test protocol (METHODOLOGY, "harness-v1.5 dev/test protocol", rules B1-B4). Pure arithmetic plus a ledger reader; no network, no model call.

Ceilings are the owner's (API-reported dollars, the sandbox API's own cost; BILLED readings are the owner's balance readings and are kept beside, never mixed in):
  entry $1.50, DEV total $40.00, ledger $75.00. The ledger starts at $29.1704 (lower bound, D-27: reports/corpus-v2.1/v1.4.3/gate/GATE_REPORT_v1.4.3.md).

Two checks before every DEV round, both written down before round 1:
  HARD     the worst case of the round (8 entries x the $1.50 entry cap = $12.00) must fit under the DEV total and under the ledger ceiling;
  RESERVE  the central estimate of the round plus the TEST reserve must fit under the ledger ceiling, so that the TEST phase can be paid for (an owner-overridable guard: the
           owner raises the ledger ceiling in chat, or accepts the freeze).
The TEST reserve = 8 entries x $0.9236 (the mean cost of the four v1.4.3 gate entries, API-reported) + 3 sustained checks x $6.24 (600 s x $0.0104 per sandbox second, the
rate in the v1.4.3 records), because the pre-registered target (3 of 8) needs three confirmed sustained runs.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

ENTRY_CAP_USD = 1.50
N_DEV = 8
ROUND_CAP_USD = round(N_DEV * ENTRY_CAP_USD, 2)  # 12.00: the worst case of one round
DEV_TOTAL_CAP_USD = 40.00
LEDGER_CEILING_USD = 75.00
LEDGER_BASE_USD = 29.1704
CENTRAL_ROUND_USD = 7.39  # 8 x 0.9236 (mean of the four v1.4.3 gate entries: 0.9435, 0.6735, 1.1742, 0.9032)
SUSTAINED_RUN_USD = 6.24  # 600 s x $0.0104 per sandbox second
TEST_TARGET = 3
TEST_RESERVE_USD = round(CENTRAL_ROUND_USD + TEST_TARGET * SUSTAINED_RUN_USD, 2)  # 26.11
EPS = 1e-9


@dataclass(frozen=True)
class Spend:
    """API-reported dollars spent by the v1.5 program so far, by kind. `estimated_usd` is the part of the total that is an estimate (a killed step: D-27)."""
    entries_usd: float = 0.0
    smoke_usd: float = 0.0
    extras_usd: float = 0.0
    estimated_usd: float = 0.0
    items: tuple[tuple[str, float], ...] = field(default_factory=tuple)

    @property
    def total_usd(self) -> float:
        return round(self.entries_usd + self.smoke_usd + self.extras_usd, 6)

    @property
    def api_reported_usd(self) -> float:
        return round(self.total_usd - self.estimated_usd, 6)


def read_spend(root: Path, exclude: Path | None = None) -> Spend:
    """What the v1.5 DEV program has spent, from the files on disk: every entry record under runs/corpus_v2_batch/harness-v1.5*/dev/ (cost_guard.spent_usd, which includes the
    estimate of a killed step), every pre-batch upload smoke record there, and the extras file (seals and anything else with a pointer to its record). `exclude` is a directory
    left out (the round being resumed: its own spend is what the round is about to continue, not a reason to refuse it)."""
    entries = smoke = estimated = 0.0
    items: list[tuple[str, float]] = []
    for path in sorted((root / "runs" / "corpus_v2_batch").glob("harness-v1.5*/dev/**/*.json*")):
        if exclude is not None and exclude in path.parents:
            continue
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        rel = path.relative_to(root).as_posix()
        if isinstance(doc.get("cost_guard"), dict) and isinstance(doc["cost_guard"].get("spent_usd"), (int, float)):
            usd = float(doc["cost_guard"]["spent_usd"])
            entries += usd
            estimated += float(doc["cost_guard"].get("estimated_sandbox_spent_usd") or 0.0)
            items.append((rel, usd))
        elif doc.get("kind") == "pre-batch upload smoke test":
            usd = sum(float(r.get("cost_usd") or 0.0) for r in doc.get("runs") or [])
            smoke += usd
            items.append((rel, usd))
    extras = 0.0
    extras_path = root / "reports" / "corpus-v2.1" / "v1.5" / "ledger_extras.json"
    if extras_path.is_file():
        for row in json.loads(extras_path.read_text(encoding="utf-8")).get("items", []):
            extras += float(row["usd"])
            estimated += float(row["usd"]) if row.get("estimated") else 0.0
            items.append((row["what"], float(row["usd"])))
    return Spend(round(entries, 6), round(smoke, 6), round(extras, 6), round(estimated, 6), tuple(items))


@dataclass(frozen=True)
class RoundGuard:
    ok: bool
    hard_ok: bool
    reserve_ok: bool
    reasons: tuple[str, ...]
    ledger_usd: float
    dev_spent_usd: float


def round_guard(spend: Spend, *, ledger_base_usd: float = LEDGER_BASE_USD, ledger_ceiling_usd: float = LEDGER_CEILING_USD,
                dev_total_cap_usd: float = DEV_TOTAL_CAP_USD, round_cap_usd: float = ROUND_CAP_USD, central_usd: float = CENTRAL_ROUND_USD,
                test_reserve_usd: float = TEST_RESERVE_USD) -> RoundGuard:
    """May another DEV round start? The ledger is the base plus everything the v1.5 DEV program has spent."""
    ledger = ledger_base_usd + spend.total_usd
    reasons: list[str] = []
    hard_ok = reserve_ok = True
    if spend.total_usd + round_cap_usd > dev_total_cap_usd + EPS:
        hard_ok = False
        reasons.append(f"HARD: DEV spent ${spend.total_usd:.4f} + a round's worst case ${round_cap_usd:.2f} passes the ${dev_total_cap_usd:.2f} DEV total")
    if ledger + round_cap_usd > ledger_ceiling_usd + EPS:
        hard_ok = False
        reasons.append(f"HARD: ledger ${ledger:.4f} + a round's worst case ${round_cap_usd:.2f} passes the ${ledger_ceiling_usd:.2f} ledger ceiling")
    if ledger + central_usd + test_reserve_usd > ledger_ceiling_usd + EPS:
        reserve_ok = False
        reasons.append(f"RESERVE: ledger ${ledger:.4f} + the round's central estimate ${central_usd:.2f} + the TEST reserve ${test_reserve_usd:.2f} "
                       f"passes the ${ledger_ceiling_usd:.2f} ledger ceiling (the TEST phase could not be paid for)")
    return RoundGuard(hard_ok and reserve_ok, hard_ok, reserve_ok, tuple(reasons), round(ledger, 6), spend.total_usd)
