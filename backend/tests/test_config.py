"""Tests for config.py's .env loading — specifically that it is NOT
sensitive to the process's current working directory at import/instantiation
time. Uses real subprocesses with different cwds rather than monkeypatching
`os.getcwd`, since the whole point is to catch exactly the class of bug a
bare relative `env_file="../.env"` string has: pydantic-settings resolves
that against the real process cwd, which in-process monkeypatching of
Python-level state doesn't reliably simulate for a library that may use
`Path.cwd()` or `os.getcwd()` internally.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = REPO_ROOT / "backend"

_LOAD_AND_PRINT_KEY = (
    "import sys; sys.path.insert(0, str(__import__('pathlib').Path(r'"
    + str(BACKEND_DIR)
    + "')));"
    "from app.config import get_settings; print(get_settings().nebius_api_key)"
)


def _run_from(cwd: Path, env_file_content: str) -> str:
    env_path = REPO_ROOT / ".env"
    assert not env_path.exists(), "a real .env already exists at the repo root — refusing to overwrite it"
    env_path.write_text(env_file_content, encoding="utf-8")
    try:
        result = subprocess.run(
            [sys.executable, "-c", _LOAD_AND_PRINT_KEY],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=30,
        )
    finally:
        env_path.unlink(missing_ok=True)
    assert result.returncode == 0, f"subprocess failed: {result.stderr}"
    return result.stdout.strip()


def test_settings_loads_repo_root_env_when_invoked_from_backend_dir():
    value = _run_from(BACKEND_DIR, "NEBIUS_API_KEY=from-repo-root-env\n")
    assert value == "from-repo-root-env"


def test_settings_loads_repo_root_env_when_invoked_from_repo_root():
    # This is the exact case a bare relative `env_file="../.env"` string
    # gets wrong: it would resolve one directory ABOVE the repo root when
    # the process's cwd is the repo root itself, silently finding nothing
    # and falling back to the empty-string default with no error at all.
    value = _run_from(REPO_ROOT, "NEBIUS_API_KEY=from-repo-root-env\n")
    assert value == "from-repo-root-env"


def test_settings_config_points_at_a_real_existing_directory():
    # A cheap, direct structural check: whatever path config.py resolved
    # for the .env file, its parent directory must actually be the repo
    # root (where .env.example genuinely lives), not something computed
    # relative to an assumption about cwd.
    from app.config import _REPO_ROOT_ENV_FILE

    assert _REPO_ROOT_ENV_FILE.parent == REPO_ROOT
    assert (REPO_ROOT / ".env.example").is_file()
