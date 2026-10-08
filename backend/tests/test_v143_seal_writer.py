"""scripts/write_seal_verification_v143.py: sandbox.py changed and every entry of the harness-v1.4.2 seal lists it, so every entry is re-verified (none carried over); the file it writes
satisfies the batch driver's seal rule (`check_seal_verification`); a stale blob, a missing stage or a failed record stops it."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import run_corpus_v1_batch as drv  # noqa: E402

NEW = "runs/sandbox_verification/v1.4.3-seal"


def _writer():
    spec = importlib.util.spec_from_file_location("write_seal_verification_v143", ROOT / "scripts" / "write_seal_verification_v143.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _tag_blob(tag: str):
    return lambda path: subprocess.run(["git", "rev-parse", f"{tag}:{path}"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()


def test_every_entry_of_the_v142_seal_lists_sandbox_py_so_none_can_be_carried_over(monkeypatch):
    """The v1.4.2 tag's seal against the v1.4.3 sandbox.py: the reason the whole seal is re-run."""
    writer = _writer()
    previous = writer.previous_entries()
    assert len(previous) == 17 and all(writer.SB in e["code_files"] for e in previous)
    monkeypatch.setattr(writer, "blob", _tag_blob("harness-v1.4.2"))
    assert writer.blob(writer.SB) == previous[0]["code_files"][writer.SB]  # at the v1.4.2 tag the blobs agree: the changed file is sandbox.py now, in the worktree
    ids = [e["id"] for e in previous]
    assert len(set(ids)) == 17


def test_every_earlier_record_maps_to_a_record_of_this_seal():
    writer = _writer()
    for entry in writer.previous_entries():
        if entry["id"] == "kill_at_operation_limit":
            continue  # its records are whatever the final stage needed
        mapped = writer.records_of(entry)
        assert len(mapped) == len(entry["records"]) and all(m.startswith(f"{NEW}/") for m in mapped), entry["id"]
    assert writer.moved("runs/sandbox_verification/v1.4.0-seal/run1_A_ready_image.json") == f"{NEW}/v140/run1_A_ready_image.json"
    assert writer.moved("runs/sandbox_verification/final-v1.4.0/smoke_alive_py36.json") == f"{NEW}/final/smoke_alive_py36.json"
    with pytest.raises(SystemExit, match="not a record of an earlier seal"):
        writer.moved("runs/other/x.json")


def _synthetic(tmp_path, monkeypatch, *, drop_stage=None, stale=None, failing=None):
    writer = _writer()
    blobs = {f: f"blob-{Path(f).name}" for f in drv.SANDBOX_TOUCHING_FILES}
    previous = writer.previous_entries()  # the real v1.4.2 entries (ids, descriptions, code files), read from the tag before ROOT moves
    monkeypatch.setattr(writer, "check_release_candidate", lambda run, git=None: None)  # tested on its own below
    monkeypatch.setattr(writer, "ROOT", tmp_path)
    monkeypatch.setattr(writer, "blob", lambda path: blobs[path])
    monkeypatch.setattr(writer, "previous_entries", lambda: previous)

    def record(rel, run_id=None, **extra):
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        run_id = run_id or f"id-{path.stem}"
        doc = {"ok": failing != rel, "run_id": run_id, **extra}
        path.write_text(json.dumps(doc), encoding="utf-8")

    for entry in previous:
        for rel in writer.records_of(entry) if entry["id"] != "kill_at_operation_limit" else []:
            extra = {}
            if entry["id"] == "runner_numpy_cap_old_torch":
                extra = {"stdout": "IMPORT_OK torch 1.8.1 1.26.4"}
            record(rel, **extra)
    for rel, via in (("final/kill_at_operation_limit_py310.json", "client_wait_timeout"), ("final/kill_at_operation_limit_py310_extra1.json", "server_result_timed_out")):
        record(f"{NEW}/{rel}", via=via, elapsed_seconds=26.8, completed_cost_usd=0.0001, message="the sandbox stopped it (exit code -1, cost measured $0.00005)")
    for _, _, _, records in writer.NEW_PATHS:
        for rel in records:
            record(rel)
    stages = {s: {"ok": s != drop_stage, "cost_usd": 0.1} for s in writer.STAGES}
    seal_blobs = {f: ("stale" if f == stale else blobs[f]) for f in writer.SANDBOX_FILES}
    (tmp_path / NEW).mkdir(parents=True, exist_ok=True)
    (tmp_path / NEW / "SEAL_RUN.json").write_text(json.dumps({"head": "h", "rc_commit": "rc", "blobs": seal_blobs, "stages": stages}), encoding="utf-8")
    return writer, blobs


