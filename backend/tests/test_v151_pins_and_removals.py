"""harness-v1.5.1, F1 and F2 (METHODOLOGY "harness-v1.5 dev/test protocol", rule G). Each test replays text read from a COMMITTED round-1 record of a DEV entry
(runs/corpus_v2_batch/harness-v1.5.0/dev/NN_*.json), never retyped:

  F1  failure class: a pinned old torch has no wheel for the interpreter RERUN chose. Replays DEV #9 (`torch==1.2.0` on Python 3.10, INDETERMINATE RUNNER_SETUP_FAILED with no
      repair attempt) and the `torch<1.9.0` pin the model proposed for DEV #17 (same failure on 3.10). Covered by the same class: both entries.
  F2  failure class: the code uses an API a newer release removed. Replays DEV #17 (`zero_gradients`, torch < 1.9) and DEV #12 (TensorFlow 1 graph API on TF 2). Covered: both.

Offline: fake model and sandbox; the real classifier, env gate and orchestrator run. The model client raises if it is called (the steps are deterministic)."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

from app.services import api_removals, env_repair, python_policy, torch_wheels
from app.services.cost_guard import CostGuard
from app.services.intake import RepoIntake
from app.services.orchestrator import PipelineDeps, run_pipeline
from app.services.sandbox import SandboxRunResult, StepResult
from app.services.torch_wheels_data import WHEELS

ROOT = Path(__file__).resolve().parents[2]
DEV = ROOT / "runs" / "corpus_v2_batch" / "harness-v1.5.0" / "dev"


def _record(name: str) -> dict:
    return json.loads(next(DEV.glob(f"{name}_*.json")).read_text(encoding="utf-8"))


def _default_choice() -> python_policy.PythonChoice:
    return python_policy.PythonChoice("3.10", "default", None, "no usable Python declaration; RERUN default 3.10")


# ------------------------------------------------------------------------------------------------------------------ the wheel snapshot

def test_the_snapshot_is_the_cpu_index_it_says_it_is():
    assert WHEELS["1.2.0"] == ("3.6", "3.7") and WHEELS["1.8.1"] == ("3.6", "3.7", "3.8", "3.9") and "3.10" in WHEELS["1.13.1"]
    assert all(m in python_policy.SUPPORTED for minors in WHEELS.values() for m in minors)


# ------------------------------------------------------------------------------------------------------------------ F1

def test_f1_replays_entry_9_torch_1_2_0_has_no_wheel_for_python_3_10_and_the_interpreter_follows_the_pin():
    record = _record("09")
    assert record["result"]["verdict"] == "INDETERMINATE" and "RUNNER_SETUP_FAILED" in record["result"]["indeterminate_reason"]
    assert record["result"]["attempts"] == []  # the failure ended the entry with no repair attempt
    spec = re.search(r"requirement torch(==[\d.]+)", record["result"]["last_error"]).group(1)
    assert spec == "==1.2.0"
    assert "(from versions: 1.11.0," in record["result"]["last_error"]  # the index offered nothing older than 1.11 for this interpreter
    choice = torch_wheels.python_for_pin(_default_choice(), spec)
    assert (choice.version, choice.source, choice.image) == ("3.7", "torch pin", "python:3.7-slim") and choice.is_declared
    assert "torch==1.2.0" in choice.reason
    assert "no wheel on the CPU index for Python 3.10" in choice.reason and "snapshot 2026-10-02" in choice.reason


def test_f1_covers_entry_17s_model_proposed_pin_too():
    record = _record("17")
    cand3 = next(a for a in record["result"]["attempts"] if a["attempt_number"] == 1 and a.get("candidate") == 3)
    assert "No matching distribution found for torch<1.9.0" in cand3["stderr_tail"]
    choice = torch_wheels.python_for_pin(_default_choice(), "<1.9.0")
    assert choice.version == "3.9"  # the policy's most preferred Python that has a wheel for some torch < 1.9
    assert torch_wheels.newest_release("<1.9.0", "3.9") == "1.8.1"


def test_f1_changes_nothing_when_the_chosen_python_can_install_the_pin_or_there_is_no_pin_or_nothing_matches():
    default = _default_choice()
    assert torch_wheels.python_for_pin(default, "==1.12.1") is default  # 1.12.1 has a cp310 wheel
    assert torch_wheels.python_for_pin(default, "") is default
    assert torch_wheels.python_for_pin(default, "==99.0.0") is default  # not in the snapshot: not our call
    assert torch_wheels.python_for_pin(default, "not a spec") is default
    declared = python_policy.PythonChoice("3.7", "Pipfile", "3.7.4", "declared by Pipfile")
    assert torch_wheels.python_for_pin(declared, "==1.2.0") is declared  # the declared Python already installs it


def test_f1_a_pin_the_declared_python_cannot_install_moves_the_interpreter_only_inside_the_declaration():
    wide = python_policy.PythonChoice("3.10", "pyproject.toml", ">=3.6", "declared by pyproject.toml (>=3.6)")
    choice = torch_wheels.python_for_pin(wide, "==1.2.0")
    assert choice.version == "3.7" and choice.declared == "torch==1.2.0" and "declared by pyproject.toml (>=3.6)" in choice.reason
    narrow = python_policy.PythonChoice("3.10", "pyproject.toml", ">=3.8", "declared by pyproject.toml (>=3.8)")
    assert torch_wheels.python_for_pin(narrow, "==1.2.0") is narrow  # 1.2.0 installs on 3.6 and 3.7 only: the declaration wins, the run ends as it did before


@pytest.mark.parametrize("spec,must_have", [("==1.2.0", {"3.7", "3.6"}), ("<1.9", {"3.9", "3.8", "3.7", "3.6"}), (">=2.5", {"3.10", "3.9", "3.11", "3.12", "3.13"})])
def test_f1_minors_come_back_in_the_policys_order_of_preference(spec, must_have):
    got = torch_wheels.minors_with_wheel(spec)
    assert must_have <= set(got)
    assert list(got) == [m for m in python_policy.PREFERENCE if m in got]


def _git_repo(tmp_path, files):
    for name, text in files.items():
        (tmp_path / name).write_text(text, encoding="utf-8", newline="\n")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True, capture_output=True)
    for k, v in (("core.autocrlf", "false"), ("user.email", "t@e.st"), ("user.name", "t")):
        subprocess.run(["git", "config", k, v], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-q", "-m", "x"], cwd=tmp_path, check=True, capture_output=True)


class _Chat:
    def __init__(self, replies=()):
        self.replies = [json.dumps(r) for r in replies]
        self.calls = []

    def chat_completion(self, **kw):
        self.calls.append(kw)
        if not self.replies:
            raise AssertionError("the model was called: the deterministic rule should have handled this failure")
        return self.replies.pop(0)


def _pipeline(tmp_path, results, *, files, dependency_files=None, replies=(), max_attempts=3):
    _git_repo(tmp_path, files)
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
    )
    intake = RepoIntake(tmp_path, "a" * 40, dict(dependency_files or {}), frozenset(), (), ("train.py",), None)
    result = run_pipeline(repo_url="https://example.com/r", commit_sha="a" * 40, workdir=tmp_path, intake_result=intake, deps=deps,
                          cost_guard=CostGuard(daily_cost_ceiling_usd=100), run_id="v151")
    return result, repair, plans, results


def _fail(stderr, stdout=""):
    return SandboxRunResult(steps=(StepResult("python train.py", 1, stdout, stderr, 1.0, 0.01),))


def _ok():
    return SandboxRunResult(steps=(StepResult("python train.py", 0, "ok", "", 1.0, 0.01),))


def test_f1_in_the_pipeline_the_sandbox_gets_the_interpreter_the_pin_needs(tmp_path):
    """requirements.txt pins torch==1.2.0: the plan's base image is python:3.7-slim, not the 3.10 default (the log says why)."""
    result, _, plans, left = _pipeline(tmp_path, [_ok()], files={"train.py": "import torch\n"}, dependency_files={"requirements.txt": "torch==1.2.0\nnumpy\n"})
    assert not left and result.verdict == "RUNS_CLEAN"
    assert plans[0]["base_image"] == "python:3.7-slim"
    assert "[python] python:3.7-slim (torch pin)" in result.full_log


