"""scripts/write_seal_verification_v142.py: option B over CHANGED files only. An entry whose code files are unchanged since its live verification is carried over from
harness-v1.4.1; an entry that lists a changed file must be re-verified or the writer stops; the file it writes satisfies the batch driver's seal rule."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import run_corpus_v1_batch as drv  # noqa: E402

HOOK_ENTRIES = {"runner_hooks_on_a_kept_image", "exit_hook_gap_and_exit_wrapper", "exit_wrapper_python36"}


def _writer():
    spec = importlib.util.spec_from_file_location("write_seal_verification_v142", ROOT / "scripts" / "write_seal_verification_v142.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_with_the_real_files_only_the_three_hooks_entries_of_v141_need_re_verification():
    """The v1.4.1 tag's seal_verification.json against the current files: runner_hooks.py changed again (shim, evidence), nothing else sandbox-touching did."""
    writer = _writer()
    previous = writer.previous_entries()
    listing_hooks = {e["id"] for e in previous if writer.HOOKS in e["code_files"]}
    assert listing_hooks == HOOK_ENTRIES and len(previous) == 16
    replaced = {pid for pid, *_ in writer.PATHS}
    assert HOOK_ENTRIES <= replaced and replaced - HOOK_ENTRIES == {"resource_evidence_after_a_kill"}
    kept, notes = writer.carried_over(replaced)
    assert {e["id"] for e in kept} == {e["id"] for e in previous} - HOOK_ENTRIES and len(kept) == 13
    assert {"additive_apt_layer_on_a_kept_image", "resume_from_the_layer_of_a_killed_operation", "kill_at_operation_limit", "smoke_launcher"} <= {e["id"] for e in kept}
    with pytest.raises(SystemExit, match="runner_hooks.py.*no v1.4.2 verification"):
        writer.carried_over(set())  # the changed file without a replacement: the writer stops


def test_a_synthetic_seal_passes_the_batch_drivers_seal_rule(tmp_path, monkeypatch):
    writer = _writer()
    blobs = {f: f"blob-{Path(f).name}" for f in drv.SANDBOX_TOUCHING_FILES}
    monkeypatch.setattr(writer, "ROOT", tmp_path)
    monkeypatch.setattr(writer, "blob", lambda path: blobs[path])
    monkeypatch.setattr(writer, "NEW", "runs/new")

    def record(rel, run_id):
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"ok": True, "run_id": run_id}), encoding="utf-8")

    old = [{"id": f"old_{i}", "description": "d", "live_nebius": True, "code_files": {f: blobs[f]}, "records": [f"runs/old/{i}.json"], "run_ids": [f"r{i}"]}
           for i, f in enumerate(f for f in drv.SANDBOX_TOUCHING_FILES if not f.endswith("runner_hooks.py"))]
    for e in old:
        record(e["records"][0], e["run_ids"][0])
    for pid in HOOK_ENTRIES:
        old.append({"id": pid, "description": "d", "live_nebius": True, "code_files": {writer.SB: blobs[writer.SB], writer.HOOKS: "blob-OLD-hooks"},
                    "records": [f"runs/old/{pid}.json"], "run_ids": [pid]})
        record(f"runs/old/{pid}.json", pid)
    monkeypatch.setattr(writer, "previous_entries", lambda: old)
    monkeypatch.setattr(writer, "PATHS", [(pid, d, files, [rel.replace("runs/sandbox_verification/v1.4.2-seal", "runs/new") for rel in recs])
                                          for pid, d, files, recs in writer.PATHS])
    for _, _, _, records in writer.PATHS:
        for rel in records:
            record(rel, f"id-{Path(rel).stem}")
    assert writer.main() == 0
    doc = json.loads((tmp_path / "seal_verification.json").read_text(encoding="utf-8"))
    assert doc["harness_tag"] == "harness-v1.4.2" and doc["carried_over_from"] == "harness-v1.4.1"
    ids = [e["id"] for e in doc["paths"]]
    assert "old_0" in ids and all(ids.count(pid) == 1 for pid in HOOK_ENTRIES) and "resource_evidence_after_a_kill" in ids
    hooks = next(e for e in doc["paths"] if e["id"] == "runner_hooks_on_a_kept_image")
    assert hooks["code_files"][writer.HOOKS] == "blob-runner_hooks.py" and hooks["records"][0].startswith("runs/new/")
    drv.check_seal_verification(tmp_path, lambda p: blobs[p])  # the preflight's seal rule accepts it


def test_a_failed_new_record_stops_the_writer(tmp_path, monkeypatch):
    writer = _writer()
    monkeypatch.setattr(writer, "ROOT", tmp_path)
    monkeypatch.setattr(writer, "blob", lambda path: "b")
    rel = writer.PATHS[0][3][0]
    (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / rel).write_text(json.dumps({"ok": False, "run_id": "x"}), encoding="utf-8")
    with pytest.raises(SystemExit, match="not a passing live record"):
        writer.main()
