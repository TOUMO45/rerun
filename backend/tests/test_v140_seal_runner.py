"""The v1.4.0 seal runner (reports/corpus-v2.1/v1.4.0/seal/run_seal_v140.py), exercised OFFLINE before any money is spent: its plan,
its refusals, and runs 1 and 2 end to end against the fake ConTree cloud (v140_cloud) through the real sandbox runner. The live
seal measures what this cannot: real costs, and whether a kept image is billed."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

import v140_cloud
from app.services import runner_hooks, smoke_exec

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "reports" / "corpus-v2.1" / "v1.4.0" / "seal" / "run_seal_v140.py"


@pytest.fixture
def seal(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("run_seal_v140", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "OUT", tmp_path / "seal")
    monkeypatch.setattr(module.time, "sleep", lambda s: None)
    return module


def test_the_plan_runs_nothing_and_run_2_comes_from_the_committed_record(seal, capsys):
    assert seal.main([]) == 0
    out = capsys.readouterr().out
    assert "PLAN ONLY" in out and "python:3.8-slim" in out and "pfqi@84901d291e75" in out
    plan, entry = seal.entry07_plan()
    assert plan.base_image == "python:3.8-slim" and "pkg-config" in plan.apt_install and entry["commit_sha"].startswith("84901d29")
    assert {o["op"] for o in seal.planned_operations([1, 2])} == set("ABCDEF")


def test_no_live_run_without_the_owners_cap_or_above_the_bound(seal, capsys):
    assert seal.main(["--run", "1", "--go"]) == 2
    assert seal.main(["--run", "1", "--go", "--max-usd", "1.51"]) == 2
    assert seal.main(["--run", "3"]) == 2  # run 3 only as a repeat of an ambiguous run
    assert "at most $1.50" in capsys.readouterr().err


def test_run_1_end_to_end_on_the_fake_cloud(seal, monkeypatch):
    hook = runner_hooks.install_command(runner_hooks.EXIT_HOOK)

    def behaviour(shell, built, files):
        if shell == "python3 probe.py":
            return 0, files["probe.py"].decode().split("'")[1] + "\n", ""
        if shell == "python3 exit_probe.py":
            stack = "RERUN_EXIT_HOOK: sys.exit(3) was called; the exit site (most recent call last):\n  File \"exit_probe.py\", line 4, in leave\nSystemExit: 3\n"
            return 3, "", stack if hook in built else ""
        return None

    cloud = v140_cloud.install(monkeypatch, behaviour)
    docs = seal.run_1("key", "", seal._spend_guard(1.5), wait_seconds=0)
    assert [d["ok"] for d in docs] == [True, True, True, True], docs
    a, b, c, d = docs
    assert b["branch_from_image"] == a["layers"][-1]["image"] and b["result_image"]
    assert d["branch_from_image"] == b["result_image"] and b["result_image"] in d["kept_images"]
    assert cloud.count("pip install six==1.16.0") == 1  # built once, reused by B, C and D
    assert (seal.OUT / "run1_B_branch_run.json").is_file()


def test_run_2_end_to_end_on_the_fake_cloud(seal, monkeypatch):
    plan, entry = seal.entry07_plan()
    apt, lock = plan.as_shell_steps()

    def fake_clone(url, workdir, sha):
        (Path(workdir) / "scripts").mkdir(parents=True, exist_ok=True)
        (Path(workdir) / "scripts" / "run_cartpole.py").write_text("import gym\n", encoding="utf-8")
        return sha

    from app.services import intake

    monkeypatch.setattr(intake, "clone_repo_at_commit", fake_clone)
    smoke = smoke_exec.wrap(entry["command"], seal.SMOKE_SECONDS)

    def behaviour(shell, built, files):
        if shell == lock:
            return 1, "", "ERROR: Failed building wheel for pygame\n"  # as recorded: this environment never completes
        if shell == smoke:
            return 1, "", "ModuleNotFoundError: No module named 'gym'\n"
        return None

    cloud = v140_cloud.install(monkeypatch, behaviour)
    docs = seal.run_2("key", "", seal._spend_guard(1.5))
    e, f = docs
    assert e["ok"] and f["ok"], docs
    assert f["start_setup_commands"] == 1 and cloud.count(apt) == 1  # F reopened E's apt layer: the apt step ran once
    assert cloud.count(lock) == 2  # the step that never completed is the only one run again


def _fake_clone(url, workdir, sha):
    (Path(workdir) / "scripts").mkdir(parents=True, exist_ok=True)
    (Path(workdir) / "scripts" / "run_cartpole.py").write_text("import gym\n", encoding="utf-8")
    return sha


def test_a_killed_seal_operation_is_recorded_with_its_cost_not_lost(seal, monkeypatch):
    """The defect of run 2's first live attempt: a timeout escaped with the measured cost of the completed steps."""
    import uuid as uuidlib

    from contree_sdk.sdk.exceptions import OperationTimedOutError

    from app.services import intake

    monkeypatch.setattr(intake, "clone_repo_at_commit", _fake_clone)
    plan, _ = seal.entry07_plan()
    apt, lock = plan.as_shell_steps()
    cloud = v140_cloud.install(monkeypatch, None, costs={apt: 0.04})
    real_run = v140_cloud.Image.run

    def run(self, shell, timeout, disposable, preserve_env=False):
        if shell == lock:
            raise OperationTimedOutError(operation_uuid=uuidlib.uuid4())
        return real_run(self, shell, timeout, disposable, preserve_env)

    monkeypatch.setattr(v140_cloud.Image, "run", run)
    guard = seal._spend_guard(1.5)
    assert seal.run_2("key", "", guard, op_seconds=120) == []
    import json

    doc = json.loads((seal.OUT / "run2_E_entry07_checkpoint.json").read_text(encoding="utf-8"))
    assert doc["ok"] is False and doc["killed"] and doc["measured_completed_usd"] >= 0.04
    assert guard.spent_today_usd == pytest.approx(doc["cost_usd"]) and len(doc["layers"]) == 2  # tree + apt kept
    del cloud


def test_run_2_can_start_from_a_kept_image_without_uploading_or_rerunning_apt(seal, monkeypatch):
    from app.services import intake

    monkeypatch.setattr(intake, "clone_repo_at_commit", _fake_clone)
    plan, entry = seal.entry07_plan()
    apt, lock = plan.as_shell_steps()
    cloud = v140_cloud.install(monkeypatch, None)
    kept = cloud.new_image(("FROM python:3.8-slim", "tar -xpf ...", apt), {"scripts/run_cartpole.py": b"import gym\n"})
    docs = seal.run_2("key", "", seal._spend_guard(1.5), op_seconds=120, start_image=kept.uuid)
    assert [d["ok"] for d in docs] == [True, True]
    assert cloud.count(apt) == 0 and not [c for c in cloud.ran if c.startswith("tar -xpf .rerun-upload")]
    assert docs[0]["branch_from_image"] == kept.uuid
