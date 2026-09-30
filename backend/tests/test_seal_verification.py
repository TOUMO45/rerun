"""harness-v1.3.2 seal rule: no seal without one real Nebius execution per sandbox-touching path, enforced by preflight."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _driver():
    spec = importlib.util.spec_from_file_location("drv", ROOT / "scripts" / "run_corpus_v1_batch.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


drv = _driver()
BLOBS = {f: f"{i:040x}" for i, f in enumerate(drv.SANDBOX_TOUCHING_FILES)}


def _write(root: Path, *, mutate=None, record_ok=True):
    rec = root / "runs" / "rec.json"
    rec.parent.mkdir(parents=True, exist_ok=True)
    rec.write_text(json.dumps({"ok": record_ok, "run_id": "run-1"}), encoding="utf-8")
    doc = {"paths": [{"id": "all", "live_nebius": True, "code_files": dict(BLOBS), "records": ["runs/rec.json"], "run_ids": ["run-1"]}]}
    if mutate:
        mutate(doc)
    (root / "seal_verification.json").write_text(json.dumps(doc), encoding="utf-8")


def check(root):
    drv.check_seal_verification(root, lambda p: BLOBS[p])


def test_a_complete_current_verification_passes(tmp_path):
    _write(tmp_path)
    check(tmp_path)


def test_no_file_no_batch(tmp_path):
    with pytest.raises(drv.PreflightError, match="missing"):
        check(tmp_path)


@pytest.mark.parametrize("mutate, message", [
    (lambda d: d["paths"][0].update(live_nebius=False), "not marked live_nebius"),
    (lambda d: d["paths"][0].update(run_ids=[]), "no run id"),
    (lambda d: d["paths"][0].update(run_ids=["some-other-run"]), "not the run_id of any listed record"),
    (lambda d: d["paths"][0].update(records=["runs/gone.json"]), "is missing"),
    (lambda d: d["paths"][0]["code_files"].pop("backend/app/services/runner_env.py"), "no live verification covers"),
    (lambda d: d["paths"][0]["code_files"].update({"backend/app/services/sandbox.py": "f" * 40}), "changed after its live verification"),
])
def test_incomplete_or_stale_verification_refuses(tmp_path, mutate, message):
    _write(tmp_path, mutate=mutate)
    with pytest.raises(drv.PreflightError, match=message):
        check(tmp_path)


def test_a_failed_record_does_not_count(tmp_path):
    _write(tmp_path, record_ok=False)
    with pytest.raises(drv.PreflightError, match="did not pass"):
        check(tmp_path)


def test_the_file_is_sealed_and_every_sandbox_touching_file_is_listed():
    assert drv.SEAL_VERIFICATION in drv.SEALED_FILES
    for f in ("backend/app/services/sandbox.py", "backend/app/services/sandbox_limits.py", "backend/app/services/runner_env.py"):
        assert f in drv.SANDBOX_TOUCHING_FILES and (ROOT / f).is_file()


def test_the_committed_file_names_only_live_records_that_exist_and_passed():
    """Structure check of the real file (blob currency is checked by preflight at HEAD, not here)."""
    doc = json.loads((ROOT / "seal_verification.json").read_text(encoding="utf-8"))
    assert doc["harness_tag"] == "harness-v1.3.4" and len(doc["paths"]) >= 11  # v1.3.2: 7; v1.3.3: +NumPy cap, kill path, smoke launcher; v1.3.4: +download-route overlay
    for entry in doc["paths"]:
        assert entry["live_nebius"] is True and entry["run_ids"] and entry["code_files"]
        for rec in entry["records"]:
            data = json.loads((ROOT / rec).read_text(encoding="utf-8"))
            assert data["ok"] is True and data["run_id"] in entry["run_ids"]
