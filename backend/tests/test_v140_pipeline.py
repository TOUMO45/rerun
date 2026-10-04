"""harness-v1.4.0-rc, end to end offline: the real orchestrator and the real sandbox runner against a fake ConTree cloud (v140_cloud).

The failures are the ones the harness-v1.3.4 gate RECORDED for corpus-v2 entries 3, 8 and 11 (read from the committed records, not
retyped); entry 7's mechanism (D-24) has its own tests in test_d24_build_essential.py. Each test checks one mechanism of the v1.4.0
directive and the record fields that make it checkable (`operations`: sandbox_seconds, install_seconds, branch_from_image,
result_image, image_kept)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

import v140_cloud
from app.services import classifier, runner_env, runner_hooks, sandbox, smoke_exec
from app.services.cost_guard import CostGuard
from app.services.intake import RepoIntake
from app.services.orchestrator import PipelineDeps, run_pipeline
from app.services.time_machine import LockResult

ROOT = Path(__file__).resolve().parents[2]
V134 = ROOT / "runs" / "corpus_v2_batch" / "harness-v1.3.4" / "smoke"


def _recorded(entry: str) -> dict:
    return json.loads((V134 / f"{entry}.json").read_text(encoding="utf-8"))


def _recorded_attempt(entry: str, number: int, origin: str) -> dict:
    return next(a for a in _recorded(entry)["result"]["attempts"] if a["attempt_number"] == number and a["origin"] == origin)


ENTRY_11_GPU = _recorded_attempt("11_JindongGu__VoteAttack", 0, "time_machine")  # the era re-execution: torch.load on a CUDA tensor
ENTRY_03_SILENT = _recorded_attempt("03_autumn9999__vmtl", 0, "time_machine")  # the era re-execution: exit 1, progress bars only
TQDM_MISSING = "Traceback (most recent call last):\n  File \"main.py\", line 3, in <module>\nModuleNotFoundError: No module named 'tqdm'\n"
SKLEARN_MISSING = "Traceback (most recent call last):\n  File \"main.py\", line 2, in <module>\nModuleNotFoundError: No module named 'sklearn'\n"
SHIM = runner_hooks.install_command(runner_hooks.CPU_SHIM)
HOOK = runner_hooks.install_command(runner_hooks.EXIT_HOOK)
# the documented command, as-published and smoke-wrapped; harness-v1.7 (R1 c): a re-execution after the memory hook carries the memory environment
EXEC = {"python main.py", smoke_exec.wrap("python main.py", 60), runner_env.with_memory_env("python main.py"),
        smoke_exec.wrap(runner_env.with_memory_env("python main.py"), 60)}


class _Chat:
    def __init__(self, replies=(), name="model"):
        self.replies = [json.dumps(r) for r in replies]
        self.calls = []
        self.name = name

    def chat_completion(self, **kw):
        self.calls.append(kw)
        if not self.replies:
            raise AssertionError(f"the {self.name} was called: a deterministic rule should have handled this failure")
        return self.replies.pop(0)


class _Ultra:
    """The adjudicator model: candidate adjudications come from `choices` (and are counted); certificate prose is always answered."""

    def __init__(self, choices=()):
        self.choices = [json.dumps(c) for c in choices]
        self.calls = []

    def chat_completion(self, **kw):
        if "adjudicate between candidate repairs" in kw["system_prompt"]:
            self.calls.append(kw)
            if not self.choices:
                raise AssertionError("the adjudicator was asked to choose between candidates")
            return self.choices.pop(0)
        verdict = kw["user_prompt"].split("Verdict: ", 1)[1].splitlines()[0]
        return json.dumps({"verdict": verdict, "prose": "The command ran.", "downgrade_reason": ""})


def _repo(tmp_path: Path, files: dict) -> None:
    for name, text in files.items():
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text(text, encoding="utf-8", newline="\n")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True, capture_output=True)
    for k, v in (("core.autocrlf", "false"), ("user.email", "t@e.st"), ("user.name", "t")):
        subprocess.run(["git", "config", k, v], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-q", "-m", "x"], cwd=tmp_path, check=True, capture_output=True)


def _head(tmp_path: Path) -> str:
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=tmp_path, capture_output=True, text=True, check=True).stdout.strip()


def _run(tmp_path, cloud, *, repair=(), adjudicator=None, lock=None, candidates=1, releaser=None, max_attempts=3, entry="main.py", cap=1.25,
         command="python main.py"):
    deps = PipelineDeps(
        recon_client=_Chat([{"entrypoint": entry, "confidence": 0.9}], "recon"), recon_model="r",
        repair_client=repair if isinstance(repair, _Chat) else _Chat(repair, "repair model"), repair_model="super",
        adjudicator_client=adjudicator, adjudicator_model="ultra" if adjudicator is not None else None,
        sandbox_api_key="k", sandbox_wall_clock_seconds=600, sandbox_runner=sandbox.run_build_and_execute,
        tavily_client=None, smoke_seconds=60, max_attempts=max_attempts, candidates_per_round=candidates, image_releaser=releaser,
        lock_compiler=lock or (lambda *a: LockResult(True, ("numpy==1.19.5",), ("numpy",))),
    )
    commit = _head(tmp_path)
    intake = RepoIntake(tmp_path, commit, {}, frozenset(), (), (entry,), None)
    guard = CostGuard(daily_cost_ceiling_usd=cap)
    result = run_pipeline(repo_url="https://example.com/r", commit_sha=commit, workdir=tmp_path, intake_result=intake, deps=deps,
                          cost_guard=guard, run_id="v140", documented_command=command)
    return result, deps, guard


def _torch_command(tmp_path: Path, steps=()) -> str:
    setup = runner_env.plan_torch_setup(list(steps), tmp_path)
    assert setup is not None
    return setup.install_command


# --- entry 11: CPU shim (deterministic, on GPU_REQUIRED) + checkpoint persistence -------------------------------------

def test_entry_11_cpu_shim_fires_on_the_recorded_torch_load_error_with_no_model_call(tmp_path, monkeypatch):
    _repo(tmp_path, {"main.py": "import torch\nimport tqdm\ntorch.load('model.pt')\n"})
    assert classifier.classify(1, ENTRY_11_GPU["stderr_tail"], ENTRY_11_GPU["stdout_tail"]).code == "GPU_REQUIRED"

    def behaviour(shell, built, files):
        if shell not in EXEC:
            return None  # setup commands succeed
        if not any("numpy==1.19.5" in b for b in built):
            return 1, "", TQDM_MISSING  # the as-published environment: an undeclared import
        if SHIM not in built:
            return 1, ENTRY_11_GPU["stdout_tail"], ENTRY_11_GPU["stderr_tail"]  # the era environment: the recorded GPU error
        return 0, "RERUN_SMOKE_ALIVE: still running after 60s with output and no traceback", ""

    cloud = v140_cloud.install(monkeypatch, behaviour)
    result, deps, guard = _run(tmp_path, cloud)  # the repair model raises if it is ever called
    assert result.verdict == "RUNS_AFTER_REPAIR"
    assert deps.repair_client.calls == []
    shim_step = result.attempts[-1]
    assert (shim_step.origin, shim_step.attempt_number, shim_step.exit_code) == ("time_machine", 0, 0)
    assert shim_step.time_machine_action["rule"] == "cpu_shim" and "CUDA device" in shim_step.time_machine_action["matched_error"]
    # checkpoint persistence: the shim operation reopened the era environment image and ran only the shim install on top of it
    ops = guard.operations
    tm_op, shim_op = ops[-2], ops[-1]
    assert shim_op["branch_from_image"] == tm_op["env_image_id"] and shim_op["branch_from_image"] in cloud.reopened
    assert not shim_op["torch_installed"] and shim_op["torch_in_start_image"]
    assert [i["command"] for i in shim_op["install_seconds"]] == [SHIM[:160]]


def _fields_ok(op: dict) -> None:
    for key in ("sandbox_seconds", "install_seconds", "branch_from_image", "result_image", "image_kept"):
        assert key in op, key
    assert isinstance(op["sandbox_seconds"], float) and all({"command", "seconds", "phase"} <= set(i) for i in op["install_seconds"])


def test_operation_records_are_complete_and_measured(tmp_path, monkeypatch):
    _repo(tmp_path, {"main.py": "import torch\nimport tqdm\n"})

    def behaviour(shell, built, files):
        if shell in EXEC:
            return (0, "ok", "") if any("numpy==1.19.5" in b for b in built) else (1, "", TQDM_MISSING)
        return None

    cloud = v140_cloud.install(monkeypatch, behaviour, seconds={"pip install torch": 41.5})
    result, _, guard = _run(tmp_path, cloud)
    assert result.verdict == "RUNS_AFTER_REPAIR" and len(guard.operations) == 2
    for op in guard.operations:
        _fields_ok(op)
    baseline, tm = guard.operations
    torch_steps = [i for i in baseline["install_seconds"] if i["torch"]]
    assert len(torch_steps) == 1 and torch_steps[0]["seconds"] == 41.5  # the install seconds are the API's per-step value
    assert baseline["role"] == "baseline" and baseline["branch_from_image"] is None and baseline["image_kept"]
    assert baseline["sandbox_seconds"] == pytest.approx(sum(i["seconds"] for i in baseline["install_seconds"]) + 2.0 + 2.0)


# --- entry 8: checkpoint persistence (the time machine reuses the baseline's torch layer) ------------------------------

def test_entry_8_the_time_machine_branches_from_the_baseline_torch_layer_and_installs_torch_once(tmp_path, monkeypatch):
    """v1.3.4 entry 8: the era lock was unavailable, the fallback pip step ran on the SAME base image, and its operation was killed
    33 s into a second torch install. Now the fallback branches from the baseline's layer that already holds torch."""
    _repo(tmp_path, {"main.py": "import torch\nimport sklearn\n"})
    torch_cmd = _torch_command(tmp_path)

    def behaviour(shell, built, files):
        if shell in EXEC:
            return (0, "ok", "") if any("scikit-learn" in b for b in built) else (1, "", SKLEARN_MISSING)
        return None

    cloud = v140_cloud.install(monkeypatch, behaviour)
    lock = lambda *a: LockResult(False, error="use torchvision>=0.1.7 was yanked ... your requirements are unsatisfiable.")  # noqa: E731
    result, _, guard = _run(tmp_path, cloud, lock=lock)
    assert result.verdict == "RUNS_AFTER_REPAIR"
    assert cloud.count(torch_cmd) == 1
    baseline, tm = guard.operations
    assert baseline["torch_installed"] and not tm["torch_installed"] and tm["torch_in_start_image"]
    assert tm["branch_from_image"] in baseline["kept_images"] and tm["torch_env_key"] == baseline["torch_env_key"]
    assert [i["command"] for i in tm["install_seconds"]] == [c[:160] for c in cloud.ran if "scikit-learn" in c]


