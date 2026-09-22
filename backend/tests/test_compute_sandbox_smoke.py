"""Live Compute-VM kill gate, mirroring test_sandbox_smoke.py's pattern for
the Token Factory backend: provisions one real Nebius AI Cloud Compute VM,
runs a command on it, and tears it down.

This is a REAL integration test, not a mock. It is skipped (not faked) when
NEBIUS_COMPUTE_CREDENTIALS_FILE isn't configured, per the directive's rule
against ever reporting a gate green without actually running it. Populate
the Compute-specific vars from .env.example (NEBIUS_COMPUTE_CREDENTIALS_FILE,
NEBIUS_COMPUTE_PROJECT_ID, NEBIUS_COMPUTE_SUBNET_ID, NEBIUS_COMPUTE_PLATFORM,
NEBIUS_COMPUTE_PRESET, NEBIUS_COMPUTE_IMAGE_FAMILY) and export them to run
this for real:

    cd backend
    set -a; source ../.env; set +a
    pytest tests/test_compute_sandbox_smoke.py -v -s

Unlike test_sandbox_smoke.py, this has never been run even once as of this
session's Nebius integration audit — there is no real Nebius Compute
credential, subnet, or image family available here. It exists so that the
first person with real Compute access has an actual gate to run rather than
having to write one from scratch. See compute_sandbox.py's module docstring
for exactly what is and isn't verified about the code this exercises.
"""

from __future__ import annotations

import os

import pytest

from app.services.compute_sandbox import run_build_and_execute

NEBIUS_COMPUTE_CREDENTIALS_FILE = os.environ.get("NEBIUS_COMPUTE_CREDENTIALS_FILE", "")

pytestmark = pytest.mark.skipif(
    not NEBIUS_COMPUTE_CREDENTIALS_FILE,
    reason=(
        "NEBIUS_COMPUTE_CREDENTIALS_FILE not set — this is the real Nebius AI Cloud "
        "Compute integration test and cannot be faked. Set it plus NEBIUS_COMPUTE_PROJECT_ID/"
        "SUBNET_ID/PLATFORM/PRESET/IMAGE_FAMILY (see .env.example) to actually run this gate."
    ),
)


def test_compute_sandbox_provisions_runs_and_tears_down_a_real_vm(capsys):
    result = run_build_and_execute(
        credentials_file=NEBIUS_COMPUTE_CREDENTIALS_FILE,
        project_id=os.environ.get("NEBIUS_COMPUTE_PROJECT_ID", ""),
        subnet_id=os.environ.get("NEBIUS_COMPUTE_SUBNET_ID", ""),
        platform=os.environ.get("NEBIUS_COMPUTE_PLATFORM", "cpu-e2"),
        preset=os.environ.get("NEBIUS_COMPUTE_PRESET", "4vcpu-16gb"),
        image_family=os.environ.get("NEBIUS_COMPUTE_IMAGE_FAMILY", ""),
        ssh_username=os.environ.get("NEBIUS_COMPUTE_SSH_USERNAME", "ubuntu"),
        boot_disk_gib=int(os.environ.get("NEBIUS_COMPUTE_BOOT_DISK_GIB", "20")),
        base_image="python:3.11-slim",
        install_commands=[],
        execute_command="python -c \"print('rerun compute sandbox smoke')\"",
        wall_clock_seconds=600,
    )
    with capsys.disabled():
        print(f"\n[compute sandbox smoke] instance={result.sandbox_id}")
        print(f"[compute sandbox smoke] exit_code={result.final.exit_code}")
        print(f"[compute sandbox smoke] stdout={result.final.stdout!r}")
    assert result.succeeded
    assert result.final.stdout.strip() != ""
