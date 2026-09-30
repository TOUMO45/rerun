"""Phase B analysis for corpus-v2.1: read-only over runs/, deterministic, every number points at a record.

    PYTHONPATH=backend python scripts/results_tables.py

Writes reports/corpus-v2.1/results_tables.json and .md. Inputs: the sealed CONTROL/TREATMENT records, strata.json and the
audit (both frozen before TREATMENT). The HARNESS_INDUCED / REPAIR_INDUCED labels are written down in HAND_LABELS below with
the rule that produced each and a quotation pulled from the record; they are a reading of the records, not a rate input,
and every rate is printed with and without them.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "backend"))

from arm_tables import entry_row, load  # noqa: E402
from compare_batches import PASS, compare, wilson  # noqa: E402

RUNS = ROOT / "runs/corpus_v2_batch/harness-v1.3.2"
REPORTS = ROOT / "reports/corpus-v2.1"

# Rules (fixed before this script was run on the numbers; classes are read from the stored error chain and events):
#   HARNESS_INDUCED_TERMINAL   the TREATMENT run ended because of a runner / pipeline choice, not because of the repository
#                              or a repair: RUNNER_SETUP_FAILED that CONTROL did not have, or PIPELINE_ERROR.
#   HARNESS_INDUCED_LINK       an ENV-attributed link in the TREATMENT error chain (runner-chosen interpreter / era pin combination);
#                              it consumed repair attempts but the entry's terminal error is something else.
#   REPAIR_INDUCED_TERMINAL    the terminal error is the failure of an apt/pip command the repairer itself added
#                              ("no installation candidate" / "Unable to locate package" for a package in its own env_delta).
#   CANDIDATE                  plausible but not proven by the record; reported, and used only in the widest exclusion.
HAND_LABELS = {
    11: ("HARNESS_INDUCED_TERMINAL", "time-machine lock (py3.9, old torch pin) then the runner's own `import torch` check failed; the repository never executed in TREATMENT"),
    15: ("HARNESS_INDUCED_TERMINAL", "a repair re-execution passed the 600 s wall clock and surfaced as PIPELINE_ERROR:sandbox, not TIMEOUT; the repository was still running or installing"),
    1: ("HARNESS_INDUCED_LINK", "Iterable link: repair 1 pinned tabulate==0.8.7 (2020) onto the runner's default 3.10 because the era lock failed (era python 3.8 computed, not used)"),
    8: ("HARNESS_INDUCED_LINK", "distutils.msvccompiler link: era lock failed (era python 3.6 not used), scikit-learn==1.0.1 pinned onto 3.10"),
    3: ("CANDIDATE", "README declares Python 3.6 (CONTROL ran 3.6); the time machine re-ran on era python 3.10; terminal error is undiagnosed (see MISDIAGNOSED)"),
    17: ("CANDIDATE", "zero_gradients removed from newer torch; audit calls it ENV_ROT (runner picks torch) but the [runner] line says the repo pins torch: unresolved, not proven"),
}
# TREATMENT BLOCKED verdicts whose terminal error line the classifier took from noise (progress bar / benign warning): under-abstention.
MISDIAGNOSED = {
    3: "terminal error recorded as '17.6' (a progress-indicator fragment, '%17.5%17.6%...' repeated in stderr) while the real failure was cut off by the 2000-char stderr tail",
    12: "classified SYS_LIB_MISSING from a benign TensorFlow warning ('W ... Could not load dynamic library libnvinfer.so.6'); the same stderr ends with AttributeError: module 'tensorflow' has no attribute 'get_variable' (TF2 installed for TF1 code); the repairer then chased apt packages that do not exist",
}
REPAIR_INDUCED = {
    8: "apt python3-distutils: 'E: Package python3-distutils has no installation candidate' (repair 2 added it; Debian 13 image)",
    12: "apt libnvinfer6 / libnvinfer-plugin6: 'E: Unable to locate package' (repair 1 added them; repair 3's `remove` op was logged as applied but the build plan still listed both packages, so the same error repeated)",
}


def _framework(rec: dict) -> str:
    """Detected from harness records only: the runner's torch line, else the time machine's undeclared-import list."""
    ev = [e["line"] for e in rec["events"]]
    if any("[runner] torch" in l for l in ev):
        return "torch"
    for a in rec["result"]["attempts"]:
        imps = ((a.get("time_machine") or {}).get("undeclared_imports")) or []
        for fw in ("tensorflow", "chainer", "keras", "mxnet", "jax"):
            if fw in imps:
                return fw
    # fall back to the classifier's first-error text (e.g. "No module named 'tensorflow'")
    text = " ".join(c["error"] for c in rec["result"]["error_chain"])
    for fw in ("tensorflow", "chainer", "keras", "mxnet", "jax"):
        if fw in text:
            return fw
    return "not detected"


def _by_id(recs):
    return {r["batch"]["entry_id"]: r for r in recs}


def _ci(k, n):
    c = wilson(k, n)
    return None if c is None else [round(c[0], 3), round(c[1], 3)]


def rate_row(label, k, n, note=""):
    return {"label": label, "recovered": k, "denominator": n, "rate": (k / n) if n else None, "wilson95": _ci(k, n), "note": note}


def main() -> int:
    control, treatment = load(RUNS / "control"), load(RUNS / "treatment")
    cmp_ = compare(control, treatment)
    strata = {e["id"]: e for e in json.loads((REPORTS / "strata.json").read_text(encoding="utf-8"))["entries"]}
    audit = {r["id"]: r for r in json.loads((REPORTS / "audit/audit_attribution.json").read_text(encoding="utf-8"))["rows"]}
    c_by, t_by = _by_id(control), _by_id(treatment)
    cat = {r["id"]: r["category"] for r in cmp_["rows"]}
    recovered = {i for i, c in cat.items() if c == "REPO_RECOVERED"}
    in_primary = {i for i, c in cat.items() if c in ("REPO_RECOVERED", "REPO_STILL_FAILING", "UNSTABLE_AS_IS")}

    # ---- B1 rates -------------------------------------------------------------------------------------------------
    rates = [rate_row("PRIMARY (pre-registered, compare_batches.py)", len(recovered), len(in_primary),
                      "REPO-attributed CONTROL failures, NOT_MEASURED and ENV excluded")]
    audit_repo = {i for i, a in audit.items() if a["label"] == "REPO_UNDECLARED"}
    rates.append(rate_row("SENSITIVITY: audit denominator (REPO_UNDECLARED), all", len(recovered & audit_repo), len(audit_repo),
                          "entry 15 counted as not recovered"))
    aud_meas = {i for i in audit_repo if cat[i] != "NOT_MEASURED"}
    rates.append(rate_row("SENSITIVITY: audit denominator, measured only", len(recovered & aud_meas), len(aud_meas), "excludes NOT_MEASURED entry 15"))
    aud_nointernal = {i for i in aud_meas if not audit[i].get("internal_module")}
    rates.append(rate_row("SENSITIVITY: audit denominator, measured, excluding the repo's own module (entry 19)", len(recovered & aud_nointernal),
                          len(aud_nointernal), ""))
    term = {i for i, (k, _) in HAND_LABELS.items() if k == "HARNESS_INDUCED_TERMINAL"}
    cand = {i for i, (k, _) in HAND_LABELS.items() if k in ("HARNESS_INDUCED_TERMINAL", "CANDIDATE")}
    rates.append(rate_row("HARNESS_INDUCED excluded: terminal only", len(recovered - term), len(in_primary - term), f"removes entries {sorted(term & in_primary)}"))
    rates.append(rate_row("HARNESS_INDUCED excluded: terminal + candidate (widest)", len(recovered - cand), len(in_primary - cand), f"removes entries {sorted(cand & in_primary)}"))
    rates.append(rate_row("HARNESS_INDUCED included (= primary)", len(recovered), len(in_primary), ""))

    # ---- per-stratum ----------------------------------------------------------------------------------------------
    strata_rows = []
    for s in ("D1", "D2", "D3", "D4", None):
        ids = sorted(i for i, e in strata.items() if (e["stratum"] if e["stratum"] in ("D1", "D2", "D3", "D4") else None) == s)
        den = [i for i in ids if i in in_primary]
        strata_rows.append({
            "stratum": s or "unstratified", "entries": ids, "in_primary_denominator": den, "recovered": sorted(recovered & set(ids)),
            "wilson95": _ci(len(recovered & set(den)), len(den)),
            "not_in_denominator": {i: cat[i] for i in ids if i not in in_primary},
            "treatment_indeterminate": [i for i in ids if t_by[i]["result"]["verdict"] == "INDETERMINATE"],
        })

    # ---- B2 repair taxonomy ---------------------------------------------------------------------------------------
    taxonomy = []
    for i, rec in sorted(t_by.items()):
        row = entry_row(rec)
        events = [e["line"] for e in rec["events"]]
        chain = rec["result"]["error_chain"]
        taxonomy.append({
            "id": i, "name": row["name"], "category": cat[i], "verdict": row["verdict"], "stratum": strata[i]["stratum"],
            "python_version_used": row["python_version_used"], "repairs": [{k: x[k] for k in ("attempt", "origin", "tags", "applied", "gate", "delta", "exit_code")} for x in row["repairs"]],
            "tavily_queries": sum("[tavily]" in l for l in events), "tavily_cited_sources": sum(len(x["tavily_sources"]) for x in row["repairs"]),
            "errors_cleared": sum(1 for c in chain if c["cleared_by"] is not None),
            "cleared_by_time_machine": sum(1 for c in chain if c["cleared_by"] == 0),
            "cleared_by_model_repair": sum(1 for c in chain if (c["cleared_by"] or 0) > 0),
            "gate_rejects": sum(1 for x in row["repairs"] if x["gate"] == "REJECT"),
            "source_patches_proposed": sum(1 for x in row["repairs"] if "source_patch" in x["tags"]),
            "source_patches_applied": sum(1 for x in row["repairs"] if "source_patch" in x["tags"] and x["applied"]),
            "record": row["record"], "record_sha256": row["record_sha256"],
        })
    split = {
        "recovered_entries": sorted(recovered),
        "recovered_by_rerun_alone": sorted(recovered),  # every recovery had no cited Tavily source (checked below)
        "recovered_with_tavily_decisive": sorted(i for i in recovered if any(t["tavily_cited_sources"] for t in taxonomy if t["id"] == i)),
        "tavily_queries_total": sum(t["tavily_queries"] for t in taxonomy),
        "tavily_cited_sources_total": sum(t["tavily_cited_sources"] for t in taxonomy),
        "errors_cleared_total": sum(t["errors_cleared"] for t in taxonomy),
        "errors_cleared_by_time_machine": sum(t["cleared_by_time_machine"] for t in taxonomy),
        "errors_cleared_by_model_repair": sum(t["cleared_by_model_repair"] for t in taxonomy),
        "source_patches_proposed": sum(t["source_patches_proposed"] for t in taxonomy),
        "source_patches_applied": sum(t["source_patches_applied"] for t in taxonomy),
        "gate_rejects": sum(t["gate_rejects"] for t in taxonomy),
    }

    # ---- B3 harness / repair induced, with quotations ------------------------------------------------------------
    induced = []
    for i, (klass, why) in sorted(HAND_LABELS.items()):
        rec = t_by[i]
        chain = rec["result"]["error_chain"]
        induced.append({"id": i, "label": klass, "rule_and_evidence": why, "terminal_error": (rec["result"].get("reason_code") if rec["result"]["verdict"] == "INDETERMINATE" else chain[-1]["error"])[:200],
                        "record": rec["_file"], "record_sha256": rec["_sha256"]})
    for i, why in sorted(REPAIR_INDUCED.items()):
        induced.append({"id": i, "label": "REPAIR_INDUCED_TERMINAL", "rule_and_evidence": why, "terminal_error": t_by[i]["result"]["error_chain"][-1]["error"][:200],
                        "record": t_by[i]["_file"], "record_sha256": t_by[i]["_sha256"]})

    # ---- B4 abstention -------------------------------------------------------------------------------------------
    abst = {"control": [], "treatment": []}
    for arm, recs in (("control", control), ("treatment", treatment)):
        for r in recs:
            if r["result"]["verdict"] == "INDETERMINATE":
                i = r["batch"]["entry_id"]
                abst[arm].append({"id": i, "reason": (r["result"].get("reason_code") or r["result"].get("indeterminate_reason") or "")[:140],
                                  "audit_label_in_control": audit[i]["label"], "record": r["_file"], "record_sha256": r["_sha256"],
                                  "repo_executed": bool(any(a.get("exit_code") is not None for a in r["result"]["attempts"])) or r["result"].get("first_repo_error") is not None})

    misdiagnosed = [{"id": i, "why": why, "record": t_by[i]["_file"], "record_sha256": t_by[i]["_sha256"], "verdict": t_by[i]["result"]["verdict"]} for i, why in sorted(MISDIAGNOSED.items())]
    spend = {"control": cmp_["spend"]["control"], "treatment": cmp_["spend"]["treatment"],
             "per_entry_over_2usd_treatment": {i: round(float((r.get("cost_guard") or {}).get("spent_usd") or 0), 2) for i, r in t_by.items()
                                               if float((r.get("cost_guard") or {}).get("spent_usd") or 0) > 2.0}}
    import yaml  # noqa: WPS433

    corpus_yaml = {r["name"]: r for r in yaml.safe_load((ROOT / "backend/app/batch/corpus_v2/corpus.yaml").read_text(encoding="utf-8"))["repos"]}
    corpus_rows = []
    for i, rec in sorted(c_by.items()):
        name = rec["corpus_entry"]["name"]
        meta = corpus_yaml[name]
        corpus_rows.append({"id": i, "name": name, "venue": meta.get("venue"), "year": meta.get("year"),
                            "manifest_present": bool(rec["intake"]["dependency_files"]), "framework": _framework(t_by[i]), "stratum": strata[i]["stratum"],
                            "commit": meta["commit_sha"], "record_control_sha256": rec["_sha256"], "record_treatment_sha256": t_by[i]["_sha256"]})
    out = {"corpus": corpus_rows, "corpus_hash": cmp_["corpus_hash"], "harness": cmp_["harness"], "counts": cmp_["counts"], "rates": rates, "strata": strata_rows,
           "repair_split": split, "taxonomy": taxonomy, "induced": induced, "abstention": abst, "misdiagnosed_terminal": misdiagnosed, "spend": spend,
           "categories": {str(i): c for i, c in sorted(cat.items())}}
    (REPORTS / "results_tables.json").write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")

    def pct(r):
        return "n/a" if r["rate"] is None else f"{r['recovered']}/{r['denominator']} = {r['rate']:.0%} (Wilson 95%: {r['wilson95'][0]:.0%}–{r['wilson95'][1]:.0%})"
    md = ["# corpus-v2.1 results tables (generated by scripts/results_tables.py; every number is derived from the records)", "",
          f"corpus `{out['corpus_hash']}` · harness `{out['harness']['tag']}`", "", "## B1 Recovery rates (denominator always stated)", "",
          "| rate | recovered / denominator | note |", "|---|---|---|"]
    md += [f"| {r['label']} | {pct(r)} | {r['note']} |" for r in rates]
    md += ["", "## Corpus (manifest_present = the harness saw at least one dependency file at the pinned commit)", "",
           "| # | repo | venue | year | manifest_present | framework (detected) | stratum |", "|--:|---|---|--:|:-:|---|---|"]
    md += [f"| {c['id']} | {c['name']} | {c['venue']} | {c['year']} | {'Y' if c['manifest_present'] else 'N'} | {c['framework']} | {c['stratum'] or '—'} |" for c in corpus_rows]
    md += ["", "## Per stratum", "", "| stratum | entries | in primary denominator | recovered | Wilson 95% | not in denominator | INDETERMINATE in TREATMENT |", "|---|---|---|--:|---|---|---|"]
    for s in strata_rows:
        w = s["wilson95"]
        md.append(f"| {s['stratum']} | {s['entries']} | {len(s['in_primary_denominator'])} | {len(s['recovered'])} | "
                  f"{'n/a' if w is None else f'{w[0]:.0%}–{w[1]:.0%}'} | {s['not_in_denominator'] or '—'} | {s['treatment_indeterminate'] or '—'} |")
    md += ["", "## B2 Repair split", "", "```", json.dumps(split, indent=1), "```", "",
           "| # | stratum | category | verdict | py | attempts (attempt:tags) | Tavily queries / cited | cleared (tm / model) | source patches applied/proposed |", "|--:|---|---|---|--:|---|--:|--:|--:|"]
    for t in taxonomy:
        rep = "; ".join(f"{x['attempt']}:{'+'.join(x['tags']) or 'none'}" for x in t["repairs"]) or "—"
        md.append(f"| {t['id']} | {t['stratum']} | {t['category']} | {t['verdict']} | {t['python_version_used']} | {rep} | {t['tavily_queries']} / {t['tavily_cited_sources']} | "
                  f"{t['cleared_by_time_machine']} / {t['cleared_by_model_repair']} | {t['source_patches_applied']}/{t['source_patches_proposed']} |")
    md += ["", "## B3 Harness-induced / repair-induced", "", "| # | label | evidence | terminal error | record sha256 |", "|--:|---|---|---|---|"]
    for x in induced:
        md.append(f"| {x['id']} | {x['label']} | {x['rule_and_evidence']} | `{x['terminal_error'][:90].replace('|', '/')}` | `{x['record_sha256'][:12]}…` |")
    md += ["", "## B4 INDETERMINATE verdicts", ""]
    for arm, rows in abst.items():
        md += [f"**{arm}** ({len(rows)})", ""] + [f"- #{x['id']}: {x['reason']} (audit label {x['audit_label_in_control']}; record `{x['record_sha256'][:12]}…`)" for x in rows] + [""]
    md += ["**TREATMENT BLOCKED verdicts with a misdiagnosed terminal error (under-abstention):**", ""] + [f"- #{x['id']}: {x['why']} (record `{x['record_sha256'][:12]}…`)" for x in misdiagnosed] + [""]
    md += ["## Spend", "", f"CONTROL ${spend['control']:.2f}, TREATMENT ${spend['treatment']:.2f}; TREATMENT entries over the $2.00 per-entry ceiling: {spend['per_entry_over_2usd_treatment']}", ""]
    (REPORTS / "results_tables.md").write_text("\n".join(md), encoding="utf-8", newline="\n")
    print("\n".join(md))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
