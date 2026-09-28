"""A2 (2026-09-28): gated env op `pip_no_build_isolation`.

TTPT v5 (runs/live_run_ttpt_v5.json) ended BLOCKED because Dassl's legacy
setup.py imports numpy at build time and pip builds it in an ISOLATED build
env where the locked numpy is invisible. The op builds one named package with
`pip install --no-build-isolation`, after everything else is installed — and
the env gate allows it only when the build log shows that package's build
backend failing to import a module that IS in the lock.

The logs below are shaped on TTPT v5's real output (stdout "Collecting dassl@
git+…", stderr the isolated build backend's traceback)."""

from __future__ import annotations

import json
import shlex
from datetime import date
from pathlib import Path

import pytest

from app.services import time_machine
from app.services.cost_guard import CostGuard
from app.services.env_repair import (
    REQUIREMENTS_OVERRIDE_FILE,
    EnvChange,
    EnvRule,
    apply_env_delta,
    build_isolation_evidence,
    check_env_delta,
    find_build_isolation_candidate,
)
from app.services.intake import RepoIntake
from app.services.orchestrator import PipelineDeps, run_pipeline
from app.services.planner import BuildPlan
from app.services.sandbox import SandboxRunResult, StepResult
from app.services.time_machine import EraDate, LockResult

SHA = "c61a1b570ac6333bd50fb5ae06aea59002fb20bb"
DASSL = f"dassl @ git+https://github.com/KaiyangZhou/Dassl.pytorch@{SHA}"
LOCK = ("numpy==2.1.0", "setuptools==74.0.0", "torch==2.4.0", DASSL)
LOCK_WITHOUT_NUMPY = ("setuptools==74.0.0", "torch==2.4.0", DASSL)

BUILD_STDOUT = (
    f"Collecting dassl@ git+https://github.com/KaiyangZhou/Dassl.pytorch@{SHA} (from -r .rerun-requirements.txt (line 4))\n"
    "  Cloning https://github.com/KaiyangZhou/Dassl.pytorch to /tmp/pip-install-x/dassl\n"
    "  Installing build dependencies: finished with status 'done'\n"
    "  Getting requirements to build wheel: started\n"
    "  Getting requirements to build wheel: finished with status 'error'\n"
)
BUILD_STDERR = (
    "  error: subprocess-exited-with-error\n"
    "      File \"/tmp/pip-build-env-zn7stomz/overlay/lib/python3.12/site-packages/setuptools/build_meta.py\", line 317, in run_setup\n"
    "        exec(code, locals())\n"
    "      File \"<string>\", line 1, in <module>\n"
    "      ModuleNotFoundError: No module named 'numpy'\n"
    "× Getting requirements to build wheel did not run successfully.\n"
)
BUILD_LOG = BUILD_STDERR + "\n" + BUILD_STDOUT  # the orchestrator's failure_log order
EVIDENCE = "ModuleNotFoundError: No module named 'numpy'"


def _nbi(package="dassl", **kw) -> EnvChange:
    base = dict(
        op="pip_no_build_isolation",
        package=package,
        justification="dassl's setup.py imports numpy at build time; numpy is locked but invisible to the isolated build",
        evidence=EVIDENCE,
    )
    base.update(kw)
    return EnvChange(**base)


def _check(change, *, log=BUILD_LOG, lock=LOCK):
    return check_env_delta(
        (change,), log_text=log, imported_modules=frozenset({"dassl", "torch"}), has_requirements_txt=True,
        locked_requirements=lock,
    )


def _rules(violations):
    return {v.rule for v in violations}


# --- Gate: positive case --------------------------------------------------


def test_positive_build_backend_missing_a_locked_module_passes():
    assert build_isolation_evidence("dassl", BUILD_LOG, LOCK) == "numpy"
    assert _check(_nbi()) == ()


def test_positive_package_name_is_matched_pep503_normalized():
    log = BUILD_LOG.replace("Collecting dassl@", "Collecting Dassl@")
    assert _check(_nbi(package="DASSL"), log=log) == ()


# --- Gate: the required negative control ----------------------------------


def test_negative_control_module_absent_from_the_lock_is_rejected():
    """Same log, but numpy is NOT in the lock: turning off isolation would
    not make it importable, so the op must be rejected."""
    violations = _check(_nbi(), lock=LOCK_WITHOUT_NUMPY)
    assert _rules(violations) == {EnvRule.ENV_BUILD_ISOLATION_UNJUSTIFIED}


# --- Gate: further rejections ----------------------------------------------