def test_without_a_checkpoint_capable_runner_the_harness_v13_flow_is_unchanged(tmp_path):
    """A runner that does not declare `checkpoint` (every older runner and test double) gets the v1.3.x call: no kept image."""
    _repo(tmp_path, {"main.py": "import tqdm\n"})
    calls = []

    def runner(**kw):
        calls.append(kw)
        stderr = TQDM_MISSING if len(calls) == 1 else ""
        return sandbox.SandboxRunResult(steps=(sandbox.StepResult("python main.py", 1 if stderr else 0, "", stderr, 1.0, 0.01),))

    deps = PipelineDeps(recon_client=_Chat([{"entrypoint": "main.py", "confidence": 0.9}]), recon_model="r", repair_client=_Chat(),
                        repair_model="p", adjudicator_client=None, adjudicator_model=None, sandbox_api_key="k",
                        sandbox_wall_clock_seconds=600, sandbox_runner=runner, smoke_seconds=0, candidates_per_round=3,
                        lock_compiler=lambda *a: LockResult(True, ("tqdm==4.0",), ("tqdm",)))
    commit = _head(tmp_path)
    result = run_pipeline(repo_url="https://example.com/r", commit_sha=commit, workdir=tmp_path,
                          intake_result=RepoIntake(tmp_path, commit, {}, frozenset(), (), ("main.py",), None), deps=deps,
                          cost_guard=CostGuard(daily_cost_ceiling_usd=5), run_id="legacy")
    assert result.verdict == "RUNS_AFTER_REPAIR"
    assert all("checkpoint" not in kw and "runner_extras" not in kw for kw in calls)


