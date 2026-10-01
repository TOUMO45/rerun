"""harness-v1.4.2-rc, directive item 2 (D-39): the CPU shim also covers `.cuda()` on Tensor and Module (return self), `torch.device("cuda*")` (-> cpu) and
`.to("cuda*")` (-> cpu), and records which shim path fired.

Anchor: corpus-v2 #8, harness-v1.4.1 gate, round 3: after the shim had handled `torch.load`, the adopted candidate's run reached an explicit `.cuda()` and died
with `AssertionError: Torch not compiled with CUDA enabled` (GPU_REQUIRED). A fake `torch` reproduces that error from `.cuda()` / `.to("cuda")` and runs in every
environment; the same checks run against REAL torch (CPU wheel) when RERUN_REAL_TORCH_PYTHON names an interpreter that has it."""

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

ROOT = Path(__file__).resolve().parents[2]
GATE_V141 = ROOT / "runs" / "corpus_v2_batch" / "harness-v1.4.1" / "gate"

FAKE_TORCH = '''
ERR = "Torch not compiled with CUDA enabled"


class device(object):
    def __init__(self, type, index=None):
        if isinstance(type, str) and ":" in type:
            type, index = type.split(":")
        self.type, self.index = type, index

    def __repr__(self):
        return "device(type=%r)" % (self.type,)


def _check(target):
    kind = getattr(target, "type", target)
    if isinstance(kind, str) and kind.startswith("cuda"):
        raise AssertionError(ERR)


class Tensor(object):
    def cuda(self, *a, **k):
        raise AssertionError(ERR)

    def to(self, *args, **kwargs):
        _check(args[0] if args else kwargs.get("device"))
        return self


class nn(object):
    class Module(object):
        def cuda(self, *a, **k):
            raise AssertionError(ERR)

        def to(self, *args, **kwargs):
            _check(args[0] if args else kwargs.get("device"))
            return self


class cuda(object):
    @staticmethod
    def is_available():
        return False


def load(f, map_location=None, **kwargs):
    if map_location != "cpu":
        raise RuntimeError("Attempting to deserialize object on a CUDA device but torch.cuda.is_available() is False.")
    return {"map_location": map_location}
'''


@pytest.fixture
def fake_torch(tmp_path):
    pkg = tmp_path / "pkgs" / "torch"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text(FAKE_TORCH, encoding="utf-8")
    return tmp_path / "pkgs"


def _run(tmp_path, code, fake_torch, *hooks):
    site = _site(tmp_path, *hooks)
    boot = f"import site, sys; sys.path.insert(0, {str(fake_torch)!r}); site.addsitedir({str(site)!r})\n"
    return subprocess.run([sys.executable, "-c", boot + textwrap.dedent(code)], capture_output=True, text=True, timeout=60)


def _recorded_8() -> dict:
    record = json.loads((GATE_V141 / "08_edenton__svg.json").read_text(encoding="utf-8"))
    return next(a for a in record["result"]["attempts"] if a["attempt_number"] == 3 and a.get("chosen"))


CODE = """
    import torch
    x = torch.Tensor().cuda()
    m = torch.nn.Module().cuda()
    d = torch.device("cuda:0")
    print("device", d.type, isinstance(d, torch.device), isinstance(torch.device("cpu"), torch.device))
    torch.Tensor().to("cuda"); torch.Tensor().to(d); torch.Tensor().to(device=torch.device("cuda"))
    torch.nn.Module().to("cuda:1")
    print("same", x is not None and m is not None, torch.cuda.is_available(), torch.load("m.pt"))
"""


def test_the_recorded_8_error_is_what_a_cuda_call_raises_and_it_is_classified_gpu_required():
    recorded = _recorded_8()
    assert "Torch not compiled with CUDA enabled" in recorded["stderr_tail"]
    assert classifier.classify(1, recorded["stderr_tail"]).code == "GPU_REQUIRED"


def test_without_the_shim_cuda_raises_the_recorded_assertion(tmp_path, fake_torch):
    proc = _run(tmp_path, "import torch\ntorch.Tensor().cuda()\n", fake_torch)
    assert proc.returncode == 1 and "AssertionError: Torch not compiled with CUDA enabled" in proc.stderr
    assert classifier.classify(1, proc.stderr).code == "GPU_REQUIRED"


