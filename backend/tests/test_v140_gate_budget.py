"""harness-v1.4.0-rc: gate budget rules and the planning estimator (offline, pure)."""

from __future__ import annotations

import pytest

from app.services import gate_budget as gb


def test_the_estimator_refuses_a_gate_whose_cap_is_below_four_entry_caps():
    with pytest.raises(gb.GateBudgetError, match="starved"):
        gb.check_gate_caps(4.99, 1.25, 4)
    gb.check_gate_caps(5.00, 1.25, 4)  # the owner's proposed shape: gate $5.00, entry $1.25 x 4
    with pytest.raises(gb.GateBudgetError):
        gb.estimate_gate([gb.plan_entry(f"#{i}", baseline_usd=0.3, checkpoint_usd=0.35, branch_usd=0.01) for i in range(4)],
                         gate_cap_usd=3.5, entry_cap_usd=2.0)  # the harness-v1.3.4 gate's own caps: refused


def test_the_v134_starvation_cannot_happen_an_entry_gets_its_full_cap_or_is_not_started():
    assert gb.entry_cap_for(5.0, 1.25, spent_usd=3.75) == 1.25
    with pytest.raises(gb.GateBudgetError, match="not started"):
        gb.entry_cap_for(3.5, 2.0, spent_usd=2.7181)  # v1.3.4: $3.5 gate, $2.7181 spent before entry 8 -> it got $0.7819


def test_the_cost_estimator_uses_one_install_per_entry():
    plans = [gb.plan_entry(f"#{i}", baseline_usd=0.32, checkpoint_usd=0.35, branch_usd=0.0011, rounds=3, candidates=3, hook_ops=1,
                           entry_cap_usd=1.25) for i in (3, 7, 8, 11)]
    estimate = gb.estimate_gate(plans, gate_cap_usd=5.0, entry_cap_usd=1.25)
    assert [p.torch_installs for p in plans] == [1, 1, 1, 1]
    assert all(e["torch_installs"] == 1 for e in estimate.as_dict()["entries"])
    assert sum(op.installs_torch for op in plans[0].operations) == 2  # baseline (outside (e)) + the one checkpoint build
    assert not estimate.notes and estimate.as_dict()["tag"] == "ESTIMATED"
    assert plans[0].usd == pytest.approx(0.32 + 0.35 + 10 * 0.0011)


def test_entries_are_clipped_at_their_cap_and_a_plan_that_reinstalls_is_flagged():
    clipped = gb.plan_entry("#8", baseline_usd=0.32, checkpoint_usd=0.63, branch_usd=0.38, entry_cap_usd=1.25)
    assert clipped.usd == 1.25 and clipped.clipped
    reinstall = gb.EntryPlan("#11", (gb.PlannedOperation("baseline", 0.3, True), gb.PlannedOperation("checkpoint", 0.3, True),
                                      gb.PlannedOperation("branch", 0.3, True)))
    assert gb.estimate_gate([reinstall]).notes
