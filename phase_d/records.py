"""The 65 per-entry run records of harness-v1.3.2 / v1.3.3 / v1.3.4 / v1.4.0 / v1.4.1 / v1.4.2 / v1.4.3, read from git, never from the worktree.

A record's identity is `<harness_tag>/<arm>/<entry>@<sha256>`, with the SHA-256 taken over the committed blob
(`git cat-file blob HEAD:<path>`). The worktree copy is not a valid basis: with `core.autocrlf=true` a checkout
rewrites LF to CRLF, so its hash differs from machine to machine.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

ROOT = Path(__file__).resolve().parents[1]

ENTRY_FILE = re.compile(r"^\d{2}_[^/]+\.json$")


@dataclass(frozen=True)
class RecordSet:
    harness_tag: str
    name: str  # the folder role: control, control/infra_retries, treatment, smoke
    directory: str
    expected: int


RECORD_SETS: tuple[RecordSet, ...] = (
    RecordSet("harness-v1.3.2", "control", "runs/corpus_v2_batch/harness-v1.3.2/control", 20),
    RecordSet("harness-v1.3.2", "control/infra_retries", "runs/corpus_v2_batch/harness-v1.3.2/control/infra_retries", 1),
    RecordSet("harness-v1.3.2", "treatment", "runs/corpus_v2_batch/harness-v1.3.2/treatment", 20),
    RecordSet("harness-v1.3.3", "smoke", "runs/corpus_v2_batch/harness-v1.3.3/smoke", 4),
    RecordSet("harness-v1.3.4", "smoke", "runs/corpus_v2_batch/harness-v1.3.4/smoke", 4),
    # the v1.4.x gates (entries 3, 7, 8, 11, TREATMENT only): the folder is `gate`, not `smoke`
    RecordSet("harness-v1.4.0", "gate", "runs/corpus_v2_batch/harness-v1.4.0/gate", 4),
    RecordSet("harness-v1.4.1", "gate", "runs/corpus_v2_batch/harness-v1.4.1/gate", 4),
    RecordSet("harness-v1.4.2", "gate", "runs/corpus_v2_batch/harness-v1.4.2/gate", 4),
    RecordSet("harness-v1.4.3", "gate", "runs/corpus_v2_batch/harness-v1.4.3/gate", 4),
)
EXPECTED_TOTAL = sum(s.expected for s in RECORD_SETS)  # 65


class BlobSource(Protocol):
    def list_dir(self, directory: str) -> list[str]: ...

    def read(self, path: str) -> bytes: ...


class GitBlobSource:
    """Committed blobs at one revision. Lists and reads through git only."""

    def __init__(self, root: Path = ROOT, rev: str = "HEAD") -> None:
        self.root, self.rev = Path(root), rev

    def _git(self, *args: str) -> bytes:
        return subprocess.run(["git", *args], cwd=self.root, check=True, capture_output=True).stdout

    def list_dir(self, directory: str) -> list[str]:
        out = self._git("ls-tree", "--name-only", f"{self.rev}:{directory}").decode("utf-8")
        return sorted(f"{directory}/{name}" for name in out.splitlines() if name)

    def read(self, path: str) -> bytes:
        return self._git("cat-file", "blob", f"{self.rev}:{path}")


@dataclass(frozen=True)
class Record:
    path: str
    record_set: RecordSet
    blob: bytes
    data: dict

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.blob).hexdigest()

    @property
    def harness_tag(self) -> str:
        return self.data["batch"]["harness_tag"]

    @property
    def arm(self) -> str:
        return self.data["batch"]["arm"]

    @property
    def entry(self) -> str:
        return f"{int(self.data['batch']['entry_id']):02d}"

    @property
    def record_id(self) -> str:
        return make_record_id(self.harness_tag, self.arm, self.entry, self.blob)


def make_record_id(harness_tag: str, arm: str, entry: str, blob: bytes) -> str:
    return f"{harness_tag}/{arm}/{entry}@{hashlib.sha256(blob).hexdigest()}"


class RecordError(Exception):
    pass


def load_records(source: BlobSource | None = None) -> list[Record]:
    """All 65 records in a fixed order (set order, then path). Raises if a set has an unexpected count."""
    source = source or GitBlobSource()
    records: list[Record] = []
    for rs in RECORD_SETS:
        paths = [p for p in source.list_dir(rs.directory) if ENTRY_FILE.match(p.rsplit("/", 1)[1])]
        if len(paths) != rs.expected:
            raise RecordError(f"{rs.directory}: {len(paths)} entry records, expected {rs.expected}")
        for path in paths:
            blob = source.read(path)
            data = json.loads(blob.decode("utf-8"))
            record = Record(path, rs, blob, data)
            if record.harness_tag != rs.harness_tag:
                raise RecordError(f"{path}: batch.harness_tag {record.harness_tag!r} is not {rs.harness_tag!r}")
            if not path.rsplit("/", 1)[1].startswith(record.entry + "_"):
                raise RecordError(f"{path}: file name does not match batch.entry_id {record.entry}")
            records.append(record)
    ids = [r.record_id for r in records]
    if len(set(ids)) != len(ids) or len(ids) != EXPECTED_TOTAL:
        raise RecordError(f"{len(ids)} records, {len(set(ids))} unique ids, expected {EXPECTED_TOTAL}")
    return records
