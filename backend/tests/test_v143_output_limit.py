"""harness-v1.4.3-rc, D-41: the SDK cut every output stream at 65,535 bytes and `sandbox.py` never read the API's `truncated` flag.

Anchor (the probe of 2026-10-02, runs/sandbox_verification/d41-probe/probe_03_vmtl_op5.json): corpus-v2 #3's real stderr is 400,939 bytes, the SDK returned the first
65,535 of them, the raw API result's stderr `truncated` flag was true, and the cut-off tail holds a CUDA error (`.cuda()` on a CPU-only torch) and the evidence block.
Every test here runs the REAL sandbox runner against the fake ConTree cloud (v140_cloud), which now applies the client's `default_truncate_output_at` like the real one.
No network."""

from __future__ import annotations

import inspect
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import v140_cloud
from app.services import classifier, sandbox

ROOT = Path(__file__).resolve().parents[2]
PROBE = ROOT / "runs" / "sandbox_verification" / "d41-probe" / "probe_03_vmtl_op5.json"


def _real_traceback() -> str:
    """The traceback the probe read from #3's real stderr file (its printed lines carry a `NNN:` grep prefix)."""
    out = json.loads(PROBE.read_text(encoding="utf-8"))["probe_stdout"]
    lines = [line.split(":", 1)[1] if ":" in line and line.split(":", 1)[0].isdigit() else line for line in out.splitlines()]
    start = next(i for i, line in enumerate(lines) if line.startswith("Traceback"))
    end = next(i for i, line in enumerate(lines) if line.startswith("AssertionError"))
    return "\n".join(lines[start:end + 1]) + "\n"


def _progress(n: int) -> str:
    return "".join("\r%.1f%%" % (i * 0.0016) for i in range(1, n + 1))


def _run(monkeypatch, stderr: str, stdout: str = "", **kwargs):
    cloud = v140_cloud.install(monkeypatch, lambda shell, built, files: (1, stdout, stderr) if shell == "python run.py" else None)
    result = sandbox.run_build_and_execute(api_key="k", project_id="p", base_image="python:3.10-slim", install_commands=[], execute_command="python run.py",
                                           wall_clock_seconds=60, upload_files={"run.py": b"print(1)\n"}, **kwargs)
    return cloud, result


# --- the finding, pinned ---------------------------------------------------------------------------------------------------------

def test_the_sdk_default_that_cut_the_stream_is_65535_bytes():
    from contree_sdk.config import ContreeConfig

    assert ContreeConfig().default_truncate_output_at == 65535  # the default every harness version before v1.4.3 ran with


def test_the_probe_record_shows_the_cut_and_the_error_behind_it():
    probe = json.loads(PROBE.read_text(encoding="utf-8"))
    assert probe["flags"]["raw_stderr_truncated"] is True and probe["flags"]["raw_stdout_truncated"] is False
    assert probe["returned_stderr_bytes"] == 65535 and "stderr_bytes=400939" in probe["probe_stdout"]
    assert "Torch not compiled with CUDA enabled" in _real_traceback()


def test_the_real_error_behind_the_cut_is_a_gpu_error_and_the_cut_head_says_nothing():
    """What the harness saw (the head) classifies as nothing; what #3 really printed classifies as GPU_REQUIRED, the class the CPU shim answers."""
    full = _progress(67558) + "\n" + _real_traceback()
    head = full.encode("utf-8")[:65535].decode("utf-8", "ignore")
    assert len(full.encode("utf-8")) > 400_000 and "Traceback" not in head
    assert not classifier.has_actionable_error(head, "")
    assert classifier.classify(1, head, "").code != classifier.TaxonomyCode.GPU_REQUIRED
    assert classifier.has_actionable_error(full, "")
    assert classifier.classify(1, full, "").code == classifier.TaxonomyCode.GPU_REQUIRED


# --- the fix ---------------------------------------------------------------------------------------------------------------------

def test_the_runner_asks_for_the_raised_limit_and_a_200_kb_stderr_keeps_its_last_traceback(monkeypatch):
    stderr = _progress(35000) + "\n" + _real_traceback()
    assert len(stderr.encode("utf-8")) > 200_000
    cloud, result = _run(monkeypatch, stderr)
    assert cloud.output_limit == sandbox.OUTPUT_LIMIT_BYTES == 4 * 1024 * 1024
    final = result.final
    assert final.stderr == stderr and final.stderr.endswith("AssertionError: Torch not compiled with CUDA enabled\n")
    assert not final.stderr_truncated and not final.stdout_truncated and not final.truncated
    assert classifier.classify(final.exit_code, final.stderr, final.stdout).code == classifier.TaxonomyCode.GPU_REQUIRED


