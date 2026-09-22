"""Tests for the Batch Lab job entrypoint (app/batch/run_single_repo.py).

`run_one_repo`'s clone step is real (against a real local git repo, same
pattern as test_intake.py) — only the orchestrator call itself is faked,
since that needs live Nebius credentials. This proves the actual
job-container logic (clone at a pinned commit, detect non-Python repos,
shape the output dict) works, not just that it could theoretically be
wired up.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from app.batch.run_single_repo import main, run_one_repo
from app.services.orchestrator import PipelineResult


class _FakeSettings:
    nebius_api_key = "fake-key-for-construction-only"
    nebius_base_url = "https://api.tokenfactory.nebius.com/v1"
    nebius_model_recon = "nvidia/nemotron-3-nano"
    nebius_model_repairer = "nvidia/nemotron-3-super"
    nebius_model_adjudicator = "nvidia/nemotron-3-ultra"
    nebius_model_planner = "nvidia/nemotron-3-super"
    nebius_sandbox_wall_clock_seconds = 60
    max_attempts_per_run = 3
    daily_cost_ceiling_usd = 25.0
    tavily_configured = False
    nebius_sandbox_image = "python:3.11-slim"
    nebius_project_id = ""
    nebius_sandbox_backend = "token_factory"


def _fake_run_pipeline(**kwargs) -> PipelineResult:
    from datetime import datetime, timezone

    return PipelineResult(
        verdict="RUNS_CLEAN",
        taxonomy_code=None,
        indeterminate_reason="",
        attempts=(),
        build_plan={},
        full_log="[fake]",
        certificate_prose="ok",
        reproduction_passport_hash="a" * 64,
        timestamp=datetime.now(timezone.utc).isoformat(),
        repo_url=kwargs["repo_url"],
        commit_sha=kwargs["commit_sha"],
    )


def test_run_one_repo_clones_at_the_pinned_commit_and_runs_the_pipeline(fake_paper_repo):
    real_sha = subprocess.run(
        ["git", "-C", str(fake_paper_repo), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()

    result = run_one_repo(
        str(fake_paper_repo),
        real_sha,
        "test-repo",
        settings=_FakeSettings(),
        run_pipeline_fn=_fake_run_pipeline,
    )

    duration = result.pop("duration_seconds")
    assert result == {
        "name": "test-repo",
        "repo_url": str(fake_paper_repo),
        "verdict": "RUNS_CLEAN",
        "taxonomy_code": None,
        "attempts_used": 0,
    }
    assert isinstance(duration, float)


def test_run_one_repo_detects_non_python_repo_without_ever_calling_the_pipeline(tmp_path):
    src = tmp_path / "non_python_repo"
    src.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=src, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=src, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=src, check=True, capture_output=True)
    subprocess.run(["git", "config", "uploadpack.allowReachableSHA1InWant", "true"], cwd=src, check=True, capture_output=True)
    (src / "README.md").write_text("just docs\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=src, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=src, check=True, capture_output=True)
    real_sha = subprocess.run(
        ["git", "-C", str(src), "rev-parse", "HEAD"], capture_output=True, text=True, check=True,
    ).stdout.strip()

    def _exploding_pipeline(**kwargs):
        raise AssertionError("run_pipeline must never be called for a repo with no Python code")

    result = run_one_repo(
        str(src), real_sha, "non-python", settings=_FakeSettings(), run_pipeline_fn=_exploding_pipeline
    )
    assert result["verdict"] == "NOT_ATTEMPTABLE"
    assert result["attempts_used"] == 0


def test_run_one_repo_cleans_up_its_workdir(fake_paper_repo):
    real_sha = subprocess.run(
        ["git", "-C", str(fake_paper_repo), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()

    captured_workdir = {}

    def _capturing_pipeline(**kwargs):
        captured_workdir["path"] = kwargs["workdir"]
        assert kwargs["workdir"].is_dir()
        return _fake_run_pipeline(**kwargs)

    run_one_repo(
        str(fake_paper_repo), real_sha, "test-repo", settings=_FakeSettings(), run_pipeline_fn=_capturing_pipeline
    )
    assert not captured_workdir["path"].exists()


def test_main_prints_valid_json_and_exits_zero_on_success(fake_paper_repo, monkeypatch, capsys):
    real_sha = subprocess.run(
        ["git", "-C", str(fake_paper_repo), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    monkeypatch.setattr("app.batch.run_single_repo.get_settings", lambda: _FakeSettings())
    monkeypatch.setattr("app.batch.run_single_repo.run_pipeline", _fake_run_pipeline)

    exit_code = main(["--repo-url", str(fake_paper_repo), "--commit-sha", real_sha, "--name", "test-repo"])

    assert exit_code == 0
    output = json.loads(capsys.readouterr().out.strip())
    assert output["verdict"] == "RUNS_CLEAN"


def test_main_exits_nonzero_on_clone_failure(tmp_path, capsys):
    exit_code = main(
        ["--repo-url", str(tmp_path / "does_not_exist"), "--commit-sha", "a" * 40, "--name", "missing-repo"]
    )
    assert exit_code == 1
    output = json.loads(capsys.readouterr().out.strip())
    assert "error" in output


def test_script_is_invokable_as_a_real_subprocess_module(tmp_path):
    # Proves `python -m app.batch.run_single_repo ...` (exactly how
    # runner.run_single_repo_job constructs the job's container args)
    # actually works as a real entrypoint, not just as an importable
    # function.
    backend_dir = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, "-m", "app.batch.run_single_repo",
         "--repo-url", str(tmp_path / "does_not_exist"),
         "--commit-sha", "a" * 40,
         "--name", "missing-repo"],
        cwd=backend_dir,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 1
    output = json.loads(result.stdout.strip())
    assert "error" in output
