"""harness-v1.1 fixes (2026-09-28), each exposed by the corpus-v1 batch on
harness-v1:

(a) infrastructure resilience — every external failure (Nebius sandbox, model
    API, GitHub, package index, git host) is retried with bounded backoff and
    then ends the run as INFRA_ERROR (RERUN's fault), never as a verdict
    about the repository; one-archive upload with a post-extraction check;
(m) git file modes survive the upload (an executable ./run.sh stays
    executable), verified after extraction;
(b) import -> distribution from the cited table, hardware variants excluded,
    mappings recorded in the certificate;
(c) classifier fallback evidence skips pip noise and prefers the exception.
"""

from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import tarfile
import types
from datetime import date, timedelta
from pathlib import Path

import httpx
import openai
import pytest
from contree_sdk.sdk.exceptions.api import ApiStatusCodeError, ApiTimeoutError, ForbiddenError

from app.services import (
    classifier,
    dep_resolver,
    import_names,
    infra,
    intake,
    model_client,
    sandbox,
    time_machine,
    tree_integrity,
)
from app.services.cost_guard import CostGuard
from app.services.intake import RepoIntake
from app.services.orchestrator import PipelineDeps, is_our_fault, reason_code_of, run_pipeline
from app.services.sandbox import SandboxError, SandboxRunResult, StepResult
from app.services.time_machine import EraDate, LockResult
# Bound at import (collection) time, before conftest's autouse double replaces it.
from app.services.tree_integrity import verify_upload as REAL_VERIFY_UPLOAD

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    slept = []
    for module in (model_client, sandbox, time_machine, intake):
        monkeypatch.setattr(module, "_sleep", lambda s: slept.append(s))
    monkeypatch.setattr(infra, "sleep_fn", lambda s: slept.append(s))
    return slept


# --- retry policy -----------------------------------------------------------------


def test_retry_call_backs_off_then_succeeds():
    calls, slept = [], []

    def fn():
        calls.append(1)
        if len(calls) < 3:
            raise TimeoutError("slow")
        return "ok"

    assert infra.retry_call(fn, source="x", is_transient=lambda e: isinstance(e, TimeoutError), sleep=slept.append) == "ok"
    assert slept == [2.0, 4.0]


def test_retry_call_persistent_failure_becomes_infra_error_after_bounded_attempts():
    slept = []
    with pytest.raises(infra.InfraError) as excinfo:
        infra.retry_call(lambda: (_ for _ in ()).throw(TimeoutError("down")), source="sandbox",
                         is_transient=lambda e: True, sleep=slept.append)
    assert excinfo.value.attempts == infra.DEFAULT_ATTEMPTS and excinfo.value.source == "sandbox"
    assert slept == infra.backoff_delays() == [2.0, 4.0, 8.0]


def test_retry_call_external_is_immediate_and_other_errors_propagate():
    with pytest.raises(infra.InfraError):
        infra.retry_call(lambda: (_ for _ in ()).throw(PermissionError("403")), source="x",
                         is_transient=lambda e: False, is_external=lambda e: True, sleep=lambda s: None)
    with pytest.raises(ValueError):  # a RERUN bug is not an outage
        infra.retry_call(lambda: (_ for _ in ()).throw(ValueError("bug")), source="x",
                         is_transient=lambda e: False, sleep=lambda s: None)


def test_backoff_is_capped():
    assert infra.backoff_delays(8, 2.0, 30.0) == [2.0, 4.0, 8.0, 16.0, 30.0, 30.0, 30.0]


# --- every verdict-emitting path with an injected external failure --------------

_REQ = httpx.Request("POST", "https://api.tokenfactory.example/v1/chat/completions")


def _timeout():
    return openai.APITimeoutError(request=_REQ)


