"""harness-v1.3 driver: validated resume, child ownership, driver log, honest watcher, ablation arms."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

from app.services.cost_guard import CostGuard
from app.services.intake import RepoIntake
from app.services.orchestrator import PipelineDeps, run_pipeline
from app.services.passport import sign_certificate
from app.services.sandbox import SandboxRunResult, StepResult
from app.services.time_machine import LockResult

ROOT = Path(__file__).resolve().parents[2]


def _load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


batch = _load("run_corpus_v1_batch")
watch = _load("watch_batch")

FROZEN = {"corpus": "corpus-v2", "harness_tag": "harness-v1.3", "harness_commit": "c" * 40, "corpus_hash": "h" * 64,
          "arm": "control"}


def _certificate() -> dict:
    cert = {"repo_url": "https://github.com/o/r", "commit_sha": "a" * 40, "build_plan": {}, "full_log": "x", "diffs": [],
            "verdict": "BLOCKED", "timestamp": "t", "bundle_version": 4, "baseline": {"result": "FAILS"}, "recovery": False,
            "tree_integrity": {"status": "verified"}, "corpus_hash": FROZEN["corpus_hash"], "taxonomy_code": "DEP_MISSING",
            "indeterminate_reason": "", "error_chain": [], "first_repo_error": None, "last_error": None}
    return sign_certificate(cert)


def _record(**over) -> dict:
    rec = {"batch": {k: FROZEN[k] for k in ("corpus_hash", "harness_tag", "harness_commit")},
           "corpus_entry": {"name": "e1"}, "config": {"arm": "control"}, "finished_at": "2026-09-29T00:00:00+00:00",
           "result": {"verdict": "BLOCKED"}, "certificate": _certificate(), "cost_guard": {"spent_usd": 0.1}}
    rec.update(over)
    return rec


def _write(tmp_path, rec) -> Path:
    path = tmp_path / "01_e1.json"
    path.write_text(json.dumps(rec), encoding="utf-8")
    return path


# --- record validation -----------------------------------------------------------------------

def test_a_complete_record_is_valid(tmp_path):
    assert batch.record_problems(_write(tmp_path, _record()), "e1", FROZEN) == []


@pytest.mark.parametrize("mutate, expect", [
    (lambda r: r.pop("finished_at"), "finished_at"),
    (lambda r: r["result"].pop("verdict"), "no verdict"),
    (lambda r: r.pop("certificate"), "signed certificate"),
    (lambda r: r["certificate"].update(verdict="RUNS_CLEAN"), "does not verify"),
    (lambda r: r.update(error="RuntimeError: boom"), "driver error"),
    (lambda r: r["batch"].update(corpus_hash="x"), "corpus_hash"),
    (lambda r: r["batch"].update(harness_tag="harness-v1.2"), "harness_tag"),
    (lambda r: r["config"].update(arm="treatment"), "arm differs"),
    (lambda r: r["corpus_entry"].update(name="other"), "entry name"),
    (lambda r: r.pop("cost_guard"), "spent_usd"),
])
def test_incomplete_or_foreign_records_are_invalid(tmp_path, mutate, expect):
    rec = _record()
    mutate(rec)
    problems = batch.record_problems(_write(tmp_path, rec), "e1", FROZEN)
    assert any(expect in p for p in problems), problems


def test_a_development_run_is_never_a_valid_record(tmp_path):
    problems = batch.record_problems(_write(tmp_path, _record(dev_run=True)), "e1", FROZEN)
    assert any("development run" in p for p in problems)


def test_truncated_json_is_invalid(tmp_path):
    path = tmp_path / "01_e1.json"
    path.write_text('{"batch": {', encoding="utf-8")
    assert "unreadable" in batch.record_problems(path, "e1", FROZEN)[0]


# --- resume ------------------------------------------------------------------------------------

def _run_batch(monkeypatch, tmp_path, runs):
    monkeypatch.setattr(batch, "ROOT", tmp_path)
    monkeypatch.setattr(batch, "entries_for", lambda corpus: [{"id": 1, "name": "e1", "category": "PRIMARY", "rules_matched": []}])

    def runner(corpus, name, corpus_hash, meta, path):
        runs.append(name)
        path.write_text(json.dumps(_record()), encoding="utf-8")

    return batch.run_batch(dict(FROZEN), runner=runner)


def test_resume_skips_a_valid_record_and_reruns_an_invalid_one_once(monkeypatch, tmp_path, capsys):
    odir = tmp_path / "runs" / "corpus_v2_batch" / "harness-v1.3" / "control"
    odir.mkdir(parents=True)
    (odir / "01_e1.json").write_text(json.dumps(_record()), encoding="utf-8")
    runs: list[str] = []
    _run_batch(monkeypatch, tmp_path, runs)
    assert runs == [] and "valid record exists" in capsys.readouterr().out

    (odir / "01_e1.json").write_text('{"half": ', encoding="utf-8")  # a dead child's leftover
    _run_batch(monkeypatch, tmp_path, runs)
    assert runs == ["e1"] and list(odir.glob("01_e1.json.invalid-*"))  # set aside, kept as evidence, re-run
    assert batch.record_problems(odir / "01_e1.json", "e1", FROZEN) == []

    (odir / "01_e1.json").write_text('{"half": ', encoding="utf-8")  # invalid AGAIN: a defect, stop
    _run_batch(monkeypatch, tmp_path, runs)
    assert runs == ["e1"] and "invalid record twice" in capsys.readouterr().out


def test_arm_records_live_in_their_own_directory():
    assert batch.out_dir("corpus-v2", "harness-v1.3", "control").as_posix().endswith("corpus_v2_batch/harness-v1.3/control")
    assert batch.out_dir("corpus-v2", "harness-v1.2").as_posix().endswith("corpus_v2_batch/harness-v1.2")


# --- child ownership (real processes, Windows job object) -------------------------------------------

@pytest.mark.skipif(sys.platform != "win32", reason="job objects are Windows-only")
def test_children_die_with_the_driver(tmp_path):
    marker = tmp_path / "child.pid"
    driver = tmp_path / "driver.py"
    driver.write_text(textwrap.dedent(f"""
        import importlib.util, subprocess, sys, time
        spec = importlib.util.spec_from_file_location("b", r"{ROOT / 'scripts' / 'run_corpus_v1_batch.py'}")
        b = importlib.util.module_from_spec(spec); spec.loader.exec_module(b)
        b.own_children()
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
        open(r"{marker}", "w").write(str(child.pid))
        time.sleep(120)
    """), encoding="utf-8")
    proc = subprocess.Popen([sys.executable, str(driver)])
    try:
        for _ in range(100):
            if marker.exists() and marker.read_text():
                break
            time.sleep(0.1)
        child_pid = int(marker.read_text())
        assert watch.pid_alive(child_pid)
        proc.kill()  # the driver dies hard, no cleanup code runs
        proc.wait(timeout=10)
        for _ in range(100):
            if not watch.pid_alive(child_pid):
                break
            time.sleep(0.1)
        assert not watch.pid_alive(child_pid), "orphaned child survived its driver"
    finally:
        proc.kill()


# --- the watcher tells the truth -------------------------------------------------------------------

def test_watcher_states(tmp_path):
    assert watch.state_of(tmp_path) == "NOT_STARTED"
    (tmp_path / "driver.pid").write_text(str(os.getpid()), encoding="utf-8")
    assert watch.state_of(tmp_path).startswith("RUNNING")
    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait()
    (tmp_path / "driver.pid").write_text(str(dead.pid), encoding="utf-8")
    assert watch.state_of(tmp_path).startswith("GONE")
    (tmp_path / "summary.json").write_text("{}", encoding="utf-8")
    assert watch.state_of(tmp_path) == "DONE"


# --- ablation: the control arm turns repair off ------------------------------------------------------

class _Chat:
    def __init__(self, responses):
        self._responses = list(responses)

    def chat_completion(self, **kwargs):
        return self._responses.pop(0)


def _res(code, stderr=""):
    return SandboxRunResult(steps=(StepResult("run", code, "", stderr, 1.0, 0.0),))


def _pipeline(tmp_path, *, repair_enabled):
    (tmp_path / "requirements.txt").write_text("regex==2017.4.5\n", encoding="utf-8")
    (tmp_path / "gen.py").write_text("import regex\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "-c", "user.email=t@e.st", "-c", "user.name=t", "commit", "-q", "-m", "x"], cwd=tmp_path, check=True)
    calls = []

    def sandbox(**kw):
        calls.append(kw)
        return _res(1, "ModuleNotFoundError: No module named 'foo'")

    deps = PipelineDeps(
        recon_client=_Chat([json.dumps({"entrypoint": "gen.py", "confidence": 0.9})]), recon_model="r",
        repair_client=_Chat([]), repair_model="p", adjudicator_client=None, adjudicator_model=None,
        sandbox_api_key="k", sandbox_wall_clock_seconds=60, sandbox_runner=sandbox, max_attempts=3,
        lock_compiler=lambda *a: LockResult(True, ("regex==2017.4.5",), ()), repair_enabled=repair_enabled,
    )
    intake = RepoIntake(tmp_path, "a" * 40, {"requirements.txt": "regex==2017.4.5\n"}, frozenset({"regex"}), (), ("gen.py",), None)
    result = run_pipeline(repo_url="https://example.com/r", commit_sha="a" * 40, workdir=tmp_path, intake_result=intake,
                          deps=deps, cost_guard=CostGuard(daily_cost_ceiling_usd=100), run_id="arm")
    return result, calls


def test_control_arm_runs_the_repo_once_as_is_and_never_repairs(tmp_path):
    result, calls = _pipeline(tmp_path, repair_enabled=False)
    assert len(calls) == 1 and result.attempts == () and result.verdict == "BLOCKED"
    assert result.repair_mode == "deterministic" and result.first_repo_error.startswith("ModuleNotFoundError")


def test_treatment_arm_still_tries_to_repair(tmp_path):
    result, calls = _pipeline(tmp_path, repair_enabled=True)
    assert len(calls) > 1  # the time machine (and the repair loop) re-executed the repo


def test_total_cap_is_a_parameter_that_counts_the_other_arms_spend(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(batch, "ROOT", tmp_path)
    monkeypatch.setattr(batch, "entries_for", lambda corpus: [{"id": 1, "name": "e1", "category": "PRIMARY", "rules_matched": []}])
    runs: list[str] = []
    frozen = {**FROZEN, "total_cap_usd": 5.0, "already_spent_usd": 3.5}  # 3.5 + the $2 per-entry cap > 5.0
    batch.run_batch(frozen, runner=lambda *a: runs.append(a))
    assert runs == [] and "STOP: $3.5000 spent" in capsys.readouterr().out
    frozen["already_spent_usd"] = 2.9  # 2.9 + 2.0 <= 5.0: the entry may start
    monkeypatch.setattr(batch, "record_problems", lambda *a: [])
    try:
        batch.run_batch(frozen, runner=lambda *a: runs.append(a))
    except (FileNotFoundError, KeyError):
        pass  # the fake runner wrote no record; only "did it start" matters here
    assert len(runs) == 1
