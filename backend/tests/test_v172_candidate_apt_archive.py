"""harness-v1.7.2 (D-48): R4's archive rewrite reached only the main loop, so a repair candidate's own `apt install` on an end-of-life Debian
image met the 404 mirror and the candidate was judged on RERUN's missing rewrite. Live scan v1.7.2b, insta-dl (record below): candidate 1's
`apt python3-tk`, the right idea, failed with the bullseye security mirror's 404s, the adjudicator adopted nothing, and the run ended BLOCKED.

Now the step runs on that candidate's own branch (a recorded deterministic action, no model call), and an adopted candidate carries it into
the run. The replay uses the record's own stderr. On the code before the fix the candidate stays at exit 100 and nothing is adopted."""

from __future__ import annotations

import json
from pathlib import Path

import v140_cloud
from app.services import classifier, runner_env
from test_v140_pipeline import EXEC, _Chat, _Ultra, _repo, _run

ROOT = Path(__file__).resolve().parents[2]
RECORD = ROOT / "runs" / "live_scan" / "v1.7.2b" / "2026-10-05_sdushantha__insta-dl_api_certificate.json"
MIRROR_404 = next(d for d in json.loads(RECORD.read_text(encoding="utf-8"))["diffs"]
                  if d.get("candidate") == 1 and d.get("exit_code") == 100)["stderr_tail"]
TK_MISSING = "Traceback (most recent call last):\n  File \"main.py\", line 1, in <module>\nImportError: libtk8.6.so: cannot open shared object file: No such file or directory\n"
ALIVE = "RERUN_SMOKE_ALIVE: still running after 60s with output and no traceback"
APT_TK = {"file_edits": None, "cited_sources": [], "reason_no_citation": "none offered", "explanation": "python3-tk provides libtk8.6",
          "env_delta": [{"op": "apt", "package": "python3-tk", "justification": "Tk library for Python 3", "evidence": "ImportError: libtk8.6.so"}]}
DECLINE = {"file_edits": None, "env_delta": [], "explanation": "no other fix"}


def _cloud(monkeypatch):
    """The image is bullseye: an apt install reaches the archive only behind the rewrite step; Tk loads once python3-tk is installed."""
    def behaviour(shell, built, files):
        if "apt-get install" in shell and "python3-tk" in shell:
            if runner_env.APT_ARCHIVE_MARKER in shell:
                return 0, "", f"{runner_env.APT_ARCHIVE_MARKER} bullseye\n"
            return 100, "", MIRROR_404
        if shell not in EXEC:
            return None
        if not any("numpy==1.19.5" in b for b in built):
            return 1, "", "ModuleNotFoundError: No module named 'numpy'\n"
        tk = any("python3-tk" in b and runner_env.APT_ARCHIVE_MARKER in b for b in built)
        return (0, ALIVE, "") if tk else (1, "", TK_MISSING)

    return v140_cloud.install(monkeypatch, behaviour)


def test_the_record_is_the_scenario_the_candidates_apt_install_met_the_gone_mirror():
    assert classifier.classify(100, MIRROR_404, "").code == classifier.TaxonomyCode.APT_MIRROR_GONE
    assert "security.debian.org" in MIRROR_404 and "404" in MIRROR_404


def test_the_archive_step_runs_on_the_candidates_branch_and_the_adopted_candidate_keeps_it(tmp_path, monkeypatch):
    _repo(tmp_path, {"main.py": "import numpy\nimport tkinter\n"})
    cloud = _cloud(monkeypatch)
    repair = _Chat([APT_TK, DECLINE, DECLINE], "repair model")
    ultra = _Ultra([{"chosen": 1, "reasoning": "candidate 1 installs the Tk library and the program now runs"}])
    result, _, guard = _run(tmp_path, cloud, repair=repair, adjudicator=ultra, candidates=3, cap=5.0, max_attempts=1)

    one = next(a for a in result.attempts if a.candidate == 1 and a.gate_decision == "PASS")
    action = one.time_machine_action
    assert action["rule"] == "apt_archive" and action["on_candidate"] == 1
    assert action["fires_on"] == "APT_MIRROR_GONE on a repair candidate's branch"
    assert "404" in action["matched_error"] and action["rewrote"] == ["bullseye"]
    assert one.exit_code == 0 and one.chosen  # the candidate is judged on the run after the rewrite
    assert result.verdict == "RUNS_AFTER_REPAIR"
    # the step ran once, on the candidate's branch, and only in front of the candidate's apt command
    assert [op["role"] for op in guard.operations].count("repair 1 candidate 1: apt_archive") == 1
    archived = [c for c in cloud.ran if runner_env.APT_ARCHIVE_MARKER in c]
    assert archived and all("python3-tk" in c for c in archived)
    # adopted: the run's build plan names the rewrite, as the main-loop step does
    assert any("apt_archive (harness-v1.7, R4)" in n for n in result.build_plan["notes"])


