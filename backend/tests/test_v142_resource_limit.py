"""harness-v1.4.2-rc, directive items 3 and 4 (D-38, D-40): a kill by SIGKILL (exit 137 / -9) is RESOURCE_LIMIT, not a silent exit; the entry ends INDETERMINATE
with the limit quoted, never BLOCKED, and no model attempt is spent on it. The sandbox's limits are stored on every operation (documented figures: there are none
for memory and CPU) and read inside the sandbox by one evidence run.

Anchor: corpus-v2 #11, harness-v1.4.1 gate: after the CPU shim cleared its GPU error the era run was `Killed` (exit 137) at iteration 1 of 40, in three separate
VMs. The recorded stderr is read from the committed record."""

from __future__ import annotations

import base64
import json
import platform
import shutil
import subprocess
from pathlib import Path

import pytest

import v140_cloud
from app.services import classifier, resource_limits, runner_hooks
from app.services.cost_guard import CostGuard
from app.services.intake import RepoIntake
from app.services.orchestrator import PipelineDeps, run_pipeline
from app.services.sandbox import run_build_and_execute
from app.services.time_machine import LockResult
from test_v140_pipeline import ENTRY_11_GPU, EXEC, SHIM, TQDM_MISSING, _Chat, _head, _repo, _run

ROOT = Path(__file__).resolve().parents[2]
GATE_V141 = ROOT / "runs" / "corpus_v2_batch" / "harness-v1.4.1" / "gate"


def _recorded_kill() -> dict:
    record = json.loads((GATE_V141 / "11_JindongGu__VoteAttack.json").read_text(encoding="utf-8"))
    return next(a for a in record["result"]["attempts"] if a["origin"] == "time_machine" and a["exit_code"] == 137)


def _decoded(shell: str) -> str:
    try:
        return json.loads(base64.b64decode(shell.split()[-1]))["cmd"]
    except Exception:  # noqa: BLE001
        return ""


def evidence_block(exit_status=137, oom_kill=1, dmesg="Out of memory: Killed process 4242 (python)", mem_kb=2048000) -> str:
    return (f"RERUN_EVIDENCE_BEGIN exit_status={exit_status}\n--ulimit\ncore file size (blocks, -c) 0\n--meminfo\nMemTotal:        {mem_kb} kB\nSwapTotal:             0 kB\n"
            f"--nproc\n2\n--kernel\n6.1.0\n--selfcgroup\n0::/\n--cgroup\n/sys/fs/cgroup/memory.max=max \n"
            f"/sys/fs/cgroup/memory.events=low 0 high 0 max 0 oom 1 oom_kill {oom_kill} \n--dmesg\n{dmesg}\nRERUN_EVIDENCE_END\n")


# --- classification ----------------------------------------------------------------------------------------------------------

def test_the_recorded_kill_of_entry_11_is_a_resource_limit_not_a_silent_exit():
    kill = _recorded_kill()
    assert kill["exit_code"] == 137 and kill["stderr_tail"].rstrip().endswith("Killed")
    c = classifier.classify(kill["exit_code"], kill["stderr_tail"], kill["stdout_tail"])
    assert c.code == "RESOURCE_LIMIT" and c.family == "Platform" and "SIGKILL" in c.evidence and "'Killed'" in c.evidence
    assert "RESOURCE_LIMIT" in classifier.TaxonomyCode.SANDBOX_CODES and "RESOURCE_LIMIT" in classifier.TaxonomyCode.ALL
    # v1.4.1 saw nothing in that output: the progress bar that carried "Killed" is denoised away, so it was a silent exit
    assert not classifier.has_actionable_error(kill["stderr_tail"], kill["stdout_tail"])


@pytest.mark.parametrize("code", [137, -9])
def test_sigkill_codes_classify_with_or_without_output(code):
    assert classifier.classify(code, "").code == "RESOURCE_LIMIT" and classifier.classify(code, "", "Killed\n").code == "RESOURCE_LIMIT"


@pytest.mark.parametrize("code", [1, 2, 134, 139, 143, 255])
def test_other_exit_codes_are_not_resource_limits(code):
    """SIGSEGV (139) and SIGABRT (134) are crashes; SIGTERM (143) may be the program's own; they keep their old classification."""
    assert classifier.classify(code, "").code == "RUNTIME_ERROR_OTHER"


def test_a_python_error_with_exit_1_keeps_its_rule():
    assert classifier.classify(1, TQDM_MISSING).code == "DEP_MISSING"


def test_the_attribution_of_a_resource_limit_is_the_sandbox_not_the_repository():
    from app.services import error_chain

    kwargs = dict(declared_deps=frozenset(), python_claim=None, base_image="python:3.10-slim")
    assert error_chain.attribute("RESOURCE_LIMIT", "exit code 137", phase="repo_run", **kwargs) == error_chain.SANDBOX_QUOTA
    assert error_chain.attribute("RESOURCE_LIMIT", "exit code 137", phase=error_chain.PHASE_RUNNER_SETUP, **kwargs) == error_chain.SANDBOX_QUOTA


# --- the evidence command and its parser ------------------------------------------------------------------------------------

