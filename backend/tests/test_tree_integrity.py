"""Step 5b (2026-09-24): clone integrity.

The TTPT live run's clone on this Windows host (global core.autocrlf=true)
turned every LF into CRLF; `run_ttpt.sh` then failed in the Linux sandbox and
was blamed on the repo. These tests use the REAL gate (the unit suite's
autouse double is bypassed by passing `tree_verifier=REAL`)."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from app.services import intake, tree_integrity
from app.services.cost_guard import CostGuard
from app.services.orchestrator import PipelineDeps, _collect_upload_files, is_our_fault, reason_code_of, run_pipeline
from app.services.passport import verify_certificate
from app.services.sandbox import SandboxRunResult, StepResult
from app.services.tree_integrity import HarnessIntegrityError, git_blob_sha1

# Captured at import time, before the conftest double is installed.
REAL = tree_integrity.verify_upload
SCRIPT = b"#!/usr/bin/env bash\nset -euo pipefail\necho ok\n"


def _git(*args, cwd=None, env=None):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, env=env)


@pytest.fixture
def autocrlf_true_env(tmp_path, monkeypatch):
    """A git config environment with core.autocrlf=true, like the Windows
    host where the bug was found — independent of this machine's settings."""
    cfg = tmp_path / "autocrlf.gitconfig"
    cfg.write_text("[core]\n\tautocrlf = true\n[user]\n\temail = t@e.st\n\tname = t\n", encoding="utf-8")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(cfg))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    return os.environ.copy()


@pytest.fixture
def upstream(tmp_path, autocrlf_true_env) -> tuple[Path, str]:
    """An 'upstream' repo whose committed blobs are LF-only."""
    src = tmp_path / "upstream"
    src.mkdir()
    _git("init", "-q", "-b", "main", cwd=src)
    _git("config", "core.autocrlf", "false", cwd=src)  # commit exact LF bytes
    _git("config", "uploadpack.allowReachableSHA1InWant", "true", cwd=src)
    (src / "run.sh").write_bytes(SCRIPT)
    (src / "train.py").write_bytes(b"import sys\nprint('x')\n")
    (src / "requirements.txt").write_bytes(b"numpy\n")
    _git("add", "-A", cwd=src)
    _git("commit", "-q", "-m", "x", cwd=src)
    sha = _git("rev-parse", "HEAD", cwd=src).stdout.decode().strip()
    return src, sha


def test_blob_sha_matches_git_hash_object(tmp_path):
    path = tmp_path / "f.sh"
    path.write_bytes(SCRIPT)
    expected = _git("hash-object", str(path)).stdout.decode().strip()
    assert git_blob_sha1(SCRIPT) == expected


def test_regression_lf_script_survives_a_clone_under_autocrlf_true(tmp_path, upstream):
    src, sha = upstream
    # Sanity: under this config, a plain checkout WOULD convert (the bug).
    plain = tmp_path / "plain"
    _git("clone", "-q", str(src), str(plain))
    assert b"\r\n" in (plain / "run.sh").read_bytes()

    dest = tmp_path / "rerun-clone"
    intake.clone_repo_at_commit(str(src), dest, sha)
    assert (dest / "run.sh").read_bytes() == SCRIPT  # byte-identical
    record = REAL(dest, sha, _collect_upload_files(dest))
    assert record.status == "verified" and record.files_checked == 3
    assert len(record.tree_sha) == 40


def test_regression_clone_repo_is_byte_exact_too(tmp_path, upstream):
    src, _ = upstream
    dest = tmp_path / "shallow"
    sha = intake.clone_repo(str(src), dest, shallow=False)
    assert (dest / "run.sh").read_bytes() == SCRIPT
    REAL(dest, sha, _collect_upload_files(dest))


def test_gate_rejects_a_converted_file_and_names_it(tmp_path, upstream):
    src, sha = upstream
    dest = tmp_path / "c"
    intake.clone_repo_at_commit(str(src), dest, sha)
    (dest / "run.sh").write_bytes(SCRIPT.replace(b"\n", b"\r\n"))
    with pytest.raises(HarnessIntegrityError) as excinfo:
        REAL(dest, sha, _collect_upload_files(dest))
    assert "run.sh" in str(excinfo.value)
    assert excinfo.value.record["mismatched"] == ["run.sh"]