# --- entry 3: the exit-site hook (D-25), automatic on a non-zero exit with no traceback ---------------------------------

def test_entry_3_the_exit_hook_fires_on_the_recorded_silent_exit_and_the_model_then_sees_the_exit_site(tmp_path, monkeypatch):
    _repo(tmp_path, {"main.py": "import sklearn\nimport sys\nsys.exit(1)\n"})
    assert not classifier.has_actionable_error(ENTRY_03_SILENT["stderr_tail"], ENTRY_03_SILENT["stdout_tail"])
    hook_stack = ("RERUN_EXIT_HOOK: sys.exit(1) was called; the exit site (most recent call last):\n"
                  "  File \"main.py\", line 3, in <module>\n    sys.exit(1)\nSystemExit: 1\n")

    def behaviour(shell, built, files):
        if shell not in EXEC:
            return None
        if not any("numpy==1.19.5" in b for b in built):
            return 1, "", SKLEARN_MISSING
        if HOOK not in built:
            return 1, ENTRY_03_SILENT["stdout_tail"], ENTRY_03_SILENT["stderr_tail"]  # the recorded silent exit
        return 1, "", ENTRY_03_SILENT["stderr_tail"][-200:] + "\n" + hook_stack

    cloud = v140_cloud.install(monkeypatch, behaviour)
    decline = {"file_edits": None, "env_delta": [], "explanation": "sys.exit(1) at main.py line 3 is the repository's own exit"}
    repair = _Chat([decline] * 3, "repair model")
    result, _, guard = _run(tmp_path, cloud, repair=repair)
    hook_step = next(a for a in result.attempts if a.time_machine_action and a.time_machine_action["rule"] == "exit_site_hook")
    assert hook_step.origin == "time_machine" and "with no error text" in hook_step.time_machine_action["matched_error"]
    assert "raise SystemExit" in hook_step.time_machine_action["limit"]
    # the model is asked only after the hook, and it sees the exit site instead of the "NO TRACEBACK FOUND" rule
    assert repair.calls
    prompt = repair.calls[0]["user_prompt"]
    assert "RERUN_EXIT_HOOK" in prompt and "NO TRACEBACK FOUND" not in prompt
    hook_op = next(op for op in guard.operations if op["role"] == "time machine: exit_site_hook")
    assert hook_op["branch_from_image"] is not None and not hook_op["torch_installed"]


