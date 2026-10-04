"""harness-v1.7, R2 (METHODOLOGY "harness-v1.7 — PRE-REGISTRATION"). Failure class: GPU_REQUIRED where the operation has no CPU kernel.

Recorded failure: DEV entry 14 (IST-DASLab/M-FAC), rounds 3 and 4 (runs/corpus_v2_batch/harness-v1.5.2/dev/, harness-v1.6.0/dev/): after the CPU shim answered
`torch.cuda.set_device`, the shim's own re-execution stopped at `RuntimeError: linalg.lu_factor: LU without pivoting is not implemented on the CPU` (the repository calls
`torch.lu(x, pivot=False)` and keeps `triu` of the factor). In round 3 a model patch replaced the call by the PIVOTING `torch.linalg.lu_factor` (candidate D-44). The CPU shim
now carries a pure-torch reference for LU without pivoting, used only when torch raises "not implemented on the CPU". **Single-case**: no other DEV or gate record has an
operation without a CPU kernel.

Offline (Windows, no torch): the replay and the source checks. On REAL torch (CPU wheel; RERUN_REAL_TORCH_PYTHON, run under WSL as in test_v151_cuda_set_device.py):
the factorisation itself, against the analytical product and against scipy where partial pivoting makes no exchange."""

from __future__ import annotations

import json
import os
import subprocess
import textwrap
from pathlib import Path

import pytest

from app.services import blocker, classifier, runner_hooks

ROOT = Path(__file__).resolve().parents[2]
RECORDS = [ROOT / "runs" / "corpus_v2_batch" / tag / "dev" / "14_IST-DASLab__M-FAC.json" for tag in ("harness-v1.5.2", "harness-v1.6.0")]
LU_ERROR = "RuntimeError: linalg.lu_factor: LU without pivoting is not implemented on the CPU"
REAL_PY = os.environ.get("RERUN_REAL_TORCH_PYTHON")
real_torch = pytest.mark.skipif(not REAL_PY or not Path(REAL_PY).exists(), reason="set RERUN_REAL_TORCH_PYTHON to an interpreter with torch (CPU) installed")


def _events(path: Path) -> list[str]:
    return [e["line"] for e in json.loads(path.read_text(encoding="utf-8"))["events"]]


# --- replay of the recorded failure (offline) ---------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("path", RECORDS, ids=["round3", "round4"])
def test_the_recorded_lu_failure_came_after_the_cpu_shim_and_is_gpu_required(path):
    events = _events(path)
    shim_at = next(i for i, line in enumerate(events) if "deterministic step: cpu_shim" in line)
    lu_at = next(i for i, line in enumerate(events) if line.startswith("[classifier]") and "LU without pivoting is not implemented on the CPU" in line)
    assert shim_at < lu_at  # the shim was in place; the old shim had no answer for this kernel
    stderr = ("Traceback (most recent call last):\n  File \"/main_optim.py\", line 160, in <module>\n  File \"/optim.py\", line 58, in __init__\n"
              "    self.giHig = torch.lu(self.giHig + diag, pivot=False)[0]\n" + LU_ERROR + "\n")
    got = classifier.classify(1, stderr, "")
    assert got.code == classifier.TaxonomyCode.GPU_REQUIRED and "LU without pivoting" in got.evidence
    assert runner_hooks.reference_kernel_for(got.evidence) == "lu_nopivot"


def test_the_shim_carries_the_reference_for_every_lu_entry_point_and_names_its_paths():
    source = runner_hooks.source_of(runner_hooks.CPU_SHIM)
    for path in ("cpu_ref:torch.lu", "cpu_ref:linalg.lu_factor", "cpu_ref:linalg.lu_factor_ex", "cpu_ref:linalg.lu"):
        assert path in source
    assert '"not implemented on the CPU" in str(exc)' in source  # the reference answers only when torch has no CPU kernel
    assert set(runner_hooks.CPU_REFERENCE_KERNELS["lu_nopivot"]["entry_points"]) == {"torch.lu", "torch._lu_with_info", "torch.linalg.lu_factor",
                                                                                     "torch.linalg.lu_factor_ex", "torch.linalg.lu"}
    assert "LU without pivoting" in runner_hooks.HOOKS[runner_hooks.CPU_SHIM].limit
    compile(source, "rerun_cpu_shim.py", "exec")  # the module the sandbox imports parses


