"""harness-v1.8 (T1, narrowed by the owner 2026-10-07): "a move is recorded failed only if the error it targeted is still present after applying it. If the run died on a different or
earlier error, record it untested and allow exactly one retry on the winning branch. No change to gate rules."

Evidence: TEST-B #8 CSAILVision/gandissect (now DEV-CONTAMINATED), `runs/corpus_v3_batch/harness-v1.7.2/treatment/08_CSAILVision__gandissect.json`. Round 1, candidate 3 proposed
`apt pkg-config` + `apt libfreetype6-dev`, citing `freetype: no [The C/C++ header for freetype2 (ft2build.h) could not be found...` from the failing log; the adjudicator adopted
candidate 1 (a matplotlib pin); candidate 3's run died elsewhere (the cited line was gone from its output). Every change of a non-adopted candidate whose run did not succeed was
then barred as "already tried and failed this run", and in round 2 (the run now ended on `fatal error: ft2build.h`) `apt libfreetype6-dev` was refused (ENV_REPEATS_FAILED_CHANGE).
`attempts[*].env_delta[*].evidence` is read from that record below.

The scenario here is the same shape with a tool the apt table does not know (ffmpeg), so the deterministic T5 rule does not decide it; the real classifier, env gate, adjudication and
orchestrator run against the fake ConTree cloud. On the harness-v1.7.2 code the run ends BLOCKED (the model's second proposal is refused as a repeat)."""

from __future__ import annotations

import json
from pathlib import Path

import v140_cloud
from app.services import orchestrator
from test_v140_pipeline import EXEC, _Chat, _repo, _run, _Ultra

ROOT = Path(__file__).resolve().parents[2]
GANDISSECT = ROOT / "runs" / "corpus_v3_batch" / "harness-v1.7.2" / "treatment" / "08_CSAILVision__gandissect.json"

WARN = "warning: ffmpeg was not found, video output disabled"
E1 = "AttributeError: module 'platform' has no attribute 'linux_distribution'"
E2 = "FileNotFoundError: [Errno 2] No such file or directory: 'ffmpeg'"
ALIVE = "RERUN_SMOKE_ALIVE: still running after 60s with output and no traceback"
DECLINE = {"file_edits": None, "env_delta": [], "explanation": "no other fix"}
PIN_FOO = {"file_edits": None, "cited_sources": [], "reason_no_citation": "none", "explanation": "foo 1.0 avoids platform.linux_distribution",
           "env_delta": [{"op": "pin", "package": "foo", "version": "1.0", "justification": "foo 1.0 does not call platform.linux_distribution", "evidence": E1}]}
APT_FFMPEG_EARLY = {"file_edits": None, "cited_sources": [], "reason_no_citation": "none", "explanation": "install ffmpeg",
                    "env_delta": [{"op": "apt", "package": "ffmpeg", "justification": "the log says ffmpeg was not found", "evidence": WARN}]}
APT_FFMPEG_LATE = {"file_edits": None, "cited_sources": [], "reason_no_citation": "none", "explanation": "install ffmpeg",
                   "env_delta": [{"op": "apt", "package": "ffmpeg", "justification": "the run now ends on ffmpeg: not found", "evidence": E2}]}


def _cloud(monkeypatch):
    def behaviour(shell, built, files):
        if "apt-get install" in shell and "ffmpeg" in shell:
            return 0, "", ""
        if shell not in EXEC:
            return None
        if not any("numpy==1.19.5" in b for b in built):
            return 1, "", "ModuleNotFoundError: No module named 'numpy'\n"
        foo, ff = any("foo==1.0" in b for b in built), any("ffmpeg" in b for b in built)
        if foo and ff:
            return 0, ALIVE, ""
        if foo:
            return 1, "", f"Traceback (most recent call last):\n  File \"main.py\", line 9, in <module>\n{E2}\n"
        if ff:  # ffmpeg is there, so its warning is gone, and the run dies on the first error as before
            return 1, "", f"Traceback (most recent call last):\n  File \"main.py\", line 4, in <module>\n{E1}\n"
        return 1, "", f"{WARN}\nTraceback (most recent call last):\n  File \"main.py\", line 4, in <module>\n{E1}\n"

    return v140_cloud.install(monkeypatch, behaviour)


