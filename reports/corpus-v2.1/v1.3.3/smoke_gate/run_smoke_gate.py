"""Step 2 of the v1.3.3 plan: the paid SMOKE GATE. TREATMENT only, entries 11, 7, 3, 8, cap $6 (METHODOLOGY.md, harness-v1.3.3 amendments).

    backend/.venv/Scripts/python.exe reports/corpus-v2.1/v1.3.3/smoke_gate/run_smoke_gate.py            # DRY RUN: preflight + plan, no spend
    backend/.venv/Scripts/python.exe reports/corpus-v2.1/v1.3.3/smoke_gate/run_smoke_gate.py --go       # spends money (needs operator approval)
    backend/.venv/Scripts/python.exe reports/corpus-v2.1/v1.3.3/smoke_gate/run_smoke_gate.py --selftest # the gate arithmetic on synthetic records, no network

It lives under reports/ on purpose: `scripts/` is part of the sealed harness (a new file there would fail the batch preflight). It changes nothing in the
harness: it runs the driver's own preflight (sealed tag, seal verification, corpus hash), the driver's upload smoke test and the driver's per-entry runner
(`_run_live` -> scripts/live_run.py) for the four entries only, into runs/corpus_v2_batch/harness-v1.3.3/smoke/ (kept apart from the later full TREATMENT run).

Spend control: before each entry the running total plus that entry's cap must fit under $6, and each entry's own CostGuard ceiling is min($2, what is left of the $6),
so the repairs of the last entries can never pass the gate cap. (The as-published baseline run keeps the 600 s wall clock by design; see METHODOLOGY.)

Gate criteria, evaluated mechanically from the records (all required):
  (a) >= 2 of the 4 entries end RUNS_CLEAN or RUNS_AFTER_REPAIR;
  (b) >= 1 source patch applied via `git apply` (an attempt with a non-empty diff that reached a re-execution). If NO attempt of any entry PROPOSED a source
      patch, (b) is N/A for this step and becomes mandatory for the reporting of the full run;
  (c) >= 1 repair attempt carries a Tavily citation stored in the record (`tavily_sources` non-empty);
  (d) no entry spent more than $2.00 and the cost guard either did not fire or fired correctly (an entry that ended COST_CAP did so with spend <= $2.00 + the killed
      step's measured cost; every cost event is listed).
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "backend"))

ENTRIES = (11, 7, 3, 8)  # METHODOLOGY amendment, 2026-09-30 (entry 10 replaced by 7 before any run)
GATE_CAP_USD = 6.0
ENTRY_CAP_USD = 2.0
PASS = ("RUNS_CLEAN", "RUNS_AFTER_REPAIR")


def evaluate_gate(records: list[dict]) -> dict:
    """PURE. `records` are the four entries' run records."""
    verdicts = {r["batch"]["entry_id"]: (r.get("result") or {}).get("verdict") for r in records}
    attempts = [(r["batch"]["entry_id"], a) for r in records for a in (r.get("result") or {}).get("attempts", [])]
    proposed = [(i, a) for i, a in attempts if a.get("diff_text")]
    applied = [(i, a) for i, a in proposed if a.get("exit_code") is not None]  # reached a re-execution, so git apply succeeded
    cited = [(i, a) for i, a in attempts if a.get("tavily_sources")]
    spent = {r["batch"]["entry_id"]: float((r.get("cost_guard") or {}).get("spent_usd") or 0.0) for r in records}
    events = {r["batch"]["entry_id"]: (r.get("cost_guard") or {}).get("cost_events", []) for r in records}
    cap_hits = {i: (r.get("result") or {}).get("indeterminate_reason", "")[:80] for r in records
                for i in [r["batch"]["entry_id"]] if str((r.get("result") or {}).get("indeterminate_reason", "")).startswith("COST_CAP")}
    a_ok = sum(1 for v in verdicts.values() if v in PASS) >= 2
    if not proposed:
        b_status = "N/A (no source patch was proposed; mandatory for the full run's reporting)"
        b_ok = True
    else:
        b_ok = bool(applied)
        b_status = f"{len(applied)} applied of {len(proposed)} proposed"
    c_ok = bool(cited)
    over = {i: round(s, 4) for i, s in spent.items() if s > ENTRY_CAP_USD + 1e-9}
    d_ok = not over
    return {
        "verdicts": verdicts,
        "a": {"ok": a_ok, "detail": f"{sum(1 for v in verdicts.values() if v in PASS)} of {len(verdicts)} reached RUNS_CLEAN / RUNS_AFTER_REPAIR"},
        "b": {"ok": b_ok, "detail": b_status, "proposed": [[i, a['attempt_number']] for i, a in proposed], "applied": [[i, a['attempt_number']] for i, a in applied]},
        "c": {"ok": c_ok, "detail": f"{len(cited)} repair attempt(s) with a stored Tavily citation",
              "cited": [[i, a['attempt_number'], [s.get('url') for s in a['tavily_sources']]] for i, a in cited]},
        "d": {"ok": d_ok, "detail": "no entry over $2.00" if d_ok else f"over the $2.00 entry cap: {over}", "spent_usd": {i: round(s, 4) for i, s in spent.items()},
              "cost_cap_endings": cap_hits, "cost_events": {i: e for i, e in events.items() if e}},
        "passed": a_ok and b_ok and c_ok and d_ok,
        "total_spent_usd": round(sum(spent.values()), 4),
    }