# --- parallel candidates (3 per failure) with adjudication -------------------------------------------------------------

def _edit(old: str, new: str, why: str) -> dict:
    return {"file_edits": [{"path": "main.py", "old": old, "new": new}], "env_delta": [], "cited_sources": [],
            "reason_no_citation": "no reference offered", "explanation": why}


@pytest.mark.parametrize("cap, concurrent", [(5.0, 3), (1.25, 1)])
def test_three_candidates_run_in_branches_and_the_adjudicated_one_becomes_the_environment(tmp_path, monkeypatch, cap, concurrent):
    """With $5 left, each of three concurrent branches is funded for more than the smoke run: they run at the same time. With the
    owner's proposed $1.25 entry cap, a third of what is left funds less than that (at the guard's $0.0085/s bound): they run one
    after another, each funded from what is left, and none is killed for running beside the others."""
    _repo(tmp_path, {"main.py": "import numpy\nVALUE = compute()\nprint(VALUE)\n"})
    failure = "Traceback (most recent call last):\n  File \"main.py\", line 2, in <module>\nNameError: name 'compute' is not defined\n"

    def behaviour(shell, built, files):
        if shell not in EXEC:
            return None
        if not any("numpy==1.19.5" in b for b in built):
            return 1, "", "ModuleNotFoundError: No module named 'numpy'\n"
        source = files.get("main.py", b"").decode()
        if "def compute" in source:
            return 0, "RERUN_SMOKE_ALIVE: still running after 60s with output and no traceback", ""
        if "VALUE = 1" in source:
            return 1, "", "Traceback (most recent call last):\n  File \"main.py\", line 3\nTypeError: print() got nothing\n"
        return 1, "", failure

    cloud = v140_cloud.install(monkeypatch, behaviour)
    repair = _Chat([
        _edit("VALUE = compute()\n", "VALUE = 1\n", "replace the call by a constant"),
        _edit("import numpy\n", "import numpy\n\n\ndef compute():\n    return numpy.zeros(1)\n", "define the missing helper"),
        _edit("print(VALUE)\n", "print(VALUE)  # unchanged\n", "comment"),
    ], "repair model")
    ultra = _Ultra([{"chosen": 2, "reasoning": "candidate 2 defines the missing function; candidate 1 replaces the computation"}])
    released = []
    result, _, guard = _run(tmp_path, cloud, repair=repair, adjudicator=ultra, candidates=3, cap=cap,
                            releaser=lambda **kw: released.extend(kw["image_ids"]) or {"released": len(kw["image_ids"]), "cost_usd": 0.002, "seconds": 1.0})
    assert result.verdict == "RUNS_AFTER_REPAIR"
    candidates = [a for a in result.attempts if a.candidate is not None]
    assert [a.candidate for a in candidates] == [1, 2, 3] and [a.chosen for a in candidates] == [False, True, False]
    assert all(a.branch and a.branch["branch_from_image"] for a in candidates)
    assert candidates[1].branch["image_kept"] and not candidates[0].branch["image_kept"]
    adjudication = candidates[0].adjudication
    assert adjudication["qualifying"] == [1, 2] and adjudication["chosen"] == 2 and "missing function" in adjudication["reasoning"]
    assert sorted(released) == sorted(c.branch["result_image"] for c in candidates if not c.chosen)
    release_op = next(op for op in guard.operations if op["role"].endswith("release candidate images not chosen"))
    assert release_op["cost_usd"] == 0.002 and release_op["released"] == 2  # the disposal runs' cost is recorded spend
    # only the chosen change is in the checkout
    assert "def compute" in (tmp_path / "main.py").read_text(encoding="utf-8") and "VALUE = 1" not in (tmp_path / "main.py").read_text(encoding="utf-8")
    # the three ran as concurrent branches of ONE environment image, with no reinstall
    runs = [op for op in guard.operations if op["candidate"] is not None]
    assert len(runs) == 3 and {op["concurrent"] for op in runs} == {concurrent}
    assert all(op["outcome"] == "completed" for op in runs)
    assert len({op["branch_from_image"] for op in runs}) == 1 and not any(op["torch_installed"] for op in runs)
    for op in guard.operations:
        _fields_ok(op)
    assert all(op["setup_commands"] == op["start_setup_commands"] for op in runs)
    # every candidate is in the certificate (the passport hash covers it), each with its branch image
    stored = [d for d in result.certificate()["diffs"] if "candidate" in d]
    assert [d["candidate"] for d in stored] == [1, 2, 3] and all("result_image" in d["branch"] for d in stored)
    assert len(ultra.calls) == 1


