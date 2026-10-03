"""harness-v1.5.1, F3 (METHODOLOGY "harness-v1.5 dev/test protocol", rule G). Failure class: GPU-only code the CPU shim did not cover.

Recorded failure: DEV entry 14 (runs/corpus_v2_batch/harness-v1.5.0/dev/14_IST-DASLab__M-FAC.json): `torch.cuda.set_device(dev.index)` raised
`AttributeError: module 'torch._C' has no attribute '_cuda_setDevice'` on the CPU wheel, the classifier read it as RUNTIME_ERROR_OTHER, the CPU shim never ran on the baseline, and
the model's candidates patched the call out. The shim now makes `torch.cuda.set_device(...)` do nothing and the classifier reads the error as GPU_REQUIRED, so the shim is
installed by RERUN before any model call. Covered by the same class: any repository that selects a CUDA device by index on a CPU-only runner (the other recorded CUDA call
sites, `.cuda()` and `.to("cuda")`, were already covered by the shim: DEV entry 4, gate entries 3 and 8).

Offline: the shim runs against a fake `torch` (the v1.4.2 fixture, extended with the CPU wheel's missing `_cuda_setDevice`); the same checks run on REAL torch when
RERUN_REAL_TORCH_PYTHON names an interpreter with the CPU wheel."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from app.services import classifier, runner_hooks
from test_v140_runner_hooks import _site
from test_v142_cpu_shim import FAKE_TORCH, fake_torch  # noqa: F401 - the fixture

ROOT = Path(__file__).resolve().parents[2]
DEV = ROOT / "runs" / "corpus_v2_batch" / "harness-v1.5.0" / "dev"
SET_DEVICE_ERROR = "AttributeError: module 'torch._C' has no attribute '_cuda_setDevice'"

FAKE_WITH_SET_DEVICE = FAKE_TORCH.replace(
    "class cuda(object):\n    @staticmethod\n    def is_available():\n        return False\n",
    "class cuda(object):\n    @staticmethod\n    def is_available():\n        return False\n\n    @staticmethod\n"
    "    def set_device(device):\n        raise AttributeError(\"module 'torch._C' has no attribute '_cuda_setDevice'\")\n",
)
assert "_cuda_setDevice" in FAKE_WITH_SET_DEVICE


def _record14() -> dict:
    return json.loads(next(DEV.glob("14_*.json")).read_text(encoding="utf-8"))


def _run(tmp_path, code, fake_torch_dir, *hooks):
    site = _site(tmp_path, *hooks)
    boot = f"import site, sys; sys.path.insert(0, {str(fake_torch_dir)!r}); site.addsitedir({str(site)!r})\n"
    return subprocess.run([sys.executable, "-c", boot + textwrap.dedent(code)], capture_output=True, text=True, timeout=60)


# --- the classifier ----------------------------------------------------------------------------------------------------------------------------

def test_the_recorded_entry_14_error_is_now_gpu_required():
    record = _record14()
    assert record["result"]["first_repo_error"] == SET_DEVICE_ERROR
    stderr = f"Traceback (most recent call last):\n  File \"//main_optim.py\", line 134, in <module>\n    torch.cuda.set_device(dev.index)\n{SET_DEVICE_ERROR}\n"
    got = classifier.classify(1, stderr, "")
    assert got.code == classifier.TaxonomyCode.GPU_REQUIRED and "_cuda_setDevice" in got.evidence


def test_other_torch_c_attribute_errors_and_ordinary_attribute_errors_are_not_read_as_gpu():
    for text in ("AttributeError: module 'torch._C' has no attribute '_jit_foo'", "AttributeError: module 'torch' has no attribute 'foo'",
                 "AttributeError: module 'numpy' has no attribute 'float'"):
        assert classifier.classify(1, f"Traceback\n{text}\n", "").code != classifier.TaxonomyCode.GPU_REQUIRED


# --- the shim ------------------------------------------------------------------------------------------------------------------------------------

CODE = """
    import torch
    dev = torch.device("cuda:1")
    torch.cuda.set_device(dev.index)
    torch.cuda.set_device(dev)
    torch.cuda.set_device(0)
    print("past set_device")
"""


def test_without_the_shim_set_device_raises_the_recorded_error_and_with_it_the_run_goes_on(tmp_path, fake_torch):
    (fake_torch / "torch" / "__init__.py").write_text(FAKE_WITH_SET_DEVICE, encoding="utf-8")
    (tmp_path / "plain").mkdir()
    (tmp_path / "shimmed").mkdir()
    plain = _run(tmp_path / "plain", CODE, fake_torch)
    assert plain.returncode == 1 and SET_DEVICE_ERROR in plain.stderr
    assert classifier.classify(1, plain.stderr).code == classifier.TaxonomyCode.GPU_REQUIRED
    shimmed = _run(tmp_path / "shimmed", CODE, fake_torch, runner_hooks.CPU_SHIM)
    assert shimmed.returncode == 0, shimmed.stderr
    assert "past set_device" in shimmed.stdout
    assert runner_hooks.shim_paths_fired(shimmed.stderr) == ["torch.device", "cuda.set_device"]  # the probe also builds torch.device("cuda:1")
    assert shimmed.stderr.count("RERUN_CPU_SHIM_PATH: cuda.set_device") == 1  # once per path per process
    assert "torch.cuda.set_device(...) does nothing" in shimmed.stderr


def test_the_shim_record_names_set_device_as_covered_and_the_rest_of_torch_cuda_as_not():
    hook = runner_hooks.HOOKS[runner_hooks.CPU_SHIM]
    assert "torch.cuda.set_device()" in hook.limit and "the other torch.cuda.* functions (current_device, synchronize, ...)" in hook.limit
    assert "cuda.set_device" in runner_hooks.shim_paths_fired.__doc__


# --- the same on REAL torch (CPU wheel), when an interpreter that has it is named ---------------------------------------------------------------

REAL_PY = os.environ.get("RERUN_REAL_TORCH_PYTHON")


@pytest.mark.skipif(not REAL_PY or not Path(REAL_PY).exists(), reason="set RERUN_REAL_TORCH_PYTHON to an interpreter with torch (CPU) installed")
def test_on_real_torch_set_device_raises_without_the_shim_and_does_nothing_with_it(tmp_path):
    site = tmp_path / "site"
    site.mkdir()
    (site / "rerun_cpu_shim.py").write_text(runner_hooks.source_of(runner_hooks.CPU_SHIM), encoding="utf-8")
    (site / "rerun_cpu_shim.pth").write_text("import rerun_cpu_shim\n", encoding="utf-8")
    probe = "import torch\ntorch.cuda.set_device(torch.device('cuda:0').index)\nprint('past', torch.zeros(1).device.type)\n"

    def run(shimmed):
        boot = f"import site; site.addsitedir({str(site)!r})\n" if shimmed else ""
        return subprocess.run([REAL_PY, "-c", boot + probe], capture_output=True, text=True, timeout=300, cwd=tmp_path)

    plain = run(False)
    assert plain.returncode != 0 and ("_cuda_setDevice" in plain.stderr or "Torch not compiled with CUDA enabled" in plain.stderr or "has no attribute" in plain.stderr)
    shimmed = run(True)
    assert shimmed.returncode == 0, shimmed.stderr[-1500:]
    assert "past cpu" in shimmed.stdout and "cuda.set_device" in runner_hooks.shim_paths_fired(shimmed.stderr)
