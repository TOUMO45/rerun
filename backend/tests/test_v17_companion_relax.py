"""harness-v1.7, R5 (METHODOLOGY "harness-v1.7 — PRE-REGISTRATION"): companion_relax. Failure class: DEP_UNPINNED_CONFLICT where the repository pins a framework and its
companion exactly, to releases that cannot be installed together.

Recorded: DEV #5 (BorgwardtLab/topological-autoencoders), round 4 (runs/corpus_v2_batch/harness-v1.6.0/dev/05_*.json) and every earlier record: the runner's torch-family
install `pip install torch==1.2.0 torchvision==0.5.0 torchaudio 'numpy<2' ...` ends `ERROR: ResolutionImpossible` in phase runner_setup, so the entry ends INDETERMINATE
RUNNER_SETUP_FAILED before the repository's first command. torchvision 0.5.0 requires torch 1.4.0 (PyPI metadata). **Single-case** (#5 only).

Offline: fake model and sandbox; the real classifier, runner_env and orchestrator run; the model client raises if it is called."""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

from app.services import outcome_levels, runner_env, torch_companions_data
from app.services.sandbox import SandboxRunResult, StepResult
from test_v151_pins_and_removals import _ok, _pipeline

ROOT = Path(__file__).resolve().parents[2]
R4 = ROOT / "runs" / "corpus_v2_batch" / "harness-v1.6.0" / "dev" / "05_BorgwardtLab__topological-autoencoders.json"
SNAPSHOT = ROOT / "scripts" / "data" / "torchvision_requires_dist_2026-10-04.json"


def _recorded() -> tuple[str, str]:
    """(the runner's torch install command, the recorded evidence line), both read from the round-4 record."""
    doc = json.loads(R4.read_text(encoding="utf-8"))
    step = next(s for s in doc["operations"][0]["install_seconds"] if s["phase"] == "runner_setup")
    assert step["exit_code"] == 1
    return step["command"], doc["result"]["error_chain"][0]["error"]


def _setup_failure(command: str, evidence: str) -> SandboxRunResult:
    return SandboxRunResult(steps=(StepResult(command, 1, "", f"{evidence}\n", 1.0, 0.01, phase="runner_setup"),))


def _requirements_from(command: str) -> str:
    return "".join(f"{name}=={version}\n" for name, version in re.findall(r"\b(torch|torchvision)==([\d.]+)", command))


def test_the_table_is_generated_from_the_committed_snapshot_and_pairs_torch_1_2_0_with_torchvision_0_4_0():
    import importlib.util
    spec = importlib.util.spec_from_file_location("bt", ROOT / "scripts" / "build_torch_wheel_table.py")
    bt = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bt)
    generated = bt.render_companions(json.loads(SNAPSHOT.read_text(encoding="utf-8")))
    assert generated == (ROOT / "backend" / "app" / "services" / "torch_companions_data.py").read_text(encoding="utf-8").replace("\r\n", "\n")
    assert torch_companions_data.TORCHVISION_REQUIRES_TORCH["0.5.0"] == "1.4.0"
    assert torch_companions_data.TORCHVISION_FOR_TORCH["1.2.0"] == "0.4.0"
    ast.parse(generated)


def test_the_recorded_pins_are_a_known_incompatible_pair_and_the_swap_keeps_torch():
    command, evidence = _recorded()
    assert "ResolutionImpossible" in evidence and "torch==1.2.0" in command and "torchvision==0.5.0" in command
    swap = runner_env.companion_swap(("torch==1.2.0", "torchvision==0.5.0", "torchaudio"))
    assert (swap.package, swap.pinned, swap.replacement, swap.primary_version, swap.pinned_requires) == ("torchvision", "0.5.0", "0.4.0", "1.2.0", "1.4.0")
    assert runner_env.companion_swap(("torch==1.4.0", "torchvision==0.5.0")) is None  # the pins agree
    assert runner_env.companion_swap(("torch>=1.2", "torchvision==0.5.0")) is None  # a range is the resolver's to settle
    assert runner_env.companion_swap(("torch==1.2.0", "torchvision")) is None


