"""harness-v1.4.3-rc, D-41 and D-42 end to end offline: the real orchestrator and the real sandbox runner against the fake ConTree cloud (v140_cloud), which applies the client's
output limit like the real API.

The chain is corpus-v2 #3's, as the probe of 2026-10-02 found it: the as-published run fails on a missing module, the era environment is built, and the era run prints
hundreds of kilobytes of download progress and then a CUDA traceback (`.cuda()` on a CPU-only torch). Until v1.4.3 the API returned the first 65,535 bytes of that stream and the
harness read "exit code 1, no error text" (EXIT_OUTSIDE_PYTHON in every version)."""

from __future__ import annotations

import v140_cloud
from app.services import runner_hooks, sandbox
from app.services.orchestrator import OUTPUT_TRUNCATED_REASON_CODE, command_image, output_cut_without_error, reason_code_of
from app.services.sandbox import SandboxRunResult, StepResult
from test_v140_pipeline import EXEC, SHIM, SKLEARN_MISSING, _repo, _run
from test_v143_output_limit import _progress, _real_traceback

ALIVE = "RERUN_SMOKE_ALIVE: still running after 60s with output and no traceback"


def _cloud_3(monkeypatch, tmp_path, *, stderr: str | None = None):
    _repo(tmp_path, {"main.py": "import torch\nimport sklearn\nmodel = torch.nn.Linear(1, 1).cuda()\n"})
    big = stderr if stderr is not None else _progress(35000) + "\n" + _real_traceback()

    def behaviour(shell, built, files):
        if shell not in EXEC:
            return None
        if not any("numpy==1.19.5" in b for b in built):
            return 1, "", SKLEARN_MISSING  # the as-published run
        if SHIM not in built:
            return 1, "", big  # the era run: progress, then the CUDA traceback
        return 0, ALIVE, ""

    return v140_cloud.install(monkeypatch, behaviour)


# --- the fix: the chain that ended EXIT_OUTSIDE_PYTHON now reaches the CPU shim ---------------------------------------------

def test_entry_3s_cuda_error_behind_200_kb_of_progress_is_seen_and_the_cpu_shim_answers_it(tmp_path, monkeypatch):
    cloud = _cloud_3(monkeypatch, tmp_path)
    result, deps, guard = _run(tmp_path, cloud)  # the repair model raises if it is ever called
    assert deps.repair_client.calls == []
    assert result.verdict == "RUNS_AFTER_REPAIR"
    shim = result.attempts[-1]
    assert shim.time_machine_action["rule"] == "cpu_shim" and "CUDA" in shim.time_machine_action["matched_error"]
    era = guard.operations[1]
    assert era["streams"]["stderr"]["bytes"] > 200_000 and era["streams"]["stderr"]["truncated"] is False
    assert era["streams"]["limit_bytes"] == sandbox.OUTPUT_LIMIT_BYTES
    assert not any("exit_wrapper" in a.time_machine_action.get("rule", "") for a in result.attempts if a.time_machine_action)  # no hook, no wrapper, no evidence run


def test_the_same_chain_with_the_old_limit_ends_output_truncated_not_exit_outside_python(tmp_path, monkeypatch):
    """The finding, reproduced: with the SDK's 65,535-byte limit the era run's stream is cut before the traceback. The harness now says so (INDETERMINATE OUTPUT_TRUNCATED), spends
    no model attempt and runs no hook, wrapper or evidence run on a stream that proves nothing."""
    monkeypatch.setattr(sandbox, "OUTPUT_LIMIT_BYTES", 65535)
    cloud = _cloud_3(monkeypatch, tmp_path)
    result, deps, guard = _run(tmp_path, cloud)
    assert result.verdict == "INDETERMINATE" and deps.repair_client.calls == []
    assert result.indeterminate_reason.startswith("OUTPUT_TRUNCATED: ") and reason_code_of(result.indeterminate_reason) == OUTPUT_TRUNCATED_REASON_CODE
    assert "65535 bytes returned" in result.indeterminate_reason and "not a verdict on the repository" in result.indeterminate_reason
    assert "EXIT_OUTSIDE_PYTHON" not in result.indeterminate_reason
    assert SHIM not in cloud.ran and not any(runner_hooks.EXIT_HOOK_MARKER in c for c in cloud.ran)
    era = guard.operations[1]
    assert era["streams"]["stderr"]["truncated"] is True and era["streams"]["stderr"]["bytes"] == 65535