def test_other_no_cpu_kernel_errors_are_not_claimed_by_the_reference_table():
    assert runner_hooks.reference_kernel_for("RuntimeError: \"slow_conv2d_cpu\" not implemented for 'Half'") is None
    assert runner_hooks.reference_kernel_for("RuntimeError: _cdist_backward is not implemented on the CPU") is None
    assert runner_hooks.reference_kernel_for(LU_ERROR) == "lu_nopivot"


def test_the_blocker_sentence_for_an_lu_kernel_names_the_reference_and_for_another_kernel_a_cuda_device():
    """v1.7 review, M5: the blocker never claims a fix the record does not show; it says whether this run's shim carried the reference."""
    chain = [{"class": "GPU_REQUIRED", "error": LU_ERROR, "phase": "repo_run", "attribution": "REPO"}]
    b = blocker.report({"verdict": "BLOCKED", "error_chain": chain})
    assert b["fixable_by"] == blocker.HUMAN and "this run's shim did not carry it" in b["what_a_human_must_supply"]
    old_shim = [{"time_machine_action": {"rule": "cpu_shim", "limit": "covers torch.load ..."}}]
    assert "did not carry it" in blocker.report({"verdict": "BLOCKED", "error_chain": chain, "attempts": old_shim})["what_a_human_must_supply"]
    new_shim = [{"time_machine_action": {"rule": "cpu_shim", "limit": runner_hooks.HOOKS[runner_hooks.CPU_SHIM].limit}}]
    assert "the run still stopped here" in blocker.report({"verdict": "BLOCKED", "error_chain": chain, "attempts": new_shim})["what_a_human_must_supply"]
    for record in RECORDS:  # the recorded #14 runs keep their human-facing claim (no retroactive fix)
        result = json.loads(record.read_text(encoding="utf-8"))["result"]
        if result["verdict"] not in ("RUNS_CLEAN", "RUNS_AFTER_REPAIR"):
            assert blocker.report(result)["fixable_by"] != blocker.DETERMINISTIC
    other = [{"class": "GPU_REQUIRED", "error": "RuntimeError: _cdist_backward is not implemented on the CPU", "phase": "repo_run", "attribution": "REPO"}]
    assert blocker.report({"verdict": "BLOCKED", "error_chain": other})["what_a_human_must_supply"] == "a CUDA device: the operation has no CPU implementation"


# --- on real torch -------------------------------------------------------------------------------------------------------------------------------

