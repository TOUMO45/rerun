"""The v1.4.1 gate runner (reports/corpus-v2.1/v1.4.1/gate/run_gate_v141.py): the criteria are the v1.4.0 gate's (loaded, not copied), the
caps are the owner's and have no defaults, a starved gate is refused. Offline: nothing here reaches the preflight's network checks."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _load(rel: str, name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _gates():
    return (_load("reports/corpus-v2.1/v1.4.0/gate/run_gate_v140.py", "g140"),
            _load("reports/corpus-v2.1/v1.4.1/gate/run_gate_v141.py", "g141"))


def test_the_selftest_passes():
    assert _gates()[1]._selftest() == 0


def test_same_entries_same_order_same_criteria():
    g140, g141 = _gates()
    assert g141.ENTRIES == g140.ENTRIES == (3, 7, 8, 11)
    assert g141.ENTRY_SPEND_LIMIT_USD == g140.ENTRY_SPEND_LIMIT_USD == 2.0 and g141.PASS == g140.PASS
    assert g141.criterion_e is g141.v140.criterion_e  # loaded from the v1.4.0 runner, not copied
    # the evaluation of the real v1.4.0 gate records is identical under both runners (apart from the pending BILLED line)
    gate = ROOT / "runs" / "corpus_v2_batch" / "harness-v1.4.0" / "gate"
    records = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(gate.glob("[0-9]*.json"))]
    assert len(records) == 4
    old, new = g140.evaluate_gate(records), g141.evaluate_gate(records)
    assert {k: v for k, v in new.items() if k != "billed"} == old
    assert old["passed"] is False and old["a"]["detail"] == "0 of 4 reached RUNS_CLEAN / RUNS_AFTER_REPAIR"  # what the recorded gate said
    assert new["billed"]["tag"] == "BILLED" and new["billed"]["value"] is None and "owner reads the account balance" in new["billed"]["reason"]


def test_no_run_without_the_owners_caps_and_no_starved_gate(capsys):
    gate = _gates()[1]
    assert gate.main([]) == 2 and "no defaults" in capsys.readouterr().err
    assert gate.main(["--gate-cap-usd", "5.99", "--entry-cap-usd", "1.50"]) == 2 and "starved" in capsys.readouterr().err
    assert gate.main(["--gate-cap-usd", "6.00"]) == 2