def test_f1_in_the_pipeline_an_installable_pin_keeps_the_default_interpreter(tmp_path):
    result, _, plans, _ = _pipeline(tmp_path, [_ok()], files={"train.py": "import torch\n"}, dependency_files={"requirements.txt": "torch==1.12.1\n"})
    assert plans[0]["base_image"] == "python:3.10-slim" and result.verdict == "RUNS_CLEAN"


# ------------------------------------------------------------------------------------------------------------------ F2

def test_f2_matches_the_recorded_signatures_and_nothing_else():
    r17, r12 = _record("17"), _record("12")
    hit = api_removals.match(r17["result"]["first_repo_error"])
    assert hit and hit[0].rule == "removed_api_torch_zero_gradients" and hit[1] == "cannot import name 'zero_gradients' from 'torch.autograd.gradcheck'"
    tf_texts = [r12["result"]["last_error"]] + [a["stderr_tail"] for a in r12["result"]["attempts"]]
    hits = [api_removals.match(t) for t in tf_texts if t]
    assert any(h and h[0].rule == "removed_api_tensorflow_v1_graph_api" for h in hits)
    assert "module 'tensorflow_core._api.v2.train' has no attribute 'Saver'" in " ".join(tf_texts)
    assert api_removals.match("ModuleNotFoundError: No module named 'tensorflow'") is None
    assert api_removals.match("AttributeError: module 'torch' has no attribute 'foo'") is None
    assert api_removals.match("") is None


