"""harness-v1.6 DEMO / REPLAY mode: the seeder's selection rule, idempotent seeding into a temp SQLite, the TEST firewall (a TEST entry's
record is never opened, no row exists for it), the 409 on execution in demo mode, and the shape of `GET /runs`.

The firewall is loaded the way the replay tests load it (reports/corpus-v2.1/v1.5/devtest on sys.path), so the TEST entry ids used here come
from the protocol's own split, never from a list written in this file."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import _add_missing_columns
from app.models import Base, Certificate, Run
from app.services import demo_seed
from app.services.demo_seed import RecordRef, record_ref, select_latest_per_entry, tag_key

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "reports" / "corpus-v2.1" / "v1.5" / "devtest"))
import firewall  # noqa: E402

RUNS_DIR = ROOT / "runs" / "corpus_v2_batch"
SOME_DEV = sorted(firewall.DEV_ENTRIES)[0]
SOME_TEST = sorted(firewall.TEST_ENTRIES)[0]
SOME_GATE = sorted(firewall.GATE_ENTRIES)[0]


def _ref(tag: str, arm: str, entry_id: int, name: str = "o__r") -> RecordRef:
    return RecordRef(Path(f"/x/{tag}/{arm}/{entry_id:02d}_{name}.json"), tag, arm, entry_id, name)


# ---------------------------------------------------------------- selection rule


def test_tag_key_orders_harness_tags_numerically():
    assert tag_key("harness-v1.5.1") > tag_key("harness-v1.4.3")
    assert tag_key("harness-v1.4.10") > tag_key("harness-v1.4.3")  # numeric, not lexical
    assert tag_key("harness-v1.6.0-rc") == (1, 6, 0)
    with pytest.raises(ValueError):
        tag_key("attempt1_harness-v1.3.1_aborted_4of20")


def test_select_latest_per_entry_keeps_one_record_per_entry_at_the_highest_tag():
    refs = [
        _ref("harness-v1.4.0", "gate", 3),
        _ref("harness-v1.4.3", "gate", 3),
        _ref("harness-v1.4.2", "gate", 3),
        _ref("harness-v1.5.0", "dev", 15),
        _ref("harness-v1.5.1", "dev", 15),
        _ref("harness-v1.4.1", "gate", 7),
    ]
    chosen = select_latest_per_entry(reversed(refs))
    assert [(r.entry_id, r.tag) for r in chosen] == [(3, "harness-v1.4.3"), (7, "harness-v1.4.1"), (15, "harness-v1.5.1")]
    assert [r.run_id for r in chosen] == ["demo-harness-v1.4.3-gate-03", "demo-harness-v1.4.1-gate-07", "demo-harness-v1.5.1-dev-15"]


def test_select_latest_per_entry_is_order_independent_and_breaks_a_tag_tie_by_arm_name():
    a, b = _ref("harness-v1.5.1", "dev", 9), _ref("harness-v1.5.1", "gate", 9)
    assert select_latest_per_entry([a, b])[0] is b and select_latest_per_entry([b, a])[0] is b
    assert select_latest_per_entry([]) == []


def test_record_ref_parses_only_tagged_arm_entry_records(tmp_path):
    runs_dir = tmp_path / "runs"
    assert record_ref(runs_dir, runs_dir / "harness-v1.5.1" / "dev" / "15_YuliaRubanova__latent_ode.json").name == "YuliaRubanova__latent_ode"
    assert record_ref(runs_dir, runs_dir / "harness-v1.5.1" / "dev" / "round_summary.json") is None
    assert record_ref(runs_dir, runs_dir / "harness-v1.5.1" / "dev" / "upload_smoke_20261003T153638Z.json") is None
    assert record_ref(runs_dir, runs_dir / "harness-v1.2" / "01_nadiinchi__power_laws_deep_ensembles.json") is None  # no arm level
    assert record_ref(runs_dir, runs_dir / "attempt1_harness-v1.3.1_aborted_4of20" / "control" / "01_x.json") is None
    assert record_ref(tmp_path / "elsewhere", runs_dir / "harness-v1.5.1" / "dev" / "15_a__b.json") is None


# ---------------------------------------------------------------- a synthetic runs tree (no committed record is needed)


def _record(entry_id: int, tag: str, verdict: str = "BLOCKED", taxonomy: str = "DATA_MISSING") -> dict:
    return {
        "corpus_entry": {"name": f"owner__repo{entry_id}", "repo_url": f"https://github.com/owner/repo{entry_id}", "commit_sha": "c" * 40},
        "config": {"harness_version": tag},
        "result": {
            "verdict": verdict,
            "taxonomy_code": taxonomy,
            "indeterminate_reason": "",
            "error_chain": [{"error": "FileNotFoundError: data/", "class": taxonomy, "attribution": "REPO", "phase": "repo_run", "cleared_by": None}],
            "first_repo_error": "ModuleNotFoundError: No module named 'x'",
            "last_error": "FileNotFoundError: data/",
            "attempts": [{"attempt_number": 0, "diff_text": "", "gate_decision": "PASS", "gate_violations": [], "exit_code": 1}],
            "certificate_prose": f"prose for {entry_id} at {tag}",
        },
        "certificate": {
            "repo_url": f"https://github.com/owner/repo{entry_id}",
            "commit_sha": "c" * 40,
            "build_plan": {"base_image": "python:3.8-slim"},
            "full_log": f"[intake] cloned repo{entry_id}\n[run] exit 1",
            "diffs": [{"attempt_number": 0, "diff_text": "", "gate_decision": "PASS", "gate_violations": [], "exit_code": 1}],
            "verdict": verdict,
            "timestamp": "2026-10-03T16:23:47.513455+00:00",
            "bundle_version": 4,
            "baseline": {"result": "FAILS", "exit_code": 1},
            "recovery": False,
            "tree_integrity": {"status": "verified", "tree_sha": "t" * 40},
            "corpus_hash": "h" * 64,
            "taxonomy_code": taxonomy,
            "indeterminate_reason": "",
            "error_chain": [{"error": "FileNotFoundError: data/", "class": taxonomy, "attribution": "REPO", "phase": "repo_run", "cleared_by": None}],
            "first_repo_error": "ModuleNotFoundError: No module named 'x'",
            "last_error": "FileNotFoundError: data/",
            "reproduction_passport_hash": "p" * 64,
        },
    }


def _write(root: Path, tag: str, arm: str, entry_id: int, record: dict) -> Path:
    path = root / "runs" / "corpus_v2_batch" / tag / arm / f"{entry_id:02d}_owner__repo{entry_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record), encoding="utf-8")
    return path


@pytest.fixture
def demo_root(tmp_path):
    """A repository root with a synthetic runs tree and the REAL firewall module (copied, so its split is the protocol's)."""
    devtest = tmp_path / demo_seed.FIREWALL_SUBDIR
    devtest.mkdir(parents=True)
    for name in ("firewall.py", "split.py"):
        (devtest / name).write_text((ROOT / demo_seed.FIREWALL_SUBDIR / name).read_text(encoding="utf-8"), encoding="utf-8")
    gate = SOME_GATE
    _write(tmp_path, "harness-v1.4.2", "gate", gate, _record(gate, "harness-v1.4.2", "INDETERMINATE", "RESOURCE_LIMIT"))
    _write(tmp_path, "harness-v1.4.3", "gate", gate, _record(gate, "harness-v1.4.3"))
    _write(tmp_path, "harness-v1.5.0", "dev", SOME_DEV, _record(SOME_DEV, "harness-v1.5.0"))
    _write(tmp_path, "harness-v1.5.1", "dev", SOME_DEV, _record(SOME_DEV, "harness-v1.5.1", "RUNS_AFTER_REPAIR", "DEP_YANKED"))
    _write(tmp_path, "harness-v1.5.1", "dev", SOME_TEST, _record(SOME_TEST, "harness-v1.5.1"))  # must never be opened
    (tmp_path / "runs" / "corpus_v2_batch" / "harness-v1.5.1" / "dev" / "round_summary.json").write_text("{}", encoding="utf-8")
    return tmp_path


@pytest.fixture
def db(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'demo.db'}")
    Base.metadata.create_all(engine)
    _add_missing_columns(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


# ---------------------------------------------------------------- seeding


def test_seed_is_idempotent_and_copies_the_record_fields(demo_root, db):
    assert demo_seed.seed(db, demo_root) == 2  # latest per entry: one gate, one DEV
    assert demo_seed.seed(db, demo_root) == 0
    runs = db.query(Run).order_by(Run.id).all()
    assert len(runs) == 2 and db.query(Certificate).count() == 2
    dev = db.get(Run, f"demo-harness-v1.5.1-dev-{SOME_DEV:02d}")
    assert dev is not None and dev.stage == "DONE" and dev.verdict == "RUNS_AFTER_REPAIR" and dev.taxonomy_code == "DEP_YANKED"
    assert dev.repo_url == f"https://github.com/owner/repo{SOME_DEV}" and dev.commit_sha == "c" * 40 and dev.attempts_used == 1
    assert dev.demo_source == f"runs/corpus_v2_batch/harness-v1.5.1/dev/{SOME_DEV:02d}_owner__repo{SOME_DEV}.json"
    cert = dev.certificate
    assert cert.verdict == "RUNS_AFTER_REPAIR" and cert.certificate_prose == f"prose for {SOME_DEV} at harness-v1.5.1"
    assert cert.full_log.startswith("[intake] cloned") and cert.build_plan == {"base_image": "python:3.8-slim"}
    assert cert.diffs[0]["exit_code"] == 1 and cert.reproduction_passport_hash == "p" * 64
    assert cert.timestamp == "2026-10-03T16:23:47.513455+00:00" and cert.bundle_version == 4
    assert cert.baseline == {"result": "FAILS", "exit_code": 1} and cert.recovery is False
    assert cert.tree_integrity["tree_sha"] == "t" * 40 and cert.corpus_hash == "h" * 64
    assert cert.taxonomy_code == "DEP_YANKED" and cert.error_chain[0]["class"] == "DEP_YANKED"
    assert cert.first_repo_error.startswith("ModuleNotFoundError") and cert.last_error.startswith("FileNotFoundError")
    # the older tags were not seeded by default
    assert db.get(Run, f"demo-harness-v1.5.0-dev-{SOME_DEV:02d}") is None
    assert db.get(Run, f"demo-harness-v1.4.2-gate-{SOME_GATE:02d}") is None


def test_seed_with_explicit_versions_adds_every_allowed_record_of_those_tags(demo_root, db):
    assert demo_seed.seed(db, demo_root, versions=["harness-v1.4.2", "harness-v1.5.0"]) == 2
    assert demo_seed.seed(db, demo_root) == 2  # the latest tags are different rows
    assert db.query(Run).count() == 4


def test_seed_never_opens_a_test_record_and_creates_no_row_for_it(demo_root, db, monkeypatch):
    opened: list[str] = []
    real = firewall.read_record_text

    def _observed(path):
        opened.append(Path(path).name)
        return real(path)

    monkeypatch.setattr(firewall, "read_record_text", _observed)
    demo_seed.seed(db, demo_root, versions=["harness-v1.4.2", "harness-v1.4.3", "harness-v1.5.0", "harness-v1.5.1"])
    assert opened and all(firewall.entry_id_of(name) != SOME_TEST for name in opened)
    assert not [r for r in db.query(Run).all() if r.id.endswith(f"-{SOME_TEST:02d}")]
    with pytest.raises(firewall.FirewallError):  # and the firewall itself would have refused the file
        firewall.read_record_text(demo_root / "runs" / "corpus_v2_batch" / "harness-v1.5.1" / "dev" / f"{SOME_TEST:02d}_owner__repo{SOME_TEST}.json")


def test_seed_never_writes_under_runs(demo_root, db):
    before = {p: p.stat().st_mtime_ns for p in (demo_root / "runs").rglob("*") if p.is_file()}
    demo_seed.seed(db, demo_root)
    assert {p: p.stat().st_mtime_ns for p in (demo_root / "runs").rglob("*") if p.is_file()} == before


def test_seed_without_a_runs_directory_or_firewall_logs_and_skips(tmp_path, db, caplog):
    assert demo_seed.seed(db, tmp_path) == 0
    (tmp_path / "runs" / "corpus_v2_batch").mkdir(parents=True)
    assert demo_seed.seed(db, tmp_path) == 0
    assert "nothing to replay" in caplog.text


def test_full_log_falls_back_to_a_note_when_the_record_stores_none(demo_root, db):
    rec = _record(SOME_DEV, "harness-v1.5.1")
    del rec["certificate"]["full_log"]
    _write(demo_root, "harness-v1.5.1", "dev", SOME_DEV, rec)
    demo_seed.seed(db, demo_root)
    assert db.get(Run, f"demo-harness-v1.5.1-dev-{SOME_DEV:02d}").certificate.full_log == demo_seed.DEMO_FULL_LOG_NOTE


@pytest.mark.skipif(not (RUNS_DIR / "harness-v1.5.1" / "dev").is_dir(), reason="committed records not in this checkout")
def test_the_committed_records_seed_the_dev_and_gate_entries_only(db):
    added = demo_seed.seed(db, ROOT)
    ids = {int(r.id.rsplit("-", 1)[1]) for r in db.query(Run).all()}
    assert added == len(ids) and ids and ids <= firewall.ANALYSIS_ENTRIES and not ids & firewall.TEST_ENTRIES
    assert all(r.demo_source.startswith("runs/corpus_v2_batch/harness-v1.") for r in db.query(Run).all())
    assert demo_seed.seed(db, ROOT) == 0


# ---------------------------------------------------------------- the API in demo mode


class _DemoSettings:
    demo_mode = True
    nebius_configured = True


def test_execute_is_refused_with_409_in_demo_mode(client, fake_paper_repo, monkeypatch):
    created = client.post("/runs", json={"repo_url": str(fake_paper_repo)})
    assert created.status_code == 201  # intake still works
    monkeypatch.setattr("app.routers.runs.get_settings", lambda: _DemoSettings())
    response = client.post(f"/runs/{created.json()['id']}/execute")
    assert response.status_code == 409
    assert response.json()["detail"] == "demo mode replays recorded audits; live execution is off"
    assert client.get(f"/runs/{created.json()['id']}").json()["stage"] == "RECON_PENDING"  # nothing started
    stream = client.get(f"/runs/{created.json()['id']}/stream")
    assert stream.status_code == 409


def test_list_runs_shape_and_demo_rows(client, demo_root):
    from app.db import get_db
    from app.main import app

    override = app.dependency_overrides[get_db]
    session = next(override())
    try:
        demo_seed.seed(session, demo_root)
    finally:
        session.close()

    response = client.get("/runs")
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"runs", "total", "limit", "offset"} and body["total"] == 2 and body["limit"] == 200 and body["offset"] == 0
    assert len(body["runs"]) == 2
    row = next(r for r in body["runs"] if r["id"] == f"demo-harness-v1.5.1-dev-{SOME_DEV:02d}")
    assert set(row) == {"id", "repo_url", "commit_sha", "status", "verdict", "taxonomy_code", "demo_source", "created_at"}
    assert row["status"] == "DONE" and row["verdict"] == "RUNS_AFTER_REPAIR" and row["taxonomy_code"] == "DEP_YANKED"
    assert row["demo_source"].startswith("runs/corpus_v2_batch/harness-v1.5.1/dev/")
    # the certificate screen's endpoints serve the seeded row
    assert client.get(f"/runs/{row['id']}").json()["demo_source"] == row["demo_source"]
    cert = client.get(f"/runs/{row['id']}/certificate").json()
    assert cert["verdict"] == "RUNS_AFTER_REPAIR" and cert["reproduction_passport_hash"] == "p" * 64 and "outcome_levels" in cert
    # a seeded run replays its stored log over the stream endpoint rather than executing
    assert "[intake] cloned" in client.get(f"/runs/{row['id']}/stream").text

    paged = client.get("/runs", params={"limit": 1, "offset": 1}).json()
    assert len(paged["runs"]) == 1 and paged["total"] == 2 and paged["limit"] == 1 and paged["offset"] == 1
    assert client.get("/runs", params={"limit": 201}).status_code == 422


def test_list_runs_is_empty_on_a_fresh_db(client):
    assert client.get("/runs").json() == {"runs": [], "total": 0, "limit": 200, "offset": 0}


def test_lifespan_seeds_in_demo_mode(demo_root, tmp_path, monkeypatch):
    from app import main as main_module

    engine = create_engine(f"sqlite:///{tmp_path / 'app.db'}")
    Base.metadata.create_all(engine)
    _add_missing_columns(engine)
    monkeypatch.setattr(main_module, "SessionLocal", sessionmaker(bind=engine))

    root_str = str(demo_root)

    class _S:
        demo_mode = True
        demo_root = root_str

    monkeypatch.setattr(main_module, "get_settings", lambda: _S())
    assert main_module.seed_demo_records() == 2
    assert main_module.seed_demo_records() == 0
