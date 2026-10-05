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
    # v1.7 review, H1: a dependency change is labelled on the ladder and the verdict, and noted in the build plan. harness-v1.7.1: with the Pillow pin beside it
    # (this requirements file does not name Pillow, so the label says not declared)
    assert levels["dependency_change"] == "dependency change: torchvision 0.5.0->0.4.0, Pillow not declared->6.2.2"
    assert outcome_levels.verdict_label(record) == "RUNS_AFTER_REPAIR (dependency change: torchvision 0.5.0->0.4.0, Pillow not declared->6.2.2)"
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


# --- harness-v1.7.1 (after check N4 of the harness-v1.7.0 seal failed) ----------------------------------------------------------------------------------
N4 = ROOT / "runs" / "sandbox_verification" / "v1.7-seal" / "v17" / "N4_companion_torch_1_2_0_torchvision_0_4_0.json"
# DEV #5's requirements.txt at its recorded commit 203e94a69c5f9cda049b9c3985b7c2b1e39ca922 (the lines that matter here, verbatim; the file has 67 lines). The
# record keeps only the file names (intake.dependency_files), so the lines are quoted here from the repository at that commit.
DEV5_REQUIREMENTS = "numpy==1.17.2\nPillow==9.0.0\nrequests==2.22.0\nsix==1.12.0\ntorch==1.2.0\ntorchvision==0.5.0\nurllib3==1.26.5\n"


def test_the_n4_record_is_the_pillow_version_import_error_and_the_swap_now_pins_pillow_6_2_2_beside_torchvision_0_4_0():
    n4 = json.loads(N4.read_text(encoding="utf-8"))
    assert n4["ok"] is False and "cannot import name 'PILLOW_VERSION' from 'PIL'" in n4["stderr_tail"]
    swap = runner_env.companion_swap(("torch==1.2.0", "torchvision==0.5.0", "torchaudio"))
    assert swap.also == (("Pillow", "6.2.2"),) and swap.overrides() == {"torchvision": "0.4.0", "Pillow": "6.2.2"}
    assert "PILLOW_VERSION" in swap.as_dict()["reason"] and swap.as_dict()["also"] == [{"package": "Pillow", "to": "6.2.2"}]
    setup = runner_env.plan_torch_setup(["torch==1.2.0\ntorchvision==0.5.0\n"], None, overrides=swap.overrides())
    assert setup.specs == ("torch==1.2.0", "torchvision==0.4.0", "torchaudio", "Pillow==6.2.2")
    assert "Pillow==6.2.2" in setup.install_command and "Pillow" in setup.needed  # in the fallback install too
    # only the release R5 swaps to on DEV #5 is listed (rule G): another replacement brings nothing beside it
    other = runner_env.companion_swap(("torch==1.4.0", "torchvision==0.6.0"))
    assert other is not None and other.replacement == "0.5.0" and other.also == () and other.overrides() == {"torchvision": "0.5.0"}


def test_replay_entry_5_with_its_own_requirements_the_install_copy_carries_both_pins_and_the_label_names_both(tmp_path):
    """The repository's `pip install -r requirements.txt` runs after the runner's torch step: with the file as published it would put torchvision==0.5.0 and
    Pillow==9.0.0 back. The swap's pins go into RERUN's copy (.rerun-requirements.txt); every other line is the repository's own."""
    command, evidence = _recorded()
    result, repair, plans, left = _pipeline(tmp_path, [_setup_failure(command, evidence), _ok()], files={"train.py": "import torch, torchvision\n"},
                                            dependency_files={"requirements.txt": DEV5_REQUIREMENTS})
    assert not left and not repair.calls and result.verdict == "RUNS_AFTER_REPAIR"
    assert not any(".rerun-requirements" in c for c in plans[0]["install_commands"])  # the baseline ran as published
    copy = next(c for c in plans[1]["install_commands"] if ".rerun-requirements" in c)
    assert "torchvision==0.4.0" in copy and "Pillow==6.2.2" in copy and "torchvision==0.5.0" not in copy and "Pillow==9.0.0" not in copy
    for kept in ("numpy==1.17.2", "requests==2.22.0", "six==1.12.0", "torch==1.2.0", "urllib3==1.26.5"):
        assert kept in copy
    assert plans[1]["torch_setup"].specs == ("torch==1.2.0", "torchvision==0.4.0", "torchaudio", "Pillow==6.2.2")
    act = result.attempts[0].time_machine_action
    assert act["requirements_pins"] == [{"package": "torchvision", "from": "torchvision==0.5.0", "to": "0.4.0"},
                                        {"package": "Pillow", "from": "Pillow==9.0.0", "to": "6.2.2"}]
    record = {"verdict": result.verdict, "attempts": [a.as_dict() for a in result.attempts], "error_chain": []}
    assert outcome_levels.verdict_label(record) == "RUNS_AFTER_REPAIR (dependency change: torchvision 0.5.0->0.4.0, Pillow 9.0.0->6.2.2)"


