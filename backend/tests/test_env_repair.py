"""Environment-layer repair: the deterministic env gate, build-plan
materialization, classifier routing, and end-to-end through the orchestrator."""

from __future__ import annotations

import json
import shlex
from pathlib import Path

import pytest

from app.services import classifier
from app.services.cost_guard import CostGuard
from app.services.env_repair import (
    EnvChange,
    EnvRule,
    REQUIREMENTS_OVERRIDE_FILE,
    apply_env_delta,
    check_env_delta,
    imported_top_level_modules,
    parse_env_delta,
)
from app.services.intake import RepoIntake
from app.services.orchestrator import PipelineDeps, run_pipeline
from app.services.passport import verify_certificate
from app.services.planner import BuildPlan
from app.services.sandbox import SandboxRunResult, StepResult

LOG = (
    "Collecting regex==2017.4.5\n"
    "  error: command 'gcc' failed: No such file or directory\n"
    "ERROR: Failed building wheel for regex\n"
    "ModuleNotFoundError: No module named 'dassl'\n"
)
SHA = "c4d3e9f1a2b3c4d5e6f708192a3b4c5d6e7f8091"


def _ok(**kw) -> EnvChange:
    base = dict(justification="gcc is missing, needed to build regex", evidence="error: command 'gcc' failed")
    base.update(kw)
    return EnvChange(**base)


def _rules(violations):
    return {v.rule for v in violations}


def _check(*changes, imported=frozenset({"regex", "numpy"}), has_req=True):
    return check_env_delta(tuple(changes), log_text=LOG, imported_modules=imported, has_requirements_txt=has_req)


# --- Valid deltas PASS (negative controls for every rule below) ------------


@pytest.mark.parametrize(
    "change",
    [
        _ok(op="apt", package="build-essential"),
        _ok(op="pin", package="regex", version="2023.12.25"),
        _ok(op="unpin", package="regex"),
        _ok(op="add", package="torch", version=None),
        _ok(op="add", package="torch", version="2.3.1"),
        _ok(op="remove", package="tensorflow-gpu"),
        _ok(op="python", version="3.8"),
        _ok(op="pip_git", package="dassl", git_url="https://github.com/KaiyangZhou/Dassl.pytorch", commit=SHA,
            evidence="No module named 'dassl'"),
    ],
)
def test_valid_env_change_passes(change):
    assert _check(change) == ()


# --- ENV_REMOVES_IMPORTED --------------------------------------------------


@pytest.mark.parametrize("package", ["numpy", "NumPy", "regex"])
def test_removing_an_imported_package_is_rejected(package):
    assert EnvRule.ENV_REMOVES_IMPORTED in _rules(_check(_ok(op="remove", package=package)))


def test_removing_an_imported_package_via_dist_alias_is_rejected():
    # scikit-learn is imported as sklearn.
    v = _check(_ok(op="remove", package="scikit-learn"), imported=frozenset({"sklearn"}))
    assert EnvRule.ENV_REMOVES_IMPORTED in _rules(v)


def test_negative_control_removing_a_non_imported_package_passes():
    assert _check(_ok(op="remove", package="tensorboard")) == ()


# --- ENV_DATA_URL -----------------------------------------------------------


@pytest.mark.parametrize(
    "change",
    [
        _ok(op="add", package="https://example.com/weights.pt"),
        _ok(op="pin", package="regex", version="https://evil.example/x.whl"),
        _ok(op="add", package="torch", git_url="https://github.com/pytorch/pytorch"),  # git_url on a non-git op
        _ok(op="pip_git", package="data", git_url="https://example.com/data.zip", commit=SHA),
        _ok(op="pip_git", package="dassl", git_url="http://github.com/o/r", commit=SHA),  # not https
        _ok(op="pip_git", package="dassl", git_url="https://user:tok@github.com/o/r", commit=SHA),  # credentials
    ],
)
def test_urls_other_than_a_pinned_git_source_are_rejected(change):
    assert EnvRule.ENV_DATA_URL in _rules(_check(change))