def test_gate_rejects_a_file_not_in_the_commit(tmp_path, upstream):
    src, sha = upstream
    dest = tmp_path / "c"
    intake.clone_repo_at_commit(str(src), dest, sha)
    (dest / "injected.py").write_bytes(b"print('not committed')\n")
    with pytest.raises(HarnessIntegrityError) as excinfo:
        REAL(dest, sha, _collect_upload_files(dest))
    assert excinfo.value.record["not_in_commit"] == ["injected.py"]


def test_gate_excludes_paths_changed_by_approved_patches(tmp_path, upstream):
    src, sha = upstream
    dest = tmp_path / "c"
    intake.clone_repo_at_commit(str(src), dest, sha)
    (dest / "train.py").write_bytes(b"import sys\nprint('patched')\n")
    record = REAL(dest, sha, _collect_upload_files(dest), frozenset({"train.py"}))
    assert record.files_checked == 2 and record.excluded_patched == ["train.py"]


def test_gate_refuses_a_non_git_workdir(tmp_path):
    (tmp_path / "x.py").write_bytes(b"1\n")
    with pytest.raises(HarnessIntegrityError):
        REAL(tmp_path, "a" * 40, {"x.py": tmp_path / "x.py"})


# --- end to end ---------------------------------------------------------------------


class _Chat:
    def __init__(self, responses):
        self._responses = list(responses)

    def chat_completion(self, **kwargs):
        return self._responses.pop(0)


def _run(workdir, sha, sandbox_calls):
    def sandbox(**kwargs):
        sandbox_calls.append(kwargs)
        return SandboxRunResult(steps=(StepResult("run", 0, "ok", "", 1.0, 0.0),))

    deps = PipelineDeps(
        recon_client=_Chat([json.dumps({"entrypoint": "train.py", "confidence": 0.9})]),
        recon_model="r", repair_client=_Chat([]), repair_model="p", adjudicator_client=None, adjudicator_model=None,
        sandbox_api_key="k", sandbox_wall_clock_seconds=60, sandbox_runner=sandbox, tree_verifier=REAL,
    )
    intake_result = intake.parse_intake(workdir, sha)
    return run_pipeline(repo_url="https://example.com/r", commit_sha=sha, workdir=workdir, intake_result=intake_result,
                        deps=deps, cost_guard=CostGuard(daily_cost_ceiling_usd=100), run_id="integrity",
                        documented_command="bash run.sh")


def test_verified_tree_is_recorded_in_the_passport(tmp_path, upstream):
    src, sha = upstream
    dest = tmp_path / "c"
    intake.clone_repo_at_commit(str(src), dest, sha)
    calls = []
    result = _run(dest, sha, calls)
    assert result.verdict == "RUNS_CLEAN"
    cert = result.certificate()
    assert cert["bundle_version"] == 3
    assert cert["tree_integrity"]["status"] == "verified" and len(cert["tree_integrity"]["tree_sha"]) == 40
    assert verify_certificate(cert)
    tampered = dict(cert, tree_integrity={**cert["tree_integrity"], "status": "failed"})
    assert not verify_certificate(tampered)


def test_a_corrupted_tree_ends_invalid_harness_and_never_runs(tmp_path, upstream):
    src, sha = upstream
    dest = tmp_path / "c"
    intake.clone_repo_at_commit(str(src), dest, sha)
    (dest / "run.sh").write_bytes(SCRIPT.replace(b"\n", b"\r\n"))  # what the bug did
    calls = []
    result = _run(dest, sha, calls)
    assert result.verdict == "INVALID_HARNESS"
    assert reason_code_of(result.indeterminate_reason) == "INVALID_HARNESS"
    assert "run.sh" in result.indeterminate_reason
    assert is_our_fault(reason_code_of(result.indeterminate_reason))
    assert result.baseline == {"result": "NOT_RUN"}  # never FAILS
    assert calls == []  # nothing was uploaded
    cert = result.certificate()
    assert cert["tree_integrity"]["status"] == "failed" and cert["tree_integrity"]["mismatched"] == ["run.sh"]
    assert verify_certificate(cert)


def test_committed_v2_live_certificates_still_verify():
    root = Path(__file__).resolve().parents[2] / "runs"
    for name in ("live_run_gpt2_v4.json", "live_run_ttpt_v4.json"):
        cert = json.loads((root / name).read_text(encoding="utf-8"))["certificate"]
        assert cert["bundle_version"] == 2 and verify_certificate(cert)
