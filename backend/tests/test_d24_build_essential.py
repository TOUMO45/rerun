"""harness-v1.3.5-unvalidated (D-24, post-gate, NOT validated by any gate): the deterministic "missing C compiler -> apt
build-essential" rule fires on a SYS_LIB_MISSING classification at repair time, before any model proposal.

Offline: fake model and sandbox; the real classifier, env gate and orchestrator run. The error text is the one recorded for
corpus-v2 entry 7 in the harness-v1.3.4 gate record (read from the committed record, not retyped)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from app.services import classifier
from app.services.cost_guard import CostGuard
from app.services.intake import RepoIntake
from app.services.orchestrator import BUILD_ESSENTIAL_RULE, AttemptRecord, PipelineDeps, missing_compiler_error, run_pipeline
from app.services.sandbox import SandboxRunResult, StepResult
from app.services.time_machine import LockResult

ROOT = Path(__file__).resolve().parents[2]
ENTRY_7 = ROOT / "runs" / "corpus_v2_batch" / "harness-v1.3.4" / "smoke" / "07_albertometelli__pfqi.json"
GCC_ERROR = "unable to execute 'gcc': No such file or directory"
NUMPY_MISSING = "Traceback (most recent call last):\n  File \"train.py\", line 1, in <module>\nModuleNotFoundError: No module named 'numpy'\n"
FFMPEG_MISSING = "/bin/sh: 1: ffmpeg: not found\nerror: metadata-generation-failed\n"


def _entry_7_stderr() -> str:
    """The stderr tail of the re-execution after repair 2 in the v1.3.4 gate record: the run that could not execute gcc."""
    record = json.loads(ENTRY_7.read_text(encoding="utf-8"))
    attempt = next(a for a in record["result"]["attempts"] if a["attempt_number"] == 2)
    assert GCC_ERROR in attempt["stderr_tail"]
    assert any(link["error"] == GCC_ERROR and link["class"] == "SYS_LIB_MISSING" for link in record["result"]["error_chain"])
    return attempt["stderr_tail"]


class _Chat:
    def __init__(self, replies=()):
        self.replies = [json.dumps(r) for r in replies]
        self.calls = []

    def chat_completion(self, **kw):
        self.calls.append(kw)
        if not self.replies:
            raise AssertionError("the model was called: the deterministic rule should have handled this failure")
        return self.replies.pop(0)


def _pipeline(tmp_path, results, replies=(), max_attempts=3):
    (tmp_path / "train.py").write_text("import numpy\nprint('ok')\n", encoding="utf-8", newline="\n")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True, capture_output=True)
    for k, v in (("core.autocrlf", "false"), ("user.email", "t@e.st"), ("user.name", "t")):
        subprocess.run(["git", "config", k, v], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-q", "-m", "x"], cwd=tmp_path, check=True, capture_output=True)
    results = list(results)
    plans = []

    def runner(**kw):
        plans.append(kw)
        return results.pop(0)

    repair = _Chat(replies)
    deps = PipelineDeps(
        recon_client=_Chat([{"entrypoint": "train.py", "confidence": 0.9}]), recon_model="r", repair_client=repair, repair_model="p",
        adjudicator_client=None, adjudicator_model=None, sandbox_api_key="k", sandbox_wall_clock_seconds=100, sandbox_runner=runner,
        tavily_client=None, smoke_seconds=0, max_attempts=max_attempts,
        lock_compiler=lambda *a: LockResult(True, ("numpy==1.19.1",), ("numpy",)),
    )
    intake = RepoIntake(tmp_path, "a" * 40, {}, frozenset(), (), ("train.py",), None)
    result = run_pipeline(repo_url="https://example.com/r", commit_sha="a" * 40, workdir=tmp_path, intake_result=intake, deps=deps,
                          cost_guard=CostGuard(daily_cost_ceiling_usd=100), run_id="d24")
    assert not results, "not every scripted sandbox result was used"
    return result, repair


def _fail(stderr, stdout=""):
    return SandboxRunResult(steps=(StepResult("python train.py", 1, stdout, stderr, 1.0, 0.01),))


def _ok():
    return SandboxRunResult(steps=(StepResult("python train.py", 0, "ok", "", 1.0, 0.01),))


# ---------------------------------------------------------------- the matcher

def test_entry_7s_recorded_error_string_matches_the_rule():
    stderr = _entry_7_stderr()
    classification = classifier.classify(1, stderr, "", declared_deps=())
    assert classification.code == classifier.TaxonomyCode.SYS_LIB_MISSING and classification.evidence == GCC_ERROR
    assert missing_compiler_error(classification) == GCC_ERROR


def test_an_unrelated_sys_lib_missing_string_does_not_match():
    classification = classifier.classify(1, FFMPEG_MISSING, "", declared_deps=())
    assert classification.code == classifier.TaxonomyCode.SYS_LIB_MISSING and "ffmpeg" in classification.evidence
    assert missing_compiler_error(classification) is None
    other = classifier.classify(1, NUMPY_MISSING, "", declared_deps=())
    assert other.code != classifier.TaxonomyCode.SYS_LIB_MISSING and missing_compiler_error(other) is None


# ---------------------------------------------------------------- repair time (D-24)

def test_at_repair_time_the_recorded_gcc_error_adds_build_essential_with_no_model_call(tmp_path):
    """baseline: numpy missing -> time machine (era lock) -> its re-execution cannot execute gcc -> at repair time RERUN adds
    build-essential itself -> the command runs. The fake model client raises if it is ever invoked."""
    result, repair = _pipeline(tmp_path, [_fail(NUMPY_MISSING), _fail(_entry_7_stderr()), _ok()])
    assert repair.calls == []
    assert result.verdict == "RUNS_AFTER_REPAIR"
    step = result.attempts[-1]
    assert (step.origin, step.attempt_number, step.gate_decision, step.exit_code) == ("time_machine", 0, "PASS", 0)
    assert [(c["op"], c["package"]) for c in step.env_delta] == [("apt", "build-essential")]
    assert step.env_delta[0]["evidence"] == GCC_ERROR
    assert result.certificate()["build_plan"]["apt_install"] == ["build-essential"]
    assert all(a.origin == "time_machine" for a in result.attempts)  # no model attempt in the record


def test_the_attempt_record_carries_time_machine_action_with_the_quoted_string(tmp_path):
    result, _ = _pipeline(tmp_path, [_fail(NUMPY_MISSING), _fail(_entry_7_stderr()), _ok()])
    record = result.attempts[-1].as_dict()
    assert record["time_machine_action"] == {"rule": BUILD_ESSENTIAL_RULE, "matched_error": GCC_ERROR, "apt_added": ["build-essential"], "phase": "repair"}
    assert record["origin"] == "time_machine" and record["time_machine"] is None
    stored = result.certificate()["diffs"][-1]
    assert stored["time_machine_action"]["matched_error"] == GCC_ERROR  # in the certificate, so the passport hash covers it


def test_the_deterministic_step_comes_first_and_the_model_gets_what_is_left(tmp_path):
    """After build-essential the run fails on something else: only then is the model asked, about the new failure."""
    fix = {"env_delta": [{"op": "apt", "package": "ffmpeg", "justification": "ffmpeg is missing", "evidence": "/bin/sh: 1: ffmpeg: not found"}],
           "cited_sources": [], "reason_no_citation": "no reference offered", "explanation": "system package"}
    result, repair = _pipeline(tmp_path, [_fail(NUMPY_MISSING), _fail(_entry_7_stderr()), _fail(FFMPEG_MISSING), _ok()], replies=[fix])
    assert len(repair.calls) == 1 and result.verdict == "RUNS_AFTER_REPAIR"
    origins = [(a.origin, a.attempt_number, bool(a.time_machine_action)) for a in result.attempts]
    assert origins == [("time_machine", 0, False), ("time_machine", 0, True), ("model", 1, False)]  # the step did not use up a model attempt
    assert "gcc" not in json.dumps(repair.calls[0]) or "ffmpeg" in json.dumps(repair.calls[0])
    assert sorted(result.certificate()["build_plan"]["apt_install"]) == ["build-essential", "ffmpeg"]


def test_the_rule_fires_once_and_never_proposes_gcc_as_a_pip_package(tmp_path):
    """If the compiler error is still there after build-essential, the rule does not loop: the model is asked."""
    declined = {"cannot_fix": True, "explanation": "nothing to change", "cited_sources": [], "reason_no_citation": "none offered"}
    stderr = _entry_7_stderr()
    result, repair = _pipeline(tmp_path, [_fail(NUMPY_MISSING), _fail(stderr), _fail(stderr)], replies=[declined] * 6, max_attempts=1)
    assert sum(1 for a in result.attempts if a.time_machine_action) == 1 and len(repair.calls) >= 1
    assert result.certificate()["build_plan"]["apt_install"] == ["build-essential"] and result.verdict == "BLOCKED"


def test_an_unrelated_sys_lib_missing_at_repair_time_goes_to_the_model(tmp_path):
    fix = {"env_delta": [{"op": "apt", "package": "ffmpeg", "justification": "ffmpeg is missing", "evidence": "/bin/sh: 1: ffmpeg: not found"}],
           "cited_sources": [], "reason_no_citation": "no reference offered", "explanation": "system package"}
    result, repair = _pipeline(tmp_path, [_fail(NUMPY_MISSING), _fail(FFMPEG_MISSING), _ok()], replies=[fix])
    assert len(repair.calls) == 1
    assert not any(a.time_machine_action for a in result.attempts)
    assert result.certificate()["build_plan"]["apt_install"] == ["ffmpeg"]


# ---------------------------------------------------------------- baseline path (regression)

def test_the_baseline_path_still_adds_build_essential_as_before(tmp_path):
    """A missing compiler at the BASELINE classification: the time machine adds build-essential in its own step (unchanged),
    and the repair-time rule does not fire a second time."""
    result, repair = _pipeline(tmp_path, [_fail(_entry_7_stderr()), _ok()])
    assert repair.calls == [] and result.verdict == "RUNS_AFTER_REPAIR"
    assert len(result.attempts) == 1
    tm = result.attempts[0]
    assert tm.origin == "time_machine" and tm.time_machine["apt_added"] == ["build-essential"] and tm.time_machine["apt_reason"] == GCC_ERROR
    assert tm.time_machine_action is None and "time_machine_action" not in tm.as_dict()
    assert result.certificate()["build_plan"]["apt_install"] == ["build-essential"]


def test_records_without_the_step_serialize_exactly_as_before():
    plain = AttemptRecord(1, "", "PASS", (), 1, "", "").as_dict()
    assert "time_machine_action" not in plain
    assert list(plain) == ["attempt_number", "diff_text", "gate_decision", "gate_violations", "exit_code", "stdout_tail", "stderr_tail",
                           "tavily_sources", "env_delta", "resolved_sources", "origin", "time_machine"]
