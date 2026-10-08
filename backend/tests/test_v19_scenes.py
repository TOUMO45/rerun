"""harness-v1.9, task 5: the demo's scenes. latent_ode stays the primary scene; spline-calibration is the second ("candidates that reach exit 0 by skipping
missing inputs, none adopted"). Every claim of a caption is computed from the committed record, a scene whose record does not support its caption is
not listed, and every scene is marked REPLAY. These tests read the real committed records."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import _add_missing_columns
from app.models import Base, Run
from app.services import demo_seed

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def db(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'scenes.db'}")
    Base.metadata.create_all(engine)
    _add_missing_columns(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


def _record(scene_id: str) -> dict:
    scene = next(s for s in demo_seed.SCENES if s["id"] == scene_id)
    return json.loads((ROOT / scene["record"]).read_text(encoding="utf-8"))


def test_latent_ode_is_the_primary_scene_and_every_scene_is_a_replay():
    ordered = sorted(demo_seed.SCENES, key=lambda s: s["order"])
    assert [s["id"] for s in ordered] == ["latent_ode", "spline-calibration"]
    assert {s["mode"] for s in demo_seed.SCENES} == {"REPLAY"}


def test_the_latent_ode_caption_is_what_its_record_says():
    claims = demo_seed._latent_ode_claims(_record("latent_ode"))
    text = " ".join(c["text"] for c in claims)
    assert "ModuleNotFoundError: No module named 'matplotlib'" in text
    assert "dataclasses==0.8" in text and "DEP_YANKED" in text
    assert "candidate 1: remove `dataclasses`" in text and "candidate 3: Python 3.6" in text
    assert "adopts candidate 1" in text and "RUNS_AFTER_REPAIR" in text and "not a reproduction" in text


def test_the_spline_caption_counts_six_skipping_candidates_none_adopted():
    """The owner's brief said "seven"; the record shows six candidates that reached exit 0 by skipping (rounds 2 and 3), and the caption says six."""
    claims = demo_seed._spline_claims(_record("spline-calibration"))
    text = " ".join(c["text"] for c in claims)
    assert "In rounds 2 and 3, 6 candidates pass the tamper gate (harness-v1.8.0)" in text
    assert "adopts none" in text and "BLOCKED (DATA_MISSING)" in text


def test_a_record_that_contradicts_the_caption_drops_the_scene():
    rec = copy.deepcopy(_record("spline-calibration"))
    for a in rec["result"]["attempts"]:
        if a.get("exit_code") == 0 and a.get("origin") == "model":
            a["chosen"] = True
            break
    assert demo_seed._spline_claims(rec) is None
    rec = copy.deepcopy(_record("latent_ode"))
    rec["result"]["verdict"] = "BLOCKED"
    assert demo_seed._latent_ode_claims(rec) is None


def test_seeding_the_scenes_adds_the_test_c_record_once_and_lists_both(db):
    assert demo_seed.seed_scenes(db, ROOT) == 2  # an empty database: both records are added
    assert demo_seed.seed_scenes(db, ROOT) == 0
    spline = db.get(Run, "demo-harness-v1.8.0-treatment-01")
    assert spline.verdict == "BLOCKED" and spline.demo_source.startswith("runs/corpus_v4_batch/")
    listed = demo_seed.list_scenes(db, ROOT)
    assert [s["id"] for s in listed] == ["latent_ode", "spline-calibration"]
    assert all(s["mode"] == "REPLAY" and s["claims"] for s in listed)
    assert listed[1]["note"].startswith("Not from the record")


def test_an_unseeded_scene_is_not_listed(db):
    assert demo_seed.list_scenes(db, ROOT) == []
