"""harness-v1.3.4, D-20: on the download route a patched file travels as an overlay and the integrity check accepts it.

The sandbox's own scripts (overlay.py, verify.py) run here for real, in a temp directory, against a "fetched" tree written by
the test (the fetch itself needs GitHub and is verified live at the seal)."""

from __future__ import annotations

import io
import json
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

from app.services import sandbox, sandbox_limits
from app.services.sandbox import UPLOAD_DIR, UPLOAD_MISMATCH_EXIT, build_upload_archive

SOURCE = sandbox_limits.DownloadSource.from_repo_url("https://github.com/o/r", "a" * 40)
ORIGINAL = b"def psnr(a, b):\n    from skimage.measure import compare_psnr\n    return compare_psnr(a, b)\n"
PATCHED = b"def psnr(a, b):\n    from skimage.metrics import peak_signal_noise_ratio as compare_psnr\n    return compare_psnr(a, b)\n"


def _members(archive: bytes) -> dict[str, bytes]:
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        return {m.name: tar.extractfile(m).read() for m in tar.getmembers() if m.isfile()}


def _sandbox_like(tmp_path: Path, archive: bytes, fetched: dict[str, bytes]) -> Path:
    """Extract the manifest-only archive the way the sandbox does, then write what fetch.py would have fetched."""
    root = tmp_path / "sbx"
    root.mkdir(parents=True)
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        tar.extractall(root)
    for rel, data in fetched.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_bytes(data)
    return root


def _run(root: Path, script: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, f"{UPLOAD_DIR}/{script}"], cwd=root, capture_output=True, text=True)


def test_the_manifest_only_archive_carries_the_patched_file_as_an_overlay():
    archive, manifest = build_upload_archive({"utils.py": PATCHED, "train.py": b"x = 1\n"}, {"utils.py": "100644"},
                                             manifest_only=True, download_source=SOURCE, overlay_paths=frozenset({"utils.py"}))
    members = _members(archive)
    assert f"{UPLOAD_DIR}/overlay/utils.py" in members and members[f"{UPLOAD_DIR}/overlay/utils.py"] == PATCHED
    assert "train.py" not in members and "utils.py" not in members  # still manifest-only for everything else
    overlay = json.loads(members[f"{UPLOAD_DIR}/overlay.json"])
    assert list(overlay) == ["utils.py"] and overlay["utils.py"][0] == sandbox._blob_sha1(PATCHED)  # post-patch hash
    assert manifest["utils.py"][0] == sandbox._blob_sha1(PATCHED) and manifest["train.py"][0] == sandbox._blob_sha1(b"x = 1\n")
    assert f"{UPLOAD_DIR}/overlay.py" in members


def test_overlay_then_verify_accepts_the_patched_tree_that_used_to_fail(tmp_path):
    """Entry 8 of the v1.3.3 smoke gate: the sandbox fetched the original utils.py, the manifest held the patched blob, exit 97."""
    archive, _ = build_upload_archive({"utils.py": PATCHED, "train.py": b"x = 1\n"}, {"utils.py": "100644", "train.py": "100644"},
                                      manifest_only=True, download_source=SOURCE, overlay_paths=frozenset({"utils.py"}))
    root = _sandbox_like(tmp_path, archive, {"utils.py": ORIGINAL, "train.py": b"x = 1\n"})  # what git fetched: the ORIGINAL
    without = _run(root, "verify.py")
    assert without.returncode == UPLOAD_MISMATCH_EXIT and "utils.py (content)" in without.stderr  # the v1.3.3 failure, reproduced
    applied = _run(root, "overlay.py")
    assert applied.returncode == 0 and "RERUN_OVERLAY_APPLIED 1 file(s)" in applied.stdout
    assert (root / "utils.py").read_bytes() == PATCHED
    verified = _run(root, "verify.py")
    assert verified.returncode == 0, verified.stderr
    assert "RERUN_UPLOAD_VERIFIED 2 file(s) (1 original against the committed blob, 1 overlay against the post-patch blob)" in verified.stdout


def test_a_tampered_overlay_file_or_a_tampered_original_still_fails(tmp_path):
    archive, _ = build_upload_archive({"utils.py": PATCHED, "train.py": b"x = 1\n"}, None, manifest_only=True,
                                      download_source=SOURCE, overlay_paths=frozenset({"utils.py"}))
    root = _sandbox_like(tmp_path, archive, {"utils.py": ORIGINAL, "train.py": b"x = 2\n"})  # train.py differs from the manifest
    assert _run(root, "overlay.py").returncode == 0
    bad = _run(root, "verify.py")
    assert bad.returncode == UPLOAD_MISMATCH_EXIT and "train.py (content)" in bad.stderr
    root2 = _sandbox_like(tmp_path / "b", archive, {"utils.py": ORIGINAL, "train.py": b"x = 1\n"})
    (root2 / UPLOAD_DIR / "overlay" / "utils.py").write_bytes(PATCHED + b"# tampered\n")
    assert _run(root2, "overlay.py").returncode == 0
    bad2 = _run(root2, "verify.py")
    assert bad2.returncode == UPLOAD_MISMATCH_EXIT and "utils.py (content)" in bad2.stderr


