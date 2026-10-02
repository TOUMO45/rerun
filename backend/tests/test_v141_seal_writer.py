"""scripts/write_seal_verification_v141.py: option B over CHANGED files only. An entry whose code files are unchanged since its live
verification is carried over from harness-v1.4.0; an entry that lists a changed file must be re-verified or the writer stops; the file it
writes satisfies the batch driver's seal rule (`check_seal_verification`)."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import run_corpus_v1_batch as drv  # noqa: E402


def _writer():
    spec = importlib.util.spec_from_file_location("write_seal_verification_v141", ROOT / "scripts" / "write_seal_verification_v141.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _tag_blob(tag: str):
    """`git hash-object` of a file as it was at `tag`: these two tests describe the state of their own version, not of the worktree, which moves on."""
    import subprocess

    return lambda path: subprocess.run(["git", "rev-parse", f"{tag}:{path}"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()


def test_with_the_real_files_only_the_hooks_entry_of_v140_needs_re_verification(monkeypatch):
    """The v1.4.0 tag's seal_verification.json against the current files: runner_hooks.py changed (the exit wrapper), nothing else
    sandbox-touching did, so exactly the entries listing it are replaced and the rest are carried over."""
    writer = _writer()
    monkeypatch.setattr(writer, "blob", _tag_blob("harness-v1.4.1"))  # the files as they were at harness-v1.4.1
    previous = writer.previous_entries()
    ids = {e["id"] for e in previous}
    listing_hooks = {e["id"] for e in previous if writer.HOOKS in e["code_files"]}
    assert listing_hooks == {"runner_hooks_on_a_kept_image"} and len(previous) == 12
    kept, notes = writer.carried_over(listing_hooks)
    assert {e["id"] for e in kept} == ids - listing_hooks and len(kept) == 11
    with pytest.raises(SystemExit, match="runner_hooks.py.*no v1.4.1 verification"):
        writer.carried_over(set())  # the changed file without a replacement: the writer stops
    for unchanged in ("sandbox.py", "sandbox_limits.py", "runner_env.py", "smoke_exec.py"):
        assert not any(unchanged in n and "changed" in n for n in notes)


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

    old = [{"id": f"old_{i}", "description": "d", "live_nebius": True, "code_files": {f: blobs[f]}, "records": [f"runs/old/{i}.json"],
            "run_ids": [f"r{i}"]} for i, f in enumerate(f for f in drv.SANDBOX_TOUCHING_FILES if not f.endswith("runner_hooks.py"))]
    for e in old:
        record(e["records"][0], e["run_ids"][0])
    old.append({"id": "runner_hooks_on_a_kept_image", "description": "d", "live_nebius": True,
                "code_files": {writer.SB: blobs[writer.SB], writer.HOOKS: "blob-OLD-hooks"}, "records": ["runs/old/h.json"], "run_ids": ["rh"]})
    record("runs/old/h.json", "rh")
    monkeypatch.setattr(writer, "previous_entries", lambda: old)
    monkeypatch.setattr(writer, "PATHS", [(pid, d, files, [rel.replace("runs/sandbox_verification/v1.4.1-seal", "runs/new") for rel in recs])
                                          for pid, d, files, recs in writer.PATHS])
    for _, _, _, records in writer.PATHS:
        for rel in records:
            record(rel, f"id-{Path(rel).stem}")
    assert writer.main() == 0
    doc = json.loads((tmp_path / "seal_verification.json").read_text(encoding="utf-8"))
    assert doc["harness_tag"] == "harness-v1.4.1" and doc["carried_over_from"] == "harness-v1.4.0"
    ids = [e["id"] for e in doc["paths"]]
    assert "old_0" in ids and ids.count("runner_hooks_on_a_kept_image") == 1  # the old hooks entry is replaced, not duplicated
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
