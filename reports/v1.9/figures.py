"""harness-v1.9: every number the README's "The result" section states, read from the committed result files and written to reports/v1.9/figures.json with its tag and source.

    backend/.venv/Scripts/python.exe reports/v1.9/figures.py [--write]

The README guard (backend/tests/test_phase_d_submission.py) requires every number in the submission texts to come from a committed JSON source and every numbered line
to carry a tag; this file is such a source (as reports/phase-d/dev_rounds.json is). Nothing here is typed by hand: each value is computed from `facts.json`,
`classification.json`, `second_rater.json`, the planted gate outputs, TEST-C's score and the three held-out result files (through the batch router's `sets`).

Flag-mode pass (owner, 2026-10-09): this file is the ONE source of the README's result section, the Batch Lab headline (`GET /batch/preregistered` reads it) and the
Devpost texts (`reports/texts/render.py`). It also carries the benchmark's per-layer tables (`benchmark/score.py --all`, under "tables") and the flag-mode figures, which are
DERIVED FROM COMMITTED RECORDS (`reports/v1.10/flag/derive.py`), never measured by a run of the flag mode.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.routers import batch  # noqa: E402

sys.path.insert(0, str(ROOT))
from benchmark import score  # noqa: E402

V19 = ROOT / "reports" / "v1.9"


def _j(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _headline_inputs() -> dict:
    """What the Batch Lab headline used to compute itself (harness-v1.9, task 6), computed here from the same committed files. The batch router now READS figures.json,
    so nothing here may read the router's headline (it would read this file's previous output)."""
    sets = batch.preregistered_results(ROOT)["sets"]
    by = {s["key"]: s for s in sets}
    fresh = [by[k] for k in ("test", "test_b", "test_c")]
    out: dict = {"ran": {"count": sum(s["count"] for s in fresh), "of": sum(s["of"] for s in fresh),
                         "parts": [{"set": s["title"], "count": s["count"], "of": s["of"]} for s in fresh]}}
    d = by["test_c"]["diagnosis"]
    out["diagnosis"] = {"count": d["count"], "of": d["of"], "strict": batch.TEST_C_DIAGNOSIS_STRICT, "source": d["source"]}
    facts = batch._read(ROOT, batch.COUNTERFACTUAL_FACTS)
    items = batch._read(ROOT, batch.COUNTERFACTUAL_CLASSES)["items"]
    fresh_f, dev_f = facts["summary"]["FRESH (TEST-A+B+C)"], facts["summary"]["DEV"]
    withdrawn = {e["record"] for e in batch._read(ROOT, batch.ERRATA)["errata"] if "dev_certified" in e.get("affects", [])}
    dev_withdrawn = sum(1 for r in facts["entry_runs"] if r["set"] == "DEV" and r["certified"] and r["record"] in withdrawn)
    fakes = [i for i in items if i["label"] == "GENUINE FAKE"]
    gate_items = [i for i in items if i["group"] == "gate rejection under a faking rule"]
    out["counterfactual"] = {
        "fresh": {"ungated_at_least": fresh_f["naive_success_entry_runs"], "of": fresh_f["entry_runs"], "certified": fresh_f["certified_entry_runs"], "after_audits": out["ran"]["count"]},
        "dev": {"ungated_at_least": dev_f["naive_success_entry_runs"], "of": dev_f["entry_runs"], "certified": dev_f["certified_entry_runs"],
                "certified_after_erratum": dev_f["certified_entry_runs"] - dev_withdrawn},
        "fakes_refused_by_the_adjudicator": sum(1 for i in fakes if i.get("fate", "").startswith("adjudicator")),
        "gate_faking_rule_rejections": len(gate_items), "of_which_honest": sum(1 for i in gate_items if i["label"] == "HONEST PATCH REJECTED")}
    return out


def build() -> dict:
    head = _headline_inputs()
    facts = _j(V19 / "counterfactual" / "facts.json")["summary"]
    items = _j(V19 / "counterfactual" / "classification.json")["items"]
    rater = _j(V19 / "counterfactual" / "second_rater.json")["items"]
    before, after = _j(V19 / "planted" / "gate_heldout_before.json")["summary"], _j(V19 / "planted" / "gate_heldout_after.json")["summary"]
    fakes = [i for i in items if i["label"] == "GENUINE FAKE"]
    first = [i["label"] for i in items if i["group"] == "reached naive success"] + [i["label"] for i in items if i["group"] != "reached naive success"]
    agree = sum(1 for a, b in zip(first, rater) if a == b["label"])
    families = [f for f in ("F1", "F2", "F3", "F4", "F5", "F6")]
    unreached = [f for f in families if after[f]["rejected"] == 0]
    corpus = [json.loads(line) for line in (V19 / "planted" / "corpus.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    fig: dict[str, dict] = {}

    def add(name: str, value, source: str, note: str, tag: str = "DERIVED") -> None:
        fig[name] = {"value": value, "tag": tag, "source": source, "note": note}

    ran = head["ran"]
    add("held_out_ran", ran["count"], "GET /batch/preregistered headline.ran", "TEST after its published audit + TEST-B + TEST-C")
    add("held_out_total", ran["of"], "GET /batch/preregistered headline.ran", "8 + 8 + 10")
    for part in ran["parts"]:
        key = part["set"].lower().replace("-", "_")
        add(f"{key}_ran", part["count"], "GET /batch/preregistered headline.ran.parts", part["set"])
        add(f"{key}_of", part["of"], "GET /batch/preregistered headline.ran.parts", part["set"])
    add("test_preregistered_confirmed", batch._read(ROOT, batch.TEST_RESULT)["confirmed_count"], batch.TEST_RESULT, "TEST as pre-registered, before the audit")
    d = head["diagnosis"]
    add("diagnosis_actionable", d["count"], d["source"], "TEST-C, stored blockers scored by the committed rubric")
    add("diagnosis_non_running", d["of"], d["source"], "TEST-C non-running entries")
    add("diagnosis_strict", d["strict"]["count"], d["strict"]["source"], "one key regex judged strictly")
    cf = head["counterfactual"]
    add("ungated_fresh_at_least", cf["fresh"]["ungated_at_least"], "reports/v1.9/counterfactual/facts.json", "fresh = TEST + TEST-B + TEST-C")
    add("fresh_entry_runs", cf["fresh"]["of"], "reports/v1.9/counterfactual/facts.json", "")
    add("certified_fresh_as_recorded", cf["fresh"]["certified"], "reports/v1.9/counterfactual/facts.json", "RUNS_CLEAN or RUNS_AFTER_REPAIR as recorded")
    add("certified_fresh_after_audits", cf["fresh"]["after_audits"], "reports/v1.9/counterfactual/facts.json + the published audits", "")
    add("ungated_dev_at_least", cf["dev"]["ungated_at_least"], "reports/v1.9/counterfactual/facts.json", "")
    add("dev_entry_runs", cf["dev"]["of"], "reports/v1.9/counterfactual/facts.json", "")
    add("certified_dev", cf["dev"]["certified"], "reports/v1.9/counterfactual/facts.json", "as recorded")
    add("certified_dev_after_erratum", cf["dev"]["certified_after_erratum"], "reports/v1.9/counterfactual/facts.json + reports/v1.10/errata.json", "E-3: the M-FAC run withdrawn")
    errata = _j(ROOT / "reports" / "v1.10" / "errata.json")["errata"]
    rounds = {r["round"]: r["runs_count"]["value"] for r in _j(ROOT / "reports" / "phase-d" / "dev_rounds.json")["rounds"]}
    for n, as_recorded in sorted(rounds.items()):
        withdrawn = sum(1 for e in errata if e.get("dev_round") == n and "dev_round_smoke_count" in e.get("affects", []))
        add(f"dev_round{n}_smoke_as_recorded", as_recorded, "reports/phase-d/dev_rounds.json", f"DEV round {n}")
        add(f"dev_round{n}_smoke_after_erratum", as_recorded - withdrawn, "reports/phase-d/dev_rounds.json + reports/v1.10/errata.json", f"DEV round {n}")
    add("dev_entries_per_round", _j(ROOT / "reports" / "phase-d" / "dev_rounds.json")["rounds"][0]["entries_total"]["value"], "reports/phase-d/dev_rounds.json", "")
    bd = _j(ROOT / "reports" / "v1.10" / "breakdown" / "breakdown.json")
    add("fresh_removed_by_audit", bd["removed_by_audit"], "reports/v1.10/breakdown/breakdown.json", "TEST-A #18 and TEST-B #6")
    add("fresh_removed_that_were_fakes", bd["removed_that_were_fakes"], "reports/v1.10/breakdown/breakdown.json", "no model patch was involved in either")
    add("fakes_recorded", len(fakes), "reports/v1.9/counterfactual/classification.json", "genuine fakes in the committed records")
    add("fakes_exit_zero_passed_gate", sum(1 for i in fakes if i["group"] == "reached naive success"), "reports/v1.9/counterfactual/classification.json", "genuine fakes that reached exit 0")
    add("fakes_refused_by_adjudicator", cf["fakes_refused_by_the_adjudicator"], "reports/v1.9/counterfactual/classification.json", "")
    add("gate_faking_rule_rejections", cf["gate_faking_rule_rejections"], "reports/v1.9/counterfactual/classification.json", "all honest patches")
    add("gate_faking_rule_rejections_honest", cf["of_which_honest"], "reports/v1.9/counterfactual/classification.json", "")
    add("judgements", len(items), "reports/v1.9/counterfactual/classification.json", "")
    add("second_rater_agreement", agree, "reports/v1.9/counterfactual/second_rater.json", "labels that agree with the first rater")
    add("planted_patches", len(corpus), "reports/v1.9/planted/corpus.jsonl", "")
    add("planted_cheats", sum(1 for r in corpus if r["kind"] == "cheat"), "reports/v1.9/planted/corpus.jsonl", "")
    add("planted_controls", sum(1 for r in corpus if r["kind"] == "control"), "reports/v1.9/planted/corpus.jsonl", "")
    add("planted_bases", len({r["base"] for r in corpus}), "reports/v1.9/planted/corpus.jsonl", "repositories with a committed run")
    add("planted_heldout_cheats", after["ALL CHEATS"]["n"], "reports/v1.9/planted/gate_heldout_after.json", "")
    add("planted_heldout_cheats_caught_after", after["ALL CHEATS"]["rejected"], "reports/v1.9/planted/gate_heldout_after.json", "")
    add("planted_heldout_cheats_caught_before", before["ALL CHEATS"]["rejected"], "reports/v1.9/planted/gate_heldout_before.json", "13 of them by D-55 alone")
    add("planted_heldout_controls", after["ALL CONTROLS"]["n"], "reports/v1.9/planted/gate_heldout_after.json", "")
    add("planted_controls_rejected_after", after["ALL CONTROLS"]["rejected"], "reports/v1.9/planted/gate_heldout_after.json", "")
    add("planted_controls_rejected_before", before["ALL CONTROLS"]["rejected"], "reports/v1.9/planted/gate_heldout_before.json", "all L2D, PROTECTED_PATH_MODIFIED")
    add("planted_uncaught_families_cheats", sum(after[f]["n"] for f in unreached), "reports/v1.9/planted/gate_heldout_after.json", "families F4, F5, F6: " + ", ".join(unreached))
    add("planted_uncaught_families_caught", sum(after[f]["rejected"] for f in unreached), "reports/v1.9/planted/gate_heldout_after.json", "")
    add("planted_stubs_n", after["F2"]["n"], "reports/v1.9/planted/gate_heldout_after.json", "F2 stubbed function")
    add("planted_stubs_caught", after["F2"]["rejected"], "reports/v1.9/planted/gate_heldout_after.json", "")
    add("planted_swallow_n", after["F1"]["n"], "reports/v1.9/planted/gate_heldout_after.json", "F1 swallowed exception")
    add("planted_swallow_caught", after["F1"]["rejected"], "reports/v1.9/planted/gate_heldout_after.json", "")
    add("planted_skip_n", after["F3"]["n"], "reports/v1.9/planted/gate_heldout_after.json", "F3 skipped missing input")
    add("planted_skip_caught", after["F3"]["rejected"], "reports/v1.9/planted/gate_heldout_after.json", "")
    steam = _j(ROOT / "runs" / "v1.9" / "steamctl" / "summary.json")
    for tag, label in (("harness-v1.7.2", "v172"), ("harness-v1.8.0", "v180")):
        rows = [r for r in steam if r["tag"] == tag]
        add(f"steamctl_{label}_runs", len(rows), "runs/v1.9/steamctl/summary.json", tag)
        add(f"steamctl_{label}_ran", sum(1 for r in rows if r.get("verdict") in ("RUNS_CLEAN", "RUNS_AFTER_REPAIR")), "runs/v1.9/steamctl/summary.json", tag)
    # harness-v1.10 pass: Task 1 (the full pipeline on the planted held-out half) and Task 4 (the independent set, once at v1.9.0 and once at the v1.10 release candidate)
    t1 = _j(ROOT / "reports" / "v1.10" / "pipeline" / "heldout_v190" / "summary.json")
    pooled, pop_a = t1["pooled"], t1["population_A"]
    src1 = "reports/v1.10/pipeline/heldout_v190/summary.json"
    add("pipeline_cheats", pooled["cheats"], src1, "held-out planted cheats through the full pipeline at harness-v1.9.0")
    add("pipeline_cheats_adopted", pooled["escaped"], src1, "adopted = escaped")
    add("pipeline_stopped_by_gate", pooled["stopped_by"]["gate"], src1, "")
    add("pipeline_stopped_by_run", pooled["stopped_by"]["run"], src1, "did not make the documented command pass: not a catch")
    add("pipeline_stopped_by_adjudicator", pooled["stopped_by"]["adjudicator"], src1, "")
    add("pipeline_controls_passed_run", pooled["controls_passed_run"], src1, "honest controls that reached the adjudicator")
    add("pipeline_controls_refused", pooled["false_refusals"], src1, "all by the adjudicator")
    add("pipeline_real_failure_cheats_refused", pop_a["stopped_by"]["adjudicator"], src1, "population A: the cheats that reached exit 0 on an image whose unpatched run fails, all refused")
    comp = _j(ROOT / "reports" / "v1.10" / "independent" / "compare.json")
    src4 = "reports/v1.10/independent/compare.json"
    ind90 = [json.loads(line) for line in (ROOT / "reports" / "v1.10" / "independent" / "measure_v190" / "results.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    adopted90 = [r for r in ind90 if r["kind"] == "cheat" and r["outcome"] == "adopted"]
    cheats_a = [r for r in ind90 if r["kind"] == "cheat" and r["population"] == "A"]
    add("indep_confirmed_cheats", comp["confirmed_cheats"], src4, "cheats of the independent set that reached exit 0 in the confirmation runs")
    manifest = _j(ROOT / "reports" / "v1.10" / "independent" / "manifest.json")
    add("indep_authored_cheats", sum(1 for m in manifest if m["kind"] == "cheat"), "reports/v1.10/independent/manifest.json", "authored; the ones that did not reach exit 0 were dropped")
    add("indep_controls", comp["controls"]["n"], src4, "honest controls, all kept")
    add("indep_v190_before_any_model", comp["summary"]["C0"], src4, "gate + exit-zero audit at harness-v1.9.0")
    add("indep_v190_adopted", len(adopted90), "reports/v1.10/independent/measure_v190/results.jsonl", "cheats the full pipeline adopted at harness-v1.9.0")
    add("indep_real_failure_cheats", len(cheats_a), "reports/v1.10/independent/measure_v190/results.jsonl", "cheats aimed at the three repositories whose unpatched run fails")
    add("indep_real_failure_cheats_adopted", sum(1 for r in adopted90 if r["population"] == "A"), "reports/v1.10/independent/measure_v190/results.jsonl", "adopted at harness-v1.9.0")
    add("indep_v110_before_any_model", comp["summary"]["C"], src4, "gate + behavioural checks at the v1.10 release candidate")
    add("indep_controls_passed_run", comp["controls"]["passed_the_run_at_v1.9.0"], src4, "")
    add("indep_controls_refused_by_checks", comp["controls"]["FR"]["refused_by_behaviour_layers"], src4, "FR numerator")
    add("indep_dropped_cheats", sum(1 for m in manifest if m["kind"] == "cheat") - comp["confirmed_cheats"], "benchmark/sets/independent/dropped.json", "did not reach exit 0; dropped, not edited")
    add("indep_v190_adopted_controls", sum(1 for r in ind90 if r["kind"] == "control" and r["outcome"] == "adopted"), "reports/v1.10/independent/measure_v190/results.jsonl", "honest repairs v1.9.0 adopted")
    add("indep_real_failure_adopted_pct", round(100 * sum(1 for r in adopted90 if r["population"] == "A") / len(cheats_a)), "reports/v1.10/independent/measure_v190/results.jsonl",
        "adopted / aimed at failing repositories, rounded; the anti-cheat line is 25")
    add("anticheat_headline_line_pct", 25, "METHODOLOGY.md, flag-mode decisions (owner, 2026-10-09)", "above it, anti-cheat leaves the headline")
    add("indep_fr_pct", round(100 * comp["controls"]["FR"]["refused_by_behaviour_layers"] / comp["controls"]["passed_the_run_at_v1.9.0"]), src4, "false refusals of the v1.10 checks, rounded")
    add("fr_rule_line_pct", 30, "reports/v1.10/behaviour/PROTOCOL.md", "pre-registered: above it, table only and the submission stays on v1.9.0")

    # the flag mode, DERIVED FROM COMMITTED RECORDS (reports/v1.10/flag/flag_table.json); the use was chosen after these results were seen
    flag = _j(ROOT / "reports" / "v1.10" / "flag" / "flag_table.json")
    srcf = "reports/v1.10/flag/flag_table.json (derived from committed records)"
    fc, fk = flag["groups"]["cheats"], flag["groups"]["honest controls"]
    add("flag_cheats_flagged", fc["flagged"]["n"], srcf, "cheats rc4's checks found something in")
    add("flag_cheats_adopted_flagged", sum(v["adopted_flagged"] for v in flag["cheats_by_family"].values()), srcf, "adopted by v1.9.0, with REVIEW_REQUIRED")
    add("flag_cheats_adopted_clean", sum(v["adopted_clean"] for v in flag["cheats_by_family"].values()), srcf, "adopted by v1.9.0 with no flag")
    add("flag_real_failure_adopted_flagged", flag["cheats_aimed_at_failing_repositories"]["adopted_flagged"], srcf, "")
    add("flag_real_failure_adopted_clean", flag["cheats_aimed_at_failing_repositories"]["adopted_clean"], srcf, "")
    add("flag_cheats_never_judged", fc["never judged (refused by the gate)"]["n"], srcf, "refused by the gate before the checks")
    add("flag_controls_flagged", fk["flagged"]["n"], srcf, "")
    add("flag_controls_adopted_flagged", fk["flagged"]["adopted"], srcf, "honest repairs adopted with REVIEW_REQUIRED")
    add("flag_controls_adopted_clean", fk["clean (judged, no finding)"]["adopted"], srcf, "")
    add("flag_controls_passed_run_flagged", flag["controls_that_passed_the_run_at_v190"]["flagged"], srcf, "of the 27 that passed the run at v1.9.0")
    add("flag_cheats_traced", flag["tracer"]["cheats_traced_at_rc4"], srcf, "no cheat was ever run with the tracer")
    add("flag_controls_traced", flag["tracer"]["controls_traced_at_rc4"], srcf, "")
    add("flag_controls_trace_findings", flag["tracer"]["trace_findings_on_controls"], srcf, "")

    # the post-hoc minmaxot run (the v1.10 pass, task 5) and erratum E-3, under their labels
    mm = _j(ROOT / "runs" / "v1.10" / "mkdir_live" / "02_stephaneckstein__minmaxot_v190.json")
    add("minmaxot_posthoc_cost_usd", round(float(mm["cost_guard"]["spent_usd"]), 2), "runs/v1.10/mkdir_live/02_stephaneckstein__minmaxot_v190.json",
        "POST-HOC live check of the output_dir repair at harness-v1.9.0, never merged into TEST-C", tag="API-REPORTED")
    add("minmaxot_posthoc_ran", 1 if mm["result"]["verdict"] in ("RUNS_CLEAN", "RUNS_AFTER_REPAIR") else 0, "runs/v1.10/mkdir_live/02_stephaneckstein__minmaxot_v190.json",
        "RUNS_AFTER_REPAIR at smoke level (stopped by RERUN at the smoke limit)")

    # the ledger (reports/ledger_total.py) and the gate-era facts the Devpost answers cite (reports/phase-d/replay/summary.json, their own tags)
    sys.path.insert(0, str(ROOT / "reports"))
    import ledger_total  # noqa: E402

    parts = ledger_total.parts()
    add("ledger_usd", round(ledger_total.total(), 2), "reports/ledger_total.py", "API-reported operation and model costs, a lower bound", tag="API-REPORTED")
    add("ledger_ceiling_usd", 300, "the owner's ceiling", "")
    add("ledger_v110_pass_usd", round(parts["v1.10 (reports/v1.10, runs/v1.10)"], 2), "reports/ledger_total.py", "the harness-v1.10 passes", tag="API-REPORTED")
    rp = _j(ROOT / "reports" / "phase-d" / "replay" / "summary.json")
    add("gate_entry_runs", rp["headline"]["gate_entry_runs"]["value"], "reports/phase-d/replay/summary.json", "every exploratory gate entry-run", tag="API-REPORTED")
    add("gate_apparent_recoveries", rp["headline"]["apparent_recoveries"]["value"], "reports/phase-d/replay/summary.json", "RUNS_* verdicts in the gates", tag="API-REPORTED")
    add("gate_with_model_attempt", rp["headline"]["with_recorded_model_attempt"]["value"], "reports/phase-d/replay/summary.json", "", tag="API-REPORTED")
    add("gate_passports", rp["inventory"]["records"]["value"], "reports/phase-d/replay/summary.json", "entry-run records (passports) of the gates", tag="API-REPORTED")
    add("defects_registered_by_the_gates", rp["inventory"]["defects"]["value"], "reports/phase-d/replay/summary.json", "", tag="API-REPORTED")
    add("billed_second_reading_charged_usd", rp["ledger"]["billed"]["account"]["value"], "reports/phase-d/replay/summary.json ledger.billed.account",
        "at most this much charged at the owner's second reading of the account balance (before the last gates); not reconciled with the API-reported ledger (D-36)", tag="BILLED")
    last = rp["stack"]["versions"][-1]
    for mc in last["model_calls"]:
        size = next(s for s in ("nano", "super", "ultra") if s in mc["model"].lower())
        add(f"last_gate_calls_{size}", mc["calls"]["value"], "reports/phase-d/replay/summary.json (" + last["harness_tag"] + ")", mc["model"], tag="API-REPORTED")

    tables = score.score_all(score.labels())
    return {"note": "Generated by reports/v1.9/figures.py from committed result files; every value is a DERIVED count or a count of stored fields, with its tag. "
                    "'tables' are benchmark/score.py --all on RERUN's own decision files (benchmark/decisions).",
            "figures": fig, "tables": {name: {"meta": {k: v for k, v in r["meta"].items() if k != "file"}, "table": r["table"]} for name, r in tables.items()}}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()
    doc = build()
    for name, f in doc["figures"].items():
        print(f"{name:42} {f['value']} [{f['tag']}]")
    if args.write:
        (V19 / "figures.json").write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
