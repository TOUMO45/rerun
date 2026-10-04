"""Tests of the v1.5 dev/test protocol machinery: the split, the TEST firewall, the budget guard, the DEV round runner's pure parts and METHODOLOGY's pre-registration block.
Kept beside the code and not in backend/tests (the batch preflight refuses any file outside its data allowlist that changed since the sealed tag). Run with
`backend/.venv/Scripts/python.exe -m pytest reports/corpus-v2.1/v1.5/devtest/test_devtest.py -q`."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
sys.path.insert(0, str(HERE))

import budget  # noqa: E402
import firewall  # noqa: E402
import split  # noqa: E402


def _runner():
    spec = importlib.util.spec_from_file_location("run_dev_round", HERE.parent / "dev" / "run_dev_round.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# --- the split: the rule, recomputed independently ----------------------------------------------------------------------------------------------

def test_split_follows_the_written_rule_independently_recomputed():
    pool = [i for i in range(1, 21) if i not in (3, 7, 8, 11)]
    assert len(pool) == 16
    ordered = sorted(pool, key=lambda i: hashlib.sha256(str(i).encode("ascii")).hexdigest())
    assert split.split() == {"dev": sorted(ordered[0::2]), "test": sorted(ordered[1::2])}


def test_split_is_eight_and_eight_disjoint_and_leaves_the_gate_entries_out():
    parts = split.split()
    assert len(parts["dev"]) == len(parts["test"]) == 8
    assert not set(parts["dev"]) & set(parts["test"])
    assert not (set(parts["dev"]) | set(parts["test"])) & {3, 7, 8, 11}
    assert set(parts["dev"]) | set(parts["test"]) | {3, 7, 8, 11} == set(range(1, 21))


def test_the_dev_list_is_pinned():
    assert split.DEV_ENTRIES == (4, 5, 9, 12, 14, 15, 16, 17)


def test_methodology_pre_registers_exactly_the_computed_lists():
    text = (ROOT / "METHODOLOGY.md").read_text(encoding="utf-8")
    for key, want in (("DEV_ENTRIES", split.split()["dev"]), ("TEST_ENTRIES", split.split()["test"])):
        match = re.search(rf"^{key}:\s*\[([0-9, ]*)\]\s*$", text, flags=re.M)
        assert match, f"METHODOLOGY.md has no {key} line"
        assert [int(x) for x in match.group(1).replace(" ", "").split(",")] == want


# --- the firewall -------------------------------------------------------------------------------------------------------------------------------

def test_firewall_refuses_a_test_entry_before_the_freeze_and_lets_dev_and_gate_entries_through(monkeypatch):
    monkeypatch.delenv(firewall.FROZEN_ENV, raising=False)
    test_id = split.split()["test"][0]
    with pytest.raises(firewall.FirewallError):
        firewall.assert_not_test(test_id)
    for ok_id in (*split.DEV_ENTRIES, *split.GATE_ENTRIES):
        firewall.assert_not_test(ok_id)


def test_firewall_reads_the_entry_id_from_the_file_name_so_a_test_record_is_never_opened(monkeypatch, tmp_path):
    monkeypatch.delenv(firewall.FROZEN_ENV, raising=False)
    test_id = split.split()["test"][0]
    secret = tmp_path / f"{test_id:02d}_owner__repo.json"
    secret.write_text("OPENED", encoding="utf-8")
    assert firewall.entry_id_of(secret) == test_id
    assert not firewall.may_read_record(secret)
    with pytest.raises(firewall.FirewallError):
        firewall.read_record_text(secret)
    other = tmp_path / f"{split.DEV_ENTRIES[0]:02d}_owner__repo.json"
    other.write_text("fine", encoding="utf-8")
    assert firewall.read_record_text(other) == "fine"
    assert firewall.may_read_record(tmp_path / "round_summary.json")  # not an entry record
    monkeypatch.setenv(firewall.FROZEN_ENV, "1")
    assert firewall.read_record_text(secret) == "OPENED"


def test_analysis_records_lists_only_dev_and_gate_records(tmp_path, monkeypatch):
    monkeypatch.delenv(firewall.FROZEN_ENV, raising=False)
    d = tmp_path / "harness-v1.3.2" / "control"
    d.mkdir(parents=True)
    for i in range(1, 21):
        (d / f"{i:02d}_a__b.json").write_text("{}", encoding="utf-8")
    got = {firewall.entry_id_of(p) for p in firewall.analysis_records(tmp_path)}
    assert got == set(split.DEV_ENTRIES) | set(split.GATE_ENTRIES)


# --- the budget guard ----------------------------------------------------------------------------------------------------------------------------

def test_round_one_is_allowed_from_the_recorded_ledger():
    guard = budget.round_guard(budget.Spend())
    assert guard.ok and guard.ledger_usd == budget.LEDGER_BASE_USD and not guard.reasons


def test_the_dev_total_is_a_hard_check_on_a_rounds_worst_case():
    guard = budget.round_guard(budget.Spend(entries_usd=20.50))  # harness-v1.7: the worst case is 8 x $2.50 = $20.00 (was $12.00, threshold $28.00)
    assert not guard.hard_ok and any("DEV total" in r for r in guard.reasons)
    assert budget.round_guard(budget.Spend(entries_usd=19.99), ledger_ceiling_usd=200.0).hard_ok
    # the owner's DEV total, written in chat, is what the runner passes (rule B4); round 5 after round 4's $23.7632 needs at least $43.77
    assert not budget.round_guard(budget.Spend(entries_usd=23.7632), ledger_ceiling_usd=100.0).hard_ok
    assert budget.round_guard(budget.Spend(entries_usd=23.7632), ledger_ceiling_usd=100.0, dev_total_cap_usd=50.0).ok


def test_the_ledger_ceiling_is_a_hard_check_on_a_rounds_worst_case():
    guard = budget.round_guard(budget.Spend(entries_usd=34.0))  # ledger 63.17 + 12.00 > 75
    assert not guard.hard_ok and any("ledger ceiling" in r for r in guard.reasons)


def test_the_test_reserve_refuses_a_round_that_would_leave_no_money_for_the_test_phase():
    guard = budget.round_guard(budget.Spend(entries_usd=15.0))  # ledger 44.17 + 7.39 + 26.11 > 75 (hard checks fine)
    assert guard.hard_ok and not guard.reserve_ok and not guard.ok
    assert any("TEST reserve" in r for r in guard.reasons)
    assert budget.round_guard(budget.Spend(entries_usd=15.0), ledger_ceiling_usd=100.0).ok  # the owner raising the ceiling is the way out


def test_the_central_estimate_and_the_reserve_come_from_the_recorded_costs():
    gate = [0.94354533, 0.6735389700000002, 1.1742299299999996, 0.90323577]
    assert round(8 * sum(gate) / 4, 2) == budget.CENTRAL_ROUND_USD
    assert budget.TEST_RESERVE_USD == round(budget.CENTRAL_ROUND_USD + 3 * 600 * 0.0104, 2) == 26.11
    assert budget.ROUND_CAP_USD == 20.00  # harness-v1.7: 8 x the owner's $2.50 entry cap (was 8 x $1.50 = $12.00 through round 4)


def test_read_spend_sums_entry_records_smoke_tests_and_extras_and_can_exclude_a_round(tmp_path):
    dev = tmp_path / "runs" / "corpus_v2_batch" / "harness-v1.5.0" / "dev"
    dev.mkdir(parents=True)
    (dev / "04_a__b.json").write_text(json.dumps({"cost_guard": {"spent_usd": 1.0, "estimated_sandbox_spent_usd": 0.25}}), encoding="utf-8")
    (dev / "upload_smoke_x.json").write_text(json.dumps({"kind": "pre-batch upload smoke test", "runs": [{"cost_usd": 0.004}, {"cost_usd": 0.001}]}), encoding="utf-8")
    (dev / "round_summary.json").write_text(json.dumps({"round": 1, "round_spent_usd": 99}), encoding="utf-8")  # not a cost record: never counted
    (tmp_path / "reports" / "corpus-v2.1" / "v1.5").mkdir(parents=True)
    (tmp_path / "reports" / "corpus-v2.1" / "v1.5" / "ledger_extras.json").write_text(json.dumps({"items": [{"what": "seal", "usd": 0.5, "estimated": False}]}), encoding="utf-8")
    spend = budget.read_spend(tmp_path)
    assert (spend.entries_usd, spend.smoke_usd, spend.extras_usd, spend.estimated_usd) == (1.0, 0.005, 0.5, 0.25)
    assert spend.total_usd == 1.505 and spend.api_reported_usd == 1.255
    assert budget.read_spend(tmp_path, exclude=dev).total_usd == 0.5


# --- the runner's pure parts --------------------------------------------------------------------------------------------------------------------

def test_the_runner_reads_the_dev_list_from_methodology_and_refuses_a_mismatch(monkeypatch, tmp_path):
    runner = _runner()
    runner.check_pre_registration()  # the committed METHODOLOGY.md agrees with the rule
    bad = tmp_path / "METHODOLOGY.md"
    bad.write_text("DEV_ENTRIES: [1, 2, 3, 4, 5, 6, 7, 8]\n", encoding="utf-8")
    monkeypatch.setattr(runner, "METHODOLOGY", bad)
    with pytest.raises(SystemExit):
        runner.check_pre_registration()


def test_the_runner_plans_only_dev_entries_in_id_order_and_the_firewall_stops_a_test_id(monkeypatch):
    monkeypatch.delenv(firewall.FROZEN_ENV, raising=False)
    runner = _runner()
    rows = [{"id": i, "name": f"o__r{i}", "category": "PRIMARY", "rules_matched": []} for i in range(1, 21)]
    assert [r["id"] for r in runner.plan_entries(rows)] == sorted(split.DEV_ENTRIES)
    monkeypatch.setattr(runner, "DEV_ENTRIES", (*split.DEV_ENTRIES[:-1], split.split()["test"][0]))
    with pytest.raises(firewall.FirewallError):
        runner.plan_entries(rows)


def test_the_infra_requeue_rule_retries_only_an_infra_error_with_no_completed_baseline():
    runner = _runner()
    assert runner.should_retry_infra({"result": {"verdict": "INFRA_ERROR"}, "operations": []})
    assert runner.should_retry_infra({"result": {"verdict": "INFRA_ERROR"}, "operations": [{"role": "baseline", "outcome": "killed"}]})
    assert not runner.should_retry_infra({"result": {"verdict": "INFRA_ERROR"}, "operations": [{"role": "baseline", "outcome": "completed"}]})
    assert not runner.should_retry_infra({"result": {"verdict": "BLOCKED"}, "operations": []})


def test_the_runner_selftest_passes():
    assert _runner()._selftest() == 0
