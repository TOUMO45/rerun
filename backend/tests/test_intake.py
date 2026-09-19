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
    RepoNotFoundError,
    clone_repo,
    clone_repo_at_commit,
    detect_python_version_hint,
    find_dependency_files,
    find_entrypoint_candidates,
    find_notebooks,
    parse_declared_dependencies,
    parse_environment_yml,
    parse_requirements_txt,
    parse_setup_py,
    repo_has_python_code,
    run_intake,
    validate_repo_accessible,
)


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


# --- clone_repo_at_commit: pins to a SPECIFIC commit, not just HEAD ---------


def test_clone_repo_at_commit_pins_to_an_older_commit_not_head(fake_paper_repo, tmp_path):
    # fake_paper_repo has one commit at fixture-creation time; capture its
    # SHA, then add a SECOND commit that changes train.py, so cloning "at
    # the first commit" is verifiably different from cloning HEAD.
    first_sha = subprocess.run(
        ["git", "-C", str(fake_paper_repo), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()

    (fake_paper_repo / "train.py").write_text("def main():\n    return 'CHANGED AFTER PINNED COMMIT'\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=fake_paper_repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "second commit"], cwd=fake_paper_repo, check=True, capture_output=True)

    dest = tmp_path / "pinned_clone"
    resolved_sha = clone_repo_at_commit(str(fake_paper_repo), dest, first_sha)

    assert resolved_sha == first_sha
    assert "CHANGED AFTER PINNED COMMIT" not in (dest / "train.py").read_text(encoding="utf-8")


def test_clone_repo_at_commit_negative_control_head_differs_from_pinned(fake_paper_repo, tmp_path):
    first_sha = subprocess.run(
        ["git", "-C", str(fake_paper_repo), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()

    (fake_paper_repo / "train.py").write_text("def main():\n    return 'HEAD VERSION'\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=fake_paper_repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "second commit"], cwd=fake_paper_repo, check=True, capture_output=True)

    head_sha = clone_repo(str(fake_paper_repo), tmp_path / "head_clone", shallow=False)
    pinned_sha = clone_repo_at_commit(str(fake_paper_repo), tmp_path / "pinned_clone", first_sha)

    assert head_sha != pinned_sha
    assert pinned_sha == first_sha


def test_clone_repo_at_commit_raises_intake_error_for_bad_commit(fake_paper_repo, tmp_path):
    with pytest.raises(IntakeError):
        clone_repo_at_commit(str(fake_paper_repo), tmp_path / "bad_commit_clone", "a" * 40)


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


# --- validate_repo_accessible (S1 pre-flight, real local git, no network) ---


def test_validate_repo_accessible_accepts_reachable_repo(fake_paper_repo):
    validate_repo_accessible(str(fake_paper_repo))  # must not raise


def test_validate_repo_accessible_negative_control_missing_repo(tmp_path):
    with pytest.raises(RepoNotFoundError):
        validate_repo_accessible(str(tmp_path / "no_such_repo_here"))


# --- repo_has_python_code -----------------------------------------------------


def test_repo_has_python_code_detects_py_files(fake_paper_repo):
    assert repo_has_python_code(fake_paper_repo) is True


def test_repo_has_python_code_negative_control_empty_repo(tmp_path):
    empty = tmp_path / "empty_repo"
    empty.mkdir()
    assert repo_has_python_code(empty) is False
