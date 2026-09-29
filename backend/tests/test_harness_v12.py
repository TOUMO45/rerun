"""harness-v1.2 (2026-09-28): no silent SDK timeouts; the sandbox transport
timeout scales with the upload archive; a pre-declared upload cap
(UPLOAD_TOO_LARGE). Exposed by corpus-v1 on harness-v1.1: SearchFair (30.6 MB)
and ExpressGNN (125.6 MB) timed out on contree_sdk's default 10 s transport
timeout, identically on every attempt."""

from __future__ import annotations

import importlib.util
import json
import os
import types
from datetime import timedelta
from pathlib import Path

import pytest

from app.services import model_client, sandbox, tavily, timeouts
from app.services.cost_guard import CostGuard
from app.services.intake import RepoIntake
from app.services.orchestrator import UPLOAD_TOO_LARGE, PipelineDeps, is_our_fault, reason_code_of, run_pipeline
from app.services.sandbox import SandboxRunResult, StepResult

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    "archive_mb, expected_s",
    [(0, 60.0), (0.2, 60.0), (13.3, 60.0), (30.6, 60.6), (125.6, 155.6), (150, 180.0), (500, 530.0)],
)
def test_transport_timeout_scales_with_the_archive_with_a_floor(archive_mb, expected_s):
    assert timeouts.sandbox_transport_timeout(int(archive_mb * 1_000_000)) == pytest.approx(expected_s)


def test_transport_timeout_is_never_the_silent_sdk_default():
    from contree_sdk.config import ContreeConfig

    assert ContreeConfig.__dataclass_fields__["transport_timeout"].default == 10.0  # the default that bit us
    assert min(timeouts.sandbox_transport_timeout(n) for n in (0, 10**6, 10**8)) >= timeouts.SANDBOX_TRANSPORT_FLOOR_S > 10.0


class _Captured:
    configs: list = []


def _fake_contree():
    class _Result:
        exit_code, stdout, stderr, cost = 0, "ok", "", 0.0
        elapsed_time = timedelta(seconds=1)

    class _Image:
        uuid = None

        def __init__(self, result=None):
            self.result, self.exit_code = result, (0 if result else None)

        def apply_files(self, files):
            return _Image()

        def run(self, shell, timeout, disposable, preserve_env=False):
            return _Image(_Result())

        def wait(self):
            return self

    class _Client:
        def __init__(self, config):
            _Captured.configs.append(config)
            self.images = types.SimpleNamespace(docker=lambda ref: _Image())

    return _Client


def test_real_runner_configures_the_sdk_client_from_the_archive_size(monkeypatch):
    _Captured.configs = []
    monkeypatch.setattr(sandbox, "ContreeSync", _fake_contree())
    big = {"data.bin": os.urandom(40_000_000), "run.sh": b"#!/bin/sh\n"}
    sandbox.run_build_and_execute(api_key="k", base_image="python:3.11-slim", install_commands=[],
                                  execute_command="./run.sh", wall_clock_seconds=60, upload_files=big,
                                  file_modes={"run.sh": "100755"})
    config = _Captured.configs[-1]
    archive = len(sandbox.build_upload_archive(big, {"run.sh": "100755"}, mtime=0)[0])
    assert config.transport_timeout == pytest.approx(timeouts.sandbox_transport_timeout(archive))
    assert config.transport_timeout > 60
    assert config.operation_timeout == timeouts.SANDBOX_OPERATION_S


def test_model_client_timeouts_are_explicit():
    client = model_client.NebiusChatClient(api_key="k", base_url="https://api.example/v1")._client()
    t = client.timeout
    assert (t.connect, t.read, t.write, t.pool) == (
        timeouts.MODEL_CONNECT_S, timeouts.MODEL_READ_S, timeouts.MODEL_WRITE_S, timeouts.MODEL_POOL_S)
    assert client.max_retries == 0