def test_a_cut_stream_that_already_holds_an_error_is_classified_as_before(tmp_path, monkeypatch):
    """The label is only for a cut that hides the answer: a traceback in the returned start keeps its ordinary classification and its ordinary repair path."""
    monkeypatch.setattr(sandbox, "OUTPUT_LIMIT_BYTES", 4000)
    cloud = _cloud_3(monkeypatch, tmp_path, stderr=_real_traceback() + _progress(3000))
    result, deps, guard = _run(tmp_path, cloud)
    assert result.verdict == "RUNS_AFTER_REPAIR" and result.attempts[-1].time_machine_action["rule"] == "cpu_shim"
    assert guard.operations[1]["streams"]["stderr"]["truncated"] is True  # still recorded: the claim rests on the returned start, and the record says so


# --- the helpers ------------------------------------------------------------------------------------------------------------

def _step(code=1, stdout="", stderr="", out_cut=False, err_cut=False, phase="repo_run") -> StepResult:
    return StepResult("cmd", code, stdout, stderr, 1.0, 0.01, phase, False, out_cut, err_cut)


def test_output_cut_without_error_needs_a_failure_a_cut_and_no_error_in_what_came_back():
    cut = SandboxRunResult(steps=(_step(stderr=_progress(50), err_cut=True),))
    reason = output_cut_without_error(cut)
    assert reason.startswith("OUTPUT_TRUNCATED: the command exited with code 1") and "stderr stream" in reason and f"{sandbox.OUTPUT_LIMIT_BYTES} bytes" in reason
    assert output_cut_without_error(SandboxRunResult(steps=(_step(stderr=_progress(50), err_cut=False),))) is None  # nothing was cut: a silent exit is a silent exit
    assert output_cut_without_error(SandboxRunResult(steps=(_step(code=0, stderr=_progress(50), err_cut=True),))) is None  # a pass
    assert output_cut_without_error(SandboxRunResult(steps=(_step(stderr=_real_traceback(), err_cut=True),))) is None  # the error is in the start
    assert output_cut_without_error(SandboxRunResult(steps=())) is None
    both = output_cut_without_error(SandboxRunResult(steps=(_step(stdout="x" * 10, stderr=_progress(5), out_cut=True, err_cut=True),)))
    assert "stdout and stderr stream" in both and "stdout 10 bytes returned, stderr" in both


def test_command_image_is_the_image_that_holds_everything_the_command_ran_on():
    setup = ("apt step", "pip step")
    layers = (((), "tree"), (("apt step",), "apt"), (setup, "env"))
    final = SandboxRunResult(steps=(_step(code=0),), layers=layers, setup_commands=setup, ran_setup=setup)
    assert command_image(final) == "env"  # the layer holding every setup command
    assert command_image(SandboxRunResult(steps=(_step(code=0),), layers=layers, setup_commands=setup, result_image="result")) == "result"
    patched = SandboxRunResult(steps=(_step(code=0),), layers=layers, setup_commands=setup, rerun_steps=(_step(phase="rerun_branch"),))
    assert command_image(patched) is None  # a patch overlay ran and its image was not kept: the environment layer lacks the patch
    branch = SandboxRunResult(steps=(_step(code=0),), branch_from_image="start", setup_commands=setup, ran_setup=())
    assert command_image(branch) == "start"  # the operation started from an image that already held every setup command
    partial = SandboxRunResult(steps=(_step(code=0),), branch_from_image="start", setup_commands=setup, ran_setup=("pip step",))
    assert command_image(partial) is None  # it ran setup on top of the start image but kept no layer: nothing holds it
    assert command_image(SandboxRunResult(steps=(_step(code=0),))) is None


# --- D-42: the smoke attempt records the image it ran on --------------------------------------------------------------------

