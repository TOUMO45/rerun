"""The v1.4.2 seal runner (reports/corpus-v2.1/v1.4.2/seal/run_seal_v142.py), exercised OFFLINE before any money is spent: its plan, its refusals, and runs 1 and 2
end to end against the fake ConTree cloud (v140_cloud) through the real sandbox runner. The live seal measures what this cannot: the real shell, the real kernel, the
limits the sandbox shows."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

import v140_cloud
from app.services import runner_hooks

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "reports" / "corpus-v2.1" / "v1.4.2" / "seal" / "run_seal_v142.py"
HOOK = runner_hooks.install_command(runner_hooks.EXIT_HOOK)
RAISE_SITE = ("RERUN_EXIT_WRAPPER: the entry script raised SystemExit(1); the traceback of the raise (most recent call last):\n"
              "Traceback (most recent call last):\n  File \"bare.py\", line 6, in main\n    raise SystemExit(1)\nSystemExit: 1\n")


def block(status: int, oom_kill: int = 0, dmesg: str = "") -> str:
    return (f"RERUN_EVIDENCE_BEGIN exit_status={status}\n--meminfo\nMemTotal:        4096000 kB\n--nproc\n2\n--cgroup\n"
            f"/sys/fs/cgroup/memory.events=low 0 high 0 max 0 oom {oom_kill} oom_kill {oom_kill} \n--dmesg\n{dmesg}\nRERUN_EVIDENCE_END\n")


@pytest.fixture
def seal(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("run_seal_v142", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "OUT", tmp_path / "seal")
    return module


def _behaviour(shell, built, files):
    if shell == "python3 probe.py":
        return 0, files["probe.py"].decode().split("'")[1] + "\n", ""
    if shell == "python3 exit_probe.py":
        stack = "RERUN_EXIT_HOOK: sys.exit(3) was called; the exit site (most recent call last):\n  File \"exit_probe.py\", line 4, in leave\nSystemExit: 3\n"
        return 3, "", stack if HOOK in built else ""
    if shell == "python3 bare.py":
        return 1, "working\n", ""
    if "script bare.py" in shell:
        return 1, "working\n", RAISE_SITE
    if shell.startswith("(\npython3 probe.py\n);"):  # the evidence command: the probe script decides what happens
        script = files["probe.py"]
        if b"sys.exit(3)" in script:
            return 3, "calm run\n", block(3)
        if b"SIGKILL" in script:
            return 137, "about to be killed\n", "Killed\n" + block(137)
        return 137, "ALLOCATED_MB 64\nALLOCATED_MB 128\nALLOCATED_MB 192\n", "Killed\n" + block(137, oom_kill=1, dmesg="Out of memory: Killed process 9 (python3)")
    return None


def test_the_plan_runs_nothing_and_is_estimated_from_v141_records(seal, capsys):
    assert seal.main([]) == 0
    out = capsys.readouterr().out
    assert "PLAN ONLY" in out and "ESTIMATED" in out and "run 2 op E1b" in out
    assert {o["op"] for o in seal.planned_operations([1, 2])} == {"A", "B", "C", "W0", "W1", "W2", "E0", "E1a", "E1b"}
    total = sum(o["estimated_usd"] for o in seal.planned_operations([1, 2]))
    assert 0.25 < total < 0.35 and total < seal.MAX_SEAL_USD


def test_the_cap_is_the_ceiling_arithmetic_not_the_owners_looser_one_dollar(seal, capsys):
    assert seal.MAX_SEAL_USD == 0.49 and 25.00 - 18.5083 - 6.00 == pytest.approx(0.4917)
    assert seal.main(["--go"]) == 2 and seal.main(["--go", "--max-usd", "0.50"]) == 2 and seal.main(["--go", "--max-usd", "0"]) == 2
    assert "at most $0.49" in capsys.readouterr().err


def test_an_operation_is_not_started_without_one_and_a_half_times_its_estimate_left(seal):
    guard = seal._spend_guard(0.30)
    with pytest.raises(SystemExit, match="E1b"):
        seal._seconds(guard, "E1b")  # $0.26 x 1.5 = $0.39 would have to be left
    assert seal._seconds(guard, "A") == 120.0
    guard.record_spend(0.295)
    with pytest.raises(SystemExit, match="not started"):
        seal._seconds(guard, "A")


def test_run_1_end_to_end_on_the_fake_cloud(seal, monkeypatch):
    cloud = v140_cloud.install(monkeypatch, _behaviour)
    docs = seal.run_1("key", "", seal._spend_guard(0.49))
    assert [d["ok"] for d in docs] == [True] * 6, docs
    assert docs[1]["measured_branch_run_usd"] == docs[1]["cost_usd"]
    assert cloud.count(seal.PIP_STEP) == 1 and all(d["harness"] == "harness-v1.4.2-rc" for d in docs)


def test_run_2_the_evidence_command_on_a_calm_run_a_self_kill_and_an_allocation(seal, monkeypatch):
    v140_cloud.install(monkeypatch, _behaviour)
    docs = seal.run_2("key", "", seal._spend_guard(0.49))
    e0, e1a, e1b = docs
    assert e0["ok"] and e0["evidence"]["exit_status"] == 3 and e0["evidence"]["mem_total_kb"] == 4096000 and "MemTotal 4096000 kB" in e0["limit_quote"]
    assert e1a["ok"] and e1a["evidence"]["exit_status"] == 137 and "Killed" in e1a["stderr"]
    assert e1b["informational"] and e1b["killed"] and e1b["kill_evidenced"] and e1b["allocated_mb_before_the_end"] == 192 and not e1b["reached_cap"]
    assert "oom_kill 1" in e1b["limit_quote"]


def test_run_2_fails_when_a_calm_run_shows_a_kill_or_a_self_kill_shows_none(seal, monkeypatch):
    def broken(shell, built, files):
        if shell.startswith("(\npython3 probe.py\n);") and b"sys.exit(3)" in files["probe.py"]:
            return 3, "", block(3, oom_kill=1)  # a calm run must not show an OOM kill
        return _behaviour(shell, built, files)

    v140_cloud.install(monkeypatch, broken)
    assert [d["ok"] for d in seal.run_2("key", "", seal._spend_guard(0.49))][0] is False


def test_the_allocation_probe_timeout_is_recorded_informational_and_does_not_fail_the_seal(seal, monkeypatch):
    import uuid as uuidlib

    from contree_sdk.sdk.exceptions import OperationTimedOutError

    v140_cloud.install(monkeypatch, _behaviour, costs={"": 0.01})
    real_run = v140_cloud.Image.run

    def run(self, shell, timeout, disposable, preserve_env=False):
        if shell.startswith("(\npython3 probe.py\n);") and b"ALLOCATED_MB" in self.state["files"].get("probe.py", b""):
            raise OperationTimedOutError(operation_uuid=uuidlib.uuid4())
        return real_run(self, shell, timeout, disposable, preserve_env)

    monkeypatch.setattr(v140_cloud.Image, "run", run)
    guard = seal._spend_guard(0.49)
    docs = seal.run_2("key", "", guard)
    assert len(docs) == 2 and all(d["ok"] for d in docs)
    stopped = json.loads((seal.OUT / "run2_E1b_allocate_until_killed_with_evidence.json").read_text(encoding="utf-8"))
    assert stopped["killed"] and stopped["informational"] and stopped["ok"] is False and "$0.0152/s" in stopped["cost_tag"]
    assert guard.cost_events and guard.cost_events[-1]["rate_usd_per_s"] == 0.0152  # the D-27 rate