def test_a_candidate_that_does_not_compile_is_rejected_before_it_runs(tmp_path, monkeypatch):
    _repo(tmp_path, {"main.py": "import numpy\nx = undefined_name\n"})

    def behaviour(shell, built, files):
        if shell not in EXEC:
            return None
        if not any("numpy==1.19.5" in b for b in built):
            return 1, "", "ModuleNotFoundError: No module named 'numpy'\n"
        return 1, "", "Traceback (most recent call last):\nNameError: name 'undefined_name' is not defined\n"

    cloud = v140_cloud.install(monkeypatch, behaviour)
    bad = _edit("x = undefined_name\n", "return undefined_name\n", "return instead")  # parses (ast) but does not compile
    decline = {"file_edits": None, "env_delta": [], "explanation": "no other fix"}
    result, _, guard = _run(tmp_path, cloud, repair=_Chat([bad, decline, decline] * 3), candidates=3, max_attempts=1)
    rejected = next(a for a in result.attempts if a.gate_decision == "REJECT")
    assert rejected.gate_violations[0]["rule"] == "PY_COMPILE_FAILED" and rejected.candidate == 1
    assert not [op for op in guard.operations if op["candidate"] is not None]  # nothing ran: no candidate passed


def test_no_candidate_changing_the_outcome_means_no_adjudication_call_and_no_change(tmp_path, monkeypatch):
    _repo(tmp_path, {"main.py": "import numpy\nx = undefined_name\n"})
    failure = "Traceback (most recent call last):\nNameError: name 'undefined_name' is not defined\n"

    def behaviour(shell, built, files):
        if shell not in EXEC:
            return None
        if not any("numpy==1.19.5" in b for b in built):
            return 1, "", "ModuleNotFoundError: No module named 'numpy'\n"
        return 1, "", failure

    cloud = v140_cloud.install(monkeypatch, behaviour)
    edit = _edit("x = undefined_name\n", "x = undefined_name  # same\n", "comment")
    decline = {"file_edits": None, "env_delta": [], "explanation": "no other fix"}
    ultra = _Ultra()  # raises if asked to choose between candidates
    result, _, _ = _run(tmp_path, cloud, repair=_Chat([edit, decline, decline]), adjudicator=ultra, candidates=3, max_attempts=1)
    assert result.verdict == "BLOCKED" and ultra.calls == []
    ran = next(a for a in result.attempts if a.candidate == 1 and a.gate_decision == "PASS")
    assert ran.adjudication["qualifying"] == [] and ran.adjudication["chosen"] is None and ran.chosen is False
    assert (tmp_path / "main.py").read_text(encoding="utf-8") == "import numpy\nx = undefined_name\n"


