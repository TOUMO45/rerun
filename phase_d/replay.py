"""Phase D REPLAY: an offline, deterministic replay of harness-v1.3.2 / v1.3.3 / v1.3.4 from committed records.

REPLAY reads each record blob, rebuilds the entry's timeline (baseline -> era lock -> attempts -> verdict -> cost),
and cross-checks every value it shows against the passport field it displays. A mismatch is a build failure.

Number rule (Phase D housekeeping 3): no displayed number comes from text. Every number in the output is a tagged
passport field, carried with a pointer to it:
  * `ref`      {"record_id", "field"}                    the value and tag of that passport field;
  * `sum_of`   {"field", "run_order_through"}            the sum of that passport field over the version's run order
                                                         up to and including that record;
  * `count_of` {"field", "equals", "records"}            how many of those passports have that field value.
Text that contains digits (ids, error messages, quoted source lines, the D1 badge sentence) is a quoted string.
The output carries no build timestamp and no absolute path.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from . import defects as register
from .passports import DERIVED, ESTIMATED, GATE_FILES, MEASURED, PASSPORT_DIR, RECOVERED, RESULTS_TABLES, TAGS, passport_path
from .records import ROOT, BlobSource, GitBlobSource, Record, load_records

SCHEMA = "rerun/phase-d/replay/v1"
REPLAY_DIR = "reports/phase-d/replay"
VERSIONS = ("harness-v1.3.2", "harness-v1.3.3", "harness-v1.3.4")
_SKIP = object()
_PATH = re.compile(r"([^.\[\]]+)|\[(\d+)\]")
_NUMBER = re.compile(r"\d+(?:\.\d+)?")


class ReplayError(Exception):
    """REPLAY and the passports (or the records) disagree: the build stops."""


def resolve(obj: Any, field: str) -> Any:
    for name, index in _PATH.findall(field):
        obj = obj[int(index)] if index else obj[name]
    return obj


def is_tagged(obj: Any) -> bool:
    return isinstance(obj, dict) and "tag" in obj and "value" in obj


def load_passports(root: Path = ROOT) -> dict[str, dict]:
    """The stored passports, keyed by record id."""
    out: dict[str, dict] = {}
    for file in sorted((Path(root) / PASSPORT_DIR).rglob("*.json")):
        passport = json.loads(file.read_bytes().replace(b"\r\n", b"\n").decode("utf-8"))
        out[passport["record_id"]] = passport
    return out


# ---------------------------------------------------------------- one entry: passport fields, cross-checked against the record

class _Entry:
    def __init__(self, record: Record, passport: dict, records_by_id: dict[str, Record]) -> None:
        self.record, self.passport, self.records_by_id = record, passport, records_by_id
        self.rid = record.record_id

    def _fail(self, field: str, shown: Any, expected: Any) -> None:
        raise ReplayError(f"{self.record.path}: passport field {field!r} is {shown!r}, the record gives {expected!r}")

    def _check_derived(self, field: str, obj: dict) -> None:
        sources = obj["source"] if isinstance(obj["source"], list) else [obj["source"]]
        for src in sources:
            source_record = self.records_by_id.get(src["record_id"])
            if source_record is None or resolve(source_record.data, src["field"]) != src["line"]:
                raise ReplayError(f"{self.record.path}: {field}: quoted source line is not in record {src['record_id']} at {src['field']}")
        value = obj["value"]
        if isinstance(sources, list) and isinstance(obj["source"], list):
            ok = value == len(sources)
        elif isinstance(value, str):
            ok = sources[0]["line"].startswith(f"[{value}]")
        else:
            ok = any(float(token) == float(value) for token in _NUMBER.findall(sources[0]["line"]))
        if not ok:
            raise ReplayError(f"{self.record.path}: {field}: DERIVED value {value!r} is not in its quoted source line")

    def _with_ref(self, field: str, obj: dict) -> dict:
        out = dict(obj)
        out["ref"] = {"record_id": self.rid, "field": field}
        if obj.get("tag") == DERIVED:
            self._check_derived(field, obj)
        return out

    def text(self, field: str, expected: Any = _SKIP) -> Any:
        """A plain (non-numeric) passport value, checked against the record's own value."""
        value = resolve(self.passport, field)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            raise ReplayError(f"{self.record.path}: {field} is a bare number")
        if expected is not _SKIP and value != expected:
            self._fail(field, value, expected)
        return value

    def num(self, field: str, expected: Any = _SKIP) -> dict:
        """A tagged (or absent-with-reason) passport field, with a pointer to it; the value is checked against the record."""
        obj = resolve(self.passport, field)
        if not isinstance(obj, dict) or "value" not in obj or ("tag" not in obj and obj["value"] is not None):
            raise ReplayError(f"{self.record.path}: {field} is not a tagged field")
        if "tag" in obj and obj["tag"] not in TAGS:
            raise ReplayError(f"{self.record.path}: {field} has an unknown tag")
        if expected is not _SKIP and obj["value"] != expected:
            self._fail(field, obj["value"], expected)
        return self._with_ref(field, obj)

    def optional(self, field: str, present: bool, expected: Any) -> Any:
        """A field that is either a plain record value or absent-with-reason."""
        value = resolve(self.passport, field)
        if present:
            if value != expected:
                self._fail(field, value, expected)
            return value
        if not (isinstance(value, dict) and value.get("value") is None and value.get("reason")):
            self._fail(field, value, None)
        return self._with_ref(field, value)

    def tree(self, field: str) -> Any:
        """A passport subtree, copied; every tagged field inside gets its pointer."""
        def walk(obj: Any, path: str) -> Any:
            if is_tagged(obj):
                return self._with_ref(path, {k: walk(v, f"{path}.{k}") if k not in ("value", "tag", "source") else v for k, v in obj.items()})
            if isinstance(obj, dict):
                return {k: walk(v, f"{path}.{k}") for k, v in obj.items()}
            if isinstance(obj, list):
                return [walk(v, f"{path}[{i}]") for i, v in enumerate(obj)]
            if isinstance(obj, (int, float)) and not isinstance(obj, bool):
                raise ReplayError(f"{self.record.path}: bare number at {path}")
            return copy.deepcopy(obj)
        return walk(resolve(self.passport, field), field)


