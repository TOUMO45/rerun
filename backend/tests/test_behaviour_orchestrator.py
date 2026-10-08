"""harness-v1.10: the behavioural checks inside the repair loop (orchestrator + behaviour.py), against the fake cloud behind the REAL sandbox runner.

A candidate that changes computation is refused BEFORE its run with a named reason (the attempt is a REJECT whose violations carry the reason); a candidate whose patched run does not
reach the failure site it repairs is refused AFTER its run and does not qualify; the tracer's line is taken out of the stderr every later reader sees; the checks are off for a
hand-built `PipelineDeps` (the v1.9 flow) and on for a deployment (Settings.behaviour_checks)."""

from __future__ import annotations

import json

import v140_cloud
from app.config import Settings
from app.services import behaviour, sandbox, smoke_exec
from app.services.cost_guard import CostGuard
from app.services.time_machine import LockResult
from app.services.intake import RepoIntake
from app.services.orchestrator import PipelineDeps, build_pipeline_deps, run_pipeline
from test_v140_pipeline import _Chat, _Ultra, _edit, _head, _repo

FAILURE = "Traceback (most recent call last):\n  File \"main.py\", line 2, in <module>\nNameError: name 'compute' is not defined\n"
ALIVE = "RERUN_SMOKE_ALIVE: still running after 60s with output and no traceback"
APT_CANDIDATE = {"file_edits": None, "cited_sources": [], "reason_no_citation": "none offered", "explanation": "libfoo-dev provides the header",
                 "env_delta": [{"op": "apt", "package": "libfoo-dev", "justification": "the program needs the foo headers",
                                "evidence": "NameError: name 'compute' is not defined"}]}
DECLINE = {"file_edits": None, "env_delta": [], "explanation": "no third fix"}
TRACED = smoke_exec.wrap("python main.py", 60, env=behaviour.TRACE_ENV)
PLAIN = smoke_exec.wrap("python main.py", 60)


def _report(**kw) -> str:
    doc = {"pid": 1, "t0": 1.0, "entry_main": True, "sites": {"main.py:2": 1}, "site_raised": {}, "exit": None, "main_lines": 0, "lines": 9, "argv0": ["main.py"], "argv_changed": None,
           "last": ["main.py", 3], **kw}
    return "\nRERUN_BEHAVIOUR " + json.dumps(doc) + "\n"


def _cloud(monkeypatch, *, report: str):
    def behaviour_of(shell, built, files):
        if shell not in (TRACED, PLAIN, "python main.py"):
            return None
        if not any("numpy==1.19.5" in b for b in built):
            return 1, "", "ModuleNotFoundError: No module named 'numpy'\n"
        if any("libfoo-dev" in b for b in built):
            return 0, ALIVE, report
        return 1, "", FAILURE

    return v140_cloud.install(monkeypatch, behaviour_of)


def _deps(repair, adjudicator, *, checks: bool) -> PipelineDeps:
    return PipelineDeps(
        recon_client=_Chat([{"entrypoint": "main.py", "confidence": 0.9}], "recon"), recon_model="r", repair_client=repair, repair_model="super",
        adjudicator_client=adjudicator, adjudicator_model="ultra", sandbox_api_key="k", sandbox_wall_clock_seconds=600, sandbox_runner=sandbox.run_build_and_execute,
        tavily_client=None, smoke_seconds=60, max_attempts=1, candidates_per_round=3, image_releaser=None, behaviour_checks=checks,
        lock_compiler=lambda *a: LockResult(True, ("numpy==1.19.5",), ("numpy",)))


def _run(tmp_path, deps):
    commit = _head(tmp_path)
    intake = RepoIntake(tmp_path, commit, {}, frozenset(), (), ("main.py",), None)
    guard = CostGuard(daily_cost_ceiling_usd=5.0)
    result = run_pipeline(repo_url="https://example.com/r", commit_sha=commit, workdir=tmp_path, intake_result=intake, deps=deps, cost_guard=guard, run_id="v110",
                          documented_command="python main.py")
    return result, guard


def _fixture(tmp_path):
    _repo(tmp_path, {"main.py": "import numpy\nVALUE = compute()\nprint(VALUE)\n"})


