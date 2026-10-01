"""Step 2 of the v1.4.0 directive: the pre-registered gate v1.4.0. TREATMENT only, corpus-v2 entries 3, 7, 8, 11.

    backend/.venv/Scripts/python.exe reports/corpus-v2.1/v1.4.0/gate/run_gate_v140.py --selftest
    backend/.venv/Scripts/python.exe reports/corpus-v2.1/v1.4.0/gate/run_gate_v140.py --gate-cap-usd G --entry-cap-usd E          # DRY RUN
    backend/.venv/Scripts/python.exe reports/corpus-v2.1/v1.4.0/gate/run_gate_v140.py --gate-cap-usd G --entry-cap-usd E --go     # spends money

Nothing here runs live without --go AND both caps on the command line; the caps are the owner's figures, written in chat first (there
are no defaults). The gate cap must be at least 4 x the entry cap (gate_budget.check_gate_caps) and every entry runs with the same
fixed entry cap: an entry whose cap no longer fits is not started (gate_budget.entry_cap_for). In the harness-v1.3.4 gate the last entry
inherited what was left of the gate cap ($0.7819 of $2.00) and was starved.

It lives under reports/ like the earlier gate runners: `scripts/` is part of the sealed harness. It uses the batch driver's preflight
(sealed tag on origin, seal verification of every sandbox-touching file, corpus hash), the driver's upload smoke test and the driver's
per-entry runner (`_run_live` -> scripts/live_run.py). Records go to runs/corpus_v2_batch/<tag>/gate/.

Criteria, pre-registered (same four entries and criteria a-d as the v1.3.4 gate, plus e), evaluated mechanically from the records:
  (a) >= 2 of the 4 entries end RUNS_CLEAN or RUNS_AFTER_REPAIR;
  (b) >= 1 source patch applied: an attempt with a non-empty diff that reached a re-execution (exit code recorded);
  (c) >= 1 repair attempt carries a Tavily citation stored in the record (`tavily_sources` non-empty);
  (d) no entry spent more than $2.00, and the cost guard fired correctly where it fired (every cost event listed);
  (e) torch installed at most once per environment image, from the records' `operations`: no operation installed torch on top of an
      image that already held it, and no operation rebuilt an environment definition (base image + setup commands through the torch
      install) that an earlier operation of the entry had already built. The planner-image baseline's own install is counted
      separately and is outside (e). A record without `operations` fails (e): it cannot be checked.
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

ENTRIES = (3, 7, 8, 11)  # the owner's order for gate v1.4.0 (chat, 2026-10-01); the same four entries as the v1.3.4 gate
ENTRY_SPEND_LIMIT_USD = 2.0  # criterion (d), pre-registered since the v1.3.3 gate
PASS = ("RUNS_CLEAN", "RUNS_AFTER_REPAIR")


def criterion_e(record: dict) -> dict:
    """Criterion (e) for one record. PURE."""
    ops = record.get("operations")
    if not isinstance(ops, list):
        return {"ok": False, "detail": "no `operations` in the record: (e) cannot be checked", "baseline_installs": None, "installs": []}
    baseline_installs = sum(1 for op in ops if op.get("role") == "baseline" and op.get("torch_installed"))
    installs, violations, built = [], [], {}

    def _round(role: str) -> str | None:
        # candidates of one round run at the same time: none of them can reuse what another is still building
        return role.rsplit(" candidate", 1)[0] if " candidate " in f"{role} " else None

    for op in ops:
        key, role = op.get("torch_env_key"), str(op.get("role") or "")
        if role == "baseline":
            if op.get("torch_installed") and key:
                built.setdefault(key, (op.get("n"), None))
            continue
        if not op.get("torch_installed"):
            continue
        installs.append({"operation": op.get("n"), "role": role, "env_key": key, "result_layers": op.get("kept_images", [])})
        if op.get("torch_in_start_image"):
            violations.append(f"operation {op.get('n')} ({role}) installed torch on an image that already held it")
        if key and key in built and not (built[key][1] is not None and built[key][1] == _round(role)):
            violations.append(f"operation {op.get('n')} ({role}) rebuilt the torch environment operation {built[key][0]} had built")
        if key:
            built.setdefault(key, (op.get("n"), _round(role)))
    return {"ok": not violations, "detail": "; ".join(violations) or f"{len(installs)} torch install(s) outside the baseline, each in its own environment image",
            "baseline_installs": baseline_installs, "installs": installs}


def evaluate_gate(records: list[dict]) -> dict:
    """PURE. `records` are the entries' run records."""
    verdicts = {r["batch"]["entry_id"]: (r.get("result") or {}).get("verdict") for r in records}
    attempts = [(r["batch"]["entry_id"], a) for r in records for a in (r.get("result") or {}).get("attempts", [])]
    proposed = [(i, a) for i, a in attempts if a.get("diff_text")]
    applied = [(i, a) for i, a in proposed if a.get("exit_code") is not None]
    cited = [(i, a) for i, a in attempts if a.get("tavily_sources")]
    spent = {r["batch"]["entry_id"]: float((r.get("cost_guard") or {}).get("spent_usd") or 0.0) for r in records}
    events = {r["batch"]["entry_id"]: (r.get("cost_guard") or {}).get("cost_events", []) for r in records}
    caps = {r["batch"]["entry_id"]: (r.get("batch") or {}).get("per_entry_cap_usd") for r in records}
    passed = sum(1 for v in verdicts.values() if v in PASS)
    a_ok = passed >= 2
    b_ok = bool(applied)
    c_ok = bool(cited)
    over = {i: round(s, 4) for i, s in spent.items() if s > ENTRY_SPEND_LIMIT_USD + 1e-9}
    d_ok = not over
    e = {r["batch"]["entry_id"]: criterion_e(r) for r in records}
    e_ok = bool(records) and all(x["ok"] for x in e.values())
    return {
        "verdicts": verdicts,
        "a": {"ok": a_ok, "detail": f"{passed} of {len(verdicts)} reached RUNS_CLEAN / RUNS_AFTER_REPAIR"},
        "b": {"ok": b_ok, "detail": f"{len(applied)} applied of {len(proposed)} proposed",
              "applied": [[i, a["attempt_number"], a.get("candidate")] for i, a in applied]},
        "c": {"ok": c_ok, "detail": f"{len(cited)} repair attempt(s) with a stored Tavily citation",
              "cited": [[i, a["attempt_number"], [s.get("url") for s in a["tavily_sources"]]] for i, a in cited]},
        "d": {"ok": d_ok, "detail": f"no entry over ${ENTRY_SPEND_LIMIT_USD:.2f}" if d_ok else f"over ${ENTRY_SPEND_LIMIT_USD:.2f}: {over}",
              "spent_usd": {i: round(s, 4) for i, s in spent.items()}, "entry_caps_usd": caps,
              "cost_events": {i: ev for i, ev in events.items() if ev}},
        "e": {"ok": e_ok, "per_entry": e},
        "passed": a_ok and b_ok and c_ok and d_ok and e_ok,
        "total_spent_usd": round(sum(spent.values()), 4),
    }