# --- ENV_GIT_UNPINNED -------------------------------------------------------


@pytest.mark.parametrize("commit", [None, "main", "v1.0", "abc1234", SHA[:39], SHA.upper()])
def test_git_source_must_be_pinned_to_a_full_sha(commit):
    change = _ok(op="pip_git", package="dassl", git_url="https://github.com/KaiyangZhou/Dassl.pytorch", commit=commit)
    assert EnvRule.ENV_GIT_UNPINNED in _rules(_check(change))


# --- ENV_INVALID_NAME -------------------------------------------------------


@pytest.mark.parametrize(
    "change",
    [
        _ok(op="apt", package="gcc; rm -rf /"),
        _ok(op="apt", package="Build-Essential"),
        _ok(op="add", package="torch --index-url x"),
        _ok(op="add", package="-e ."),
        _ok(op="pin", package="regex", version=">=2020"),
        _ok(op="pin", package="regex", version="1.0; os_name=='nt'"),
        _ok(op="python", version="2.7"),
        _ok(op="python", version="3.11-slim"),
    ],
)
def test_invalid_names_and_versions_are_rejected(change):
    assert EnvRule.ENV_INVALID_NAME in _rules(_check(change))


# --- ENV_UNJUSTIFIED --------------------------------------------------------


@pytest.mark.parametrize(
    "change",
    [
        _ok(op="apt", package="build-essential", justification=""),
        _ok(op="apt", package="build-essential", justification="line one\nline two"),
        _ok(op="apt", package="build-essential", evidence=""),
        _ok(op="apt", package="build-essential", evidence="gcc"),  # too short to identify a log line
        _ok(op="apt", package="build-essential", evidence="error: command 'clang' failed"),  # not in the log
    ],
)
def test_changes_need_a_justification_tied_to_a_real_log_line(change):
    assert EnvRule.ENV_UNJUSTIFIED in _rules(_check(change))


# --- ENV_UNSUPPORTED / ENV_TOO_LARGE / ENV_INVALID_CHANGE -------------------


def test_unpin_without_requirements_txt_is_rejected():
    assert EnvRule.ENV_UNSUPPORTED in _rules(_check(_ok(op="unpin", package="regex"), has_req=False))


def test_negative_control_add_without_requirements_txt_passes():
    assert _check(_ok(op="add", package="torch"), has_req=False) == ()


def test_too_many_changes_rejected():
    changes = [_ok(op="apt", package=f"pkg{i}") for i in range(11)]
    assert EnvRule.ENV_TOO_LARGE in _rules(_check(*changes))


def test_unknown_op_and_malformed_delta_are_rejected():
    assert EnvRule.ENV_INVALID_CHANGE in _rules(_check(_ok(op="curl", package="x")))
    _, violations = parse_env_delta({"op": "apt"})
    assert EnvRule.ENV_INVALID_CHANGE in _rules(violations)
    _, violations = parse_env_delta(["not an object"])
    assert EnvRule.ENV_INVALID_CHANGE in _rules(violations)


# --- imported-module scan ---------------------------------------------------


def test_imported_top_level_modules_scans_repo_code(tmp_path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "train.py").write_text("import numpy as np\nfrom sklearn.metrics import f1_score\n", encoding="utf-8")
    (tmp_path / "pkg" / "m.py").write_text("import torch.nn\nfrom . import sibling\n", encoding="utf-8")
    (tmp_path / "broken.py").write_text("def (:\n", encoding="utf-8")
    assert imported_top_level_modules(tmp_path) == {"numpy", "sklearn", "torch"}


# --- materialization into the build plan ------------------------------------

