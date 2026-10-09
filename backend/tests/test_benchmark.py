"""The cheat benchmark package (benchmark/, owner 2026-10-09, task 3): byte copies of both sets with their hashes, RERUN's decision files derived from the committed
records, and a scorer whose `--all` output is the published per-layer tables (reports/v1.9/figures.json carries them)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from benchmark import build, score  # noqa: E402


def test_the_package_is_what_the_committed_records_give():
    assert build.main(["--check"]) == 0


def test_the_copies_hash_to_what_each_set_was_published_with():
    hashes = json.loads((ROOT / "benchmark" / "HASHES.json").read_text(encoding="utf-8"))
    published = json.loads((ROOT / "reports" / "v1.10" / "independent" / "SET_HASH.json").read_text(encoding="utf-8"))["set_sha256"]
    assert build.set_hash_of(ROOT / "benchmark" / "sets" / "independent") == published == hashes["independent_set_sha256"]


def test_score_all_is_the_table_figures_json_publishes():
    published = json.loads((ROOT / "reports" / "v1.9" / "figures.json").read_text(encoding="utf-8"))["tables"]
    fresh = score.score_all(score.labels())
    assert {name: r["table"] for name, r in fresh.items()} == {name: t["table"] for name, t in published.items()}


def test_the_dropped_list_is_the_cheats_that_did_not_reach_exit_zero():
    dropped = json.loads((ROOT / "benchmark" / "sets" / "independent" / "dropped.json").read_text(encoding="utf-8"))["dropped"]
    measured = set((ROOT / "benchmark" / "sets" / "independent" / "measured_ids.txt").read_text(encoding="utf-8").split())
    manifest = json.loads((ROOT / "benchmark" / "sets" / "independent" / "manifest.json").read_text(encoding="utf-8"))
    assert len(dropped) == sum(1 for m in manifest if m["kind"] == "cheat") - sum(1 for m in manifest if m["kind"] == "cheat" and m["id"] in measured) == 22
    assert all(d["exit_code"] != 0 or d["timed_out"] for d in dropped)


def test_a_new_checker_can_be_scored_and_a_malformed_file_is_refused(tmp_path):
    lab = score.labels()
    measured = [i for i, v in lab.items() if v["set"] == "independent" and v["subset"] == "measured"]
    good = tmp_path / "mine.jsonl"
    good.write_text("".join(json.dumps({"id": i, "decision": "refuse" if lab[i]["kind"] == "cheat" else "adopt"}) + "\n" for i in measured), encoding="utf-8")
    which, rows = score.load(good, lab)
    t = score.table(rows, lab)
    assert which == "independent" and t["all_cheats"]["refused"] == 144 and t["all_controls"]["adopted"] == 42
    bad = tmp_path / "bad.jsonl"
    bad.write_text(json.dumps({"id": measured[0], "decision": "maybe"}) + "\n", encoding="utf-8")
    with pytest.raises(SystemExit):
        score.load(bad, lab)
    short = tmp_path / "short.jsonl"
    short.write_text("".join(json.dumps({"id": i, "decision": "adopt"}) + "\n" for i in measured[:10]), encoding="utf-8")
    with pytest.raises(SystemExit):
        score.load(short, lab)


def test_the_flag_mode_file_says_what_it_is():
    index = json.loads((ROOT / "benchmark" / "decisions" / "INDEX.json").read_text(encoding="utf-8"))
    note = index["independent.flag_mode.derived"]["note"]
    for phrase in ("derived from committed records", "chosen after these results were seen", "exercised by no cheat", "unmeasured"):
        assert phrase in note
    readme = (ROOT / "benchmark" / "README.md").read_text(encoding="utf-8")
    assert "both are development material now" in readme


def test_every_committed_blob_of_the_package_is_the_byte_copy_its_hash_names():
    """The index (what a fresh checkout gets) holds the exact bytes: .gitattributes marks the package -text, so no line ending is converted (34 independent patches
    are byte-mixed on purpose)."""
    import hashlib
    import subprocess

    hashes = json.loads((ROOT / "benchmark" / "HASHES.json").read_text(encoding="utf-8"))["files"]
    for rel, digest in hashes.items():
        blob = subprocess.run(["git", "-C", str(ROOT), "show", f":benchmark/{rel}"], capture_output=True, check=True).stdout
        assert hashlib.sha256(blob).hexdigest() == digest, rel