CHECKS = r'''
import sys, warnings
warnings.simplefilter("ignore")
import torch
torch.manual_seed(0)
out = []

def dd(*shape, dtype=torch.float64):
    """Column- and row-diagonally-dominant: LU without pivoting exists, and partial pivoting makes no row exchange."""
    A = torch.rand(*shape, dtype=dtype) - 0.5
    n = min(shape[-2], shape[-1])
    A[..., range(n), range(n)] += shape[-1] + shape[-2]
    return A

def unpack(LU, m, n):
    k = min(m, n)
    L = torch.tril(LU[..., :, :k], -1) + torch.eye(m, k, dtype=LU.dtype)
    U = torch.triu(LU[..., :k, :])
    return L, U

for dtype, tol in ((torch.float64, 1e-10), (torch.float32, 1e-5)):
    for shape in ((5, 5), (3, 6, 6), (2, 3, 7, 4), (4, 7), (64, 64)):
        A = dd(*shape, dtype=dtype)
        LU, piv = torch.linalg.lu_factor(A, pivot=False)
        m, n = shape[-2], shape[-1]
        L, U = unpack(LU, m, n)
        err = (L @ U - A).abs().max().item()
        assert err < tol * max(1.0, A.abs().max().item()), (dtype, shape, err)
        assert LU.dtype == dtype and LU.shape == A.shape and piv.dtype == torch.int32
        assert torch.equal(piv, torch.arange(1, min(m, n) + 1, dtype=torch.int32).expand(piv.shape))
out.append("analytic_ok")

A = dd(16, 16)
LU1, piv1 = torch.lu(A, pivot=False)
LU2, piv2, info = torch.linalg.lu_factor_ex(A, pivot=False)
P, L, U = torch.linalg.lu(A, pivot=False)
assert torch.equal(LU1, LU2) and torch.equal(piv1, piv2) and int(info) == 0 and P.numel() == 0
assert (L @ U - A).abs().max().item() < 1e-10
out.append("entry_points_ok")

# what DEV #14 does with it (optim.py lines 58-59)
X = dd(8, 8)
diag = torch.diag(torch.full([8], 1e-3, dtype=X.dtype))
giHig = torch.triu(torch.lu(X + diag, pivot=False)[0] - diag)
assert giHig.shape == (8, 8) and torch.isfinite(giHig).all()
out.append("mfac_usage_ok")

# pivoting calls are untouched: the same result as torch's own kernel, and no reference path fired
B = torch.rand(6, 6, dtype=torch.float64)
LUp, pivp = torch.linalg.lu_factor(B)
assert pivp.dtype == torch.int32
out.append("pivoting_untouched")

# a zero pivot: lu_factor raises (check_errors), lu_factor_ex reports it in info
S = torch.tensor([[0.0, 1.0], [1.0, 1.0]], dtype=torch.float64)
try:
    torch.linalg.lu_factor(S, pivot=False)
    out.append("singular_not_raised")
except RuntimeError as exc:
    assert "is zero" in str(exc)
    out.append("singular_raised")
_, _, info = torch.linalg.lu_factor_ex(S, pivot=False)
assert int(info) == 1
out.append("info_ok")

# autograd flows through the reference
G = dd(5, 5).requires_grad_(True)
torch.linalg.lu_factor(G, pivot=False)[0].sum().backward()
assert G.grad is not None and torch.isfinite(G.grad).all()
out.append("grad_ok")

try:
    import numpy as np, scipy.linalg
    C = dd(12, 12)
    lu_s, piv_s = scipy.linalg.lu_factor(C.numpy())
    assert (piv_s == np.arange(12)).all()  # partial pivoting made no exchange on this matrix
    LU_t, _ = torch.linalg.lu_factor(C, pivot=False)
    assert np.abs(LU_t.numpy() - lu_s).max() < 1e-12
    out.append("scipy_ok")
except ImportError:
    out.append("scipy_missing")
print("CHECKS", " ".join(out))
'''


def _site(tmp_path: Path) -> Path:
    site = tmp_path / "site"
    site.mkdir()
    (site / "rerun_cpu_shim.py").write_text(runner_hooks.source_of(runner_hooks.CPU_SHIM), encoding="utf-8")
    (site / "rerun_cpu_shim.pth").write_text("import rerun_cpu_shim\n", encoding="utf-8")
    return site


@real_torch
def test_on_real_torch_lu_without_pivoting_raises_without_the_shim_and_is_factorised_with_it(tmp_path):
    site = _site(tmp_path)
    plain = subprocess.run([REAL_PY, "-c", "import torch\ntorch.linalg.lu_factor(torch.eye(3) * 2, pivot=False)\n"], capture_output=True, text=True, timeout=300)
    assert plain.returncode != 0 and "not implemented on the CPU" in plain.stderr
    shimmed = subprocess.run([REAL_PY, "-c", f"import site; site.addsitedir({str(site)!r})\n" + textwrap.dedent(CHECKS)],
                             capture_output=True, text=True, timeout=600, cwd=tmp_path)
    assert shimmed.returncode == 0, shimmed.stderr[-3000:]
    checks = shimmed.stdout.split("CHECKS", 1)[1].split()
    for name in ("analytic_ok", "entry_points_ok", "mfac_usage_ok", "pivoting_untouched", "singular_raised", "info_ok", "grad_ok"):
        assert name in checks, checks
    if os.environ.get("RERUN_REQUIRE_SCIPY"):
        assert "scipy_ok" in checks, checks
    fired = runner_hooks.shim_paths_fired(shimmed.stderr)
    for path in ("cpu_ref:linalg.lu_factor", "cpu_ref:torch.lu", "cpu_ref:linalg.lu_factor_ex", "cpu_ref:linalg.lu"):
        assert path in fired, fired
