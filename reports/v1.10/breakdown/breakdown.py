"""harness-v1.10 pass, task 6: the counterfactual's "5 as recorded, 3 after audits": what removed the two, and whether they were fakes. Records only, zero spend.

    backend/.venv/Scripts/python.exe reports/v1.10/breakdown/breakdown.py [--write]

For each fresh entry-run (TEST-A, TEST-B, TEST-C) that an ungated agent (exit code 0 accepted) would have reported as reproduced: the verdict as recorded, what produced the exit 0 (the
as-published command, a deterministic step, or a model patch), whether any model patch was involved, the published audit that struck it (if any), and, post-hoc and labelled, what the
harness-v1.8 DEV re-run of the same entry says. Reads reports/v1.9/counterfactual/facts.json and the committed records.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
DEV_V18 = {("TEST-A", "18"): "runs/dev_v18/round1/TEST/18_aam-at__adversary_critic.json", ("TEST-A", "10"): "runs/dev_v18/round1/TEST/10_alevine0__patchSmoothing.json",
           ("TEST-B", "04"): "runs/dev_v18/round1/TEST-B/04_zcajiayin__L2D.json", ("TEST-B", "06"): "runs/dev_v18/round1/TEST-B/06_galsang__trees_from_transformers.json"}


def build() -> dict:
    facts = json.loads((ROOT / "reports/v1.9/counterfactual/facts.json").read_text(encoding="utf-8"))["entry_runs"]
    rows = []
    for r in facts:
        if r["set"] not in ("TEST-A", "TEST-B", "TEST-C") or not r["naive_success"]:
            continue
        rec = json.loads((ROOT / r["record"]).read_text(encoding="utf-8"))
        base = rec["certificate"]["baseline"]
        execs = r["naive_executions"]
        patch_runs = [n for n in execs if n["patch"]]
        by = ("the as-published command" if any(n["execution"].startswith("baseline") for n in execs)
              else "a model patch" if patch_runs
              else "a deterministic step (no model proposal)")
        post_hoc = None
        key = (r["set"], r["entry"])
        if key in DEV_V18:
            v18 = json.loads((ROOT / DEV_V18[key]).read_text(encoding="utf-8"))["result"]
            post_hoc = {"record": DEV_V18[key], "verdict": v18["verdict"], "taxonomy_code": v18.get("taxonomy_code")}
        rows.append({"set": r["set"], "entry": r["entry"], "name": r["name"], "verdict_as_recorded": r["verdict"], "certified_as_recorded": r["certified"],
                     "documented_command": base["execute_command"], "baseline_exit_code": base["exit_code"], "exit_zero_came_from": by,
                     "model_patch_involved": bool(patch_runs), "published_audit": r["published_audit"], "removed_by_audit": r["published_audit"] is not None,
                     "was_a_fake": bool(patch_runs) and r["published_audit"] is None and not r["certified"], "post_hoc_v18_rerun": post_hoc})
    cert = [x for x in rows if x["certified_as_recorded"]]
    return {"rows": rows, "ungated_at_least": len(rows), "certified_as_recorded": len(cert), "removed_by_audit": sum(1 for x in cert if x["removed_by_audit"]),
            "certified_after_audits": sum(1 for x in cert if not x["removed_by_audit"]),
            "removed_that_were_fakes": sum(1 for x in cert if x["removed_by_audit"] and x["model_patch_involved"]),
            "ungated_but_not_certified": [x["name"] for x in rows if not x["certified_as_recorded"]]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()
    doc = build()
    for x in doc["rows"]:
        print(f"{x['set']:7} #{x['entry']} {x['name'][:34]:34} {x['verdict_as_recorded']:18} exit 0 from {x['exit_zero_came_from']:42} patch={x['model_patch_involved']!s:5} audit={x['published_audit']}")
    print({k: v for k, v in doc.items() if k != "rows"})
    if args.write:
        (HERE / "breakdown.json").write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