def test_a_candidate_that_still_fails_after_the_step_is_not_retried_again(tmp_path, monkeypatch):
    """Once per candidate: a second gone-mirror failure on the same branch is the candidate's outcome (no loop, no model call)."""
    _repo(tmp_path, {"main.py": "import numpy\nimport tkinter\n"})

    def behaviour(shell, built, files):
        if "apt-get install" in shell and "python3-tk" in shell:
            return 100, "", MIRROR_404  # the archive does not serve it either
        if shell not in EXEC:
            return None
        if not any("numpy==1.19.5" in b for b in built):
            return 1, "", "ModuleNotFoundError: No module named 'numpy'\n"
        return 1, "", TK_MISSING

    cloud = v140_cloud.install(monkeypatch, behaviour)
    repair = _Chat([APT_TK, DECLINE, DECLINE], "repair model")
    ultra = _Ultra([{"chosen": None, "reasoning": "nothing ran"}])
    result, _, guard = _run(tmp_path, cloud, repair=repair, adjudicator=ultra, candidates=3, cap=5.0, max_attempts=1)
    one = next(a for a in result.attempts if a.candidate == 1 and a.gate_decision == "PASS")
    assert one.time_machine_action["rule"] == "apt_archive" and one.exit_code == 100
    assert [op["role"] for op in guard.operations].count("repair 1 candidate 1: apt_archive") == 1
    assert result.verdict != "RUNS_AFTER_REPAIR"


def test_d45_the_main_loop_step_records_the_codename_its_install_step_printed(tmp_path):
    """harness-v1.7.2 (D-45): round 5, entry #16 recorded `rewrote: []` although the step ran: the marker is printed by the install step and
    only the final (execute) step's output was read."""
    from app.services.sandbox import SandboxRunResult, StepResult
    from test_v17_apt_archive import R16, _apt_failure, _apt_pipeline, _recorded_attempt

    after = SandboxRunResult(steps=(
        StepResult("apt-get update && apt-get install -y libgl1", 0, "", f"{runner_env.APT_ARCHIVE_MARKER} bullseye\n", 11.4, 0.01, phase="repo_install"),
        StepResult("python train.py", 0, "1\n", "", 1.0, 0.01),
    ))
    result, _, _, left = _apt_pipeline(tmp_path, [_apt_failure(_recorded_attempt(R16)), after])
    assert not left and result.verdict == "RUNS_AFTER_REPAIR"
    step = next(a for a in result.attempts if (a.time_machine_action or {}).get("rule") == "apt_archive")
    assert step.time_machine_action["rewrote"] == ["bullseye"]


def test_an_adopted_branch_whose_step_rewrote_nothing_does_not_switch_the_run_to_the_archive(tmp_path, monkeypatch):
    """Review finding: on a live release (or a dead third-party source) the step rewrites nothing; if that branch is adopted, the run must not claim the
    archive rewrite in its plan notes or keep the step for later apt commands."""
    _repo(tmp_path, {"main.py": "import numpy\nimport tkinter\n"})

    def behaviour(shell, built, files):
        if "apt-get install" in shell and "python3-tk" in shell:
            return (0, "", "") if runner_env.APT_ARCHIVE_MARKER in shell else (100, "", MIRROR_404)  # a transient 404; the step prints nothing
        if shell not in EXEC:
            return None
        if not any("numpy==1.19.5" in b for b in built):
            return 1, "", "ModuleNotFoundError: No module named 'numpy'\n"
        return (0, ALIVE, "") if any("python3-tk" in b for b in built) else (1, "", TK_MISSING)

    cloud = v140_cloud.install(monkeypatch, behaviour)
    repair = _Chat([APT_TK, DECLINE, DECLINE], "repair model")
    ultra = _Ultra([{"chosen": 1, "reasoning": "candidate 1 runs"}])
    result, _, _ = _run(tmp_path, cloud, repair=repair, adjudicator=ultra, candidates=3, cap=5.0, max_attempts=1)
    one = next(a for a in result.attempts if a.candidate == 1 and a.gate_decision == "PASS")
    assert one.time_machine_action["rule"] == "apt_archive" and one.time_machine_action["rewrote"] == [] and one.chosen
    assert not any("apt_archive (harness-v1.7, R4)" in n for n in result.build_plan["notes"])
