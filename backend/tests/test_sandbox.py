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


# --- wall_clock_seconds is a single shared deadline, not a per-step budget --


class _FakeChainedImage:
    """Duck-typed stand-in for the full contree_sdk chaining shape (image
    -> .run(...).wait() -> another chainable image), matching .exit_code
    as a property delegating to .result.exit_code — verified against the
    installed SDK's real ImageLike._base.py."""

    def __init__(self, recorded_timeouts, fake_clock, step_duration=50.0, exit_code=0):
        self._recorded = recorded_timeouts
        self._clock = fake_clock
        self._step_duration = step_duration
        self.result = _FakeResult(
            exit_code=exit_code, stdout="ok", stderr="", elapsed_time=timedelta(seconds=1), cost=0.001
        )

    @property
    def exit_code(self):
        return self.result.exit_code

    def apply_files(self, files):
        return self

    def run(self, *, shell, timeout, disposable, preserve_env=None):
        self._recorded.append((shell, timeout))
        self._clock[0] += self._step_duration
        return self

    def wait(self):
        return self


def _install_fake_contree_sync(monkeypatch, recorded_timeouts, fake_clock, step_duration=50.0):
    import app.services.sandbox as sandbox_module

    class _FakeImages:
        def docker(self, ref):
            return _FakeChainedImage(recorded_timeouts, fake_clock, step_duration)

    class _FakeContreeSync:
        def __init__(self, token):
            self.images = _FakeImages()

    monkeypatch.setattr(sandbox_module, "ContreeSync", _FakeContreeSync)
    monkeypatch.setattr(sandbox_module.time, "monotonic", lambda: fake_clock[0])


def test_run_build_and_execute_shrinks_the_remaining_budget_across_steps(monkeypatch):
    """Found live during this session's audit: passing the full
    wall_clock_seconds unchanged to every step's own timeout= would let a
    multi-step build consume up to len(commands) * wall_clock_seconds in
    aggregate (e.g. a configured 60s ceiling silently allowing 120s across
    two install commands), rather than a single ceiling for the whole
    attempt. Each real command here "takes" 20 simulated seconds; the
    second command's timeout must reflect the 20s already spent, not a
    fresh full 60s.
    """
    recorded_timeouts: list[tuple[str, float]] = []
    fake_clock = [0.0]
    _install_fake_contree_sync(monkeypatch, recorded_timeouts, fake_clock, step_duration=20.0)

    run_build_and_execute(
        api_key="fake-key",
        base_image="python:3.11-slim",
        install_commands=["pip install numpy"],
        execute_command="python train.py",
        wall_clock_seconds=60,
    )

    real_timeouts = [t for shell, t in recorded_timeouts if shell != "true"]
    assert len(real_timeouts) == 2
    assert real_timeouts[0] == pytest.approx(60.0)
    assert real_timeouts[1] == pytest.approx(40.0)  # 60 - 20 already spent, not a fresh 60


def test_run_build_and_execute_stops_before_exceeding_the_shared_deadline(monkeypatch):
    """Companion test: once the shared deadline is exhausted, a further
    step must not be started at all (with its own fresh timeout) - the
    attempt fails clearly instead of silently running past the configured
    ceiling.
    """
    recorded_timeouts: list[tuple[str, float]] = []
    fake_clock = [0.0]
    _install_fake_contree_sync(monkeypatch, recorded_timeouts, fake_clock, step_duration=50.0)

    with pytest.raises(SandboxError, match="exceeded 60s wall clock for the whole attempt"):
        run_build_and_execute(
            api_key="fake-key",
            base_image="python:3.11-slim",
            install_commands=["pip install numpy", "pip install torch"],
            execute_command="python train.py",
            wall_clock_seconds=60,
        )

    real_commands_run = [shell for shell, _ in recorded_timeouts if shell != "true"]
    # Two 50s steps already exceed the 60s deadline - the third (execute)
    # command must never have been started.
    assert real_commands_run == ["pip install numpy", "pip install torch"]
