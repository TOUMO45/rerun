"""The v1.4.1 seal runner (reports/corpus-v2.1/v1.4.1/seal/run_seal_v141.py), exercised OFFLINE before any money is spent: its plan, its
refusals, and runs 1-3 end to end against the fake ConTree cloud (v140_cloud) through the real sandbox runner. The live seal measures
what this cannot: the real costs, and that the real shell, apt and ConTree behave as the fake does."""

from __future__ import annotations

import importlib.util
import json
import uuid as uuidlib
from pathlib import Path

import pytest

import v140_cloud
from app.services import runner_hooks
from app.services.orchestrator import apt_layer_command

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "reports" / "corpus-v2.1" / "v1.4.1" / "seal" / "run_seal_v141.py"
LAYER = apt_layer_command(["build-essential"])
HOOK = runner_hooks.install_command(runner_hooks.EXIT_HOOK)
RAISE_SITE = ("RERUN_EXIT_WRAPPER: the entry script raised SystemExit(1); the traceback of the raise (most recent call last):\n"
              "Traceback (most recent call last):\n  File \"bare.py\", line 6, in main\n    raise SystemExit(1)\nSystemExit: 1\n")


@pytest.fixture
def seal(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("run_seal_v141", SCRIPT)
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
        return 1, "working\n", ""  # the hook cannot see a bare raise
    if "script bare.py" in shell:
        return 1, "working\n", RAISE_SITE  # the wrapper prints the raise site
    if shell.startswith("python3 -c \"import shutil"):
        return 0, ("gcc\n" if any("build-essential" in b for b in built) else "None\n"), ""
    if shell == "gcc --version":
        return (0, "gcc (Debian 12.2.0-14) 12.2.0\n", "") if any("build-essential" in b for b in built) else (127, "", "gcc: not found\n")
    return None


def test_the_plan_runs_nothing_and_is_estimated_from_v140_records(seal, capsys):
    assert seal.main([]) == 0
    out = capsys.readouterr().out
    assert "PLAN ONLY" in out and "ESTIMATED" in out and "run 3 op K1" in out
    assert {o["op"] for o in seal.planned_operations([1, 2, 3])} == {"A", "B", "C", "W0", "W1", "W2", "L1", "L2", "K1", "K2"}
    total = sum(o["estimated_usd"] for o in seal.planned_operations([1, 2, 3]))
    assert 0.30 < total < 0.45 and total < seal.MAX_SEAL_USD  # the owner's seal bound is $1.00


def test_no_live_run_without_the_owners_cap_or_above_the_bound(seal, capsys):
    assert seal.main(["--go"]) == 2
    assert seal.main(["--go", "--max-usd", "1.01"]) == 2
    assert seal.main(["--go", "--max-usd", "0"]) == 2
    assert "at most $1.00" in capsys.readouterr().err and seal.MAX_SEAL_USD == 1.00


def test_an_operation_is_not_started_without_three_times_its_estimate_left(seal):
    guard = seal._spend_guard(0.30)
    with pytest.raises(SystemExit, match="K1"):
        seal._seconds(guard, "K1")  # K1's estimate is $0.22: $0.66 would have to be left
    assert seal._seconds(guard, "A") == 120.0
    guard.record_spend(0.29)
    with pytest.raises(SystemExit, match="not started"):
        seal._seconds(guard, "A")


def test_run_1_end_to_end_on_the_fake_cloud(seal, monkeypatch):
    cloud = v140_cloud.install(monkeypatch, _behaviour)
    docs = seal.run_1("key", "", seal._spend_guard(1.0))
    assert [d["ok"] for d in docs] == [True] * 6, docs
    a, b, c, w0, w1, w2 = docs
    assert b["measured_branch_run_usd"] == b["cost_usd"] and b["branch_from_image"] == a["layers"][-1]["image"]
    assert c["branch_from_image"] == a["layers"][-1]["image"] == w0["branch_from_image"] == w1["branch_from_image"]
    assert w0["stderr"].strip() == "" and "RERUN_EXIT_WRAPPER" in w1["stderr"] and "RERUN_EXIT_WRAPPER" in w2["stderr"]
    assert cloud.count(seal.PIP_STEP) == 1  # built once for A; C, W0 and W1 reuse its layer; W2 (python:3.6) installs nothing
    assert (seal.OUT / "run1_W1_wrapper_prints_the_raise_site.json").is_file()


def test_run_1_fails_when_the_wrapper_prints_nothing_or_the_hook_alone_already_saw_the_exit(seal, monkeypatch):
    def silent_wrapper(shell, built, files):
        return (1, "working\n", "") if "script bare.py" in shell else _behaviour(shell, built, files)

    v140_cloud.install(monkeypatch, silent_wrapper)
    docs = seal.run_1("key", "", seal._spend_guard(1.0))
    assert [d["ok"] for d in docs] == [True, True, True, True, False, False]

    def noisy_hook(shell, built, files):
        return (1, "working\n", "SystemExit: 1\n") if shell == "python3 bare.py" else _behaviour(shell, built, files)

    v140_cloud.install(monkeypatch, noisy_hook)
    assert [d["ok"] for d in seal.run_1("key", "", seal._spend_guard(1.0))][3] is False  # W0 must show the gap


def test_run_2_the_layer_runs_alone_on_top_of_the_kept_pip_layer(seal, monkeypatch):
    cloud = v140_cloud.install(monkeypatch, _behaviour)
    docs = seal.run_2("key", "", seal._spend_guard(1.0))
    l1, l2 = docs
    assert l1["ok"] and l2["ok"], docs
    assert l2["branch_from_image"] == l1["layers"][-1]["image"] and l2["start_setup_commands"] == 1
    assert cloud.count(seal.PIP_STEP) == 1 and cloud.count(LAYER) == 1  # the pip step was not run again
    assert "gcc" in l2["stdout"]


def test_run_3_a_killed_operation_keeps_its_first_layer_and_a_new_operation_resumes_from_it(seal, monkeypatch):
    from contree_sdk.sdk.exceptions import OperationTimedOutError

    cloud = v140_cloud.install(monkeypatch, _behaviour, costs={"": 0.01})
    real_run = v140_cloud.Image.run

    def run(self, shell, timeout, disposable, preserve_env=False):
        if shell == seal.SLEEP_STEP:
            raise OperationTimedOutError(operation_uuid=uuidlib.uuid4())
        return real_run(self, shell, timeout, disposable, preserve_env)

    monkeypatch.setattr(v140_cloud.Image, "run", run)
    guard = seal._spend_guard(1.0)
    k1, k2 = seal.run_3("key", "", guard)
    assert k1["ok"] and k1["killed"] and k2["ok"], (k1, k2)
    assert k1["killed_command"] == seal.SLEEP_STEP and [layer["setup_commands"] for layer in k1["layers"]] == [0, 1]
    assert k2["branch_from_image"] == k1["layers"][-1]["image"] and k2["start_setup_commands"] == 1
    assert cloud.count(seal.PIP_STEP) == 1  # K2 did not run it again
    assert k1["cost_usd"] > 0 and guard.spent_today_usd >= k1["cost_usd"]  # the killed operation's cost is recorded, not lost


def test_run_3_is_not_ok_when_the_sleep_step_was_never_stopped(seal, monkeypatch):
    v140_cloud.install(monkeypatch, _behaviour)  # nothing is killed: the fake finishes the sleep at once
    docs = seal.run_3("key", "", seal._spend_guard(1.0))
    assert len(docs) == 1 and docs[0]["ok"] is False and "not stopped" in docs[0]["message"]


def test_the_records_are_json_with_the_fields_the_seal_writer_needs(seal, monkeypatch):
    v140_cloud.install(monkeypatch, _behaviour)
    seal.run_2("key", "", seal._spend_guard(1.0))
    doc = json.loads((seal.OUT / "run2_L2_additive_apt_layer.json").read_text(encoding="utf-8"))
    assert doc["ok"] is True and doc["run_id"] and doc["harness"] == "harness-v1.4.1-rc" and doc["layers"]