def test_rejected_when_the_import_error_is_at_runtime_not_in_a_build_backend():
    runtime_log = (
        "Collecting dassl@ git+https://github.com/KaiyangZhou/Dassl.pytorch\n"
        "Successfully installed dassl-0.6.3\n"
        "Traceback (most recent call last):\n  File \"train.py\", line 1\nModuleNotFoundError: No module named 'numpy'\n"
    )
    assert _rules(_check(_nbi(), log=runtime_log)) == {EnvRule.ENV_BUILD_ISOLATION_UNJUSTIFIED}


def test_rejected_when_the_log_never_collects_the_named_package():
    # torch is in the lock, but the build that failed was dassl's.
    assert _rules(_check(_nbi(package="torch"))) == {EnvRule.ENV_BUILD_ISOLATION_UNJUSTIFIED}


def test_rejected_when_the_package_is_not_being_installed():
    assert _rules(_check(_nbi(package="yacs"))) == {EnvRule.ENV_UNSUPPORTED}


def test_rejected_without_a_resolved_lock():
    assert _rules(_check(_nbi(), lock=None)) == {EnvRule.ENV_UNSUPPORTED}


def test_rejected_with_a_version_and_without_verbatim_evidence():
    assert EnvRule.ENV_INVALID_CHANGE in _rules(_check(_nbi(version="0.6.3")))
    assert _rules(_check(_nbi(evidence="No module named 'scipy'"))) == {EnvRule.ENV_UNJUSTIFIED}


# --- Application: two-stage install -----------------------------------------


def test_apply_installs_the_lock_first_then_the_package_without_isolation():
    plan = BuildPlan(
        base_image="python:3.12-slim",
        apt_install=("git",),
        install_commands=(f"printf x > {REQUIREMENTS_OVERRIDE_FILE} && pip install -r {REQUIREMENTS_OVERRIDE_FILE}",),
        execute_command="bash run_ttpt.sh",
    )
    new_plan, new_requirements = apply_env_delta(plan, (_nbi(),), "\n".join(LOCK) + "\n")

    assert "dassl" not in new_requirements
    assert "numpy==2.1.0" in new_requirements
    first, second = new_plan.install_commands
    assert first.endswith(f"pip install -r {REQUIREMENTS_OVERRIDE_FILE}") and "dassl" not in first
    assert second == f"pip install --no-build-isolation '{DASSL}'"
    assert new_plan.execute_command == "bash run_ttpt.sh"


# --- End to end through the orchestrator (real env gate) ------------------


class _Chat:
    def __init__(self, responses):
        self._responses = list(responses)

    def chat_completion(self, **kwargs):
        return self._responses.pop(0)


class _Sandbox:
    """Fails with the isolated-build error until dassl is installed with
    --no-build-isolation (and only if numpy was installed before it)."""

    def __init__(self):
        self.calls = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        cmds = list(kwargs["install_commands"])
        installed = " ".join(cmds)
        if "dassl" not in installed:  # baseline: the declared install only
            return SandboxRunResult(steps=(StepResult("bash run.sh", 1, "", "ModuleNotFoundError: No module named 'numpy'", 1.0, 0.0),))
        nbi = [i for i, c in enumerate(cmds) if "--no-build-isolation" in c and "dassl" in c]
        lock_step = [i for i, c in enumerate(cmds) if "numpy==2.1.0" in c]
        if nbi and lock_step and lock_step[0] < nbi[0] and "dassl" not in cmds[lock_step[0]]:
            return SandboxRunResult(steps=(StepResult("bash run.sh", 0, "trained", "", 1.0, 0.0),))
        return SandboxRunResult(steps=(StepResult("pip install", 1, BUILD_STDOUT, BUILD_STDERR, 1.0, 0.0),))


def _run(tmp_path, monkeypatch, lock_lines, responses):
    (tmp_path / "requirements.txt").write_text("torch\n", encoding="utf-8")
    (tmp_path / "train.py").write_text("import numpy\nimport dassl\n", encoding="utf-8")
    monkeypatch.setattr(time_machine, "era_date", lambda *a: EraDate(date(2024, 8, 30), "dependency-files"))
    intake = RepoIntake(tmp_path, "a" * 40, {"requirements.txt": "torch\n"}, frozenset({"torch"}), (), ("train.py",), None)
    sandbox = _Sandbox()
    deps = PipelineDeps(
        recon_client=_Chat([json.dumps({"entrypoint": "train.py", "confidence": 0.9})]),
        recon_model="r",
        repair_client=_Chat([json.dumps(r) for r in responses]),
        repair_model="p",
        adjudicator_client=None,
        adjudicator_model=None,
        sandbox_api_key="k",
        sandbox_wall_clock_seconds=60,
        sandbox_runner=sandbox,
        max_attempts=len(responses),
        lock_compiler=lambda *a: LockResult(True, tuple(lock_lines)),
    )
    result = run_pipeline(repo_url="https://example.com/r", commit_sha="a" * 40, workdir=tmp_path, intake_result=intake,
                          deps=deps, cost_guard=CostGuard(daily_cost_ceiling_usd=100), run_id="nbi",
                          documented_command="bash run.sh")
    return result, sandbox


