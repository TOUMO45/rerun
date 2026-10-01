"""harness-v1.4.1-rc, directive item 5 (D-34): apt packages added at repair time are an additive layer on top of the kept environment image,
never a rebuild from the tree image. A fake ConTree cloud (v140_cloud) behind the REAL sandbox runner counts every command it runs, so
the tests assert what was and was not run again.

harness-v1.4.0, corpus-v2 #8: build-essential was added to the plan's FIRST (apt) setup step, the kept torch layer no longer matched, and
the operation started a second torch install (funded 44 s, stopped). Here the apt command is a layer placed after the setup steps the
kept image already holds."""

from __future__ import annotations

import pytest

import v140_cloud
from app.services import runner_hooks, sandbox, sandbox_limits
from app.services.orchestrator import apt_layer_command
from test_v140_pipeline import EXEC, SKLEARN_MISSING, _recorded, _repo, _run, _torch_command

GCC = next(a for a in _recorded("07_albertometelli__pfqi")["result"]["attempts"] if a["attempt_number"] == 2)["stderr_tail"]
NUMPY_MISSING = "ModuleNotFoundError: No module named 'numpy'\n"
LAYER = apt_layer_command(["build-essential"])


def test_the_layer_command_is_not_filed_with_the_system_packages_so_it_keeps_its_place_after_the_kept_steps():
    ops = sandbox_limits.split_setup_ops(["apt-get update && apt-get install -y libx", "pip install foo", LAYER, "pip install bar"])
    assert [(o.kind, o.command) for o in ops] == [("system", "apt-get update && apt-get install -y libx"), ("requirements", "pip install foo"),
                                                  ("requirements", LAYER), ("requirements", "pip install bar")]
    assert LAYER == "export DEBIAN_FRONTEND=noninteractive && apt-get update && apt-get install -y build-essential"
    assert apt_layer_command(["zlib1g-dev", "build-essential"]) == LAYER.replace("build-essential", "build-essential zlib1g-dev")


def test_a_run_time_compiler_need_adds_the_layer_on_top_of_the_whole_environment_and_no_pip_install_follows_it(tmp_path, monkeypatch):
    """The recorded gcc error of corpus-v2 #7 as a failure of the command itself (every setup step succeeded): the environment image is
    complete, so the repair-time apt step is the only setup command that runs, and nothing named `pip install` runs after it."""
    assert "unable to execute 'gcc'" in GCC
    _repo(tmp_path, {"main.py": "import torch\nimport numpy\n"})
    torch_cmd = _torch_command(tmp_path)

    def behaviour(shell, built, files):
        if shell not in EXEC:
            return None
        if not any("numpy==1.19.5" in b for b in built):
            return 1, "", NUMPY_MISSING
        if not any("build-essential" in b for b in built):
            return 1, "", GCC
        return 0, "ok", ""

    cloud = v140_cloud.install(monkeypatch, behaviour)
    result, deps, guard = _run(tmp_path, cloud)
    assert result.verdict == "RUNS_AFTER_REPAIR" and deps.repair_client.calls == []
    at = max(i for i, c in enumerate(cloud.ran) if c == LAYER)
    assert cloud.ran.count(LAYER) == 1
    assert [c for c in cloud.ran[at + 1:] if "pip install" in c] == []
    assert cloud.ran.count(torch_cmd) == 2  # the baseline's and the era environment's; the repair-time step adds none
    tm_op, d24_op = guard.operations[-2], guard.operations[-1]
    assert d24_op["branch_from_image"] == tm_op["env_image_id"] and d24_op["start_setup_commands"] == d24_op["setup_commands"] - 1
    assert [i["command"] for i in d24_op["install_seconds"]] == [LAYER] and not d24_op["torch_installed"]
    assert d24_op["apt_layers"] == [{"packages": ["build-essential"], "after_rest_commands": 1}]
    action = result.attempts[-1].time_machine_action
    assert action["rule"] == "missing_compiler_build_essential" and action["apt_layer"]["layering"] == "additive"
    assert action["apt_layer"]["on_kept_image"] == tm_op["env_image_id"]
    # the certificate's plan still lists the package: the layering is how the sandbox applies it, not what the plan says
    assert "build-essential" in result.certificate()["build_plan"]["apt_install"]


