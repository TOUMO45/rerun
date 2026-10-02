"""The final gate (v1.4.3 directive): the pre-registered gate v1.4.3. TREATMENT only, corpus-v2 entries 3, 7, 8, 11, in that order.

    backend/.venv/Scripts/python.exe reports/corpus-v2.1/v1.4.3/gate/run_gate_v143.py --selftest
    backend/.venv/Scripts/python.exe reports/corpus-v2.1/v1.4.3/gate/run_gate_v143.py --gate-cap-usd G --entry-cap-usd E          # DRY RUN
    backend/.venv/Scripts/python.exe reports/corpus-v2.1/v1.4.3/gate/run_gate_v143.py --gate-cap-usd G --entry-cap-usd E --go     # spends money

Same entries, same order, same criteria (a)-(e), same arithmetic as the harness-v1.4.0, v1.4.1 and v1.4.2 gates: this runner LOADS the v1.4.2 runner's `evaluate_gate`
(which loads the v1.4.0 runner's `criterion_e` and `evaluate_gate`) rather than copying them (test: test_v143_gate_runner.py). The pre-registered budget (owner, chat
2026-10-02): entry cap $1.75, gate cap $7.00 (= 4 x the entry cap), seal at most $1.50, ledger ceiling $32.00 API-reported; no defaults here, both caps are on the command
line. An entry whose full cap no longer fits in what is left of the gate cap is not started (gate_budget.entry_cap_for).

Criteria, pre-registered (METHODOLOGY "Gate v1.4.3"), the v1.4.0 text unchanged:
  (a) >= 2 of the 4 entries end RUNS_CLEAN or RUNS_AFTER_REPAIR;
  (b) >= 1 source patch applied (an attempt with a non-empty diff that reached a re-execution);
  (c) >= 1 repair attempt carries a Tavily citation stored in the record (`tavily_sources` non-empty);
  (d) no entry spent more than $2.00 and the cost guard fired correctly where it fired (every cost event listed);
  (e) torch installed at most once per environment image (from the records' `operations`; the planner-image baseline is outside (e)).

New in v1.4.3, NOT a criterion and changing no verdict (D-42): after the four entries, every RUNS_* entry whose smoke run was still alive at its limit is re-executed once
from its final image for 600 s or to completion (app.services.sustained_run), funded from what the gate cap has left; each outcome is written beside the entry's record as
`sustained_<NN>_<name>.json` and listed in the gate result. The sustained runs' cost counts in the gate cap and in the ledger.

After the gate, whatever the verdict: all live work stops (owner). The gate's BILLED line is read from the owner's balance reading AFTER the gate; the result file carries it
as null with that reason until the owner reports it (ledger figures are the sandbox API's reported cost, not account billing: D-36).
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "backend"))

_V142 = ROOT / "reports" / "corpus-v2.1" / "v1.4.2" / "gate" / "run_gate_v142.py"
_spec = importlib.util.spec_from_file_location("run_gate_v142", _V142)
v142 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(v142)

ENTRIES = v142.ENTRIES  # (3, 7, 8, 11)
ENTRY_SPEND_LIMIT_USD = v142.ENTRY_SPEND_LIMIT_USD  # criterion (d): $2.00
PASS = v142.PASS
criterion_e = v142.criterion_e
BILLED_PENDING = v142.BILLED_PENDING


def evaluate_gate(records: list[dict], sustained: list[dict] | None = None) -> dict:
    """PURE. The v1.4.2 evaluation unchanged (criteria (a)-(e), endings, the pending BILLED line), plus the sustained-run line: listed, never evaluated."""
    verdict = v142.evaluate_gate(records)
    docs = [d for d in (sustained or []) if d]
    verdict["sustained_runs"] = {
        "gating": False,
        "runs": [{"entry": d.get("entry"), "name": d.get("name"), "outcome": d.get("outcome"), "ran": d.get("ran"), "label": d.get("label"),
                  "funded_seconds": d.get("funded_seconds"), "seconds": d.get("seconds"), "cost_usd": d.get("cost_usd", 0.0),
                  "cost_estimated_usd": d.get("cost_estimated_usd", 0.0)} for d in docs],
        "cost_usd": round(sum(float(d.get("cost_usd") or 0.0) for d in docs), 6),
        "cost_estimated_usd": round(sum(float(d.get("cost_estimated_usd") or 0.0) for d in docs), 6),
    }
    return verdict


def sustained_phase(records: list[dict], paths: dict, *, gate_cap_usd: float, spent_usd: float, odir: Path, run=None, api_key: str = "", project_id: str = "") -> tuple[list[dict], float]:
    """After the entries: one sustained run for each RUNS_* record, each funded with its equal share of what the gate cap has left. Returns (docs, their cost: API-reported
    plus the estimate of a run whose cost was not reported). Writes `sustained_<NN>_<name>.json` beside each entry's record."""
    from app.services import sustained_run

    run = run or sustained_run.run_sustained
    todo = [r for r in records if sustained_run.final_run_of(r) is not None]
    docs, extra = [], 0.0
    for i, record in enumerate(todo):
        remaining = gate_cap_usd - spent_usd - extra
        doc = run(record, api_key=api_key, project_id=project_id, remaining_usd=remaining, entries_left=len(todo) - i)
        if doc is None:
            continue
        extra += float(doc.get("cost_usd") or 0.0) + float(doc.get("cost_estimated_usd") or 0.0)
        docs.append(doc)
        name = paths[(record.get("corpus_entry") or {}).get("name")].name
        (odir / f"sustained_{name}").write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    return docs, extra


