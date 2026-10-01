"""harness-v1.4.2-rc: what the independent review of the Step 1 diff found, each with the test that pins its fix.

1. A run that PASSED is never "partial progress" (the adjudicator's veto of a pass stands), and a silent run that was still running is not an advance
   over a quick exit.
2. A candidate whose run the sandbox KILLED is adopted over a "none", so the entry ends INDETERMINATE (RESOURCE_LIMIT), not BLOCKED.
3. The baseline-kill evidence run is recorded among the attempts, not only quoted.
4. The evidence run is not made for a kill during setup (the sandbox never reaches the command), cannot turn a decided RESOURCE_LIMIT into an error, and is
   not made for a wrapped run that exited 0.
5. The kill found by the evidence run is a link of the error chain, attributed to the sandbox.
6. The certificate prose and the batch summaries know RESOURCE_LIMIT and EXIT_OUTSIDE_PYTHON.
7. The evidence command does not depend on the shell's wording of `ulimit -a`, and reads the process's own cgroup.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

import v140_cloud
from app.services import adjudicator, runner_hooks
from app.services.adjudicator import adjudicate_candidates, partial_progress_choice, templated_certificate_prose
from app.services.cost_guard import OperationBudgetExhausted
from app.services.infra import InfraError
from test_v140_pipeline import EXEC, _Chat, _edit, _repo, _run, _Ultra
from test_v141_exit_wrapper import BARE_EXIT, NO_KILL_EVIDENCE, SKLEARN_MISSING, _decoded, _is_wrapped, _silent_cloud
from test_v142_resource_limit import _cloud_11, evidence_block

ROOT = Path(__file__).resolve().parents[2]
NONE = json.dumps({"chosen": None, "reasoning": "neither candidate is a repair"})

SETUP0 = {"phase": "repo_install", "setup_completed": 0, "exit_code": 1}
RUN_QUICK = {"phase": "repo_run", "setup_completed": 3, "outcome": "exited", "seconds": 0.2, "exit_code": 1}
RUN_ALIVE = {"phase": "repo_run", "setup_completed": 3, "outcome": "failed_while_running", "seconds": 1.0, "exit_code": 1}
PASSED = {"phase": "repo_run", "setup_completed": 3, "outcome": "exited", "seconds": 5.0, "exit_code": 0}


class _Replies:
    def __init__(self, *replies):
        self.replies, self.calls = list(replies), []

    def chat_completion(self, **kw):
        self.calls.append(kw)
        return self.replies.pop(0)


# --- 1. partial progress ----------------------------------------------------------------------------------------------------

def test_a_run_that_passed_is_never_partial_progress_so_the_adjudicators_veto_stands():
    candidates = [{"number": 1, "exit_code": 0, "stage": PASSED}]
    assert partial_progress_choice(SETUP0, candidates) is None and partial_progress_choice(RUN_QUICK, candidates) is None
    result = adjudicate_candidates(_Replies(NONE), "ultra", "f", candidates, current_stage=RUN_QUICK)
    assert result.chosen is None and result.adopted_reason == ""  # v1.4.1 ended BLOCKED here; v1.4.2-rc as first written adopted the pass


def test_a_silent_run_that_was_still_running_is_not_an_advance_over_a_quick_exit():
    assert partial_progress_choice(RUN_QUICK, [{"number": 1, "exit_code": 1, "stage": RUN_ALIVE}]) is None
    assert adjudicator.advance_key(RUN_QUICK) == adjudicator.advance_key(RUN_ALIVE)
    # a real advance (install step -> the repository's own command) is still adopted
    assert partial_progress_choice(SETUP0, [{"number": 2, "exit_code": 1, "stage": RUN_ALIVE}])["number"] == 2


# --- 2. a killed candidate ----------------------------------------------------------------------------------------------------

def test_a_killed_candidate_is_adopted_over_a_none_and_the_lowest_killed_number_wins():
    candidates = [{"number": 1, "exit_code": 1, "stage": RUN_QUICK}, {"number": 2, "exit_code": 137, "stage": RUN_QUICK, "resource_kill": True},
                  {"number": 3, "exit_code": 137, "stage": RUN_QUICK, "resource_kill": True}]
    result = adjudicate_candidates(_Replies(NONE), "ultra", "f", candidates, current_stage=RUN_QUICK)
    assert result.chosen == 2 and result.adopted_reason == "resource kill" and "INDETERMINATE (RESOURCE_LIMIT)" in result.reasoning
    # the model's own choice is respected
    chosen = adjudicate_candidates(_Replies(json.dumps({"chosen": 1, "reasoning": "x"})), "ultra", "f", candidates, current_stage=RUN_QUICK)
    assert chosen.chosen == 1 and chosen.adopted_reason == "adjudicator"
    # no kill, no partial progress: still none
    plain = [{"number": 1, "exit_code": 1, "stage": RUN_QUICK}]
    assert adjudicate_candidates(_Replies(NONE), "ultra", "f", plain, current_stage=RUN_QUICK).chosen is None


def test_a_killed_candidate_the_adjudicator_would_not_adopt_ends_the_entry_indeterminate_not_blocked(tmp_path, monkeypatch):
    """The review's scenario: the current failure is a NameError; candidate 1 fixes it and is killed (137); Ultra says none; the stage is the same, so
    partial progress cannot adopt it. v1.4.2-rc as first written asked the model four more times and ended BLOCKED."""
    _repo(tmp_path, {"main.py": "import numpy\nVALUE = compute()\n"})

    def behaviour(shell, built, files):
        command = _decoded(shell)
        if shell not in EXEC and "RERUN_EVIDENCE_BEGIN" not in command:
            return None
        if not any("numpy==1.19.5" in b for b in built):
            return 1, "", "ModuleNotFoundError: No module named 'numpy'\n"
        if b"def compute" in files.get("main.py", b""):
            return 137, "", "Killed\n"
        return 1, "", "Traceback (most recent call last):\n  File \"main.py\", line 2, in <module>\nNameError: name 'compute' is not defined\n"

    cloud = v140_cloud.install(monkeypatch, behaviour)
    fix = _edit("import numpy\n", "import numpy\n\n\ndef compute():\n    return 1\n", "define the helper")
    decline = {"file_edits": None, "env_delta": [], "explanation": "nothing else"}
    repair = _Chat([fix, decline, decline], "repair model")  # a fourth call (a second round) raises
    ultra = _Ultra([{"chosen": None, "reasoning": "the run was killed; this does not show a repair"}])
    result, _, _ = _run(tmp_path, cloud, repair=repair, adjudicator=ultra, candidates=3, cap=5.0, max_attempts=2)
    assert result.verdict == "INDETERMINATE" and result.taxonomy_code == "RESOURCE_LIMIT", result.full_log[-1500:]
    assert len(repair.calls) == 3  # one round only
    killed = next(a for a in result.attempts if a.candidate == 1 and a.gate_decision == "PASS")
    assert killed.exit_code == 137 and killed.adjudication["adopted_reason"] == "resource kill" and killed.chosen is True


# --- 3. the baseline kill ----------------------------------------------------------------------------------------------------

def test_the_evidence_run_of_a_baseline_kill_is_recorded_among_the_attempts(tmp_path, monkeypatch):
    _repo(tmp_path, {"main.py": "import numpy\n"})
    block = evidence_block()

    def behaviour(shell, built, files):
        command = _decoded(shell)
        if shell in EXEC or "RERUN_EVIDENCE_BEGIN" in command:
            return 137, "", "Killed\n" + (block if "RERUN_EVIDENCE_BEGIN" in command else "")
        return None

    cloud = v140_cloud.install(monkeypatch, behaviour)
    result, _, guard = _run(tmp_path, cloud, repair=_Chat([], "repair model"))
    assert result.verdict == "INDETERMINATE" and result.taxonomy_code == "RESOURCE_LIMIT"
    evidence = [a for a in result.attempts if a.time_machine_action and a.time_machine_action["rule"] == "resource_evidence"]
    assert len(evidence) == 1 and evidence[0].time_machine_action["kill_evidenced"] is True
    assert sum(1 for op in guard.operations if op["role"] == "resource evidence") == 1


# --- 4. the evidence run: when it is not made, and when it fails ----------------------------------------------------------------

def test_a_kill_during_setup_makes_no_evidence_run_because_the_sandbox_never_reaches_the_command(tmp_path, monkeypatch):
    _repo(tmp_path, {"main.py": "import numpy\n"})

    def behaviour(shell, built, files):
        if "pip install" in shell and "numpy==1.19.5" in shell:
            return 137, "", "Killed\n"  # the era install is killed: a setup step
        if shell in EXEC:
            return 1, "", "ModuleNotFoundError: No module named 'numpy'\n"
        return None

    cloud = v140_cloud.install(monkeypatch, behaviour)
    result, _, guard = _run(tmp_path, cloud, repair=_Chat([], "repair model"))
    assert result.verdict == "INDETERMINATE" and result.taxonomy_code == "RESOURCE_LIMIT", result.full_log[-1500:]
    assert not [op for op in guard.operations if "evidence" in op["role"]]  # no money spent on a run that cannot print the block
    assert "No evidence was read" in result.indeterminate_reason and "never reached" in result.indeterminate_reason
    assert not [a for a in result.attempts if a.time_machine_action and a.time_machine_action["rule"] == "resource_evidence"]


@pytest.mark.parametrize("error", [InfraError("sandbox", "the sandbox API failed"), RuntimeError("plain sandbox failure"), OperationBudgetExhausted("no money left for it")])
def test_a_failed_evidence_run_never_changes_a_decided_resource_limit(tmp_path, monkeypatch, error):
    """InfraError would have become INFRA_ERROR, a plain error PIPELINE_ERROR, a budget stop COST_CAP; the kill is already decided."""
    _repo(tmp_path, {"main.py": "import torch\nimport tqdm\ntorch.load('model.pt')\n"})
    inner = _cloud_11(monkeypatch, evidence=evidence_block())
    original = inner.behaviour

    def failing(shell, built, files):
        if "RERUN_EVIDENCE_BEGIN" in _decoded(shell):
            raise error
        return original(shell, built, files)

    inner.behaviour = failing
    result, _, _ = _run(tmp_path, inner, repair=_Chat([], "repair model"))
    assert result.verdict == "INDETERMINATE" and result.taxonomy_code == "RESOURCE_LIMIT", result.full_log[-1500:]
    assert "No evidence was read: the evidence run did not complete" in result.indeterminate_reason
    stopped = next(a.time_machine_action for a in result.attempts if a.time_machine_action and a.time_machine_action["rule"] == "resource_evidence")
    assert "did not complete" in stopped["stopped"]


def test_a_wrapped_run_that_exits_zero_is_a_pass_and_is_not_sent_for_evidence(tmp_path, monkeypatch):
    _repo(tmp_path, {"main.py": BARE_EXIT})

    def behaviour(shell, built, files):
        if shell in EXEC or _is_wrapped(shell):
            if not any("numpy==1.19.5" in b for b in built):
                return 1, "", SKLEARN_MISSING
            if _is_wrapped(shell):
                return 0, "", ""  # the wrapped run exits 0 and prints nothing (the first run failed silently, e.g. a flaky exit)
            return 1, "", ""
        return None

    cloud = v140_cloud.install(monkeypatch, behaviour)
    result, _, guard = _run(tmp_path, cloud, repair=_Chat([], "repair model"))
    assert result.verdict == "RUNS_AFTER_REPAIR", result.full_log[-1500:]
    assert not [op for op in guard.operations if "evidence" in op["role"]]
    wrapper = next(a.time_machine_action for a in result.attempts if a.time_machine_action and a.time_machine_action["rule"] == "exit_wrapper")
    assert wrapper["result"] == "the wrapped run exited 0"


# --- 5. the error chain ------------------------------------------------------------------------------------------------------

def test_a_kill_found_by_the_evidence_run_is_a_sandbox_link_in_the_error_chain(tmp_path, monkeypatch):
    killed = NO_KILL_EVIDENCE.replace("oom_kill 0", "oom_kill 1")
    _repo(tmp_path, {"main.py": BARE_EXIT})
    cloud = _silent_cloud(monkeypatch, wrapper_prints=False, evidence=killed)
    result, _, _ = _run(tmp_path, cloud, repair=_Chat([], "repair model"))
    assert result.taxonomy_code == "RESOURCE_LIMIT"
    last = result.error_chain[-1]
    assert last["class"] == "RESOURCE_LIMIT" and last["attribution"] == "SANDBOX_QUOTA"


# --- 6. prose and summaries ---------------------------------------------------------------------------------------------------

def test_the_certificate_prose_says_what_happened_for_the_new_reason_codes():
    kill = templated_certificate_prose("INDETERMINATE", "RESOURCE_LIMIT", 0, "RESOURCE_LIMIT: exit code 137")
    assert "killed the process" in kill and "Recon could not establish" not in kill and "nothing is claimed" in kill
    outside = templated_certificate_prose("INDETERMINATE", "RUNTIME_ERROR_OTHER", 0, "EXIT_OUTSIDE_PYTHON: exit outside Python — ...")
    assert "cannot say why it exited" in outside and "Recon could not establish" not in outside
    other = templated_certificate_prose("INDETERMINATE", None, 0, "")
    assert "Recon could not establish" in other  # unchanged for the cases that did not change
    assert not adjudicator.makes_reproduction_claim(kill) and not adjudicator.makes_reproduction_claim(outside)


def _view(verdict, reason="", first_repo_error=None):
    return {"verdict": verdict, "klass": "", "reason_code": reason, "first_repo_error": first_repo_error, "attributions": [], "spent": 0.0, "attempts": 0,
            "tavily": False}


def test_a_resource_limit_is_sandbox_side_and_an_unexplained_exit_is_not_measured_in_the_batch_summaries():
    sys.path.insert(0, str(ROOT / "scripts"))
    import compare_batches

    control = _view("BLOCKED", "", first_repo_error="NameError")
    assert compare_batches.categorize(control, _view("INDETERMINATE", "RESOURCE_LIMIT: exit code 137")) == "SANDBOX_SIDE"
    assert compare_batches.categorize(control, _view("INDETERMINATE", "EXIT_OUTSIDE_PYTHON: exit outside Python")) == "NOT_MEASURED"
    assert compare_batches.categorize(control, _view("BLOCKED", "")) == "REPO_STILL_FAILING"  # unchanged
    import run_corpus_v1_batch

    source = (ROOT / "scripts" / "run_corpus_v1_batch.py").read_text(encoding="utf-8")
    assert '"RESOURCE_LIMIT"' in source and '"EXIT_OUTSIDE_PYTHON"' in source and run_corpus_v1_batch is not None


# --- 7. the evidence command --------------------------------------------------------------------------------------------------

def test_the_evidence_command_does_not_filter_ulimit_by_one_shells_wording_and_reads_the_processs_own_cgroup():
    suffix = runner_hooks._EVIDENCE_SUFFIX
    assert "ulimit -a 2>&1 | head" in suffix and "grep -E \"core file size" not in suffix  # dash prints `memory(kbytes)`, bash `max memory size`
    assert "/proc/self/cgroup" in suffix and '"$cg/memory.max"' in suffix and '"$cg/memory.events"' in suffix


def test_the_larger_oom_kill_count_of_the_roots_and_the_processs_own_cgroup_counts():
    block = ("RERUN_EVIDENCE_BEGIN exit_status=1\n--cgroup\n/sys/fs/cgroup/memory.events=low 0 high 0 max 0 oom 0 oom_kill 0 \n"
             "/sys/fs/cgroup/system.slice/job/memory.events=low 0 high 0 max 3 oom 2 oom_kill 2 \n--dmesg\nRERUN_EVIDENCE_END\n")
    evidence = runner_hooks.parse_evidence(block)
    assert evidence["oom_kill"] == 2 and runner_hooks.kill_evidenced(evidence)
    # dash's wording of ulimit is kept whole
    dash = "RERUN_EVIDENCE_BEGIN exit_status=1\n--ulimit\nmemory(kbytes) unlimited\nvmemory(kbytes) unlimited\n--meminfo\nRERUN_EVIDENCE_END\n"
    assert runner_hooks.parse_evidence(dash)["ulimit"] == ["memory(kbytes) unlimited", "vmemory(kbytes) unlimited"]