def test_with_the_shim_every_cuda_path_goes_to_the_cpu_and_each_path_that_fired_is_recorded(tmp_path, fake_torch):
    proc = _run(tmp_path, CODE, fake_torch, runner_hooks.CPU_SHIM)
    assert proc.returncode == 0, proc.stderr
    assert "device cpu True True" in proc.stdout and "same True False" in proc.stdout and "'map_location': 'cpu'" in proc.stdout
    fired = runner_hooks.shim_paths_fired(proc.stderr)
    assert fired == ["tensor.cuda", "module.cuda", "torch.device", "tensor.to", "module.to", "cuda.is_available", "torch.load"] or set(fired) == {
        "tensor.cuda", "module.cuda", "torch.device", "tensor.to", "module.to", "cuda.is_available", "torch.load"}
    assert "RERUN_CPU_SHIM: injected by RERUN" in proc.stderr and "Tensor.cuda() returns the tensor" in proc.stderr
    assert proc.stderr.count("RERUN_CPU_SHIM_PATH: tensor.cuda") == 1  # once per path per process
    assert not classifier.has_actionable_error(proc.stderr)  # the shim's own lines are not errors


def test_a_torch_without_some_attribute_still_gets_the_other_patches(tmp_path, fake_torch):
    """The fake of v1.4.0 had no Tensor, nn or device: each patch stands alone, so torch.load and is_available still work and the others are reported."""
    partial = ("class cuda(object):\n    is_available = staticmethod(lambda: True)\n\n\n"
               "def load(f, map_location=None, **kw):\n    return {'map_location': map_location}\n")
    (fake_torch / "torch" / "__init__.py").write_text(partial, encoding="utf-8")
    proc = _run(tmp_path, "import torch\nprint(torch.cuda.is_available(), torch.load('m.pt'))\n", fake_torch, runner_hooks.CPU_SHIM)
    assert proc.returncode == 0, proc.stderr
    assert "False {'map_location': 'cpu'}" in proc.stdout
    assert "Tensor.cuda() returns the tensor not applied" in proc.stderr and "torch.device('cuda*') -> cpu not applied" in proc.stderr
    assert "torch.cuda.is_available() -> False" in proc.stderr.split("injected by RERUN:")[1]


def test_the_shim_hook_record_states_what_it_does_not_cover():
    hook = runner_hooks.HOOKS[runner_hooks.CPU_SHIM]
    assert "device='cuda' strings given to factory functions" in hook.limit and "torch.cuda.*Tensor types" in hook.limit


def test_shim_paths_fired_reads_the_lines_in_order_without_duplicates():
    text = "x\nRERUN_CPU_SHIM_PATH: torch.load\nnoise\nRERUN_CPU_SHIM_PATH: tensor.cuda\nRERUN_CPU_SHIM_PATH: torch.load\n"
    assert runner_hooks.shim_paths_fired(text, "RERUN_CPU_SHIM_PATH: module.to\n", None) == ["torch.load", "tensor.cuda", "module.to"]
    assert runner_hooks.shim_paths_fired("") == []


# --- the same checks on REAL torch (CPU wheel), run when an interpreter that has it is named ------------------------------

REAL_PY = os.environ.get("RERUN_REAL_TORCH_PYTHON")


@pytest.mark.skipif(not REAL_PY or not Path(REAL_PY).exists(), reason="set RERUN_REAL_TORCH_PYTHON to an interpreter with torch (CPU) installed")
def test_on_real_torch_cuda_calls_raise_without_the_shim_and_pass_with_it(tmp_path):
    site = tmp_path / "site"
    site.mkdir()
    (site / "rerun_cpu_shim.py").write_text(runner_hooks.source_of(runner_hooks.CPU_SHIM), encoding="utf-8")
    (site / "rerun_cpu_shim.pth").write_text("import rerun_cpu_shim\n", encoding="utf-8")
    probe = textwrap.dedent("""
        import torch, sys
        x = torch.zeros(2).cuda()
        m = torch.nn.Linear(2, 2).cuda()
        d = torch.device("cuda:0")
        y = torch.ones(2).to("cuda").to(d).to(device=torch.device("cuda"))
        z = torch.zeros(2, device=torch.device("cuda"))
        m2 = torch.nn.Linear(2, 2).to("cuda")
        print("types", d.type, y.device.type, z.device.type, isinstance(d, torch.device), isinstance(torch.device("cpu"), torch.device))
        print("index", torch.device("cuda", 0) == torch.zeros(1).device, torch.device("cuda:1") == torch.device("cpu"), torch.device(type="cuda", index=0).type)
        print("avail", torch.cuda.is_available())
        torch.save(x, "t.pt"); print("load", torch.load("t.pt", "cuda:0").device.type if True else "")
        print("forward", m(torch.ones(1, 2)).shape)
    """)

    def run(shimmed):
        boot = f"import site; site.addsitedir({str(site)!r})\n" if shimmed else ""
        return subprocess.run([REAL_PY, "-c", boot + probe], capture_output=True, text=True, timeout=300, cwd=tmp_path)

    plain = run(False)
    assert plain.returncode != 0 and "Torch not compiled with CUDA enabled" in plain.stderr
    shimmed = run(True)
    assert shimmed.returncode == 0, shimmed.stderr[-1500:]
    assert "types cpu cpu cpu True True" in shimmed.stdout and "avail False" in shimmed.stdout and "load cpu" in shimmed.stdout
    assert "forward torch.Size([1, 2])" in shimmed.stdout
    # every shimmed device is THE cpu device: no `cpu:0` that would not compare equal to a tensor's own `cpu` (found by the independent review)
    assert "index True True cpu" in shimmed.stdout
    assert {"tensor.cuda", "module.cuda", "torch.device", "tensor.to", "module.to"} <= set(runner_hooks.shim_paths_fired(shimmed.stderr))


