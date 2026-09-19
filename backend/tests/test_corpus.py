"""Tests for the Batch Lab corpus (§7).

Structural checks run everywhere, no network needed. A separate,
explicitly-marked "still reachable right now" check does hit the network
(git ls-remote against all 20 real URLs) and is skipped by default so the
normal test suite stays network-free — run it deliberately before an
actual Batch Lab run to catch a repo that's gone private/been deleted
since the corpus was assembled.
"""

from __future__ import annotations

import os
import subprocess

import pytest

from app.batch.corpus import CorpusError, load_corpus


def test_corpus_loads_with_exactly_twenty_entries():
    entries = load_corpus()
    assert len(entries) == 20


def test_corpus_entries_have_unique_names_and_urls():
    entries = load_corpus()
    names = [e.name for e in entries]
    urls = [e.repo_url for e in entries]
    assert len(names) == len(set(names))
    assert len(urls) == len(set(urls))


def test_corpus_entries_have_full_length_commit_shas():
    entries = load_corpus()
    for entry in entries:
        assert len(entry.commit_sha) == 40
        assert all(c in "0123456789abcdef" for c in entry.commit_sha)


def test_corpus_entries_all_use_https_github_urls():
    entries = load_corpus()
    for entry in entries:
        assert entry.repo_url.startswith("https://github.com/")


def test_corpus_negative_control_missing_file_raises():
    from pathlib import Path

    with pytest.raises(CorpusError):
        load_corpus(Path("/definitely/does/not/exist/corpus.yaml"))


def test_corpus_negative_control_duplicate_name_rejected(tmp_path):
    bad = tmp_path / "bad_corpus.yaml"
    fake_sha = "a" * 40
    bad.write_text(
        f"""
repos:
  - name: dup
    repo_url: https://github.com/a/a
    commit_sha: "{fake_sha}"
    entrypoint_hint: x
    selection_note: y
  - name: dup
    repo_url: https://github.com/b/b
    commit_sha: "{fake_sha}"
    entrypoint_hint: x
    selection_note: y
""",
        encoding="utf-8",
    )
    with pytest.raises(CorpusError, match="duplicate"):
        load_corpus(bad)


def test_corpus_spans_multiple_dependency_file_conventions():
    # §7: "prefer repos spanning multiple failure modes" — at minimum, the
    # corpus must not be uniform in how dependencies are declared (some
    # requirements.txt, some setup.py/pyproject.toml, some with nothing
    # declared at all), which is the first structural signal of diversity.
    entries = load_corpus()
    has_none = any(not e.dependency_files_observed for e in entries)
    has_requirements_txt = any("requirements.txt" in e.dependency_files_observed for e in entries)
    has_setup_py = any("setup.py" in e.dependency_files_observed for e in entries)
    assert has_none and has_requirements_txt and has_setup_py


@pytest.mark.skipif(
    not os.environ.get("RERUN_VERIFY_CORPUS_NETWORK"),
    reason="Network-dependent corpus freshness check — set RERUN_VERIFY_CORPUS_NETWORK=1 to run it deliberately",
)
def test_every_corpus_repo_is_still_reachable():
    entries = load_corpus()
    unreachable = []
    for entry in entries:
        result = subprocess.run(
            ["git", "ls-remote", "--exit-code", entry.repo_url, "HEAD"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode != 0:
            unreachable.append(entry.name)
    assert not unreachable, f"corpus entries no longer reachable: {unreachable}"