def test_the_record_is_the_scenario():
    attempts = json.loads(GANDISSECT.read_text(encoding="utf-8"))["result"]["attempts"]
    cand3 = next(a for a in attempts if a["attempt_number"] == 1 and a["candidate"] == 3)
    freetype = next(c for c in cand3["env_delta"] if c["package"] == "libfreetype6-dev")
    assert "ft2build.h" in freetype["evidence"] and cand3["chosen"] is False and "ft2build" not in cand3["stderr_tail"]  # the cited line is gone from its output
    round2 = next(a for a in attempts if a["attempt_number"] == 2 and a["candidate"] == 1)
    assert round2["gate_decision"] == "REJECT" and "ENV_REPEATS_FAILED_CHANGE" in str(round2["gate_violations"])


def test_evidence_persists_compares_the_cited_line_with_digits_and_paths_blanked():
    from app.services.orchestrator import evidence_persists

    assert evidence_persists(WARN, f"x\n{WARN}\ny")
    assert not evidence_persists(WARN, f"Traceback\n{E1}\n")
    assert evidence_persists("error: command '/tmp/pip-1234/gcc' failed with exit status 1", "error: command '/tmp/pip-98765/gcc' failed with exit status 1")
    assert evidence_persists("", "anything") and evidence_persists("   \n", "anything")  # nothing cited: judged as before (failed)
    assert evidence_persists("ERROR: Failed building wheel for foo", "  error: failed  BUILDING wheel for foo  ")  # whitespace and case


def test_a_change_whose_cited_line_vanished_is_untested_and_may_be_proposed_again(tmp_path, monkeypatch):
    _repo(tmp_path, {"main.py": "import numpy\n"})
    cloud = _cloud(monkeypatch)
    repair = _Chat([PIN_FOO, DECLINE, APT_FFMPEG_EARLY, APT_FFMPEG_LATE, DECLINE, DECLINE, DECLINE, DECLINE, DECLINE, DECLINE], "repair model")
    ultra = _Ultra([{"chosen": 1, "reasoning": "candidate 1 removes the first error"}, {"chosen": 1, "reasoning": "candidate 1 runs"}])
    result, _, _ = _run(tmp_path, cloud, repair=repair, adjudicator=ultra, candidates=3, cap=5.0, max_attempts=2)
    round1 = [a for a in result.attempts if a.attempt_number == 1 and a.candidate == 3][0]
    assert round1.chosen is False and round1.env_outcome == {"apt ffmpeg": "untested"}
    assert round1.as_dict()["env_outcome"] == {"apt ffmpeg": "untested"}
    round2 = [a for a in result.attempts if a.attempt_number == 2 and a.candidate == 1][0]
    assert round2.gate_decision == "PASS" and "ENV_REPEATS_FAILED_CHANGE" not in str(round2.gate_violations)  # not refused as a repeat
    assert result.verdict == "RUNS_AFTER_REPAIR" and "ffmpeg" in result.certificate()["build_plan"]["apt_install"]
    assert "already tried and failed this run (apt ffmpeg)" not in result.full_log


