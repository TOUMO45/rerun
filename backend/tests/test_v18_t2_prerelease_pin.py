"""harness-v1.8 (T2): a torch-family pin to a pre-release the index never served is pinned to its final release at the runner's own setup step, as R5's companion rule
does for an incompatible pair: a recorded, labelled dependency change, no model call.

Evidence: TEST-B #2 vlievin/ovis (now DEV-CONTAMINATED), `runs/corpus_v3_batch/harness-v1.7.2/treatment/02_vlievin__ovis.json`: `torchvision==0.6.0a0` in the repository's
requirements; the runner's torch-family install failed before the baseline ran, the run ended INDETERMINATE RUNNER_SETUP_FAILED with no repair. The runner's command and the
evidence line are read from that record. Offline: scripted sandbox; the real classifier, runner_env and orchestrator run; the model client raises if called. On the
harness-v1.7.2 code `test_replay_ovis...` ends INDETERMINATE RUNNER_SETUP_FAILED."""

from __future__ import annotations

import json
import re
from pathlib import Path

from app.services import outcome_levels, prerelease_pin
from app.services.sandbox import SandboxRunResult, StepResult
from test_v151_pins_and_removals import _ok, _pipeline

ROOT = Path(__file__).resolve().parents[2]
OVIS = ROOT / "runs" / "corpus_v3_batch" / "harness-v1.7.2" / "treatment" / "02_vlievin__ovis.json"


def _recorded() -> tuple[str, str]:
    doc = json.loads(OVIS.read_text(encoding="utf-8"))
    step = next(s for s in doc["operations"][0]["install_seconds"] if s["phase"] == "runner_setup")
    assert step["exit_code"] == 1 and "torchvision==0.6.0a0" in step["command"]
    # the record caps its evidence line at 300 characters, which cuts pip's closing parenthesis; the run printed it, and pip's second line
    line = doc["result"]["error_chain"][0]["error"].rstrip(", ") + ")\nERROR: No matching distribution found for torchvision==0.6.0a0"
    return step["command"], line


def _setup_failure(command: str, evidence: str) -> SandboxRunResult:
    return SandboxRunResult(steps=(StepResult(command, 1, "", f"{evidence}\n", 1.0, 0.01, phase="runner_setup"),))


def _requirements_from(command: str) -> str:
    return "".join(f"{name}=={version}\n" for name, version in re.findall(r"\b(torch|torchvision)==([\w.]+)", command))


def test_relax_for_reads_the_pin_from_the_log_and_the_runners_own_specs():
    log = "ERROR: Could not find a version that satisfies the requirement torchvision==0.6.0a0 (from versions: 0.5.0, 0.6.0, 0.6.1)"
    relax = prerelease_pin.relax_for(log, ("torch==1.5.0", "torchvision==0.6.0a0", "torchaudio"))
    assert (relax.package, relax.pinned, relax.replacement) == ("torchvision", "0.6.0a0", "0.6.0") and relax.overrides() == {"torchvision": "0.6.0"}  # torch 1.5.0: its own release
    assert prerelease_pin.relax_for(log, ("torch==1.5.0", "torchvision==0.6.0", "torchaudio")) is None  # the runner's spec does not carry that pin
    assert prerelease_pin.relax_for(log.replace("torchvision", "foo"), ("foo==0.6.0a0",)) is None  # not a torch-family package: the runner did not install it
    final = "ERROR: Could not find a version that satisfies the requirement torchvision==0.6.0 (from versions: 0.5.0)"
    assert prerelease_pin.relax_for(final, ("torchvision==0.6.0",)) is None  # a final release that is missing is not a pre-release pin
    for suffix in ("rc1", "b2", ".dev3", "a0"):
        assert prerelease_pin.relax_for(f"ERROR: Could not find a version that satisfies the requirement torch==1.5.0{suffix} (from versions: 1.4.0)", (f"torch==1.5.0{suffix}",)).replacement == "1.5.0"