def _selftest() -> int:
    def op(n, role, installed, in_start, key):
        return {"n": n, "role": role, "torch_installed": installed, "torch_in_start_image": in_start, "torch_env_key": key, "kept_images": []}

    def rec(i, verdict, attempts=(), spent=0.3, ops=None):
        r = {"batch": {"entry_id": i, "per_entry_cap_usd": 1.25}, "result": {"verdict": verdict, "attempts": list(attempts)},
             "cost_guard": {"spent_usd": spent, "cost_events": []}}
        if ops is not None:
            r["operations"] = ops
        return r

    good_ops = [op(1, "baseline", True, False, "k310"), op(2, "re-execution", True, False, "k39"), op(3, "repair 1 candidate 1", False, True, "k39")]
    patch = {"attempt_number": 1, "diff_text": "--- a\n+++ b\n", "exit_code": 0, "tavily_sources": [{"url": "https://x"}], "candidate": 1}
    ok = evaluate_gate([rec(11, "RUNS_AFTER_REPAIR", [patch], ops=good_ops), rec(7, "RUNS_AFTER_REPAIR", ops=good_ops),
                        rec(3, "BLOCKED", ops=good_ops), rec(8, "BLOCKED", ops=good_ops)])
    assert ok["passed"], ok
    reinstall = good_ops[:2] + [op(3, "repair 1 candidate 1", True, True, "k39")]
    assert not evaluate_gate([rec(11, "RUNS_AFTER_REPAIR", [patch], ops=reinstall)])["e"]["ok"]  # torch on top of torch
    rebuilt = good_ops[:2] + [op(3, "repair 2", True, False, "k39")]
    assert not evaluate_gate([rec(11, "RUNS_AFTER_REPAIR", [patch], ops=rebuilt)])["e"]["ok"]  # the same environment built twice
    baseline_twice = [op(1, "baseline", True, False, "k310"), op(2, "re-execution", True, False, "k310")]
    assert not evaluate_gate([rec(11, "RUNS_AFTER_REPAIR", [patch], ops=baseline_twice)])["e"]["ok"]  # missed reuse of the baseline's layer
    assert not evaluate_gate([rec(11, "RUNS_AFTER_REPAIR", [patch])])["e"]["ok"]  # no operations: cannot be checked
    assert not evaluate_gate([rec(11, "RUNS_CLEAN", [patch], spent=2.4, ops=good_ops), rec(7, "RUNS_CLEAN", ops=good_ops)])["d"]["ok"]
    print("selftest ok: the v1.4.0 gate arithmetic behaves as specified")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--go", action="store_true", help="actually run (spends money; needs the owner's caps)")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--gate-cap-usd", type=float)
    ap.add_argument("--entry-cap-usd", type=float)
    ap.add_argument("--tag", default="harness-v1.4.0", help="the sealed tag to gate")
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
    spent, records = 0.0, []
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
        spent += float(record["cost_guard"]["spent_usd"])
        result = record.get("result") or {}
        print(f"#{row['id']:2} -> {result.get('verdict')} {result.get('taxonomy_code') or result.get('reason_code') or ''} "
              f"${record['cost_guard']['spent_usd']:.4f} (gate total ${spent:.4f})", flush=True)
        if record.get("error"):
            print(f"STOP: entry #{row['id']} ended without a verdict: {record['error']}", flush=True)
            break
    verdict = evaluate_gate(records)
    out = Path(__file__).with_name(f"gate_result_{args.tag}.json")
    out.write_text(json.dumps(verdict, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(verdict, indent=2))
    complete = len(records) == len(ENTRIES)
    print("GATE v1.4.0:", "PASSED" if verdict["passed"] and complete else "NOT PASSED (attempted, did not pass; Phase D assets stay as they are)")
    return 0 if verdict["passed"] and complete else 1


if __name__ == "__main__":
    raise SystemExit(main())