def test_a_build_time_compiler_need_puts_the_layer_before_the_failing_pip_step_and_never_installs_torch_again(tmp_path, monkeypatch):
    """Corpus-v2 #8's shape: the step that needed gcc was a pip step. The kept image holds the steps before it (the torch install and its
    exec-stack fix); the layer goes right after them and the failing step runs once more on top. v1.4.0 rebuilt torch."""
    _repo(tmp_path, {"main.py": "import torch\nimport numpy\n"})
    torch_cmd = _torch_command(tmp_path)

    def behaviour(shell, built, files):
        if "numpy==1.19.5" in shell and "pip install" in shell and not any("build-essential" in b for b in built):
            return 1, "", GCC  # the era lock's pip step fails to build a package: no compiler
        if shell not in EXEC:
            return None
        return (1, "", NUMPY_MISSING) if not any("numpy==1.19.5" in b for b in built) else (0, "ok", "")

    cloud = v140_cloud.install(monkeypatch, behaviour)
    result, deps, guard = _run(tmp_path, cloud)
    assert result.verdict == "RUNS_AFTER_REPAIR", result.full_log[-1500:]
    assert cloud.ran.count(torch_cmd) == 2  # baseline + the era environment; the repair-time step does not install it a third time
    tm_op, d24_op = guard.operations[-2], guard.operations[-1]
    assert tm_op["outcome"] == "completed" and d24_op["outcome"] == "completed"
    assert d24_op["start_setup_commands"] == 2 and d24_op["branch_from_image"] in tm_op["kept_images"]
    commands = [i["command"] for i in d24_op["install_seconds"]]
    assert commands[0] == LAYER and len(commands) == 2 and "numpy==1.19.5" in commands[1]  # the layer, then the step that failed before
    assert not d24_op["torch_installed"] and d24_op["torch_in_start_image"]


def test_with_nothing_kept_to_add_onto_the_package_joins_the_first_apt_step_as_before(tmp_path, monkeypatch):
    """A baseline that already fails for a missing compiler: the era environment is a FRESH build on its own base image (no image of it is
    kept yet), so build-essential is installed by the first apt step, exactly as in v1.4.0; no additive layer exists."""
    _repo(tmp_path, {"main.py": "import numpy\n"})

    def behaviour(shell, built, files):
        if shell not in EXEC:
            return None
        if not any("numpy==1.19.5" in b for b in built):
            return 1, "", GCC
        return 0, "ok", ""

    cloud = v140_cloud.install(monkeypatch, behaviour)
    result, _, guard = _run(tmp_path, cloud)
    assert result.verdict == "RUNS_AFTER_REPAIR"
    assert "apt-get update && apt-get install -y build-essential" in cloud.ran and LAYER not in cloud.ran
    assert not any("apt_layers" in op for op in guard.operations)


def test_a_legacy_runner_without_checkpoints_never_gets_a_layer(tmp_path):
    """The layer needs kept images; a runner that does not declare `checkpoint` keeps the harness-v1.3.x flow (build-essential in the plan)."""
    from app.services.orchestrator import PipelineDeps, run_pipeline
    from app.services.cost_guard import CostGuard
    from app.services.intake import RepoIntake
    from app.services.time_machine import LockResult
    from test_v140_pipeline import _Chat, _head

    _repo(tmp_path, {"main.py": "import numpy\n"})
    calls = []

    def runner(**kw):
        calls.append(kw)
        failing = len(calls) < 3
        stderr = GCC if failing and len(calls) == 2 else (NUMPY_MISSING if failing else "")
        return sandbox.SandboxRunResult(steps=(sandbox.StepResult("python main.py", 1 if failing else 0, "", stderr, 1.0, 0.01),))

    deps = PipelineDeps(recon_client=_Chat([{"entrypoint": "main.py", "confidence": 0.9}]), recon_model="r", repair_client=_Chat(),
                        repair_model="p", adjudicator_client=None, adjudicator_model=None, sandbox_api_key="k",
                        sandbox_wall_clock_seconds=600, sandbox_runner=runner, smoke_seconds=0, candidates_per_round=3,
                        lock_compiler=lambda *a: LockResult(True, ("numpy==1.19.5",), ("numpy",)))
    commit = _head(tmp_path)
    result = run_pipeline(repo_url="https://example.com/r", commit_sha=commit, workdir=tmp_path,
                          intake_result=RepoIntake(tmp_path, commit, {}, frozenset(), (), ("main.py",), None), deps=deps,
                          cost_guard=CostGuard(daily_cost_ceiling_usd=5), run_id="legacy")
    assert result.verdict == "RUNS_AFTER_REPAIR"
    assert all("checkpoint" not in kw for kw in calls)
    assert not any(LAYER in kw["install_commands"] for kw in calls)
    assert any("apt-get update && apt-get install -y build-essential" in kw["install_commands"] for kw in calls)