def test_the_smoke_attempt_that_passed_names_the_image_the_sustained_run_reopens(tmp_path, monkeypatch):
    cloud = _cloud_3(monkeypatch, tmp_path)
    result, _, guard = _run(tmp_path, cloud)
    final = result.attempts[-1]
    assert final.execution["outcome"] == "alive_at_limit" and final.execution["image"] in cloud.images
    ops = guard.operations
    assert final.execution["image"] == ops[-1]["env_image_id"]  # the shim operation's environment layer: tree + era environment + the shim
    from app.services import sustained_run

    record = {"result": {"verdict": result.verdict, "attempts": [a.as_dict() for a in result.attempts]}, "corpus_entry": {"name": "x", "command": "python main.py"}}
    final_run = sustained_run.final_run_of(record)
    assert final_run["kind"] == "smoke_alive" and final_run["image"] == final.execution["image"]


def test_a_baseline_that_ran_to_completion_has_no_attempt_and_so_nothing_to_sustain(tmp_path, monkeypatch):
    _repo(tmp_path, {"main.py": "print('ok')\n"})
    cloud = v140_cloud.install(monkeypatch, lambda shell, built, files: (0, "ok", "") if shell in EXEC else None)
    result, _, guard = _run(tmp_path, cloud)
    assert result.verdict == "RUNS_CLEAN" and not result.attempts  # the baseline ran to completion: nothing to sustain


# --- a repair candidate whose output was cut gets no hook either ------------------------------------------------------------------

def _cloud_for_a_cut_candidate(monkeypatch):
    """The baseline needs numpy (the era lock fixes it) and then fails with a NameError; the candidate's edit makes the run exit 1 after a long progress stream with no error text."""
    from test_v140_pipeline import HOOK

    def behaviour(shell, built, files):
        if shell not in EXEC:
            return None
        if not any("numpy==1.19.5" in b for b in built):
            return 1, "", "ModuleNotFoundError: No module named 'numpy'\n"
        if any(f"VALUE = {n}" in files.get("main.py", b"").decode() for n in (1, 2)):
            return 1, "", _progress(2000)  # about 12 KB of progress ticks, then exit 1: no error text in it
        return 1, "", "Traceback (most recent call last):\n  File \"main.py\", line 2, in <module>\nNameError: name 'compute' is not defined\n"

    return v140_cloud.install(monkeypatch, behaviour), HOOK


def _two_edits():
    from test_v140_pipeline import _Chat, _edit

    return _Chat([_edit("VALUE = compute()\n", "VALUE = 1\n", "replace the call by a constant"), _edit("VALUE = compute()\n", "VALUE = 2\n", "another constant")], "repair model")


def _candidate_attempt(result):
    return next(a for a in result.attempts if a.candidate == 1 and a.gate_decision == "PASS")


def test_a_candidate_whose_stream_was_cut_without_an_error_is_not_given_the_exit_hook(tmp_path, monkeypatch):
    from test_v140_pipeline import _Ultra

    monkeypatch.setattr(sandbox, "OUTPUT_LIMIT_BYTES", 4000)  # the 12 KB stream is cut at 4,000 bytes: nothing in what came back says why it exited
    _repo(tmp_path, {"main.py": "import numpy\nVALUE = compute()\nprint(VALUE)\n"})
    cloud, hook = _cloud_for_a_cut_candidate(monkeypatch)
    result, deps, guard = _run(tmp_path, cloud, repair=_two_edits(), adjudicator=_Ultra([{"chosen": None, "reasoning": "neither run says why it exited"}]),
                               candidates=2, max_attempts=1, cap=5.0)
    attempt = _candidate_attempt(result)
    assert attempt.exit_code == 1 and attempt.time_machine_action is None
    assert not any(hook in c for c in cloud.ran) and hook not in cloud.ran
    op = next(op for op in guard.operations if op["role"] == "repair 1 candidate 1")
    assert op["streams"]["stderr"]["truncated"] is True and op["streams"]["stderr"]["bytes"] == 4000


