"""scripts/run_corpus_v1_batch.py: the freeze preflight and the pure summary
(headline over PRIMARY entries only, amendment 1)."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("run_corpus_v1_batch", ROOT / "scripts" / "run_corpus_v1_batch.py")
batch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(batch)


def test_recomputed_corpus_hash_equals_the_frozen_one():
    recorded = (batch.CORPUS_DIR / "corpus_hash.txt").read_text(encoding="utf-8").strip()
    assert batch.recompute_corpus_hash() == recorded


def test_pinned_amendment_sha256_matches_the_committed_amendment():
    assert batch._sha256(batch.CORPUS_DIR / "amendment-1.json") == batch.EXPECTED_AMENDMENT_SHA256
    assert (batch.CORPUS_DIR / "amendment-1.sha256").read_text(encoding="utf-8").split()[0] == batch.EXPECTED_AMENDMENT_SHA256


def test_dirty_paths_only_tolerates_untracked_batch_output():
    prefix = "runs/corpus_v1_batch/"
    assert batch.dirty_paths("?? runs/corpus_v1_batch/01_x.json\n", prefix) == []
    assert batch.dirty_paths(" M backend/app/services/classifier.py\n", prefix) == [" M backend/app/services/classifier.py"]
    assert batch.dirty_paths("M  runs/corpus_v1_batch/01_x.json\n", prefix)  # staged, even in the output dir
    assert batch.dirty_paths("?? scratch.txt\n", prefix) == ["?? scratch.txt"]


def test_git_output_keeps_the_leading_status_space():
    """Regression: `_git` stripped the whole output, eating the first
    porcelain line's leading space (" M x" -> "M x")."""
    out = batch._git("status", "--porcelain", "--untracked-files=no")
    assert out == out.rstrip() and (not out or out[0] in " MADRCU?!")
    assert batch._git("rev-parse", "HEAD") == batch._git("rev-parse", "HEAD").strip()


def test_preflight_refuses_when_head_is_not_the_tag(monkeypatch):
    calls = {
        ("status", "--porcelain", "--untracked-files=all"): "",
        ("rev-parse", "harness-v1^{commit}"): "a" * 40,
        ("rev-parse", "HEAD"): "b" * 40,
    }
    monkeypatch.setattr(batch, "_git", lambda *args: calls[args])
    with pytest.raises(batch.PreflightError, match="is not harness-v1"):
        batch.preflight()


def test_preflight_refuses_a_dirty_tree(monkeypatch):
    monkeypatch.setattr(batch, "_git", lambda *args: " M scripts/live_run.py" if args[0] == "status" else "x")
    with pytest.raises(batch.PreflightError, match="dirty"):
        batch.preflight()


def test_preflight_refuses_a_tampered_amendment(monkeypatch, tmp_path):
    corpus_dir = tmp_path / "corpus_v1"
    corpus_dir.mkdir()
    for name in ("amendment-1.json", "amendment-1.sha256", "corpus.yaml", "prereg.json", "corpus_hash.txt"):
        (corpus_dir / name).write_bytes((batch.CORPUS_DIR / name).read_bytes())
    (corpus_dir / "amendment-1.json").write_bytes((batch.CORPUS_DIR / "amendment-1.json").read_bytes().replace(b"PRIMARY", b"PRIMARX", 1))
    head = "c" * 40
    calls = {
        ("status", "--porcelain", "--untracked-files=all"): "",
        ("rev-parse", "harness-v1^{commit}"): head,
        ("rev-parse", "HEAD"): head,
        ("ls-remote", "origin", "refs/tags/harness-v1^{}"): f"{head}\trefs/tags/harness-v1^{{}}",
    }
    monkeypatch.setattr(batch, "_git", lambda *args: calls[args])
    monkeypatch.setattr(batch, "CORPUS_DIR", corpus_dir)
    with pytest.raises(batch.PreflightError, match="amendment sha256 mismatch"):
        batch.preflight()


def _record(entry_id, category, baseline, verdict, taxonomy=None, mode="deterministic", spent=0.5, recovery=None):
    return {
        "corpus_entry": {"name": f"e{entry_id}"},
        "batch": {"entry_id": entry_id, "category": category, "harness_tag": "harness-v1", "harness_commit": "f" * 40},
        "result": {"verdict": verdict, "taxonomy_code": taxonomy, "reason_code": None},
        "certificate": {
            "baseline": {"result": baseline, "taxonomy_code": taxonomy},
            "recovery": recovery if recovery is not None else (baseline == "FAILS" and verdict == "RUNS_AFTER_REPAIR"),
            "tree_integrity": {"status": "verified"},
        },
        "repair_mode": mode,
        "cost_guard": {"spent_usd": spent},
    }


def test_summary_headline_counts_primary_entries_only():
    records = [
        _record(1, "PRIMARY", "FAILS", "RUNS_AFTER_REPAIR", mode="deterministic"),
        _record(2, "PRIMARY", "FAILS", "RUNS_AFTER_REPAIR", mode="model_assisted"),
        _record(3, "COMMAND_NOT_A_RUN", "FAILS", "RUNS_AFTER_REPAIR"),  # never in the headline
        _record(4, "PRIMARY", "FAILS", "BLOCKED", taxonomy="DATA_MISSING"),
        _record(5, "PRIMARY", "FAILS", "BLOCKED", taxonomy="GPU_REQUIRED"),
        _record(6, "PRIMARY", "FAILS", "BLOCKED", taxonomy="DATA_MISSING"),
        _record(7, "PRIMARY", "RUNS_CLEAN", "RUNS_CLEAN"),
        _record(8, "PRIMARY", "NOT_RUN", "INVALID_HARNESS"),
    ]
    s = batch.summarize(records)
    p = s["primary"]
    assert p["n"] == 7
    assert p["failed_as_published"] == 5
    assert p["runs_after_repair"] == 2
    assert p["blocked_by_reason"] == {"DATA_MISSING": 2, "GPU_REQUIRED": 1}
    assert p["invalid_harness"] == 1
    assert p["ran_as_published"] == 1
    assert p["recovered_repair_mode"] == {"deterministic": 1, "model_assisted": 1}
    assert p["headline"] == "PRIMARY: 2/5 of 7"
    assert s["command_not_a_run"]["n"] == 1
    assert s["total_spent_usd"] == 4.0
    assert [r["id"] for r in s["rows"]] == [1, 2, 3, 4, 5, 6, 7, 8]
    assert all(r["harness_tag"] == "harness-v1" and r["tree_integrity"] == "verified" for r in s["rows"])


def test_summary_json_round_trips():
    s = batch.summarize([_record(1, "PRIMARY", "FAILS", "BLOCKED", taxonomy="DEP_MISSING")])
    assert json.loads(json.dumps(s))["primary"]["headline"] == "PRIMARY: 0/1 of 1"
