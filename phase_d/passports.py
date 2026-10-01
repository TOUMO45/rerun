"""Phase D passports: one per committed run record (49), rebuilt deterministically from git blobs.

Rules the builder enforces (Phase D directive, decisions of 2026-10-01):
  * a record value is copied, never recomputed or rounded; a correction is an annotation beside it;
  * every JSON number is `{"value": n, "tag": API-REPORTED | ESTIMATED | DERIVED}`:
      API-REPORTED  the value is a stored field of a committed record (or a count / sum / difference of such fields,
                    then with `computed_from`). A dollar figure with this tag is the sandbox API's reported
                    operation cost, NOT account billing (D-36, open). This tag was named MEASURED until D-36;
                    the meaning is unchanged, only the word,
      ESTIMATED     the cost guard itself flagged the amount as an estimate (a killed sandbox step),
      DERIVED       the value was parsed from event text or a `cost_events[].note`; the source line is quoted
                    verbatim with its record id;
  * a fourth tag, BILLED, exists but never appears on a passport: it is used only on the owner's account-balance
    readings in the REPLAY summary (`ledger.billed`), never on an API cost;
  * a field the harness version did not store is `{"value": null, "reason": "not recorded by harness-vX.Y.Z"}`;
  * identifiers and ordinals (entry, attempt, reference) are strings, not numbers.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from .records import BlobSource, GitBlobSource, Record, load_records

# v2 (phase-d2): + attempts[].consulted_count, cost.batch_cap, cost.operations, badge criteria b/d, v1.3.2 anchor
# v3 (phase-d3): + record.results_tables_sha256 (D-28: the CRLF worktree hash results_tables.json lists for the record);
#                 annotations[].status dropped (a defect's status is in the register, not on each passport)
# v4 (D-36):      tag MEASURED renamed API-REPORTED (same meaning; a dollar figure is the sandbox API's reported operation
#                 cost, not account billing); no value changed
SCHEMA = "rerun/phase-d/passport/v4"
API_REPORTED, ESTIMATED, DERIVED, BILLED = "API-REPORTED", "ESTIMATED", "DERIVED", "BILLED"
RECORD_TAGS = (API_REPORTED, ESTIMATED, DERIVED)  # the tags a passport or a REPLAY version file may carry
TAGS = (API_REPORTED, ESTIMATED, DERIVED, BILLED)  # BILLED: the owner's account-balance readings only (REPLAY summary, ledger.billed)
PASSPORT_DIR = "reports/phase-d/passports"

GATE_DIR = "reports/corpus-v2.1/v1.3.3/smoke_gate"
DEFECTS = "reports/corpus-v2.1/candidate_v1.3.3_defects.md"
GATE_FILES = {
    "harness-v1.3.3": {"result": f"{GATE_DIR}/smoke_gate_result.json", "report": f"{GATE_DIR}/SMOKE_GATE_REPORT.md",
                       "cost_line": "Spend: **$2.9298** (gate)."},
    "harness-v1.3.4": {"result": f"{GATE_DIR}/smoke_gate_result_harness-v1.3.4.json", "report": f"{GATE_DIR}/SMOKE_GATE_REPORT_v1.3.4.md",
                       "cost_line": "Gate spend **$3.3962** (cap $3.50)."},
}
RESULTS_TABLES = "reports/corpus-v2.1/results_tables.json"
RECOVERED = ("RUNS_CLEAN", "RUNS_AFTER_REPAIR")
CITED_NOTE = "tavily_sources empty on all attempts — consistent with D-21 open"
ARTEFACT_NOTE = "the one recovery (entry 11) was later identified as a smoke-limit artefact; measured line unchanged."


class BuildError(Exception):
    pass


def api_reported(value: Any, **extra: Any) -> dict:
    return {"value": value, "tag": API_REPORTED, **extra}


def absent(reason: str) -> dict:
    return {"value": None, "reason": reason}


def tag_numbers(obj: Any) -> Any:
    """Copy a record subtree; every bare number becomes an API-REPORTED value (it is a stored field)."""
    if isinstance(obj, bool) or obj is None or isinstance(obj, str):
        return obj
    if isinstance(obj, (int, float)):
        return api_reported(obj)
    if isinstance(obj, list):
        return [tag_numbers(x) for x in obj]
    return {k: tag_numbers(v) for k, v in obj.items()}


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _attempt_label(number: Any) -> str:
    return f"attempt-{int(number)}"


# ---------------------------------------------------------------- annotations (editorial, each with a quoted source)

def _src(path: str, quote: str) -> dict:
    return {"path": path, "quote": quote}


def _defect(defect: str, text: str, quote: str, path: str = DEFECTS) -> dict:
    return {"id": defect, "text": text, "sources": [_src(path, quote)]}  # the defect's status lives in the register (phase_d/defects.py)


ANNOTATIONS: dict[tuple[str, str, str], list[dict]] = {
    ("harness-v1.3.2", "control/infra_retries", "07"): [{
        "id": "SUPERSEDED-INFRA-RETRY",
        "text": "First attempt of CONTROL entry 7 (INFRA_ERROR). Kept as evidence; superseded by the registered retry (see superseded_by).",
        "sources": [_src("METHODOLOGY.md", "attempt 1 (INFRA_ERROR, $0.003) is kept in `control/infra_retries/`")],
    }],
    ("harness-v1.3.2", "treatment", "13"): [_defect("D-7", "The per-entry ceiling was not hard in harness-v1.3.2; this entry's recorded spend exceeds its cap.",
                                                     "**D-7 Per-entry $2 ceiling is not hard.**")],
    ("harness-v1.3.2", "treatment", "16"): [_defect("D-7", "The per-entry ceiling was not hard in harness-v1.3.2; this entry's recorded spend exceeds its cap.",
                                                     "**D-7 Per-entry $2 ceiling is not hard.**")],
    ("harness-v1.3.2", "treatment", "15"): [_defect("D-8", "A re-execution hit the wall clock (PIPELINE_ERROR); its spend may be missing from the recorded cost.",
                                                     "**D-8 A timed-out sandbox operation may be unrecorded spend.**")],
    ("harness-v1.3.3", "smoke", "03"): [_defect("D-19", "Silent exit after a progress stream: the repairer had no error text.",
                                                 "**D-19** A silent exit 1 after a progress stream leaves the repairer no error text (entry 3")],
    ("harness-v1.3.3", "smoke", "07"): [_defect("D-18", "The repairer was shown RERUN's lock as requirements.txt; edits to it were refused.",
                                                 "**D-18** The repairer prompt shows RERUN's resolved lock as `requirements.txt`; edits to it are refused (entry 7")],
    ("harness-v1.3.3", "smoke", "08"): [
        _defect("D-20", "INVALID_HARNESS: the download route could not carry the patched file.",
                "**D-20** The download route (repositories over 125.8 MB: entries 2, 8, 10, 11) cannot carry a patched file"),
        _defect("D-22", "The model repair attempt that ended INVALID_HARNESS is not in this record's attempts[].",
                "**D-22** An attempt that ends in INVALID_HARNESS is not recorded (entry 8, repair 1)."),
    ],
    ("harness-v1.3.3", "smoke", "11"): [{
        "id": "ENTRY-11-SMOKE-LIMIT-ARTEFACT",
        "text": "RUNS_AFTER_REPAIR is this record's measured verdict and is unchanged. The harness-v1.3.4 gate ran the same era "
                "environment past the smoke limit and reached a REPO torch.load defect: this recovery was a smoke-limit artefact, "
                "produced by the deterministic time machine alone (no model repair attempt in this record).",
        "sources": [_src(GATE_FILES["harness-v1.3.4"]["report"], "**v1.3.3's \"recovery\" was a smoke-limit artefact.**"),
                    _src(DEFECTS, "**v1.3.3 entry 11** was a smoke-limit artefact, not a recovery")],
        "related_record": ("harness-v1.3.4", "smoke", "11"),
    }],
    ("harness-v1.3.4", "smoke", "03"): [
        _defect("D-25", "Model-placed diagnostics did not locate the deliberate silent exit.",
                "**D-25** One round of model-placed diagnostics does not locate a deliberate silent `exit 1` (entry 3)"),
        _defect("D-26", "attempt-1 was DECLINED with references consulted, and the record stores no reason_no_citation for it.",
                "**D-26** `reason_no_citation` is not recorded on a DECLINED attempt"),
    ],
    ("harness-v1.3.4", "smoke", "07"): [_defect("D-24", "A missing compiler found after a repair went to the model instead of the deterministic rule.",
                                                 "**D-24** The deterministic \"missing gcc -> build-essential\" rule fires only on the baseline classification")],
    ("harness-v1.3.4", "smoke", "08"): [
        _defect("D-23", "COST_CAP during the torch install, before the repository ran.",
                "**D-23** The per-repair funding rule starves entries whose re-executions each pay a ~90 s torch install"),
        {"id": "COST-CONTAINS-ESTIMATE",
         "text": "The recorded spend contains the cost guard's estimate for the killed step; show it as API-reported + estimated (see cost), never as one API-REPORTED figure.",
         "sources": [_src(GATE_FILES["harness-v1.3.4"]["result"], "\"kind\": \"estimated\"")]},
    ],
    ("harness-v1.3.4", "smoke", "11"): [
        _defect("D-23", "COST_CAP during a re-execution's torch install.",
                "**D-23** The per-repair funding rule starves entries whose re-executions each pay a ~90 s torch install"),
        {"id": "ENTRY-11-SMOKE-LIMIT-ARTEFACT",
         "text": "This run went past the point harness-v1.3.3 recorded as a recovery and reached a REPO torch.load defect.",
         "sources": [_src(GATE_FILES["harness-v1.3.4"]["report"], "**v1.3.3's \"recovery\" was a smoke-limit artefact.**")],
         "related_record": ("harness-v1.3.3", "smoke", "11")},
    ],
}
for _arm in ("control", "treatment"):
    for _entry in ("05", "09"):
        ANNOTATIONS[("harness-v1.3.2", _arm, _entry)] = [_defect(
            "D-13", "RUNNER_SETUP_FAILED before the repository's first command; the time machine was never entered.",
            "**D-13 Runner-setup failures never reach the time machine.** Entries 5 and 9 (both arms)")]


# ---------------------------------------------------------------- attempts

_STOPPED = re.compile(r"^\[(time-machine|repair (\d+))\] stopped: .*budget-derived limit of (\d+)s")
_GUARD_STOP = re.compile(r"^\[cost_guard\] operation stopped at (\d+)s;")
_KILLED_AFTER = re.compile(r"^killed after (\d+)s: ")


def _derived(value: Any, record: Record, field: str, line: str) -> dict:
    return {"value": value, "tag": DERIVED, "source": {"record_id": record.record_id, "field": field, "line": line}}


def _kills(record: Record) -> dict[int, dict]:
    """Cost-guard kills, keyed by attempt number, parsed from event text (DERIVED)."""
    events = record.data.get("events") or []
    cost_events = (record.data.get("cost_guard") or {}).get("cost_events") or []
    kills: dict[int, dict] = {}
    for i, event in enumerate(events):
        m = _STOPPED.match(event["line"])
        if not m:
            continue
        number = int(m.group(2)) if m.group(2) else 0
        guard = next(((j, _GUARD_STOP.match(events[j]["line"])) for j in range(i - 1, -1, -1) if _GUARD_STOP.match(events[j]["line"])), None)
        if guard is None:
            raise BuildError(f"{record.path}: a stop event without a cost_guard line: {event['line']!r}")
        j, g = guard
        kills[number] = {
            "funded_seconds": _derived(int(m.group(3)), record, f"events[{i}].line", event["line"]),
            "wall_seconds": _derived(int(g.group(1)), record, f"events[{j}].line", events[j]["line"]),
            "killed_by": _derived("cost_guard", record, f"events[{j}].line", events[j]["line"]),
        }
    if len(kills) == 1 and len(cost_events) == 1:
        m = _KILLED_AFTER.match(cost_events[0].get("note") or "")
        if m:
            next(iter(kills.values()))["killed_step_seconds"] = _derived(
                int(m.group(1)), record, "cost_guard.cost_events[0].note", cost_events[0]["note"])
    return kills


def _outcome(decision: str, exit_code: Any, path: str) -> str:
    if decision == "REJECT":
        return "rejected"
    if decision == "DECLINED":
        return "declined"
    if decision == "PASS":
        # the smoke gate's own rule: a change that reached a re-execution was applied
        return "applied" if exit_code is not None else "gate_passed_not_executed"
    raise BuildError(f"{path}: unknown gate_decision {decision!r}")


def _attempt(record: Record, index: int, a: dict, kills: dict[int, dict]) -> dict:
    tag = record.harness_tag
    not_recorded = f"not recorded by {tag}"
    has_d21_fields = tag == "harness-v1.3.4"
    not_on_attempt = "not present on this attempt in the record" if has_d21_fields else not_recorded
    if a.get("tavily_sources"):
        raise BuildError(f"{record.path}: attempt {a['attempt_number']} has tavily_sources; the cited[] rule assumes none")
    field = f"result.attempts[{index}]"
    decision, exit_code = a["gate_decision"], a.get("exit_code")
    execution = a.get("execution")
    no_exec = "no execution recorded for this attempt" if tag != "harness-v1.3.2" else not_recorded
    kill = kills.get(int(a["attempt_number"]))
    no_kill = f"no kill recorded for this attempt; the funded limit is not a stored field in {tag}"
    diff = a.get("diff_text") or ""
    return {
        "attempt": _attempt_label(a["attempt_number"]),
        "type": a["origin"],
        "gate_decision": decision,
        "outcome": _outcome(decision, exit_code, record.path),
        "reject_reason": list(a.get("gate_violations") or []) if decision == "REJECT" else absent(f"not applicable: gate decision {decision}"),
        "consulted": [{"ref": f"[{c['number']}]", "title": c["title"], "url": c["url"], "content_sha256": _sha(c.get("content") or "")}
                      for c in a["consulted"]] if "consulted" in a else absent(not_on_attempt),
        "consulted_count": api_reported(len(a["consulted"]), computed_from=f"length of {field}.consulted") if "consulted" in a else absent(not_on_attempt),
        "cited": absent(CITED_NOTE),
        "reason_no_citation": a["reason_no_citation"] if "reason_no_citation" in a else absent(not_on_attempt),
        "silent_exit": a["silent_exit"] if "silent_exit" in a else absent(not_on_attempt),
        "exit_code": api_reported(exit_code, source_field=f"{field}.exit_code") if exit_code is not None else absent("no re-execution recorded for this attempt"),
        "change": {
            "diff_sha256": _sha(diff) if diff else absent("no diff on this attempt"),
            "patch_notes": list(a["patch_notes"]) if "patch_notes" in a else absent(not_on_attempt if tag != "harness-v1.3.2" else not_recorded),
            "env_delta": tag_numbers(a.get("env_delta") or []),
        },
        "execution": {
            "mode": execution["mode"] if execution else absent(no_exec),
            "seconds": api_reported(execution["seconds"], source_field=f"{field}.execution.seconds") if execution else absent(no_exec),
            "outcome": execution["outcome"] if execution else absent(no_exec),
            "funded_seconds": kill["funded_seconds"] if kill else absent(no_kill),
            "wall_seconds": kill["wall_seconds"] if kill else absent(no_kill),
            "killed_by": kill["killed_by"] if kill else absent(no_kill),
            "killed_step_seconds": kill["killed_step_seconds"] if kill and "killed_step_seconds" in kill else absent(no_kill),
        },
    }


def _time_machine_action(a: dict) -> dict:
    tm = a["time_machine"]
    lock = tm.get("lock") or {}
    return tag_numbers({
        "attempt": _attempt_label(a["attempt_number"]),
        "outcome": _outcome(a["gate_decision"], a.get("exit_code"), "time_machine"),
        "era": tm.get("era"),
        "python": tm.get("python"),
        "undeclared_imports": tm.get("undeclared_imports"),
        "apt_added": tm.get("apt_added"),
        "apt_reason": tm.get("apt_reason"),
        "lock": {k: lock.get(k) for k in ("ok", "lock", "relaxed", "not_on_index", "error")},
        "fallback": tm.get("fallback"),
    })


# ---------------------------------------------------------------- cost

_OP_RECORDED = re.compile(r"^\[cost_guard\] recorded \$(\d+\.\d+) sandbox spend, \$(\d+\.\d+) remaining today$")
_OP_STOPPED = re.compile(r"^\[cost_guard\] operation stopped at (\d+)s; recorded \$(\d+\.\d+) \((\d+\.\d+) measured \+ estimate for the killed step\), \$(\d+\.\d+) left$")


def _operations(record: Record) -> list[dict]:
    """The cost guard's own log of each sandbox operation, in event order (DERIVED: parsed from the event line)."""
    ops: list[dict] = []
    for i, event in enumerate(record.data.get("events") or []):
        line = event["line"]
        if not line.startswith("[cost_guard]"):
            continue
        field = f"events[{i}].line"
        done, stopped = _OP_RECORDED.match(line), _OP_STOPPED.match(line)
        if done:
            op = {"killed": False, "spend": _derived(float(done.group(1)), record, field, line),
                  "remaining": _derived(float(done.group(2)), record, field, line)}
        elif stopped:
            op = {"killed": True, "stopped_at_second": _derived(int(stopped.group(1)), record, field, line),
                  "spend": _derived(float(stopped.group(2)), record, field, line),
                  "measured_part": _derived(float(stopped.group(3)), record, field, line),
                  "remaining": _derived(float(stopped.group(4)), record, field, line)}
        else:
            raise BuildError(f"{record.path}: unrecognised cost_guard line: {line!r}")
        ops.append({"operation": f"operation-{len(ops) + 1}", **op})
    return ops