def test_replay_entry_5_the_step_installs_torch_1_2_0_with_torchvision_0_4_0_and_no_model_is_called(tmp_path):
    command, evidence = _recorded()
    result, repair, plans, left = _pipeline(tmp_path, [_setup_failure(command, evidence), _ok()], files={"train.py": "import torch, torchvision\n"},
                                            dependency_files={"requirements.txt": _requirements_from(command)})
    assert not left and not repair.calls
    assert result.verdict == "RUNS_AFTER_REPAIR" and result.taxonomy_code == "DEP_UNPINNED_CONFLICT"
    step = result.attempts[0]
    assert step.origin == "time_machine" and step.time_machine_action["rule"] == "companion_relax"
    assert (step.time_machine_action["from"], step.time_machine_action["to"], step.time_machine_action["kept"]) == ("0.5.0", "0.4.0", "torch==1.2.0")
    assert "torchvision 0.5.0 requires torch==1.4.0" in step.time_machine_action["reason"]
    assert plans[0]["torch_setup"].specs[:2] == ("torch==1.2.0", "torchvision==0.5.0")  # the baseline ran as published
    assert plans[1]["torch_setup"].specs[:2] == ("torch==1.2.0", "torchvision==0.4.0")
    record = {"verdict": result.verdict, "error_chain": [link.as_dict() if hasattr(link, "as_dict") else link for link in result.error_chain],
              "attempts": [a.as_dict() for a in result.attempts]}
    levels = outcome_levels.compute(record)
    assert levels["first_error_cleared"] and levels["first_error_cleared_by"] == "time_machine"
    # v1.7 review, H1: a dependency change is labelled on the ladder and the verdict, and noted in the build plan
    assert levels["dependency_change"] == "dependency change: torchvision 0.5.0->0.4.0"
    assert outcome_levels.verdict_label(record) == "RUNS_AFTER_REPAIR (dependency change: torchvision 0.5.0->0.4.0)"
    assert any("companion_relax" in n and "DEPENDENCY CHANGE" in n for n in result.build_plan["notes"])


def test_a_conflict_without_pips_resolution_impossible_text_is_not_relaxed(tmp_path):
    """v1.7 review, L6: the rule needs pip's own ResolutionImpossible, not any DEP_UNPINNED_CONFLICT pattern."""
    command, _ = _recorded()
    other = "ERROR: Cannot install torch==1.2.0 and torchvision==0.5.0 because these package versions have conflicting dependencies."
    result, repair, plans, left = _pipeline(tmp_path, [_setup_failure(command, other)], files={"train.py": "import torch\n"},
                                            dependency_files={"requirements.txt": _requirements_from(command)})
    assert len(plans) == 1 and result.indeterminate_reason.startswith("RUNNER_SETUP_FAILED")


def test_a_conflict_the_table_does_not_explain_still_ends_runner_setup_failed_with_no_step(tmp_path):
    command = "pip install torch==1.4.0 torchvision==0.5.0 torchaudio --index-url https://download.pytorch.org/whl/cpu"
    result, repair, plans, left = _pipeline(tmp_path, [_setup_failure(command, "ERROR: ResolutionImpossible: for help visit https://pip.pypa.io")],
                                            files={"train.py": "import torch\n"}, dependency_files={"requirements.txt": "torch==1.4.0\ntorchvision==0.5.0\nnumpy==0.1\n"})
    assert not left and not repair.calls and len(plans) == 1
    assert result.verdict == "INDETERMINATE" and result.indeterminate_reason.startswith("RUNNER_SETUP_FAILED")
    assert not any((a.time_machine_action or {}).get("rule") == "companion_relax" for a in result.attempts)


def test_a_step_that_fails_again_in_setup_ends_runner_setup_failed_with_both_failures_in_the_chain(tmp_path):
    command, evidence = _recorded()
    again = _setup_failure(command.replace("0.5.0", "0.4.0"), "ERROR: Could not find a version that satisfies the requirement torchvision==0.4.0 (from versions: 0.1.6)")
    result, repair, plans, left = _pipeline(tmp_path, [_setup_failure(command, evidence), again], files={"train.py": "import torch\n"},
                                            dependency_files={"requirements.txt": _requirements_from(command)})
    assert not left and not repair.calls
    assert result.verdict == "INDETERMINATE" and result.indeterminate_reason.startswith("RUNNER_SETUP_FAILED")
    classes = [link.as_dict()["class"] if hasattr(link, "as_dict") else link["class"] for link in result.error_chain]
    assert classes[0] == "DEP_UNPINNED_CONFLICT" and len(classes) == 2


def test_the_control_arm_never_relaxes(tmp_path):
    command, evidence = _recorded()
    from test_v151_pins_and_removals import _git_repo, _Chat  # noqa: F401
    from app.services.cost_guard import CostGuard
    from app.services.intake import RepoIntake
    from app.services.orchestrator import PipelineDeps, run_pipeline

    _git_repo(tmp_path, {"train.py": "import torch\n"})
    calls = []

    def runner(**kw):
        calls.append(kw)
        return _setup_failure(command, evidence)

    deps = PipelineDeps(recon_client=_Chat([{"entrypoint": "train.py", "confidence": 0.9}]), recon_model="r", repair_client=_Chat(), repair_model="p",
                        adjudicator_client=None, adjudicator_model=None, sandbox_api_key="k", sandbox_wall_clock_seconds=100, sandbox_runner=runner,
                        tavily_client=None, smoke_seconds=0, max_attempts=3, repair_enabled=False)
    intake = RepoIntake(tmp_path, "a" * 40, {"requirements.txt": _requirements_from(command)}, frozenset(), (), ("train.py",), None)
    result = run_pipeline(repo_url="https://example.com/r", commit_sha="a" * 40, workdir=tmp_path, intake_result=intake, deps=deps,
                          cost_guard=CostGuard(daily_cost_ceiling_usd=100), run_id="v17-control")
    assert len(calls) == 1 and result.verdict == "INDETERMINATE" and result.indeterminate_reason.startswith("RUNNER_SETUP_FAILED")
