"""TEST-C audit helper `reports/test-c/raw_evidence.py`: the key must be written from the raw log BEFORE any blocker text is read, so the helper must never print the blocker report's sentences.
Pinned on a DEV record whose stored blocker has distinctive sentences. The verdict's own `indeterminate_reason` (the harness's stop text, a hashed field of the verdict) is raw evidence and IS printed;
it is not the derived blocker."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "reports" / "test-c"))
import raw_evidence as re_  # noqa: E402

RECORD = ROOT / "runs" / "dev_v18" / "round1" / "TEST-B" / "05_twitter-research__cwn.json"


@pytest.mark.skipif(not RECORD.is_file(), reason="the DEV record is not in this checkout")
def test_the_raw_evidence_never_contains_the_blockers_sentences():
    record = json.loads(RECORD.read_text(encoding="utf-8"))
    blocker = record["result"]["blocker"]
    text = re_.render(record)
    for field in ("next_action", "what_a_human_must_supply"):
        assert str(blocker[field]) not in text, field  # the report's own sentences never appear
    assert "diagnosis" not in text and "fixable" not in text
    assert "conda: not found" in text  # the raw line the key is written from IS there
    assert "verdict INDETERMINATE" in text and "command: sh graph-tool_install.sh" in text


def test_the_helper_source_never_reads_the_blocker_fields():
    source = (ROOT / "reports" / "test-c" / "raw_evidence.py").read_text(encoding="utf-8")
    body = source.split("def render", 1)[1]
    for forbidden in ('"blocker"', "'blocker'", "next_action", "what_a_human_must_supply", "error_line", "fixable_by"):
        assert forbidden not in body, forbidden