def _cost(record: Record) -> dict:
    tag = record.harness_tag
    cg = record.data["cost_guard"]
    spent, estimate = cg["spent_usd"], cg.get("estimated_sandbox_spent_usd")
    has_estimate = bool(estimate)
    cap = record.data["batch"].get("per_entry_cap_usd")
    events = cg.get("cost_events")
    cost = {
        "value": spent,
        "tag": ESTIMATED if has_estimate else API_REPORTED,
        "currency": "USD",
        "source_field": "cost_guard.spent_usd",
    }
    if has_estimate:
        cost["note"] = "contains an ESTIMATED component: show as API-reported + estimated, never as one API-REPORTED figure"
    cost["measured"] = api_reported(round(spent - estimate, 10), computed_from="cost_guard.spent_usd - cost_guard.estimated_sandbox_spent_usd") \
        if has_estimate else api_reported(spent, source_field="cost_guard.spent_usd")
    cost["estimated"] = {"value": estimate, "tag": ESTIMATED, "source_field": "cost_guard.estimated_sandbox_spent_usd"} \
        if estimate is not None else absent(f"not recorded by {tag}")
    cost["model"] = api_reported(cg["model_spent_usd"], source_field="cost_guard.model_spent_usd")
    cost["per_entry_cap"] = api_reported(cap, source_field="batch.per_entry_cap_usd") if cap is not None else absent(f"not recorded by {tag}")
    batch_cap = record.data["batch"].get("total_cap_usd")
    cost["batch_cap"] = api_reported(batch_cap, source_field="batch.total_cap_usd") if batch_cap is not None else absent(f"not recorded by {tag}")
    cost["operations"] = _operations(record)
    cost["cost_events"] = [
        {"kind": e["kind"], "usd": {"value": e["usd"], "tag": ESTIMATED if e["kind"] == "estimated" else API_REPORTED}, "note": e.get("note")}
        for e in events] if events is not None else absent(f"not recorded by {tag}")
    return cost