def _own_outcome(decision: str, exit_code: Any) -> str:
    if decision == "PASS":
        return "applied" if exit_code is not None else "gate_passed_not_executed"
    return {"REJECT": "rejected", "DECLINED": "declined"}[decision]


def _execution(e: _Entry, i: int, a: dict) -> dict:
    base = f"attempts[{i}].execution"
    execution = a.get("execution")
    out = {
        "mode": e.optional(f"{base}.mode", bool(execution), execution and execution["mode"]),
        "seconds": e.num(f"{base}.seconds", execution["seconds"] if execution else None),
        "outcome": e.optional(f"{base}.outcome", bool(execution), execution and execution["outcome"]),
        "funded_seconds": e.num(f"{base}.funded_seconds"),
        "wall_seconds": e.num(f"{base}.wall_seconds"),
        "killed_by": e.num(f"{base}.killed_by"),
        "killed_step_seconds": e.num(f"{base}.killed_step_seconds"),
    }
    killed = out["killed_by"]["value"] is not None
    if killed:
        funded, wall = out["funded_seconds"], out["wall_seconds"]
        out["cap_line"] = {"limit_second": funded, "crossed_at_second": wall, "crossed": wall["value"] >= funded["value"]}
    out["killed"] = killed
    return out


def _attempt_step(e: _Entry, i: int, a: dict) -> dict:
    base = f"attempts[{i}]"
    decision, exit_code = a["gate_decision"], a.get("exit_code")
    tm = a.get("time_machine")
    step: dict = {
        "step": "era_lock" if a["origin"] == "time_machine" else "attempt",
        "attempt": e.text(f"{base}.attempt", f"attempt-{int(a['attempt_number'])}"),
        "type": e.text(f"{base}.type", a["origin"]),
    }
    if tm:
        tm_index = next(j for j, action in enumerate(e.passport["time_machine_actions"]) if action["attempt"] == step["attempt"])
        tbase = f"time_machine_actions[{tm_index}]"
        lock, fallback = tm.get("lock") or {}, tm.get("fallback")
        step["era_lock"] = {
            "era_date": e.text(f"{tbase}.era.date", (tm.get("era") or {}).get("date")),
            "python": e.text(f"{tbase}.python.version", (tm.get("python") or {}).get("version")),
            "lock_ok": e.text(f"{tbase}.lock.ok", lock.get("ok")),
            "fallback": e.text(f"{tbase}.fallback.kind", fallback["kind"]) if fallback else None,
        }
    else:
        change = resolve(e.passport, f"{base}.change")
        diff = a.get("diff_text") or ""
        step["proposed"] = {
            "diff_sha256": e.optional(f"{base}.change.diff_sha256", bool(diff), hashlib.sha256(diff.encode("utf-8")).hexdigest()),
            "patch_notes": e.optional(f"{base}.change.patch_notes", "patch_notes" in a, a.get("patch_notes")),
            "env_delta": [{k: e.text(f"{base}.change.env_delta[{j}].{k}", item.get(k)) for k in ("op", "package", "version")}
                          for j, item in enumerate(a.get("env_delta") or [])],
        }
        if len(change["env_delta"]) != len(a.get("env_delta") or []):
            e._fail(f"{base}.change.env_delta", len(change["env_delta"]), len(a.get("env_delta") or []))
    step.update({
        "gate_decision": e.text(f"{base}.gate_decision", decision),
        "outcome": e.text(f"{base}.outcome", _own_outcome(decision, exit_code)),
        "reject_reason": e.optional(f"{base}.reject_reason", decision == "REJECT", list(a.get("gate_violations") or [])),
        "consulted_count": e.num(f"{base}.consulted_count", len(a["consulted"]) if "consulted" in a else None),
        "cited": e.num(f"{base}.cited", None),
        "reason_no_citation": e.optional(f"{base}.reason_no_citation", "reason_no_citation" in a, a.get("reason_no_citation")),
        "silent_exit": e.optional(f"{base}.silent_exit", "silent_exit" in a, a.get("silent_exit")),
        "exit_code": e.num(f"{base}.exit_code", exit_code),
        "execution": _execution(e, i, a),
    })
    if a.get("tavily_sources"):
        raise ReplayError(f"{e.record.path}: attempt {i} has tavily_sources but the passport shows cited as null")
    return step


