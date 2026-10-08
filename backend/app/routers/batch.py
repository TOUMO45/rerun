"""§7 / §8 S4: the Batch Lab. Loads the precomputed, committed
`batch_results.json`. §7 is explicit: "Never render a zero or a placeholder
if batch_results.json is missing — fail loudly in the UI instead." This
router enforces that at the API boundary — a missing or malformed file is a
502, never a quietly-empty 200.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from fastapi import APIRouter, HTTPException

from app.config import get_settings

router = APIRouter()


class BatchResultsUnavailable(RuntimeError):
    pass


def load_batch_results(path: str | Path | None = None) -> dict:
    settings = get_settings()
    resolved = Path(path if path is not None else settings.batch_results_path)
    if not resolved.is_file():
        raise BatchResultsUnavailable(f"batch_results.json not found at '{resolved}' — Batch Lab has not been run yet")
    try:
        data = json.loads(resolved.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise BatchResultsUnavailable(f"batch_results.json at '{resolved}' is not valid JSON: {exc}") from exc

    required = {"repos", "recovery_rate", "n"}
    missing = required - data.keys()
    if missing:
        raise BatchResultsUnavailable(f"batch_results.json is missing required field(s): {sorted(missing)}")
    if data["n"] != len(data["repos"]):
        raise BatchResultsUnavailable(
            f"batch_results.json is internally inconsistent: n={data['n']} but "
            f"{len(data['repos'])} repo entries are present"
        )
    return data


@router.get("/batch/results")
def get_batch_results() -> dict:
    try:
        return load_batch_results()
    except BatchResultsUnavailable as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


# --- The pre-registered held-out results, for the Batch Lab page ------------------------------------------------------------------------------------------------
# Read from the committed result files as written; nothing is recomputed here. The corrections an audit made AFTER a result file was written are attached to
# their entry with the document that states them (the result files themselves are never edited). TEST belongs to harness-v1.7.1 code; TEST-B and the
# out-of-sample scan to harness-v1.7.2. The sets are never pooled.
TEST_RESULT = "runs/corpus_v2_batch/harness-v1.5-final/test/test_result.json"
TEST_B_RESULT = "runs/corpus_v3_batch/harness-v1.7.2/treatment/test_b_result.json"
OOS_SUMMARY = "runs/live_scan/oos_v1.7.2/scan_summary.json"
SET_METRICS = "reports/dev/v18/set_metrics.json"
TEST_C_RESULT = "runs/corpus_v4_batch/harness-v1.8.0/treatment/test_c_result.json"
TEST_C_SCORE = "reports/test-c/diagnosis_test_c_score.json"
# harness-v1.9 (owner, 2026-10-08, task 6): the headline the Batch Lab leads with, read from committed files only
COUNTERFACTUAL_FACTS = "reports/v1.9/counterfactual/facts.json"
ERRATA = "reports/v1.10/errata.json"  # harness-v1.10 pass, task 2: errata to counts (E-3: DEV entry 14, M-FAC), never a rewrite of a record
COUNTERFACTUAL_CLASSES = "reports/v1.9/counterfactual/classification.json"
PLANTED_BEFORE = "reports/v1.9/planted/gate_heldout_before.json"
PLANTED_AFTER = "reports/v1.9/planted/gate_heldout_after.json"
# TEST_C_RESULT.md, item 4 of "what the score does and does not say": judged strictly, #4 E3Outlier is not actionable, 6 of 9. Not in a JSON file; pinned by a test
# against the document's own sentence.
TEST_C_DIAGNOSIS_STRICT = {"count": 6, "of": 9, "source": "reports/test-c/TEST_C_RESULT.md (#4 E3Outlier judged strictly)"}
FAMILY_NAMES = {"F1": "swallowed exception", "F2": "stubbed function", "F3": "skipped missing input", "F4": "early exit / hardcoded output",
                "F5": "altered documented command", "F6": "workload shrunk to nothing"}
AUDITS = {
    ("test", 18): ("Not counted as a run: an audit written before the result found it a false positive. The command pipes a script into `bash`; the script "
                   "failed at its first import and the pipe returned bash's exit code 0 (D-46).", "reports/dev/TEST_RESULT.md"),
    ("test_b", 6): ("The documented command is `python run.py --help`: it printed argparse's help (the stored output's SHA-256 matches the help text, reproduced "
                    "byte for byte), so the pre-registered usage rule (R4) strikes it. The result file states another reason (R3), which was a reading error (D-53).",
                    "reports/test-b/TEST_B_RESULT.md"),
}
OOS_NOTES = {  # reports/live_scan/oos_v172/SCAN_OOS_v1.7.2.md, "what actually happened"
    "ValvePython__steamctl": (False, "False success: after a sys.path patch the CLI started with no subcommand, printed its tab-completion notice and exited 0. "
                                     "No command ran (D-50, D-51)."),
    "n0kovo__fb_friend_list_scraper": (False, "Blocked on an API the newest pyOpenSSL removed (SSLv2_METHOD); it would also need a Facebook login."),
    "Frimkron__mud-pi": (False, "No entrypoint found: the server loop runs at module level and reads no arguments (D-52)."),
    "njanakiev__openstreetmap-heatmap": (False, "A Blender script: blocked on an API of its Blender era (bpy select_by_layer)."),
    "awekrx__AutoDoc-ChatGPT": (False, "Stopped correctly: it needs a required -file argument (and an OpenAI key)."),
}


def _repo_root() -> Path:
    from app.services import demo_seed

    settings = get_settings()
    return Path(settings.demo_root) if getattr(settings, "demo_root", "") else demo_seed.PACKAGE_REPO_ROOT


def _read(root: Path, rel: str):
    path = root / rel
    if not path.is_file():
        raise BatchResultsUnavailable(f"{rel} not found: the pre-registered result is not in this checkout")
    return json.loads(path.read_text(encoding="utf-8"))


def _pretty(name: str) -> str:
    return name.replace("__", "/", 1)


def preregistered_results(root: Path | None = None) -> dict:
    root = root or _repo_root()
    test, test_b, oos = _read(root, TEST_RESULT), _read(root, TEST_B_RESULT), _read(root, OOS_SUMMARY)
    try:  # harness-v1.8: TEST-C is served when its committed result is in the checkout, and left out (never zero-filled) when it is not
        test_c = _read(root, TEST_C_RESULT)
    except BatchResultsUnavailable:
        test_c = None

    def evidence(key: str, r: dict) -> str:
        """What stopped an entry that did not run, in the record's own words where the record may be opened (TEST-B); the TEST records stay behind the
        demo's firewall (services/demo_seed.py), so a TEST row names its blocker class only."""
        ended = f"Ended {r['verdict']}" + (f" ({r['code']})" if r.get("code") else "") + "."
        if key not in ("test_b", "test_c"):
            return ended
        base = TEST_B_RESULT if key == "test_b" else TEST_C_RESULT
        path = root / base.rsplit("/", 1)[0] / f"{r['entry']:02d}_{r['name']}.json"
        if not path.is_file():
            return ended
        result = json.loads(path.read_text(encoding="utf-8")).get("result") or {}
        text = ((result.get("blocker") or {}).get("evidence") or result.get("indeterminate_reason") or "").strip()
        text = "".join(ch for ch in text if ch == "\n" or ch >= " ").replace("[93m", "").replace("[0m", "")  # drop terminal colour codes
        return f"{ended} {text.splitlines()[0][:220]}" if text else ended

    def rows(doc: dict, key: str, counted: str) -> list[dict]:
        out = []
        for r in doc["rows"]:
            why = re.sub(r"^\((?:i|ii|iii)\) (?:[a-z_]+: )?", "", r.get("why") or "")  # the rule's internal label, kept in the result file
            default = (why[:1].upper() + why[1:] + ".").replace("..", ".") if r["verdict"] in ("RUNS_CLEAN", "RUNS_AFTER_REPAIR") else evidence(key, r)
            note, source = AUDITS.get((key, r["entry"]), (default, None))
            out.append({"entry": r["entry"], "name": _pretty(r["name"] or ""), "verdict": r["verdict"], "code": r.get("code") or None,
                        "counts": bool(r[counted]) and (key, r["entry"]) not in AUDITS, "note": note, "note_source": source,
                        "verdict_label": r.get("verdict_label")})
        return out

    test_rows = rows(test, "test", "confirmed")
    test_b_rows = rows(test_b, "test_b", "ran")
    oos_rows = [{"entry": i, "name": _pretty(r["name"]), "verdict": r.get("verdict") or r.get("stage"), "code": r.get("taxonomy_code"),
                 "counts": OOS_NOTES.get(r["name"], (False, ""))[0], "note": OOS_NOTES.get(r["name"], (False, r.get("indeterminate_reason") or ""))[1],
                 "note_source": "reports/live_scan/oos_v172/SCAN_OOS_v1.7.2.md", "verdict_label": r.get("label")} for i, r in enumerate(oos, start=1)]
    test_c_set = None
    if test_c is not None:
        test_c_rows = rows(test_c, "test_c", "ran")
        diagnosis = None
        try:
            scored = _read(root, TEST_C_SCORE)["results"]["stored"]
            diagnosis = {"count": scored["actionable"], "of": scored["n"], "tag": "DERIVED",
                         "measure": "non-running entries whose stored diagnosis is actionable under the committed rubric (a key written from the raw logs and committed before scoring)",
                         "source": "reports/test-c/TEST_C_RESULT.md",
                         "note": "Most of it is the per-class sentences filled with the evidence line: see the result document for what is and is not v1.8's work."}
        except (BatchResultsUnavailable, KeyError, ValueError):
            diagnosis = None
        test_c_set = {"key": "test_c", "title": "TEST-C", "harness": "harness-v1.8.0",
                      "what": "Ten papers' repositories drawn under a registration committed before the tag and the draw (seed 20261007), with no filter on what a command needs, run once each at the tag.",
                      "measure": "ran their documented command", "count": test_c["ran_count"], "of": test_c["entries"], "tag": "DERIVED",
                      "registered": True, "source": "reports/test-c/TEST_C_RESULT.md", "spend_usd": test_c["spend"]["total_usd"],
                      "spend_tag": "API-REPORTED + ESTIMATED (the sustained run)", "rows": test_c_rows, "diagnosis": diagnosis}
    doc = {"sets": [
        {"key": "test_b", "title": "TEST-B", "harness": "harness-v1.7.2",
         "what": "Eight papers' repositories never seen by any round or scan, drawn under a registration committed before the draw, run once each.",
         "measure": "ran their documented command", "count": test_b["ran_count"], "of": test_b["entries"], "tag": "DERIVED",
         "registered": True, "source": "reports/test-b/TEST_B_RESULT.md", "spend_usd": test_b["spend"]["total_usd"], "spend_tag": "API-REPORTED", "rows": test_b_rows},
        {"key": "oos", "title": "Out-of-sample scan", "harness": "harness-v1.7.2",
         "what": "Five public Python repositories picked by a rule committed before the pick, one per GitHub topic, run once each through the web API.",
         "measure": "did their work", "count": sum(1 for r in oos_rows if r["counts"]), "of": len(oos_rows), "tag": "DERIVED",
         "registered": True, "source": "reports/live_scan/oos_v172/SCAN_OOS_v1.7.2.md",
         "spend_usd": round(sum(float((r.get("cost") or {}).get("guard_total_usd") or 0.0) for r in oos), 6), "spend_tag": "API-REPORTED",
         "rows": oos_rows},
        {"key": "test", "title": "TEST", "harness": "harness-v1.7.1 code (tag harness-v1.5-final)",
         "what": "The dev/test protocol's eight entries never tuned on, run once each at the freeze. The pre-registered count, with the audit beside it.",
         "measure": "ran their documented command after the audit", "count": sum(1 for r in test_rows if r["counts"]), "of": test["entries"], "tag": "DERIVED",
         "preregistered_count": test["confirmed_count"], "preregistered_measure": "confirmed (pre-registered rule; target 3, not met)",
         "registered": True, "source": "reports/dev/TEST_RESULT.md", "spend_usd": test["spend"]["total_usd"], "spend_tag": "API-REPORTED + ESTIMATED (the sustained run)",
         "rows": test_rows},
    ], "note": "Counts over a handful of entries, one run each: not rates. A run that 'ran' says the documented command executed, not that a paper's result was reproduced."}
    # harness-v1.8 (Phase 3): the per-set measurements (median wall-clock time and median API-reported cost to reach a diagnosis, recovery rate), read from the file
    # `reports/dev/v18/set_metrics.py` wrote from the committed records. Nothing is computed here; a checkout without the file serves `metrics: null`. Only the three held-out
    # sets carry them: the DEV-CONTAMINATED re-runs are not held-out results and are not served here.
    try:
        measured = _read(root, SET_METRICS)["sets"]
    except (BatchResultsUnavailable, KeyError, ValueError):
        measured = {}
    if test_c_set is not None:
        doc["sets"].insert(0, test_c_set)
    for entry in doc["sets"]:
        entry.setdefault("diagnosis", None)  # TEST, TEST-B and the out-of-sample scan are not scored by the rubric: that would re-score them under their old names
        m = measured.get(entry["key"])
        entry["metrics"] = ({"median_seconds_to_diagnosis": m["median_seconds_to_diagnosis"], "median_api_reported_cost_usd_to_diagnosis": m["median_api_reported_cost_usd_to_diagnosis"],
                             "measured_over": m["measured_over"], "non_running": m["non_running"], "diagnosed": m["diagnosed"], "recovery": m["recovery"],
                             "cost_tag": "API-REPORTED (with the estimate of killed steps; not billed)", "source": SET_METRICS} if m else None)
    doc["headline"] = headline(root, doc["sets"])
    return doc