_NBI_REPLY = {
    "code_diff": None,
    "env_delta": [{"op": "pip_no_build_isolation", "package": "dassl", "justification": "numpy is locked; the isolated build can't see it", "evidence": EVIDENCE}],
    "explanation": "build dassl without build isolation",
}


def test_end_to_end_isolated_build_failure_is_repaired_deterministically(tmp_path, monkeypatch):
    """A2b: the time machine applies the op itself — no model is consulted,
    and the certificate records the deterministic step with its evidence."""
    lock_with_numpy = ("numpy==2.1.0", "setuptools==74.0.0", DASSL)
    result, sandbox = _run(tmp_path, monkeypatch, lock_with_numpy, [])
    assert result.verdict == "RUNS_AFTER_REPAIR", result.full_log
    assert result.repair_mode == "deterministic"
    assert not [a for a in result.attempts if a.origin == "model"]
    step = result.attempts[-1]
    assert step.origin == "time_machine" and step.gate_decision == "PASS"
    assert step.env_delta[0]["op"] == "pip_no_build_isolation" and step.env_delta[0]["package"] == "dassl"
    assert step.time_machine == {
        "step": "pip_no_build_isolation", "package": "dassl", "module": "numpy", "evidence": EVIDENCE,
    }
    assert "--no-build-isolation" in sandbox.calls[-1]["install_commands"][-1]
    # Baseline, era lock, then the build-isolation step: three executions.
    assert len(sandbox.calls) == 3
    certificate_steps = [d for d in result.certificate()["diffs"] if (d["time_machine"] or {}).get("step")]
    assert certificate_steps[0]["time_machine"]["evidence"] == EVIDENCE


def test_end_to_end_negative_control_module_not_in_lock_is_rejected(tmp_path, monkeypatch):
    """Same build failure, but numpy is not in the lock: the deterministic
    step does not fire, the gate refuses the model's op, no
    --no-build-isolation install ever runs, the run is BLOCKED."""
    lock_without_numpy = ("setuptools==74.0.0", DASSL)
    result, sandbox = _run(tmp_path, monkeypatch, lock_without_numpy, [_NBI_REPLY])
    assert not [a for a in result.attempts if (a.time_machine or {}).get("step")]
    attempt = [a for a in result.attempts if a.origin == "model"][0]
    assert attempt.gate_decision == "REJECT"
    assert {v["rule"] for v in attempt.gate_violations} == {EnvRule.ENV_BUILD_ISOLATION_UNJUSTIFIED}
    assert result.verdict == "BLOCKED"
    assert not any("--no-build-isolation" in c for call in sandbox.calls for c in call["install_commands"])


# --- A2b: the deterministic finder on the REAL TTPT v5 build log ----------

_V5 = Path(__file__).resolve().parents[2] / "runs" / "live_run_ttpt_v5.json"


def _v5_log_and_lock():
    record = json.loads(_V5.read_text(encoding="utf-8"))
    attempt = record["result"]["attempts"][3]  # repair 3: the isolated-build failure
    log = f"{attempt['stderr_tail']}\n{attempt['stdout_tail']}"
    write = record["certificate"]["build_plan"]["install_commands"][0].split(" > ")[0]
    lock = tuple(shlex.split(write)[2:])  # printf '%s\n' <lock lines...>
    return log, lock


def test_deterministic_finder_positive_on_the_real_ttpt_v5_log():
    log, lock = _v5_log_and_lock()
    assert any(line.startswith("numpy==") for line in lock) and any(line.startswith("dassl @ git+") for line in lock)
    package, module, evidence = find_build_isolation_candidate(log, lock)
    assert (package, module) == ("dassl", "numpy")
    assert evidence == "ModuleNotFoundError: No module named 'numpy'"
    assert evidence in log


def test_deterministic_finder_negative_on_the_real_log_when_module_not_in_lock():
    log, lock = _v5_log_and_lock()
    assert find_build_isolation_candidate(log, tuple(l for l in lock if not l.startswith("numpy=="))) is None


def test_deterministic_finder_skips_packages_already_handled():
    log, lock = _v5_log_and_lock()
    assert find_build_isolation_candidate(log, lock, exclude=frozenset({"dassl"})) is None