def _entry(e: _Entry) -> dict:
    record, passport, d = e.record, e.passport, e.record.data
    result, baseline, cg = d["result"], d["certificate"].get("baseline") or {}, d["cost_guard"]
    attempts = result.get("attempts") or []
    if len(passport["attempts"]) != len(attempts):
        e._fail("attempts", len(passport["attempts"]), len(attempts))
    if passport["record_id"] != record.record_id or passport["record"]["sha256"] != record.sha256:
        raise ReplayError(f"{record.path}: the passport is for another blob ({passport['record_id']})")
    timeline: list[dict] = [{
        "step": "baseline",
        "result": e.text("baseline.result", baseline.get("result")),
        "exit_code": e.num("baseline.exit_code", baseline.get("exit_code")),
        "taxonomy_code": e.text("baseline.taxonomy_code", baseline.get("taxonomy_code")),
        "evidence": e.text("baseline.evidence", baseline.get("evidence")),
    }]
    timeline += [_attempt_step(e, i, a) for i, a in enumerate(attempts)]
    timeline.append({
        "step": "verdict",
        "verdict": e.text("verdict.verdict", result["verdict"]),
        "taxonomy_code": e.text("verdict.taxonomy_code", result.get("taxonomy_code")),
        "reason_code": e.text("verdict.reason_code", result.get("reason_code")),
        "indeterminate_reason": e.text("verdict.indeterminate_reason", result.get("indeterminate_reason")),
        "recovery": e.text("verdict.recovery", d["certificate"].get("recovery")),
        "annotations": e.tree("annotations"),
    })
    estimate = cg.get("estimated_sandbox_spent_usd")
    cost = {
        "entry_total": e.num("cost", cg["spent_usd"]),
        "measured": e.num("cost.measured", round(cg["spent_usd"] - estimate, 10) if estimate else cg["spent_usd"]),
        "estimated": e.num("cost.estimated", estimate),
        "model": e.num("cost.model", cg["model_spent_usd"]),
        "per_entry_cap": e.num("cost.per_entry_cap", d["batch"].get("per_entry_cap_usd")),
        "batch_cap": e.num("cost.batch_cap", d["batch"].get("total_cap_usd")),
        "operations": e.tree("cost.operations"),
    }
    for key in ("measured", "estimated", "model", "per_entry_cap", "batch_cap", "operations", "cost_events", "note", "currency", "source_field"):
        cost["entry_total"].pop(key, None)  # the total's own value and tag only; its parts are separate fields
    cap = cost["per_entry_cap"]["value"]
    cost["over_entry_cap"] = bool(cap is not None and cost["entry_total"]["value"] > cap)
    superseded = passport["superseded_by"]
    return {
        "record_id": record.record_id,
        "record_path": record.path,
        "passport_path": passport_path(record),
        "passport_hash": passport["passport_hash"],
        "record_sha256": e.text("record.sha256", record.sha256),
        "results_tables_sha256": _worktree_hash(e),
        "entry": {"id": e.text("entry.id", record.entry), "name": e.text("entry.name", d["corpus_entry"]["name"])},
        "arm": e.text("arm", record.arm),
        "record_set": e.text("record.record_set", record.record_set.name),
        "started_at": e.text("run.started_at", d.get("started_at")),
        "superseded_by": superseded if isinstance(superseded, str) else None,
        "image_id": e.text("image_id.value", baseline.get("sandbox_id")),
        "timeline": timeline,
        "cost": cost,
    }


def _worktree_hash(e: _Entry) -> dict:
    """The D-28 hash results_tables.json lists for the record, re-derived here from the blob (LF written as CRLF)."""
    field = resolve(e.passport, "record.results_tables_sha256")
    out = {k: field[k] for k in ("value", "label", "note", "reason") if k in field}
    out["ref"] = {"record_id": e.rid, "field": "record.results_tables_sha256"}
    if field["value"] is not None:
        own = hashlib.sha256(e.record.blob.replace(bytes([10]), bytes([13, 10]))).hexdigest()
        if field["value"] != own or field.get("equals_sha256_of_blob_with_crlf") is not True:
            e._fail("record.results_tables_sha256", field["value"], own)
    return out


# ---------------------------------------------------------------- one version

def _sum(entries: list[dict], passports: dict[str, dict], field: str, through: int, tag: str) -> dict:
    values = [resolve(passports[x["record_id"]], field)["value"] for x in entries[: through + 1]]
    pointer = {"field": field, "run_order_through": entries[through]["record_id"]}
    if any(v is None for v in values):
        return {"value": None, "reason": resolve(passports[entries[0]["record_id"]], field).get("reason"), "sum_of": pointer}
    return {"value": round(sum(values), 10), "tag": tag, "sum_of": pointer}


def _count(entries: list[dict], field: str, value: str) -> dict:
    ids = [x["record_id"] for x in entries]
    return {"value": sum(1 for x in entries if x["timeline"][-1]["verdict"] == value), "tag": MEASURED,
            "count_of": {"field": field, "equals": value, "records": ids}}


def _check_badge(tag: str, records: list[Record], passports: dict[str, dict], source: BlobSource) -> dict:
    """The D1 badge, identical on every passport of the version, and its figures recomputed from their sources."""
    badges = [passports[r.record_id]["badge"] for r in records]
    badge = badges[0]
    if any(b != badge for b in badges):
        raise ReplayError(f"{tag}: the badge differs between passports")
    figures = {f["criterion"]: f for f in badge["figures"]}

    def same(name: str, shown: Any, expected: Any) -> None:
        if shown != expected:
            raise ReplayError(f"{tag}: badge figure {name} is {shown!r}, its source gives {expected!r}")

    if tag not in GATE_FILES:
        primary = json.loads(source.read(RESULTS_TABLES).decode("utf-8"))["rates"][0]
        same("primary.recovered", figures["primary"]["recovered"]["value"], primary["recovered"])
        same("primary.denominator", figures["primary"]["denominator"]["value"], primary["denominator"])
        same("exploratory", badge["exploratory"], False)
        return badge
    gate = json.loads(source.read(GATE_FILES[tag]["result"]).decode("utf-8"))
    attempts = [a for r in records for a in r.data["result"]["attempts"]]
    same("a.recovered", figures["a"]["recovered"]["value"], sum(1 for v in gate["verdicts"].values() if v in RECOVERED))
    same("a.entries", figures["a"]["entries"]["value"], len(gate["verdicts"]))
    same("b.applied", figures["b"]["applied"]["value"], len(gate["b"].get("applied") or []))
    same("b.proposed", figures["b"]["proposed"]["value"], len(gate["b"].get("proposed") or []))
    same("c.citations", figures["c"]["citations"]["value"], len(gate["c"]["cited"]))
    same("d.cost_cap_endings", figures["d"]["cost_cap_endings"]["value"], len(gate["d"].get("cost_cap_endings") or {}))
    for k in "abcd":
        same(f"{k}.ok", figures[k]["ok"], bool(gate[k]["ok"]))
    same("gate_passed", badge["gate_passed"], bool(gate["passed"]))
    same("exploratory", badge["exploratory"], True)
    a, c = figures["a"], figures["c"]
    if tag == "harness-v1.3.3":
        searches = sum(1 for r in records for ev in r.data["events"] if ev["line"].startswith("[tavily] "))
        same("c.searches", c["searches"]["value"], searches)
        sentence = (f"EXPLORATORY — did not pass its pre-registered gate. a: {a['recovered']['value']}/{a['entries']['value']} (measured), "
                    f"c: {c['citations']['value']} citations in {c['searches']['value']} searches.")
    else:
        same("c.attempts_consulted", c["attempts_consulted"]["value"], sum(1 for x in attempts if "consulted" in x))
        same("c.references_consulted", c["references_consulted"]["value"], sum(len(x["consulted"]) for x in attempts if "consulted" in x))
        same("c.reasons_recorded", c["reasons_recorded"]["value"], sum(1 for x in attempts if "reason_no_citation" in x))
        sentence = (f"EXPLORATORY — did not pass its pre-registered gate. a: {a['recovered']['value']}/{a['entries']['value']}, "
                    f"c: {c['citations']['value']} citations ({c['attempts_consulted']['value']} attempts consulted, "
                    f"{c['references_consulted']['value']} refs, {c['reasons_recorded']['value']} reasons recorded).")
    same("text (the sentence rebuilt from the tagged figures)", badge["text"], sentence)
    spent = round(sum(r.data["cost_guard"]["spent_usd"] for r in records), 10)
    same("gate_cost", badge["gate_cost"]["value"], spent)
    return badge