def test_replay_ovis_the_final_release_is_pinned_and_no_model_is_called(tmp_path):
    command, evidence = _recorded()
    result, repair, plans, left = _pipeline(tmp_path, [_setup_failure(command, evidence), _ok()], files={"train.py": "import torch, torchvision\n"},
                                            dependency_files={"requirements.txt": _requirements_from(command)})
    assert not left and not repair.calls
    assert result.verdict == "RUNS_AFTER_REPAIR" and result.taxonomy_code == "DEP_YANKED"
    step = result.attempts[0]
    assert step.origin == "time_machine" and step.time_machine_action["rule"] == "prerelease_pin_relax"
    # DEV re-run of ovis, 2026-10-07: the numeric final release (0.6.0) requires torch 1.5.0 and the repository pins torch 1.5.1: pip said ResolutionImpossible. The release made for
    # the pinned torch is used instead (0.6.1)
    assert (step.time_machine_action["package"], step.time_machine_action["from"], step.time_machine_action["to"]) == ("torchvision", "0.6.0a0", "0.6.1")
    assert step.time_machine_action["kept"] == "torch==1.5.1" and "release made for torch==1.5.1" in step.time_machine_action["reason"]
    assert "pre-release" in step.time_machine_action["reason"] and "DEP_YANKED" in step.time_machine_action["fires_on"]
    assert plans[0]["torch_setup"].specs[:2] == ("torch==1.5.1", "torchvision==0.6.0a0")  # the baseline ran as published
    assert plans[1]["torch_setup"].specs[:2] == ("torch==1.5.1", "torchvision==0.6.1")
    record = {"verdict": result.verdict, "error_chain": [link.as_dict() if hasattr(link, "as_dict") else link for link in result.error_chain],
              "attempts": [a.as_dict() for a in result.attempts]}
    levels = outcome_levels.compute(record)
    assert levels["dependency_change"] == "dependency change: torchvision 0.6.0a0->0.6.1"
    assert outcome_levels.verdict_label(record) == "RUNS_AFTER_REPAIR (dependency change: torchvision 0.6.0a0->0.6.1)"
    assert any("prerelease_pin_relax" in n and "DEPENDENCY CHANGE" in n for n in result.build_plan["notes"])


def test_a_pre_release_that_is_still_missing_after_the_step_ends_runner_setup_failed(tmp_path):
    command, evidence = _recorded()
    again = _setup_failure(command.replace("0.6.0a0", "0.6.0"), "ERROR: Could not find a version that satisfies the requirement torchvision==0.6.0 (from versions: 0.1.6)")
    result, repair, plans, left = _pipeline(tmp_path, [_setup_failure(command, evidence), again], files={"train.py": "import torch\n"},
                                            dependency_files={"requirements.txt": _requirements_from(command)})
    assert not left and not repair.calls
    assert result.verdict == "INDETERMINATE" and result.indeterminate_reason.startswith("RUNNER_SETUP_FAILED")
    assert sum(1 for a in result.attempts if (a.time_machine_action or {}).get("rule") == "prerelease_pin_relax") == 1  # once: no loop


def test_the_replacement_is_the_release_made_for_the_pinned_torch_not_the_numeric_one():
    """DEV re-run of ovis (2026-10-07): torch==1.5.1 with torchvision==0.6.0 is ResolutionImpossible (0.6.0 requires torch 1.5.0). The table is the one R5 already uses."""
    from app.services import torch_companions_data as data

    log = "ERROR: Could not find a version that satisfies the requirement torchvision==0.6.0a0 (from versions: 0.5.0, 0.6.0, 0.6.1)"
    relax = prerelease_pin.relax_for(log, ("torch==1.5.1", "torchvision==0.6.0a0"))
    assert relax.replacement == "0.6.1" and (relax.primary, relax.primary_version) == ("torch", "1.5.1")
    assert data.TORCHVISION_REQUIRES_TORCH["0.6.0"] == "1.5.0" != "1.5.1" and data.TORCHVISION_REQUIRES_TORCH[relax.replacement] == "1.5.1"  # why 0.6.0 was wrong
    assert prerelease_pin.relax_for(log, ("torch==1.5.1+cpu", "torchvision==0.6.0a0")).replacement == "0.6.1"  # the runner's local-version spelling
    assert prerelease_pin.relax_for(log, ("torch>=1.5", "torchvision==0.6.0a0")).replacement == "0.6.0"  # a range is not a pin: the numeric final release, as before
    assert prerelease_pin.relax_for(log, ("torch==9.9.9", "torchvision==0.6.0a0")).replacement == "0.6.0"  # a torch the table does not know: as before
    assert prerelease_pin.relax_for(log, ("torchvision==0.6.0a0",)).replacement == "0.6.0"  # no torch pin at all
    for torch_release, vision in data.TORCHVISION_FOR_TORCH.items():  # the invariant: whatever replaces the pre-release pairs with the torch pin
        got = prerelease_pin.relax_for(f"ERROR: Could not find a version that satisfies the requirement torchvision==9.9.9a0 (from versions: 0.1)", (f"torch=={torch_release}", "torchvision==9.9.9a0"))
        assert got.replacement == vision and data.TORCHVISION_REQUIRES_TORCH[got.replacement] == torch_release
