"""The v1.4.0 gate runner (reports/corpus-v2.1/v1.4.0/gate/run_gate_v140.py): criteria (a)-(e) on synthetic and on pipeline-made
records, and its refusals. Offline: nothing here reaches the preflight's network checks or any sandbox."""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / "reports" / "corpus-v2.1" / "v1.4.0" / "gate" / "run_gate_v140.py"


def _runner():
    spec = importlib.util.spec_from_file_location("run_gate_v140", RUNNER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_selftest_passes():
    assert _runner()._selftest() == 0


def test_no_run_without_the_owners_caps_and_no_starved_gate(capsys):
    gate = _runner()
    assert gate.main([]) == 2 and "no defaults" in capsys.readouterr().err
    assert gate.main(["--gate-cap-usd", "4.99", "--entry-cap-usd", "1.25"]) == 2 and "starved" in capsys.readouterr().err


def test_concurrent_candidates_building_the_same_environment_are_not_a_missed_reuse():
    gate = _runner()
    ops = [
        {"n": 1, "role": "baseline", "torch_installed": True, "torch_in_start_image": False, "torch_env_key": "a"},
        {"n": 2, "role": "re-execution", "torch_installed": True, "torch_in_start_image": False, "torch_env_key": "b"},
        {"n": 3, "role": "repair 1 candidate 1", "torch_installed": True, "torch_in_start_image": False, "torch_env_key": "c"},
        {"n": 4, "role": "repair 1 candidate 2", "torch_installed": True, "torch_in_start_image": False, "torch_env_key": "c"},
    ]
    assert gate.criterion_e({"operations": ops})["ok"]
    later = ops + [{"n": 5, "role": "repair 2 candidate 1", "torch_installed": True, "torch_in_start_image": False, "torch_env_key": "c"}]
    assert not gate.criterion_e({"operations": later})["ok"]  # a later round could have reused it


def test_criterion_e_on_records_made_by_the_real_pipeline(tmp_path, monkeypatch):
    """Entry 8's scenario (the fallback environment on the baseline's base image) through the real orchestrator and the real sandbox
    runner on the fake cloud: the record built from that run passes (e), and the same record with the harness-v1.3.4 behaviour (the
    time machine rebuilding torch) fails it."""
    import json

    import test_v140_pipeline as pipeline
    import v140_cloud
    from app.services.time_machine import LockResult

    pipeline._repo(tmp_path, {"main.py": "import torch\nimport sklearn\n"})

    def behaviour(shell, built, files):
        if shell in pipeline.EXEC:
            return (0, "ok", "") if any("scikit-learn" in b for b in built) else (1, "", pipeline.SKLEARN_MISSING)
        return None

    cloud = v140_cloud.install(monkeypatch, behaviour)
    result, _, guard = pipeline._run(tmp_path, cloud, lock=lambda *a: LockResult(False, error="unsatisfiable"))
    record = {"batch": {"entry_id": 8, "per_entry_cap_usd": 1.25},
              "result": {"verdict": result.verdict, "attempts": [a.as_dict() for a in result.attempts]},
              "cost_guard": {"spent_usd": guard.spent_today_usd, "cost_events": guard.cost_events},
              "operations": json.loads(json.dumps(guard.operations))}
    gate = _runner()
    assert gate.criterion_e(record)["ok"] and gate.criterion_e(record)["baseline_installs"] == 1
    v134_like = json.loads(json.dumps(record))
    v134_like["operations"][1].update(torch_installed=True, torch_in_start_image=False)  # what v1.3.4 did: torch again, from scratch
    assert not gate.criterion_e(v134_like)["ok"]