def build_version(tag: str, records: list[Record], passports: dict[str, dict], records_by_id: dict[str, Record], source: BlobSource) -> dict:
    missing = [r.record_id for r in records if r.record_id not in passports]
    if missing:
        raise ReplayError(f"{tag}: no passport for {missing}")
    _check_badge(tag, records, passports, source)
    entries = [_entry(_Entry(r, passports[r.record_id], records_by_id)) for r in records]
    first = _Entry(records[0], passports[records[0].record_id], records_by_id)
    badge = first.tree("badge")

    run_order = sorted(entries, key=lambda x: (x["started_at"], x["record_id"]))
    position = {x["record_id"]: i for i, x in enumerate(run_order)}
    caps = {x["cost"]["batch_cap"]["value"] for x in entries}
    if len(caps) != 1:
        raise ReplayError(f"{tag}: more than one batch cap in the records: {sorted(caps)}")
    for x in entries:
        i = position[x["record_id"]]
        measured, estimated = _sum(run_order, passports, "cost.measured", i, MEASURED), _sum(run_order, passports, "cost.estimated", i, ESTIMATED)
        total = measured["value"] + (estimated["value"] or 0.0)
        x["cost"]["batch_cumulative"] = {"measured": measured, "estimated": estimated,
                                         "over_batch_cap": bool(total > x["cost"]["batch_cap"]["value"])}

    sets: list[dict] = []
    for name in dict.fromkeys(x["record_set"] for x in entries):
        members = [x for x in entries if x["record_set"] == name]
        verdicts = sorted({x["timeline"][-1]["verdict"] for x in members})
        sets.append({"record_set": name, "arm": members[0]["arm"], "records": [x["record_id"] for x in members],
                     "verdicts": [{"verdict": v, "count": _count(members, "verdict.verdict", v)} for v in verdicts]})
    last = len(run_order) - 1
    return {
        "schema": SCHEMA,
        "harness_tag": tag,
        "role": "EXPLORATORY" if badge["exploratory"] else "PRE-REGISTERED ANCHOR",
        "badge": badge,
        "scorecard": {"criteria": badge["figures"], "gate_passed": badge.get("gate_passed"), "record_sets": sets},
        "batch": {"cap": first.num("cost.batch_cap"), "run_order": [x["record_id"] for x in run_order],
                  "measured": _sum(run_order, passports, "cost.measured", last, MEASURED),
                  "estimated": _sum(run_order, passports, "cost.estimated", last, ESTIMATED)},
        "entries": entries,
    }


def build_replay(source: BlobSource | None = None, passports: dict[str, dict] | None = None, root: Path = ROOT) -> dict[str, dict]:
    """{harness_tag: replay document}, from record blobs and the stored passports."""
    source = source or GitBlobSource()
    passports = passports if passports is not None else load_passports(root)
    records = load_records(source)
    by_id = {r.record_id: r for r in records}
    extra = sorted(set(passports) - set(by_id))
    if extra:
        raise ReplayError(f"passports without a committed record: {extra}")
    return {tag: build_version(tag, [r for r in records if r.harness_tag == tag], passports, by_id, source) for tag in VERSIONS}


# ---------------------------------------------------------------- summary: headline, defect register, ledger

SUMMARY_SCHEMA = "rerun/phase-d/replay-summary/v1"
SEAL_SETS = (
    ("seal-attempt-one-v133", "Seal verification, first attempt", "harness-v1.3.3", "runs/sandbox_verification/attempt1-v1.3.3"),
    ("seal-repeat-v133", "Seal verification, repeat", "harness-v1.3.3", "runs/sandbox_verification/final-v1.3.3"),
    ("seal-v134", "Seal verification", "harness-v1.3.4", "runs/sandbox_verification/final-v1.3.4"),
)
LEDGER_LINE = {"path": GATE_FILES["harness-v1.3.4"]["report"], "quote": "Cumulative on the new ledger: $6.738 + $3.396 = **$10.134** (ceiling ~$11)."}
LOWER_BOUND_LINE = {"path": GATE_FILES["harness-v1.3.4"]["report"], "quote": "$10.134 is a lower bound (D-27)."}
ARTEFACT = "ENTRY-11-SMOKE-LIMIT-ARTEFACT"