def test_a_synthetic_seal_passes_the_batch_drivers_seal_rule(tmp_path, monkeypatch):
    writer, blobs = _synthetic(tmp_path, monkeypatch)
    assert writer.main() == 0
    doc = json.loads((tmp_path / "seal_verification.json").read_text(encoding="utf-8"))
    assert doc["harness_tag"] == "harness-v1.4.3" and doc["reverified_from"] == "harness-v1.4.2" and "carried_over_from" not in doc
    ids = [e["id"] for e in doc["paths"]]
    assert len(ids) == 19 and len(set(ids)) == 19 and "output_limit_raised_and_truncation_flag_read" in ids and "run_on_image_for_the_sustained_run" in ids
    assert all(r.startswith(f"{NEW}/") for e in doc["paths"] for r in e["records"])  # nothing is carried over
    assert all(e["code_files"][writer.SB] == blobs[writer.SB] for e in doc["paths"])
    kills = next(e for e in doc["paths"] if e["id"] == "kill_at_operation_limit")
    assert len(kills["records"]) == 2
    monkeypatch.setattr(drv, "SANDBOX_TOUCHING_FILES", tuple(f for f in blobs if not f.endswith("behaviour.py")))  # the five files the harness-v1.4.3 seal covered (harness-v1.10 added a sixth)
    drv.check_seal_verification(tmp_path, lambda p: blobs[p])  # the preflight's seal rule accepts it


def test_a_stage_that_did_not_pass_stops_the_writer(tmp_path, monkeypatch):
    writer, _ = _synthetic(tmp_path, monkeypatch, drop_stage="v140")
    with pytest.raises(SystemExit, match="stage v140 is missing or did not pass"):
        writer.main()


def test_an_edit_after_the_live_seal_stops_the_writer(tmp_path, monkeypatch):
    writer, _ = _synthetic(tmp_path, monkeypatch, stale="backend/app/services/sandbox.py")
    with pytest.raises(SystemExit, match="sandbox.py changed after the live seal"):
        writer.main()


def test_a_record_taken_against_an_older_file_stops_the_writer(tmp_path, monkeypatch):
    writer, _ = _synthetic(tmp_path, monkeypatch)
    rel = f"{NEW}/new/S1_200kb_stderr_whole.json"
    (tmp_path / rel).write_text(json.dumps({"ok": True, "run_id": "x", "code_blobs": {writer.SB: "older"}}), encoding="utf-8")
    with pytest.raises(SystemExit, match="changed after its live run"):
        writer.main()


def test_a_failed_or_missing_record_stops_the_writer(tmp_path, monkeypatch):
    rel = f"{NEW}/new/S2_stream_over_the_limit_flagged.json"
    writer, _ = _synthetic(tmp_path, monkeypatch, failing=rel)
    with pytest.raises(SystemExit, match="not a passing live record"):
        writer.main()
    (tmp_path / rel).unlink()
    with pytest.raises(SystemExit, match="is missing"):
        writer.main()


def test_without_the_live_seal_the_writer_refuses(tmp_path, monkeypatch):
    writer = _writer()
    monkeypatch.setattr(writer, "ROOT", tmp_path)
    monkeypatch.setattr(writer, "blob", lambda path: "b")
    with pytest.raises(SystemExit, match="SEAL_RUN.json is missing"):
        writer.main()


def test_the_writer_checks_the_live_seal_ran_against_the_release_candidate_and_the_harness_paths_are_still_its(monkeypatch):
    import subprocess

    writer = _writer()
    answers = {("rev-parse", "--verify"): "rc-sha", ("diff", "--name-only"): ""}
    git = lambda *args: next(v for k, v in answers.items() if args[: len(k)] == k)  # noqa: E731
    writer.check_release_candidate({"rc_commit": "rc-sha"}, git)
    with pytest.raises(SystemExit, match="ran against"):
        writer.check_release_candidate({"rc_commit": "another"}, git)
    answers[("diff", "--name-only")] = "scripts/run_corpus_v1_batch.py"
    with pytest.raises(SystemExit, match="harness paths differ"):
        writer.check_release_candidate({"rc_commit": "rc-sha"}, git)

    def missing(*args):
        raise subprocess.CalledProcessError(128, ["git", *args])

    with pytest.raises(SystemExit, match="does not exist"):
        writer.check_release_candidate({"rc_commit": "rc-sha"}, missing)


def test_main_checks_the_release_candidate_before_it_writes_anything(tmp_path, monkeypatch):
    writer, _ = _synthetic(tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(writer, "check_release_candidate", lambda run, git=None: calls.append(run.get("rc_commit")) or (_ for _ in ()).throw(SystemExit("not the release candidate")))
    with pytest.raises(SystemExit, match="not the release candidate"):
        writer.main()
    assert calls == ["rc"] and not (tmp_path / "seal_verification.json").exists()