# ---------------------------------------------------------------- badges (per version, from that version's own measured line)

def _gate_stats(records: list[Record], source: BlobSource) -> dict[str, dict]:
    stats: dict[str, dict] = {}
    tables_blob = source.read(RESULTS_TABLES)
    primary = json.loads(tables_blob.decode("utf-8"))["rates"][0]
    if not primary["label"].startswith("PRIMARY"):
        raise BuildError(f"{RESULTS_TABLES}: rates[0] is not the PRIMARY line")
    listed: dict[tuple[str, str], dict] = {}
    for i, row in enumerate(json.loads(tables_blob.decode("utf-8"))["corpus"]):
        for arm in ("control", "treatment"):
            listed[(arm, f"{int(row['id']):02d}")] = {"value": row[f"record_{arm}_sha256"], "source_field": f"corpus[{i}].record_{arm}_sha256"}
    stats["results_tables"] = {"listed": listed, "source": f"{RESULTS_TABLES}@sha256:{hashlib.sha256(tables_blob).hexdigest()}"}
    stats["anchor"] = {"label": primary["label"], "note": primary["note"], "recovered": primary["recovered"], "denominator": primary["denominator"],
                       "source": f"{RESULTS_TABLES}@sha256:{hashlib.sha256(tables_blob).hexdigest()}"}
    for tag, files in GATE_FILES.items():
        recs = [r for r in records if r.harness_tag == tag]
        result_blob = source.read(files["result"])
        result = json.loads(result_blob.decode("utf-8"))
        if {int(k): v for k, v in result["verdicts"].items()} != {int(r.entry): r.data["result"]["verdict"] for r in recs}:
            raise BuildError(f"{files['result']}: verdicts do not match the {tag} records")
        attempts = [(r, a) for r in recs for a in r.data["result"]["attempts"]]
        searches = [(r, i, e["line"]) for r in recs for i, e in enumerate(r.data["events"]) if e["line"].startswith("[tavily] ")]
        stats[tag] = {
            "files": files, "result_sha256": hashlib.sha256(result_blob).hexdigest(), "record_ids": [r.record_id for r in recs],
            "recovered": sum(1 for v in result["verdicts"].values() if v in RECOVERED), "entries": len(result["verdicts"]),
            "citations": len(result["c"]["cited"]),
            "proposed": len(result["b"].get("proposed") or []), "applied": len(result["b"].get("applied") or []),
            "cost_cap_endings": len(result["d"].get("cost_cap_endings") or {}),
            "ok": {k: bool(result[k]["ok"]) for k in "abcd"}, "detail": {k: result[k]["detail"] for k in "abcd"}, "passed": bool(result["passed"]),
            "searches": searches,
            "consulted_attempts": [(r, a) for r, a in attempts if "consulted" in a],
            "references": sum(len(a["consulted"]) for _, a in attempts if "consulted" in a),
            "reasons": [(r, a) for r, a in attempts if "reason_no_citation" in a],
            "spent": sum(r.data["cost_guard"]["spent_usd"] for r in recs),
            "estimated": sum(r.data["cost_guard"].get("estimated_sandbox_spent_usd") or 0.0 for r in recs),
        }
    return stats