def test_tavily_snippets_reach_the_candidate_generator_with_the_citation_rule(tmp_path, monkeypatch):
    from app.services import repairer

    prompt = repairer.build_repair_user_prompt(
        classifier.classify(1, TQDM_MISSING), "main.py", "import tqdm\n", "[1] tqdm — https://pypi.org/project/tqdm\npip install tqdm==4.19")
    assert "[1] tqdm" in prompt and repairer.CITATION_RULE in prompt
    follow = repairer.candidate_followup(["pin tqdm"], 2)
    assert "candidate 2" in follow and "DIFFERENT" in follow and "pin tqdm" in follow


# --- entry 7: D-24 (already in) on the checkpoint runner ------------------------------------------------------------------

def test_entry_7_d24_under_checkpoints_branches_from_the_kept_tree_and_never_reuploads(tmp_path, monkeypatch):
    """The recorded gcc error of entry 7 (v1.3.4 gate, repair 2). Nothing is uploaded or fetched again. (harness-v1.4.0: build-essential
    changed the FIRST setup command, so only the kept pristine-tree layer could be reused and the era lock was installed again;
    harness-v1.4.1-rc, D-34: it is an additive layer on the kept environment image, so the image holding the lock is reused, see
    test_v141_apt_layer.py. The assertions below were changed from `start_setup_commands == 0` accordingly.)"""
    gcc = next(a for a in _recorded("07_albertometelli__pfqi")["result"]["attempts"] if a["attempt_number"] == 2)["stderr_tail"]
    assert "unable to execute 'gcc'" in gcc
    _repo(tmp_path, {"main.py": "import numpy\n"})

    def behaviour(shell, built, files):
        if shell not in EXEC:
            return None
        if not any("numpy==1.19.5" in b for b in built):
            return 1, "", "ModuleNotFoundError: No module named 'numpy'\n"
        if not any("build-essential" in b for b in built):
            return 1, "", gcc
        return 0, "ok", ""

    cloud = v140_cloud.install(monkeypatch, behaviour)
    result, deps, guard = _run(tmp_path, cloud)
    assert result.verdict == "RUNS_AFTER_REPAIR" and deps.repair_client.calls == []
    assert result.attempts[-1].time_machine_action["rule"] == "missing_compiler_build_essential"
    tm_op, d24_op = guard.operations[-2], guard.operations[-1]
    assert d24_op["start_setup_commands"] == 1 and d24_op["branch_from_image"] == tm_op["env_image_id"]  # the era lock's layer, not the tree
    from app.services.orchestrator import apt_layer_command

    assert [i["command"] for i in d24_op["install_seconds"]] == [apt_layer_command(["build-essential"])]  # only the apt layer ran
    assert not [s for s in d24_op["rerun_steps"] if s["phase"] == "rerun_extract"]  # the tree was not uploaded again
    assert sum(1 for c in cloud.ran if c.startswith("tar -xpf " + sandbox.UPLOAD_ARCHIVE)) == 2  # baseline + time machine only


