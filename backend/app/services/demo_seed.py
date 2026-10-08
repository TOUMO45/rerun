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


# --- harness-v1.9 (owner, 2026-10-08, task 5): the demo's scenes ------------------------------------------------------------------------------------
# A scene is one committed record, replayed (mode REPLAY: nothing executes), with a caption. Every claim of a caption is COMPUTED from the record when
# the scene is listed, and a scene whose record does not support every claim is not shown (`scene_claims` returns None and the reason is logged).
# latent_ode stays the primary scene. spline-calibration is a TEST-C record (corpus-v4, published and final): it sits outside the TEST firewall's
# directory (which guards corpus-v2's TEST entries during the v1.5 protocol) and is read here by its exact path, never by a glob.
SCENES: tuple[dict, ...] = (
    {"id": "latent_ode", "order": 1, "mode": "REPLAY", "record": "runs/corpus_v2_batch/harness-v1.7.1/dev/15_YuliaRubanova__latent_ode.json",
     "title": "A dependency the paper's era cannot install, fixed by a gate-checked environment change"},
    {"id": "spline-calibration", "order": 2, "mode": "REPLAY", "record": "runs/corpus_v4_batch/harness-v1.8.0/treatment/01_kartikgupta-at-anu__spline-calibration.json",
     "title": "Candidates that reach exit 0 by skipping missing inputs, none adopted"},
)
_SKIP_MARK = re.compile(r"Skipping|Missing logit files", re.IGNORECASE)


def _claim(text: str, basis: str) -> dict:
    return {"text": text, "basis": basis}


def _latent_ode_claims(rec: dict) -> list[dict] | None:
    cert, res = rec.get("certificate") or {}, rec.get("result") or {}
    base, chain, attempts = cert.get("baseline") or {}, res.get("error_chain") or [], res.get("attempts") or []
    if base.get("exit_code") in (0, None) or len(chain) < 2 or chain[0].get("cleared_by") != 0 or res.get("verdict") != "RUNS_AFTER_REPAIR":
        return None
    round1 = [a for a in attempts if a.get("attempt_number") == 1 and a.get("origin") == "model"]
    ran = [a for a in round1 if a.get("gate_decision") == "PASS" and a.get("exit_code") == 0]
    chosen = [a for a in ran if a.get("chosen") is True]
    declined = [a for a in round1 if a.get("gate_decision") == "DECLINED"]
    if len(chosen) != 1 or not chosen[0].get("env_delta") or chosen[0].get("diff_text"):
        return None

    def op(a: dict) -> str:
        d = (a.get("env_delta") or [{}])[0]
        if d.get("op") == "remove":
            return f"remove `{d.get('package')}`"
        if d.get("op") == "python":
            return f"Python {d.get('version')}"
        return f"{d.get('op')} {d.get('package') or ''}".strip()

    c = chosen[0]
    others = [a for a in ran if a is not c]
    execution = c.get("execution") or {}
    if not isinstance(execution.get("seconds"), (int, float)) or any((a.get("execution") or {}).get("outcome") != "alive_at_limit" for a in ran):
        return None  # "still running at the smoke limit" and the smoke length are read from the record, never assumed
    listed = "; ".join(f"candidate {a.get('candidate')}: {op(a)}" for a in sorted(ran, key=lambda a: a.get("candidate") or 0))
    return [
        _claim(f"As published ({base.get('base_image')}), the documented command fails: `{base.get('evidence')}`.", "certificate.baseline"),
        _claim(f"RERUN's time machine rebuilds the paper's era (attempt 0) and that error is cleared; the install then stops on "
               f"`{str(chain[1].get('error', ''))[:110]}` ({chain[1].get('class')}).", "result.error_chain[0].cleared_by, result.error_chain[1]"),
        _claim(f"The repairer model proposes {len(round1)} candidates, {len(declined)} of them a decline; {listed}. The tamper gate passes "
               f"{'both' if len(ran) == 2 else len(ran)}, and each is still running at the smoke limit.", "result.attempts (attempt 1), .execution.outcome"),
        _claim(f"The adjudicator adopts candidate {c.get('candidate')} ({op(c)}: an environment change, no code patch)"
               + (f" over candidate {', '.join(str(a.get('candidate')) for a in others)}" if others else "")
               + f". Verdict {res.get('verdict')}: a {execution.get('seconds')} s smoke run ({execution.get('outcome')}), not a reproduction of the paper's results.",
               "result.attempts[].chosen, result.verdict"),
    ]


