"""harness-v1.4.1-rc, directive item 3 (D-32): the candidate adjudicator re-asks once on an invalid reply (both replies recorded) and its
deterministic fallback picks the candidate whose run got furthest by its recorded stage, not the first.

Tested against corpus-v2 #7, round 1 of the harness-v1.4.0 gate, read from the committed record: two candidates changed the exit outcome;
candidate 1 stopped in the package metadata step of the install, candidate 2 finished the install and reached `No module named 'Box2D'`;
Ultra's reply was not valid JSON and RERUN's fallback chose candidate 1."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services import adjudicator
from app.services.adjudicator import adjudicate_candidates, stage_rank

ROOT = Path(__file__).resolve().parents[2]
GATE_V140 = ROOT / "runs" / "corpus_v2_batch" / "harness-v1.4.0" / "gate"


def _record_7() -> dict:
    return json.loads((GATE_V140 / "07_albertometelli__pfqi.json").read_text(encoding="utf-8"))


def _stage_from_operation(op: dict, outcome: str) -> dict:
    """The stage of a run in the terms of `stage_rank`, read from an operation record: the first failing setup step names the phase
    (the command itself ran only when every setup step passed)."""
    steps = op["install_seconds"]
    failing = next((s for s in steps if s["exit_code"] != 0), None)
    return {"phase": failing["phase"] if failing else "repo_run", "setup_completed": sum(1 for s in steps if s["exit_code"] == 0),
            "outcome": outcome, "seconds": 0.0, "exit_code": op["exit_code"]}


def _round_1_candidates() -> list[dict]:
    record = _record_7()
    attempts = {a["candidate"]: a for a in record["result"]["attempts"] if a["attempt_number"] == 1 and a.get("candidate")}
    qualifying = attempts[1]["adjudication"]["qualifying"]
    assert qualifying == [1, 2]  # as recorded: candidate 3's outcome was unchanged
    operations = {op["candidate"]: op for op in record["operations"] if op["role"].startswith("repair 1 candidate")}
    return [{"number": n, "exit_code": attempts[n]["exit_code"], "outcome": attempts[n]["execution"]["outcome"], "diff": "",
             "env_delta": "[]", "output_tail": attempts[n]["stderr_tail"], "explanation": f"candidate {n}",
             "stage": _stage_from_operation(operations[n], attempts[n]["execution"]["outcome"])} for n in qualifying]


class _Replies:
    """A chat client that answers with the given texts in order (and counts the calls)."""

    def __init__(self, *texts):
        self.texts, self.calls = list(texts), []

    def chat_completion(self, **kwargs):
        self.calls.append(kwargs)
        return self.texts.pop(0)


GOOD = json.dumps({"chosen": 2, "reasoning": "candidate 2 installed the packages and got as far as the Box2D import"})
PROSE = 'We are given a failure: "SYS_LIB_MISSING ...". Let us think about the candidates. Candidate 1 ...'


def test_the_recorded_stages_of_entry_7_round_1_put_candidate_2_ahead():
    one, two = _round_1_candidates()
    assert one["stage"]["phase"] == "repo_install" and two["stage"]["phase"] == "repo_run"
    assert "No module named 'Box2D'" in two["output_tail"] and "package metadata" in one["output_tail"]
    assert stage_rank(two["stage"]) > stage_rank(one["stage"])
    assert adjudicator._deterministic_choice([one, two]) == 2


def test_the_v140_record_shows_what_the_fallback_did_then_candidate_1_the_less_advanced_one():
    """The record this fix answers: the adjudicator's reply was not valid JSON, no re-ask, the first qualifying candidate was chosen."""
    adjudication = next(a["adjudication"] for a in _record_7()["result"]["attempts"] if a["attempt_number"] == 1 and a.get("candidate") == 1)
    assert adjudication["chosen"] == 1 and adjudication["fallback"] == "model call failed" and "not valid JSON" in adjudication["reasoning"]


def test_an_invalid_reply_is_re_asked_once_and_both_replies_are_recorded():
    client = _Replies(PROSE, GOOD)
    result = adjudicate_candidates(client, "ultra", "SYS_LIB_MISSING: x", _round_1_candidates())
    assert result.chosen == 2 and result.model_called and not result.fallback
    assert result.reasked and result.replies == (PROSE, GOOD)
    assert len(client.calls) == 2 and "could not be parsed as JSON" in client.calls[1]["user_prompt"]
    assert "could not be parsed" not in client.calls[0]["user_prompt"]
    record = result.as_dict()
    assert record["reasked"] is True and record["replies"] == [PROSE, GOOD] and "fallback" not in record


