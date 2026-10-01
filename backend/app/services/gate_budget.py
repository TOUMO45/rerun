"""Gate budget rules (harness-v1.4.0-rc): what a pre-registered gate may spend, decided before any entry runs.

Two rules, from the v1.4.0 Step 0 budget note (docs/design/v1.4.0-budget.md, finding 2):
  - a gate is refused when its cap is below `n_entries x entry cap`: in the harness-v1.3.4 gate the last entry (corpus-v2 #08) inherited
    what was left of the gate cap ($0.7819 of a $2.00 entry cap) and was starved whatever the harness did;
  - every entry runs with the SAME fixed entry cap; an entry whose cap no longer fits in what is left of the gate cap is not started
    (the gate stops and says so), instead of being started with a smaller one.

And one estimator, for planning only (ESTIMATED, never a measurement): under "install once, branch per attempt" an entry pays the
as-published baseline, ONE checkpoint build (the only operation that installs torch, outside the baseline), and then branch runs and
runner-hook suffixes that install nothing that is already in the image. Pure arithmetic: no network, no model call.
"""

from __future__ import annotations

from dataclasses import dataclass, field

EPS = 1e-9


class GateBudgetError(ValueError):
    """The gate's caps are inconsistent, or the next entry cannot get its full cap: nothing is started."""


def check_gate_caps(gate_cap_usd: float, entry_cap_usd: float, n_entries: int) -> None:
    """Refuse a gate whose cap cannot fund every entry's full cap (gate >= n_entries x entry)."""
    if entry_cap_usd <= 0 or gate_cap_usd <= 0 or n_entries <= 0:
        raise GateBudgetError(f"caps and entry count must be positive (gate ${gate_cap_usd}, entry ${entry_cap_usd}, {n_entries} entries)")
    needed = n_entries * entry_cap_usd
    if gate_cap_usd + EPS < needed:
        raise GateBudgetError(
            f"gate cap ${gate_cap_usd:.2f} is below {n_entries} x the ${entry_cap_usd:.2f} entry cap (${needed:.2f}): the entries run last "
            "would inherit a starved cap (harness-v1.3.4 gate, entry 8). Raise the gate cap or lower the entry cap."
        )


def entry_cap_for(gate_cap_usd: float, entry_cap_usd: float, spent_usd: float) -> float:
    """The cap the next entry runs with: always the fixed entry cap. Raises if what is left of the gate cap cannot cover it."""
    left = gate_cap_usd - spent_usd
    if left + EPS < entry_cap_usd:
        raise GateBudgetError(
            f"${spent_usd:.4f} spent of the ${gate_cap_usd:.2f} gate cap leaves ${left:.4f}, below the fixed ${entry_cap_usd:.2f} entry cap: "
            "the next entry is not started with a smaller cap"
        )
    return entry_cap_usd


@dataclass(frozen=True)
class PlannedOperation:
    kind: str  # "baseline" | "checkpoint" | "branch" | "hook"
    usd: float
    installs_torch: bool


@dataclass(frozen=True)
class EntryPlan:
    label: str
    operations: tuple[PlannedOperation, ...]
    model_usd: float = 0.0
    entry_cap_usd: float | None = None

    @property
    def torch_installs(self) -> int:
        """Torch installs criterion (e) counts: every operation but the as-published baseline (counted separately, outside (e))."""
        return sum(1 for op in self.operations if op.installs_torch and op.kind != "baseline")

    @property
    def usd(self) -> float:
        total = sum(op.usd for op in self.operations) + self.model_usd
        return min(total, self.entry_cap_usd) if self.entry_cap_usd is not None else total

    @property
    def clipped(self) -> bool:
        return self.entry_cap_usd is not None and sum(op.usd for op in self.operations) + self.model_usd > self.entry_cap_usd + EPS


def plan_entry(label: str, *, baseline_usd: float, checkpoint_usd: float, branch_usd: float, rounds: int = 3,
               candidates: int = 3, adopted_per_round: int = 0, hook_ops: int = 0, model_usd: float = 0.0,
               entry_cap_usd: float | None = None, torch: bool = True) -> EntryPlan:
    """An entry under "install once, branch per attempt": one baseline, ONE checkpoint build (installs torch when the entry needs it),
    `rounds x candidates` branch runs, `hook_ops` runner-hook suffixes (branch-priced: they install a small module on top), and
    `adopted_per_round` extra branch runs per round if the plan re-runs the chosen candidate (0 = the winner's own run is adopted)."""
    ops = [PlannedOperation("baseline", baseline_usd, torch), PlannedOperation("checkpoint", checkpoint_usd, torch)]
    ops += [PlannedOperation("hook", branch_usd, False) for _ in range(hook_ops)]
    ops += [PlannedOperation("branch", branch_usd, False) for _ in range(rounds * (candidates + adopted_per_round))]
    return EntryPlan(label, tuple(ops), model_usd, entry_cap_usd)


@dataclass(frozen=True)
class GateEstimate:
    entries: tuple[EntryPlan, ...]
    seal_usd: float = 0.0
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def gate_usd(self) -> float:
        return sum(e.usd for e in self.entries)

    @property
    def total_usd(self) -> float:
        return self.gate_usd + self.seal_usd

    def as_dict(self) -> dict:
        return {
            "tag": "ESTIMATED",
            "entries": [{"label": e.label, "usd": round(e.usd, 4), "clipped_at_entry_cap": e.clipped, "torch_installs": e.torch_installs,
                         "operations": len(e.operations)} for e in self.entries],
            "gate_usd": round(self.gate_usd, 4),
            "seal_usd": round(self.seal_usd, 4),
            "total_usd": round(self.total_usd, 4),
            "notes": list(self.notes),
        }


def estimate_gate(entries: list[EntryPlan], *, seal_usd: float = 0.0, gate_cap_usd: float | None = None,
                  entry_cap_usd: float | None = None) -> GateEstimate:
    """The planning estimate of a gate. When caps are given the gate-cap rule is applied first (an inconsistent gate is refused)."""
    if gate_cap_usd is not None and entry_cap_usd is not None:
        check_gate_caps(gate_cap_usd, entry_cap_usd, len(entries))
    notes = []
    for e in entries:
        if e.torch_installs > 1:
            notes.append(f"{e.label}: {e.torch_installs} torch installs outside the baseline; the plan breaks 'install once'")
    return GateEstimate(tuple(entries), seal_usd, tuple(notes))
