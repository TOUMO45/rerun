"""Seal of harness-v1.7.2: every live stage of the harness-v1.7.1 seal, run again against harness-v1.7.2-rc (owner, chat 2026-10-05: "a real paid seal
(all live checks)").

The five sandbox-touching files (scripts/run_corpus_v1_batch.py SANDBOX_TOUCHING_FILES) are byte-identical to harness-v1.7.1: harness-v1.7.2 changes the
orchestrator (D-45, D-46, D-47, D-48, entry blockers, the sole-candidate rule), intake (module-level scripts; the repo-URL check), the routers and the UI. Option B
would carry the v1.7.1 records over; the owner asked for the live checks to run again, so this is a full re-verification at the new commit, not a check of new
sandbox code. Stages, checks, estimates and the $1.50 cap are the v1.7.1 seal's (reports/corpus-v2.1/v1.7/seal/run_seal_v17.py), unchanged; only the release-
candidate tag and the record folder differ.

    backend/.venv/Scripts/python.exe reports/corpus-v2.1/v1.7.2/seal/run_seal_v172.py                                   # PLAN: what would run, ESTIMATED cost
    backend/.venv/Scripts/pythonw.exe reports/corpus-v2.1/v1.7.2/seal/run_seal_v172.py --go --max-usd 1.50 --log-file F # live (launch_seal.cmd, Task Scheduler)
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
_spec = importlib.util.spec_from_file_location("run_seal_v17", ROOT / "reports" / "corpus-v2.1" / "v1.7" / "seal" / "run_seal_v17.py")
v17 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(v17)

v17.OUT = ROOT / "runs" / "sandbox_verification" / "v1.7.2-seal"
v17.RC_TAG = "harness-v1.7.2-rc"
v17.configure()  # hands the new folder and tag to the v1.4.3 driver the v1.7.1 seal reuses

if __name__ == "__main__":
    raise SystemExit(v17.main(sys.argv[1:]))
