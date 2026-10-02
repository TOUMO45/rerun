"""The v1.4.3 gate runner's `--resume` and `--log-file` (reports/corpus-v2.1/v1.4.3/gate/run_gate_v143.py), added after the gate's process was killed inside entry 8 (INTERRUPTED_ATTEMPT.md).
Kept here and not in backend/tests: the batch driver's preflight refuses to start a gate when any file outside its data allowlist changed since the sealed tag, and a test file under
backend/tests is outside it. Run with `backend/.venv/Scripts/python.exe -m pytest reports/corpus-v2.1/v1.4.3/gate/test_run_gate_v143_resume.py -q`."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]


def _gates():
    spec = importlib.util.spec_from_file_location("g143_resume", ROOT / "reports" / "corpus-v2.1" / "v1.4.3" / "gate" / "run_gate_v143.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return (None, None, module)


# --- --resume and --log-file: after the gate's process was killed in the middle of an entry ---------------------------------------------------

def test_resume_keeps_only_complete_records_of_the_same_entry_and_tag(tmp_path):
    g143 = _gates()[2]
    plan = [{"id": 3, "name": "a__a"}, {"id": 7, "name": "b__b"}, {"id": 8, "name": "c__c"}, {"id": 11, "name": "d__d"}]

    def write(name, doc):
        (tmp_path / name).write_text(json.dumps(doc) if not isinstance(doc, str) else doc, encoding="utf-8")

    good = {"batch": {"entry_id": 3, "harness_tag": "harness-v1.4.3"}, "result": {"verdict": "BLOCKED"}, "cost_guard": {"spent_usd": 0.5}}
    write("03_a__a.json", good)
    write("07_b__b.json", {**good, "batch": {"entry_id": 7, "harness_tag": "harness-v1.4.2"}})  # another tag
    write("08_c__c.json", {**good, "batch": {"entry_id": 8, "harness_tag": "harness-v1.4.3"}, "error": "PIPELINE_ERROR"})  # ended without a verdict
    write("11_d__d.json", "{ not json")
    assert set(g143.load_resumed(plan, tmp_path, "harness-v1.4.3")) == {"a__a"}
    write("07_b__b.json", {**good, "batch": {"entry_id": 3, "harness_tag": "harness-v1.4.3"}})  # the wrong entry id for this file
    write("08_c__c.json", {"batch": {"entry_id": 8, "harness_tag": "harness-v1.4.3"}, "result": {"verdict": None}})  # no verdict
    assert set(g143.load_resumed(plan, tmp_path, "harness-v1.4.3")) == {"a__a"}


def test_log_file_sends_everything_the_process_prints_to_a_file(tmp_path, monkeypatch, capsys):
    import sys

    g143 = _gates()[2]
    monkeypatch.setattr(sys, "stdout", sys.stdout)  # restored after the test
    monkeypatch.setattr(sys, "stderr", sys.stderr)
    log = tmp_path / "gate.log"
    assert g143.main(["--log-file", str(log), "--gate-cap-usd", "6.99", "--entry-cap-usd", "1.75"]) == 2  # a starved gate: refused, and the refusal goes to the file
    sys.stderr.flush()
    assert "starved" in log.read_text(encoding="utf-8")
