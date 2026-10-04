"""harness-v1.7, R1 (METHODOLOGY "harness-v1.7 — PRE-REGISTRATION"): RESOURCE_LIMIT, the sandbox kills the process for memory.

Recorded: DEV #17 round 3 (runs/corpus_v2_batch/harness-v1.5.2/dev/17_*.json: `sh ./fs_train.sh`, killed at the first training batch, dmesg `Killed process 78
(python3) ... anon-rss:3864856kB`) and gate #11 v1.4.2 / v1.4.3 (runs/corpus_v2_batch/harness-v1.4.[23]/gate/11_*.json: `python main.py --evaluate ...`, killed at
batch 2 of 40, `anon-rss:3895992kB`). Class-level: two entries. What the records show and the pre-registration states: the main process is killed, #11 already
passes num_workers=0, so the memory hook (c) is not expected to clear either alone; resource_adapt (d) applies to #11 (a Python entry with --batch_size and
--test_batch_size, defaults 256) and not to #17 (a shell script).

Offline: the recorded output tails replayed through a fake sandbox; the real classifier and orchestrator run; the model client raises if it is called. The
hook itself on REAL torch (RERUN_REAL_TORCH_PYTHON, WSL)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services import blocker, classifier, outcome_levels, resource_adapt, runner_env, runner_hooks
from app.services.cost_guard import CostGuard
from app.services.intake import RepoIntake
from app.services.orchestrator import PipelineDeps, run_pipeline
from app.services.sandbox import SandboxRunResult, StepResult
from test_v151_pins_and_removals import _Chat, _git_repo, _ok

ROOT = Path(__file__).resolve().parents[2]
R17 = ROOT / "runs" / "corpus_v2_batch" / "harness-v1.5.2" / "dev" / "17_Haichao-Zhang__FeatureScatter.json"
R11 = [ROOT / "runs" / "corpus_v2_batch" / tag / "gate" / "11_JindongGu__VoteAttack.json" for tag in ("harness-v1.4.2", "harness-v1.4.3")]
VOTE_MAIN = ("import argparse\nparser = argparse.ArgumentParser()\n"
             "parser.add_argument('--batch_size', type=int, default=256, metavar='N', help='input batch size for training')\n"
             "parser.add_argument('--test_batch_size', type=int, default=256, metavar='N', help='input batch size for testing')\n"
             "parser.add_argument('--evaluate', action='store_true')\nargs = parser.parse_args()\n")


def _kill(path: Path) -> dict:
    """The recorded attempt that the sandbox killed (exit 137), the documented command still running (not the evidence run)."""
    attempts = json.loads(path.read_text(encoding="utf-8"))["result"]["attempts"]
    return next(a for a in attempts if a.get("exit_code") == 137 and (a.get("time_machine_action") or {}).get("rule") != "resource_evidence")


def _killed(a: dict, command: str) -> SandboxRunResult:
    return SandboxRunResult(steps=(StepResult(command, 137, a["stdout_tail"], a["stderr_tail"], 30.0, 0.3),))


@pytest.mark.parametrize("path", [R17, *R11], ids=["dev17_v152", "gate11_v142", "gate11_v143"])
def test_the_recorded_kill_is_resource_limit(path):
    a = _kill(path)
    got = classifier.classify(137, a["stderr_tail"], a["stdout_tail"])
    assert got.code == classifier.TaxonomyCode.RESOURCE_LIMIT


def test_resource_adapt_reads_the_options_statically_and_refuses_a_shell_script(tmp_path):
    (tmp_path / "main.py").write_text(VOTE_MAIN, encoding="utf-8")
    command = json.loads(R11[1].read_text(encoding="utf-8"))["certificate"]["build_plan"]["execute_command"]
    entry, _ = resource_adapt.entry_of(command)
    assert resource_adapt.batch_options(tmp_path, entry) == {"--batch_size": 256, "--test_batch_size": 256}
    one, _ = resource_adapt.adapt(command, {"--batch_size": 256, "--test_batch_size": 256}, 1)
    two, _ = resource_adapt.adapt(command, {"--batch_size": 256, "--test_batch_size": 256}, 2)
    assert one.label() == "RESOURCE-ADAPTED: --batch_size 256->128, --test_batch_size 256->128"
    assert two.changes == (("--batch_size", 256, 64), ("--test_batch_size", 256, 64))
    assert resource_adapt.adapt(command, {"--batch_size": 256}, 3)[0] is None
    documented17 = json.loads(R17.read_text(encoding="utf-8"))["certificate"]["build_plan"]["execute_command"]
    assert documented17 == "sh ./fs_train.sh" and resource_adapt.entry_of(documented17)[0] is None
    on_line, _ = resource_adapt.adapt("python train.py --batch-size 100 --lr 0.1", {"--batch-size": None}, 1)
    assert on_line.command == "python train.py --batch-size 50 --lr 0.1"
    assert resource_adapt.adapt("python train.py --bs=8", {"--bs": None}, 1)[0].command == "python train.py --bs=4"


def _memory_pipeline(tmp_path, results, *, command, files):
    _git_repo(tmp_path, files)
    results, plans = list(results), []

    def runner(*, runner_extras=(), **kw):
        plans.append({**kw, "runner_extras": runner_extras})
        return results.pop(0)

    repair = _Chat()
    deps = PipelineDeps(recon_client=_Chat([{"entrypoint": "main.py", "confidence": 0.9}]), recon_model="r", repair_client=repair, repair_model="p",
                        adjudicator_client=None, adjudicator_model=None, sandbox_api_key="k", sandbox_wall_clock_seconds=100, sandbox_runner=runner,
                        tavily_client=None, smoke_seconds=0, max_attempts=3)
    intake = RepoIntake(tmp_path, "a" * 40, {}, frozenset(), (), ("main.py",), None)
    result = run_pipeline(repo_url="https://example.com/r", commit_sha="a" * 40, workdir=tmp_path, intake_result=intake, deps=deps,
                          cost_guard=CostGuard(daily_cost_ceiling_usd=100), run_id="v17-mem", documented_command=command)
    return result, repair, plans, results


def _rules(result) -> list[str]:
    return [(a.time_machine_action or {}).get("rule") for a in result.attempts if a.time_machine_action]


def test_replay_gate_11_hook_then_resource_adapt_and_the_verdict_says_resource_adapted(tmp_path):
    a = _kill(R11[1])
    command = "python main.py  --evaluate --dataset cifar10  --eps 0.031  --model capsnet  --attack vote_attack_FGSM"
    result, repair, plans, left = _memory_pipeline(tmp_path, [_killed(a, command), _killed(a, command), _ok()], command=command, files={"main.py": VOTE_MAIN})
    assert not left and not repair.calls
    assert _rules(result) == ["memory_hook", "resource_adapt"]
    assert runner_hooks.install_command(runner_hooks.MEMORY_HOOK) in plans[1]["runner_extras"]
    assert plans[1]["execute_command"].startswith("export MALLOC_ARENA_MAX=2 OMP_NUM_THREADS=4\n") and command in plans[1]["execute_command"]
    assert plans[2]["execute_command"].endswith("--batch_size 128 --test_batch_size 128")
    assert result.verdict == "RUNS_AFTER_REPAIR"
    record = {"verdict": result.verdict, "attempts": [x.as_dict() for x in result.attempts], "error_chain": []}
    assert outcome_levels.compute(record)["resource_adapted"] == "RESOURCE-ADAPTED: --batch_size 256->128, --test_batch_size 256->128"
    assert outcome_levels.verdict_label(record) == "RUNS_AFTER_REPAIR (RESOURCE-ADAPTED: --batch_size 256->128, --test_batch_size 256->128)"
    assert any("resource_adapt round 1" in n and "NOT semantics-preserving" in n for n in result.build_plan["notes"])


def test_replay_dev_17_hook_only_then_the_stop_with_no_adaptation_of_a_shell_script(tmp_path):
    a = _kill(R17)
    command = "sh ./fs_train.sh"
    evidence = SandboxRunResult(steps=(StepResult(command, 137, "", a["stderr_tail"] + "\nRERUN_EVIDENCE_BEGIN exit_status=137\n--meminfo\nMemTotal:        4034744 kB\nRERUN_EVIDENCE_END\n", 30.0, 0.3),))
    result, repair, plans, left = _memory_pipeline(tmp_path, [_killed(a, command), _killed(a, command), evidence], command=command,
                                                   files={"fs_train.sh": "python3 fs_main.py --batch_size_train=60\n", "main.py": ""})
    assert not repair.calls
    assert _rules(result)[:1] == ["memory_hook"] and "resource_adapt" not in _rules(result)
    assert result.verdict == "INDETERMINATE" and result.taxonomy_code == "RESOURCE_LIMIT"


def test_the_control_arm_and_a_runner_without_hooks_keep_the_old_stop(tmp_path):
    a = _kill(R11[1])
    command = "python main.py --evaluate"
    _git_repo(tmp_path, {"main.py": VOTE_MAIN})
    calls = []

    def runner(**kw):  # no declared runner_extras: hooks are not available
        calls.append(kw)
        return _killed(a, command)

    deps = PipelineDeps(recon_client=_Chat([{"entrypoint": "main.py", "confidence": 0.9}]), recon_model="r", repair_client=_Chat(), repair_model="p",
                        adjudicator_client=None, adjudicator_model=None, sandbox_api_key="k", sandbox_wall_clock_seconds=100, sandbox_runner=runner,
                        tavily_client=None, smoke_seconds=0, max_attempts=3)
    intake = RepoIntake(tmp_path, "a" * 40, {}, frozenset(), (), ("main.py",), None)
    result = run_pipeline(repo_url="https://example.com/r", commit_sha="a" * 40, workdir=tmp_path, intake_result=intake, deps=deps,
                          cost_guard=CostGuard(daily_cost_ceiling_usd=100), run_id="v17-mem-old", documented_command=command)
    assert result.verdict == "INDETERMINATE" and result.taxonomy_code == "RESOURCE_LIMIT"
    assert not {"memory_hook", "resource_adapt"} & set(_rules(result))  # only the old evidence run


def test_the_blocker_says_resource_adapted_when_the_adapted_run_still_failed():
    chain = [{"class": "RESOURCE_LIMIT", "error": "exit code 137: the process was killed by SIGKILL", "phase": "repo_run", "attribution": "SANDBOX_QUOTA"}]
    attempts = [{"time_machine_action": {"rule": "resource_adapt", "label": "RESOURCE-ADAPTED: --batch_size 256->64"}}]
    assert blocker.report({"verdict": "INDETERMINATE", "error_chain": chain, "attempts": attempts})["resource_adapted"] == "RESOURCE-ADAPTED: --batch_size 256->64"
    assert "resource_adapted" not in blocker.report({"verdict": "INDETERMINATE", "error_chain": chain, "attempts": []})


def test_the_hook_source_is_python_3_6_compatible_and_registered():
    source = runner_hooks.source_of(runner_hooks.MEMORY_HOOK)
    compile(source, "rerun_memory_hook.py", "exec")
    assert "f\"" not in source and "f'" not in source  # no f-strings (python:3.6-slim has them, but the other hooks avoid them too)
    assert runner_hooks.hook_of_command(runner_hooks.install_command(runner_hooks.MEMORY_HOOK)) == runner_hooks.MEMORY_HOOK
    assert runner_hooks.memory_hook_changes("RERUN memory_hook: DataLoader num_workers 2->0\nx\nRERUN memory_hook: DataLoader num_workers 2->0\n") == \
        ["DataLoader num_workers 2->0"]
    assert runner_env.with_memory_env("sh ./fs_train.sh") == "export MALLOC_ARENA_MAX=2 OMP_NUM_THREADS=4\nsh ./fs_train.sh"