def test_without_the_raised_limit_the_same_run_loses_its_traceback(monkeypatch):
    """Negative control for the fix itself: with the SDK's old limit the fake cuts like the real API did, and the flag is the only trace of it."""
    monkeypatch.setattr(sandbox, "OUTPUT_LIMIT_BYTES", 65535)
    stderr = _progress(35000) + "\n" + _real_traceback()
    cloud, result = _run(monkeypatch, stderr)
    assert cloud.output_limit == 65535
    assert len(result.final.stderr.encode("utf-8")) == 65535 and "Traceback" not in result.final.stderr
    assert result.final.stderr_truncated is True and result.final.truncated is True and not result.final.stdout_truncated


def test_a_stream_over_the_raised_limit_is_flagged_and_its_returned_size_recorded(monkeypatch):
    monkeypatch.setattr(sandbox, "OUTPUT_LIMIT_BYTES", 5000)
    _, result = _run(monkeypatch, "x" * 9000, stdout="short output\n")
    streams = result.final.streams()
    assert streams["limit_bytes"] == 5000
    assert streams["stderr"]["bytes"] == 5000 and streams["stderr"]["truncated"] is True
    assert streams["stdout"] == {"bytes": 13, "sha256": streams["stdout"]["sha256"], "truncated": False}


def test_the_stream_record_has_the_size_and_sha256_of_what_the_sdk_returned(monkeypatch):
    import hashlib

    _, result = _run(monkeypatch, "oops\n", stdout="héllo\n")
    streams = result.final.streams()
    assert streams["stdout"]["bytes"] == len("héllo\n".encode("utf-8")) == 7  # bytes, not characters
    assert streams["stdout"]["sha256"] == hashlib.sha256("héllo\n".encode("utf-8")).hexdigest()
    assert streams["stderr"] == {"bytes": 5, "sha256": hashlib.sha256(b"oops\n").hexdigest(), "truncated": False}


def test_the_extract_cost_fold_keeps_the_stream_fields(monkeypatch):
    """The first step carries the tree-extract cost (the runner rebuilds it); a positional rebuild had dropped every field added after `phase`."""
    monkeypatch.setattr(sandbox, "OUTPUT_LIMIT_BYTES", 1000)
    cloud, result = _run(monkeypatch, "e" * 3000)
    assert len(result.steps) == 1 and result.steps[0].stderr_truncated is True
    assert result.steps[0].cost_usd == pytest.approx(0.02)  # the extract step's 0.01 folded into the command's 0.01


def test_the_flag_is_read_from_the_raw_api_result_and_defaults_to_false_for_a_fake():
    def image(raw):
        result = SimpleNamespace(exit_code=1, stdout="a", stderr="b", elapsed_time=SimpleNamespace(total_seconds=lambda: 1.0), cost=0.0)
        if raw is not None:
            result._raw = raw
        return SimpleNamespace(result=result)

    raw = SimpleNamespace(result=SimpleNamespace(stdout=SimpleNamespace(truncated=False), stderr=SimpleNamespace(truncated=True), state=SimpleNamespace(timed_out=False)))
    step = sandbox.step_result_from_image(image(raw), "cmd")
    assert (step.stdout_truncated, step.stderr_truncated, step.truncated) == (False, True, True)
    plain = sandbox.step_result_from_image(image(None), "cmd")
    assert (plain.stdout_truncated, plain.stderr_truncated, plain.truncated) == (False, False, False)


# --- the API's peak-memory figure (D-40), stored as returned ----------------------------------------------------------------------

def _image_with_resources(resources):
    raw = SimpleNamespace(result=SimpleNamespace(stdout=SimpleNamespace(truncated=False), stderr=SimpleNamespace(truncated=False), state=SimpleNamespace(timed_out=False),
                                                 **({"resources": resources} if resources is not None else {})))
    result = SimpleNamespace(exit_code=0, stdout="", stderr="", elapsed_time=SimpleNamespace(total_seconds=lambda: 1.0), cost=0.0, _raw=raw)
    return SimpleNamespace(result=result)