def _selftest() -> int:
    assert v142._selftest() == 0
    assert evaluate_gate([])["sustained_runs"]["gating"] is False
    print("selftest ok: the v1.4.3 gate loads the v1.4.2 / v1.4.0 criteria unchanged and lists the sustained runs without evaluating them")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--go", action="store_true", help="actually run (spends money; needs the owner's caps)")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--gate-cap-usd", type=float)
    ap.add_argument("--entry-cap-usd", type=float)
    ap.add_argument("--tag", default="harness-v1.4.3", help="the sealed tag to gate")
    args = ap.parse_args(argv)
    if args.selftest:
        return _selftest()
    if args.gate_cap_usd is None or args.entry_cap_usd is None:
        print("REFUSED: --gate-cap-usd and --entry-cap-usd are required (the owner's figures; there are no defaults)", file=sys.stderr)
        return 2

    from app.services import gate_budget

    try:
        gate_budget.check_gate_caps(args.gate_cap_usd, args.entry_cap_usd, len(ENTRIES))
    except gate_budget.GateBudgetError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    import run_corpus_v1_batch as drv

    try:
        frozen = {**drv.preflight("corpus-v2", args.tag), "arm": "treatment", "total_cap_usd": args.gate_cap_usd, "already_spent_usd": 0.0}
    except drv.PreflightError as exc:
        print(f"PREFLIGHT REFUSED ({args.tag}): {exc}", file=sys.stderr)
        return 3
    rows = {r["id"]: r for r in drv.entries_for("corpus-v2")}
    plan = [rows[i] for i in ENTRIES]
    odir = ROOT / "runs" / "corpus_v2_batch" / args.tag / "gate"
    print(f"preflight OK at {frozen['head_commit'][:12]} (tag {args.tag}); gate cap ${args.gate_cap_usd}, fixed entry cap "
          f"${args.entry_cap_usd}; entries: " + ", ".join(f"#{r['id']} {r['name']}" for r in plan))
    if not args.go:
        print("DRY RUN: nothing was run and nothing was spent (pass --go to run).")
        return 0

    odir.mkdir(parents=True, exist_ok=True)
    smoke = drv.run_smoke()
    (odir / f"upload_smoke_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json").write_text(json.dumps(smoke, indent=2) + "\n", encoding="utf-8")
    if not smoke.get("ok"):
        print("REFUSING TO START: the pre-batch upload smoke test failed", file=sys.stderr)
        return 3
    spent, records, paths = 0.0, [], {}
    for row in plan:
        path = odir / f"{row['id']:02d}_{row['name']}.json"
        try:
            drv.PER_ENTRY_CAP_USD = gate_budget.entry_cap_for(args.gate_cap_usd, args.entry_cap_usd, spent)
        except gate_budget.GateBudgetError as exc:
            print(f"STOP: {exc}", flush=True)
            break
        meta = {**frozen, "entry_id": row["id"], "category": row["category"], "rules_matched": row["rules_matched"],
                "per_entry_cap_usd": drv.PER_ENTRY_CAP_USD, "total_cap_usd": args.gate_cap_usd}
        print(f"#{row['id']:2} {row['name']} starting (entry cap ${drv.PER_ENTRY_CAP_USD})", flush=True)
        drv._run_live("corpus-v2", row["name"], frozen["corpus_hash"], meta, path)
        record = json.loads(path.read_text(encoding="utf-8"))
        records.append(record)
        paths[row["name"]] = path
        spent += float(record["cost_guard"]["spent_usd"])
        result = record.get("result") or {}
        print(f"#{row['id']:2} -> {result.get('verdict')} {result.get('taxonomy_code') or result.get('reason_code') or ''} "
              f"${record['cost_guard']['spent_usd']:.4f} API-reported + estimates (gate total ${spent:.4f}; record {path.name})", flush=True)
        if record.get("error"):
            print(f"STOP: entry #{row['id']} ended without a verdict: {record['error']}", flush=True)
            break
    sustained, sustained_cost = [], 0.0
    if records:
        from app.config import get_settings

        settings = get_settings()
        sustained, sustained_cost = sustained_phase(records, paths, gate_cap_usd=args.gate_cap_usd, spent_usd=spent, odir=odir,
                                                    api_key=settings.nebius_api_key, project_id=settings.nebius_project_id)
        for doc in sustained:
            print(f"sustained #{doc.get('entry')} {doc.get('name')}: {doc.get('outcome')}: {doc.get('label')} "
                  f"(${doc.get('cost_usd', 0.0):.4f} API-reported, ${doc.get('cost_estimated_usd', 0.0):.4f} estimated)", flush=True)
    verdict = evaluate_gate(records, sustained)
    verdict["gate_spend"] = {"entries_usd": round(spent, 6), "sustained_runs_usd": round(sustained_cost, 6), "total_usd": round(spent + sustained_cost, 6),
                             "cap_usd": args.gate_cap_usd, "note": "entries: cost guard figures per record (API-reported plus the estimate of a killed step); sustained runs as listed"}
    out = Path(__file__).with_name(f"gate_result_{args.tag}.json")
    out.write_text(json.dumps(verdict, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(verdict, indent=2))
    complete = len(records) == len(ENTRIES)
    print("GATE v1.4.3:", "PASSED" if verdict["passed"] and complete else "NOT PASSED (attempted, did not pass; all live work stops, Phase D follows)")
    return 0 if verdict["passed"] and complete else 1


if __name__ == "__main__":
    raise SystemExit(main())
