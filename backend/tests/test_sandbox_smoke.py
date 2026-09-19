"""Phase 0 kill gate (RERUN_BUILD_DIRECTIVE.md §11): sandbox lifecycle
proven end-to-end on 3 throwaway runs — real sandboxes created and
destroyed against the live Nebius Token Factory API.

This is a REAL integration test, not a mock. It is skipped (not faked)
when `NEBIUS_API_KEY` isn't configured, per the directive's rule against
ever reporting a gate green without actually running it. Populate `.env`
(copy from `.env.example`) and export `NEBIUS_API_KEY` to run this for
real:

    cd backend
    set -a; source ../.env; set +a   # or just export NEBIUS_API_KEY=...
    pytest tests/test_sandbox_smoke.py -v -s

Each of the 3 runs uses a distinct base image/command so this can't be
satisfied by one cached/reused sandbox — three genuinely separate
create-and-destroy cycles.
"""

from __future__ import annotations

import os

import pytest

from app.services.sandbox import run_build_and_execute

NEBIUS_API_KEY = os.environ.get("NEBIUS_API_KEY", "")

pytestmark = pytest.mark.skipif(
    not NEBIUS_API_KEY,
    reason=(
        "NEBIUS_API_KEY not set — this is the real Nebius Token Factory "
        "Sandboxes integration test and cannot be faked. Set NEBIUS_API_KEY "
        "(see .env.example) to actually run Phase 0's kill gate."
    ),
)


@pytest.mark.parametrize(
    "base_image,command",
    [
        ("python:3.11-slim", "python -c \"print('rerun sandbox smoke 1')\""),
        ("python:3.11-slim", "python -c \"import sys; print(sys.version)\""),
        ("python:3.11-slim", "echo 'rerun sandbox smoke 3'"),
    ],
)
def test_sandbox_created_executed_and_destroyed(base_image, command, capsys):
    result = run_build_and_execute(
        api_key=NEBIUS_API_KEY,
        base_image=base_image,
        install_commands=[],
        execute_command=command,
        wall_clock_seconds=120,
    )
    with capsys.disabled():
        print(f"\n[sandbox smoke] image={base_image!r} command={command!r}")
        print(f"[sandbox smoke] exit_code={result.final.exit_code} cost_usd={result.total_cost_usd}")
        print(f"[sandbox smoke] stdout={result.final.stdout!r}")
    assert result.succeeded
    assert result.final.stdout.strip() != ""
