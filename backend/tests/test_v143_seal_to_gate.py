"""The owner's seal -> gate rule as a script (reports/corpus-v2.1/v1.4.3/seal/check_seal_to_gate.py): the gate starts only if every seal check passed, the branch-run cost is at most $0.15
API-reported and the seal's spend is within its cap. Offline, on synthetic seal directories."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "reports" / "corpus-v2.1" / "v1.4.3" / "seal" / "check_seal_to_gate.py"


@pytest.fixture
def rule(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("check_seal_to_gate", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "ROOT", tmp_path)
    seal = tmp_path / "seal"
    monkeypatch.setattr(module, "SEAL", seal)
    return module, seal, tmp_path


def _write(seal: Path, root: Path, *, costs=None, branch=0.0006, ok=True, drop_stage=None):
    stages = {}
    for stage in ("new", "v141", "v142", "v140", "final"):
        if stage == drop_stage:
            continue
        rel = f"seal/{stage}/record.json"
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(json.dumps({"ok": ok if stage == "final" else True}), encoding="utf-8")
        stages[stage] = {"ok": True, "cost_usd": (costs or {}).get(stage, 0.1), "records": [rel]}
    (seal / "v142").mkdir(parents=True, exist_ok=True)
    (seal / "v140").mkdir(parents=True, exist_ok=True)
    for stage in ("v142", "v140"):
        (seal / stage / "run1_B_branch_run.json").write_text(json.dumps({"ok": True, "measured_branch_run_usd": branch}), encoding="utf-8")
    (seal / "SEAL_RUN.json").write_text(json.dumps({"stages": stages}), encoding="utf-8")


def test_a_passed_seal_within_its_cap_and_a_cheap_branch_run_starts_the_gate(rule):
    module, seal, root = rule
    _write(seal, root)
    assert module.check(1.50, seal) == (True, [])


def test_every_way_the_rule_can_fail_is_named(rule):
    module, seal, root = rule
    assert module.check(1.50, seal)[1] == ["SEAL_RUN.json is missing: the seal did not run"]
    _write(seal, root, drop_stage="v140")
    assert any("stage v140 is missing" in p for p in module.check(1.50, seal)[1])
    _write(seal, root, ok=False)
    assert any("ok is not true" in p for p in module.check(1.50, seal)[1])
    _write(seal, root, branch=0.1501)
    assert any("branch-run cost $0.150100 is above $0.15" in p for p in module.check(1.50, seal)[1])
    _write(seal, root, costs={"final": 1.2})  # 0.1 x 4 stages + 1.2 = 1.6
    assert any("seal spend $1.6000 is above the cap $1.50" in p for p in module.check(1.50, seal)[1])
    (seal / "v142" / "run1_B_branch_run.json").write_text(json.dumps({"ok": True}), encoding="utf-8")
    _write(seal, root)
    (seal / "v142" / "run1_B_branch_run.json").write_text(json.dumps({"ok": True}), encoding="utf-8")
    assert any("no measured branch-run cost" in p for p in module.check(1.50, seal)[1])


def test_main_exit_codes(rule, capsys):
    module, seal, root = rule
    assert module.main(["--cap", "1.5"]) == 1 and "NOT satisfied" in capsys.readouterr().out
    _write(seal, root)
    assert module.main(["--cap", "1.5"]) == 0 and "the rule is satisfied" in capsys.readouterr().out
