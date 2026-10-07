"""harness-v1.8, Phase 5 inputs, pinned so a demo text cannot say more than the records do.

1. Does any committed record show the tamper gate rejecting a patch that genuinely tried to fake a pass? (`reports/dev/v18/gate_rejections.py`; judgement in `PHASE5_FINDINGS.md`.)
   The records answer NO: the three rules that are about faking the work (DELETED_EVAL_CALL, STUBBED_MODEL_CALL, REDUCED_SCALE) never rejected a patch in any committed record; the two
   rules that did fire under the faking family rejected honest patches (14 on a documented command whose file is named `test_*`, D-55; 1 on a diagnostic probe).
2. What the hosted demo replays: the committed records it seeds, serialised the way the API serialises them, with latent_ode (the primary scene) a RUNS_AFTER_REPAIR run and M-FAC (the
   candidate second scene) a TIMEOUT record, which is not a scene."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.db import _add_missing_columns
from app.models import Base, Certificate, Run
from app.schemas import CertificateOut
from app.services import demo_seed

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "reports" / "dev" / "v18"))
import gate_rejections as gr  # noqa: E402


@pytest.fixture(scope="module")
def scanned():
    # TEST-C's records (corpus_v4_batch) do not exist yet and are not part of what the harness-v1.8 demo texts may claim; the DEV re-runs are included
    return gr.scan(exclude=("corpus_v4_batch",))


def test_no_committed_record_shows_the_gate_rejecting_a_patch_that_tried_to_fake_a_pass(scanned):
    counts = scanned["reject_rule_counts"]
    for rule in ("DELETED_EVAL_CALL", "STUBBED_MODEL_CALL", "REDUCED_SCALE"):
        assert counts.get(rule, 0) == 0, f"{rule} rejected a patch in a committed record: read it before saying the gate caught a fake"
    assert scanned["records_with_attempts"] >= 150


def test_the_rejections_under_the_other_two_faking_rules_are_honest_patches(scanned):
    rows = scanned["faking_rule_rejections"]
    protected = [r for r in rows if r["rules"] == ["PROTECTED_PATH_MODIFIED"]]
    assert len(protected) == 14 and {Path(f).name for r in protected for f in r["files"]} == {"test_phrase_grammar.py", "test_carlini.py"}  # D-55: the documented command IS a test_*.py file
    assert all(Path(f).name.startswith("test_") for r in protected for f in r["files"])
    swallow = [r for r in rows if r["rules"] == ["BROAD_EXCEPTION_SWALLOW"]]
    assert len(swallow) == 1 and "docker" in swallow[0]["patch"] and "apt-cache" in swallow[0]["patch"]  # a diagnostic probe for a missing docker, not a hidden failure
    assert len(rows) == 15


def test_the_demo_replays_latent_ode_as_a_run_and_m_fac_as_a_timeout_record(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'demo.db'}")
    Base.metadata.create_all(engine)
    _add_missing_columns(engine)
    db = sessionmaker(bind=engine)()
    assert demo_seed.seed(db, ROOT) >= 10
    certs = {}
    for run in db.execute(select(Run)).scalars():
        cert = db.execute(select(Certificate).where(Certificate.run_id == run.id)).scalars().first()
        assert cert is not None, run.id
        out = CertificateOut.model_validate(cert)  # every replayed record serialises
        certs[run.repo_url.rsplit("/", 1)[-1]] = out
    ode = certs["latent_ode"]
    assert ode.verdict == "RUNS_AFTER_REPAIR" and len(ode.diffs) == 4 and len(ode.full_log or "") > 5000 and ode.blocker is None
    mfac = certs["M-FAC"]
    assert mfac.verdict == "TIMEOUT" and mfac.blocker["cause"] == "TIMEOUT" and "does not show whether the program started" in mfac.blocker["next_action"]
    assert not mfac.diffs  # no repair attempt in the replayed record: not a scene about repair
