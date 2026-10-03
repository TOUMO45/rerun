"""Seal of harness-v1.5.1 (option B over CHANGED files; METHODOLOGY "harness-v1.5 dev/test protocol", rule G): live checks of what v1.5.1 changed in the sandbox-touching files.

    backend/.venv/Scripts/python.exe reports/corpus-v2.1/v1.5/seal/run_seal_v151.py                           # PLAN: what would run, cost of the same checks in the v1.4.3 seal
    backend/.venv/Scripts/python.exe reports/corpus-v2.1/v1.5/seal/run_seal_v151.py --go --max-usd X          # spends money (the DEV total counts it)

Among the sandbox-touching files (scripts/run_corpus_v1_batch.py SANDBOX_TOUCHING_FILES) harness-v1.5.1 changes `runner_hooks.py` ONLY (F3: the CPU shim's `torch.cuda.set_device`
does nothing). `sandbox.py`, `sandbox_limits.py`, `runner_env.py` and `smoke_exec.py` are byte-identical to harness-v1.4.3, so the 15 entries of the v1.4.3 seal that do not list
`runner_hooks.py` stay valid (reports/corpus-v2.1/v1.5/seal/write_seal_verification_v151.py carries them over only if their blobs still match). The 4 entries that DO list it are
re-verified by the same checks the v1.4.3 seal ran for them (its `v142` stage: the hooks on a kept image, the exit hook gap and the exit wrapper on 3.10 and 3.6, the evidence
command after a calm run and a self-SIGKILL), live, through the real runner, against the new blob. The shim's own new path is checked against REAL torch offline
(backend/tests/test_v151_cuda_set_device.py with RERUN_REAL_TORCH_PYTHON), as the v1.4.2 seal did for the shim's earlier paths: a torch install would cost more than this whole seal.

This wrapper reuses the v1.4.3 seal driver unchanged and points it at this seal's directory (runs/sandbox_verification/v1.5.1-seal/), the release candidate tag harness-v1.5.1-rc
and the one stage. Never runs without --go and --max-usd.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
_spec = importlib.util.spec_from_file_location("run_seal_v143", ROOT / "reports" / "corpus-v2.1" / "v1.4.3" / "seal" / "run_seal_v143.py")
base = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(base)

OUT = ROOT / "runs" / "sandbox_verification" / "v1.5.1-seal"
RC_TAG = "harness-v1.5.1-rc"
MAX_SEAL_USD = 0.30  # the v1.4.3 seal's v142 stage cost $0.0196; the cap leaves room for a retry of a stopped step


def configure() -> None:
    base.OUT = OUT
    base.RC_TAG = RC_TAG
    base.MAX_SEAL_USD = MAX_SEAL_USD
    base.STAGES = ("v142",)
    base.RUNNERS = {"v142": base.run_v142}
    original_plan = base.plan
    base.plan = lambda: [row for row in original_plan() if row["stage"] == "v142"]


configure()


def main(argv: list[str] | None = None) -> int:
    return base.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