PLAN = BuildPlan(
    base_image="python:3.11-slim",
    apt_install=(),
    install_commands=("pip install -r requirements.txt",),
    execute_command="python src/gen.py",
)
REQS = "fire>=0.1.3\nregex==2017.4.5\nrequests==2.21.0\ntqdm==4.31.1\n"


def test_apply_env_delta_edits_a_rerun_owned_requirements_copy():
    changes = (
        _ok(op="apt", package="build-essential"),
        _ok(op="pin", package="regex", version="2023.12.25"),
        _ok(op="python", version="3.8"),
        _ok(op="add", package="tensorflow", version="1.15.5"),
    )
    plan, reqs = apply_env_delta(PLAN, changes, REQS)
    assert plan.base_image == "python:3.8-slim"
    assert plan.apt_install == ("build-essential",)
    assert reqs == "fire>=0.1.3\nregex==2023.12.25\nrequests==2.21.0\ntqdm==4.31.1\ntensorflow==1.15.5\n"
    (cmd,) = plan.install_commands
    assert cmd.endswith(f"pip install -r {REQUIREMENTS_OVERRIDE_FILE}")
    assert "regex==2023.12.25" in shlex.split(cmd)
    # A second delta rewrites the same override, cumulatively.
    plan2, reqs2 = apply_env_delta(plan, (_ok(op="unpin", package="requests"),), reqs)
    assert "requests\n" in reqs2 and "regex==2023.12.25" in reqs2
    assert len(plan2.install_commands) == 1 and "requests" in shlex.split(plan2.install_commands[0])


def test_apply_env_delta_without_requirements_appends_a_pip_step():
    plan = BuildPlan("python:3.11-slim", (), ("pip install .",), "python train.py")
    new_plan, reqs = apply_env_delta(
        plan,
        (_ok(op="pip_git", package="dassl", git_url="https://github.com/KaiyangZhou/Dassl.pytorch", commit=SHA),),
        None,
    )
    assert reqs is None
    assert new_plan.install_commands == (
        "pip install .",
        f"pip install 'dassl @ git+https://github.com/KaiyangZhou/Dassl.pytorch@{SHA}'",
    )


def test_apply_env_delta_quotes_everything_it_puts_in_a_shell_command():
    # Names are validated by the gate first, but materialization must be
    # safe on its own too.
    evil = "x'; touch pwned; echo '"
    plan, _ = apply_env_delta(PLAN, (_ok(op="add", package=evil),), REQS)
    tokens = shlex.split(plan.install_commands[0])
    # The whole malicious string is ONE printf argument, never shell syntax.
    assert evil in tokens
    assert tokens.count(">") == 1 and tokens.count("&&") == 1


# --- routing ---------------------------------------------------------------


@pytest.mark.parametrize(
    "code,layer",
    [
        ("SYS_LIB_MISSING", "env"),
        ("DEP_MISSING", "env"),
        ("DEP_UNPINNED_CONFLICT", "env"),
        ("DEP_YANKED_GONE", "env"),
        ("PY_VERSION_INCOMPAT", "env"),
        ("RUNTIME_ERROR_OTHER", "code"),
        ("HARDCODED_PATH", "code"),
        ("DATA_MISSING", "code"),
    ],
)
def test_classifier_routes_environment_codes_to_env_repair_first(code, layer):
    assert classifier.repair_layer_for(code) == layer


# --- end to end ------------------------------------------------------------


class _Chat:
    def __init__(self, responses):
        self._responses = list(responses)
        self.prompts = []

    def chat_completion(self, **kwargs):
        self.prompts.append(kwargs)
        return self._responses.pop(0)


class _Sandbox:
    """Fails the install until build-essential is in the plan's apt step."""

    def __init__(self):
        self.calls: list[dict] = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        steps = list(kwargs["install_commands"])
        if not any("build-essential" in s for s in steps):
            return SandboxRunResult(
                steps=(StepResult("pip install -r requirements.txt", 1, "", LOG, 1.0, 0.001),)
            )
        return SandboxRunResult(steps=(StepResult("python gen.py", 0, "ok", "", 1.0, 0.001),))


