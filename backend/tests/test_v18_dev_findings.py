"""harness-v1.8: what the DEV re-runs of the 21 old held-out entries (2026-10-07, `runs/dev_v18/`, DEV-CONTAMINATED) showed about the diagnosis, and the fixes made for it.

One defect, three records. A rule that says "RERUN already fixed X" read an OLD line of the record and claimed the run still ended on it:
  - TEST-B #3 video_prediction: RERUN rewrote `git://` to `https://`; the clone worked; the run ended on a different build error; the diagnosis still said "change git:// to https://".
  - TEST #13 neo_gnns and TEST #19 RBP: RERUN's apt step added `build-essential`; the next operation was stopped by the spend cap, so no run showed anything; the diagnosis said the
    apt step "did not help" (the run "still ends on the same error").
  - TEST-B #2 ovis: RERUN pinned the final release of a pre-release pin; the pair then conflicted with the pinned torch (ResolutionImpossible); the diagnosis still said "pin the final release".
The rules now say what the run after the step showed: nothing (stopped), a different error (the step worked), or the same one (the step did not help). Also new, from the same records:
a spend-cap stop is added to the last known blocker instead of replacing it, a TIMEOUT verdict gets a diagnosis, and three evidence rules (a pin pair that cannot install together, a
build that fails after the apt step, a requirement string current setuptools rejects)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services import blocker, diagnosis
from test_v18_diagnosis import ROOT, _attempt, _chain

DEV = ROOT / "runs" / "dev_v18" / "round1"
needs_dev = pytest.mark.skipif(not DEV.is_dir(), reason="the DEV records are not in this checkout")


def _dev(rel: str) -> dict:
    d = json.loads(next(iter(sorted(DEV.glob(rel)))).read_text(encoding="utf-8"))
    r, cert = d["result"], d["certificate"]
    return {"verdict": r["verdict"], "error_chain": r["error_chain"], "attempts": r["attempts"], "indeterminate_reason": r.get("indeterminate_reason") or "",
            "baseline": cert.get("baseline"), "full_log": cert.get("full_log")}


def _step(rule: str, apt: list[str], stderr: str = "", stopped: str = "") -> dict:
    a = _attempt(1, stderr=stderr)
    a["origin"] = "time_machine"
    a["time_machine_action"] = {"rule": rule, "apt_added": apt, **({"stopped": stopped} if stopped else {})}
    return a


# --------------------------------------------------------------------------------------------------------------------- the records

@needs_dev
def test_video_prediction_after_the_rewrite_the_diagnosis_names_the_error_the_run_ended_on():
    rec = _dev("TEST-B/03_*.json")
    assert rec["verdict"] == "BLOCKED" and rec["error_chain"][-1]["class"] == "DEP_BUILD_FAILED"
    out = blocker.report(rec)
    assert out["cause"] == "REQUIREMENT_STRING_INVALID" and "InvalidRequirement" in out["error_line"]
    assert "git://" not in out["next_action"] and out["dependency_change"].startswith("dependency change: git://")  # the rewrite is shown as the label, not as the advice
    assert any('python_version>"3.7"' in b["quote"] for b in out["basis"])  # the offending string is quoted from the same output


@needs_dev
def test_neo_gnns_and_rbp_a_step_whose_run_was_stopped_is_untested_and_the_cap_is_added_not_substituted():
    for rel, line in (("TEST/13_*.json", "which', 'g++'"), ("TEST/19_*.json", "'g++' failed")):
        out = blocker.report(_dev(rel))
        assert out["cause"] == "SYSTEM_PACKAGE_ADDED_UNTESTED" and out["fixable_by"] == "deterministic" and "did not help" not in out["next_action"], rel
        assert line in out["error_line"] and out["stopped_by"]["cause"] == "COST_CAP" and "spend cap then stopped the run" in out["next_action"]
        assert any(b["source"] == "indeterminate_reason" for b in out["basis"])


@needs_dev
def test_gandissect_a_build_that_fails_after_the_apt_step_says_so():
    out = blocker.report(_dev("TEST-B/08_*.json"))
    assert out["cause"] == "BUILD_FAILS_AFTER_APT_STEP" and "./configure" in out["error_line"] and "`build-essential`" in out["what_a_human_must_supply"]
    assert "nothing, if the apt rule adds" not in out["what_a_human_must_supply"]  # the class default the record had just contradicted


@needs_dev
def test_ovis_a_relaxed_pin_that_cannot_install_beside_the_pinned_torch_is_a_conflict_not_a_missing_pin():
    out = blocker.report(_dev("TEST-B/02_*.json"))
    assert out["cause"] == "PINS_CONFLICT" and out["error_line"].startswith("ERROR: Cannot install torch==1.5.1, torchvision==0.6.0")
    assert "RERUN had pinned `torchvision==0.6.0`" in out["what_a_human_must_supply"] and "pin `torchvision==0.6.0`" not in out["next_action"]


def test_the_old_neo_gnns_record_keeps_its_compiler_diagnosis_with_the_cap_added():
    """The pre-committed key's E-T13 (the harness-v1.5 TEST record: COST_CAP after `which g++`): still the compiler, now with the cap stated beside it."""
    d = json.loads((ROOT / "runs/corpus_v2_batch/harness-v1.5-final/test/13_seongjunyun__neo_gnns.json").read_text(encoding="utf-8"))
    out = blocker.report({"verdict": d["result"]["verdict"], "error_chain": d["result"]["error_chain"], "attempts": d["result"]["attempts"],
                          "indeterminate_reason": d["result"]["indeterminate_reason"], "baseline": d["certificate"].get("baseline"), "full_log": d["certificate"].get("full_log")})
    assert out["cause"] == "SYSTEM_PACKAGE_MISSING" and "g++" in out["error_line"] and out["stopped_by"]["cause"] == "COST_CAP"