@pytest.mark.skipif(not REAL_PY or not Path(REAL_PY).exists(), reason="set RERUN_REAL_TORCH_PYTHON to an interpreter with torch (CPU) installed")
def test_on_real_torch_what_already_worked_on_the_cpu_still_works_with_the_shim(tmp_path):
    """Found on real torch (WSL, torch 2.14, 2026-10-01): the first proxy class broke `pickle.dumps(torch.device("cpu"))`
    (PicklingError: attribute lookup device on rerun_cpu_shim failed). The proxy is now named torch.device. Every line below passes on plain torch."""
    site = tmp_path / "site"
    site.mkdir()
    (site / "rerun_cpu_shim.py").write_text(runner_hooks.source_of(runner_hooks.CPU_SHIM), encoding="utf-8")
    (site / "rerun_cpu_shim.pth").write_text("import rerun_cpu_shim\n", encoding="utf-8")
    probe = textwrap.dedent("""
        import argparse, copy, pickle, torch
        d = torch.device("cpu")

        def saved_model():
            m = torch.nn.Linear(2, 2)
            m.device = d
            torch.save(m, "m.pt")
            return torch.load("m.pt", weights_only=False).device == d

        checks = {
            "isinstance": isinstance(d, torch.device) and isinstance(torch.zeros(1).device, torch.device),
            "cpu_index": str(torch.device("cpu", 0)) == "cpu:0",
            "device_of_device": str(torch.device(torch.device("cpu"))) == "cpu",
            "pickle": pickle.loads(pickle.dumps(d)) == d,
            "deepcopy": copy.deepcopy(d) == d,
            "to_dtype": torch.ones(2).to(torch.float64).dtype == torch.float64,
            "to_tensor": torch.ones(2).to(torch.zeros(2, dtype=torch.float64)).dtype == torch.float64,
            "to_cpu_kwargs": torch.ones(2).to("cpu", dtype=torch.float64, non_blocking=True).dtype == torch.float64,
            "module_to_dtype": torch.nn.Linear(2, 2).to(torch.float64).weight.dtype == torch.float64,
            "module_to_format": torch.nn.Conv2d(1, 1, 1).to(memory_format=torch.channels_last).weight.dim() == 4,
            "to_cpu_device": torch.ones(2).to(d).device.type == "cpu",
            "dataloader": len(list(torch.utils.data.DataLoader(torch.arange(4), batch_size=2))) == 2,
            "dataparallel": type(torch.nn.DataParallel(torch.nn.Linear(2, 2))).__name__ == "DataParallel",
            "forward": tuple(torch.nn.Linear(2, 2)(torch.ones(1, 2)).shape) == (1, 2),
            "class_attribute": hasattr(torch.device, "type") and hasattr(torch.device, "index"),
            "save_namespace_with_device": (torch.save(argparse.Namespace(device=d, lr=0.1), "ns.pt"),
                                           torch.load("ns.pt", weights_only=False).device == d)[1],
            "save_module_with_device_attribute": saved_model(),
        }
        print("BAD", sorted(k for k, ok in checks.items() if not ok))
    """)

    def run(shimmed):
        boot = f"import site; site.addsitedir({str(site)!r})\n" if shimmed else ""
        return subprocess.run([REAL_PY, "-c", boot + probe], capture_output=True, text=True, timeout=300, cwd=tmp_path)

    plain = run(False)
    assert plain.returncode == 0 and "BAD []" in plain.stdout, plain.stderr[-1500:] + plain.stdout
    shimmed = run(True)
    assert shimmed.returncode == 0, shimmed.stderr[-1500:]
    assert "BAD []" in shimmed.stdout, shimmed.stdout  # a name listed here is something the shim broke
