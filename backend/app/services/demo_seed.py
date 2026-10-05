"""DEMO / REPLAY mode seeder (harness-v1.6).

A hosted instance started with `DEMO_MODE=1` has no Nebius key and never
executes anything. Instead, on startup, this module loads RERUN's own
committed run records (`runs/corpus_v2_batch/<harness-tag>/<arm>/NN_<owner>__<repo>.json`)
into the ordinary `Run` / `Certificate` tables, so the normal Gallery,
timeline and certificate screens browse real recorded audits through the
same API a live run would use. Nothing here is synthesised: every stored
field is copied from the record as written.

Two rules are load-bearing:

* The TEST firewall (METHODOLOGY, v1.5 dev/test protocol, rule F). Every
  record path comes from `firewall.analysis_records` (which lists DEV and
  gate entries only, by file name) and every record is opened through
  `firewall.read_record_text` (which refuses a TEST entry). The seeder
  never globs or opens a record on its own.
* Record files are read-only data. The seeder reads them; it never writes
  under `runs/`.

Seeding is idempotent: a run's id is derived from the record's tag, arm and
entry number (`demo-<tag>-<arm>-<NN>`), so re-seeding the same root finds
the rows already present and leaves them alone.
"""

from __future__ import annotations

import json
import logging
import re
import sys
from collections.abc import Iterable
from pathlib import Path

from sqlalchemy.orm import Session

from app.models import Certificate, Run

log = logging.getLogger(__name__)

# Repository root, resolved from this file: services -> app -> backend -> root.
PACKAGE_REPO_ROOT = Path(__file__).resolve().parents[3]
RUNS_SUBDIR = Path("runs") / "corpus_v2_batch"
FIREWALL_SUBDIR = Path("reports") / "corpus-v2.1" / "v1.5" / "devtest"

# The record families the demo replays: the gate entries (arm `gate`, harness-v1.4.x) and the DEV entries (arm `dev`, harness-v1.5.0 onwards).
# harness-v1.7.1: every tag, so a later DEV round (harness-v1.6.0's round 4, round 5) is shown; the patterns had stopped at harness-v1.5.x, and the
# demo showed round 3 as the latest DEV record. The firewall filters every record, and the latest tag per entry wins (select_latest_per_entry).
RECORD_PATTERNS = (
    "harness-v*/gate/[0-9][0-9]_*.json",
    "harness-v*/dev/[0-9][0-9]_*.json",
)

_TAG_RE = re.compile(r"^harness-v(\d+)\.(\d+)\.(\d+)(?:-rc)?$")
_NAME_RE = re.compile(r"^(\d{2})_(.+)\.json$")

DEMO_FULL_LOG_NOTE = "(demo replay) this record stores no run log; the certificate below is served from the recorded audit as written."


class RecordRef:
    """Where a record sits: `<tag>/<arm>/<NN>_<name>.json` under the runs directory."""

    __slots__ = ("path", "tag", "arm", "entry_id", "name")

    def __init__(self, path: Path, tag: str, arm: str, entry_id: int, name: str) -> None:
        self.path = path
        self.tag = tag
        self.arm = arm
        self.entry_id = entry_id
        self.name = name

    @property
    def run_id(self) -> str:
        return f"demo-{self.tag}-{self.arm}-{self.entry_id:02d}"

    def __repr__(self) -> str:  # pragma: no cover
        return f"RecordRef({self.path.name}, {self.tag}, {self.arm}, {self.entry_id})"


def tag_key(tag: str) -> tuple[int, int, int]:
    """Sort key of a harness tag (`harness-v1.5.1` -> (1, 5, 1)); raises on anything else."""
    match = _TAG_RE.match(tag)
    if match is None:
        raise ValueError(f"not a harness tag: {tag!r}")
    return tuple(int(part) for part in match.groups())  # type: ignore[return-value]


def record_ref(runs_dir: Path, path: Path) -> RecordRef | None:
    """Parse `<runs_dir>/<tag>/<arm>/<NN>_<name>.json`; None for a file that is not an entry record of a tagged arm."""
    try:
        rel = path.relative_to(runs_dir)
    except ValueError:
        return None
    if len(rel.parts) != 3:
        return None
    tag, arm, filename = rel.parts
    name_match = _NAME_RE.match(filename)
    if name_match is None or _TAG_RE.match(tag) is None:
        return None
    return RecordRef(path, tag, arm, int(name_match.group(1)), name_match.group(2))


def select_latest_per_entry(refs: Iterable[RecordRef]) -> list[RecordRef]:
    """The selection rule of the default demo set, a pure function of the record list.

    For every entry id, keep the ONE record of the highest harness tag (compared numerically, `harness-v1.5.1` > `harness-v1.4.3`).
    A tie on the tag (the same entry recorded under two arms of one tag) is broken by the arm name, then the file name, so the result
    is deterministic for any input order. The output is sorted by entry id.
    """
    best: dict[int, RecordRef] = {}
    for ref in refs:
        key = (tag_key(ref.tag), ref.arm, ref.path.name)
        current = best.get(ref.entry_id)
        if current is None or key > (tag_key(current.tag), current.arm, current.path.name):
            best[ref.entry_id] = ref
    return [best[entry_id] for entry_id in sorted(best)]