def test_an_overlay_file_missing_from_the_archive_is_refused_at_build_time_and_in_the_sandbox(tmp_path):
    with pytest.raises(sandbox.UploadIntegrityError, match="overlay path"):
        build_upload_archive({"train.py": b"x\n"}, None, manifest_only=True, download_source=SOURCE, overlay_paths=frozenset({"ghost.py"}))
    archive, _ = build_upload_archive({"utils.py": PATCHED}, None, manifest_only=True, download_source=SOURCE, overlay_paths=frozenset({"utils.py"}))
    root = _sandbox_like(tmp_path, archive, {"utils.py": ORIGINAL})
    (root / UPLOAD_DIR / "overlay" / "utils.py").unlink()
    missing = _run(root, "overlay.py")
    assert missing.returncode == UPLOAD_MISMATCH_EXIT and "RERUN_OVERLAY_MISSING utils.py" in missing.stderr


def test_the_upload_route_is_unchanged_and_the_runner_passes_the_patched_paths(monkeypatch):
    seen = {}

    def fake_run_once(**kw):
        seen.update(kw)
        return sandbox.SandboxRunResult(steps=(sandbox.StepResult("x", 0, "", "", 0.0, 0.0),))

    monkeypatch.setattr(sandbox, "_run_once", fake_run_once)
    monkeypatch.setattr(sandbox, "UPLOAD_CAP_BYTES", 20)
    sandbox.run_build_and_execute(api_key="k", base_image="i", install_commands=[], execute_command="true", wall_clock_seconds=60,
                                  upload_files={"utils.py": PATCHED, "big.bin": b"z" * 100}, download_source=SOURCE,
                                  overlay_paths=frozenset({"utils.py"}))
    members = _members(seen["archive"])
    assert f"{UPLOAD_DIR}/overlay/utils.py" in members and "big.bin" not in members
    assert "overlay.py" in seen["extract_command"] and seen["extract_command"].index("fetch.py") < seen["extract_command"].index("overlay.py") < seen["extract_command"].index("verify.py")


def test_the_orchestrator_hands_its_patched_paths_to_the_runner(tmp_path):
    """End to end with fakes: after a gate-approved patch, the re-execution's runner call carries overlay_paths={'train.py'}."""
    import json as _json
    import subprocess as _sp

    from app.services.cost_guard import CostGuard
    from app.services.intake import RepoIntake
    from app.services.orchestrator import PipelineDeps, run_pipeline

    (tmp_path / "train.py").write_text("import os\nraise RuntimeError('boom')\n", encoding="utf-8")
    _sp.run(["git", "init", "-q"], cwd=tmp_path, check=True, capture_output=True)
    for k, v in (("core.autocrlf", "false"), ("core.eol", "lf")):
        _sp.run(["git", "config", k, v], cwd=tmp_path, check=True, capture_output=True)
    calls = []

    def runner(**kw):
        calls.append(kw)
        if len(calls) == 1:
            return sandbox.SandboxRunResult(steps=(sandbox.StepResult("python train.py", 1, "", "RuntimeError: boom", 1.0, 0.0),))
        return sandbox.SandboxRunResult(steps=(sandbox.StepResult("python train.py", 0, "ok", "", 1.0, 0.0),))

    class Chat:
        def __init__(self, r):
            self.r = [_json.dumps(x) for x in r]

        def chat_completion(self, **kw):
            return self.r.pop(0)

    fix = {"file_edits": [{"path": "train.py", "old": "raise RuntimeError('boom')\n", "new": "print('ok')\n"}], "cited_sources": [],
           "reason_no_citation": "no web results were given", "explanation": "x"}
    deps = PipelineDeps(recon_client=Chat([{"entrypoint": "train.py", "confidence": 0.9}]), recon_model="r", repair_client=Chat([fix]),
                        repair_model="p", adjudicator_client=None, adjudicator_model=None, sandbox_api_key="k", sandbox_wall_clock_seconds=100,
                        sandbox_runner=runner, smoke_seconds=0)
    intake = RepoIntake(tmp_path, "a" * 40, {}, frozenset(), (), ("train.py",), None)
    result = run_pipeline(repo_url="https://example.com/r", commit_sha="a" * 40, workdir=tmp_path, intake_result=intake, deps=deps,
                          cost_guard=CostGuard(daily_cost_ceiling_usd=100), run_id="ov")
    assert result.verdict == "RUNS_AFTER_REPAIR", result.full_log
    assert calls[0]["overlay_paths"] == frozenset() and calls[1]["overlay_paths"] == frozenset({"train.py"})