def test_the_peak_memory_figure_is_stored_as_returned_and_never_invented():
    read = lambda resources: sandbox.step_result_from_image(_image_with_resources(resources), "cmd").max_rss  # noqa: E731
    assert read(SimpleNamespace(max_rss=3895992)) == 3895992  # no unit conversion: the unit is not documented
    assert read(SimpleNamespace(max_rss=0)) == 0
    assert read(None) is None and read(SimpleNamespace()) is None
    assert read(SimpleNamespace(max_rss=1.5)) is None and read(SimpleNamespace(max_rss="3895992")) is None and read(SimpleNamespace(max_rss=True)) is None
    plain = SimpleNamespace(result=SimpleNamespace(exit_code=0, stdout="", stderr="", elapsed_time=SimpleNamespace(total_seconds=lambda: 1.0), cost=0.0))
    assert sandbox.step_result_from_image(plain, "cmd").max_rss is None  # a duck-typed fake with no raw result


def test_the_operation_record_carries_the_largest_figure_of_its_steps(monkeypatch, tmp_path):
    from test_v140_pipeline import EXEC, _repo, _run

    _repo(tmp_path, {"main.py": "print('ok')\n"})
    cloud = v140_cloud.install(monkeypatch, lambda shell, built, files: (0, "ok", "") if shell in EXEC else None)
    cloud.max_rss = 3895992
    _, _, guard = _run(tmp_path, cloud)
    assert guard.operations[0]["max_rss"] == 3895992


# --- run_on_image (the sustained-run primitive) ----------------------------------------------------------------------------------

def test_run_on_image_reopens_the_image_by_id_runs_once_disposable_and_asks_for_the_raised_limit(monkeypatch):
    cloud = v140_cloud.install(monkeypatch, lambda shell, built, files: (0, "done\n", "") if shell == "python train.py" else None)
    image = cloud.new_image(("FROM python:3.10-slim", "pip install six"), {"train.py": b"print('done')"})
    step = sandbox.run_on_image(api_key="k", project_id="p", image_id=image.uuid, command="python train.py", timeout_seconds=30)
    assert step.exit_code == 0 and step.stdout == "done\n" and not step.timed_out and not step.truncated
    assert cloud.reopened == [image.uuid] and cloud.ran == ["python train.py"] and cloud.output_limit == sandbox.OUTPUT_LIMIT_BYTES
    assert len(cloud.images) == 1  # disposable: nothing new was kept


def test_run_on_image_refuses_an_unknown_image_and_a_missing_key(monkeypatch):
    v140_cloud.install(monkeypatch)
    with pytest.raises(Exception, match="no image"):
        sandbox.run_on_image(api_key="k", image_id="00000000-0000-0000-0000-000000000000", command="true", timeout_seconds=5)
    with pytest.raises(sandbox.SandboxCredentialsError):
        sandbox.run_on_image(api_key="", image_id="x", command="true", timeout_seconds=5)


# --- the finding about the larger instance (item 3) -------------------------------------------------------------------------------

def test_contree_sdk_0_3_6_has_no_memory_cpu_size_or_instance_parameter():
    """The directive's item 3: a RESOURCE_LIMIT retry on a larger instance needs a parameter that selects one. The SDK installed here (0.3.6) has none on a run or on the
    spawn request it builds, so no retry rule exists and #11's OOM stays INDETERMINATE with the kernel line quoted. If an SDK upgrade adds one, this test fails and the
    question is open again."""
    import dataclasses

    from contree_sdk._internals.models.instance import InstanceSpawnRequest
    from contree_sdk.sdk.objects.image_like._base import _ImageLikeBase
    from contree_sdk.sdk.objects.run import RunRequest

    words = ("memory", "mem", "cpu", "ram", "size", "instance", "flavor", "flavour", "machine", "gpu", "vcpu", "resource")
    names = {f.name for f in dataclasses.fields(InstanceSpawnRequest)} | {f.name for f in dataclasses.fields(RunRequest)}
    names |= set(inspect.signature(_ImageLikeBase.run).parameters)
    assert not [n for n in names if any(w in n.lower() for w in words)], sorted(names)
    # the API does return the peak memory per operation (ProcessResources.max_rss): evidence, not a parameter
    from contree_sdk._internals.models.instance import ProcessResources

    assert "max_rss" in {f.name for f in dataclasses.fields(ProcessResources)}
