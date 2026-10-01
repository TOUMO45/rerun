"""harness-v1.4.2-rc, directive item 1 (D-37): when no candidate passes, the adjudicator adopts the candidate with the furthest recorded stage, provided it
strictly advances past the failure being repaired; adopted_reason = "partial progress"; the next round starts from that candidate's kept image.

Anchor: corpus-v2 #7, harness-v1.4.1 gate, rounds 1-3, read from the committed record: in every round the one qualifying candidate had moved the failure
on (`pkg-config: not found` -> `No module named 'Box2D'`; apt packages, then pygame's missing-library list) and Ultra chose none because the run still failed."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import v140_cloud
from app.services import adjudicator
from app.services.adjudicator import adjudicate_candidates, advance_key, partial_progress_choice
from test_v140_pipeline import EXEC, _Chat, _Ultra, _repo, _run
from test_v141_adjudicator import _Replies, _stage_from_operation

ROOT = Path(__file__).resolve().parents[2]
GATE_V141 = ROOT / "runs" / "corpus_v2_batch" / "harness-v1.4.1" / "gate"


def _record_7() -> dict:
    return json.loads((GATE_V141 / "07_albertometelli__pfqi.json").read_text(encoding="utf-8"))


def _rounds() -> dict[int, list[dict]]:
    """For each round: the qualifying candidates in `adjudicate_candidates` form, their stages read from the operation records."""
    record = _record_7()
    attempts = [a for a in record["result"]["attempts"] if a["origin"] == "model"]
    ops = {op["role"]: op for op in record["operations"] if "wall_seconds" in op}
    out = {}
    for rnd in (1, 2, 3):
        adjudication = next(a["adjudication"] for a in attempts if a["attempt_number"] == rnd and a.get("adjudication"))
        cands = []
        for n in adjudication["qualifying"]:
            a = next(x for x in attempts if x["attempt_number"] == rnd and x.get("candidate") == n)
            cands.append({"number": n, "exit_code": a["exit_code"], "outcome": a["execution"]["outcome"], "diff": "", "env_delta": "[]",
                          "output_tail": a["stderr_tail"], "explanation": f"candidate {n}",
                          "stage": _stage_from_operation(ops[f"repair {rnd} candidate {n}"], a["execution"]["outcome"])})
        out[rnd] = cands
    return out


def _current_stage_in_the_recorded_world() -> dict:
    """The failure every round repaired in the record, because nothing was ever adopted: the era operation (`pkg-config: not found`, in setup)."""
    record = _record_7()
    era = next(op for op in record["operations"] if op["role"] == "re-execution")
    attempt = next(a for a in record["result"]["attempts"] if a["origin"] == "time_machine")
    return _stage_from_operation(era, attempt["execution"]["outcome"])


NONE = json.dumps({"chosen": None, "reasoning": "the run still fails"})


def test_entry_7_rounds_1_to_3_each_qualifying_candidate_strictly_advanced_and_is_adopted_for_partial_progress():
    current = _current_stage_in_the_recorded_world()
    assert current["phase"] == "repo_install" and current["setup_completed"] == 0
    rounds = _rounds()
    assert {k: [c["number"] for c in v] for k, v in rounds.items()} == {1: [2], 2: [3], 3: [1]}
    assert rounds[1][0]["stage"]["phase"] == "repo_run" and "Box2D" in rounds[1][0]["output_tail"]  # Box2D is further than pkg-config
    for rnd, cands in rounds.items():
        result = adjudicate_candidates(_Replies(NONE), "ultra", "SYS_LIB_MISSING: pkg-config: not found", cands, current_stage=current)
        assert result.chosen == cands[0]["number"], (rnd, result.as_dict())
        assert result.adopted_reason == "partial progress" and result.model_called
        record = result.as_dict()
        assert record["adopted_reason"] == "partial progress" and record["partial_progress"]["current"] == current
        assert "partial progress" in record["reasoning"] and "the run still fails" in record["reasoning"]  # Ultra's own words are kept


def test_without_the_current_stage_the_v141_behaviour_stays_adopt_nothing():
    rounds = _rounds()
    result = adjudicate_candidates(_Replies(NONE), "ultra", "f", rounds[1])
    assert result.chosen is None and result.adopted_reason == ""


def test_once_candidate_2_is_adopted_the_next_rounds_candidates_that_only_reach_the_same_stage_are_not():
    """Round 2's candidate 3 reaches Box2D again (the stage the adopted candidate already holds): sideways, not adopted. Round 3's candidate 1 fails in
    setup, behind the adopted stage: not adopted either."""
    rounds = _rounds()
    adopted = rounds[1][0]["stage"]
    assert partial_progress_choice(adopted, rounds[2]) is None and partial_progress_choice(adopted, rounds[3]) is None
    result = adjudicate_candidates(_Replies(NONE), "ultra", "f", rounds[2], current_stage=adopted)
    assert result.chosen is None and result.adopted_reason == ""


def test_the_adjudicators_own_choice_is_unchanged_and_labelled():
    cands = _rounds()[1]
    chosen = adjudicate_candidates(_Replies(json.dumps({"chosen": 2, "reasoning": "x"})), "ultra", "f", cands, current_stage=_current_stage_in_the_recorded_world())
    assert chosen.chosen == 2 and chosen.adopted_reason == "adjudicator"
    fallback = adjudicate_candidates(_Replies("prose", "prose again"), "ultra", "f", cands, current_stage=_current_stage_in_the_recorded_world())
    assert fallback.chosen == 2 and fallback.adopted_reason.startswith("fallback: reply not valid JSON")


def test_the_stage_order_the_rule_uses():
    setup0 = {"phase": "repo_install", "setup_completed": 0, "exit_code": 1}
    setup2 = {"phase": "repo_install", "setup_completed": 2, "exit_code": 1}
    run_quick = {"phase": "repo_run", "setup_completed": 3, "outcome": "exited", "seconds": 0.2, "exit_code": 1}
    run_long = {"phase": "repo_run", "setup_completed": 3, "outcome": "exited", "seconds": 50.0, "exit_code": 1}
    run_alive = {"phase": "repo_run", "setup_completed": 3, "outcome": "failed_while_running", "seconds": 1.0, "exit_code": 1}
    passed = {"phase": "repo_run", "exit_code": 0}
    assert advance_key(setup0) < advance_key(setup2) < advance_key(run_quick) < advance_key(passed)
    assert advance_key(run_quick) == advance_key(run_alive)  # still running when it failed is not progress (independent review)
    assert advance_key(run_quick) == advance_key(run_long)  # a longer run is not progress: the coarse key ignores seconds
    assert partial_progress_choice(run_quick, [{"number": 1, "stage": run_long}]) is None
    assert partial_progress_choice(setup0, [{"number": 1, "stage": setup0}, {"number": 2, "stage": setup2}, {"number": 3, "stage": run_quick}])["number"] == 3
    assert partial_progress_choice(setup0, [{"number": 4, "stage": run_quick}, {"number": 2, "stage": run_quick}])["number"] == 2  # ties: the lowest number
    assert partial_progress_choice(setup0, []) is None and partial_progress_choice(None, [{"number": 1, "stage": setup0}]) is not None


# --- the pipeline: adopted, applied, and the next round starts from it --------------------------------------------------------

SETUP_ERROR = "error: command 'foo-config' not found: please install the foo headers first\n"
NAME_ERROR = "Traceback (most recent call last):\n  File \"main.py\", line 2, in <module>\nNameError: name 'compute' is not defined\n"


def _env(package: str) -> dict:
    return {"file_edits": None, "cited_sources": [], "reason_no_citation": "none offered", "explanation": f"add {package}",
            "env_delta": [{"op": "add", "package": package, "justification": f"{package} provides foo-config",
                           "evidence": "please install the foo headers first"}]}


def test_a_candidate_that_gets_the_run_past_setup_is_adopted_for_partial_progress_and_round_2_starts_from_its_image(tmp_path, monkeypatch):
    from test_v140_pipeline import _edit

    _repo(tmp_path, {"main.py": "import numpy\nVALUE = compute()\n"})

    def behaviour(shell, built, files):
        if "pip install" in shell and "numpy==1.19.5" in shell and "foopkg" not in shell:
            return 1, "", SETUP_ERROR  # the era lock cannot be installed: the failure is in setup
        if shell in EXEC:
            if not any("foopkg" in b for b in built):
                return 1, "", "ModuleNotFoundError: No module named 'numpy'\n"
            if b"def compute" in files.get("main.py", b""):
                return 0, "RERUN_SMOKE_ALIVE: still running after 60s with output and no traceback", ""
            return 1, "", NAME_ERROR
        return None

    cloud = v140_cloud.install(monkeypatch, behaviour)
    declines = {"file_edits": None, "env_delta": [], "explanation": "no further fix"}
    fix = _edit("import numpy\n", "import numpy\n\n\ndef compute():\n    return 1\n", "define the missing helper")
    repair = _Chat([_env("foopkg"), _env("barpkg"), declines,  # round 1: candidate 1 gets past setup, candidate 2 does not, candidate 3 declines
                    fix, declines, declines], "repair model")  # round 2: candidate 1 fixes the NameError the adopted environment now shows
    ultra = _Ultra([{"chosen": None, "reasoning": "neither candidate makes the command run"}, {"chosen": 1, "reasoning": "defines the helper"}])
    result, _, guard = _run(tmp_path, cloud, repair=repair, adjudicator=ultra, candidates=3, cap=5.0, max_attempts=2)
    assert result.verdict == "RUNS_AFTER_REPAIR", result.full_log[-1800:]
    cands = {(a.attempt_number, a.candidate): a for a in result.attempts if a.candidate is not None and a.gate_decision == "PASS"}
    one, two = cands[(1, 1)], cands[(1, 2)]
    assert one.chosen is True and two.chosen is False
    assert one.adjudication["adopted_reason"] == "partial progress" and one.adjudication["chosen"] == 1
    assert one.adjudication["partial_progress"]["current"]["phase"] == "repo_install"
    assert one.adjudication["partial_progress"]["chosen"]["phase"] == "repo_run"
    assert two.exit_code == 1 and "foo headers" in two.stderr_tail  # candidate 2 stayed in setup: not adopted
    # adopted: the plan carries candidate 1's change and not candidate 2's
    plan = json.dumps(result.certificate()["build_plan"])
    assert "foopkg" in plan and "barpkg" not in plan
    # round 2 starts from the adopted candidate's environment: its operation branches from an image the adopted candidate's operation kept
    adopted_op = next(op for op in guard.operations if op["role"] == "repair 1 candidate 1")
    round_2 = [op for op in guard.operations if op["role"].startswith("repair 2")]
    assert round_2 and all(op["branch_from_image"] in adopted_op["kept_images"] for op in round_2), (
        adopted_op["kept_images"], [o["branch_from_image"] for o in round_2])
    assert "(partial progress)" in result.full_log