def test_a_candidate_that_changes_computation_is_refused_before_its_run_with_a_named_reason(tmp_path, monkeypatch):
    _fixture(tmp_path)
    cloud = _cloud(monkeypatch, report=_report())
    repair = _Chat([APT_CANDIDATE, _edit("VALUE = compute()\n", "VALUE = 1\n", "replace the call by a constant"), DECLINE], "repair model")
    result, _ = _run(tmp_path, _deps(repair, _Ultra([{"chosen": 1, "reasoning": "the header is what the program needs"}]), checks=True))
    refused = [a for a in result.attempts if a.gate_decision == "REJECT" and a.behaviour]
    assert len(refused) == 1
    rec = refused[0].as_dict()
    assert {v["rule"] for v in rec["gate_violations"]} == {behaviour.COMPUTATION_CHANGED}
    assert rec["behaviour"]["refused"] is True and rec["behaviour"]["static"][0]["reason"] == behaviour.COMPUTATION_CHANGED
    assert not any("VALUE = 1" in (f.decode() if isinstance(f, bytes) else "") for img in cloud.images.values() for f in img["files"].values())  # never run
    # the honest environment candidate was run, traced, adopted
    assert result.verdict == "RUNS_AFTER_REPAIR"
    adopted = next(a for a in result.attempts if a.chosen)
    assert adopted.behaviour["trace"]["status"] == "ok" and adopted.behaviour["trace"]["findings"] == [] and "refused" not in adopted.behaviour
    assert adopted.as_dict()["behaviour"]["trace"]["plan"]["sites"] == [{"file": "main.py", "lines": [2]}]


def test_the_same_candidate_is_not_refused_when_the_checks_are_off_the_v19_flow(tmp_path, monkeypatch):
    _fixture(tmp_path)
    _cloud(monkeypatch, report=_report())
    repair = _Chat([APT_CANDIDATE, _edit("VALUE = compute()\n", "VALUE = 1\n", "replace the call by a constant"), DECLINE], "repair model")
    result, _ = _run(tmp_path, _deps(repair, _Ultra([{"chosen": 1, "reasoning": "the header"}]), checks=False))
    assert all(a.behaviour is None for a in result.attempts)
    assert [a.gate_decision for a in result.attempts if a.origin == "model" and a.gate_decision != "DECLINED"] == ["PASS", "PASS"]


def test_a_patched_run_that_never_reaches_the_failure_site_is_refused_after_its_run(tmp_path, monkeypatch):
    _fixture(tmp_path)
    _cloud(monkeypatch, report=_report(sites={}))
    repair = _Chat([APT_CANDIDATE, DECLINE, DECLINE], "repair model")
    result, _ = _run(tmp_path, _deps(repair, _Ultra(), checks=True))   # the adjudicator is never asked: nothing qualifies
    attempt = next(a for a in result.attempts if a.candidate == 1)
    assert attempt.behaviour["refused"] is True
    assert [f["reason"] for f in attempt.behaviour["trace"]["findings"]] == [behaviour.FAILURE_SITE_NOT_EXECUTED]
    assert attempt.chosen is not True and result.verdict != "RUNS_AFTER_REPAIR"


def test_a_run_whose_report_is_missing_is_recorded_as_missing_and_vetoed_by_nothing(tmp_path, monkeypatch):
    _fixture(tmp_path)
    _cloud(monkeypatch, report="")
    repair = _Chat([APT_CANDIDATE, DECLINE, DECLINE], "repair model")
    result, _ = _run(tmp_path, _deps(repair, _Ultra([{"chosen": 1, "reasoning": "the header"}]), checks=True))
    attempt = next(a for a in result.attempts if a.candidate == 1)
    assert attempt.behaviour["trace"]["status"] == "missing" and "refused" not in attempt.behaviour
    assert result.verdict == "RUNS_AFTER_REPAIR"


def test_the_tracer_line_never_reaches_the_record_and_the_tracer_is_installed_on_the_candidates_branch(tmp_path, monkeypatch):
    _fixture(tmp_path)
    cloud = _cloud(monkeypatch, report=_report())
    repair = _Chat([APT_CANDIDATE, DECLINE, DECLINE], "repair model")
    result, _ = _run(tmp_path, _deps(repair, _Ultra([{"chosen": 1, "reasoning": "the header"}]), checks=True))
    assert all("RERUN_BEHAVIOUR" not in a.stderr_tail for a in result.attempts)
    installs = [c for c in cloud.ran if " behaviour " in c and "RERUN_HOOK" not in c and c.startswith("python3 -c")]
    assert installs, "the tracer was never installed"
    # it was run with RERUN_BEHAVIOUR=1 for the candidate's command only: the sustained run's command (no smoke launcher) carries no such variable
    assert TRACED in cloud.ran and "RERUN_BEHAVIOUR" not in "python main.py"


def test_settings_turn_the_checks_on_for_a_deployment_and_the_dataclass_default_keeps_v19(tmp_path):
    assert Settings().behaviour_checks is True
    assert PipelineDeps.__dataclass_fields__["behaviour_checks"].default is False
    settings = Settings()
    deps = build_pipeline_deps(settings)
    assert deps.behaviour_checks is True