# --- regressions found by the independent review of harness-v1.4.0-rc ------------------------------------------------

def test_a_non_editable_project_install_gets_the_patch_before_the_setup_steps(tmp_path, monkeypatch):
    """`pip install .` copies the repository into site-packages: a patch put on top AFTER that step would leave the command running
    the unpatched installed package. Every patched file therefore goes in right after the tree, before the setup steps."""
    from app.services.orchestrator import _installs_project_copy

    assert _installs_project_copy("pip install .") and _installs_project_copy("pip install --no-deps .")
    assert not _installs_project_copy("pip install -e .") and not _installs_project_copy("pip install -r requirements.txt")
    _repo(tmp_path, {"setup.py": "from setuptools import setup\nsetup(name='pkg', packages=['pkg'])\n",
                     "main.py": "import pkg.model\n", "pkg/__init__.py": "", "pkg/model.py": "VALUE = broken\n"})
    failure = "Traceback (most recent call last):\nNameError: name 'broken' is not defined\n"
    installed = {}

    def behaviour(shell, built, files):
        if shell == "pip install .":
            installed["model"] = files.get("pkg/model.py", b"")  # the copy pip makes, as the image holds it at this step
            return None
        if shell not in EXEC:
            return None
        return (0, "ok", "") if b"VALUE = 1" in installed.get("model", b"") else (1, "", failure)

    cloud = v140_cloud.install(monkeypatch, behaviour)
    fix = _edit("VALUE = broken\n", "VALUE = 1\n", "define the value")
    fix["file_edits"][0]["path"] = "pkg/model.py"
    deps_files = {"setup.py": (tmp_path / "setup.py").read_text(encoding="utf-8")}
    commit = _head(tmp_path)
    deps = PipelineDeps(
        recon_client=_Chat([{"entrypoint": "main.py", "confidence": 0.9}], "recon"), recon_model="r",
        repair_client=_Chat([fix]), repair_model="super", adjudicator_client=None, adjudicator_model=None,
        sandbox_api_key="k", sandbox_wall_clock_seconds=600, sandbox_runner=sandbox.run_build_and_execute, tavily_client=None,
        smoke_seconds=60, max_attempts=1, candidates_per_round=1)
    guard = CostGuard(daily_cost_ceiling_usd=5)
    result = run_pipeline(repo_url="https://example.com/r", commit_sha=commit, workdir=tmp_path,
                          intake_result=RepoIntake(tmp_path, commit, deps_files, frozenset(), (), ("main.py",), None),
                          deps=deps, cost_guard=guard, run_id="pip-dot", documented_command="python main.py")
    assert result.verdict == "RUNS_AFTER_REPAIR", result.full_log[-2000:]
    repair_ops = [op for op in guard.operations if op["role"].startswith("repair")]
    assert repair_ops and repair_ops[-1]["branch_from_image"] is None  # rebuilt with the patch under the install, not branched


