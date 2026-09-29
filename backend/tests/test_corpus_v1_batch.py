"""scripts/run_corpus_v1_batch.py (harness-v1.1): the freeze preflight
(tag-or-descendant, data allowlist, hash checks — against a REAL temporary git
repository with a bare "origin"), the circuit breaker, and the pure summary."""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("run_corpus_v1_batch", ROOT / "scripts" / "run_corpus_v1_batch.py")
batch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(batch)

REAL_V1 = ROOT / "backend" / "app" / "batch" / "corpus_v1"
REAL_V2 = ROOT / "backend" / "app" / "batch" / "corpus_v2"
TAG = "harness-test"


def _run(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


def _commit(repo: Path, message: str) -> str:
    _run(repo, "add", "-A")
    _run(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", message)
    return _run(repo, "rev-parse", "HEAD")


@pytest.fixture(autouse=True)
def _sealed_image_setting(monkeypatch):
    """Preflight reads NEBIUS_SANDBOX_IMAGE from settings; a machine's untracked .env must not decide these tests."""
    from app.config import get_settings

    monkeypatch.setenv("NEBIUS_SANDBOX_IMAGE", batch.SEALED_SANDBOX_IMAGE)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """A repo with harness code, the sealed corpus files, a tag pushed to a
    bare origin; batch module pointed at it."""
    origin = tmp_path / "origin.git"
    _run(tmp_path, "init", "-q", "--bare", str(origin))
    work = tmp_path / "work"
    work.mkdir()
    _run(work, "init", "-q")
    _run(work, "config", "core.autocrlf", "false")
    (work / "backend" / "app").mkdir(parents=True)
    (work / "backend" / "app" / "harness.py").write_text("X = 1\n", encoding="utf-8")
    (work / "scripts").mkdir()
    (work / "scripts" / "tool.py").write_text("Y = 2\n", encoding="utf-8")
    v1 = work / "backend" / "app" / "batch" / "corpus_v1"
    v1.mkdir(parents=True)
    for name in ("prereg.json", "corpus.yaml", "corpus_hash.txt", "amendment-1.json", "amendment-1.sha256"):
        shutil.copyfile(REAL_V1 / name, v1 / name)
    v2 = work / "backend" / "app" / "batch" / "corpus_v2"
    v2.mkdir(parents=True)
    for name in ("prereg.json", "prereg.sha256"):
        shutil.copyfile(REAL_V2 / name, v2 / name)
    (work / "DECISIONS.md").write_text("log\n", encoding="utf-8")
    _commit(work, "seal")
    _run(work, "tag", "-a", TAG, "-m", "t")
    _run(work, "remote", "add", "origin", str(origin))
    _run(work, "push", "-q", "origin", "HEAD:refs/heads/main", TAG)
    monkeypatch.setattr(batch, "ROOT", work)
    monkeypatch.setattr(batch, "BATCH_DIR", work / "backend" / "app" / "batch")
    return work


def test_preflight_passes_on_the_tag(repo):
    frozen = batch.preflight("corpus-v1", TAG)
    assert frozen["harness_commit"] == frozen["head_commit"]
    assert frozen["amendment_sha256"] == batch.EXPECTED_AMENDMENT_SHA256


def test_preflight_passes_on_a_descendant_that_only_changes_data(repo):
    (repo / "runs" / "corpus_v1_batch").mkdir(parents=True)
    (repo / "runs" / "corpus_v1_batch" / "x.json").write_text("{}", encoding="utf-8")
    (repo / "DECISIONS.md").write_text("log\nmore\n", encoding="utf-8")
    v2 = repo / "backend" / "app" / "batch" / "corpus_v2"
    for name in batch.DRAW_OUTPUTS:
        (v2 / name).write_text("drawn\n", encoding="utf-8")
    head = _commit(repo, "data")
    frozen = batch.preflight("corpus-v1", TAG)
    assert frozen["head_commit"] == head != frozen["harness_commit"]


@pytest.mark.parametrize(
    "path, content",
    [
        ("backend/app/harness.py", "X = 2\n"),  # harness code
        ("scripts/tool.py", "Y = 3\n"),
        ("backend/app/batch/corpus_v2/prereg.json", "{}\n"),  # sealed pre-registration
        ("backend/app/batch/corpus_v1/amendment-1.json", "{}\n"),
        ("README.md", "new\n"),  # anything else not on the allowlist
    ],
)
def test_preflight_refuses_a_descendant_that_changes_code_or_sealed_files(repo, path, content):
    (repo / path).write_text(content, encoding="utf-8")
    _commit(repo, "change")
    with pytest.raises(batch.PreflightError, match="outside the data allowlist"):
        batch.preflight("corpus-v1", TAG)


def test_hash_check_is_independent_of_the_allowlist(repo, monkeypatch):
    """Even if the allowlist wrongly admitted harness code, the blob
    comparison against the tag still refuses."""
    (repo / "backend" / "app" / "harness.py").write_text("X = 2\n", encoding="utf-8")
    _commit(repo, "change")
    monkeypatch.setattr(batch, "disallowed_changes", lambda changed: [])
    with pytest.raises(batch.PreflightError, match="harness code differ"):
        batch.preflight("corpus-v1", TAG)


def test_preflight_refuses_when_head_is_not_a_descendant(repo):
    _run(repo, "checkout", "-q", "--orphan", "other")
    (repo / "DECISIONS.md").write_text("x\n", encoding="utf-8")
    _commit(repo, "unrelated")
    with pytest.raises(batch.PreflightError, match="nor a descendant"):
        batch.preflight("corpus-v1", TAG)


def test_preflight_refuses_a_tag_missing_on_origin(repo):
    _run(repo, "push", "-q", "origin", f":refs/tags/{TAG}")
    with pytest.raises(batch.PreflightError, match="origin does not have"):
        batch.preflight("corpus-v1", TAG)


def test_preflight_refuses_a_dirty_tree_but_tolerates_its_own_output(repo):
    out = batch.out_dir("corpus-v1", TAG)
    out.mkdir(parents=True)
    (out / "01_x.json").write_text("{}", encoding="utf-8")
    batch.preflight("corpus-v1", TAG)  # untracked batch output is fine (resume)
    (repo / "backend" / "app" / "harness.py").write_text("X = 9\n", encoding="utf-8")
    with pytest.raises(batch.PreflightError, match="dirty"):
        batch.preflight("corpus-v1", TAG)


def test_preflight_refuses_an_amendment_that_is_not_the_pinned_one(repo, monkeypatch):
    monkeypatch.setattr(batch, "EXPECTED_AMENDMENT_SHA256", "0" * 64)
    with pytest.raises(batch.PreflightError, match="amendment sha256 mismatch"):
        batch.preflight("corpus-v1", TAG)


def test_preflight_refuses_corpus_v2_before_it_is_drawn(repo):
    with pytest.raises(batch.PreflightError, match="not drawn yet"):
        batch.preflight("corpus-v2", TAG)


def test_data_allowlist():
    assert batch.disallowed_changes(["runs/a/b.json", "DECISIONS.md", "METHODOLOGY.md",
                                     "backend/app/batch/corpus_v2/corpus.yaml"]) == []
    assert batch.disallowed_changes(["backend/app/batch/corpus_v2/prereg.json", "scripts/x.py"]) == [
        "backend/app/batch/corpus_v2/prereg.json", "scripts/x.py"]


def test_recomputed_corpus_hash_equals_the_frozen_one():
    assert batch.recompute_corpus_hash(REAL_V1) == (REAL_V1 / "corpus_hash.txt").read_text(encoding="utf-8").strip()


def test_git_output_keeps_the_leading_status_space():
    out = batch._git("status", "--porcelain", "--untracked-files=no")
    assert not out or out[0] in " MADRCU?!"


# --- circuit breaker ---------------------------------------------------------


def _fake_runner(verdicts):
    calls = []

    def runner(corpus, name, corpus_hash, meta, path):
        verdict = verdicts[len(calls)]
        calls.append(name)
        path.write_text(json.dumps({"result": {"verdict": verdict}, "cost_guard": {"spent_usd": 0.1}}), encoding="utf-8")

    return runner, calls


def _frozen():
    return {"corpus": "corpus-v1", "harness_tag": TAG, "harness_commit": "c" * 40, "corpus_hash": "h"}


def test_circuit_breaker_stops_after_two_consecutive_infra_errors(repo, monkeypatch):
    monkeypatch.setattr(batch, "load_records", lambda odir: [])
    runner, calls = _fake_runner(["BLOCKED", "INFRA_ERROR", "INFRA_ERROR", "BLOCKED"])
    batch.run_batch(_frozen(), runner=runner)
    assert len(calls) == 3


def test_circuit_breaker_resets_on_a_real_verdict(repo, monkeypatch):
    monkeypatch.setattr(batch, "load_records", lambda odir: [])
    runner, calls = _fake_runner(["INFRA_ERROR", "BLOCKED", "INFRA_ERROR", "RUNS_CLEAN", "BLOCKED"] + ["BLOCKED"] * 15)
    batch.run_batch(_frozen(), runner=runner)
    assert len(calls) == 20


# --- summary -------------------------------------------------------------------


def _record(entry_id, category, baseline, verdict, taxonomy=None, mode="deterministic", spent=0.5, reason=None):
    return {
        "corpus_entry": {"name": f"e{entry_id}"},
        "batch": {"entry_id": entry_id, "category": category, "harness_tag": TAG, "harness_commit": "f" * 40},
        "result": {"verdict": verdict, "taxonomy_code": taxonomy, "reason_code": reason},
        "certificate": {
            "baseline": {"result": baseline, "taxonomy_code": taxonomy},
            "recovery": baseline == "FAILS" and verdict == "RUNS_AFTER_REPAIR",
            "tree_integrity": {"status": "verified"},
        },
        "repair_mode": mode,
        "cost_guard": {"spent_usd": spent},
    }


def test_summary_headline_counts_primary_measured_entries_only():
    records = [
        _record(1, "PRIMARY", "FAILS", "RUNS_AFTER_REPAIR", mode="deterministic"),
        _record(2, "PRIMARY", "FAILS", "RUNS_AFTER_REPAIR", mode="model_assisted"),
        _record(3, "COMMAND_NOT_A_RUN", "FAILS", "RUNS_AFTER_REPAIR"),  # never in the headline
        _record(4, "PRIMARY", "FAILS", "BLOCKED", taxonomy="DATA_MISSING"),
        _record(5, "PRIMARY", "FAILS", "BLOCKED", taxonomy="GPU_REQUIRED"),
        _record(6, "PRIMARY", "FAILS", "BLOCKED", taxonomy="DATA_MISSING"),
        _record(7, "PRIMARY", "RUNS_CLEAN", "RUNS_CLEAN"),
        _record(8, "PRIMARY", "NOT_RUN", "INVALID_HARNESS"),
        _record(9, "PRIMARY", "FAILS", "INFRA_ERROR", reason="INFRA_ERROR:sandbox:ApiTimeoutError"),  # RERUN's fault
        _record(10, "PRIMARY", "FAILS", "INDETERMINATE", reason="PIPELINE_ERROR:repairer:ValueError"),
    ]
    s = batch.summarize(records)
    p = s["primary"]
    assert p["n"] == 9 and p["n_measured"] == 6
    assert p["failed_as_published"] == 5
    assert p["runs_after_repair"] == 2
    assert p["blocked_by_reason"] == {"DATA_MISSING": 2, "GPU_REQUIRED": 1}
    assert (p["invalid_harness"], p["infra_error"], p["pipeline_error"]) == (1, 1, 1)
    assert p["recovered_repair_mode"] == {"deterministic": 1, "model_assisted": 1}
    assert p["headline"] == "PRIMARY: 2/5 of 9"
    assert s["command_not_a_run"]["n"] == 1


def test_batch_refuses_to_start_when_the_upload_smoke_test_fails(repo, monkeypatch):
    ran = []
    monkeypatch.setattr(batch, "run_smoke", lambda: {"ok": False, "runs": [{"error": "ApiTimeoutError"}]})
    monkeypatch.setattr(batch, "run_batch", lambda frozen, runner=None: ran.append(1))
    assert batch.main(["--corpus", "corpus-v1", "--harness-tag", TAG]) == 3
    assert ran == []
    assert list(batch.out_dir("corpus-v1", TAG).glob("smoke_*.json"))  # the failed smoke test is recorded