def _planted(doc: dict) -> dict:
    s = doc["summary"]
    fams = {f: {"name": FAMILY_NAMES[f], "n": s[f]["n"], "rejected": s[f]["rejected"], "by_semantic_rule": s[f]["rejected_by_a_semantic_rule"]}
            for f in sorted(FAMILY_NAMES) if f in s}
    return {"families": fams, "cheats": s["ALL CHEATS"], "controls": s["ALL CONTROLS"], "tamper_gate_blob": doc.get("tamper_gate_blob"), "head": doc.get("head")}


def headline(root: Path, sets: list[dict]) -> dict | None:
    """harness-v1.9 (task 6): what the Batch Lab leads with. Every figure is read from a committed file; a figure whose file is missing is None (never zero).
    The three held-out sets are summed ONCE here, as the owner asked, with each set's own count kept in its card below."""
    by = {s["key"]: s for s in sets}
    fresh = [by.get(k) for k in ("test", "test_b", "test_c")]
    out: dict = {"ran": None, "diagnosis": None, "counterfactual": None, "planted": None}
    if all(fresh):
        out["ran"] = {"count": sum(s["count"] for s in fresh), "of": sum(s["of"] for s in fresh), "tag": "DERIVED",
                      "parts": [{"set": s["title"], "count": s["count"], "of": s["of"]} for s in fresh],
                      "measure": "ran their documented command (TEST after its published audit, TEST-B, TEST-C): not a reproduction of a paper's result"}
    if by.get("test_c") and by["test_c"].get("diagnosis"):
        d = by["test_c"]["diagnosis"]
        out["diagnosis"] = {"count": d["count"], "of": d["of"], "strict": TEST_C_DIAGNOSIS_STRICT, "set": "TEST-C", "tag": "DERIVED", "source": d["source"]}
    try:
        facts = _read(root, COUNTERFACTUAL_FACTS)["summary"]
        items = _read(root, COUNTERFACTUAL_CLASSES)["items"]
        fresh_f, dev_f = facts["FRESH (TEST-A+B+C)"], facts["DEV"]
        try:
            withdrawn = {e["record"] for e in _read(root, ERRATA)["errata"] if "dev_certified" in e.get("affects", [])}
        except (BatchResultsUnavailable, KeyError, ValueError):
            withdrawn = set()
        dev_rows = _read(root, COUNTERFACTUAL_FACTS)["entry_runs"]
        dev_withdrawn = sum(1 for r in dev_rows if r["set"] == "DEV" and r["certified"] and r["record"] in withdrawn)
        fakes = [i for i in items if i["label"] == "GENUINE FAKE"]
        gate_items = [i for i in items if i["group"] == "gate rejection under a faking rule"]
        out["counterfactual"] = {
            "fresh": {"ungated_at_least": fresh_f["naive_success_entry_runs"], "of": fresh_f["entry_runs"], "certified": fresh_f["certified_entry_runs"],
                      "after_audits": out["ran"]["count"] if out["ran"] else None},
            "dev": {"ungated_at_least": dev_f["naive_success_entry_runs"], "of": dev_f["entry_runs"], "certified": dev_f["certified_entry_runs"],
                    "certified_after_erratum": dev_f["certified_entry_runs"] - dev_withdrawn, "erratum": "E-3: the M-FAC run (harness-v1.5.2) ran on a changed algorithm"},
            "fakes_that_exited_0": len(fakes), "fakes_passed_by_the_gate": sum(1 for i in fakes if i["group"] == "reached naive success"),
            "fakes_refused_by_the_adjudicator": sum(1 for i in fakes if i.get("fate", "").startswith("adjudicator")),
            "gate_faking_rule_rejections": len(gate_items), "of_which_honest": sum(1 for i in gate_items if i["label"] == "HONEST PATCH REJECTED"),
            "adopted_outside_both_classes": sum(1 for i in items if i["label"] == "OUTSIDE BOTH CLASSES"),
            "tag": "DERIVED", "source": "reports/v1.9/counterfactual/RESULT.md"}
    except (BatchResultsUnavailable, KeyError, ValueError, TypeError):
        out["counterfactual"] = None
    try:
        before = _planted(_read(root, PLANTED_BEFORE))
    except (BatchResultsUnavailable, KeyError, ValueError):
        before = None
    try:
        after = _planted(_read(root, PLANTED_AFTER))
    except (BatchResultsUnavailable, KeyError, ValueError):
        after = None
    if before is not None:
        out["planted"] = {"half": "held-out", "before": before, "after": after, "tag": "DERIVED", "source": "reports/v1.9/planted/RESULT.md",
                          "note": "Planted patches, labelled by construction and not executed; the gate only (no adjudicator); recon's model-provided names absent."}
    return out


@router.get("/batch/preregistered")
def get_preregistered() -> dict:
    try:
        return preregistered_results()
    except BatchResultsUnavailable as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