def _records(entries: list[dict], where: str) -> dict:
    return {"value": len(entries), "tag": MEASURED, "count_of": {"where": where, "records": [x["record_id"] for x in entries]}}


def _quote_present(root: Path, src: dict) -> None:
    """Quoted report, test and changelog lines are checked against the file in the checkout (records are read from blobs)."""
    file = Path(root) / src["path"]
    if not file.is_file() or src["quote"] not in file.read_bytes().decode("utf-8").replace("\r\n", "\n"):
        raise ReplayError(f"quoted source not found in {src['path']}: {src['quote']!r}")


def _has_model_attempt(x: dict) -> bool:
    return any(s["step"] == "attempt" and s["type"] == "model" for s in x["timeline"])


def _headline(docs: dict[str, dict]) -> dict:
    gate = [x for tag in VERSIONS if docs[tag]["badge"]["exploratory"] for x in docs[tag]["entries"]]
    recovered = [x for x in gate if x["timeline"][-1]["verdict"] in RECOVERED]
    by_loop = [x for x in recovered if any(s["step"] == "attempt" and s["type"] == "model" and s["outcome"] == "applied" for s in x["timeline"])]
    artefacts = [x for x in recovered if any(n["id"] == ARTEFACT for n in x["timeline"][-1]["annotations"])]
    alone = [x for x in recovered if not _has_model_attempt(x)]
    if len(artefacts) != len(recovered) or len(alone) != len(recovered) or by_loop:
        raise ReplayError("headline: the records no longer support the statement (a recovery without the artefact annotation, or one with a model repair)")
    note = next(n for n in artefacts[0]["timeline"][-1]["annotations"] if n["id"] == ARTEFACT) if artefacts else None
    return {
        "gate_entry_runs": _records(gate, "entry-runs of the two exploratory gates"),
        "recovered_by_llm_loop": _records(by_loop, "verdict RUNS_CLEAN or RUNS_AFTER_REPAIR with an applied model repair attempt"),
        "apparent_recoveries": _records(recovered, "verdict RUNS_CLEAN or RUNS_AFTER_REPAIR"),
        "apparent_recoveries_annotated_as_artefact": _records(artefacts, "apparent recovery carrying the smoke-limit artefact annotation"),
        "recoveries_by_time_machine_alone": _records(alone, "apparent recovery with no model repair attempt in the record"),
        "with_recorded_model_attempt": _records([x for x in gate if _has_model_attempt(x)], "at least one model repair attempt in the record"),
        "artefact": [{"record_id": x["record_id"], "harness_tag": x["record_id"].split("/")[0], "entry": x["entry"]["id"], "annotation": note} for x in artefacts],
    }


def _defects(docs: dict[str, dict], root: Path) -> dict:
    entries = [x for tag in VERSIONS for x in docs[tag]["entries"]]
    rows = []
    for row in register.REGISTER:
        for src in [row["registered"]] + row["basis"]:
            _quote_present(root, src)
        if row["status"] not in register.STATUSES:
            raise ReplayError(f"{row['id']}: unknown status {row['status']!r}")
        annotated = [x for x in entries if any(n["id"] == row["id"] for n in x["timeline"][-1]["annotations"])]
        if row["id"] == "D-28":
            annotated = [x for x in entries if x["results_tables_sha256"]["value"] is not None]
        rows.append({**row, "passports": [{"record_id": x["record_id"], "passport_path": x["passport_path"],
                                           "harness_tag": x["record_id"].split("/")[0], "entry": x["entry"]["id"], "arm": x["arm"]} for x in annotated]})
    known = {row["id"] for row in rows}
    unknown = sorted({n["id"] for x in entries for n in x["timeline"][-1]["annotations"] if n["id"].startswith("D-")} - known)
    if unknown or [row["id"] for row in rows] != [f"D-{i}" for i in range(1, len(rows) + 1)]:
        raise ReplayError(f"defect register: not a complete D-1..D-n list, or annotations name unknown defects {unknown}")
    return {"status_rule": dict(register.STATUS_RULE), "rows": rows}