def _selftest() -> int:
    def rec(i, verdict, attempts=(), spent=0.3, reason=""):
        return {"batch": {"entry_id": i}, "result": {"verdict": verdict, "attempts": list(attempts), "indeterminate_reason": reason},
                "cost_guard": {"spent_usd": spent, "cost_events": []}}

    patch_applied = {"attempt_number": 1, "diff_text": "--- a\n+++ b\n", "exit_code": 1, "tavily_sources": [{"url": "https://x"}]}
    patch_failed = {"attempt_number": 2, "diff_text": "--- a\n+++ b\n", "exit_code": None, "tavily_sources": []}
    env_only = {"attempt_number": 1, "diff_text": "", "exit_code": 0, "tavily_sources": []}
    good = evaluate_gate([rec(11, "RUNS_AFTER_REPAIR", [patch_applied]), rec(7, "BLOCKED"), rec(3, "RUNS_CLEAN"), rec(8, "BLOCKED")])
    assert good["passed"] and good["b"]["detail"] == "1 applied of 1 proposed" and good["c"]["ok"]
    assert not evaluate_gate([rec(11, "RUNS_AFTER_REPAIR", [patch_applied]), rec(7, "BLOCKED"), rec(3, "BLOCKED"), rec(8, "BLOCKED")])["passed"]  # (a) 1 of 4
    assert not evaluate_gate([rec(11, "RUNS_CLEAN"), rec(7, "RUNS_CLEAN", [patch_failed]), rec(3, "BLOCKED"), rec(8, "BLOCKED")])["b"]["ok"]  # proposed, none applied
    na = evaluate_gate([rec(11, "RUNS_AFTER_REPAIR", [dict(env_only, tavily_sources=[{"url": "https://y"}])]), rec(7, "RUNS_CLEAN"), rec(3, "BLOCKED"), rec(8, "BLOCKED")])
    assert na["b"]["ok"] and na["b"]["detail"].startswith("N/A") and na["passed"]  # (b) N/A when no patch was ever proposed
    assert not evaluate_gate([rec(11, "RUNS_CLEAN", [env_only]), rec(7, "RUNS_CLEAN", [env_only]), rec(3, "BLOCKED"), rec(8, "BLOCKED")])["c"]["ok"]  # no citation
    assert not evaluate_gate([rec(11, "RUNS_CLEAN", [patch_applied], spent=2.4), rec(7, "RUNS_CLEAN"), rec(3, "BLOCKED"), rec(8, "BLOCKED")])["d"]["ok"]  # over $2
    print("selftest ok: the gate arithmetic behaves as specified")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--go", action="store_true", help="actually run (spends money)")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--tag", default="harness-v1.3.4", help="the sealed tag to gate (records go to runs/corpus_v2_batch/<tag>/smoke)")
    args = ap.parse_args()
    if args.selftest:
        return _selftest()

    import run_corpus_v1_batch as drv

    frozen = {**drv.preflight("corpus-v2", args.tag), "arm": "treatment", "total_cap_usd": GATE_CAP_USD, "already_spent_usd": 0.0}
    rows = {r["id"]: r for r in drv.entries_for("corpus-v2")}
    plan = [rows[i] for i in ENTRIES]
    odir = ROOT / "runs" / "corpus_v2_batch" / args.tag / "smoke"
    print(f"preflight OK at {frozen['head_commit'][:12]} (tag {args.tag}); gate cap ${GATE_CAP_USD}; entries: "
          + ", ".join(f"#{r['id']} {r['name']}" for r in plan))
    if not args.go:
        print("DRY RUN: nothing was run and nothing was spent (pass --go to run).")
        return 0

    odir.mkdir(parents=True, exist_ok=True)
    smoke = drv.run_smoke()
    (odir / f"upload_smoke_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json").write_text(json.dumps(smoke, indent=2) + "\n", encoding="utf-8")
    if not smoke.get("ok"):
        print("REFUSING TO START: the pre-batch upload smoke test failed", file=sys.stderr)
        return 3
    spent, records = 0.0, []
    for row in plan:
        path = odir / f"{row['id']:02d}_{row['name']}.json"
        if GATE_CAP_USD - spent < 0.5:  # below $0.50 an entry cannot fund its baseline plus one repair
            print(f"STOP: ${spent:.4f} spent; the gate cap ${GATE_CAP_USD} leaves no room for entry #{row['id']}", flush=True)
            break
        drv.PER_ENTRY_CAP_USD = round(min(ENTRY_CAP_USD, GATE_CAP_USD - spent), 4)  # the entry's CostGuard ceiling can never pass the gate cap
        meta = {**frozen, "entry_id": row["id"], "category": row["category"], "rules_matched": row["rules_matched"],
                "per_entry_cap_usd": drv.PER_ENTRY_CAP_USD, "total_cap_usd": GATE_CAP_USD}
        print(f"#{row['id']:2} {row['name']} starting (entry cap ${drv.PER_ENTRY_CAP_USD})", flush=True)
        drv._run_live("corpus-v2", row["name"], frozen["corpus_hash"], meta, path)
        record = json.loads(path.read_text(encoding="utf-8"))
        records.append(record)
        spent += float(record["cost_guard"]["spent_usd"])
        result = record.get("result") or {}
        print(f"#{row['id']:2} -> {result.get('verdict')} {result.get('taxonomy_code') or result.get('reason_code') or ''} "
              f"${record['cost_guard']['spent_usd']:.4f} (gate total ${spent:.4f})", flush=True)
        if record.get("error"):
            print(f"STOP: entry #{row['id']} ended without a verdict: {record['error']}", flush=True)
            break
    verdict = evaluate_gate(records)
    out = Path(__file__).with_name(f"smoke_gate_result_{args.tag}.json")
    out.write_text(json.dumps(verdict, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(verdict, indent=2))
    print("SMOKE GATE:", "PASSED" if verdict["passed"] and len(records) == len(ENTRIES) else "NOT PASSED (report root causes; no further spend without a decision)")
    return 0 if verdict["passed"] and len(records) == len(ENTRIES) else 1


if __name__ == "__main__":
    raise SystemExit(main())