def test_f2_plans_entry_17s_pin_and_moves_python_only_when_it_must():
    rule = api_removals.RULES[0]
    assert api_removals.plan(rule, "3.10")[:2] == ("1.8.1", "3.9")  # 3.10 has no wheel for any torch < 1.9
    assert api_removals.plan(rule, "3.8")[:2] == ("1.8.1", None)  # 3.8 installs it: stay
    tf = api_removals.RULES[1]
    assert api_removals.plan(tf, "3.7")[:2] == ("1.15.5", None)  # entry 12's era Python: stay
    assert api_removals.plan(tf, "3.10")[:2] == ("1.15.5", "3.7")


def test_f2_the_steps_pass_the_env_gate_with_the_matched_text_as_evidence():
    rule = api_removals.RULES[0]
    evidence = "cannot import name 'zero_gradients' from 'torch.autograd.gradcheck'"
    changes = (env_repair.EnvChange(op="python", version="3.9", justification="deterministic", evidence=evidence),
               env_repair.EnvChange(op="pin", package="torch", version="1.8.1", justification="deterministic", evidence=evidence))
    log = f"Traceback...\nImportError: {evidence} (/usr/local/lib/python3.10/site-packages/torch/autograd/gradcheck.py)"
    assert env_repair.check_env_delta(changes, log_text=log, imported_modules=frozenset(), has_requirements_txt=False) == ()
    assert rule.rule in {r.rule for r in api_removals.RULES}