@pytest.mark.skipif(not shutil.which("sh"), reason="needs a POSIX sh")
def test_the_evidence_command_keeps_the_exit_status_survives_a_trailing_comment_and_prints_the_block():
    command = runner_hooks.evidence_command("echo working; exit 3 #gpu_id #split")
    proc = subprocess.run([shutil.which("sh"), "-c", command], capture_output=True, text=True, timeout=60)
    assert proc.returncode == 3 and proc.stdout == "working\n"
    evidence = runner_hooks.parse_evidence(proc.stderr)
    assert evidence and evidence["exit_status"] == 3 and evidence["mem_total_kb"] and evidence["nproc"]
    assert not runner_hooks.kill_evidenced(evidence)
    assert "MemTotal" in runner_hooks.limit_quote(evidence)


@pytest.mark.skipif(platform.system() == "Windows" or not shutil.which("sh"), reason="needs a POSIX kernel")
def test_a_real_sigkill_is_evidenced_by_the_exit_status():
    command = runner_hooks.evidence_command("sh -c 'kill -9 $$'")
    proc = subprocess.run([shutil.which("sh"), "-c", command], capture_output=True, text=True, timeout=60)
    assert proc.returncode == 137 and runner_hooks.kill_evidenced(runner_hooks.parse_evidence(proc.stderr))


def test_parse_evidence_reads_every_field_and_kill_evidence_has_three_sources():
    text = "noise\n" + evidence_block(exit_status=1, oom_kill=0, dmesg="") + "after"
    calm = runner_hooks.parse_evidence(text)
    assert calm["exit_status"] == 1 and calm["mem_total_kb"] == 2048000 and calm["nproc"] == 2 and calm["oom_kill"] == 0 and calm["dmesg"] == []
    assert calm["cgroup"]["/sys/fs/cgroup/memory.max"] == "max" and calm["kernel"] == ["6.1.0"] and calm["self_cgroup"] == ["0::/"]
    assert not runner_hooks.kill_evidenced(calm)
    assert runner_hooks.kill_evidenced(runner_hooks.parse_evidence(evidence_block(exit_status=137, oom_kill=0, dmesg="")))  # its own SIGKILL status
    assert runner_hooks.kill_evidenced(runner_hooks.parse_evidence(evidence_block(exit_status=1, oom_kill=2, dmesg="")))  # the cgroup counted an OOM kill
    assert runner_hooks.kill_evidenced(runner_hooks.parse_evidence(evidence_block(exit_status=1, oom_kill=0, dmesg="Out of memory: Killed process 7 (python)")))
    assert not runner_hooks.kill_evidenced(None) and runner_hooks.parse_evidence("no block here") is None and runner_hooks.limit_quote(None) == ""
    quote = runner_hooks.limit_quote(runner_hooks.parse_evidence(evidence_block()))
    assert "MemTotal 2048000 kB (1.95 GiB)" in quote and "nproc 2" in quote and "memory.max max" in quote and "oom_kill 1" in quote and "Killed process 4242" in quote


def test_the_documented_limits_are_stated_as_not_documented_and_nothing_is_invented():
    record = resource_limits.record()
    assert record["memory"].startswith("not documented") and record["cpu"] == "not documented" and record["disk_layer_bytes"] == 12884901888
    assert "no memory, CPU, size or GPU parameter" in record["larger_instance"] and "D-40-resources.md" in record["source"]
    assert "no documented per-operation memory limit" in resource_limits.quote()


# --- the pipeline -----------------------------------------------------------------------------------------------------------

def _cloud_11(monkeypatch, *, evidence: str | None):
    kill = _recorded_kill()

    def behaviour(shell, built, files):
        command = _decoded(shell)
        is_run = shell in EXEC or "RERUN_EVIDENCE_BEGIN" in command
        if not is_run:
            return None
        if not any("numpy==1.19.5" in b for b in built):
            return 1, "", TQDM_MISSING
        if SHIM not in built:
            return 1, ENTRY_11_GPU["stdout_tail"], ENTRY_11_GPU["stderr_tail"]  # the era run: the recorded GPU error
        tail = (evidence or "") if "RERUN_EVIDENCE_BEGIN" in command else ""
        return 137, kill["stdout_tail"], kill["stderr_tail"] + tail  # after the shim: the recorded kill

    return v140_cloud.install(monkeypatch, behaviour)


