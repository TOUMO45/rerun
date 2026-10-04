"""harness-v1.7, R1 (c): the memory hook on REAL torch (CPU wheel), kept apart from test_v17_memory.py so it runs where only torch is installed
(RERUN_REAL_TORCH_PYTHON, run under WSL as test_v151_cuda_set_device.py is: `python3 -m pytest backend/tests/test_v17_memory_hook_real_torch.py --noconftest`)."""

from __future__ import annotations

import os
import subprocess
import textwrap
from pathlib import Path

import pytest

from app.services import runner_hooks

# --- on real torch ------------------------------------------------------------------------------------------------------------------------------

REAL_PY = os.environ.get("RERUN_REAL_TORCH_PYTHON")
CHECKS = r'''
import sys, warnings
warnings.simplefilter("ignore")
import torch
from torch.utils.data import DataLoader, Dataset

class Ds(Dataset):
    def __len__(self):
        return 37
    def __getitem__(self, i):
        return i

def order(**kw):
    loader = DataLoader(Ds(), batch_size=4, shuffle=True, generator=torch.Generator().manual_seed(0), **kw)
    return loader, [b.tolist() for b in loader]

hooked, got = order(num_workers=2, pin_memory=True, prefetch_factor=2, persistent_workers=True, timeout=5)
assert hooked.num_workers == 0 and hooked.pin_memory is False and hooked.timeout == 0
default_loader, _ = order()
assert default_loader.num_workers == 0
print("ORDER", got)
'''


@pytest.mark.skipif(not REAL_PY or not Path(REAL_PY).exists(), reason="set RERUN_REAL_TORCH_PYTHON to an interpreter with torch (CPU) installed")
def test_on_real_torch_the_hook_drops_workers_keeps_the_order_and_lives_beside_the_cpu_shim(tmp_path):
    site = tmp_path / "site"
    site.mkdir()
    for name in (runner_hooks.CPU_SHIM, runner_hooks.MEMORY_HOOK):
        (site / f"rerun_{name}.py").write_text(runner_hooks.source_of(name), encoding="utf-8")
        (site / f"rerun_{name}.pth").write_text(f"import rerun_{name}\n", encoding="utf-8")
    hooked = subprocess.run([REAL_PY, "-c", f"import site; site.addsitedir({str(site)!r})\n" + textwrap.dedent(CHECKS)],
                            capture_output=True, text=True, timeout=600, cwd=tmp_path)
    assert hooked.returncode == 0, hooked.stderr[-3000:]
    assert runner_hooks.memory_hook_changes(hooked.stderr) == ["DataLoader num_workers 2->0", "DataLoader pin_memory True->False"]
    assert "RERUN_CPU_SHIM: injected by RERUN" in hooked.stderr  # both hooks patched the same torch import
    plain = subprocess.run([REAL_PY, "-c", textwrap.dedent(CHECKS).replace("assert hooked.num_workers == 0 and hooked.pin_memory is False and hooked.timeout == 0", "")],
                           capture_output=True, text=True, timeout=600, cwd=tmp_path)
    assert plain.returncode == 0, plain.stderr[-3000:]
    assert hooked.stdout.split("ORDER", 1)[1] == plain.stdout.split("ORDER", 1)[1]  # the same samples in the same order with 2 workers and with none


LEFT_ALONE = r'''
import warnings
warnings.simplefilter("ignore")
import torch
from torch.utils.data import DataLoader, IterableDataset

class Stream(IterableDataset):
    def __iter__(self):
        return iter(range(6))

it = DataLoader(Stream(), batch_size=2, num_workers=2)
print("ITERABLE", it.num_workers, sum(len(b) for b in it))
init = DataLoader(list(range(6)), batch_size=2, num_workers=2, worker_init_fn=lambda wid: None)
print("INIT", init.num_workers)
'''


@pytest.mark.skipif(not REAL_PY or not Path(REAL_PY).exists(), reason="set RERUN_REAL_TORCH_PYTHON to an interpreter with torch (CPU) installed")
def test_on_real_torch_an_iterable_dataset_or_a_worker_init_fn_is_left_as_is(tmp_path):
    """v1.7 review, H2: an unsharded IterableDataset yields once PER WORKER, and a worker_init_fn sets up each worker: the hook does not touch them."""
    site = tmp_path / "site"
    site.mkdir()
    (site / "rerun_memory_hook.py").write_text(runner_hooks.source_of(runner_hooks.MEMORY_HOOK), encoding="utf-8")
    (site / "rerun_memory_hook.pth").write_text("import rerun_memory_hook\n", encoding="utf-8")
    done = subprocess.run([REAL_PY, "-c", f"import site; site.addsitedir({str(site)!r})\n" + textwrap.dedent(LEFT_ALONE)],
                          capture_output=True, text=True, timeout=600, cwd=tmp_path)
    assert done.returncode == 0, done.stderr[-3000:]
    assert "ITERABLE 2 12" in done.stdout and "INIT 2" in done.stdout  # two workers, each yielding the whole stream: as without the hook
    assert runner_hooks.memory_hook_changes(done.stderr) == ["DataLoader left as is (IterableDataset, num_workers 2)",
                                                             "DataLoader left as is (worker_init_fn, num_workers 2)"]