def _ledger(docs: dict[str, dict], source: BlobSource, root: Path) -> dict:
    for line in (LEDGER_LINE, LOWER_BOUND_LINE):
        _quote_present(root, line)
    components, kills = [], []
    for key, name, tag, directory in SEAL_SETS:
        costed: dict[str, list[str]] = {"cost_usd": [], "completed_cost_usd": []}
        total, listed = 0.0, []
        for path in source.list_dir(directory):
            if not path.endswith(".json"):
                continue
            blob = source.read(path)
            data, rid = json.loads(blob.decode("utf-8")), f"{path}@{hashlib.sha256(blob).hexdigest()}"
            field = next((f for f in costed if f in data), None)
            listed.append({"record": rid, "path": path, "cost_field": field})
            if field:
                costed[field].append(rid)
                total += data[field]
            no_killed_step_cost = data.get("path") == "kill_at_operation_limit" and (field is None or data.get("via") == "client_wait_timeout")
            if no_killed_step_cost:
                seconds = data.get("killed_seconds")
                kills.append({
                    "record": rid, "path": path, "component": key, "via": data.get("via"), "error": data.get("error"), "message": data.get("message"),
                    "killed_seconds": {"value": seconds, "tag": MEASURED, "record_field": {"record": rid, "field": "killed_seconds"}}
                    if seconds is not None else {"value": None, "reason": "no killed_seconds field in this record"},
                    "completed_cost": {"value": data[field], "tag": MEASURED, "record_field": {"record": rid, "field": field}}
                    if field else {"value": None, "reason": "no cost field in this record"},
                })
        components.append({
            "key": key, "name": name, "kind": "seal", "harness_tag": tag, "directory": directory, "records": listed,
            "measured": {"value": round(total, 10), "tag": MEASURED,
                         "sum_of_records": [{"field": f, "records": ids} for f, ids in costed.items() if ids]},
            "estimated": {"value": None, "reason": "no estimate field in the seal-verification records"},
        })
    for tag in VERSIONS:
        doc = docs[tag]
        if not doc["badge"]["exploratory"]:
            continue
        ids = [x["record_id"] for x in doc["entries"]]
        components.append({
            "key": "gate-" + tag.replace("harness-", "").replace(".", ""), "name": "Smoke gate", "kind": "gate", "harness_tag": tag,
            "directory": doc["entries"][0]["record_path"].rsplit("/", 1)[0],
            "records": [{"record": x["record_id"], "path": x["record_path"], "cost_field": "cost_guard.spent_usd"} for x in doc["entries"]],
            "measured": {"value": doc["batch"]["measured"]["value"], "tag": MEASURED, "sum_of": {"field": "cost.measured", "records": ids}},
            "estimated": {"value": doc["batch"]["estimated"]["value"], "tag": ESTIMATED, "sum_of": {"field": "cost.estimated", "records": ids}},
        })
    order = ["seal-attempt-one-v133", "seal-repeat-v133", "gate-v133", "seal-v134", "gate-v134"]
    components.sort(key=lambda c: order.index(c["key"]))
    measured = round(sum(c["measured"]["value"] for c in components), 10)
    estimated = round(sum(c["estimated"]["value"] or 0.0 for c in components), 10)
    return {
        "reported_line": LEDGER_LINE, "lower_bound": {"defect": "D-27", "line": LOWER_BOUND_LINE},
        "components": components,
        "measured": {"value": measured, "tag": MEASURED, "sum_of_components": "measured"},
        "estimated": {"value": estimated, "tag": ESTIMATED, "sum_of_components": "estimated"},
        "total": {"value": round(measured + estimated, 10), "tag": ESTIMATED, "sum_of_components": "measured + estimated",
                  "note": "contains an ESTIMATED component: shown as measured + estimated, never as one MEASURED figure"},
        "kill_records": kills,
    }


ROLES = (
    ("recon", "finds the entrypoint to run and abstains (INDETERMINATE) when it cannot"),
    ("planner", "adds system packages to an otherwise deterministic build plan"),
    ("repairer", "proposes a minimal patch or environment change; the tamper gate and the env gate decide, never the model"),
    ("adjudicator", "writes the certificate prose; it may only downgrade a verdict, never upgrade one"),
)


def _stack(records: list[Record]) -> dict:
    """Which models, sandbox backend and search were recorded, per harness version, read from the run records."""
    versions = []
    for tag in VERSIONS:
        recs = [r for r in records if r.harness_tag == tag]
        ids = [r.record_id for r in recs]

        def same(field: str):
            values = {json.dumps(resolve(r.data, field), sort_keys=True) for r in recs}
            if len(values) != 1:
                raise ReplayError(f"{tag}: {field} differs between records")
            return json.loads(values.pop())

        def total(field: str, value) -> dict:
            return {"value": value, "tag": MEASURED, "sum_of_records": [{"field": field, "records": ids}]}

        models = same("config.models")
        prices = same("cost_guard.prices_usd_per_1m")
        calls = []
        for model in dict.fromkeys(models[role] for role, _ in ROLES):
            mine = [c for r in recs for c in r.data["model_calls"] if c["model"] == model]
            calls.append({
                "model": model,
                "roles": [role for role, _ in ROLES if models[role] == model],
                "calls": total(f"count of model_calls where model is {model}", len(mine)),
                "prompt_tokens": total(f"model_calls[].usage.prompt_tokens where model is {model}", sum(c["usage"]["prompt_tokens"] for c in mine)),
                "completion_tokens": total(f"model_calls[].usage.completion_tokens where model is {model}", sum(c["usage"]["completion_tokens"] for c in mine)),
                "price_per_million_input_tokens": {"value": prices[model][0], "tag": MEASURED, "record_field": {"record": ids[0], "field": f"cost_guard.prices_usd_per_1m[{model}][0]"}},
                "price_per_million_output_tokens": {"value": prices[model][1], "tag": MEASURED, "record_field": {"record": ids[0], "field": f"cost_guard.prices_usd_per_1m[{model}][1]"}},
            })
        searching = [r for r in recs if r.data["config"].get("tavily_configured")]
        versions.append({
            "harness_tag": tag,
            "records": ids,
            "roles": [{"role": role, "model": models[role], "does": does} for role, does in ROLES],
            "model_calls": calls,
            "sandbox": {"backend": same("config.sandbox_backend"), "default_image": same("config.sandbox_image_default"),
                        "prices_source": same("cost_guard.prices_source"), "prices_retrieved": same("cost_guard.prices_retrieved")},
            "search": {"provider": "Tavily", "records_with_search_configured": {"value": len(searching), "tag": MEASURED,
                       "count_of": {"where": "config.tavily_configured is true", "records": [r.record_id for r in searching]}}},
        })
    return {"versions": versions, "note": "prompt-engineered: the records name hosted model endpoints; no fine-tuned model appears in any record"}


def _inventory(docs: dict[str, dict], summary_defects: dict) -> dict:
    entries = [x for tag in VERSIONS for x in docs[tag]["entries"]]
    return {
        "records": {"value": len(entries), "tag": MEASURED, "count_of": {"where": "committed run records with a passport", "records": [x["record_id"] for x in entries]}},
        "defects": {"value": len(summary_defects["rows"]), "tag": MEASURED,
                    "count_of": {"where": "rows of the defect register", "records": [row["id"] for row in summary_defects["rows"]]}},
        "defects_by_status": {
            status: {"value": sum(1 for row in summary_defects["rows"] if row["status"] == status), "tag": MEASURED,
                     "count_of": {"where": f"rows of the defect register with status {status}",
                                  "records": [row["id"] for row in summary_defects["rows"] if row["status"] == status]}}
            for status in register.STATUSES},
    }


