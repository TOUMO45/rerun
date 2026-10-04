"""harness-v1.7, R4 (METHODOLOGY "harness-v1.7 — PRE-REGISTRATION"): apt_archive. Failure class: APT_MIRROR_GONE, the base image's Debian release has left the mirrors.

Recorded: DEV #16 round 4 (runs/corpus_v2_batch/harness-v1.6.0/dev/16_*.json; python:3.6-slim, bullseye; `E: Failed to fetch http://security.debian.org/debian-security/pool/
updates/main/p/perl/perl-base_5.32.1-4%2bdeb11u5_amd64.deb  404  Not Found`) and DEV #9 round 3 (runs/corpus_v2_batch/harness-v1.5.2/dev/09_*.json; python:3.7-slim, the same
bullseye-security 404 lines). Class-level: two DEV entries.

Offline: the step's shell text runs under /bin/sh against a temporary root (the paths are rewritten for the test only); fake model and sandbox for the pipeline; the
real classifier and orchestrator run."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from app.services import classifier, runner_env
from app.services.sandbox import SandboxRunResult, StepResult
from test_v151_pins_and_removals import _ok

ROOT = Path(__file__).resolve().parents[2]
R16 = ROOT / "runs" / "corpus_v2_batch" / "harness-v1.6.0" / "dev" / "16_bckim92__sequential-knowledge-transformer.json"
R9 = ROOT / "runs" / "corpus_v2_batch" / "harness-v1.5.2" / "dev" / "09_omarfoq__fedem.json"


def _recorded_attempt(path: Path) -> dict:
    """The recorded attempt whose stored output holds the bullseye-security 404 (stderr and stdout tails as stored, never retyped)."""
    attempts = json.loads(path.read_text(encoding="utf-8"))["result"]["attempts"]
    return next(a for a in attempts if "debian-security" in (a.get("stderr_tail") or "") + (a.get("stdout_tail") or "") and a.get("exit_code") == 100)


@pytest.mark.parametrize("path", [R16, R9], ids=["dev16_round4", "dev9_round3"])
def test_the_recorded_404_is_apt_mirror_gone_and_the_step_is_built_for_bullseye(path):
    a = _recorded_attempt(path)
    got = classifier.classify(a["exit_code"], a["stderr_tail"], a["stdout_tail"])
    assert got.code == classifier.TaxonomyCode.APT_MIRROR_GONE and "security.debian.org/debian-security" in got.evidence
    step = runner_env.apt_archive_step()
    assert "bullseye)" in step and "archive.debian.org/debian bullseye main" in step and "Check-Valid-Until" in step


def test_only_apt_commands_get_the_step():
    assert runner_env.with_apt_archive("pip install -r requirements.txt") == "pip install -r requirements.txt"
    wrapped = runner_env.with_apt_archive("apt-get update && apt-get install -y build-essential")
    assert wrapped.startswith(runner_env.apt_archive_step()) and wrapped.endswith("apt-get install -y build-essential")
    assert runner_env.with_apt_archive("apt-get -o Acquire::Retries=3 install -y gcc").startswith("if [ -r /etc/os-release ]")
    assert runner_env.apt_archive_rewrote("x\nRERUN_APT_ARCHIVE bullseye\n", "RERUN_APT_ARCHIVE bullseye") == ["bullseye"]


SH = shutil.which("sh")


def _run_step(tmp_path: Path, codename: str) -> tuple[subprocess.CompletedProcess, Path]:
    root = tmp_path / codename
    (root / "etc" / "apt" / "sources.list.d").mkdir(parents=True)
    (root / "etc" / "apt" / "apt.conf.d").mkdir(parents=True)
    (root / "etc" / "os-release").write_text(f'PRETTY_NAME="Debian"\nVERSION_CODENAME={codename}\n', encoding="utf-8", newline="\n")
    original = "deb http://deb.debian.org/debian x main\ndeb http://security.debian.org/debian-security x-security main\n"
    (root / "etc" / "apt" / "sources.list").write_text(original, encoding="utf-8", newline="\n")
    (root / "etc" / "apt" / "sources.list.d" / "extra.list").write_text("deb http://example.org/x x main\n", encoding="utf-8", newline="\n")
    step = runner_env.apt_archive_step().replace("/etc/", root.as_posix() + "/etc/")
    return subprocess.run([SH, "-c", step], capture_output=True, text=True, timeout=30), root


@pytest.mark.skipif(SH is None, reason="no POSIX sh on this machine")
def test_the_step_rewrites_an_end_of_life_release_and_leaves_a_live_one_alone(tmp_path):
    done, root = _run_step(tmp_path, "bullseye")
    assert done.returncode == 0, done.stderr
    assert (root / "etc" / "apt" / "sources.list").read_text(encoding="utf-8") == "deb http://archive.debian.org/debian bullseye main\n"
    assert not (root / "etc" / "apt" / "sources.list.d" / "extra.list").exists()
    assert 'Acquire::Check-Valid-Until "false";' in (root / "etc" / "apt" / "apt.conf.d" / "99rerun-archive").read_text(encoding="utf-8")
    assert "RERUN_APT_ARCHIVE bullseye" in done.stderr
    live, live_root = _run_step(tmp_path, "bookworm")
    assert live.returncode == 0 and live.stderr == ""
    assert "deb.debian.org" in (live_root / "etc" / "apt" / "sources.list").read_text(encoding="utf-8")
    assert (live_root / "etc" / "apt" / "sources.list.d" / "extra.list").exists()


def _apt_failure(a: dict) -> SandboxRunResult:
    return SandboxRunResult(steps=(StepResult("apt-get update && apt-get install -y libgl1", 100, a["stdout_tail"], a["stderr_tail"], 1.0, 0.01, phase="repo_install"),))


def _apt_pipeline(tmp_path, results):
    """The v1.5.1 test pipeline with a declared dependency the planner maps to apt packages, so the plan has an apt step."""
    from app.services.cost_guard import CostGuard
    from app.services.intake import RepoIntake
    from app.services.orchestrator import PipelineDeps, run_pipeline
    from test_v151_pins_and_removals import _Chat, _git_repo

    _git_repo(tmp_path, {"train.py": "print(1)\n"})
    results, plans = list(results), []

    def runner(**kw):
        plans.append(kw)
        return results.pop(0)

    repair = _Chat()
    deps = PipelineDeps(recon_client=_Chat([{"entrypoint": "train.py", "confidence": 0.9}]), recon_model="r", repair_client=repair, repair_model="p",
                        adjudicator_client=None, adjudicator_model=None, sandbox_api_key="k", sandbox_wall_clock_seconds=100, sandbox_runner=runner,
                        tavily_client=None, smoke_seconds=0, max_attempts=3)
    intake = RepoIntake(tmp_path, "a" * 40, {"requirements.txt": "opencv-python==4.5.1.48\n"}, frozenset({"opencv-python"}), (), ("train.py",), None)
    result = run_pipeline(repo_url="https://example.com/r", commit_sha="a" * 40, workdir=tmp_path, intake_result=intake, deps=deps,
                          cost_guard=CostGuard(daily_cost_ceiling_usd=100), run_id="v17-apt")
    return result, repair, plans, results


def test_replay_entry_16_the_step_runs_before_every_apt_command_once_and_no_model_is_called(tmp_path):
    result, repair, plans, left = _apt_pipeline(tmp_path, [_apt_failure(_recorded_attempt(R16)), _ok()])
    assert not left and not repair.calls
    assert result.verdict == "RUNS_AFTER_REPAIR"
    step = next(a for a in result.attempts if (a.time_machine_action or {}).get("rule") == "apt_archive")
    assert step.origin == "time_machine" and step.time_machine_action["sources"]["bullseye"] == ["deb http://archive.debian.org/debian bullseye main"]
    assert not any(c.startswith("if [ -r /etc/os-release ]") for c in plans[0]["install_commands"])  # the baseline ran as published
    apt_cmds = [c for c in plans[1]["install_commands"] if "apt-get" in c]
    assert apt_cmds and all(c.startswith(runner_env.apt_archive_step()) for c in apt_cmds)
    assert any("apt_archive (harness-v1.7, R4)" in n for n in result.build_plan["notes"])


def test_a_second_apt_mirror_gone_after_the_step_stops_indeterminate_as_before(tmp_path):
    a = _recorded_attempt(R16)
    result, repair, plans, left = _apt_pipeline(tmp_path, [_apt_failure(a), _apt_failure(a)])
    assert not left and not repair.calls and len(plans) == 2
    assert result.verdict == "INDETERMINATE" and result.indeterminate_reason.startswith("APT_MIRROR_GONE")