def test_entry_11s_kill_ends_resource_limit_with_the_limit_quoted_and_no_model_attempt(tmp_path, monkeypatch):
    _repo(tmp_path, {"main.py": "import torch\nimport tqdm\ntorch.load('model.pt')\n"})
    cloud = _cloud_11(monkeypatch, evidence=evidence_block())
    repair = _Chat([], "repair model")  # raises if called
    result, deps, guard = _run(tmp_path, cloud, repair=repair)
    assert result.verdict == "INDETERMINATE" and result.taxonomy_code == "RESOURCE_LIMIT"
    assert result.indeterminate_reason.startswith("RESOURCE_LIMIT: exit code 137: the process was killed by SIGKILL")
    assert "MemTotal 2048000 kB" in result.indeterminate_reason and "oom_kill 1" in result.indeterminate_reason  # the limit as the sandbox showed it
    assert "no repair attempt was made" in result.indeterminate_reason
    assert repair.calls == [] and not [a for a in result.attempts if a.origin == "model"]
    shim = next(a for a in result.attempts if a.time_machine_action and a.time_machine_action["rule"] == "cpu_shim")
    assert shim.exit_code == 137
    evidence = next(a for a in result.attempts if a.time_machine_action and a.time_machine_action["rule"] == "resource_evidence")
    assert evidence.time_machine_action["kill_evidenced"] is True and evidence.time_machine_action["evidence"]["mem_total_kb"] == 2048000
    assert sum(1 for op in guard.operations if op["role"] == "resource evidence") == 1  # one evidence run per entry
    assert is_our_fault(result.indeterminate_reason)


def is_our_fault(reason: str) -> bool:
    from app.services.orchestrator import is_our_fault as ours, reason_code_of

    return ours(reason_code_of(reason))


def test_every_operation_stores_the_sandbox_limits_as_documented(tmp_path, monkeypatch):
    _repo(tmp_path, {"main.py": "import torch\nimport tqdm\ntorch.load('model.pt')\n"})
    cloud = _cloud_11(monkeypatch, evidence=evidence_block())
    _, _, guard = _run(tmp_path, cloud, repair=_Chat([], "repair model"))
    assert guard.operations and all(op["resource_limits"] == resource_limits.record() for op in guard.operations if "wall_seconds" in op)
    assert all(op["resource_limits"]["memory"].startswith("not documented") for op in guard.operations if "wall_seconds" in op)


def test_without_evidence_the_documented_limits_are_quoted_and_the_verdict_is_the_same(tmp_path, monkeypatch):
    _repo(tmp_path, {"main.py": "import torch\nimport tqdm\ntorch.load('model.pt')\n"})
    cloud = _cloud_11(monkeypatch, evidence=None)  # the evidence run prints no block
    result, _, _ = _run(tmp_path, cloud, repair=_Chat([], "repair model"))
    assert result.verdict == "INDETERMINATE" and "documented: no documented per-operation memory limit" in result.indeterminate_reason


def test_a_baseline_killed_by_sigkill_is_indeterminate_and_the_control_arm_runs_no_extra_operation(tmp_path, monkeypatch):
    _repo(tmp_path, {"main.py": "import numpy\n"})

    def behaviour(shell, built, files):
        return (137, "", "Killed\n") if shell in EXEC or "RERUN_EVIDENCE_BEGIN" in _decoded(shell) else None

    cloud = v140_cloud.install(monkeypatch, behaviour)
    deps = PipelineDeps(recon_client=_Chat([{"entrypoint": "main.py", "confidence": 0.9}], "recon"), recon_model="r", repair_client=_Chat([], "repair"),
                        repair_model="p", adjudicator_client=None, adjudicator_model=None, sandbox_api_key="k", sandbox_wall_clock_seconds=600,
                        sandbox_runner=run_build_and_execute, smoke_seconds=60, repair_enabled=False, lock_compiler=lambda *a: LockResult(False, error="x"))
    commit = _head(tmp_path)
    guard = CostGuard(daily_cost_ceiling_usd=5)
    result = run_pipeline(repo_url="https://example.com/r", commit_sha=commit, workdir=tmp_path,
                          intake_result=RepoIntake(tmp_path, commit, {}, frozenset(), (), ("main.py",), None), deps=deps, cost_guard=guard,
                          run_id="control", documented_command="python main.py")
    assert result.verdict == "INDETERMINATE" and result.indeterminate_reason.startswith("RESOURCE_LIMIT: ")
    assert [op["role"] for op in guard.operations] == ["baseline"]  # CONTROL: no evidence run, nothing repaired
    assert "documented: no documented per-operation memory limit" in result.indeterminate_reason


def test_a_candidate_killed_by_sigkill_does_not_get_the_exit_hook_or_the_wrapper(tmp_path, monkeypatch):
    """A SIGKILL is not a silent exit: the hook and wrapper rules must not fire on a candidate whose run was killed."""
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
    from test_v140_pipeline import _Ultra, _edit

    fix = _edit("import numpy\n", "import numpy\n\n\ndef compute():\n    return 1\n", "define the helper")
    decline = {"file_edits": None, "env_delta": [], "explanation": "nothing else"}
    result, _, guard = _run(tmp_path, cloud, repair=_Chat([fix, decline, decline], "repair model"), adjudicator=_Ultra([{"chosen": 1, "reasoning": "x"}]),
                            candidates=3, cap=5.0, max_attempts=1)
    killed = next(a for a in result.attempts if a.candidate == 1 and a.gate_decision == "PASS")
    assert killed.exit_code == 137 and killed.time_machine_action is None
    assert not [op for op in guard.operations if ": exit_site_hook" in op["role"] or ": exit_wrapper" in op["role"]]
    assert result.verdict == "INDETERMINATE" and result.taxonomy_code == "RESOURCE_LIMIT"  # the adopted candidate's failure is the kill