def build_summary(docs: dict[str, dict], source: BlobSource, root: Path = ROOT) -> dict:
    registered = _defects(docs, root)
    return {"schema": SUMMARY_SCHEMA, "headline": _headline(docs), "inventory": _inventory(docs, registered),
            "stack": _stack(load_records(source)), "defects": registered, "ledger": _ledger(docs, source, root)}


# ---------------------------------------------------------------- output files

def to_json(doc: dict) -> bytes:
    return (json.dumps(doc, indent=1, ensure_ascii=False) + "\n").encode("utf-8")


def code(text: Any) -> str:
    """A verbatim string as a Markdown code span (whatever backticks it contains)."""
    text = "null" if text is None else text if isinstance(text, str) else json.dumps(text, ensure_ascii=False)
    text = text.replace("\r", " ").replace("\n", " ")
    fence = "`" * (max((len(m) for m in re.findall(r"`+", text)), default=0) + 1)
    pad = " " if text.startswith("`") or text.endswith("`") or not text.strip() else ""
    return f"{fence}{pad}{text}{pad}{fence}"


def show(obj: Any) -> str:
    """A tagged value with its tag; an absent field with its reason; any other value as a quoted string."""
    if is_tagged(obj):
        value = json.dumps(obj["value"]) if not isinstance(obj["value"], str) else code(obj["value"])
        return f"{value} [{obj['tag']}]"
    if isinstance(obj, dict) and "value" in obj and obj["value"] is None:
        return f"null ({code(obj.get('reason'))})"
    if isinstance(obj, list):
        return ", ".join(code(x) for x in obj) if obj else "none"
    return code(obj)


def _sources(*objs: Any) -> list[str]:
    lines: list[str] = []
    for obj in objs:
        if is_tagged(obj) and obj["tag"] == DERIVED:
            for src in obj["source"] if isinstance(obj["source"], list) else [obj["source"]]:
                line = f"source {code(src['line'])} ({code(src['field'])} of record {code(src['record_id'])})"
                if line not in lines:
                    lines.append(line)
    return lines


def _criterion_md(f: dict) -> str:
    parts = [f"criterion {code(f['criterion'])}"]
    if "ok" in f:
        parts.append(f"passed {code(f['ok'])}")
    for key in ("recovered", "entries", "denominator", "applied", "proposed", "citations", "searches", "attempts_consulted",
                "references_consulted", "reasons_recorded", "cost_cap_endings"):
        if key in f:
            parts.append(f"{key.replace('_', ' ')} {show(f[key])}")
    if "detail" in f:
        parts.append(f"gate line {code(f['detail'])}")
    if "label" in f:
        parts.append(f"line {code(f['label'])} ({code(f['note'])})")
    line = "- " + " · ".join(parts)
    for src in _sources(*[v for v in f.values() if is_tagged(v)]):
        line += f"\n  - {src}"
    if "annotation" in f:
        line += f"\n  - annotation beside this figure: {code(f['annotation'])}"
    return line


def _step_md(step: dict) -> list[str]:
    if step["step"] == "baseline":
        return [f"- baseline: {code(step['result'])} · exit code {show(step['exit_code'])} · {code(step['taxonomy_code'])} · evidence {code(step['evidence'])}"]
    if step["step"] == "verdict":
        lines = [f"- verdict: {code(step['verdict'])} · taxonomy {code(step['taxonomy_code'])} · reason {code(step['reason_code'])} · recovery {code(step['recovery'])}"]
        if step["indeterminate_reason"]:
            lines.append(f"  - {code(step['indeterminate_reason'])}")
        for note in step["annotations"]:
            quoted = "; ".join(f"{code(s['path'])}: {code(s['quote'])}" for s in note["sources"])
            lines.append(f"  - annotation {code(note['id'])}: {code(note['text'])} (source {quoted})")
        return lines
    head = f"- {'era lock' if step['step'] == 'era_lock' else 'attempt'} {code(step['attempt'])} ({code(step['type'])}): "
    if "era_lock" in step:
        lock = step["era_lock"]
        head += f"era {code(lock['era_date'])} · Python {code(lock['python'])} · lock ok {code(lock['lock_ok'])} · fallback {code(lock['fallback'])} · "
    else:
        proposed = step["proposed"]
        delta = ", ".join(code(" ".join(str(x[k]) for k in ("op", "package", "version") if x[k])) for x in proposed["env_delta"]) or "none"
        head += f"proposed diff {show(proposed['diff_sha256'])} · env delta {delta} · "
    head += (f"gate {code(step['gate_decision'])} → {code(step['outcome'])} · reject reason {show(step['reject_reason'])} · "
             f"consulted {show(step['consulted_count'])} · cited {show(step['cited'])} · reason_no_citation {show(step['reason_no_citation'])} · "
             f"silent_exit {show(step['silent_exit'])} · exit code {show(step['exit_code'])}")
    ex = step["execution"]
    lines = [head, f"  - execution: mode {show(ex['mode'])} · seconds {show(ex['seconds'])} · outcome {show(ex['outcome'])}"]
    if ex["killed"]:
        lines.append(f"  - KILL: funded seconds {show(ex['funded_seconds'])} · wall seconds {show(ex['wall_seconds'])} · killed by {show(ex['killed_by'])} · "
                     f"killed step seconds {show(ex['killed_step_seconds'])} · cap line at second {show(ex['cap_line']['limit_second'])} crossed at second "
                     f"{show(ex['cap_line']['crossed_at_second'])}: {code(ex['cap_line']['crossed'])}")
        lines += [f"    - {s}" for s in _sources(ex["funded_seconds"], ex["wall_seconds"], ex["killed_by"], ex["killed_step_seconds"])]
    return lines


