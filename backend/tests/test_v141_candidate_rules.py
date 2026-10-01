"""harness-v1.4.1-rc, directive item 4 (D-33): the deterministic rules (D-24 build-essential, the CPU shim, the exit-site hook, the exit
wrapper) observe EVERY candidate's failure, not only the adopted one. A rule that fires on a candidate's branch is recorded as
`time_machine_action` on that candidate's attempt, and what it added reaches the run's environment only if that candidate is adopted.

The scenario is corpus-v2 #7, round 2 of the harness-v1.4.0 gate (read from the committed record): one candidate's run reached
`unable to execute 'gcc'`, the adjudicator did not adopt it, and D-24 never saw the error. The gcc text is the one the v1.3.4 gate
recorded for the same entry (the v1.4.0 record's own tail is cut before that line, and its adjudication quotes it)."""

from __future__ import annotations

import json

import pytest

import v140_cloud
from app.services import runner_hooks
from app.services.orchestrator import apt_layer_command
from test_v140_pipeline import (
    ENTRY_11_GPU, EXEC, SHIM, _Chat, _Ultra, _edit, _recorded, _repo, _run,
)
from test_v141_adjudicator import _record_7

GCC = next(a for a in _recorded("07_albertometelli__pfqi")["result"]["attempts"] if a["attempt_number"] == 2)["stderr_tail"]
NAME_ERROR = "Traceback (most recent call last):\n  File \"main.py\", line 2, in <module>\nNameError: name 'compute' is not defined\n"
TYPE_ERROR = "Traceback (most recent call last):\n  File \"main.py\", line 3\nTypeError: print() got nothing\n"
ALIVE = "RERUN_SMOKE_ALIVE: still running after 60s with output and no traceback"
APT_CANDIDATE = {"file_edits": None, "cited_sources": [], "reason_no_citation": "none offered", "explanation": "libfoo-dev provides the header",
                 "env_delta": [{"op": "apt", "package": "libfoo-dev", "justification": "the program needs the foo headers",
                                "evidence": "NameError: name 'compute' is not defined"}]}
DECLINE = {"file_edits": None, "env_delta": [], "explanation": "no third fix"}


def test_the_v140_record_is_the_scenario_a_non_adopted_candidate_reached_gcc_and_no_rule_saw_it():
    attempts = [a for a in _record_7()["result"]["attempts"] if a["attempt_number"] == 2 and a.get("candidate") == 1]
    assert attempts and attempts[0]["chosen"] is False and attempts[0].get("time_machine_action") is None
    assert "unable to execute gcc" in attempts[0]["adjudication"]["reasoning"] and attempts[0]["adjudication"]["chosen"] is None
    assert "unable to execute 'gcc'" in GCC


def _cloud_for_the_gcc_scenario(monkeypatch):
    def behaviour(shell, built, files):
        if shell not in EXEC:
            return None
        if not any("numpy==1.19.5" in b for b in built):
            return 1, "", "ModuleNotFoundError: No module named 'numpy'\n"
        libfoo = any("libfoo-dev" in b for b in built)
        compiler = any("build-essential" in b for b in built)
        if libfoo and not compiler:
            return 1, "", GCC
        if libfoo:
            return 0, ALIVE, ""
        return (1, "", TYPE_ERROR) if "VALUE = 1" in files.get("main.py", b"").decode() else (1, "", NAME_ERROR)

    return v140_cloud.install(monkeypatch, behaviour)


@pytest.mark.parametrize("chosen", [1, 2])
def test_d24_fires_on_a_candidates_gcc_failure_in_its_own_branch_adopted_or_not(tmp_path, monkeypatch, chosen):
    _repo(tmp_path, {"main.py": "import numpy\nVALUE = compute()\nprint(VALUE)\n"})
    cloud = _cloud_for_the_gcc_scenario(monkeypatch)
    repair = _Chat([APT_CANDIDATE, _edit("VALUE = compute()\n", "VALUE = 1\n", "replace the call by a constant"), DECLINE], "repair model")
    ultra = _Ultra([{"chosen": chosen, "reasoning": f"candidate {chosen} is the better change"}])
    result, deps, guard = _run(tmp_path, cloud, repair=repair, adjudicator=ultra, candidates=3, cap=5.0, max_attempts=1)

    cands = {a.candidate: a for a in result.attempts if a.candidate is not None and a.gate_decision == "PASS"}
    one, two = cands[1], cands[2]
    # the rule fired on candidate 1's branch (and only there) and is recorded on that candidate
    action = one.time_machine_action
    assert action["rule"] == "missing_compiler_build_essential" and action["on_candidate"] == 1
    assert "unable to execute 'gcc'" in action["matched_error"] and action["apt_added"] == ["build-essential"]
    assert action["apt_layer"]["layering"] == "additive"
    assert two.time_machine_action is None
    assert one.exit_code == 0 and two.exit_code == 1  # candidate 1's outcome is the run AFTER the rule
    assert [one.chosen, two.chosen] == [chosen == 1, chosen == 2] and one.adjudication["qualifying"] == [1, 2]
    # its two operations: the run, then the rule's step on top of the image the first one built (nothing is installed again)
    first = next(op for op in guard.operations if op["role"] == "repair 1 candidate 1")
    rule_op = next(op for op in guard.operations if op["role"] == "repair 1 candidate 1: missing_compiler_build_essential")
    assert rule_op["candidate"] == 1 and rule_op["branch_from_image"] in first["kept_images"]
    assert rule_op["start_setup_commands"] == first["setup_commands"]
    assert [i["command"] for i in rule_op["install_seconds"]] == [apt_layer_command(["build-essential"])]
    # what the rule added belongs to the run's environment only when that candidate is the adopted one
    plan_apt = result.certificate()["build_plan"]["apt_install"]
    if chosen == 1:
        assert result.verdict == "RUNS_AFTER_REPAIR" and {"libfoo-dev", "build-essential"} <= set(plan_apt)
    else:
        assert result.verdict == "BLOCKED" and "build-essential" not in plan_apt and "libfoo-dev" not in plan_apt