def _spline_claims(rec: dict) -> list[dict] | None:
    cert, res = rec.get("certificate") or {}, rec.get("result") or {}
    chain, attempts = res.get("error_chain") or [], res.get("attempts") or []
    if res.get("verdict") != "BLOCKED" or not chain or chain[-1].get("class") != "DATA_MISSING":
        return None
    skipped = [a for a in attempts if a.get("origin") == "model" and a.get("gate_decision") == "PASS" and a.get("exit_code") == 0
               and _SKIP_MARK.search(a.get("stdout_tail") or "") and "Finished successfully" in (a.get("stdout_tail") or "")]
    if not skipped or any(a.get("chosen") is True for a in attempts) or any((a.get("adjudication") or {}).get("chosen") is not None for a in skipped):
        return None
    rounds = sorted({a.get("attempt_number") for a in skipped if isinstance(a.get("attempt_number"), int)})
    reason = str((skipped[0].get("adjudication") or {}).get("reasoning") or "")[:170].strip()
    tag = (rec.get("batch") or {}).get("harness_tag")
    if not rounds or not reason or not tag:
        return None  # the caption quotes the adjudicator and names the harness version: both must be in the record
    return [
        _claim(f"The documented command `{(cert.get('baseline') or {}).get('execute_command')}` stops on a logit file that is not in the checkout: "
               f"`{str(chain[-1].get('error', ''))[:120]}`.", "result.error_chain[-1]"),
        _claim(f"In rounds {' and '.join(str(r) for r in rounds)}, {len(skipped)} candidates pass the tamper gate ({tag}) and reach exit 0 by skipping the missing "
               f"files: their output reports them (`... Skipping.` or `Missing logit files`) and ends `Finished successfully`.", "result.attempts[].gate_decision, .exit_code, .stdout_tail"),
        _claim(f"The adjudicator adopts none of them: “{reason}…”", "result.attempts[].adjudication.chosen (null), .reasoning"),
        _claim(f"Verdict {res.get('verdict')} ({res.get('taxonomy_code')}): the program did not do its work, and the certificate says so. An agent that "
               f"trusted exit 0 would have reported it reproduced.", "result.verdict, result.taxonomy_code"),
    ]


_CLAIMS = {"latent_ode": _latent_ode_claims, "spline-calibration": _spline_claims}
_SCENE_NOTES = {"spline-calibration": "Not from the record: harness-v1.9 adds a tamper-gate rule (SKIPPED_MISSING_INPUT) for this pattern; this record was made at "
                                      "harness-v1.8.0, before it, so here the adjudicator alone refused the fakes."}


def scene_run_id(scene: dict) -> str:
    """The run id a scene's record is seeded under: the corpus-v2 id scheme (`demo-<tag>-<arm>-<NN>`), from the record's own path."""
    parts = Path(scene["record"]).parts
    return f"demo-{parts[-3]}-{parts[-2]}-{int(parts[-1][:2]):02d}"


def _read_scene_record(root: Path, scene: dict) -> dict | None:
    """The scene's record. A corpus-v2 record goes through the TEST firewall like every other record the demo opens; the TEST-C record (corpus-v4, published
    and final) is read by its exact path."""
    path = Path(root) / scene["record"]
    if not path.is_file():
        log.warning("demo scene %s: record %s missing", scene["id"], scene["record"])
        return None
    text = _load_firewall(Path(root)).read_record_text(path) if scene["record"].startswith(RUNS_SUBDIR.as_posix() + "/") else path.read_text(encoding="utf-8")
    return json.loads(text)


def scene_claims(root: Path, scene: dict) -> list[dict] | None:
    record = _read_scene_record(root, scene)
    if record is None:
        return None
    claims = _CLAIMS[scene["id"]](record)
    if claims is None:
        log.warning("demo scene %s: the record does not support every claim of the caption; the scene is not shown", scene["id"])
    return claims


def seed_scenes(db: Session, root: Path) -> int:
    """Seed every scene record that is not already in the database (the corpus-v2 one usually is, as the latest DEV record of its entry)."""
    added = 0
    for scene in SCENES:
        run_id = scene_run_id(scene)
        if db.get(Run, run_id) is not None or scene_claims(root, scene) is None:
            continue
        path = Path(root) / scene["record"]
        parts = path.parts
        name = _NAME_RE.match(parts[-1])
        ref = RecordRef(path, parts[-3], parts[-2], int(name.group(1)), name.group(2))
        run, certificate = rows_from_record(ref, _read_scene_record(root, scene), scene["record"])
        db.add(run)
        db.add(certificate)
        added += 1
    if added:
        db.commit()
    return added


def list_scenes(db: Session, root: Path) -> list[dict]:
    """The scenes whose run is in the database and whose record supports their caption, in order."""
    out = []
    for scene in sorted(SCENES, key=lambda s: s["order"]):
        run_id = scene_run_id(scene)
        run = db.get(Run, run_id)
        if run is None or run.demo_source != scene["record"]:
            continue  # not seeded, or the id is held by another corpus's record: never show one record's claims beside another's replay
        try:
            claims = scene_claims(root, scene)
        except Exception:  # noqa: BLE001 - a scene whose record cannot be read is left out; the route must not fail
            log.exception("demo scene %s could not be read", scene["id"])
            claims = None
        if claims is None:
            continue
        out.append({"id": scene["id"], "order": scene["order"], "mode": scene["mode"], "title": scene["title"], "run_id": run_id,
                    "record": scene["record"], "claims": claims, "note": _SCENE_NOTES.get(scene["id"])})
    return out