# --------------------------------------------------------------------------------------------------------------------- the rules, on small inputs

GIT_FATAL = "fatal: unable to connect to github.com:"


def test_git_rewrite_applied_and_a_different_final_error_is_not_a_git_diagnosis():
    rewrite = _step("git_protocol_rewrite", [], stderr=f"Running command git clone git://github.com/a/b.git\n{GIT_FATAL}")
    rec = {"verdict": "BLOCKED", "error_chain": _chain("ValueError: bad metadata", "DEP_BUILD_FAILED", "repo_install"),
           "attempts": [rewrite, _attempt(2, stderr="ValueError: bad metadata\n")]}
    assert diagnosis.diagnose(rec) is None


def test_git_rewrite_applied_and_the_clone_still_failing_is_said_as_such():
    rewrite = _step("git_protocol_rewrite", [], stderr=f"Running command git clone https://github.com/a/b.git\n{GIT_FATAL}")
    rec = {"verdict": "BLOCKED", "error_chain": _chain(GIT_FATAL, "DEP_BUILD_FAILED", "repo_install"), "attempts": [rewrite]}
    f = diagnosis.diagnose(rec)
    assert f.cause == "GIT_CLONE_STILL_FAILS" and f.error_line == GIT_FATAL and "rewrote" in f.sentence


def test_git_without_a_rewrite_is_read_as_before():
    rec = {"verdict": "BLOCKED", "error_chain": _chain("error: subprocess-exited-with-error", "DEP_BUILD_FAILED", "repo_install"),
           "attempts": [_attempt(1, stderr=f"Running command git clone git://github.com/a/b.git\n{GIT_FATAL}\n")]}
    assert diagnosis.diagnose(rec).cause == "GIT_PROTOCOL_RETIRED"


