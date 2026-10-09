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


# flag-mode pass (owner, 2026-10-09, task 4): the Batch Lab's headline is READ from reports/v1.9/figures.json, the one source of the README's result section and the
# Devpost texts; nothing here computes a figure. Order: what ran (3 of 26), the diagnosis (7 of 9, 6 strict), the benchmark and its per-layer tables, the limits.
FIGURES = "reports/v1.9/figures.json"
BENCHMARK_TABLES = (
    ("planted_heldout.gate_v1.9", "Planted set, held-out half: the tamper gate alone (harness-v1.9)", ""),
    ("planted_heldout.pipeline_v1.9.0", "Planted set, held-out half: the full pipeline (harness-v1.9.0)",
     "Table only, no summary sentence: the adjudicator refused all {pipeline_controls_refused} honest controls that passed the run here, so its refusals are detection only "
     "on the repositories whose run really fails. A refusal at `run` means the cheat did not make the command pass: not a catch."),
    ("independent.pipeline_v1.9.0", "Independent set: the full pipeline (harness-v1.9.0, the submission harness)",
     "{indep_real_failure_cheats_adopted} of the {indep_real_failure_cheats} cheats aimed at repositories whose run really fails were adopted: the real fix bundled with a change of the result."),
    ("independent.refuse_v1.10.0-rc4", "Independent set: the behavioural checks refusing (harness-v1.10.0-rc4, measured once)",
     "They also refused {indep_controls_refused_by_checks} of the {indep_controls_passed_run} honest controls that passed the run ({indep_fr_pct}%, above the pre-registered "
     "{fr_rule_line_pct}% line): the verdicts stay harness-v1.9.0's."),
    ("independent.flag_mode.derived", "Independent set: the flag mode (harness-v1.9.0 verdicts, REVIEW_REQUIRED where the checks found something)",
     "Derived from committed records, not measured by a run of the flag mode; this use of the checks was chosen after the results were seen. The behavioural tracer was "
     "exercised by no cheat ({flag_cheats_traced} traced); cheats written to fit the allow-list are unmeasured."),
)


def _rows(table: dict) -> list[dict]:
    def row(label: str, c: dict) -> dict:
        return {"label": label, "n": c["n"], "refused": c["refused"], "adopted": c["adopted"], "flagged": c["flagged"], "refused_by_layer": c["refused_by_layer"]}

    out = [row(f"cheats {fam}" + (f" {FAMILY_NAMES[fam]}" if fam in FAMILY_NAMES else ""), c) for fam, c in table["families"].items()]
    out.append(row("cheats, all", table["all_cheats"]))
    out.append(row("cheats aimed at failing repositories", table["cheats_aimed_at_failing_repositories"]))
    out.append(row("honest controls (refused = false refusals)", table["all_controls"]))
    return out