def _attempt_refs(pairs: list) -> list[str]:
    return [f"{r.record_id}#{_attempt_label(a['attempt_number'])}" for r, a in pairs]


def _badge(tag: str, stats: dict[str, dict]) -> dict:
    if tag not in GATE_FILES:
        anchor = stats["anchor"]
        return {"exploratory": False, "label": "PRE-REGISTERED",
                "text": "PRE-REGISTERED — harness-v1.3.2 is the pre-registered CONTROL / TREATMENT run; not exploratory.",
                "figures": [{"criterion": "primary", "label": anchor["label"], "note": anchor["note"],
                             "text": f"{anchor['recovered']}/{anchor['denominator']}",
                             "recovered": api_reported(anchor["recovered"], source_field="rates[0].recovered", source=anchor["source"]),
                             "denominator": api_reported(anchor["denominator"], source_field="rates[0].denominator", source=anchor["source"])}],
                "links": {"results_tables": RESULTS_TABLES, "results": "reports/corpus-v2.1/RESULTS.md"}}
    s = stats[tag]
    files = s["files"]
    gate_json = f"{files['result']}@sha256:{s['result_sha256']}"
    a = {"criterion": "a", "ok": s["ok"]["a"], "detail": s["detail"]["a"], "text": f"{s['recovered']}/{s['entries']}",
         "recovered": api_reported(s["recovered"], computed_from=f"count of verdicts in {list(RECOVERED)}", source=gate_json),
         "entries": api_reported(s["entries"], computed_from="count of verdicts", source=gate_json)}
    b = {"criterion": "b", "ok": s["ok"]["b"], "detail": s["detail"]["b"],
         "applied": api_reported(s["applied"], computed_from="length of b.applied", source=gate_json),
         "proposed": api_reported(s["proposed"], computed_from="length of b.proposed", source=gate_json)}
    c = {"criterion": "c", "ok": s["ok"]["c"], "detail": s["detail"]["c"],
         "citations": api_reported(s["citations"], computed_from="length of c.cited", source=gate_json)}
    d = {"criterion": "d", "ok": s["ok"]["d"], "detail": s["detail"]["d"],
         "cost_cap_endings": api_reported(s["cost_cap_endings"], computed_from="number of entries in d.cost_cap_endings", source=gate_json)}
    if tag == "harness-v1.3.3":
        a["text"] += " (measured)"
        a["annotation"] = ARTEFACT_NOTE
        c["searches"] = {"value": len(s["searches"]), "tag": DERIVED, "computed_from": "count of '[tavily] ' event lines",
                         "source": [{"record_id": r.record_id, "field": f"events[{i}].line", "line": line} for r, i, line in s["searches"]]}
        c["text"] = f"{s['citations']} citations in {len(s['searches'])} searches"
        text = f"EXPLORATORY — did not pass its pre-registered gate. a: {a['text']}, c: {c['text']}."
    else:
        c["attempts_consulted"] = api_reported(len(s["consulted_attempts"]), computed_from="count of result.attempts[*].consulted",
                                           source=_attempt_refs(s["consulted_attempts"]))
        c["references_consulted"] = api_reported(s["references"], computed_from="sum of len(result.attempts[*].consulted)",
                                             source=_attempt_refs(s["consulted_attempts"]))
        c["reasons_recorded"] = api_reported(len(s["reasons"]), computed_from="count of result.attempts[*].reason_no_citation",
                                         source=_attempt_refs(s["reasons"]))
        c["text"] = (f"{s['citations']} citations ({len(s['consulted_attempts'])} attempts consulted, "
                     f"{s['references']} refs, {len(s['reasons'])} reasons recorded)")
        text = f"EXPLORATORY — did not pass its pre-registered gate. a: {a['text']}, c: {c['text']}."
    spent, estimated = s["spent"], s["estimated"]
    gate_cost: dict = {"value": round(spent, 10), "tag": ESTIMATED if estimated else API_REPORTED, "currency": "USD",
                       "computed_from": "sum of cost_guard.spent_usd over the gate records", "source": s["record_ids"]}
    if estimated:
        gate_cost["measured"] = api_reported(round(spent - estimated, 10), computed_from="sum of spent_usd - sum of estimated_sandbox_spent_usd")
        gate_cost["estimated"] = {"value": round(estimated, 10), "tag": ESTIMATED, "computed_from": "sum of cost_guard.estimated_sandbox_spent_usd"}
    return {"exploratory": True, "label": "EXPLORATORY", "text": text, "gate_passed": s["passed"], "figures": [a, b, c, d], "gate_cost": gate_cost,
            "links": {"gate_result": files["result"], "gate_report": files["report"], "run_records": s["record_ids"],
                      "cost_line": _src(files["report"], files["cost_line"])}}