def test_the_apt_step_states_stopped_observed_same_and_different():
    link = _chain("subprocess.CalledProcessError: Command '['which', 'g++']' returned non-zero exit status 1.", "DEP_BUILD_FAILED", "repo_install")
    gpp = "error: command 'g++' failed: No such file or directory\n"
    stopped = {"verdict": "BLOCKED", "error_chain": link, "attempts": [_step("missing_compiler_build_essential", ["build-essential"], stderr=gpp, stopped="stopped before completion: cap")]}
    assert diagnosis.diagnose(stopped).cause == "SYSTEM_PACKAGE_ADDED_UNTESTED"  # the step's run did not finish: nothing observed (the tail is from BEFORE the step)
    same = {"verdict": "BLOCKED", "error_chain": link, "attempts": [_step("missing_compiler_build_essential", ["build-essential"], stderr=gpp)]}
    f = diagnosis.diagnose(same)
    assert f.cause == "SYSTEM_PACKAGE_DID_NOT_HELP" and "still ends on the same error" in f.sentence  # the run after the step shows g++ missing again
    moved = {"verdict": "BLOCKED", "error_chain": link, "attempts": [_step("missing_compiler_build_essential", ["build-essential"], stderr="ValueError: something else\n")]}
    assert diagnosis.diagnose(moved) is None  # the need is gone: the step worked and the run ended on something other than a compiler
    never = {"verdict": "BLOCKED", "error_chain": link, "attempts": []}
    assert diagnosis.diagnose(never).cause == "SYSTEM_PACKAGE_MISSING"  # RERUN's step never ran in this record: as before


def test_a_pins_conflict_needs_the_run_to_end_on_a_resolution_conflict():
    conflict = "ERROR: Cannot install torch==1.5.1, torchvision==0.6.0 because these package versions have conflicting dependencies.\nERROR: ResolutionImpossible: for help visit https://x\n"
    ended = {"verdict": "INDETERMINATE", "error_chain": _chain("ERROR: ResolutionImpossible: for help visit https://x", "DEP_UNPINNED_CONFLICT", "runner_setup"),
             "attempts": [_attempt(1, stderr=conflict)]}
    assert diagnosis.diagnose(ended).cause == "PINS_CONFLICT"
    other = {"verdict": "BLOCKED", "error_chain": _chain("AttributeError: module 'tensorflow' has no attribute 'flags'", "API_REMOVED"), "attempts": [_attempt(1, stderr=conflict)]}
    assert diagnosis.diagnose(other) is None  # a failed candidate's install is not the run's blocker


def test_an_invalid_requirement_string_is_quoted_from_the_same_output():
    err = ("      packaging.requirements.InvalidRequirement: Expected end or semicolon (after name and no valid version specifier)\n"
           "          python_version>\"3.7\"\n                        ^\n")
    rec = {"verdict": "BLOCKED", "error_chain": _chain("packaging._tokenizer.ParserSyntaxError: Expected end or semicolon", "DEP_BUILD_FAILED", "repo_install"),
           "attempts": [_attempt(1, stderr=err)]}
    f = diagnosis.diagnose(rec)
    assert f.cause == "REQUIREMENT_STRING_INVALID" and "`python_version>\"3.7\"`" in f.sentence and f.error_line.endswith("(after name and no valid version specifier)")
    assert diagnosis.diagnose({**rec, "error_chain": _chain("ValueError: x", "RUNTIME_ERROR_OTHER")}) is None


# --------------------------------------------------------------------------------------------------------------------- the stops

def test_a_cap_stop_with_no_error_chain_is_still_a_stop_of_its_own():
    reason = ("COST_CAP: a sandbox operation reached its budget-derived limit of 253s; not resumed: $0.0000 left funds 0s, below one operation (80s) "
              "— RERUN's per-entry / per-operation spend cap stopped the run; not a verdict on the repository.")
    out = blocker.report({"verdict": "INDETERMINATE", "error_chain": [], "attempts": [], "indeterminate_reason": reason})
    assert out["cause"] == "COST_CAP" and out["fixable_by"] == "platform" and out["error_line"].startswith("a sandbox operation reached") and "RERUN's per-entry" not in out["error_line"]


def test_a_timeout_verdict_has_a_diagnosis_that_does_not_claim_what_it_did_not_see():
    out = blocker.report({"verdict": "TIMEOUT", "error_chain": [], "attempts": [],
                          "full_log": "[sandbox] execution error: sandbox execution exceeded 600.0s wall clock: Operation x has timed out"})
    assert out["cause"] == "TIMEOUT" and out["error_line"].endswith("Operation x has timed out") and "does not show whether the program started" in out["next_action"]
    bare = blocker.report({"verdict": "TIMEOUT", "error_chain": [], "attempts": []})
    assert bare["cause"] == "TIMEOUT" and "wall-clock limit" in bare["error_line"]
    assert blocker.report({"verdict": "RUNS_CLEAN", "error_chain": [], "attempts": []}) is None