def test_f2_replays_entry_17_the_recorded_error_is_fixed_by_rerun_with_no_model_call(tmp_path):
    """baseline: the recorded zero_gradients ImportError -> RERUN pins torch 1.8.1 and moves to Python 3.9 -> the command runs. The fake model raises if called."""
    record = _record("17")
    stderr = f"Traceback (most recent call last):\n  File \"//fs_main.py\", line 43, in <module>\n{record['result']['first_repo_error']}\n"
    result, repair, plans, left = _pipeline(tmp_path, [_fail(stderr), _ok()], files={"train.py": "import torch\n"})
    assert not left and repair.calls == [] and result.verdict == "RUNS_AFTER_REPAIR"
    step = result.attempts[-1]
    assert (step.origin, step.attempt_number, step.gate_decision, step.exit_code) == ("time_machine", 0, "PASS", 0)
    assert [(c["op"], c["package"], c["version"]) for c in step.env_delta] == [("python", None, "3.9"), ("pin", "torch", "1.8.1")]
    action = step.as_dict()["time_machine_action"]
    assert action["rule"] == "removed_api_torch_zero_gradients" and action["pinned"] == "1.8.1" and action["python_changed"] is True
    assert action["matched_error"] == "cannot import name 'zero_gradients' from 'torch.autograd.gradcheck'"
    assert plans[0]["base_image"] == "python:3.10-slim" and plans[1]["base_image"] == "python:3.9-slim"
    assert any("torch==1.8.1" in cmd for cmd in plans[1]["install_commands"])
    assert result.certificate()["diffs"][-1]["time_machine_action"]["rule"] == "removed_api_torch_zero_gradients"  # inside the passport hash


def test_f2_replays_entry_12_the_recorded_tensorflow_error_pins_tf_1_15_5_on_python_3_7(tmp_path):
    record = _record("12")
    stderr = f"Traceback (most recent call last):\n  File \"/simplE_ignr.py\", line 12, in setup_weights\n{record['result']['last_error']}\n"
    assert "module 'tensorflow' has no attribute 'get_variable'" in stderr
    result, repair, plans, left = _pipeline(tmp_path, [_fail(stderr), _ok()], files={"train.py": "import tensorflow\n"})
    assert not left and repair.calls == [] and result.verdict == "RUNS_AFTER_REPAIR"
    assert [(c["op"], c["package"], c["version"]) for c in result.attempts[-1].env_delta] == [
        ("python", None, "3.7"), ("pin", "tensorflow", "1.15.5"), ("pin", "protobuf", "3.20.3")]
    assert plans[1]["base_image"] == "python:3.7-slim"


def test_f2_fires_once_per_rule_and_then_the_model_is_asked_about_what_is_left(tmp_path):
    stderr = "ImportError: cannot import name 'zero_gradients' from 'torch.autograd.gradcheck' (/x/gradcheck.py)\n"
    declined = {"cannot_fix": True, "explanation": "nothing to change", "cited_sources": [], "reason_no_citation": "none offered"}
    result, repair, plans, left = _pipeline(tmp_path, [_fail(stderr), _fail(stderr)], files={"train.py": "import torch\n"}, replies=[declined, declined, declined], max_attempts=1)
    steps = [a for a in result.attempts if a.time_machine_action]
    assert len(steps) == 1  # the rule did not loop on its own failure
    assert len(repair.calls) >= 1 and result.verdict != "RUNS_AFTER_REPAIR"
    assert not left


def test_f2_a_failure_without_a_known_signature_is_untouched(tmp_path):
    other = "ModuleNotFoundError: No module named 'matplotlib'\n"
    result, repair, plans, left = _pipeline(tmp_path, [_fail(other)], files={"train.py": "import torch\n"},
                                            replies=[{"cannot_fix": True, "explanation": "x", "cited_sources": [], "reason_no_citation": "none"}] * 3, max_attempts=1)
    assert not [a for a in result.attempts if a.time_machine_action and a.time_machine_action.get("rule", "").startswith("removed_api")]


# ------------------------------------------------------------------------------------------------------------------ the independent review's findings (harness-v1.5.1)

def test_review_f1_a_commented_out_pin_is_not_the_repositorys_pin():
    texts = ["#torch==1.0.0\ntorch>=1.4\nnumpy\n", "# torch==1.1.0 pinned for a paper figure\ntorch>=1.4  # newest\n"]
    assert torch_wheels.torch_pin(texts) == ">=1.4"
    assert torch_wheels.python_for_pin(_default_choice(), torch_wheels.torch_pin(texts)).version == "3.10"
    assert torch_wheels.torch_pin(["git+https://github.com/o/torch#egg=torch==1.2.0\n"]) != ""  # a URL fragment is not a comment


