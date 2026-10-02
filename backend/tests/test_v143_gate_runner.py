"""The v1.4.3 gate runner (reports/corpus-v2.1/v1.4.3/gate/run_gate_v143.py): the criteria are the v1.4.0 gate's (loaded through the v1.4.2 runner, not copied), the caps are the owner's
and have no defaults ($1.75 entry, $7.00 gate = 4 x entry), a starved gate is refused, and the sustained-run line (D-42) is listed and funded but never evaluated. Offline."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _load(rel: str, name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _gates():
    return (_load("reports/corpus-v2.1/v1.4.0/gate/run_gate_v140.py", "g140"), _load("reports/corpus-v2.1/v1.4.2/gate/run_gate_v142.py", "g142"),
            _load("reports/corpus-v2.1/v1.4.3/gate/run_gate_v143.py", "g143"))


def _record(entry, name, verdict, attempts=(), spent=1.0, command="python main.py"):
    return {"batch": {"entry_id": entry}, "corpus_entry": {"name": name, "command": command}, "cost_guard": {"spent_usd": spent},
            "result": {"verdict": verdict, "attempts": list(attempts)}}


def _alive(image="img-1"):
    return [{"attempt_number": 3, "origin": "model", "candidate": 1, "chosen": True, "exit_code": 0,
             "execution": {"mode": "smoke", "seconds": 60, "outcome": "alive_at_limit", "image": image}}]


def test_the_selftest_passes():
    assert _gates()[2]._selftest() == 0


def test_same_entries_same_order_same_criteria_and_the_evaluation_of_recorded_gates_is_identical():
    g140, g142, g143 = _gates()
    assert g143.ENTRIES == g142.ENTRIES == g140.ENTRIES == (3, 7, 8, 11)
    assert g143.ENTRY_SPEND_LIMIT_USD == 2.0 and g143.PASS == g140.PASS and g143.criterion_e is g143.v142.criterion_e is g143.v142.v140.criterion_e  # loaded down the chain, not copied
    for version in ("harness-v1.4.0", "harness-v1.4.1", "harness-v1.4.2"):
        gate = ROOT / "runs" / "corpus_v2_batch" / version / "gate"
        records = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(gate.glob("[0-9]*.json"))]
        assert len(records) == 4
        old, new = g142.evaluate_gate(records), g143.evaluate_gate(records)
        assert {k: v for k, v in new.items() if k != "sustained_runs"} == old
        assert new["sustained_runs"] == {"gating": False, "runs": [], "cost_usd": 0.0, "cost_estimated_usd": 0.0}


def test_no_run_without_the_owners_caps_and_no_starved_gate(capsys):
    gate = _gates()[2]
    assert gate.main([]) == 2 and "no defaults" in capsys.readouterr().err
    assert gate.main(["--gate-cap-usd", "6.99", "--entry-cap-usd", "1.75"]) == 2 and "starved" in capsys.readouterr().err
    assert gate.main(["--gate-cap-usd", "7.00"]) == 2


def test_the_owners_caps_are_consistent():
    from app.services import gate_budget

    gate_budget.check_gate_caps(7.00, 1.75, 4)  # no exception: 7.00 = 4 x 1.75
    assert gate_budget.entry_cap_for(7.00, 1.75, 5.25) == 1.75  # the last entry still gets its full cap
    with pytest.raises(gate_budget.GateBudgetError):
        gate_budget.entry_cap_for(7.00, 1.75, 5.26)


# --- the sustained-run phase -------------------------------------------------------------------------------------------------

def test_only_runs_records_get_a_sustained_run_each_funded_with_its_share_after_the_entries(tmp_path):
    g143 = _gates()[2]
    records = [_record(3, "a__a", "INDETERMINATE"), _record(7, "b__b", "RUNS_AFTER_REPAIR", _alive("img-b")), _record(8, "c__c", "COST_CAP"),
               _record(11, "d__d", "RUNS_AFTER_REPAIR", _alive("img-d"))]
    paths = {r["corpus_entry"]["name"]: tmp_path / f"{r['batch']['entry_id']:02d}_{r['corpus_entry']['name']}.json" for r in records}
    calls = []

    def fake(record, **kw):
        calls.append((record["batch"]["entry_id"], kw["remaining_usd"], kw["entries_left"]))
        return {"entry": record["batch"]["entry_id"], "name": record["corpus_entry"]["name"], "outcome": "completed", "ran": True, "cost_usd": 1.0, "cost_estimated_usd": 0.25,
                "label": "x"}

    docs, cost = g143.sustained_phase(records, paths, gate_cap_usd=7.0, spent_usd=3.5, odir=tmp_path, run=fake)
    assert [c[0] for c in calls] == [7, 11] and [c[2] for c in calls] == [2, 1]  # only RUNS_* records, shares by entries still to run
    assert calls[0][1] == pytest.approx(3.5) and calls[1][1] == pytest.approx(3.5 - 1.25)  # the second sees what the first used (measured + estimated)
    assert cost == pytest.approx(2.5) and len(docs) == 2
    assert sorted(p.name for p in tmp_path.glob("sustained_*.json")) == ["sustained_07_b__b.json", "sustained_11_d__d.json"]
    assert not list(tmp_path.glob("[0-9]*.json"))  # the entries' own records are never touched


def test_the_sustained_runs_are_listed_in_the_gate_result_and_never_evaluated():
    g143 = _gates()[2]
    docs = [{"entry": 7, "name": "b__b", "outcome": "running_at_limit", "ran": True, "label": "sustained run: still running", "funded_seconds": 198, "seconds": 198.2,
             "cost_usd": 2.05, "cost_estimated_usd": 0.0}]
    gate = ROOT / "runs" / "corpus_v2_batch" / "harness-v1.4.2" / "gate"
    records = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(gate.glob("[0-9]*.json"))]
    without, with_ = g143.evaluate_gate(records), g143.evaluate_gate(records, docs)
    assert {k: v for k, v in with_.items() if k != "sustained_runs"} == {k: v for k, v in without.items() if k != "sustained_runs"}  # criteria and endings unchanged
    assert with_["sustained_runs"]["gating"] is False and with_["sustained_runs"]["cost_usd"] == 2.05 and with_["sustained_runs"]["runs"][0]["outcome"] == "running_at_limit"
    assert with_["passed"] == without["passed"]