def test_the_conflict_line_that_used_to_be_a_class_default_row_is_now_evidence_driven():
    """test_v16_harness's DEP_UNPINNED_CONFLICT row used pip's `Cannot install A and B ... conflicting dependencies` line and expected the class sentence."""
    out = blocker.report({"verdict": "BLOCKED", "attempts": [], "error_chain": _chain(
        "ERROR: Cannot install tensorboard==2.1.0 and tensorflow==1.15.5 because these package versions have conflicting dependencies.", "DEP_UNPINNED_CONFLICT", "repo_install")})
    assert out["cause"] == "PINS_CONFLICT" and out["diagnosis"] == "evidence" and "`tensorboard==2.1.0 and tensorflow==1.15.5`" in out["what_a_human_must_supply"]
    assert out["class"] == "DEP_UNPINNED_CONFLICT"  # the class is unchanged


# --------------------------------------------------------------------------------------------------------------------- the embedded runtime seen through a stand-in

BPY_TAIL = ('Traceback (most recent call last):\n  File "/utils.py", line 55, in create_camera\n    camera = bpy.data.cameras.new("Camera")\n'
            "AttributeError: 'NoneType' object has no attribute 'cameras'\n")
NONE_ATTR = "AttributeError: 'NoneType' object has no attribute 'objects'"


def test_a_package_main_run_as_a_file_names_the_module_form():
    """D-50, the out-of-sample steamctl: `python steamctl/__main__.py` cannot import `steamctl`; the class default blamed the release."""
    miss = "ModuleNotFoundError: No module named 'steamctl'"
    rec = {"verdict": "BLOCKED", "error_chain": _chain(miss, "DEP_MISSING"), "attempts": [], "baseline": {"execute_command": "python steamctl/__main__.py"}}
    f = diagnosis.diagnose(rec)
    assert f.cause == "PACKAGE_MAIN_RUN_AS_FILE" and "python -m steamctl" in f.next_action and f.error_line == miss
    # another package missing, or another command shape: not this rule
    assert diagnosis.diagnose({**rec, "error_chain": _chain("ModuleNotFoundError: No module named 'numpy'", "DEP_MISSING")}) is None
    assert diagnosis.diagnose({**rec, "baseline": {"execute_command": "python main.py"}}) is None
    assert diagnosis.diagnose({**rec, "baseline": {"execute_command": "python -m steamctl"}}) is None
    assert diagnosis.diagnose({**rec, "baseline": None}) is None


def test_a_nonetype_error_whose_traceback_line_reaches_bpy_is_the_embedded_runtime():
    """DEV re-run of osm-heatmap (2026-10-07): the run ended on a NoneType error (the stand-in `bpy.data` is None), not on `module 'bpy' has no attribute`."""
    rec = {"verdict": "BLOCKED", "error_chain": _chain(NONE_ATTR, "RUNTIME_ERROR_OTHER"), "attempts": [_attempt(1, stderr=BPY_TAIL)]}
    f = diagnosis.diagnose(rec)
    assert f.cause == "EMBEDDED_RUNTIME_REQUIRED" and f.error_line == NONE_ATTR and "Blender" in f.sentence and "blender --background" in f.next_action
    assert any("bpy.data.cameras" in b["quote"] for b in f.basis)  # the traceback's own source line is quoted
    # the same record shape, but the `bpy` mention is in an OLDER attempt and the run ended elsewhere: no claim
    older = {"verdict": "BLOCKED", "error_chain": _chain(NONE_ATTR, "RUNTIME_ERROR_OTHER"),
             "attempts": [_attempt(1, stderr=BPY_TAIL), _attempt(2, stderr="ValueError: something else\n")]}
    assert diagnosis.diagnose(older) is None
    # a NoneType error with no embedded module anywhere is an ordinary error
    plain = {"verdict": "BLOCKED", "error_chain": _chain(NONE_ATTR, "RUNTIME_ERROR_OTHER"), "attempts": [_attempt(1, stderr="  x = cfg.get('a').objects\n" + NONE_ATTR + "\n")]}
    assert diagnosis.diagnose(plain) is None
