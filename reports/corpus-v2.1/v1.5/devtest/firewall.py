"""The TEST firewall of the v1.5 dev/test protocol (METHODOLOGY, "harness-v1.5 dev/test protocol", rule F).

Until the freeze, nothing in the v1.5 program opens, runs or reports a TEST entry: not its corpus entry, not a record of any version, not a passport or REPLAY page of it.
The entry id of a record is read from its FILE NAME (`NN_<name>.json`), so a TEST record is refused before it is opened.
The one switch is the environment variable RERUN_V15_FROZEN=1: nothing in this repository sets it; the TEST phase's own script sets it after the tag harness-v1.5-final is pushed.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

try:  # imported as a package member (tests) or as a plain module (the runner puts this directory on sys.path)
    from . import split
except ImportError:  # pragma: no cover
    import split

TEST_ENTRIES = frozenset(split.split()["test"])
DEV_ENTRIES = frozenset(split.DEV_ENTRIES)
GATE_ENTRIES = frozenset(split.GATE_ENTRIES)
ANALYSIS_ENTRIES = DEV_ENTRIES | GATE_ENTRIES  # the entries whose records the v1.5 failure analysis may read (all versions)
FROZEN_ENV = "RERUN_V15_FROZEN"
_ID_RE = re.compile(r"^(\d{2})_")


class FirewallError(RuntimeError):
    """A TEST entry was about to be opened, run or reported before the freeze."""


def frozen() -> bool:
    return os.environ.get(FROZEN_ENV) == "1"


def assert_not_test(entry_id: int, *, what: str = "read") -> None:
    if entry_id in TEST_ENTRIES and not frozen():
        raise FirewallError(f"refused to {what} a TEST entry before the freeze (entry id {entry_id}): METHODOLOGY rule F")


def entry_id_of(path: Path | str) -> int | None:
    """The entry id of a record file from its name (`07_owner__repo.json` -> 7); None for a file that is not an entry record."""
    match = _ID_RE.match(Path(path).name)
    return int(match.group(1)) if match else None


def may_read_record(path: Path | str) -> bool:
    """True if the record may be opened for the v1.5 analysis: an entry record of a DEV or gate entry, or a file that is not an entry record at all."""
    entry_id = entry_id_of(path)
    return entry_id is None or entry_id not in TEST_ENTRIES or frozen()


def read_record_text(path: Path | str) -> str:
    entry_id = entry_id_of(path)
    if entry_id is not None:
        assert_not_test(entry_id, what=f"open {Path(path).name}")
    return Path(path).read_text(encoding="utf-8")


def analysis_records(runs_dir: Path, pattern: str = "harness-*/**/[0-9][0-9]_*.json") -> list[Path]:
    """Every entry record under `runs_dir` that the failure analysis may read: DEV and gate entries only. TEST records are listed by name by the glob (a directory listing, not a
    read) and dropped here; they are never opened."""
    return sorted(p for p in runs_dir.glob(pattern) if (entry_id_of(p) in ANALYSIS_ENTRIES))
