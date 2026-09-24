"""Step 3 (2026-09-24): the repairer sees the repo's full AST import list and
the resolved lock, so ONE attempt can fix every missing module.

Fixture: a repo importing numpy, scipy and yaml (pyyaml) with an empty
requirements.txt. The sandbox only completes once all three are installed.
The era lock is made unavailable so the model repair path is what's tested."""

from __future__ import annotations

import json

from app.services.cost_guard import CostGuard
from app.services.intake import RepoIntake
from app.services.orchestrator import PipelineDeps, run_pipeline
from app.services.sandbox import SandboxRunResult, StepResult
from app.services.time_machine import LockResult

MISSING = ("numpy", "scipy", "pyyaml")
FIRST_ERROR = "ModuleNotFoundError: No module named 'numpy'"


class _Chat:
    def __init__(self, responses):
        self._responses = list(responses)
        self.prompts = []

    def chat_completion(self, **kwargs):
        self.prompts.append(kwargs)
        return self._responses.pop(0)


class _Sandbox:
    def __init__(self):
        self.calls = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        installed = " ".join(kwargs["install_commands"])
        for pkg, module in (("numpy", "numpy"), ("scipy", "scipy"), ("pyyaml", "yaml")):
            if pkg not in installed:
                return SandboxRunResult(steps=(StepResult("python train.py", 1, "", f"ModuleNotFoundError: No module named '{module}'", 1.0, 0.0),))
        return SandboxRunResult(steps=(StepResult("python train.py", 0, "ok", "", 1.0, 0.0),))


def _add(pkg, evidence):
    return {"op": "add", "package": pkg, "version": None, "justification": f"{pkg} is imported but not declared", "evidence": evidence}


def _run(tmp_path, responses, max_attempts):
    (tmp_path / "requirements.txt").write_text("\n", encoding="utf-8")
    (tmp_path / "train.py").write_text("import numpy\nimport scipy.stats\nimport yaml\nimport os\nimport helpers\n", encoding="utf-8")
    (tmp_path / "helpers.py").write_text("X = 1\n", encoding="utf-8")
    intake = RepoIntake(tmp_path, "a" * 40, {"requirements.txt": "\n"}, frozenset(), (), ("train.py",), None)
    repair = _Chat([json.dumps(r) for r in responses])
    sandbox = _Sandbox()
    deps = PipelineDeps(
        recon_client=_Chat([json.dumps({"entrypoint": "train.py", "confidence": 0.9})]),
        recon_model="r",
        repair_client=repair,
        repair_model="p",
        adjudicator_client=None,
        adjudicator_model=None,
        sandbox_api_key="k",
        sandbox_wall_clock_seconds=60,
        sandbox_runner=sandbox,
        max_attempts=max_attempts,
        lock_compiler=lambda *a: LockResult(False, (), (), (), "", "lock disabled for this test"),
    )
    result = run_pipeline(repo_url="https://example.com/r", commit_sha="a" * 40, workdir=tmp_path, intake_result=intake,
                          deps=deps, cost_guard=CostGuard(daily_cost_ceiling_usd=100), run_id="smart")
    return result, repair, sandbox


def test_one_attempt_fixes_all_three_missing_modules(tmp_path):
    all_three = {"code_diff": None, "env_delta": [_add(p, FIRST_ERROR) for p in MISSING], "explanation": "add every missing import"}
    result, repair, sandbox = _run(tmp_path, [all_three], max_attempts=1)

    assert result.verdict == "RUNS_AFTER_REPAIR", result.full_log
    model_attempts = [a for a in result.attempts if a.origin == "model"]
    assert len(model_attempts) == 1
    assert len(sandbox.calls) == 2  # baseline + one re-execution

    prompt = repair.prompts[0]["user_prompt"]
    # The full import list reached the model — not just the one module in the error.
    import_block = prompt.split("Top-level modules imported anywhere in the repository's code:")[1]
    for module in ("numpy", "scipy", "yaml"):
        assert module in import_block
    assert "fix ALL missing" in repair.prompts[0]["system_prompt"]


def test_negative_control_fixing_one_module_per_attempt_runs_out_of_attempts(tmp_path):
    one_at_a_time = [
        {"code_diff": None, "env_delta": [_add("numpy", FIRST_ERROR)], "explanation": "numpy"},
        {"code_diff": None, "env_delta": [_add("scipy", "No module named 'scipy'")], "explanation": "scipy"},
    ]
    result, _, _ = _run(tmp_path, one_at_a_time, max_attempts=2)
    assert result.verdict == "BLOCKED"
    assert "No module named 'yaml'" in result.full_log


def test_resolved_lock_is_shown_to_the_repairer(tmp_path):
    """After the time machine installs a lock, the repairer sees exactly what is installed."""
    from app.services import repairer
    from app.services.classifier import classify

    prompt = repairer.build_repair_user_prompt(
        classify(exit_code=1, stderr=FIRST_ERROR), "train.py", "import numpy\n",
        imported_modules=["numpy", "scipy"], resolved_lock=["numpy==1.16.2", "scipy==1.2.1"],
    )
    lock_block = prompt.split("resolved lock for the repository's era")[1]
    assert "numpy==1.16.2" in lock_block and "scipy==1.2.1" in lock_block
