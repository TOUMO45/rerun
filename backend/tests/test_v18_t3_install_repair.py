"""harness-v1.8 (T3): two install lines that cannot work any more are repaired by RERUN, deterministically, before any model call, recorded and labelled.

The evidence is TEST-B #3 alexlee-gk/video_prediction (now DEV-CONTAMINATED), `runs/corpus_v3_batch/harness-v1.7.2/treatment/03_alexlee-gk__video_prediction.json`:
  - the plan's `apt libgl1-mesa-glx` met `E: Package 'libgl1-mesa-glx' has no installation candidate` (classified RUNTIME_ERROR_OTHER, which skipped the time
    machine; nine repair attempts followed);
  - the requirements' `git+git://github.com/alexlee-gk/lpips-tensorflow.git#egg=lpips-tf` met `fatal: unable to connect to github.com: ... Connection timed out`
    (GitHub switched off the unauthenticated git:// protocol on 2022-03-15; reproduced 2026-10-07), recorded as pip's wrapper line.
The failing output is read from that record, not retyped. Offline: a scripted sandbox; the real classifier and orchestrator run. On the harness-v1.7.2 code the
pipeline tests fail (the model is asked, or nothing is rewritten)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from app.services import classifier, install_repair, outcome_levels, planner
from app.services.cost_guard import CostGuard
from app.services.intake import RepoIntake
from app.services.orchestrator import PipelineDeps, run_pipeline
from app.services.time_machine import LockResult
from test_d24_build_essential import _Chat, _fail, _ok

ROOT = Path(__file__).resolve().parents[2]
RECORD = ROOT / "runs" / "corpus_v3_batch" / "harness-v1.7.2" / "treatment" / "03_alexlee-gk__video_prediction.json"
_REC = json.loads(RECORD.read_text(encoding="utf-8"))["result"]
APT_LINE = next(link["error"] for link in _REC["error_chain"] if "no installation candidate" in link["error"])
GIT_STDERR = next(a["stderr_tail"] for a in reversed(_REC["attempts"]) if "git clone" in (a.get("stderr_tail") or ""))
REQ = "numpy\ngit+git://github.com/alexlee-gk/lpips-tensorflow.git#egg=lpips-tf\n"
APT_STDERR = f"Reading package lists...\n{APT_LINE}\n"


LOCK_CALLS: list = []  # every call of the era-lock compiler in the last _run


def _run(tmp_path, results, *, declared=frozenset(), dep_files=None, replies=(), max_attempts=3):
    LOCK_CALLS.clear()
    (tmp_path / "train.py").write_text("import numpy\nprint('ok')\n", encoding="utf-8", newline="\n")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True, capture_output=True)
    for k, v in (("core.autocrlf", "false"), ("user.email", "t@e.st"), ("user.name", "t")):
        subprocess.run(["git", "config", k, v], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-q", "-m", "x"], cwd=tmp_path, check=True, capture_output=True)
    results = list(results)

    def runner(**kw):
        return results.pop(0)

    repair = _Chat(replies)
    deps = PipelineDeps(
        recon_client=_Chat([{"entrypoint": "train.py", "confidence": 0.9}]), recon_model="r", repair_client=repair, repair_model="p",
        adjudicator_client=None, adjudicator_model=None, sandbox_api_key="k", sandbox_wall_clock_seconds=100, sandbox_runner=runner,
        tavily_client=None, smoke_seconds=0, max_attempts=max_attempts,
        lock_compiler=lambda *a: (LOCK_CALLS.append(a), LockResult(True, ("numpy==1.19.1",), ("numpy",)))[1],
    )
    intake = RepoIntake(tmp_path, "a" * 40, dep_files or {}, declared, (), ("train.py",), None)
    result = run_pipeline(repo_url="https://example.com/r", commit_sha="a" * 40, workdir=tmp_path, intake_result=intake, deps=deps,
                          cost_guard=CostGuard(daily_cost_ceiling_usd=100), run_id="t3")
    assert not results, "not every scripted sandbox result was used"
    return result, repair


def test_the_records_are_the_scenario():
    assert "libgl1-mesa-glx" in APT_LINE and "no installation candidate" in APT_LINE
    assert classifier.classify(100, APT_STDERR, "", declared_deps=()).code == "SYS_LIB_MISSING"  # was RUNTIME_ERROR_OTHER: the time machine was skipped
    assert "fatal: unable to connect to github.com" in GIT_STDERR and "git://github.com/alexlee-gk/lpips-tensorflow.git" in GIT_STDERR


def test_a_renamed_apt_package_is_replaced_in_the_plan_and_the_run_goes_on(tmp_path, monkeypatch):
    monkeypatch.setitem(planner._KNOWN_APT_NEEDS, "somelib", ("libgl1-mesa-glx",))  # the stale name, as the model's enrichment offered it
    result, repair = _run(tmp_path, [_fail(APT_STDERR), _ok()], declared=frozenset({"somelib"}))
    assert repair.calls == [] and result.verdict == "RUNS_AFTER_REPAIR"
    apt = result.certificate()["build_plan"]["apt_install"]
    assert "libgl1" in apt and "libgl1-mesa-glx" not in apt
    action = next(a.time_machine_action for a in result.attempts if a.time_machine_action)
    assert action["rule"] == "apt_package_renamed" and action["from"] == "libgl1-mesa-glx" and action["to"] == "libgl1"
    assert action["matched_error"] == APT_LINE
    assert outcome_levels.dependency_change({"attempts": [a.as_dict() for a in result.attempts]}) == "dependency change: apt libgl1-mesa-glx->libgl1"


def test_a_renamed_package_that_is_not_in_the_plan_is_not_touched(tmp_path):
    fix = install_repair.fix_for(APT_STDERR, planner.BuildPlan("python:3.10-slim", ("libglib2.0-0",), ("true",), "python train.py"), None)
    assert fix is None


def test_git_protocol_lines_go_into_rerun_s_copy_and_git_is_installed(tmp_path):
    result, repair = _run(tmp_path, [_fail(GIT_STDERR), _ok()], dep_files={"requirements.txt": REQ})
    assert repair.calls == [] and result.verdict == "RUNS_AFTER_REPAIR"
    plan = result.certificate()["build_plan"]
    assert "git" in plan["apt_install"]
    install = " ".join(plan["install_commands"])
    assert "git+https://github.com/alexlee-gk/lpips-tensorflow.git#egg=lpips-tf" in install and "git://github.com" not in install.replace("git+https://", "")
    action = next(a.time_machine_action for a in result.attempts if a.time_machine_action)
    assert action["rule"] == "git_protocol_rewrite" and "fatal: unable to connect to github.com" in action["matched_error"]
    assert action["lines"] == [{"from": "git+git://github.com/alexlee-gk/lpips-tensorflow.git#egg=lpips-tf",
                                "to": "git+https://github.com/alexlee-gk/lpips-tensorflow.git#egg=lpips-tf"}]
    assert outcome_levels.dependency_change({"attempts": [a.as_dict() for a in result.attempts]}) == "dependency change: git:// -> https:// in 1 requirement line"
    assert not (tmp_path / ".rerun-requirements.txt").exists()  # the repository tree is never written: the copy is made by the install step


def test_another_host_s_git_protocol_is_left_alone():
    plan = planner.BuildPlan("python:3.10-slim", (), ("pip install -r requirements.txt",), "python train.py")
    log = "git clone git://example.org/x.git did not run successfully\nfatal: unable to connect to example.org\n"
    assert install_repair.fix_for(log, plan, "git+git://example.org/x.git#egg=x\n") is None


def test_each_repair_is_used_once(tmp_path):
    """A second run that fails the same way is not rewritten again: the model is asked."""
    declined = {"cannot_fix": True, "explanation": "nothing to change", "cited_sources": [], "reason_no_citation": "none offered"}
    # baseline, the repair's re-execution, then the era lock's re-execution (it still runs, see the next test), all failing the same way
    result, repair = _run(tmp_path, [_fail(GIT_STDERR), _fail(GIT_STDERR), _fail(GIT_STDERR)], dep_files={"requirements.txt": REQ}, replies=[declined] * 6, max_attempts=1)
    assert sum(1 for a in result.attempts if (a.time_machine_action or {}).get("rule") == "git_protocol_rewrite") == 1
    assert len(repair.calls) >= 1 and result.verdict == "BLOCKED"


def test_the_planner_maps_the_one_stale_name_the_model_offers():
    """Plan creation: the model's enrichment offered `libgl1-mesa-glx` (TEST-B #3); the plan carries `libgl1` and says so."""
    from app.services import recon

    class _Client:
        def chat_completion(self, **kw):
            return json.dumps({"apt_packages": ["libgl1-mesa-glx", "libglib2.0-0"]})

    intake = RepoIntake(Path("."), "a" * 40, {}, frozenset({"opencv-python"}), (), ("train.py",), None)
    plan = planner.build_plan(intake, recon.ReconResult(entrypoint="train.py", confidence=0.9, python_version=None, is_indeterminate=False,
                                                        indeterminate_reason=""), client=_Client(), model="m", cost_guard=CostGuard(daily_cost_ceiling_usd=100))
    assert "libgl1" in plan.apt_install and "libgl1-mesa-glx" not in plan.apt_install
    assert any("libgl1-mesa-glx replaced by libgl1" in n for n in plan.notes)