def test_a_failed_overlay_check_records_what_the_completed_steps_cost(tmp_path, monkeypatch):
    _repo(tmp_path, {"main.py": "import numpy\nx = undefined_name\n"})

    def behaviour(shell, built, files):
        if "apply.py" in shell:
            return 97, "", "RERUN_BRANCH_MISMATCH 1 file(s): main.py\n"
        if shell not in EXEC:
            return None
        if not any("numpy==1.19.5" in b for b in built):
            return 1, "", "ModuleNotFoundError: No module named 'numpy'\n"
        return 1, "", "Traceback (most recent call last):\nNameError: name 'undefined_name' is not defined\n"

    cloud = v140_cloud.install(monkeypatch, behaviour, costs={"pip install": 0.05})
    edit = _edit("x = undefined_name\n", "x = 1\n", "define it")
    result, _, guard = _run(tmp_path, cloud, repair=_Chat([edit]), max_attempts=1)
    assert result.verdict == "INVALID_HARNESS"
    void = guard.operations[-1]
    # the operation branched from the environment image (no setup step ran); the failed overlay step's own measured cost ($0.01 in the
    # fake) is recorded spend, where before it was dropped
    assert void["outcome"] == "void" and void["cost_usd"] == pytest.approx(0.01) and void["branch_from_image"]
    assert guard.sandbox_spent_usd == pytest.approx(sum(op["cost_usd"] for op in guard.operations))


def test_released_losing_images_are_no_longer_reported_as_kept(tmp_path, monkeypatch):
    """A losing candidate's result image gets the disposal step; its operation record then no longer lists it as kept."""
    _repo(tmp_path, {"main.py": "import numpy\nVALUE = compute()\n"})

    def behaviour(shell, built, files):
        if shell not in EXEC:
            return None
        if not any("numpy==1.19.5" in b for b in built):
            return 1, "", "ModuleNotFoundError: No module named 'numpy'\n"
        source = files.get("main.py", b"").decode()
        if "def compute" in source:
            return 0, "ok", ""
        if "VALUE = 1" in source:
            return 1, "", "Traceback (most recent call last):\nTypeError: other\n"
        return 1, "", "Traceback (most recent call last):\nNameError: name 'compute' is not defined\n"

    cloud = v140_cloud.install(monkeypatch, behaviour)
    repair = _Chat([_edit("VALUE = compute()\n", "VALUE = 1\n", "constant"),
                    _edit("import numpy\n", "import numpy\n\n\ndef compute():\n    return 1\n", "define it"),
                    {"file_edits": None, "env_delta": [], "explanation": "no third fix"}])
    ultra = _Ultra([{"chosen": 2, "reasoning": "defines the function"}])
    result, _, guard = _run(tmp_path, cloud, repair=repair, adjudicator=ultra, candidates=3, cap=5.0,
                            releaser=lambda **kw: {"released": len(kw["image_ids"]), "cost_usd": 0.0, "seconds": 0.0})
    assert result.verdict == "RUNS_AFTER_REPAIR"
    loser = next(op for op in guard.operations if op["candidate"] == 1)
    winner = next(op for op in guard.operations if op["candidate"] == 2)
    assert loser.get("result_image_released") and loser["result_image"] not in loser["kept_images"]
    assert winner["result_image"] in winner["kept_images"] and not winner.get("result_image_released")