def test_without_the_rule_a_candidate_stuck_on_gcc_would_stay_stuck_the_v140_outcome(tmp_path, monkeypatch):
    """The control: the same candidates with the rule's trigger removed (the failure is not a missing compiler) get no action."""
    _repo(tmp_path, {"main.py": "import numpy\nVALUE = compute()\nprint(VALUE)\n"})

    def behaviour(shell, built, files):
        if shell not in EXEC:
            return None
        if not any("numpy==1.19.5" in b for b in built):
            return 1, "", "ModuleNotFoundError: No module named 'numpy'\n"
        return 1, "", (TYPE_ERROR if any("libfoo-dev" in b for b in built) else NAME_ERROR)

    cloud = v140_cloud.install(monkeypatch, behaviour)
    repair = _Chat([APT_CANDIDATE, _edit("VALUE = compute()\n", "VALUE = 1\n", "constant"), DECLINE], "repair model")
    result, _, guard = _run(tmp_path, cloud, repair=repair, adjudicator=_Ultra([{"chosen": None, "reasoning": "neither"}]), candidates=3,
                            cap=5.0, max_attempts=1)
    assert all(a.time_machine_action is None for a in result.attempts if a.candidate is not None)
    assert not [op for op in guard.operations if ": missing_compiler" in op["role"]]


def test_the_cpu_shim_fires_on_a_candidates_gpu_failure_in_its_own_branch(tmp_path, monkeypatch):
    """Entry 11's recorded GPU error, produced by a candidate that fixed the first error and ran into the next one."""
    _repo(tmp_path, {"main.py": "import numpy\nVALUE = compute()\n"})

    def behaviour(shell, built, files):
        if shell not in EXEC:
            return None
        if not any("numpy==1.19.5" in b for b in built):
            return 1, "", "ModuleNotFoundError: No module named 'numpy'\n"
        if "def compute" in files.get("main.py", b"").decode():
            return (0, ALIVE, "") if SHIM in built else (1, ENTRY_11_GPU["stdout_tail"], ENTRY_11_GPU["stderr_tail"])
        return 1, "", NAME_ERROR

    cloud = v140_cloud.install(monkeypatch, behaviour)
    fix = _edit("import numpy\n", "import numpy\n\n\ndef compute():\n    return 1\n", "define the helper")
    ultra = _Ultra([{"chosen": 1, "reasoning": "the helper is defined"}])
    result, _, guard = _run(tmp_path, cloud, repair=_Chat([fix, DECLINE, DECLINE], "repair model"), adjudicator=ultra, candidates=3,
                            cap=5.0, max_attempts=1)
    one = next(a for a in result.attempts if a.candidate == 1 and a.gate_decision == "PASS")
    assert one.time_machine_action["rule"] == "cpu_shim" and one.time_machine_action["on_candidate"] == 1
    assert "CUDA device" in one.time_machine_action["matched_error"] and one.exit_code == 0 and one.chosen
    assert result.verdict == "RUNS_AFTER_REPAIR"
    # adopted: the shim is now part of the run's environment (a later operation would reopen it, not reinstall it)
    assert SHIM in [command for op in guard.operations for command in [i["command"] for i in op["install_seconds"]]] or any(
        i["command"].startswith(SHIM[:100]) for op in guard.operations for i in op["install_seconds"])


def test_a_rule_that_fires_on_no_candidate_leaves_every_record_unchanged(tmp_path, monkeypatch):
    """No rule matches (plain NameErrors): no action, no extra operation, the v1.4.0 candidate flow."""
    _repo(tmp_path, {"main.py": "import numpy\nVALUE = compute()\n"})

    def behaviour(shell, built, files):
        if shell not in EXEC:
            return None
        if not any("numpy==1.19.5" in b for b in built):
            return 1, "", "ModuleNotFoundError: No module named 'numpy'\n"
        return (0, ALIVE, "") if "def compute" in files.get("main.py", b"").decode() else (1, "", NAME_ERROR)

    cloud = v140_cloud.install(monkeypatch, behaviour)
    fix = _edit("import numpy\n", "import numpy\n\n\ndef compute():\n    return 1\n", "define the helper")
    result, _, guard = _run(tmp_path, cloud, repair=_Chat([fix, DECLINE, DECLINE], "repair model"),
                            adjudicator=_Ultra([{"chosen": 1, "reasoning": "x"}]), candidates=3, cap=5.0, max_attempts=1)
    assert result.verdict == "RUNS_AFTER_REPAIR"
    assert all(a.time_machine_action is None for a in result.attempts if a.candidate is not None)
    assert all(": " not in op["role"].split("candidate")[-1] for op in guard.operations if op["candidate"] is not None)
