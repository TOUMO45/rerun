"""Tests for the Reproduction Passport signer (§6.3).

Includes a cross-check against `scripts/verify_passport.py`'s standalone
(intentionally duplicated) implementation, so the two can never silently
drift apart without a test failing.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

from app.services.passport import (
    MissingFieldError,
    PASSPORT_FIELD,
    compute_passport_hash,
    sign_certificate,
    verify_certificate,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
VERIFY_SCRIPT = REPO_ROOT / "scripts" / "verify_passport.py"


def _sample_certificate() -> dict:
    return {
        "repo_url": "https://github.com/example/paper-repo",
        "commit_sha": "abc123",
        "build_plan": {"python": "3.11", "steps": ["pip install -r requirements.txt"]},
        "full_log": "Cloning...\nInstalling...\nRunning train.py...\nDone.",
        "diffs": [{"attempt": 1, "status": "PASS", "diff": "--- a/x.py\n+++ b/x.py\n"}],
        "verdict": "RUNS_AFTER_REPAIR",
        "timestamp": "2026-09-19T00:00:00Z",
    }


def test_sign_certificate_adds_hash_field():
    cert = sign_certificate(_sample_certificate())
    assert PASSPORT_FIELD in cert
    assert len(cert[PASSPORT_FIELD]) == 64  # sha256 hex digest length


def test_verify_certificate_accepts_untampered_signature():
    cert = sign_certificate(_sample_certificate())
    assert verify_certificate(cert) is True


def test_verify_certificate_rejects_tampered_verdict():
    cert = sign_certificate(_sample_certificate())
    tampered = {**cert, "verdict": "RUNS_CLEAN"}  # flip a real failure into a clean pass
    assert verify_certificate(tampered) is False


def test_verify_certificate_rejects_tampered_log():
    cert = sign_certificate(_sample_certificate())
    tampered = {**cert, "full_log": cert["full_log"] + "\n(edited)"}
    assert verify_certificate(tampered) is False


def test_verify_certificate_rejects_missing_hash():
    cert = _sample_certificate()  # never signed
    assert verify_certificate(cert) is False


def test_hash_is_deterministic_regardless_of_field_order():
    cert_a = _sample_certificate()
    cert_b = {k: cert_a[k] for k in reversed(list(cert_a.keys()))}
    assert compute_passport_hash(cert_a) == compute_passport_hash(cert_b)


def test_compute_passport_hash_requires_all_canonical_fields():
    incomplete = _sample_certificate()
    del incomplete["verdict"]
    with pytest.raises(MissingFieldError):
        compute_passport_hash(incomplete)


# --- Cross-check against the standalone verifier script --------------------


def _load_standalone_module():
    spec = importlib.util.spec_from_file_location("verify_passport_standalone", VERIFY_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_standalone_script_hash_matches_backend_module():
    standalone = _load_standalone_module()
    cert = _sample_certificate()
    assert standalone.compute_passport_hash(cert) == compute_passport_hash(cert)


def test_standalone_script_cli_verifies_a_real_certificate(tmp_path):
    cert = sign_certificate(_sample_certificate())
    cert_path = tmp_path / "certificate.json"
    cert_path.write_text(json.dumps(cert), encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(VERIFY_SCRIPT), str(cert_path)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "PASSPORT VERIFIED" in result.stdout


def test_standalone_script_cli_detects_tampering(tmp_path):
    cert = sign_certificate(_sample_certificate())
    cert["verdict"] = "RUNS_CLEAN"  # tamper after signing
    cert_path = tmp_path / "tampered.json"
    cert_path.write_text(json.dumps(cert), encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(VERIFY_SCRIPT), str(cert_path)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert "MISMATCH" in result.stdout