def _entry_md(x: dict) -> list[str]:
    lines = [f"### {code(x['entry']['id'])} {code(x['entry']['name'])} — {code(x['arm'])} ({code(x['record_set'])})", "",
             f"- record {code(x['record_id'])}", f"- passport {code(x['passport_path'])} · hash {code(x['passport_hash'])} · image id {code(x['image_id'])}"]
    if x["superseded_by"]:
        lines.append(f"- SUPERSEDED by {code(x['superseded_by'])}")
    for step in x["timeline"]:
        lines += _step_md(step)
    c = x["cost"]
    lines.append(f"- cost (USD): total {show(c['entry_total'])} = measured {show(c['measured'])} + estimated {show(c['estimated'])} · model {show(c['model'])} · "
                 f"entry cap {show(c['per_entry_cap'])} · over the entry cap {code(c['over_entry_cap'])}")
    for op in c["operations"]:
        line = f"  - {code(op['operation'])}: spend {show(op['spend'])} · remaining {show(op['remaining'])}"
        if op["killed"]:
            line += f" · STOPPED at second {show(op['stopped_at_second'])} · measured part {show(op['measured_part'])}"
        lines.append(line)
        lines += [f"    - {s}" for s in _sources(op["spend"])]
    cum = c["batch_cumulative"]
    lines.append(f"  - batch so far: measured {show(cum['measured'])} + estimated {show(cum['estimated'])} of cap {show(c['batch_cap'])} · "
                 f"over the batch cap {code(cum['over_batch_cap'])}")
    return lines + [""]


def to_markdown(doc: dict) -> bytes:
    badge = doc["badge"]
    lines = [f"# REPLAY {code(doc['harness_tag'])} — {doc['role']}", "",
             "Offline replay from committed records. Every number below is a tagged passport field (MEASURED, ESTIMATED or DERIVED);",
             "text in code spans is quoted verbatim from a record or a passport. Generated by `python -m phase_d.build_replay`.", "",
             "## Badge", "", f"> {code(badge['text'])}", ""]
    if badge["exploratory"]:
        links = badge["links"]
        lines += [f"- gate result {code(links['gate_result'])} · gate report {code(links['gate_report'])}",
                  f"- cost line {code(links['cost_line']['quote'])} in {code(links['cost_line']['path'])}",
                  "- run records: " + ", ".join(code(r) for r in links["run_records"]),
                  f"- gate passed {code(badge['gate_passed'])}"]
        cost = badge["gate_cost"]
        cost_line = f"- gate cost (USD): {show(cost)}"
        if "measured" in cost:
            cost_line += f" = measured {show(cost['measured'])} + estimated {show(cost['estimated'])}"
        lines.append(cost_line)
    else:
        lines.append("- not exploratory: this is the pre-registered run the exploratory versions sit beside")
    lines += ["", "## Scorecard", ""] + [_criterion_md(f) for f in doc["scorecard"]["criteria"]] + [""]
    for rs in doc["scorecard"]["record_sets"]:
        counts = " · ".join(f"{code(v['verdict'])} {show(v['count'])}" for v in rs["verdicts"])
        lines.append(f"- {code(rs['arm'])} ({code(rs['record_set'])}): {counts}")
    batch = doc["batch"]
    lines += ["", "## Cost against the batch cap", "",
              f"- measured {show(batch['measured'])} + estimated {show(batch['estimated'])} of cap {show(batch['cap'])} (USD)", "", "## Entries", ""]
    for x in doc["entries"]:
        lines += _entry_md(x)
    return ("\n".join(lines).rstrip("\n") + "\n").encode("utf-8")


def index_markdown(docs: dict[str, dict], files: dict[str, bytes]) -> bytes:
    lines = ["# REPLAY index", "",
             "Offline, deterministic replay of the committed records, cross-checked against the passports. The pre-registered run is the anchor;",
             "the exploratory versions sit beside it with their badges. Rebuild with `python -m phase_d.build_replay`; check with",
             "`python -m phase_d.build_replay --check`.", ""]
    for tag, doc in docs.items():
        lines += [f"## {code(tag)} — {doc['role']}", "", f"> {code(doc['badge']['text'])}", ""]
        for ext in ("md", "json"):
            rel = f"{REPLAY_DIR}/{tag}.{ext}"
            lines.append(f"- [{tag}.{ext}]({tag}.{ext}) · sha256 {code(hashlib.sha256(files[rel]).hexdigest())}")
        lines.append("")
    lines += ["## Summary", "", "Headline counts, the defect register and the cost ledger, each number with its tag and its records.", "",
              f"- [summary.json](summary.json) · sha256 {code(hashlib.sha256(files[f'{REPLAY_DIR}/summary.json']).hexdigest())}", ""]
    return ("\n".join(lines).rstrip("\n") + "\n").encode("utf-8")


def expected_files(source: BlobSource | None = None, passports: dict[str, dict] | None = None, root: Path = ROOT) -> dict[str, bytes]:
    source = source or GitBlobSource()
    docs = build_replay(source, passports, root)
    files: dict[str, bytes] = {f"{REPLAY_DIR}/summary.json": to_json(build_summary(docs, source, root))}
    for tag, doc in docs.items():
        files[f"{REPLAY_DIR}/{tag}.json"] = to_json(doc)
        files[f"{REPLAY_DIR}/{tag}.md"] = to_markdown(doc)
    files[f"{REPLAY_DIR}/index.md"] = index_markdown(docs, files)
    return files
