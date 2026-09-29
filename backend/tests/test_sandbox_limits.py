"""sandbox_limits: the 120 MiB upload gate, the in-sandbox download route, and the
split of environment setup into separate operations (Nebius Sandboxes team, 2026-09-29)."""
import io
import tarfile

import pytest

from app.services import sandbox, sandbox_limits as lim

SHA = "0123456789abcdef0123456789abcdef01234567"
SOURCE = lim.DownloadSource("owner", "repo", SHA)


# --- size gate ---------------------------------------------------------------------

def test_enforced_limit_is_120_mib_and_below_both_readings_of_128_mb():
    assert lim.MAX_UPLOAD_BYTES == 125_829_120
    assert lim.MAX_UPLOAD_BYTES < 128_000_000 < 128 * 1024 * 1024
    assert sandbox.UPLOAD_CAP_BYTES == lim.MAX_UPLOAD_BYTES


def test_gate_boundary():
    at = lim.decide_upload(lim.MAX_UPLOAD_BYTES, None)
    over = lim.decide_upload(lim.MAX_UPLOAD_BYTES + 1, None)
    assert at.mode == "archive"
    assert over.mode == "refuse" and "no in-sandbox download route" in over.reason


def test_over_limit_routes_to_download_when_there_is_a_source():
    d = lim.decide_upload(lim.MAX_UPLOAD_BYTES + 1, SOURCE)
    assert d.mode == "download" and SOURCE.tarball_url in d.reason


@pytest.mark.parametrize("url, ok", [
    ("https://github.com/owner/repo", True),
    ("https://github.com/owner/repo.git", True),
    ("https://github.com/owner/repo/", True),
    ("https://gitlab.com/owner/repo", False),
    ("https://github.com/owner/repo; rm -rf /", False),
    ("https://github.com/owner/repo/tree/main", False),
    ("", False),
])
def test_download_source_only_for_plain_github_urls(url, ok):
    assert (lim.DownloadSource.from_repo_url(url, SHA) is not None) is ok


def test_download_source_requires_a_full_commit_sha():
    assert lim.DownloadSource.from_repo_url("https://github.com/o/r", "main") is None
    assert lim.DownloadSource.from_repo_url("https://github.com/o/r", SHA[:7]) is None
    with pytest.raises(ValueError):
        lim.DownloadSource("o;x", "r", SHA)


def test_fetch_command_has_no_git_dependency_and_quotes_the_url():
    cmd = SOURCE.fetch_command()
    assert "git " not in cmd and "https://codeload.github.com/owner/repo/tar.gz/" + SHA in cmd
    assert "--strip-components=1" in cmd and "rm -f /tmp/rerun_source.tar.gz" in cmd


# --- op splitting -------------------------------------------------------------------

def kinds(steps):
    return [(o.kind, o.command) for o in lim.split_setup_ops(steps)]


def test_ops_are_ordered_system_torch_rest():
    steps = ["pip install numpy", "pip install torch==2.3.0", "apt-get update && apt-get install -y gcc libgl1"]
    assert kinds(steps) == [
        ("system", "apt-get update && apt-get install -y gcc libgl1"),
        ("torch", "pip install torch==2.3.0"),
        ("requirements", "pip install numpy"),
    ]


def test_a_pip_command_naming_torch_and_others_is_split_in_two():
    assert kinds(["pip install numpy 'torch>=2' torchvision scipy"]) == [
        ("torch", "pip install 'torch>=2' torchvision"),
        ("requirements", "pip install numpy scipy"),
    ]


def test_torch_index_url_stays_with_the_torch_op():
    ops = kinds(["pip install torch --index-url https://download.pytorch.org/whl/cpu"])
    assert ops == [("torch", "pip install --index-url https://download.pytorch.org/whl/cpu torch")]


def test_requirements_file_stays_in_the_rest_op_even_with_torch():
    ops = kinds(["pip install -r requirements.txt torch"])
    assert [k for k, _ in ops] == ["torch", "requirements"]
    assert ops[1][1] == "pip install -r requirements.txt"


def test_unparseable_commands_are_never_split():
    steps = ["pip install torch | tee log", "cd sub; pip install torch numpy", "pip install numpy torch>=2",
             "true  # nothing declared"]
    assert kinds(steps) == [("requirements", s) for s in steps]


def test_mixed_apt_and_pip_compound_is_not_called_system():
    step = "apt-get install -y gcc && pip install torch"
    assert kinds([step]) == [("requirements", step)]