def test_the_same_candidate_with_nothing_cut_is_given_the_exit_hook_as_before(tmp_path, monkeypatch):
    """The control: a silent exit whose stream was NOT cut is still a silent exit (D-25 / D-33 unchanged)."""
    from test_v140_pipeline import _Ultra

    _repo(tmp_path, {"main.py": "import numpy\nVALUE = compute()\nprint(VALUE)\n"})
    cloud, hook = _cloud_for_a_cut_candidate(monkeypatch)
    result, deps, guard = _run(tmp_path, cloud, repair=_two_edits(), adjudicator=_Ultra([{"chosen": None, "reasoning": "neither run says why it exited"}]),
                               candidates=2, max_attempts=1, cap=5.0)
    attempt = _candidate_attempt(result)
    assert attempt.time_machine_action is not None and attempt.time_machine_action["rule"] == "exit_site_hook"
    op = next(op for op in guard.operations if op["role"] == "repair 1 candidate 1")
    assert op["streams"]["stderr"]["truncated"] is False


# --- the exit wrapper's run and the evidence run read a cut stream correctly ----------------------------------------------------------

def _silent_chain(monkeypatch, *, wrapper_stderr: str = "", evidence_stderr: str = ""):
    """#3's chain with every run silent (exit 1, nothing on stderr) except the one named: the exit wrapper's run or the evidence run prints `*_stderr` instead."""
    from test_v141_exit_wrapper import _decoded, _is_wrapped

    def behaviour(shell, built, files):
        if shell not in EXEC and not _is_wrapped(shell):
            return None
        if not any("numpy==1.19.5" in b for b in built):
            return 1, "", SKLEARN_MISSING
        if "RERUN_EVIDENCE_BEGIN" in _decoded(shell):
            return 1, "", evidence_stderr
        if _is_wrapped(shell):
            return 1, "", wrapper_stderr
        return 1, "", ""

    return v140_cloud.install(monkeypatch, behaviour)


def test_a_cut_stream_from_the_exit_wrappers_run_ends_output_truncated_without_an_evidence_run(tmp_path, monkeypatch):
    from test_v140_pipeline import _Chat
    from test_v141_exit_wrapper import BARE_EXIT

    monkeypatch.setattr(sandbox, "OUTPUT_LIMIT_BYTES", 4000)
    _repo(tmp_path, {"main.py": BARE_EXIT})
    cloud = _silent_chain(monkeypatch, wrapper_stderr=_progress(2000))  # 12 KB of ticks, no error: cut at 4,000 bytes
    repair = _Chat([], "repair model")  # raises if called
    result, _, guard = _run(tmp_path, cloud, repair=repair)
    assert result.verdict == "INDETERMINATE" and result.indeterminate_reason.startswith("OUTPUT_TRUNCATED: ") and repair.calls == []
    action = next(a.time_machine_action for a in result.attempts if a.time_machine_action and a.time_machine_action["rule"] == "exit_wrapper")
    assert action["result"] == "OUTPUT_TRUNCATED"
    assert not [op for op in guard.operations if op["role"] == "exit wrapper with evidence"]  # an evidence run could not have shown more than the cut stream hides


def test_a_cut_stream_from_the_evidence_run_is_said_not_read_as_no_evidence_block(tmp_path, monkeypatch):
    from test_v140_pipeline import _Chat
    from test_v141_exit_wrapper import BARE_EXIT

    monkeypatch.setattr(sandbox, "OUTPUT_LIMIT_BYTES", 4000)
    _repo(tmp_path, {"main.py": BARE_EXIT})
    cloud = _silent_chain(monkeypatch, evidence_stderr=_progress(2000))  # the block is printed last, behind 12 KB of ticks
    result, _, guard = _run(tmp_path, cloud, repair=_Chat([], "repair model"))
    assert result.verdict == "INDETERMINATE" and result.indeterminate_reason.startswith("EXIT_OUTSIDE_PYTHON: ")
    assert "the run's output was cut by the API" in result.indeterminate_reason and "printed no evidence block" not in result.indeterminate_reason
    evidence_op = next(op for op in guard.operations if op["role"] == "exit wrapper with evidence")
    assert evidence_op["streams"]["stderr"]["truncated"] is True