def _load_firewall(root: Path):
    """Import `firewall` from reports/corpus-v2.1/v1.5/devtest (the way the replay tests do): the only way a record is listed or opened."""
    devtest = root / FIREWALL_SUBDIR
    if not (devtest / "firewall.py").is_file():
        raise FileNotFoundError(f"TEST firewall not found at {devtest}")
    devtest_str = str(devtest)
    if devtest_str not in sys.path:
        sys.path.insert(0, devtest_str)
    import firewall  # noqa: PLC0415

    return firewall


def allowed_records(root: Path, versions: list[str] | None = None) -> list[RecordRef]:
    """Every record the demo may replay: the firewall's listing of DEV and gate entries under the demo's patterns, restricted to `versions` (tags) when given,
    and reduced to the latest tag per entry when not."""
    firewall = _load_firewall(root)
    runs_dir = root / RUNS_SUBDIR
    refs: list[RecordRef] = []
    for pattern in RECORD_PATTERNS:
        for path in firewall.analysis_records(runs_dir, pattern):
            ref = record_ref(runs_dir, path)
            if ref is not None:
                refs.append(ref)
    if versions is None:
        return select_latest_per_entry(refs)
    wanted = set(versions)
    return sorted((r for r in refs if r.tag in wanted), key=lambda r: (tag_key(r.tag), r.arm, r.entry_id))


def _text(value) -> str:
    return value if isinstance(value, str) else ("" if value is None else json.dumps(value))


def rows_from_record(ref: RecordRef, record: dict, demo_source: str) -> tuple[Run, Certificate]:
    """Build the `Run` and `Certificate` rows for one record (no DB access). Fields come from the stored `certificate` dict first (the signed bundle),
    with the `result` dict filling what the certificate does not carry (prose, taxonomy, chain)."""
    corpus_entry = record.get("corpus_entry") or {}
    result = record.get("result") or {}
    cert = record.get("certificate") or {}

    verdict = cert.get("verdict") or result.get("verdict") or "INDETERMINATE"
    taxonomy_code = cert.get("taxonomy_code") if cert.get("taxonomy_code") is not None else result.get("taxonomy_code")
    indeterminate_reason = cert.get("indeterminate_reason") if cert.get("indeterminate_reason") is not None else result.get("indeterminate_reason")
    error_chain = cert.get("error_chain") if cert.get("error_chain") is not None else result.get("error_chain")
    attempts = cert.get("diffs") if cert.get("diffs") is not None else result.get("attempts")
    build_plan = cert.get("build_plan") if cert.get("build_plan") is not None else result.get("build_plan")
    full_log = cert.get("full_log")

    run = Run(
        id=ref.run_id,
        repo_url=corpus_entry.get("repo_url") or cert.get("repo_url") or "",
        commit_sha=corpus_entry.get("commit_sha") or cert.get("commit_sha"),
        stage="DONE",
        verdict=verdict,
        taxonomy_code=taxonomy_code,
        indeterminate_reason=indeterminate_reason,
        attempts_used=len(attempts or []),
        build_plan=build_plan,
        demo_source=demo_source,
    )
    certificate = Certificate(
        run_id=ref.run_id,
        verdict=verdict,
        certificate_prose=_text(result.get("certificate_prose") or cert.get("certificate_prose")),
        full_log=full_log if isinstance(full_log, str) and full_log else DEMO_FULL_LOG_NOTE,
        build_plan=build_plan or {},
        diffs=list(attempts or []),
        reproduction_passport_hash=_text(cert.get("reproduction_passport_hash")),
        timestamp=_text(cert.get("timestamp") or record.get("finished_at")),
        bundle_version=cert.get("bundle_version") or 1,
        baseline=cert.get("baseline"),
        recovery=cert.get("recovery"),
        tree_integrity=cert.get("tree_integrity") or record.get("tree_integrity"),
        corpus_hash=cert.get("corpus_hash"),
        taxonomy_code=taxonomy_code,
        indeterminate_reason=indeterminate_reason,
        error_chain=list(error_chain or []),
        first_repo_error=cert.get("first_repo_error") if cert.get("first_repo_error") is not None else result.get("first_repo_error"),
        last_error=cert.get("last_error") if cert.get("last_error") is not None else result.get("last_error"),
        blocker_sources=cert.get("blocker_sources"),
    )
    return run, certificate


def seed(db: Session, root: Path, versions: list[str] | None = None) -> int:
    """Insert one `Run` + `Certificate` per allowed record under `<root>/runs/corpus_v2_batch`; returns how many were ADDED (0 on a re-seed).

    `versions=None` seeds the latest tag per entry (`select_latest_per_entry`); a list of tags seeds every allowed record of those tags.
    A root without the runs directory or the firewall module seeds nothing (logged, not raised) so an image shipped without the data still starts.
    """
    root = Path(root)
    if not (root / RUNS_SUBDIR).is_dir():
        log.warning("demo seed: %s has no %s directory; nothing to replay", root, RUNS_SUBDIR)
        return 0
    try:
        refs = allowed_records(root, versions)
    except FileNotFoundError as exc:
        log.warning("demo seed: %s; nothing to replay", exc)
        return 0
    firewall = _load_firewall(root)

    added = 0
    for ref in refs:
        if db.get(Run, ref.run_id) is not None:
            continue
        record = json.loads(firewall.read_record_text(ref.path))
        demo_source = ref.path.relative_to(root).as_posix()
        run, certificate = rows_from_record(ref, record, demo_source)
        db.add(run)
        db.add(certificate)
        added += 1
    if added:
        db.commit()
    log.info("demo seed: %d record(s) added, %d already present", added, len(refs) - added)
    return added