def test_two_invalid_replies_fall_back_to_the_furthest_stage_not_the_first_and_record_both():
    client = _Replies(PROSE, "still thinking, no JSON here")
    result = adjudicate_candidates(client, "ultra", "SYS_LIB_MISSING: x", _round_1_candidates())
    assert len(client.calls) == 2  # one re-ask, never more
    assert result.chosen == 2 and result.fallback == "reply not valid JSON after a re-ask" and result.reasked
    assert result.replies == (PROSE, "still thinking, no JSON here")
    basis = result.as_dict()["fallback_basis"]
    assert basis["chosen"] == 2 and set(basis["stages"]) == {"1", "2"} and basis["stages"]["2"]["phase"] == "repo_run"
    assert "furthest recorded stage" in result.reasoning


def test_a_valid_first_reply_is_never_re_asked():
    client = _Replies(GOOD)
    result = adjudicate_candidates(client, "ultra", "f", _round_1_candidates())
    assert result.chosen == 2 and not result.reasked and len(client.calls) == 1 and result.replies == (GOOD,)
    assert "reasked" not in result.as_dict()


def test_a_call_failure_other_than_bad_json_is_not_re_asked():
    from app.services.model_client import ModelCallError

    class Broken:
        calls = 0

        def chat_completion(self, **kwargs):
            Broken.calls += 1
            raise ModelCallError("empty message content")

    result = adjudicate_candidates(Broken(), "ultra", "f", _round_1_candidates())
    assert Broken.calls == 1 and result.fallback == "model call failed" and result.chosen == 2 and not result.reasked


def test_an_answer_outside_the_qualifying_candidates_falls_back_by_stage():
    result = adjudicate_candidates(_Replies(json.dumps({"chosen": 7, "reasoning": "x"})), "ultra", "f", _round_1_candidates())
    assert result.chosen == 2 and result.fallback == "answer outside the qualifying candidates"


def test_a_passing_run_is_chosen_before_any_stage_and_ties_go_to_the_lowest_number():
    passing = {"number": 3, "exit_code": 0, "stage": {"phase": "repo_run", "exit_code": 0, "setup_completed": 0}}
    behind = {"number": 1, "exit_code": 1, "stage": {"phase": "repo_install", "exit_code": 1, "setup_completed": 4}}
    assert adjudicator._deterministic_choice([behind, passing]) == 3
    same = {"phase": "repo_run", "exit_code": 1, "outcome": "exited", "seconds": 2.0, "setup_completed": 1}
    assert adjudicator._deterministic_choice([{"number": 2, "exit_code": 1, "stage": same}, {"number": 1, "exit_code": 1, "stage": same}]) == 1
    assert adjudicator._deterministic_choice([{"number": 2, "exit_code": 1}, {"number": 1, "exit_code": 1}]) == 1  # no stage: the first


def test_within_the_same_phase_the_stage_that_ran_longer_or_finished_more_setup_is_further():
    install_2 = {"phase": "repo_install", "setup_completed": 2, "exit_code": 1}
    install_1 = {"phase": "repo_install", "setup_completed": 1, "exit_code": 1}
    quick = {"phase": "repo_run", "setup_completed": 3, "outcome": "exited", "seconds": 0.4, "exit_code": 1}
    longer = {"phase": "repo_run", "setup_completed": 3, "outcome": "exited", "seconds": 19.0, "exit_code": 1}
    alive = {"phase": "repo_run", "setup_completed": 3, "outcome": "failed_while_running", "seconds": 1.0, "exit_code": 1}
    assert stage_rank(install_2) > stage_rank(install_1) and stage_rank(longer) > stage_rank(quick) > stage_rank(install_2)
    assert stage_rank(alive) > stage_rank(longer)
    assert stage_rank({"phase": "runner_setup", "setup_completed": 5, "exit_code": 1}) < stage_rank(install_1)
    assert stage_rank({"phase": "repo_run", "exit_code": 0}) > stage_rank(alive)


def test_no_client_and_no_candidates_keep_their_v140_behaviour():
    none = adjudicate_candidates(None, None, "f", _round_1_candidates())
    assert none.chosen == 2 and not none.model_called and none.fallback == "no adjudicator client"
    empty = adjudicate_candidates(_Replies(), "ultra", "f", [])
    assert empty.chosen is None and not empty.model_called
