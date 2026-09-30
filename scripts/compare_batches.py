"""Compare the two arms of the corpus-v2.1 ablation and write a report a judge can re-derive.

    PYTHONPATH=backend python scripts/compare_batches.py \
        --control runs/corpus_v2_batch/harness-v1.3/control \
        --treatment runs/corpus_v2_batch/harness-v1.3/treatment \
        --out reports/comparison-control-vs-treatment.md

Same corpus (hash checked), same sealed harness tag (checked); the arms differ only in `repair_enabled`
(CONTROL: no time machine, no repair loop, no Tavily = the repo as-is in the fixed runner; TREATMENT: full RERUN,
tamper gate on). Runner-level fixes (torch, Python policy, sandbox limits) are shared by both arms, so they cannot
inflate the number.

Every entry lands in exactly ONE category; the categories are never merged:

  CONTROL_PASS          the repo ran as-is in the control arm (not in the denominator). If the treatment arm did NOT
                        pass it, that is a REGRESSION (a stop condition; exit code 2).
  REPO_RECOVERED        control failed with a REPO-attributed error, treatment ended RUNS_AFTER_REPAIR  -> numerator
  REPO_STILL_FAILING    control failed with a REPO-attributed error, treatment did not pass             -> denominator only
  UNSTABLE_AS_IS        control failed with a REPO-attributed error but treatment ended RUNS_CLEAN, i.e. the as-is run
                        passed without any repair (non-determinism); in the denominator, never in the numerator
  ENV_ONLY              control failed and no link of its error chain is REPO (runner-side ENV): reported separately,
                        excluded from the rate; `passes in treatment` is shown but is not a repo-fix recovery
  SANDBOX_SIDE          either arm ended INDETERMINATE for SANDBOX_QUOTA / SANDBOX_INCOMPAT: platform, excluded
  NOT_MEASURED          a RERUN-side verdict (INFRA_ERROR, INVALID_HARNESS, UPLOAD_TOO_LARGE, PIPELINE_ERROR)

Reproducibility Recovery Rate = REPO_RECOVERED / (REPO_RECOVERED + REPO_STILL_FAILING + UNSTABLE_AS_IS), with the
denominator printed next to it and a 95 % Wilson interval (n is small; the interval is the honest size of the claim).
"Researcher-hours saved" keeps its formula (RERUN_BUILD_DIRECTIVE §6.2: REPO_RECOVERED x hours per repo), shows its
inputs and is marked ESTIMATE.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from run_corpus_v1_batch import load_records  # noqa: E402
from summarize_batch import chain_of  # noqa: E402

PASS = ("RUNS_CLEAN", "RUNS_AFTER_REPAIR")
NOT_MEASURED_VERDICTS = ("INFRA_ERROR", "INVALID_HARNESS", "UPLOAD_TOO_LARGE")
SANDBOX_REASONS = ("SANDBOX_QUOTA", "SANDBOX_INCOMPAT")
# RERUN-side reason codes: PIPELINE_ERROR (v1.3.2), COST_CAP (v1.3.3: the spend cap stopped the run).
NOT_MEASURED_REASONS = ("PIPELINE_ERROR", "COST_CAP")
HOURS_PER_REPAIR_ASSUMPTION = 3  # midpoint of the directive's 2-4 hr/repo range (same constant as BatchLab.tsx)
CATEGORIES = ("CONTROL_PASS", "REPO_RECOVERED", "REPO_STILL_FAILING", "UNSTABLE_AS_IS", "ENV_ONLY", "SANDBOX_SIDE",
              "NOT_MEASURED")


def wilson(k: int, n: int, z: float = 1.959964) -> tuple[float, float] | None:
    if n == 0:
        return None
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


def _view(record: dict) -> dict:
    result = record.get("result") or {}
    chain = chain_of(record)
    return {
        "verdict": result.get("verdict"),
        "klass": result.get("taxonomy_code") or result.get("reason_code") or "",
        "reason_code": result.get("reason_code") or "",
        "first_repo_error": chain.first_repo_error,
        "attributions": sorted({link["attribution"] for link in chain.links}),
        "spent": float((record.get("cost_guard") or {}).get("spent_usd") or 0.0),
        "attempts": sum(1 for a in result.get("attempts", []) if a.get("origin") != "time_machine"),
        "tavily": any(a.get("tavily_sources") for a in result.get("attempts", [])),
    }


def _sandbox_side(v: dict) -> bool:
    return v["verdict"] == "INDETERMINATE" and v["reason_code"].split(":", 1)[0] in SANDBOX_REASONS


def categorize(c: dict, t: dict) -> str:
    if c["verdict"] in NOT_MEASURED_VERDICTS or t["verdict"] in NOT_MEASURED_VERDICTS or \
            c["reason_code"].startswith(NOT_MEASURED_REASONS) or t["reason_code"].startswith(NOT_MEASURED_REASONS):
        return "NOT_MEASURED"
    if _sandbox_side(c) or _sandbox_side(t):
        return "SANDBOX_SIDE"
    if c["verdict"] == "RUNS_CLEAN":
        return "CONTROL_PASS"
    if c["first_repo_error"] is not None:
        if t["verdict"] == "RUNS_AFTER_REPAIR":
            return "REPO_RECOVERED"
        if t["verdict"] == "RUNS_CLEAN":
            return "UNSTABLE_AS_IS"
        return "REPO_STILL_FAILING"
    return "ENV_ONLY"


def compare(control: list[dict], treatment: list[dict]) -> dict:
    c_by, t_by = {r["batch"]["entry_id"]: r for r in control}, {r["batch"]["entry_id"]: r for r in treatment}
    problems: list[str] = []
    hashes = {r["batch"]["corpus_hash"] for r in control + treatment}
    tags = {r["batch"]["harness_tag"] for r in control + treatment}
    commits = {r["batch"]["harness_commit"] for r in control + treatment}
    if len(hashes) > 1:
        problems.append(f"corpus hash differs between/within arms: {sorted(hashes)}")
    if len(tags) > 1 or len(commits) > 1:
        problems.append(f"harness differs between/within arms: {sorted(tags)} {sorted(commits)}")
    if set(c_by) != set(t_by):
        problems.append(f"entry sets differ: control-only {sorted(set(c_by) - set(t_by))}, treatment-only {sorted(set(t_by) - set(c_by))}")
    rows = []
    for entry_id in sorted(set(c_by) & set(t_by)):
        c, t = _view(c_by[entry_id]), _view(t_by[entry_id])
        category = categorize(c, t)
        rows.append({
            "id": entry_id, "name": c_by[entry_id]["corpus_entry"]["name"], "category": category, "control": c, "treatment": t,
            "regression": category == "CONTROL_PASS" and t["verdict"] not in PASS,
            "env_passes_in_treatment": category == "ENV_ONLY" and t["verdict"] in PASS,
        })
    counts = {cat: sum(1 for r in rows if r["category"] == cat) for cat in CATEGORIES}
    numerator = counts["REPO_RECOVERED"]
    denominator = counts["REPO_RECOVERED"] + counts["REPO_STILL_FAILING"] + counts["UNSTABLE_AS_IS"]
    return {
        "rows": rows, "counts": counts, "numerator": numerator, "denominator": denominator,
        "rate": (numerator / denominator) if denominator else None, "ci95": wilson(numerator, denominator),
        "regressions": [r for r in rows if r["regression"]],
        "spend": {"control": round(sum(r["control"]["spent"] for r in rows), 4),
                  "treatment": round(sum(r["treatment"]["spent"] for r in rows), 4)},
        "problems": problems,
        "corpus_hash": next(iter(hashes)) if len(hashes) == 1 else None,
        "harness": {"tag": next(iter(tags)) if len(tags) == 1 else None},
    }


def _cell(text: str, width: int = 44) -> str:
    text = (text or "—").replace("|", "\\|").replace("\n", " ")
    return text if len(text) <= width else text[: width - 1] + "…"


def render(result: dict, control_dir: str, treatment_dir: str) -> str:
    n, d = result["numerator"], result["denominator"]
    ci = result["ci95"]
    out = ["# corpus-v2.1 ablation: CONTROL vs TREATMENT", "",
           f"corpus hash `{result['corpus_hash']}` · harness `{result['harness']['tag']}` · generated by "
           "`scripts/compare_batches.py` from the raw records", "",
           f"- CONTROL: `{control_dir}` (repair off, Tavily off): the repo as-is in the fixed runner",
           f"- TREATMENT: `{treatment_dir}` (repair on, Tavily on, tamper gate on)", ""]
    for problem in result["problems"]:
        out.append(f"> **INTEGRITY PROBLEM:** {problem}")
    if result["problems"]:
        out.append("")
    out += ["## Headline", "",
            "| Reproducibility Recovery Rate | numerator | denominator | 95 % Wilson interval |", "|---|--:|--:|---|",
            f"| {f'{n}/{d} = {n / d:.0%}' if d else 'n/a (empty denominator)'} | {n} (REPO_RECOVERED) | {d} "
            f"(REPO_RECOVERED + REPO_STILL_FAILING + UNSTABLE_AS_IS) | "
            f"{f'{ci[0]:.0%}–{ci[1]:.0%}' if ci else 'n/a'} |", "",
            "Denominator = entries whose CONTROL run failed with a **REPO-attributed** error. ENV, SANDBOX and NOT_MEASURED rows "
            "are below and are excluded. Runner-level fixes are shared by both arms.", ""]
    hours = n * HOURS_PER_REPAIR_ASSUMPTION
    out += [f"**ESTIMATE, not measured:** researcher-hours saved ≈ REPO_RECOVERED ({n}) × {HOURS_PER_REPAIR_ASSUMPTION} h/repo "
            f"(assumed midpoint of 2–4 h; RERUN_BUILD_DIRECTIVE §6.2) = {hours} h.", ""]
    out += ["## Categories (each entry in exactly one; never merged)", "", "| category | entries |", "|---|--:|"]
    for cat in CATEGORIES:
        out.append(f"| {cat} | {result['counts'][cat]} |")
    out.append("")
    env_recov = [r for r in result["rows"] if r["env_passes_in_treatment"]]
    out += [f"ENV_ONLY entries that pass in TREATMENT (a repair helped a runner-side failure): {len(env_recov)}"
            + (" (" + ", ".join(f"#{r['id']}" for r in env_recov) + "); these are NOT repo-fix recoveries and are not in the rate." if env_recov else "."), ""]
    out += ["## Per entry", "",
            "| # | entry | category | CONTROL verdict | first repo error (control) | attribution | TREATMENT verdict | repairs | Tavily |",
            "|--:|---|---|---|---|---|---|--:|:-:|"]
    for r in result["rows"]:
        c, t = r["control"], r["treatment"]
        out.append(f"| {r['id']} | {r['name']} | {r['category']}{' **REGRESSION**' if r['regression'] else ''} | {c['verdict']} "
                   f"({_cell(c['klass'], 24)}) | {_cell(c['first_repo_error'] or '', 44)} | {'/'.join(c['attributions']) or '—'} | "
                   f"{t['verdict']} ({_cell(t['klass'], 24)}) | {t['attempts']} | {'Y' if t['tavily'] else 'N'} |")
    out += ["", "## Spend", "", f"CONTROL ${result['spend']['control']:.2f} · TREATMENT ${result['spend']['treatment']:.2f} · "
            f"total ${result['spend']['control'] + result['spend']['treatment']:.2f} "
            "(sum of `cost_guard.spent_usd` over the records)", ""]
    if result["regressions"]:
        out += ["## REGRESSIONS (stop condition)", ""] + [
            f"- #{r['id']} {r['name']}: CONTROL passed, TREATMENT {r['treatment']['verdict']}" for r in result["regressions"]] + [""]
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--control", required=True, type=Path)
    ap.add_argument("--treatment", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--json", type=Path, help="also write the numbers as JSON")
    args = ap.parse_args(argv)
    control, treatment = load_records(args.control), load_records(args.treatment)
    if not control or not treatment:
        print("both arms need records", file=sys.stderr)
        return 2
    result = compare(control, treatment)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(render(result, args.control.as_posix(), args.treatment.as_posix()), encoding="utf-8", newline="\n")
    if args.json:
        args.json.write_text(json.dumps({k: v for k, v in result.items() if k != "rows"}, indent=2, default=str) + "\n",
                             encoding="utf-8", newline="\n")
    print(f"wrote {args.out}: {result['counts']} rate {result['numerator']}/{result['denominator']}")
    return 2 if result["regressions"] or result["problems"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
