"""Sandbox lifecycle (RERUN directive §3 must-have #3, Phase 0).

Wraps the real Nebius Token Factory Sandboxes SDK: `pip install contree-sdk`
(PyPI), importable as `contree_sdk`. Every sandbox run is wrapped in
try/finally so a failure never leaks a Nebius resource, per §2.6.

Ground truth for this module was read directly from the **installed**
`contree_sdk` v0.3.6 source (`.venv/Lib/site-packages/contree_sdk/...`),
not guessed and not taken solely from the (incomplete, beta) hosted docs —
see DECISIONS.md for exactly which source files were read. Key facts that
shape this design:

  - `image.run(..., disposable=True).wait()` is the only execution
    primitive, and `disposable=True` is the SDK's own default: the
    resulting image (and its backing compute) is discarded the moment
    that run completes. There is no separate `sandbox.destroy()` call in
    this SDK version — running the *last* step of a chain with
    `disposable=True` **is** the destroy step. §2.6 ("every sandbox
    session must be destroyed after use") is satisfied by never letting a
    `disposable=False` image survive past this module's `finally` block.
  - Chaining steps (upload files -> install deps -> run entrypoint, each
    against the *result* of the previous step) requires `disposable=False`
    on every non-final step, or the backend discards that intermediate
    image before the next step can reference it. Every such retained image
    is explicitly disposed of in `finally` via a trivial `disposable=True`
    no-op run, so a mid-chain exception can never leave a resource behind.
  - `ContreeResult.cost` (a float, USD) comes back from every completed
    step and is the real number `cost_guard.CostGuard.record_spend()`
    should be fed — not an estimate.

**Not yet live-verified.** Phase 0's actual gate (3 real sandboxes created
and destroyed, logs shown to a human) requires a real `NEBIUS_API_KEY` that
is not present in this environment. This module is written and structured
against the real SDK's real API, but has only been exercised by this
file's own unit tests against duck-typed stand-ins for `ContreeResult` —
see `test_sandbox.py`. Do not report Phase 0 as done until it has actually
run against the live API.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Protocol

from contree_sdk import ContreeSync
from contree_sdk.sdk.exceptions import ContreeError, OperationTimedOutError


class SandboxError(RuntimeError):
    pass


class SandboxCredentialsError(SandboxError):
    pass


class _ResultLike(Protocol):
    exit_code: int
    stdout: str | None
    stderr: str | None

    @property
    def elapsed_time(self): ...

    @property
    def cost(self) -> float: ...


@dataclass(frozen=True)
class StepResult:
    command: str
    exit_code: int
    stdout: str
    stderr: str
    elapsed_seconds: float
    cost_usd: float


@dataclass(frozen=True)
class SandboxRunResult:
    steps: tuple[StepResult, ...]

    @property
    def final(self) -> StepResult:
        if not self.steps:
            raise SandboxError("sandbox run produced no steps")
        return self.steps[-1]

    @property
    def total_cost_usd(self) -> float:
        return sum(s.cost_usd for s in self.steps)

    @property
    def succeeded(self) -> bool:
        return self.final.exit_code == 0


def step_result_from_image(image, command: str) -> StepResult:
    """Map a completed contree_sdk image's `.result` onto our own
    dataclass, so the rest of the codebase never touches the SDK's types
    directly. `image.result` matches `ContreeResult` (see module
    docstring) — this function is exercised in tests against a duck-typed
    stand-in exposing the same shape, since a live image can't be
    constructed without hitting the real API.
    """
    result: _ResultLike = image.result
    return StepResult(
        command=command,
        exit_code=result.exit_code,
        stdout=result.stdout or "",
        stderr=result.stderr or "",
        elapsed_seconds=result.elapsed_time.total_seconds(),
        cost_usd=result.cost,
    )


def run_build_and_execute(
    *,
    api_key: str,
    base_image: str,
    install_commands: Iterable[str],
    execute_command: str,
    wall_clock_seconds: float,
    upload_files: dict[str, str | Path | bytes] | None = None,
) -> SandboxRunResult:
    """Run the full build-plan pipeline in an isolated Token Factory
    Sandbox: reference/import the base image, upload the repo, run each
    install command, then the execute command — stopping at the first
    non-zero exit code. Always tears down sandbox resources, success or
    failure (§2.6): every intermediate retained (`disposable=False`) image
    is disposed of in `finally`, and the final step always runs with
    `disposable=True`.
    """
    if not api_key:
        raise SandboxCredentialsError(
            "NEBIUS_API_KEY is not set — cannot open a Token Factory Sandbox. "
            "Populate .env from .env.example before running a real sandbox."
        )

    client = ContreeSync(token=api_key)
    image = client.images.docker(base_image)

    steps: list[StepResult] = []
    current = image
    retained_images = []  # every disposable=False image, for guaranteed cleanup

    try:
        if upload_files:
            current = current.apply_files(files=upload_files)
            retained_images.append(current)

        commands = [*install_commands, execute_command]
        if not commands:
            raise SandboxError("no commands to run: install_commands and execute_command are both empty")

        # `wall_clock_seconds` is meant to be a single hard ceiling for the
        # WHOLE attempt (§4: "hard limits (wall clock...)"; the TIMEOUT
        # verdict means "exceeded wall-clock ceiling", singular). Found
        # live: passing the full `wall_clock_seconds` unchanged to every
        # step's own `timeout=` would let a multi-step build (each install
        # command plus the execute command) consume up to
        # len(commands) * wall_clock_seconds in aggregate — e.g. a
        # configured 60s ceiling silently allowing 180s for a 2-install
        # build. Tracking one shared deadline across all steps makes the
        # configured value an actual ceiling on the whole attempt,
        # matching §9's cost-predictability goal, rather than a per-step
        # allowance that scales with how many install commands a given
        # repo happens to need.
        deadline = time.monotonic() + wall_clock_seconds
        for i, cmd in enumerate(commands):
            is_last = i == len(commands) - 1
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise SandboxError(
                    f"sandbox execution exceeded {wall_clock_seconds}s wall clock "
                    f"for the whole attempt (stopped before running '{cmd}')"
                )
            executed = current.run(
                shell=cmd,
                timeout=remaining,
                disposable=is_last,
                preserve_env=not is_last,
            ).wait()
            steps.append(step_result_from_image(executed, cmd))
            current = executed
            if not is_last:
                retained_images.append(executed)
            if executed.exit_code != 0:
                break

        return SandboxRunResult(steps=tuple(steps))

    except OperationTimedOutError as exc:
        raise SandboxError(f"sandbox execution exceeded {wall_clock_seconds}s wall clock: {exc}") from exc
    except ContreeError as exc:
        raise SandboxError(f"sandbox execution failed: {exc}") from exc
    finally:
        for retained in retained_images:
            try:
                retained.run(shell="true", disposable=True, timeout=30).wait()
            except ContreeError:
                pass  # best-effort cleanup; nothing more actionable from here