class _Chat:
    """Model client: `script` is a list of replies or exceptions (raised)."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = 0

    def chat_completion(self, **kwargs):
        self.calls += 1
        item = self.script.pop(0) if len(self.script) > 1 else self.script[0]
        if isinstance(item, BaseException):
            raise item
        return item


class _Sandbox:
    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        item = self.results.pop(0) if len(self.results) > 1 else self.results[0]
        if isinstance(item, BaseException):
            raise item
        return item


def _fail(stderr="ModuleNotFoundError: No module named 'widget'"):
    return SandboxRunResult(steps=(StepResult("python train.py", 1, "", stderr, 1.0, 0.0),))


def _ok():
    return SandboxRunResult(steps=(StepResult("python train.py", 0, "ok", "", 1.0, 0.0),))


RECON_OK = json.dumps({"entrypoint": "train.py", "confidence": 0.9})
DECLINE = json.dumps({"code_diff": None, "env_delta": [], "explanation": "none"})


def _pipeline(tmp_path, *, recon=None, planner=None, repair=None, adjudicator=None, sandbox_runner=None,
               http_get=None, lock_compiler=None, repo_url="https://example.com/r", tavily_client=None):
    (tmp_path / "requirements.txt").write_text("\n", encoding="utf-8")
    (tmp_path / "train.py").write_text("import widget\n", encoding="utf-8")
    intake_result = RepoIntake(tmp_path, "a" * 40, {"requirements.txt": "\n"}, frozenset(), (), ("train.py",), None)
    deps = PipelineDeps(
        recon_client=recon or _Chat([RECON_OK]),
        recon_model="r",
        repair_client=repair or _Chat([DECLINE]),
        repair_model="p",
        adjudicator_client=adjudicator,
        adjudicator_model="a",
        planner_client=planner,
        planner_model="pl",
        sandbox_api_key="k",
        sandbox_wall_clock_seconds=60,
        sandbox_runner=sandbox_runner or _Sandbox([_fail()]),
        max_attempts=1,
        http_get=http_get,
        lock_compiler=lock_compiler or (lambda *a: LockResult(False, error="lock disabled")),
        tavily_client=tavily_client,
    )
    return run_pipeline(repo_url=repo_url, commit_sha="a" * 40, workdir=tmp_path, intake_result=intake_result,
                        deps=deps, cost_guard=CostGuard(daily_cost_ceiling_usd=100), run_id="infra",
                        documented_command="python train.py")


def _assert_infra(result, source):
    assert result.verdict == infra.INFRA_ERROR, result.full_log
    code = reason_code_of(result.indeterminate_reason)
    assert code.startswith(f"INFRA_ERROR:{source}"), code
    assert is_our_fault(code)
    assert result.verdict != "NOT_ATTEMPTABLE" and result.taxonomy_code is None


def test_path_sandbox_api_failure_at_baseline_is_infra_error_not_not_attemptable(tmp_path):
    result = _pipeline(tmp_path, sandbox_runner=_Sandbox([sandbox.SandboxInfraError("ApiTimeoutError(read)", attempts=4)]))
    _assert_infra(result, "sandbox")
    assert result.baseline["result"] == "NOT_RUN"


def test_path_real_sandbox_runner_retries_upload_timeouts_then_infra_error(tmp_path, monkeypatch, _no_sleep):
    plan = types.SimpleNamespace(uploads=0, fail_uploads=99, commands=[])
    monkeypatch.setattr(sandbox, "ContreeSync", _fake_contree(plan))
    result = _pipeline(tmp_path, sandbox_runner=sandbox.run_build_and_execute)
    _assert_infra(result, "sandbox")
    assert plan.uploads == infra.DEFAULT_ATTEMPTS  # one archive per attempt, not one POST per file
    assert _no_sleep == [2.0, 4.0, 8.0]


def test_path_real_sandbox_runner_recovers_from_a_transient_upload_timeout(tmp_path, monkeypatch):
    plan = types.SimpleNamespace(uploads=0, fail_uploads=1, commands=[])
    monkeypatch.setattr(sandbox, "ContreeSync", _fake_contree(plan))
    result = _pipeline(tmp_path, sandbox_runner=sandbox.run_build_and_execute)
    assert result.verdict != infra.INFRA_ERROR
    assert result.baseline["result"] == "RUNS_CLEAN"
    assert plan.commands[0] == sandbox.EXTRACT_COMMAND  # RERUN's own step, never in the result
    assert result.baseline["execute_command"] == "python train.py"


@pytest.mark.parametrize(
    "error, transient",
    [
        (ApiTimeoutError(timeout_type="pool"), True),
        (ApiStatusCodeError(status=503), True),
        (ApiStatusCodeError(status=429), True),
        (ForbiddenError(), False),
    ],
)
def test_sandbox_error_classification(error, transient):
    assert sandbox._is_transient_sandbox_error(error) is transient
    assert sandbox._is_external_sandbox_error(error)


def test_path_recon_model_timeout_is_infra_error_and_never_runs_the_sandbox(tmp_path):
    runner = _Sandbox([_fail()])
    result = _pipeline(tmp_path, recon=_Chat([_timeout()]), sandbox_runner=runner)
    _assert_infra(result, "model")
    assert runner.calls == []


def test_path_planner_model_timeout_is_infra_error(tmp_path):
    _assert_infra(_pipeline(tmp_path, planner=_Chat([_timeout()])), "model")


def test_path_repairer_model_timeout_is_infra_error_not_a_declined_attempt(tmp_path):
    result = _pipeline(tmp_path, repair=_Chat([_timeout()]))
    _assert_infra(result, "model")
    assert not [a for a in result.attempts if a.origin == "model"]


def test_path_adjudicator_model_timeout_is_infra_error(tmp_path):
    _assert_infra(_pipeline(tmp_path, adjudicator=_Chat([_timeout()]), sandbox_runner=_Sandbox([_ok()])), "model")


def test_path_model_auth_failure_is_immediate_infra_error(tmp_path):
    auth = openai.AuthenticationError("bad key", response=httpx.Response(401, request=_REQ), body=None)
    recon = _Chat([auth])
    _assert_infra(_pipeline(tmp_path, recon=recon), "model")
    assert recon.calls == 1


def test_negative_control_model_parse_failure_still_uses_the_stage_fallback(tmp_path):
    """A model that answers badly is not an outage: recon's abstention and
    the documented command apply as before."""
    result = _pipeline(tmp_path, recon=_Chat(["not json"]))
    assert result.verdict != infra.INFRA_ERROR


def test_path_github_outage_during_the_era_lookup_is_infra_error(tmp_path):
    http = lambda url: (503, None)  # noqa: E731
    _assert_infra(_pipeline(tmp_path, repo_url="https://github.com/o/r", http_get=http), "github")


def test_path_github_rate_limit_403_is_immediate_infra_error(tmp_path):
    calls = []

    def http(url):
        calls.append(url)
        return 403, {"message": "API rate limit exceeded"}

    _assert_infra(_pipeline(tmp_path, repo_url="https://github.com/o/r", http_get=http), "github")
    assert len(calls) == 1


def test_negative_control_github_404_is_an_answer_not_an_outage(tmp_path):
    result = _pipeline(tmp_path, repo_url="https://github.com/o/r", http_get=lambda url: (404, None))
    assert result.verdict != infra.INFRA_ERROR


def test_path_package_index_outage_in_the_resolver_is_infra_error():
    def http(url):
        raise httpx.ConnectTimeout("pypi unreachable", request=httpx.Request("GET", url))

    with pytest.raises(infra.InfraError) as excinfo:
        dep_resolver.resolve(None, classifier.TaxonomyCode.DEP_MISSING, "ModuleNotFoundError: No module named 'widget'",
                             date(2020, 1, 1), http_get=http)
    assert excinfo.value.source == "package-index"


def test_path_uv_index_unreachable_is_infra_error_not_a_failed_lock():
    calls = []

    def runner(argv, stdin):
        calls.append(1)
        return 2, "", "error: Failed to fetch: `https://pypi.org/simple/numpy/`\n  Caused by: dns error"

    with pytest.raises(infra.InfraError) as excinfo:
        time_machine.compile_lock(["numpy"], [], date(2020, 1, 1), "3.8", runner=runner, uv="uv", build_python="3.8")
    assert excinfo.value.source == "package-index" and len(calls) == infra.DEFAULT_ATTEMPTS


def test_negative_control_uv_resolution_failure_is_still_a_failed_lock():
    lock = time_machine.compile_lock(["x"], [], date(2020, 1, 1), "3.8",
                                     runner=lambda a, s: (1, "", "error: No solution found when resolving dependencies"),
                                     uv="uv", build_python="3.8")
    assert not lock.ok


def test_path_uv_outage_through_the_time_machine_is_infra_error(tmp_path, monkeypatch):
    monkeypatch.setattr(time_machine, "era_date", lambda *a: EraDate(date(2020, 1, 1), "dependency-files"))

    def lock(*args):
        raise infra.InfraError("package-index", "uv could not reach the index", attempts=4)

    _assert_infra(_pipeline(tmp_path, lock_compiler=lock), "package-index")


def _fake_git(stderr_for_fetch):
    def run(argv, **kwargs):
        if "fetch" in argv:
            return subprocess.CompletedProcess(argv, 128, "", stderr_for_fetch)
        return subprocess.CompletedProcess(argv, 0, "", "")

    return run


def test_path_git_host_unreachable_during_clone_is_infra_error(tmp_path, monkeypatch):
    monkeypatch.setattr(intake.subprocess, "run", _fake_git("fatal: unable to access 'https://github.com/o/r/': Could not resolve host: github.com"))
    with pytest.raises(infra.InfraError) as excinfo:
        intake.clone_repo_at_commit("https://github.com/o/r", tmp_path / "c", "a" * 40)
    assert excinfo.value.source == "git" and excinfo.value.attempts == infra.DEFAULT_ATTEMPTS


def test_negative_control_missing_commit_is_an_intake_error_not_infra(tmp_path, monkeypatch):
    monkeypatch.setattr(intake.subprocess, "run", _fake_git("fatal: couldn't find remote ref " + "a" * 40))
    with pytest.raises(intake.IntakeError):
        intake.clone_repo_at_commit("https://github.com/o/r", tmp_path / "c", "a" * 40)


def test_negative_control_wall_clock_is_still_timeout(tmp_path):
    result = _pipeline(tmp_path, sandbox_runner=_Sandbox([SandboxError("sandbox execution exceeded 60s wall clock")]))
    assert result.verdict == "TIMEOUT"


def test_other_sandbox_errors_are_rerun_bugs_not_not_attemptable(tmp_path):
    result = _pipeline(tmp_path, sandbox_runner=_Sandbox([SandboxError("sandbox run produced no steps")]))
    assert result.verdict == "INDETERMINATE"
    assert reason_code_of(result.indeterminate_reason).startswith("PIPELINE_ERROR:sandbox")


def test_post_extraction_mismatch_is_invalid_harness(tmp_path):
    result = _pipeline(tmp_path, sandbox_runner=_Sandbox([sandbox.UploadIntegrityError("post-extraction check failed (exit code 97)", "RERUN_UPLOAD_MISMATCH 1 file(s): run.sh (mode 644 != 0755)")]))
    assert result.verdict == tree_integrity.INVALID_HARNESS
    assert result.tree_integrity["status"] == "post_extraction_mismatch"


def test_infra_error_is_excluded_from_the_batch_denominator():
    from app.batch.runner import aggregate_batch_results

    agg = aggregate_batch_results([
        {"name": "a", "verdict": "BLOCKED", "taxonomy_code": "DEP_MISSING"},
        {"name": "b", "verdict": "INFRA_ERROR", "reason_code": "INFRA_ERROR:sandbox:ApiTimeoutError"},
    ])
    assert agg["n_measured"] == 1 and agg["our_fault_breakdown"] == {"INFRA_ERROR": 1}


def _fake_contree(plan):
    class _Result:
        def __init__(self, code):
            self.exit_code, self.stdout, self.stderr = code, "ok", ""
            self.elapsed_time, self.cost = timedelta(seconds=1), 0.0

    class _Image:
        uuid = None

        def __init__(self, result=None):
            self.result = result
            self.exit_code = result.exit_code if result else None

        def apply_files(self, files):
            plan.uploads += 1
            assert list(files) == [sandbox.UPLOAD_ARCHIVE]  # ONE upload
            if plan.fail_uploads > 0:
                plan.fail_uploads -= 1
                raise ApiTimeoutError(timeout_type="read")
            return _Image()

        def run(self, shell, timeout, disposable, preserve_env=False):
            plan.commands.append(shell)
            return _Image(_Result(0))

        def wait(self):
            return self

    class _Client:
        def __init__(self, config):
            self.images = types.SimpleNamespace(docker=lambda ref: _Image())

    return _Client


# --- (m) git file modes through the upload ----------------------------------------


def _git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


def _repo_with_executable_script(tmp_path) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "core.autocrlf", "false")
    (repo / "run.sh").write_bytes(b"#!/bin/sh\necho RUN_SH_EXECUTED\n")
    (repo / "train.py").write_bytes(b"print('hi')\n")
    _git(repo, "add", "-A")
    _git(repo, "update-index", "--chmod=+x", "run.sh")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "c")
    return repo, _git(repo, "rev-parse", "HEAD")


def test_git_modes_come_from_the_pinned_commit(tmp_path):
    repo, sha = _repo_with_executable_script(tmp_path)
    files = {"run.sh": repo / "run.sh", "train.py": repo / "train.py"}
    record = REAL_VERIFY_UPLOAD(repo, sha, files)
    assert record.modes == {"run.sh": "100755", "train.py": "100644"}


def test_archive_carries_git_modes_into_tar_and_manifest():
    data, manifest = sandbox.build_upload_archive(
        {"run.sh": b"#!/bin/sh\necho hi\n", "train.py": b"print(1)\n"}, {"run.sh": "100755", "train.py": "100644"}
    )
    with tarfile.open(fileobj=io.BytesIO(data)) as tar:
        modes = {m.name: m.mode for m in tar.getmembers()}
    assert modes["run.sh"] == 0o755 and modes["train.py"] == 0o644
    assert manifest["run.sh"][1] == "0755" and manifest["train.py"][1] == "0644"


def test_archive_refuses_unsafe_or_reserved_paths():
    for bad in ("../x", "/etc/passwd", f"{sandbox.UPLOAD_DIR}/verify.py"):
        with pytest.raises(sandbox.UploadIntegrityError):
            sandbox.build_upload_archive({bad: b"x"})


def _wsl_available() -> bool:
    if shutil.which("wsl.exe") is None and shutil.which("wsl") is None:
        return os.name != "nt" and shutil.which("tar") is not None and shutil.which("python3") is not None
    try:
        out = subprocess.run(["wsl.exe", "-d", "kali-linux", "--", "sh", "-c", "command -v python3 && command -v tar"],
                             capture_output=True, text=True, timeout=60)
        return out.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _run_extract_in_linux(archive: bytes, then: str) -> subprocess.CompletedProcess:
    """Extract with the EXACT sandbox command on a Linux filesystem (WSL's
    own /tmp on Windows hosts, where NTFS can't hold exec bits), then run `then`."""
    host = Path(os.environ.get("TEMP", "/tmp")) / "rerun_upload_roundtrip.tar"
    host.write_bytes(archive)
    script = (
        "set -e; D=$(mktemp -d); cp \"$SRC\" \"$D/" + sandbox.UPLOAD_ARCHIVE + "\"; cd \"$D\"; "
        # The step's exit status, as the sandbox sees it for its own step.
        + "{ " + sandbox.EXTRACT_COMMAND + "; } || exit $?; " + then
    )
    if os.name == "nt":
        # Forward slashes: WSL's argument passing strips backslashes.
        src = subprocess.run(["wsl.exe", "-d", "kali-linux", "--", "wslpath", "-a", str(host).replace("\\", "/")],
                             capture_output=True, text=True, timeout=60).stdout.strip()
        # --exec: no outer shell, so "$SRC" reaches `sh -c` unexpanded.
        return subprocess.run(["wsl.exe", "-d", "kali-linux", "--exec", "env", f"SRC={src}", "sh", "-c", script],
                              capture_output=True, text=True, timeout=120)
    return subprocess.run(["sh", "-c", script], env={**os.environ, "SRC": str(host)}, capture_output=True, text=True, timeout=120)


needs_linux = pytest.mark.skipif(not _wsl_available(), reason="needs a Linux filesystem (WSL kali-linux or POSIX host)")


@needs_linux
def test_round_trip_executable_run_sh_stays_executable_and_verifies(tmp_path):
    repo, sha = _repo_with_executable_script(tmp_path)
    files = {"run.sh": repo / "run.sh", "train.py": repo / "train.py"}
    modes = {"run.sh": "100755", "train.py": "100644"}
    archive, _ = sandbox.build_upload_archive(files, modes)
    out = _run_extract_in_linux(archive, "./run.sh && test ! -e " + sandbox.UPLOAD_DIR + " && stat -c '%a %n' run.sh train.py")
    assert out.returncode == 0, out.stderr
    assert "RERUN_UPLOAD_VERIFIED 2 file(s)" in out.stdout
    assert "RUN_SH_EXECUTED" in out.stdout
    assert "755 run.sh" in out.stdout and "644 train.py" in out.stdout


def _retar(archive: bytes, edit) -> bytes:
    src = tarfile.open(fileobj=io.BytesIO(archive))
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w", format=tarfile.PAX_FORMAT) as dst:
        for member in src.getmembers():
            data = src.extractfile(member).read()
            member, data = edit(member, data)
            member.size = len(data)
            dst.addfile(member, io.BytesIO(data))
    return buffer.getvalue()


@needs_linux
def test_round_trip_mode_mismatch_fails_the_post_extraction_check():
    archive, _ = sandbox.build_upload_archive({"run.sh": b"#!/bin/sh\n"}, {"run.sh": "100755"})

    def drop_exec(member, data):
        if member.name == "run.sh":
            member.mode = 0o644
        return member, data

    out = _run_extract_in_linux(_retar(archive, drop_exec), "true")
    assert out.returncode == sandbox.UPLOAD_MISMATCH_EXIT
    assert "run.sh (mode 644 != 0755)" in out.stderr


@needs_linux
def test_round_trip_content_mismatch_fails_the_post_extraction_check():
    archive, _ = sandbox.build_upload_archive({"train.py": b"print(1)\n"}, {"train.py": "100644"})

    def tamper(member, data):
        return member, (b"print(2)\n" if member.name == "train.py" else data)

    out = _run_extract_in_linux(_retar(archive, tamper), "true")
    assert out.returncode == sandbox.UPLOAD_MISMATCH_EXIT and "train.py (content)" in out.stderr


# --- (b) import -> distribution ---------------------------------------------------


@pytest.mark.parametrize(
    "module, dist",
    [("absl", "absl-py"), ("cv2", "opencv-python"), ("sklearn", "scikit-learn"), ("yaml", "pyyaml"), ("PIL", "pillow")],
)
def test_import_map_required_names(module, dist):
    assert import_names.dist_for_import(module) == dist
    assert import_names.dist_for_import(f"{module}.sub") == dist


def test_import_map_unknown_name_falls_back_unchanged():
    assert import_names.mapping_for("zzz_not_a_module") is None
    assert import_names.dist_for_import("zzz_not_a_module.x") == "zzz_not_a_module"


def test_import_map_flags_low_confidence():
    clip = import_names.mapping_for("clip")
    assert (clip.distribution, clip.source, clip.confidence) == ("openai-clip", "pigar+rank", "low")
    assert import_names.mapping_for("absl").confidence == "normal"


def _build_script():
    import importlib.util

    spec = importlib.util.spec_from_file_location("build_import_map", ROOT / "scripts" / "build_import_map.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "dist, variant",
    [
        ("cupy", True), ("cupy-cuda12x", True), ("tensorflow-gpu", True), ("tensorflow-cpu", True),
        ("torch-cu118", True), ("jax-cuda12-plugin", True), ("jaxlib-cuda", True), ("nvidia-cudnn-cu12", True),
        ("onnxruntime-gpu", True), ("tensorflow-metal", True), ("faiss-cpu", True),
        ("tensorflow", False), ("torch", False), ("jax", False), ("opencv-python", False),
        ("scikit-learn", False), ("absl-py", False), ("torch-geometric", False), ("gpustat", False),
    ],
)
def test_hardware_variant_rule(dist, variant):
    assert _build_script().is_hardware_variant(dist) is variant


def test_table_never_maps_to_a_hardware_variant_and_leaves_those_names_unmapped():
    build = _build_script()
    rows = json.loads(import_names.TABLE_PATH.read_text(encoding="utf-8"))["rows"]
    assert not [m for m, (dist, *_rest) in rows.items() if build.is_hardware_variant(dist)]
    for module in ("cupy", "tensorflow", "torch", "jax", "faiss"):
        assert import_names.mapping_for(module) is None


def test_table_provenance_is_recorded():
    table = json.loads(import_names.TABLE_PATH.read_text(encoding="utf-8"))
    assert set(table["sources"]) == {"pipreqs", "pigar", "top_pypi_packages"}
    assert all(len(src["sha256"]) == 64 for src in table["sources"].values())
    assert (import_names.TABLE_PATH.parent / "pipreqs_LICENSE").read_text(encoding="utf-8").lstrip().startswith("Apache License")


def test_era_lock_uses_the_map_and_records_every_mapping_in_the_certificate(tmp_path, monkeypatch):
    (tmp_path / "requirements.txt").write_text("\n", encoding="utf-8")
    (tmp_path / "train.py").write_text("import absl.flags\nimport cv2\nimport zzz_unknown\n", encoding="utf-8")
    monkeypatch.setattr(time_machine, "era_date", lambda *a: EraDate(date(2020, 1, 1), "dependency-files"))
    seen = {}

    def lock(requirements, extra, era, py):
        seen["extra"] = list(extra)
        return LockResult(True, ("absl-py==0.9.0", "opencv-python==4.2.0.32"))

    intake_result = RepoIntake(tmp_path, "a" * 40, {"requirements.txt": "\n"}, frozenset(), (), ("train.py",), None)
    deps = PipelineDeps(
        recon_client=_Chat([RECON_OK]), recon_model="r", repair_client=_Chat([DECLINE]), repair_model="p",
        adjudicator_client=None, adjudicator_model=None, sandbox_api_key="k", sandbox_wall_clock_seconds=60,
        sandbox_runner=_Sandbox([_fail("ModuleNotFoundError: No module named 'absl'"), _ok()]), max_attempts=0,
        lock_compiler=lock,
    )
    result = run_pipeline(repo_url="https://example.com/r", commit_sha="a" * 40, workdir=tmp_path, intake_result=intake_result,
                          deps=deps, cost_guard=CostGuard(daily_cost_ceiling_usd=100), run_id="map",
                          documented_command="python train.py")
    assert seen["extra"] == ["absl-py", "opencv-python", "zzz_unknown"]
    era_record = result.certificate()["diffs"][0]["time_machine"]
    assert era_record["import_mappings"] == [
        {"import": "absl", "distribution": "absl-py", "source": "pigar+rank", "confidence": "normal"},
        {"import": "cv2", "distribution": "opencv-python", "source": "pigar+rank", "confidence": "normal"},
    ]
    assert "[import-map] absl -> absl-py (pigar+rank, confidence normal)" in result.full_log


def test_classifier_declared_check_uses_the_map():
    # opencv-python declared -> a failed `import cv2` is not "undeclared".
    c = classifier.classify(1, "ModuleNotFoundError: No module named 'cv2'", declared_deps=frozenset({"opencv-python"}))
    assert c.code != classifier.TaxonomyCode.DEP_MISSING
    assert dep_resolver.package_from_evidence("ModuleNotFoundError: No module named 'absl'") == "absl-py"


# --- (c) classifier fallback evidence -------------------------------------------

_ENTRY1 = ROOT / "runs" / "corpus_v1_batch" / "void_harness-v1" / "01_neuroailab__Neural-Alignment.json"


def test_entry1_real_log_evidence_is_the_exception_not_the_pip_notice():
    record = json.loads(_ENTRY1.read_text(encoding="utf-8"))
    attempt = record["result"]["attempts"][2]
    assert attempt["stderr_tail"].rstrip().endswith("[notice] To update, run: pip install --upgrade pip")
    c = classifier.classify(attempt["exit_code"], attempt["stderr_tail"], attempt["stdout_tail"])
    assert c.evidence == "RuntimeError: Python version 2.7 or 3.4+ is required."
    assert "[notice]" not in c.evidence


@pytest.mark.parametrize(
    "stderr, expected",
    [
        ("step 1\nerror: metadata-generation-failed\n× Encountered error\n[notice] upgrade pip\n", "× Encountered error"),
        ("Traceback (most recent call last):\n  x\nKeyError: 'lr'\nWARNING: something\n", "KeyError: 'lr'"),
        ("done\nexited\n[notice] A new release of pip is available\n", "exited"),
        ("[notice] only noise\nWARNING: more noise\n", "exit code 3"),
    ],
)
def test_fallback_evidence_rules(stderr, expected):
    assert classifier.fallback_evidence(stderr, "", 3) == expected
