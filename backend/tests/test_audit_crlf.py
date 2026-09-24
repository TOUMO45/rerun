"""The retroactive CRLF audit (scripts/audit_crlf.py) — its rules, on
synthetic records shaped like the committed ones."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("audit_crlf", ROOT / "scripts" / "audit_crlf.py")
audit_crlf = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit_crlf)


def _record(execute_command, stderr="", origin=None, tree=None):
    attempt = {"attempt_number": 1, "stdout_tail": "", "stderr_tail": stderr, "gate_decision": "DECLINED"}
    if origin:
        attempt["origin"] = origin
    cert = {"build_plan": {"execute_command": execute_command, "install_commands": ["pip install -r requirements.txt"]},
            "full_log": "", "diffs": [attempt]}
    if tree:
        cert["tree_integrity"] = tree
    return {"certificate": cert, "result": {"verdict": "BLOCKED"}}


def test_shell_script_execution_is_invalidated():
    out = audit_crlf.audit(_record("bash run_ttpt.sh"))
    assert out["invalidated_by"] == "crlf-clone-bug" and "run_ttpt.sh" in out["invalidation_reason"]


def test_shell_symptom_in_output_is_invalidated():
    out = audit_crlf.audit(_record("python train.py", stderr="run.sh: line 2: set: pipefail\\r: invalid option name"))
    assert out["invalidated_by"] == "crlf-clone-bug"


def test_python_only_run_is_not_affected():
    out = audit_crlf.audit(_record("python train.py", stderr="ModuleNotFoundError: No module named 'torch'"))
    assert "invalidated_by" not in out and out["crlf_audit"].startswith("not affected")


def test_progress_bar_carriage_returns_are_not_evidence():
    """gpt-2 v4: tqdm redraws with a bare \\r — not a CRLF artifact."""
    out = audit_crlf.audit(_record("python3 download_model.py 124M", stderr=" 47%|###   | 213k/456k\rFetching"))
    assert "invalidated_by" not in out


def test_crlf_pairs_in_output_are_evidence():
    out = audit_crlf.audit(_record("python train.py", stderr="line one\r\nline two"))
    assert out["invalidated_by"] == "crlf-clone-bug"


def test_runs_after_the_fix_are_not_applicable():
    out = audit_crlf.audit(_record("bash run.sh", tree={"status": "verified", "tree_sha": "t"}))
    assert out["crlf_audit"].startswith("not applicable")


def test_repair_mode_tags():
    assert audit_crlf.repair_mode(_record("x")) == "model_assisted"  # legacy attempts had no origin
    assert audit_crlf.repair_mode(_record("x", origin="time_machine")) == "deterministic"
    assert audit_crlf.repair_mode({"certificate": {"diffs": []}}) == "deterministic"


def test_committed_records_carry_the_audit():
    records = {p.name: json.loads(p.read_text(encoding="utf-8")) for p in (ROOT / "runs").glob("*.json")}
    assert records["live_run_ttpt_v4.json"]["invalidated_by"] == "crlf-clone-bug"
    assert "invalidated_by" not in records["live_run_gpt2_v4.json"]
    assert all(r.get("repair_mode") in ("deterministic", "model_assisted") for r in records.values())