def headline(root: Path, sets: list[dict]) -> dict | None:
    """flag-mode pass (task 4): what the Batch Lab leads with, read from reports/v1.9/figures.json (generated from the committed result files by
    reports/v1.9/figures.py). A missing or unreadable figures file is None (never zero). `sets` is unused: the figures file already holds the three held-out counts."""
    try:
        doc = _read(root, FIGURES)
        f = {k: v["value"] for k, v in doc["figures"].items()}
        tables = doc.get("tables") or {}
    except (BatchResultsUnavailable, KeyError, ValueError, TypeError):
        return None
    try:
        ran = {"count": f["held_out_ran"], "of": f["held_out_total"], "tag": "DERIVED",
               "parts": [{"set": name, "count": f[f"{key}_ran"], "of": f[f"{key}_of"]} for key, name in (("test", "TEST"), ("test_b", "TEST-B"), ("test_c", "TEST-C"))],
               "measure": "ran their documented command (TEST after its published audit, TEST-B, TEST-C): not a reproduction of a paper's result"}
        diagnosis = {"count": f["diagnosis_actionable"], "of": f["diagnosis_non_running"], "set": "TEST-C", "tag": "DERIVED",
                     "strict": {"count": f["diagnosis_strict"], "of": f["diagnosis_non_running"], "source": doc["figures"]["diagnosis_strict"]["source"]},
                     "source": doc["figures"]["diagnosis_actionable"]["source"]}
        counterfactual = {
            "fresh": {"ungated_at_least": f["ungated_fresh_at_least"], "of": f["fresh_entry_runs"], "certified": f["certified_fresh_as_recorded"],
                      "after_audits": f["certified_fresh_after_audits"]},
            "dev": {"ungated_at_least": f["ungated_dev_at_least"], "of": f["dev_entry_runs"], "certified": f["certified_dev"],
                    "certified_after_erratum": f["certified_dev_after_erratum"], "erratum": "E-3: the M-FAC run (harness-v1.5.2) ran on a changed algorithm"},
            "removed_by_audit": f["fresh_removed_by_audit"], "removed_that_were_fakes": f["fresh_removed_that_were_fakes"],
            "fakes_that_exited_0": f["fakes_recorded"], "fakes_passed_by_the_gate": f["fakes_exit_zero_passed_gate"], "fakes_refused_by_the_adjudicator": f["fakes_refused_by_adjudicator"],
            "gate_faking_rule_rejections": f["gate_faking_rule_rejections"], "of_which_honest": f["gate_faking_rule_rejections_honest"],
            "tag": "DERIVED", "source": "reports/v1.9/counterfactual/RESULT.md"}
        benchmark = {"source": "benchmark/README.md", "command": "python benchmark/score.py --all", "tag": "DERIVED",
                     "sets": {"planted": f["planted_patches"], "independent": f["indep_authored_cheats"] + f["indep_controls"], "independent_measured_cheats": f["indep_confirmed_cheats"],
                              "independent_dropped": f["indep_dropped_cheats"]},
                     "status": "Both sets are development material now: a new independent set is needed to measure again",
                     "tables": [{"name": name, "title": title, "note": note.format(**f), "rows": _rows(tables[name]["table"])}
                                for name, title, note in BENCHMARK_TABLES if name in tables]}
        limits = [
            f"Anti-cheat is not a headline claim: harness-v1.9.0 adopted {f['indep_real_failure_cheats_adopted']} of the {f['indep_real_failure_cheats']} independent cheats aimed at "
            f"repositories whose run really fails ({f['indep_real_failure_adopted_pct']}%), above the {f['anticheat_headline_line_pct']}% line.",
            f"The flag mode marks all {f['flag_cheats_adopted_flagged']} of the cheats harness-v1.9.0 adopted and {f['flag_controls_adopted_flagged']} of the "
            f"{f['indep_v190_adopted_controls']} honest repairs it adopted: derived from committed records, chosen after the results were seen; no cheat was traced, and cheats "
            "written to fit the allow-list are unmeasured.",
            "Both cheat sets are development material now; an adaptive set (an author who knows the checks) is not measured.",
            f"Erratum E-3: DEV certified {f['certified_dev']} as recorded, {f['certified_dev_after_erratum']} after it (entry 14, M-FAC, ran on a changed algorithm).",
            f"Post-hoc, never merged into TEST-C: one live run of minmaxot at harness-v1.9.0 (the output-directory repair fired; RUNS_AFTER_REPAIR at smoke level, "
            f"${f['minmaxot_posthoc_cost_usd']:.2f} API-REPORTED).",
            "\"Ran\" means the documented command executed, never that a paper's result was reproduced.",
        ]
    except KeyError:
        return None
    return {"source": FIGURES, "ran": ran, "diagnosis": diagnosis, "benchmark": benchmark, "counterfactual": counterfactual, "limits": limits}


@router.get("/batch/preregistered")
def get_preregistered() -> dict:
    try:
        return preregistered_results()
    except BatchResultsUnavailable as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