def test_a_later_requirements_edit_starts_from_the_copy_with_the_swaps_pins_not_from_the_repositorys_file(tmp_path):
    """v1.7.1 review (MEDIUM): after the swap the run fails again in the repository's command; the next deterministic step (the removed-API rule, which
    edits the requirements copy) must start from RERUN's copy, so torchvision==0.4.0 and Pillow==6.2.2 stay in it and the published 0.5.0 / 9.0.0 never return."""
    from test_v151_pins_and_removals import _fail

    command, evidence = _recorded()
    removed = _fail("ImportError: cannot import name 'zero_gradients' from 'torch.autograd.gradcheck' (/x/gradcheck.py)\n")
    result, repair, plans, left = _pipeline(tmp_path, [_setup_failure(command, evidence), removed, _ok()],
                                            files={"train.py": "import torch, torchvision\n"}, dependency_files={"requirements.txt": DEV5_REQUIREMENTS})
    assert not left and not repair.calls and len(plans) == 3
    later = next(c for c in plans[2]["install_commands"] if ".rerun-requirements" in c)
    assert "torchvision==0.4.0" in later and "Pillow==6.2.2" in later and "torchvision==0.5.0" not in later and "Pillow==9.0.0" not in later


def test_the_label_names_each_requirement_shape_plainly():
    """v1.7.1 review (LOW): the `from` of a pin beside the swap is the repository's line; the label shows its version, its range, `unpinned` for a bare name and
    `not declared` when the file does not name the package."""
    def label(frm):
        also = {"package": "Pillow", "to": "6.2.2", **({"from": frm} if frm is not None else {})}
        rec = {"attempts": [{"time_machine_action": {"rule": "companion_relax", "package": "torchvision", "from": "0.5.0", "to": "0.4.0", "also": [also]}}]}
        return outcome_levels.dependency_change(rec)
    assert label("Pillow==9.0.0") == "dependency change: torchvision 0.5.0->0.4.0, Pillow 9.0.0->6.2.2"
    assert label("Pillow>=7.0") == "dependency change: torchvision 0.5.0->0.4.0, Pillow >=7.0->6.2.2"
    assert label("Pillow") == "dependency change: torchvision 0.5.0->0.4.0, Pillow unpinned->6.2.2"
    assert label(None) == "dependency change: torchvision 0.5.0->0.4.0, Pillow not declared->6.2.2"
    old = {"attempts": [{"time_machine_action": {"rule": "companion_relax", "package": "torchvision", "from": "0.5.0", "to": "0.4.0"}}]}
    assert outcome_levels.dependency_change(old) == "dependency change: torchvision 0.5.0->0.4.0"  # a v1.7.0-shaped action renders as before


def test_the_seals_n4_construction_runs_the_torch_step_then_the_requirements_copy_in_the_order_a_run_uses():
    """v1.7.1 review: the seal's N4 builds its operation with the run's own code (orchestrator._companion_requirements, runner_env.plan_torch_setup); the setup
    order the sandbox runs (sandbox.setup_commands) puts the torch step, with Pillow==6.2.2 in it, before `pip install -r` of the copy."""
    from app.services import orchestrator, planner, sandbox

    swap = runner_env.companion_swap(("torch==1.2.0", "torchvision==0.5.0", "torchaudio"))
    reqs = "numpy==1.17.2\nPillow==9.0.0\nsix==1.12.0\ntorch==1.2.0\ntorchvision==0.5.0\n"
    plan, copy, pins = orchestrator._companion_requirements(planner.BuildPlan("python:3.7-slim", (), ("pip install -r requirements.txt",), "true"), swap, reqs, "e")
    setup = runner_env.plan_torch_setup([reqs], None, overrides=swap.overrides())
    steps = sandbox.setup_commands(plan.install_commands, setup)
    torch_at = next(i for i, s in enumerate(steps) if "torchvision==0.4.0" in s and "Pillow==6.2.2" in s and "download.pytorch.org" in s)
    copy_at = next(i for i, s in enumerate(steps) if ".rerun-requirements" in s)
    assert torch_at < copy_at and "torchvision==0.4.0" in steps[copy_at] and "Pillow==6.2.2" in steps[copy_at] and "numpy==1.17.2" in steps[copy_at]
    assert [p["package"] for p in pins] == ["torchvision", "Pillow"] and copy.splitlines()[1] == "Pillow==6.2.2"
    assert orchestrator._companion_requirements(plan, swap, None, "e") == (plan, None, [])  # no requirements.txt: nothing to copy, the torch step pins it
    assert orchestrator._companion_requirements(plan, swap, "scipy==1.3\n", "e")[1:] == (None, [])  # a file naming neither package is left as it is
