"""Tests for intake.py: repo cloning (§2.5, read-only) and dependency/
entrypoint/notebook parsing.

The clone test uses a real local git repository (created on disk in a
pytest tmp_path, no network) so `clone_repo` is proven against real `git`
subprocess behavior, not mocked — per the directive's "never report done
without a command that actually runs" ethos.
"""

from __future__ import annotations

import subprocess

import pytest

from app.services.intake import (
    IntakeError,
    clone_repo,
    detect_python_version_hint,
    find_dependency_files,
    find_entrypoint_candidates,
    find_notebooks,
    parse_declared_dependencies,
    parse_environment_yml,
    parse_requirements_txt,
    parse_setup_py,
    run_intake,
)


def _git(*args: str, cwd) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


@pytest.fixture
def fake_paper_repo(tmp_path):
    """A minimal but realistic fake 'paper repo' committed to a real local
    git repository, so cloning it is a real filesystem+git operation."""
    src = tmp_path / "source_repo"
    src.mkdir()
    _git("init", "-b", "main", cwd=src)
    _git("config", "user.email", "test@example.com", cwd=src)
    _git("config", "user.name", "Test", cwd=src)

    (src / "requirements.txt").write_text("numpy==1.26.0\ntorch>=2.0\n# a comment\n-e .\n", encoding="utf-8")
    (src / "train.py").write_text(
        "def main():\n    pass\n\nif __name__ == '__main__':\n    main()\n",
        encoding="utf-8",
    )
    (src / "utils.py").write_text("def helper():\n    return 1\n", encoding="utf-8")
    notebooks_dir = src / "notebooks"
    notebooks_dir.mkdir()
    (notebooks_dir / "explore.ipynb").write_text("{}", encoding="utf-8")

    _git("add", "-A", cwd=src)
    _git("commit", "-m", "initial", cwd=src)
    return src


# --- clone_repo: real local git operations -----------------------------------


def test_clone_repo_returns_real_commit_sha(fake_paper_repo, tmp_path):
    dest = tmp_path / "cloned"
    sha = clone_repo(str(fake_paper_repo), dest, shallow=False)
    assert len(sha) == 40  # full git SHA-1 hex length
    assert (dest / "train.py").is_file()


def test_clone_repo_raises_intake_error_for_bad_url(tmp_path):
    dest = tmp_path / "cloned_bad"
    with pytest.raises(IntakeError):
        clone_repo(str(tmp_path / "does_not_exist_repo"), dest)


# --- run_intake: end-to-end on the real cloned repo --------------------------


def test_run_intake_end_to_end(fake_paper_repo, tmp_path):
    dest = tmp_path / "intake_target"
    intake = run_intake(str(fake_paper_repo), dest, shallow=False)
    assert len(intake.commit_sha) == 40
    assert "requirements.txt" in intake.dependency_files
    assert intake.declared_dependencies == frozenset({"numpy", "torch"})
    assert "train.py" in intake.entrypoint_candidates
    assert "notebooks/explore.ipynb" in intake.notebook_paths or "notebooks\\explore.ipynb" in intake.notebook_paths


# --- find_entrypoint_candidates ----------------------------------------------


def test_find_entrypoint_candidates_detects_main_guard(fake_paper_repo):
    candidates = find_entrypoint_candidates(fake_paper_repo)
    assert "train.py" in candidates


def test_find_entrypoint_candidates_negative_control_helper_excluded(fake_paper_repo):
    candidates = find_entrypoint_candidates(fake_paper_repo)
    assert "utils.py" not in candidates


# --- find_notebooks -----------------------------------------------------------


def test_find_notebooks_finds_ipynb(fake_paper_repo):
    notebooks = find_notebooks(fake_paper_repo)
    assert len(notebooks) == 1
    assert notebooks[0].endswith("explore.ipynb")


def test_find_notebooks_negative_control_no_notebooks(tmp_path):
    empty = tmp_path / "empty_repo"
    empty.mkdir()
    assert find_notebooks(empty) == ()


# --- parse_requirements_txt ---------------------------------------------------


def test_parse_requirements_txt_extracts_names_and_ignores_comments():
    content = "numpy==1.26.0\n# comment\ntorch>=2.0\n-e .\n\nrequests\n"
    assert parse_requirements_txt(content) == frozenset({"numpy", "torch", "requests"})


def test_parse_requirements_txt_negative_control_empty_file():
    assert parse_requirements_txt("") == frozenset()


# --- parse_setup_py ------------------------------------------------------------


def test_parse_setup_py_extracts_install_requires():
    content = """
from setuptools import setup
setup(
    name='foo',
    install_requires=['numpy>=1.20', 'pandas'],
)
"""
    assert parse_setup_py(content) == frozenset({"numpy", "pandas"})


def test_parse_setup_py_negative_control_no_install_requires():
    content = "from setuptools import setup\nsetup(name='foo')\n"
    assert parse_setup_py(content) == frozenset()


# --- parse_environment_yml ----------------------------------------------------


def test_parse_environment_yml_extracts_conda_and_pip_deps():
    content = """
name: myenv
dependencies:
  - python=3.10
  - numpy=1.26
  - pip:
    - torch==2.0
"""
    assert parse_environment_yml(content) == frozenset({"numpy", "torch"})


def test_parse_environment_yml_negative_control_invalid_yaml():
    assert parse_environment_yml("not: valid: yaml: [") == frozenset()


# --- detect_python_version_hint -----------------------------------------------


def test_detect_python_version_hint_from_setup_py():
    files = {"setup.py": "setup(python_requires='>=3.8,<3.11')"}
    assert detect_python_version_hint(files) == ">=3.8,<3.11"


def test_detect_python_version_hint_negative_control_no_hint():
    files = {"requirements.txt": "numpy\n"}
    assert detect_python_version_hint(files) is None


# --- parse_declared_dependencies (aggregation) -------------------------------


def test_parse_declared_dependencies_merges_all_sources():
    files = {
        "requirements.txt": "numpy\n",
        "environment.yml": "dependencies:\n  - torch\n",
    }
    assert parse_declared_dependencies(files) == frozenset({"numpy", "torch"})