def test_review_f1_the_repositorys_declared_python_is_never_overridden():
    declared = python_policy.PythonChoice("3.10", "setup.py", ">=3.10", "declared by setup.py (>=3.10)")
    assert torch_wheels.python_for_pin(declared, "==1.9.0") is declared  # torch 1.9.0 has no wheel for any Python >= 3.10: the run ends as before
    wide = python_policy.PythonChoice("3.10", "setup.py", ">=3.6", "declared by setup.py (>=3.6)")
    assert torch_wheels.python_for_pin(wide, "==1.9.0").version == "3.9"  # inside the declaration: allowed
    caret = python_policy.PythonChoice("3.10", "pyproject.toml", "^3.10", "declared by pyproject.toml (^3.10)")
    assert torch_wheels.python_for_pin(caret, "==1.2.0") is caret


def test_review_f1_the_moved_choice_names_the_pin_as_its_declaration():
    choice = torch_wheels.python_for_pin(_default_choice(), "==1.2.0")
    assert choice.declared == "torch==1.2.0" and "declared by torch pin" not in choice.reason


def test_review_f1_without_packaging_the_policy_changes_nothing(monkeypatch):
    import sys

    monkeypatch.setitem(sys.modules, "packaging", None)
    monkeypatch.setitem(sys.modules, "packaging.specifiers", None)
    monkeypatch.setitem(sys.modules, "packaging.version", None)
    default = _default_choice()
    assert torch_wheels.python_for_pin(default, "==1.2.0") is default


def test_review_f2_the_tensorflow_signature_is_only_what_a_record_shows():
    assert api_removals.match("AttributeError: module 'tensorflow' has no attribute 'get_variable'")
    assert api_removals.match("AttributeError: module 'tensorflow_core._api.v2.train' has no attribute 'Saver'")
    assert api_removals.match("AttributeError: module 'tensorflow' has no attribute 'placeholder'") is None  # needs its own recorded failure first


def test_review_f2_tensorflow_1_15_5_comes_with_a_protobuf_it_can_import(tmp_path):
    stderr = "AttributeError: module 'tensorflow' has no attribute 'get_variable'\n"
    result, repair, plans, left = _pipeline(tmp_path, [_fail(stderr), _ok()], files={"train.py": "import tensorflow\n"})
    assert not left and repair.calls == [] and result.verdict == "RUNS_AFTER_REPAIR"
    pins = [(c["package"], c["version"]) for c in result.attempts[-1].env_delta if c["op"] == "pin"]
    assert pins == [("tensorflow", "1.15.5"), ("protobuf", "3.20.3")]
    assert any("protobuf==3.20.3" in cmd for cmd in plans[1]["install_commands"])
    assert result.attempts[-1].as_dict()["time_machine_action"]["companions"] == [{"package": "protobuf", "version": "3.20.3"}]
    assert api_removals.companion_pins(api_removals.RULES[1], "3.6") == (("protobuf", "3.19.6"),)  # the last protobuf that installs on Python 3.6
    assert api_removals.companion_pins(api_removals.RULES[0], "3.9") == ()


def test_review_f2_a_requirements_file_that_already_pins_protobuf_keeps_its_pin(tmp_path):
    stderr = "AttributeError: module 'tensorflow' has no attribute 'get_variable'\n"
    result, _, plans, _ = _pipeline(tmp_path, [_fail(stderr), _ok()], files={"train.py": "import tensorflow\n"},
                                    dependency_files={"requirements.txt": "tensorflow>=2.0\nprotobuf==3.11.2\nnumpy\n"})
    pins = [(c["package"], c["version"]) for c in result.attempts[-1].env_delta if c["op"] == "pin"]
    assert pins == [("tensorflow", "1.15.5")]
    assert any("protobuf==3.11.2" in cmd for cmd in plans[1]["install_commands"])


def _setup_failure(stderr="ERROR: ResolutionImpossible: torch 1.8.1 conflicts with torchvision 0.10.0\n"):
    return SandboxRunResult(steps=(StepResult("pip install torch==1.8.1 torchvision==0.10.0", 1, "", stderr, 1.0, 0.01, phase="runner_setup"),))


