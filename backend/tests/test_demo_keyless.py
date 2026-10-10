"""The hosted demo and the one-command local demo are keyless (owner, 2026-10-10): no key reaches the Space image, the container refuses to start with one,
and the local launcher forces the keys empty. Static checks of the deploy files, plus the start-up guard run under a POSIX shell when one is available."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPACE = ROOT / "deploy" / "hf-space"
KEYS = ("NEBIUS_API_KEY", "NEBIUS_PROJECT_ID", "TAVILY_API_KEY")


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_the_space_image_sets_demo_mode_and_no_key():
    text = _read("deploy/hf-space/Dockerfile")
    assert re.search(r"DEMO_MODE=1", text)
    for name in ("NEBIUS_API_KEY", "TAVILY_API_KEY"):
        assert re.search(rf"{name}=\s*\\?\n", text), f"{name} must be set empty in the image"
    assert not re.search(r"(?:ARG|ENV)\s+\w*(?:KEY|TOKEN|SECRET)\w*=\S", text), "no key, token or secret may be given a value in the image"
    assert "COPY .env" not in text and "find /repo -name .env -type f -delete" in text


def test_the_space_image_installs_the_pinned_backend():
    text = _read("deploy/hf-space/Dockerfile")
    assert "pip install --no-cache-dir -c /repo/.github/seal/constraints.txt /repo/backend" in text
    assert (ROOT / ".github" / "seal" / "constraints.txt").is_file()
    assert "npm ci" in text  # the frontend installs from its lock file


def test_the_start_script_refuses_a_key_and_a_disabled_demo_mode():
    text = _read("deploy/hf-space/start.sh")
    assert all(name in text for name in KEYS) and 'DEMO_MODE:-}" != "1"' in text and "/repo/.env" in text
    assert "\r" not in text and "s/\\r$//" in _read("deploy/hf-space/Dockerfile")


@pytest.mark.skipif(shutil.which("sh") is None, reason="no POSIX shell on this machine")
@pytest.mark.parametrize("env, refused", [({"DEMO_MODE": "1"}, False), ({"DEMO_MODE": "1", "TAVILY_API_KEY": "x" * 40}, True),
                                          ({"DEMO_MODE": "1", "NEBIUS_API_KEY": "x" * 40}, True), ({"DEMO_MODE": "0"}, True)])
def test_the_start_up_guard_runs(tmp_path, env, refused):
    lines = _read("deploy/hf-space/start.sh").splitlines()
    start = next(i for i, l in enumerate(lines) if l.startswith("for name in"))
    end = next(i for i, l in enumerate(lines) if "/repo/.env" in l)
    guard = tmp_path / "guard.sh"
    guard.write_text("\n".join(lines[start:end + 1]) + "\n", encoding="utf-8", newline="\n")
    proc = subprocess.run([shutil.which("sh"), str(guard)], env={"PATH": "/usr/bin:/bin", **env}, capture_output=True, text=True)
    assert (proc.returncode != 0) is refused
    assert "x" * 40 not in proc.stderr  # the message names the variable, never its value


def test_the_compose_demo_and_the_local_launcher_force_the_keys_empty():
    compose = _read("docker-compose.demo.yml")
    assert 'DEMO_MODE: "1"' in compose and all(f'{name}: ""' in compose for name in KEYS)
    demo = _read("demo.py")
    assert 'KEYS = ("NEBIUS_API_KEY", "NEBIUS_PROJECT_ID", "TAVILY_API_KEY")' in demo and 'env.update({k: "" for k in KEYS})' in demo and '"DEMO_MODE": "1"' in demo


def test_the_space_readme_says_no_secret():
    text = _read("deploy/hf-space/README.md")
    assert text.startswith("---\n") and "sdk: docker" in text and "app_port: 7860" in text
    assert "Do not add any secret or variable" in text