def test_relative_order_inside_a_class_is_preserved():
    assert [c for _, c in kinds(["pip install a", "pip install b", "pip install c"])] == [
        "pip install a", "pip install b", "pip install c"]


# --- per-op fs-delta check (ESTIMATE) --------------------------------------------------

def test_default_torch_is_estimated_as_cuda_and_cpu_index_as_cpu():
    default = lim.split_setup_ops(["pip install torch"])[0]
    cpu = lim.split_setup_ops(["pip install torch --index-url https://download.pytorch.org/whl/cpu"])[0]
    assert cpu.est_delta_bytes < default.est_delta_bytes <= lim.MAX_FS_DELTA_PER_OP_BYTES


def test_ops_over_the_ceiling_are_rejected_before_running():
    many = "apt-get install -y " + " ".join(f"pkg{i}" for i in range(80))
    ops = lim.split_setup_ops([many])
    assert not ops[0].within_limit
    with pytest.raises(lim.FsDeltaExceeded, match="per operation"):
        lim.check_ops(ops)
    assert lim.check_ops(lim.split_setup_ops(["apt-get install -y gcc"]))


def test_run_build_and_execute_refuses_an_over_limit_setup_op_without_calling_the_sdk(monkeypatch):
    monkeypatch.setattr(sandbox, "_run_once", lambda **kw: pytest.fail("must not reach the sandbox"))
    with pytest.raises(lim.FsDeltaExceeded):
        sandbox.run_build_and_execute(
            api_key="k", base_image="python:3.11-slim",
            install_commands=["apt-get install -y " + " ".join(f"p{i}" for i in range(80))],
            execute_command="true", wall_clock_seconds=60)


# --- the route-to-download path -----------------------------------------------------------

def _capture(monkeypatch):
    seen = {}

    def fake_run_once(**kw):
        seen.update(kw)
        return sandbox.SandboxRunResult(steps=(sandbox.StepResult("x", 0, "", "", 0.0, 0.0),))

    monkeypatch.setattr(sandbox, "_run_once", fake_run_once)
    return seen


def _members(archive: bytes) -> dict[str, bytes]:
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        return {m.name: tar.extractfile(m).read() for m in tar.getmembers()}


def test_within_the_limit_the_repo_is_uploaded_as_before(monkeypatch):
    seen = _capture(monkeypatch)
    sandbox.run_build_and_execute(api_key="k", base_image="i", install_commands=[], execute_command="true",
                                  wall_clock_seconds=60, upload_files={"a.py": b"print(1)"}, download_source=SOURCE)
    assert "a.py" in _members(seen["archive"]) and seen["extract_command"] == sandbox.EXTRACT_COMMAND


def test_over_the_limit_only_the_manifest_is_uploaded_and_the_sandbox_downloads(monkeypatch):
    monkeypatch.setattr(sandbox, "UPLOAD_CAP_BYTES", 20_000)
    seen = _capture(monkeypatch)
    payload = b"SECRET-REPO-BYTES" * 2000  # 34,000 B > the 20,000 B limit
    sandbox.run_build_and_execute(api_key="k", base_image="i", install_commands=[], execute_command="true",
                                  wall_clock_seconds=60, upload_files={"big.bin": payload}, download_source=SOURCE)
    members = _members(seen["archive"])
    assert "big.bin" not in members and payload not in seen["archive"]
    manifest = members[f"{sandbox.UPLOAD_DIR}/manifest.json"].decode()
    assert "big.bin" in manifest
    cmd = seen["extract_command"]
    assert cmd.index("tar -xpf") < cmd.index("codeload.github.com") < cmd.index("verify.py")
    assert len(seen["archive"]) < 20_000


def test_over_the_limit_without_a_source_ends_upload_too_large(monkeypatch):
    monkeypatch.setattr(sandbox, "UPLOAD_CAP_BYTES", 2_000)
    monkeypatch.setattr(sandbox, "_run_once", lambda **kw: pytest.fail("nothing may be sent"))
    with pytest.raises(sandbox.UploadTooLargeError):
        sandbox.run_build_and_execute(api_key="k", base_image="i", install_commands=[], execute_command="true",
                                      wall_clock_seconds=60, upload_files={"big.bin": b"x" * 5000})


def test_orchestrator_only_passes_download_source_to_runners_that_accept_it():
    from app.services.orchestrator import _accepts_kwarg

    assert _accepts_kwarg(sandbox.run_build_and_execute, "download_source")
    assert not _accepts_kwarg(lambda *, api_key: None, "download_source")
    assert _accepts_kwarg(lambda **kw: None, "download_source")
