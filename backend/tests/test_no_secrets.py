"""No committed record, log or fixture holds a secret-shaped value (owner, 2026-10-10, after both dispatches of the v1.10 seal workflow carried a key into
their records). The scanner prints a pattern name and four characters, never a value. Part of the final gate with `reports/scan_history_for_secrets.py`
(every ref, tag, stash and reflog)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _scanner():
    spec = importlib.util.spec_from_file_location("scan_history_for_secrets", ROOT / "reports" / "scan_history_for_secrets.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def scanner():
    return _scanner()


def test_no_tracked_file_holds_a_secret_shaped_value(scanner):
    found = scanner.scan_tracked()
    assert not found, f"secret-shaped strings in tracked files (path, pattern, first four characters): {found}"


def test_no_commit_in_head_s_history_holds_a_secret_shaped_value(scanner):
    found = [(sha[:7], path, name, prefix) for sha, path, name, prefix in scanner.scan_history(head_only=True)]
    assert not found, f"secret-shaped strings in HEAD's history (blob, path, pattern, first four characters): {found}"


# The samples are built at run time, so this file holds no secret-shaped literal itself.
_ALNUM = "Ab3dE5gH7jK9mN1pQ2rS4tU6vW8xY0z" * 3


@pytest.mark.parametrize("sample, pattern", [
    ("tvly-" + "dev-" + _ALNUM[:32], "tavily key"),
    ("v1" + ".Cm" + _ALNUM[:60], "nebius static key"),
    ("Bearer " + _ALNUM[:40], "bearer token"),
    ("nvapi-" + _ALNUM[:40], "nvidia api key"),
    ("hf" + "_" + _ALNUM[:34], "hugging face token"),
    ("gh" + "p_" + _ALNUM[:36], "github token"),
    ("-----BEGIN RSA " + "PRIVATE KEY-----", "private key block"),
    ("api_key = '" + _ALNUM[:30] + "'", "assignment of a long literal to a secret-named variable"),
])
def test_each_pattern_catches_its_shape(scanner, sample, pattern):
    assert pattern in [name for name, _ in scanner.scan_text(("x " + sample + " y").encode())]


@pytest.mark.parametrize("sample", [
    "tvly-[REDACTED: the TAVILY_API_KEY value, replaced before this copy was committed to main]",
    "v1.[REDACTED: the NEBIUS_API_KEY value]",
    "api_key = 'sk-" + "fake-key-for-the-unit-tests-xx'",
])
def test_a_redaction_note_or_a_placeholder_is_not_a_finding(scanner, sample):
    assert scanner.scan_text(sample.encode()) == []


def test_the_scanner_never_returns_more_than_four_characters_of_a_match(scanner):
    found = scanner.scan_text(("tvly-" + "dev-" + _ALNUM[:40]).encode())
    assert found and all(len(prefix) == 4 for _, prefix in found)