def test_review_f2_a_step_that_breaks_the_setup_is_put_back_and_the_model_repairs_the_original_failure(tmp_path):
    """requirements torch>=1.9 + torchvision==0.10.0: pinning torch 1.8.1 cannot be installed beside torchvision 0.10.0. The run must not end INDETERMINATE
    RUNNER_SETUP_FAILED with no model attempt: the plan is restored and the model gets the zero_gradients failure."""
    stderr = "ImportError: cannot import name 'zero_gradients' from 'torch.autograd.gradcheck' (/x/gradcheck.py)\n"
    fix = {"env_delta": [{"op": "pin", "package": "torchvision", "version": "0.9.1", "justification": "match torch 1.8", "evidence": "cannot import name 'zero_gradients'"}],
           "cited_sources": [], "reason_no_citation": "none offered", "explanation": "x"}
    result, repair, plans, left = _pipeline(tmp_path, [_fail(stderr), _setup_failure(), _ok()], files={"train.py": "import torch\n"}, replies=[fix],
                                            dependency_files={"requirements.txt": "torch>=1.9\ntorchvision==0.10.0\n"})
    assert not left and len(repair.calls) == 1, "the model must be asked about the original failure"
    assert result.verdict == "RUNS_AFTER_REPAIR" and result.indeterminate_reason == ""
    step = next(a for a in result.attempts if a.time_machine_action and a.time_machine_action["rule"].startswith("removed_api"))
    assert "put_back" in step.time_machine_action and "own setup step" in step.time_machine_action["put_back"]
    assert plans[2]["base_image"] == plans[0]["base_image"]  # the model repair runs on the plan as it was, not on the broken one
    assert not any("torch==1.8.1" in cmd for cmd in plans[2]["install_commands"])


def test_review_f2_a_different_later_error_does_not_poison_the_change_for_the_model(tmp_path):
    """The step worked (the removed API is gone) and the run now fails on something else. A model proposal that repeats one of the changes of the step is not refused as
    applied-and-failed: it did not fail."""
    first = "ImportError: cannot import name 'zero_gradients' from 'torch.autograd.gradcheck' (/x/gradcheck.py)\n"
    later = "ModuleNotFoundError: No module named 'foobar'\n"
    fix = {"env_delta": [{"op": "pin", "package": "torch", "version": "1.8.1", "justification": "same pin again", "evidence": "No module named 'foobar'"}],
           "cited_sources": [], "reason_no_citation": "none offered", "explanation": "x"}
    result, repair, plans, left = _pipeline(tmp_path, [_fail(first), _fail(later), _ok()], files={"train.py": "import torch\n"}, replies=[fix], max_attempts=1)
    model_attempts = [a for a in result.attempts if a.origin == "model"]
    assert model_attempts and not any(v["rule"] == "ENV_REPEATS_FAILED_CHANGE" for a in model_attempts for v in a.gate_violations)


def test_review_f2_when_the_removal_step_is_refused_the_other_deterministic_steps_still_run(tmp_path):
    """The log has a removed-API signature AND a missing compiler. A repo directory named tensorflow makes the env gate refuse the TensorFlow pin (it would shadow the own
    module of the repo): the step is not taken and the build-essential rule, which used to be skipped for the rest of that pass, runs in the same pass."""
    (tmp_path / "tensorflow").mkdir()
    (tmp_path / "tensorflow" / "__init__.py").write_text("", encoding="utf-8")
    stderr = "AttributeError: module 'tensorflow' has no attribute 'get_variable'\nerror: unable to execute 'gcc': No such file or directory\n"
    result, repair, plans, left = _pipeline(tmp_path, [_fail(stderr), _ok()], files={"train.py": "import tensorflow\n"})
    assert not left and repair.calls == [] and result.verdict == "RUNS_AFTER_REPAIR"
    rules = [a.time_machine_action["rule"] for a in result.attempts if a.time_machine_action]
    assert rules == ["missing_compiler_build_essential"]
