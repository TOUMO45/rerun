"""harness-v1.8 (T6, the minimum): "era lock unavailable" names its real cause. Five of the 21 held-out entries (now DEV-CONTAMINATED) logged it and fell back to one unpinned pip step; the
full uv message is in each record's time-machine attempt (`attempts[0].time_machine.lock.error`, up to 2,000 characters), read below. Only the NAMING changes: no lock behaviour does."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services import time_machine
from app.services.time_machine import LockResult

ROOT = Path(__file__).resolve().parents[2]
CASES = [
    ("runs/corpus_v2_batch/harness-v1.5-final/test/13_seongjunyun__neo_gnns.json", "BUILD_NEEDS_BUILD_DEPENDENCY"),
    ("runs/corpus_v3_batch/harness-v1.7.2/treatment/05_twitter-research__cwn.json", "BUILD_NEEDS_BUILD_DEPENDENCY"),
    ("runs/corpus_v2_batch/harness-v1.5-final/test/19_lrjconan__RBP.json", "CUTOFF_BELOW_BUILD_TOOL"),
    ("runs/corpus_v2_batch/harness-v1.5-final/test/20_XiaoxiaoGuo__fashion-retrieval.json", "SDIST_METADATA_BUILD_FAILED_ON_HOST"),
]


@pytest.mark.parametrize("rel, cause", CASES, ids=[Path(c[0]).stem[:24] for c in CASES])
def test_the_recorded_uv_message_gets_its_cause(rel, cause):
    attempts = json.loads((ROOT / rel).read_text(encoding="utf-8"))["result"]["attempts"]
    lock = None
    for a in attempts:
        tm = a.get("time_machine")
        if isinstance(tm, str):
            import ast
            tm = ast.literal_eval(tm)
        if isinstance(tm, dict) and (tm.get("lock") or {}).get("ok") is False:
            lock = tm["lock"]
            break
    assert lock is not None and lock["error"]
    found = time_machine.lock_failure_cause(lock["error"])
    assert found is not None and found["id"] == cause
    assert found["quote"] and found["quote"] in lock["error"] and "\n" not in found["quote"]  # ONE verbatim line of uv's own message
    if cause == "BUILD_NEEDS_BUILD_DEPENDENCY":
        assert '"torch"' in found["detail"] or "torch" in found["detail"]  # the dependency comes from uv's hint


def test_a_no_build_isolation_hint_that_names_another_package_does_not_say_torch():
    hint = "hint: ...\n[tool.uv.extra-build-dependencies]\nfoo = [\"numpy\"]\nor re-run with `--no-build-isolation`."
    found = time_machine.lock_failure_cause(hint)
    assert found["id"] == "BUILD_NEEDS_BUILD_DEPENDENCY" and "`foo`" in found["detail"] and "numpy" in found["detail"] and "torch" not in found["detail"]
    assert time_machine.lock_failure_cause("re-run with `--no-build-isolation`") is None  # a bare hint names nothing: no claim


def test_fb_scrapers_unsatisfiable_message_is_named():
    found = time_machine.lock_failure_cause("you require rerun-backend, we can conclude that your requirements are unsatisfiable.")
    assert found["id"] == "REQUIREMENTS_UNSATISFIABLE"


def test_an_unknown_message_gets_no_cause_and_a_good_lock_has_none():
    assert time_machine.lock_failure_cause("something uv never said") is None
    assert "cause" not in LockResult(True, ("numpy==1.19.5",), ("numpy",)).as_dict()
    failed = LockResult(False, (), ("numpy",), (), "uv pip compile", "your requirements are unsatisfiable").as_dict()
    assert failed["cause"]["id"] == "REQUIREMENTS_UNSATISFIABLE"