def test_the_era_lock_still_runs_after_an_install_repair_exposes_another_error(tmp_path):
    """Independent review, finding 2: the first version of T3 skipped the era lock for good once an install repair applied. The repair goes first; the era lock then
    runs on what the repaired plan fails on (here an undeclared numpy), exactly as it would have without the install line problem."""
    numpy_missing = "Traceback (most recent call last):\n  File \"train.py\", line 1, in <module>\nModuleNotFoundError: No module named 'numpy'\n"
    result, repair = _run(tmp_path, [_fail(GIT_STDERR), _fail(numpy_missing), _ok()], dep_files={"requirements.txt": REQ})
    assert repair.calls == [] and result.verdict == "RUNS_AFTER_REPAIR"
    assert len(LOCK_CALLS) == 1  # the era lock ran, after the install repair
    rules = [(a.time_machine_action or {}).get("rule") for a in result.attempts]
    assert rules[0] == "git_protocol_rewrite" and result.attempts[1].time_machine is not None  # the repair, then the era step, in that order


def test_an_apt_package_with_no_known_successor_skips_the_era_lock_and_goes_to_the_model(tmp_path, monkeypatch):
    """Review, finding 8: `libjasper-dev` has no successor; the era lock would only fail at the same apt line."""
    monkeypatch.setitem(planner._KNOWN_APT_NEEDS, "somelib", ("libjasper-dev",))
    stderr = "E: Package 'libjasper-dev' has no installation candidate\n"
    declined = {"cannot_fix": True, "explanation": "nothing to change", "cited_sources": [], "reason_no_citation": "none offered"}
    result, repair = _run(tmp_path, [_fail(stderr)], declared=frozenset({"somelib"}), replies=[declined] * 6, max_attempts=1)
    assert LOCK_CALLS == [] and len(repair.calls) >= 1
    assert "skipped the era lock: an apt package the plan names has no installation candidate" in result.full_log