def test_tavily_search_timeout_is_explicit():
    seen = {}

    class _Client:
        def search(self, query, **kwargs):
            seen.update(kwargs)
            return {"results": []}

    tavily.fetch_context(_Client(), "DEP_MISSING", "ModuleNotFoundError: No module named 'x'")
    assert seen["timeout"] == timeouts.TAVILY_S


# --- UPLOAD_TOO_LARGE -------------------------------------------------------------


def test_archive_over_the_cap_is_refused_before_any_network_call(monkeypatch):
    _Captured.configs = []
    monkeypatch.setattr(sandbox, "ContreeSync", _fake_contree())
    monkeypatch.setattr(sandbox, "UPLOAD_CAP_BYTES", 1_000_000)
    with pytest.raises(sandbox.UploadTooLargeError) as excinfo:
        sandbox.run_build_and_execute(api_key="k", base_image="python:3.11-slim", install_commands=[],
                                      execute_command="true", wall_clock_seconds=60,
                                      upload_files={"big.bin": b"x" * 2_000_000})
    assert excinfo.value.archive_bytes > excinfo.value.cap_bytes == 1_000_000
    assert _Captured.configs == []  # no client was ever created


def test_upload_too_large_is_a_harness_limitation_verdict(tmp_path):
    class _Chat:
        def chat_completion(self, **kwargs):
            return json.dumps({"entrypoint": "train.py", "confidence": 0.9})

    def runner(**kwargs):
        raise sandbox.UploadTooLargeError(600_000_000, 500_000_000)

    (tmp_path / "train.py").write_text("print(1)\n", encoding="utf-8")
    intake = RepoIntake(tmp_path, "a" * 40, {}, frozenset(), (), ("train.py",), None)
    deps = PipelineDeps(recon_client=_Chat(), recon_model="r", repair_client=_Chat(), repair_model="p",
                        adjudicator_client=None, adjudicator_model=None, sandbox_api_key="k",
                        sandbox_wall_clock_seconds=60, sandbox_runner=runner)
    result = run_pipeline(repo_url="https://example.com/r", commit_sha="a" * 40, workdir=tmp_path, intake_result=intake,
                          deps=deps, cost_guard=CostGuard(daily_cost_ceiling_usd=10), run_id="big",
                          documented_command="python train.py")
    assert result.verdict == UPLOAD_TOO_LARGE
    assert reason_code_of(result.indeterminate_reason) == UPLOAD_TOO_LARGE and is_our_fault(UPLOAD_TOO_LARGE)
    assert result.baseline["result"] == "NOT_RUN" and result.taxonomy_code is None


def test_batch_summary_reports_upload_too_large_separately():
    spec = importlib.util.spec_from_file_location("b", ROOT / "scripts" / "run_corpus_v1_batch.py")
    batch = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(batch)

    def rec(i, verdict, baseline):
        return {"corpus_entry": {"name": f"e{i}"}, "batch": {"entry_id": i, "category": "PRIMARY", "harness_tag": "t", "harness_commit": "c"},
                "result": {"verdict": verdict, "taxonomy_code": None, "reason_code": None},
                "certificate": {"baseline": {"result": baseline}, "recovery": False, "tree_integrity": {"status": "verified"}},
                "repair_mode": "deterministic", "cost_guard": {"spent_usd": 0.0}}

    p = batch.summarize([rec(1, "UPLOAD_TOO_LARGE", "NOT_RUN"), rec(2, "BLOCKED", "FAILS")])["primary"]
    assert p["upload_too_large"] == 1 and p["n_measured"] == 1 and p["headline"] == "PRIMARY: 0/1 of 2"


# --- LIVE: a ~150 MB archive through the real client -------------------------------


