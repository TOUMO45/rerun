"""Step 4 (2026-09-24): corpus entries carry the repository's documented
command; it is ground truth, and a repair may only change it through the
gated `command` env op, where the scale-reduction rule applies."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.batch.corpus import CorpusError, load_corpus
from app.services.cost_guard import CostGuard
from app.services.env_repair import EnvChange, EnvRule, apply_env_delta, check_command_change, check_env_delta
from app.services.intake import RepoIntake
from app.services.orchestrator import PipelineDeps, run_pipeline
from app.services.planner import BuildPlan, build_plan
from app.services.recon import ReconResult
from app.services.sandbox import SandboxRunResult, StepResult

DOC = "python3 download_model.py 124M && python3 src/generate_unconditional_samples.py --nsamples 1 --top_k 40"


# --- corpus -----------------------------------------------------------------


def _corpus(tmp_path: Path, extra: str) -> Path:
    path = tmp_path / "corpus.yaml"
    path.write_text(
        "repos:\n  - name: r\n    repo_url: https://github.com/o/r\n    commit_sha: " + "a" * 40
        + "\n    entrypoint_hint: x\n    selection_note: y\n" + extra,
        encoding="utf-8",
    )
    return path


def test_corpus_command_and_its_source_load(tmp_path):
    (entry,) = load_corpus(_corpus(tmp_path, f"    command: '{DOC}'\n    command_source: DEVELOPERS.md\n"))
    assert entry.command == DOC and entry.command_source == "DEVELOPERS.md"


def test_corpus_entry_without_command_still_loads(tmp_path):
    (entry,) = load_corpus(_corpus(tmp_path, ""))
    assert entry.command is None


@pytest.mark.parametrize("extra", ["    command: 'python x.py'\n", "    command: ''\n    command_source: README\n"])
def test_corpus_command_needs_a_source_and_content(tmp_path, extra):
    with pytest.raises(CorpusError):
        load_corpus(_corpus(tmp_path, extra))


# --- planner / orchestrator ------------------------------------------------------


def _intake(path=Path("unused")):
    return RepoIntake(path, "a" * 40, {"requirements.txt": "numpy\n"}, frozenset({"numpy"}), (), ("src/gen.py",), None)


def test_documented_command_is_the_execute_command_verbatim():
    plan = build_plan(_intake(), ReconResult(is_indeterminate=False, entrypoint="src/gen.py"), documented_command=DOC)
    assert plan.execute_command == DOC
    assert any("documented command" in n for n in plan.notes)


def test_without_a_documented_command_recon_entrypoint_is_used():
    plan = build_plan(_intake(), ReconResult(is_indeterminate=False, entrypoint="src/gen.py"))
    assert plan.execute_command == "python src/gen.py"


class _Chat:
    def __init__(self, responses):
        self._responses = list(responses)

    def chat_completion(self, **kwargs):
        return self._responses.pop(0)


def _run(tmp_path, documented_command, repair=(), results=None):
    (tmp_path / "src").mkdir(exist_ok=True)
    (tmp_path / "src" / "gen.py").write_text("print('x')\n", encoding="utf-8")
    calls = []
    scripted = list(results or [SandboxRunResult(steps=(StepResult("run", 0, "ok", "", 1.0, 0.0),))])

    def sandbox(**kwargs):
        calls.append(kwargs)
        return scripted.pop(0)

    deps = PipelineDeps(
        recon_client=_Chat([json.dumps({"entrypoint": None, "confidence": 0.1})]),  # recon abstains
        recon_model="r",
        repair_client=_Chat([json.dumps(r) for r in repair]),
        repair_model="p",
        adjudicator_client=None,
        adjudicator_model=None,
        sandbox_api_key="k",
        sandbox_wall_clock_seconds=60,
        sandbox_runner=sandbox,
        max_attempts=max(1, len(repair)),
    )
    result = run_pipeline(repo_url="https://example.com/r", commit_sha="a" * 40, workdir=tmp_path, intake_result=_intake(tmp_path),
                          deps=deps, cost_guard=CostGuard(daily_cost_ceiling_usd=100), run_id="cmd", documented_command=documented_command)
    return result, calls


def test_documented_command_runs_even_when_recon_cannot_pick_an_entrypoint(tmp_path):
    result, calls = _run(tmp_path, DOC)
    assert result.verdict == "RUNS_CLEAN"
    assert calls[0]["execute_command"] == DOC
    assert "proceeding with the documented command" in result.full_log
    assert result.baseline["execute_command"] == DOC


def test_negative_control_no_documented_command_recon_abstains(tmp_path):
    result, calls = _run(tmp_path, None)
    assert result.verdict == "INDETERMINATE" and calls == []


# --- command-change rules ------------------------------------------------------------


@pytest.mark.parametrize(
    "new",
    [
        DOC.replace("--top_k 40", "--top_k 40 --temperature 0.7"),  # adds a non-scale flag
        DOC.replace("--top_k 40", "--top_k 20"),  # changes a non-scale flag
        DOC.replace("--nsamples 1", "--nsamples 4"),  # increases scale
        DOC.replace("--nsamples 1", "--nsamples=1"),  # same value, other spelling
    ],
)
def test_allowed_command_changes(new):
    assert check_command_change(DOC, new) == []


@pytest.mark.parametrize(
    "new,rule",
    [
        ("python train.py --epochs 1", EnvRule.REDUCED_SCALE),
        ("python train.py", EnvRule.REDUCED_SCALE),  # removes --epochs
        ("python train.py --epochs 50 --max_steps 10", EnvRule.REDUCED_SCALE),  # adds a scale flag
        ("python train.py --epochs=25", EnvRule.REDUCED_SCALE),
        ("python eval.py --epochs 50", EnvRule.ENV_COMMAND_PROGRAM_CHANGED),
        ("python -c 'print(1)' --epochs 50", EnvRule.ENV_COMMAND_PROGRAM_CHANGED),
        ("python train.py --epochs 50; rm -rf /", EnvRule.ENV_COMMAND_UNSAFE),
        ("python train.py --epochs 50 | tee log", EnvRule.ENV_COMMAND_UNSAFE),
        ("python train.py --epochs 50 > /dev/null", EnvRule.ENV_COMMAND_UNSAFE),
        ("python train.py --epochs $(echo 50)", EnvRule.ENV_COMMAND_UNSAFE),
        ("pip install x && python train.py --epochs 50", EnvRule.ENV_COMMAND_PROGRAM_CHANGED),
    ],
)
def test_rejected_command_changes(new, rule):
    rules = {r for r, _ in check_command_change("python train.py --epochs 50", new)}
    assert rule in rules


def test_positional_arguments_are_ground_truth():
    rules = {r for r, _ in check_command_change(DOC, DOC.replace("124M", "1558M"))}
    assert EnvRule.ENV_COMMAND_PROGRAM_CHANGED in rules


LOG = "Traceback (most recent call last):\nTypeError: sample_model() got an unexpected keyword argument\n"


def _cmd_change(new, evidence="TypeError: sample_model() got an unexpected keyword argument"):
    return EnvChange(op="command", command=new, justification="documented flag", evidence=evidence)


def test_command_op_goes_through_the_env_gate():
    ok = check_env_delta((_cmd_change(DOC.replace("--top_k 40", "--top_k 20")),), log_text=LOG, imported_modules=frozenset(),
                         has_requirements_txt=True, current_command=DOC)
    assert ok == ()
    bad = check_env_delta((_cmd_change(DOC.replace("--nsamples 1", "--nsamples 0")),), log_text=LOG, imported_modules=frozenset(),
                          has_requirements_txt=True, current_command=DOC)
    assert EnvRule.REDUCED_SCALE in {v.rule for v in bad}
    unjustified = check_env_delta((_cmd_change(DOC, evidence="not in the log at all"),), log_text=LOG, imported_modules=frozenset(),
                                  has_requirements_txt=True, current_command=DOC)
    assert EnvRule.ENV_UNJUSTIFIED in {v.rule for v in unjustified}


def test_apply_env_delta_sets_the_execute_command():
    plan = BuildPlan("python:3.7-slim", (), ("pip install -r requirements.txt",), DOC)
    new_cmd = DOC.replace("--top_k 40", "--top_k 20")
    new_plan, _ = apply_env_delta(plan, (_cmd_change(new_cmd),), "numpy\n")
    assert new_plan.execute_command == new_cmd
    assert new_plan.install_commands == plan.install_commands


def test_scale_reducing_command_repair_is_rejected_end_to_end(tmp_path):
    fail = SandboxRunResult(steps=(StepResult("run", 1, "", LOG, 1.0, 0.0),))
    reduce = {"code_diff": None, "env_delta": [{"op": "command", "command": DOC.replace("--nsamples 1", "--nsamples 0"),
              "justification": "fewer samples", "evidence": "TypeError: sample_model() got an unexpected keyword argument"}],
              "explanation": "x"}
    result, calls = _run(tmp_path, DOC, repair=[reduce], results=[fail])
    attempt = [a for a in result.attempts if a.origin == "model"][0]
    assert attempt.gate_decision == "REJECT"
    assert EnvRule.REDUCED_SCALE in {v["rule"] for v in attempt.gate_violations}
    assert len(calls) == 1  # never re-executed