def _run(tmp_path, repair_responses):
    (tmp_path / "requirements.txt").write_text(REQS, encoding="utf-8")
    (tmp_path / "gen.py").write_text("import regex\nprint(regex.__name__)\n", encoding="utf-8")
    intake = RepoIntake(
        local_path=tmp_path,
        commit_sha="a" * 40,
        dependency_files={"requirements.txt": REQS},
        declared_dependencies=frozenset({"fire", "regex", "requests", "tqdm"}),
        notebook_paths=(),
        entrypoint_candidates=("gen.py",),
        python_version_hint=None,
    )
    sandbox = _Sandbox()
    repair = _Chat([json.dumps(r) for r in repair_responses])
    deps = PipelineDeps(
        recon_client=_Chat([json.dumps({"entrypoint": "gen.py", "confidence": 0.9})]),
        recon_model="r",
        repair_client=repair,
        repair_model="p",
        adjudicator_client=None,
        adjudicator_model=None,
        sandbox_api_key="k",
        sandbox_wall_clock_seconds=60,
        sandbox_runner=sandbox,
        max_attempts=len(repair_responses),
    )
    result = run_pipeline(
        repo_url="https://example.com/r",
        commit_sha="a" * 40,
        workdir=tmp_path,
        intake_result=intake,
        deps=deps,
        cost_guard=CostGuard(daily_cost_ceiling_usd=100),
        run_id="env",
    )
    return result, sandbox, repair


APT_FIX = {
    "code_diff": None,
    "env_delta": [
        {"op": "apt", "package": "build-essential", "justification": "gcc is missing to build regex",
         "evidence": "error: command 'gcc' failed"}
    ],
    "explanation": "install a compiler",
}


def test_sys_lib_missing_is_repaired_at_the_env_layer_end_to_end(tmp_path):
    result, sandbox, repair = _run(tmp_path, [APT_FIX])
    assert result.verdict == "RUNS_AFTER_REPAIR", result.full_log
    assert "Repair layer hint: ENV" in repair.prompts[0]["user_prompt"]
    attempt = result.attempts[0]
    assert attempt.gate_decision == "PASS"
    assert attempt.diff_text == ""  # no code diff
    assert attempt.env_delta[0]["op"] == "apt"
    # The re-execution really ran with the new plan; the repo file is untouched.
    assert "build-essential" in sandbox.calls[1]["install_commands"][0]
    assert (tmp_path / "requirements.txt").read_text(encoding="utf-8") == REQS


def test_env_delta_violation_rejects_the_attempt_and_nothing_is_applied(tmp_path):
    bad = {
        "code_diff": None,
        "env_delta": [{"op": "apt", "package": "build-essential", "justification": "x",
                       "evidence": "a line that was never in the log"}],
        "explanation": "",
    }
    result, sandbox, _ = _run(tmp_path, [bad])
    assert result.verdict == "BLOCKED"
    assert result.attempts[0].gate_decision == "REJECT"
    assert EnvRule.ENV_UNJUSTIFIED in {v["rule"] for v in result.attempts[0].gate_violations}
    assert len(sandbox.calls) == 1


def test_passport_covers_the_environment_delta(tmp_path):
    result, _, _ = _run(tmp_path, [APT_FIX])
    cert = {
        "repo_url": result.repo_url,
        "commit_sha": result.commit_sha,
        "build_plan": result.build_plan or {},
        "full_log": result.full_log,
        "diffs": [a.as_dict() for a in result.attempts],
        "verdict": result.verdict,
        "timestamp": result.timestamp,
        "reproduction_passport_hash": result.reproduction_passport_hash,
    }
    assert verify_certificate(cert)
    cert["diffs"][0]["env_delta"][0]["package"] = "something-else"
    assert not verify_certificate(cert)