@pytest.mark.skipif(os.environ.get("RERUN_LIVE_UPLOAD") != "1", reason="live Nebius upload; set RERUN_LIVE_UPLOAD=1")
def test_live_upload_at_the_cap_through_the_real_client():
    if not sandbox.UPLOAD_CAP_BYTES:
        pytest.skip("no upload cap set yet")
    spec = importlib.util.spec_from_file_location("smoke_upload", ROOT / "scripts" / "smoke_upload.py")
    smoke = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(smoke)
    cap_mb = int(sandbox.UPLOAD_CAP_BYTES // 1_000_000) - 1
    record = smoke.upload_once(cap_mb)
    print(json.dumps(record))
    assert record["ok"], record
    assert cap_mb * 1_000_000 < record["archive_bytes"] <= sandbox.UPLOAD_CAP_BYTES


# --- extract step: archive deleted BEFORE the manifest check (v1.2 probe amendment) ---


def test_extract_command_deletes_the_archive_before_the_check():
    cmd = sandbox.EXTRACT_COMMAND
    assert cmd.index(f"rm -f {sandbox.UPLOAD_ARCHIVE}") < cmd.index("verify.py") < cmd.index(f"rm -rf {sandbox.UPLOAD_DIR}")


def _v11():
    spec = importlib.util.spec_from_file_location("t11", Path(__file__).with_name("test_harness_v11.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.skipif(not _v11()._wsl_available(), reason="needs a Linux filesystem (WSL kali-linux or POSIX host)")
def test_check_runs_on_the_extracted_tree_after_the_archive_is_gone():
    v11 = _v11()
    archive, _ = sandbox.build_upload_archive({"run.sh": b"#!/bin/sh\necho hi\n", "a/b.txt": b"x\n"},
                                              {"run.sh": "100755", "a/b.txt": "100644"})
    out = v11._run_extract_in_linux(archive, f"test ! -e {sandbox.UPLOAD_ARCHIVE} && ./run.sh")
    assert out.returncode == 0, out.stderr
    assert "RERUN_UPLOAD_VERIFIED 2 file(s)" in out.stdout and "hi" in out.stdout

    def tamper(member, data):
        return member, (b"y\n" if member.name == "a/b.txt" else data)

    bad = v11._run_extract_in_linux(v11._retar(archive, tamper), "true")
    assert bad.returncode == sandbox.UPLOAD_MISMATCH_EXIT and "a/b.txt (content)" in bad.stderr


def test_operation_timeout_is_passed_explicitly_not_left_to_the_sdk_default(monkeypatch):
    """SANDBOX_OPERATION_S equals the SDK default (1000 s), so the value alone
    can't show it was set: capture the keyword arguments instead."""
    seen = {}
    real = sandbox.ContreeConfig

    def recorder(**kwargs):
        seen.update(kwargs)
        return real(**kwargs)

    monkeypatch.setattr(sandbox, "ContreeConfig", recorder)
    monkeypatch.setattr(sandbox, "ContreeSync", _fake_contree())
    sandbox.run_build_and_execute(api_key="k", base_image="python:3.11-slim", install_commands=[],
                                  execute_command="true", wall_clock_seconds=60, upload_files={"a.txt": b"a"})
    assert seen["operation_timeout"] == timeouts.SANDBOX_OPERATION_S
    assert "transport_timeout" in seen


@pytest.mark.skipif(not _v11()._wsl_available(), reason="needs a Linux filesystem (WSL kali-linux or POSIX host)")
def test_probe_payload_runs_under_sh_after_the_real_extraction():
    """Regression: the first amendment-1 probe run was voided because the
    payload's unquoted `file(s)` is a sh syntax error."""
    spec = importlib.util.spec_from_file_location("smoke_upload", ROOT / "scripts" / "smoke_upload.py")
    smoke = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(smoke)
    files = smoke.synthetic_files(1)
    modes = {p: ("100755" if p == "run.sh" else "100644") for p in files}
    archive, _ = sandbox.build_upload_archive(files, modes)
    out = _v11()._run_extract_in_linux(archive, "./run.sh")
    assert out.returncode == 0, out.stderr
    assert "UPLOAD_OK 1 files" in out.stdout
    assert smoke._field(out.stdout, "EXTRACTED_BYTES") >= 1_000_000
    assert smoke._field(out.stdout, "DF", whole=True)
