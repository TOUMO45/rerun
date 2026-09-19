"""Tests for sandbox.py's pure/structural logic only.

These do NOT hit the real Nebius Token Factory API — there is no
NEBIUS_API_KEY in this environment (see DECISIONS.md). What's tested here:

  1. `step_result_from_image` correctly maps a `contree_sdk`-shaped result
     object (duck-typed to match the real `ContreeResult` fields read from
     the installed SDK source) onto our own `StepResult`.
  2. `SandboxRunResult`'s pure aggregation logic (`final`, `total_cost_usd`,
     `succeeded`).
  3. `run_build_and_execute` fails fast with a clear, specific error when
     no API key is configured, instead of a confusing SDK-internal
     exception several calls deep.

Phase 0's actual gate — 3 real sandboxes created and destroyed against the
live API — is intentionally NOT claimed here. See `test_sandbox_smoke.py`
for that (skipped until credentials are available).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

import pytest

from app.services.sandbox import (
    SandboxCredentialsError,
    SandboxError,
    SandboxRunResult,
    StepResult,
    run_build_and_execute,
    step_result_from_image,
)


@dataclass
class _FakeResult:
    """Duck-typed stand-in matching the real contree_sdk.ContreeResult
    fields (exit_code: int, stdout/stderr: str | None, elapsed_time:
    timedelta, cost: float) as read from the installed SDK source."""

    exit_code: int
    stdout: str | None
    stderr: str | None
    elapsed_time: timedelta
    cost: float


class _FakeImage:
    def __init__(self, result: _FakeResult):
        self.result = result


def test_step_result_from_image_maps_all_fields():
    fake = _FakeImage(
        _FakeResult(exit_code=1, stdout="building...", stderr="ModuleNotFoundError", elapsed_time=timedelta(seconds=12.5), cost=0.002)
    )
    step = step_result_from_image(fake, "pip install -r requirements.txt")
    assert step == StepResult(
        command="pip install -r requirements.txt",
        exit_code=1,
        stdout="building...",
        stderr="ModuleNotFoundError",
        elapsed_seconds=12.5,
        cost_usd=0.002,
    )


def test_step_result_from_image_handles_none_stdout_stderr():
    # The real SDK can return None for stdout/stderr; we normalize to "".
    fake = _FakeImage(_FakeResult(exit_code=0, stdout=None, stderr=None, elapsed_time=timedelta(seconds=1), cost=0.0))
    step = step_result_from_image(fake, "true")
    assert step.stdout == ""
    assert step.stderr == ""


def test_sandbox_run_result_final_and_success():
    steps = (
        StepResult("install", 0, "", "", 5.0, 0.001),
        StepResult("execute", 0, "done", "", 3.0, 0.0005),
    )
    result = SandboxRunResult(steps=steps)
    assert result.final == steps[-1]
    assert result.succeeded is True
    assert result.total_cost_usd == pytest.approx(0.0015)


def test_sandbox_run_result_negative_control_failure_not_succeeded():
    steps = (StepResult("execute", 1, "", "Traceback...", 2.0, 0.0001),)
    result = SandboxRunResult(steps=steps)
    assert result.succeeded is False


def test_sandbox_run_result_final_raises_on_empty_steps():
    result = SandboxRunResult(steps=())
    with pytest.raises(SandboxError):
        _ = result.final


# --- Fail-fast credential check (no network call should happen) ------------


def test_run_build_and_execute_fails_fast_without_api_key():
    with pytest.raises(SandboxCredentialsError):
        run_build_and_execute(
            api_key="",
            base_image="python:3.11-slim",
            install_commands=["pip install -r requirements.txt"],
            execute_command="python train.py",
            wall_clock_seconds=60,
        )
