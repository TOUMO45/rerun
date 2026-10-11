"""The hosted demos and the one-command local demo are keyless (owner, 2026-10-10; Render brought to the Space's standard 2026-10-11): no key reaches the
Space or Render image, each container refuses to start with one, each image is pinned, and the local launcher forces the keys empty. Static checks of the
deploy files, plus the start-up guard run under a POSIX shell when one is available. The images themselves are built and probed by
.github/workflows/demo-check.yml (no secret)."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
KEYS = ("NEBIUS_API_KEY", "NEBIUS_PROJECT_ID", "TAVILY_API_KEY")
IMAGES = ("deploy/hf-space", "deploy/render")


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


@pytest.mark.parametrize("folder", IMAGES)
def test_the_image_sets_demo_mode_and_no_key(folder):
    text = _read(f"{folder}/Dockerfile")
    assert re.search(r"DEMO_MODE=1", text)
    for name in ("NEBIUS_API_KEY", "TAVILY_API_KEY"):
        assert re.search(rf"{name}=\s*\\?\n", text), f"{name} must be set empty in the image"
    assert not re.search(r"(?:ARG|ENV)\s+\w*(?:KEY|TOKEN|SECRET)\w*=\S", text), "no key, token or secret may be given a value in the image"
    assert "COPY .env" not in text and "find /repo -name .env -type f -delete" in text


@pytest.mark.parametrize("folder", IMAGES)
def test_the_image_is_pinned(folder):
    text = _read(f"{folder}/Dockerfile")
    assert "pip install --no-cache-dir -c /repo/.github/seal/constraints.txt /repo/backend" in text
    assert (ROOT / ".github" / "seal" / "constraints.txt").is_file()
    assert "npm ci" in text  # the frontend installs from its lock file
    bases = re.findall(r"^FROM\s+(\S+)", text, re.MULTILINE)
    assert bases == ["node:20.19.5-alpine", "python:3.14-slim"], bases  # exact tags, the same in both images


def test_render_serves_a_pinned_commit():
    ref = re.search(r"^ARG REF=(\S+)$", _read("deploy/render/Dockerfile"), re.MULTILINE)
    assert ref and re.fullmatch(r"[0-9a-f]{40}", ref.group(1)), "Render builds the repository's Dockerfile as is: REF must be a full commit SHA, never a branch"


@pytest.mark.parametrize("folder", IMAGES)
def test_the_start_script_refuses_a_key_and_a_disabled_demo_mode(folder):
    text = _read(f"{folder}/start.sh")
    assert all(name in text for name in KEYS) and 'DEMO_MODE:-}" != "1"' in text and "/repo/.env" in text
    assert "\r" not in text and "s/\\r$//" in _read(f"{folder}/Dockerfile")


def _guard(folder: str) -> list[str]:
    lines = _read(f"{folder}/start.sh").splitlines()
    start = next(i for i, l in enumerate(lines) if l.startswith("for name in"))
    end = next(i for i, l in enumerate(lines) if "/repo/.env" in l)
    return lines[start:end + 1]


def test_the_two_images_share_one_guard():
    strip = lambda ls: [re.sub(r"\(remove the [^)]*\)", "", l) for l in ls]  # noqa: E731 - only the hint at the end of the refusal names the platform
    assert strip(_guard("deploy/hf-space")) == strip(_guard("deploy/render"))


@pytest.mark.skipif(shutil.which("sh") is None, reason="no POSIX shell on this machine")
@pytest.mark.parametrize("folder", IMAGES)
@pytest.mark.parametrize("env, refused", [({"DEMO_MODE": "1"}, False), ({"DEMO_MODE": "1", "TAVILY_API_KEY": "x" * 40}, True),
                                          ({"DEMO_MODE": "1", "NEBIUS_API_KEY": "x" * 40}, True), ({"DEMO_MODE": "1", "NEBIUS_PROJECT_ID": "x" * 40}, True),
                                          ({"DEMO_MODE": "0"}, True)])
def test_the_start_up_guard_runs(tmp_path, folder, env, refused):
    guard = tmp_path / "guard.sh"
    guard.write_text("\n".join(_guard(folder)) + "\n", encoding="utf-8", newline="\n")
    proc = subprocess.run([shutil.which("sh"), str(guard)], env={"PATH": "/usr/bin:/bin", **env}, capture_output=True, text=True)
    assert (proc.returncode != 0) is refused
    assert "x" * 40 not in proc.stderr  # the message names the variable, never its value


def test_the_local_launcher_forces_the_keys_empty():
    demo = _read("demo.py")
    assert 'KEYS = ("NEBIUS_API_KEY", "NEBIUS_PROJECT_ID", "TAVILY_API_KEY")' in demo and 'env.update({k: "" for k in KEYS})' in demo and '"DEMO_MODE": "1"' in demo


def test_no_untested_demo_path_is_offered():
    """2026-10-11 (owner): a judge must not find a demo path that was never tested. The compose demo was removed; the README offers demo.py and the two
    images, and the workflow builds and probes each of them."""
    assert not (ROOT / "docker-compose.demo.yml").exists()
    readme = _read("README.md")
    assert "docker compose" not in readme and "docker-compose.demo" not in readme
    workflow = _read(".github/workflows/demo-check.yml")
    assert "python demo.py --check" in workflow
    for folder in IMAGES:
        assert f"--build-arg REF=${{{{ github.sha }}}} {folder}" in workflow, folder


def test_the_space_readme_says_no_secret():
    text = _read("deploy/hf-space/README.md")
    assert text.startswith("---\n") and "sdk: docker" in text and "app_port: 7860" in text
    assert "Do not add any secret or variable" in text