def test_a_change_whose_cited_line_is_still_there_is_failed_and_barred_as_before(tmp_path, monkeypatch):
    """The same candidate, but ffmpeg does not remove the warning (the line it cited is still in the output): failed, and a second proposal is refused."""
    _repo(tmp_path, {"main.py": "import numpy\n"})

    def behaviour(shell, built, files):
        if "apt-get install" in shell and "ffmpeg" in shell:
            return 0, "", ""
        if shell not in EXEC:
            return None
        if not any("numpy==1.19.5" in b for b in built):
            return 1, "", "ModuleNotFoundError: No module named 'numpy'\n"
        if any("foo==1.0" in b for b in built):
            return 1, "", f"Traceback (most recent call last):\n  File \"main.py\", line 9, in <module>\n{E2}\n"
        return 1, "", f"{WARN}\nTraceback (most recent call last):\n  File \"main.py\", line 4, in <module>\n{E1}\n"  # the warning stays whatever is installed

    cloud = v140_cloud.install(monkeypatch, behaviour)
    repair = _Chat([PIN_FOO, DECLINE, APT_FFMPEG_EARLY, APT_FFMPEG_LATE] + [DECLINE] * 12, "repair model")
    ultra = _Ultra([{"chosen": 1, "reasoning": "candidate 1 removes the first error"}] + [{"chosen": None, "reasoning": "nothing ran"}] * 3)
    result, _, _ = _run(tmp_path, cloud, repair=repair, adjudicator=ultra, candidates=3, cap=5.0, max_attempts=2)
    round1 = [a for a in result.attempts if a.attempt_number == 1 and a.candidate == 3][0]
    assert round1.env_outcome == {"apt ffmpeg": "failed"}
    assert result.verdict != "RUNS_AFTER_REPAIR"
    assert "proposal repeats change(s) already tried and failed this run (apt ffmpeg)" in result.full_log  # refused as a repeat, as before


def _change(op="apt", package="ffmpeg", evidence=E2, version=None):
    from app.services.env_repair import EnvChange

    return EnvChange(op=op, package=package, version=version, justification="j", evidence=evidence)


def test_the_retry_is_allowed_once_not_forever():
    """Two untested outcomes bar the move like a failure (`MAX_UNTESTED_ATTEMPTS`), so a change that never reaches its error cannot be proposed for ever."""
    from app.services import env_repair

    assert orchestrator.MAX_UNTESTED_ATTEMPTS == 2
    key = env_repair.change_key(_change())
    failed: set = set()
    untested: dict = {}
    assert not orchestrator.move_barred(key, failed, untested)  # never tried
    untested[key] = 1
    assert not orchestrator.move_barred(key, failed, untested)  # one untested outcome: the one retry is still open
    untested[key] = 2
    assert orchestrator.move_barred(key, failed, untested)  # the second untested outcome bars it
    assert orchestrator.move_barred(key, {key}, {})  # a failure bars at once, as before


def test_a_move_is_failed_when_its_cited_line_persists_untested_when_it_vanished():
    assert orchestrator.move_status(_change(), f"x\n{E2}\n") == "failed"
    assert orchestrator.move_status(_change(), f"Traceback\n{E1}\n") == "untested"
    assert orchestrator.move_status(_change(evidence=""), "anything") == "failed"  # nothing cited: judged as before


def test_a_move_whose_own_install_failed_is_failed_not_untested():
    """review (finding 7): the run died on the change's own install, so it never reached the error the change was for, and the change is at fault."""
    apt_missing = "E: Unable to locate package ffmpeg-nope\nE: Package 'ffmpeg-nope' has no installation candidate"
    change = _change(package="ffmpeg-nope")
    assert orchestrator.move_status(change, f"Traceback\n{E1}\n{apt_missing}") == "failed"  # the cited line is gone, but the apt name does not exist
    assert orchestrator.move_status(_change(op="pin", package="foo", version="9.9.9"), f"Traceback\n{E1}\n", self_inflicted_package="foo") == "failed"
    assert orchestrator.move_status(_change(op="pin", package="foo", version="9.9.9"), f"Traceback\n{E1}\n", self_inflicted_package="bar") == "untested"
    assert orchestrator.move_status(_change(op="pip", package="x", evidence=E1), f"Traceback\n{E2}\n") == "untested"  # a different error, no own failure