# ---------------------------------------------------------------- passport

def passport_hash(passport: dict) -> str:
    body = {k: v for k, v in passport.items() if k != "passport_hash"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()


def serialize(passport: dict) -> bytes:
    return (json.dumps(passport, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def passport_path(record: Record) -> str:
    return f"{PASSPORT_DIR}/{record.harness_tag}/{record.record_set.name.replace('/', '_')}/{record.path.rsplit('/', 1)[1]}"


def _key(record: Record) -> tuple[str, str, str]:
    return (record.harness_tag, record.record_set.name, record.entry)


LF, CRLF = bytes([10]), bytes([13, 10])
D28_NOTE = ("D-28: the hash results_tables.json lists for this record is the SHA-256 of the CRLF worktree file, "
            "not of the git blob; it does not match the record id")


def _results_tables_hash(record: Record, stats: dict[str, dict]) -> dict:
    """The record hash as listed in results_tables.json (harness-v1.3.2 CONTROL / TREATMENT only), reconciled with the blob."""
    tables = stats["results_tables"]
    row = tables["listed"].get((record.record_set.name, record.entry)) if record.harness_tag == "harness-v1.3.2" else None
    if row is None:
        return absent(f"not listed in {RESULTS_TABLES}")
    reconciled = hashlib.sha256(record.blob.replace(LF, CRLF)).hexdigest() == row["value"]
    return {"value": row["value"], "label": "worktree hash (D-28)", "note": D28_NOTE, "equals_sha256_of_blob_with_crlf": reconciled,
            "source": tables["source"], "source_field": row["source_field"]}


def build_passport(record: Record, by_key: dict[tuple[str, str, str], Record], stats: dict[str, dict]) -> dict:
    d, tag = record.data, record.harness_tag
    result, cert, batch = d["result"], d["certificate"], d["batch"]
    baseline = cert.get("baseline") or {}
    kills = _kills(record)
    attempts = result.get("attempts") or []
    unplaced = set(kills) - {int(a["attempt_number"]) for a in attempts}
    if unplaced:
        raise BuildError(f"{record.path}: kill events for attempts not in the record: {sorted(unplaced)}")
    sandbox_id = baseline.get("sandbox_id")
    superseded = by_key[(tag, "control", record.entry)].record_id if record.record_set.name == "control/infra_retries" else None
    annotations = []
    for note in ANNOTATIONS.get(_key(record), []):
        note = dict(note)
        if "related_record" in note:
            note["related_record"] = by_key[note["related_record"]].record_id
        annotations.append(note)
    passport = {
        "schema": SCHEMA,
        "record_id": record.record_id,
        "record": {"path": record.path, "sha256": record.sha256, "record_set": record.record_set.name,
                   "hash_basis": "git blob at HEAD (git cat-file blob HEAD:<path>), never the worktree file",
                   "results_tables_sha256": _results_tables_hash(record, stats)},
        "image_id": {"value": sandbox_id, "source_field": "certificate.baseline.sandbox_id", "base_image": baseline.get("base_image")}
        if sandbox_id else absent("no baseline sandbox recorded"),
        "harness_tag": tag,
        "harness_commit": batch["harness_commit"],
        "arm": record.arm,
        "entry": {"id": record.entry, "name": d["corpus_entry"]["name"], "repo_url": d["corpus_entry"]["repo_url"],
                  "commit_sha": d["corpus_entry"]["commit_sha"], "category": batch.get("category")},
        "run": {"started_at": d.get("started_at"), "finished_at": d.get("finished_at")},
        "verdict": {"verdict": result["verdict"], "taxonomy_code": result.get("taxonomy_code"), "reason_code": result.get("reason_code"),
                    "indeterminate_reason": result.get("indeterminate_reason"), "recovery": cert.get("recovery"),
                    "first_repo_error": result.get("first_repo_error"), "last_error": result.get("last_error")},
        "baseline": {"result": baseline.get("result"),
                     "exit_code": api_reported(baseline["exit_code"], source_field="certificate.baseline.exit_code")
                     if baseline.get("exit_code") is not None else absent("no baseline exit code recorded"),
                     "taxonomy_code": baseline.get("taxonomy_code"), "evidence": baseline.get("evidence")},
        "classification_chain": [
            {"error": e["error"], "class": e["class"], "attribution": e["attribution"], "phase": e["phase"],
             "cleared_by": _attempt_label(e["cleared_by"]) if e.get("cleared_by") is not None else absent("not cleared by any attempt")}
            for e in result.get("error_chain") or []],
        "attempts": [_attempt(record, i, a, kills) for i, a in enumerate(attempts)],
        "time_machine_actions": [_time_machine_action(a) for a in attempts if a.get("time_machine")],
        "cost": _cost(record),
        "badge": _badge(tag, stats),
        "superseded_by": superseded if superseded else absent("not superseded"),
        "annotations": annotations,
    }
    passport["passport_hash"] = passport_hash(passport)
    return passport


def build_all(source: BlobSource | None = None) -> list[tuple[Record, dict]]:
    """Every (record, passport), in record order. Deterministic: same blobs in, same bytes out."""
    source = source or GitBlobSource()
    records = load_records(source)
    by_key = {_key(r): r for r in records}
    stats = _gate_stats(records, source)
    return [(r, build_passport(r, by_key, stats)) for r in records]


def record_index(built: list[tuple[Record, dict]]) -> str:
    lines = [
        "# Phase D record index",
        "",
        f"{len(built)} run records (API-REPORTED: count of committed record blobs), one passport each. Record id = `<harness_tag>/<arm>/<entry>@<sha256>`; the SHA-256 is taken over the",
        "committed blob (`git cat-file blob HEAD:<path>`), never over the worktree file. Generated by `python -m phase_d.build_passports`;",
        "checked by `python -m phase_d.verify_passports`.",
        "",
        "",
        "D-28 reconciliation: `reports/corpus-v2.1/results_tables.json` lists `record_*_sha256` values that are hashes of the CRLF worktree",
        "files, not of the git blobs. The third column is the hash that file lists; the second is the blob hash used in the record id.",
        "The listed hash equals the SHA-256 of the blob with every LF written as CRLF (checked at build time for every listed record).",
        "",
        "| Record id | Blob sha256 (record id basis) | results_tables.json sha256 (D-28, CRLF worktree file) | Record | Set | Verdict | Passport |",
        "|---|---|---|---|---|---|---|",
    ]
    for record, passport in built:
        listed = passport["record"]["results_tables_sha256"]["value"]
        lines.append(f"| `{record.record_id}` | `{record.sha256}` | {f'`{listed}`' if listed else 'not listed'} | `{record.path}` | "
                     f"{record.record_set.name} | {passport['verdict']['verdict']} | `{passport_path(record)}` |")
    return "\n".join(lines) + "\n"
