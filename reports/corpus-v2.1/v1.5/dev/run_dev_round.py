"""One DEV round of the v1.5 dev/test protocol: TREATMENT, the eight DEV entries of corpus-v2, once each, at one sealed harness tag.

    backend/.venv/Scripts/python.exe reports/corpus-v2.1/v1.5/dev/run_dev_round.py --selftest
    backend/.venv/Scripts/python.exe reports/corpus-v2.1/v1.5/dev/run_dev_round.py --round N --tag harness-v1.5.K --entry-cap-usd 1.50           # DRY RUN
    backend/.venv/Scripts/python.exe reports/corpus-v2.1/v1.5/dev/run_dev_round.py --round N --tag harness-v1.5.K --entry-cap-usd 1.50 --go    # spends money

Everything that decides a verdict is the batch driver's and the live runner's, unchanged (preflight, the sealed tag, `_run_live`, the cost guard). What is new here is only the
protocol of METHODOLOGY "harness-v1.5 dev/test protocol": the entry list is the DEV list (the TEST firewall refuses any other id), the budget guard (HARD and RESERVE checks,
devtest/budget.py) runs before the round, a round whose cap does not fit is refused, and an entry that ends INFRA_ERROR with no baseline execution is re-run ONCE with the first
record kept unmodified under infra_retries/ and a note beside it (annotated, never edited). No sustained-run phase in a DEV round (a 600 s run costs about $6.24; METHODOLOGY B3).

The process must run DETACHED (Task Scheduler + pythonw + --log-file): a paid batch is never a child of a session (the v1.4.3 gate lost entries to that, D-43).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "devtest"))

import budget  # noqa: E402
import firewall  # noqa: E402
import split  # noqa: E402

DEV_ENTRIES = split.DEV_ENTRIES
METHODOLOGY = ROOT / "METHODOLOGY.md"


def methodology_dev_list(text: str) -> list[int]:
    """The DEV list written in METHODOLOGY.md (the line `DEV_ENTRIES: [..]`), or [] when there is none."""
    match = re.search(r"^DEV_ENTRIES:\s*\[([0-9, ]*)\]\s*$", text, flags=re.M)
    return [int(x) for x in match.group(1).replace(" ", "").split(",") if x] if match else []


def check_pre_registration() -> None:
    """The runner runs only the DEV list that METHODOLOGY.md pre-registered."""
    listed = methodology_dev_list(METHODOLOGY.read_text(encoding="utf-8"))
    if listed != sorted(DEV_ENTRIES) or sorted(split.split()["dev"]) != listed:
        raise SystemExit(f"REFUSED: the DEV list in METHODOLOGY.md {listed} differs from the split rule's {sorted(DEV_ENTRIES)}")


def should_retry_infra(record: dict) -> bool:
    """The re-queue rule (METHODOLOGY, 2026-09-28): an entry that ends INFRA_ERROR with NO baseline execution is run again; an INFRA_ERROR after a baseline ran is not. The record
    carries no baseline field for an entry that never got one, so 'no baseline execution' is read from the operations: the entry has no operation of role `baseline` that completed."""
    result = record.get("result") or {}
    if result.get("verdict") != "INFRA_ERROR":
        return False
    for op in record.get("operations") or []:
        if op.get("role") == "baseline" and op.get("outcome") == "completed":
            return False
    return True


def plan_entries(rows: list[dict]) -> list[dict]:
    """The DEV rows in id order; the firewall refuses a TEST id however it got here."""
    plan = [r for r in rows if r["id"] in DEV_ENTRIES]
    for row in plan:
        firewall.assert_not_test(row["id"], what="run")
    if sorted(r["id"] for r in plan) != sorted(DEV_ENTRIES):
        raise SystemExit(f"REFUSED: the corpus gives {sorted(r['id'] for r in plan)} for the DEV list {sorted(DEV_ENTRIES)}")
    return sorted(plan, key=lambda r: r["id"])


def _selftest() -> int:
    assert methodology_dev_list("x\nDEV_ENTRIES: [4, 5, 9]\ny") == [4, 5, 9]
    assert methodology_dev_list("nothing") == []
    assert not should_retry_infra({"result": {"verdict": "BLOCKED"}})
    assert should_retry_infra({"result": {"verdict": "INFRA_ERROR"}, "operations": []})
    assert not should_retry_infra({"result": {"verdict": "INFRA_ERROR"}, "operations": [{"role": "baseline", "outcome": "completed"}]})
    guard = budget.round_guard(budget.Spend())
    assert guard.ok, guard.reasons
    print("selftest ok: DEV list parse, infra re-queue rule, round-1 budget guard")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--go", action="store_true", help="actually run (spends money)")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--round", type=int, help="the DEV round number (1-6), for the records' labels")
    ap.add_argument("--tag", help="the sealed harness tag this round runs at (harness-v1.5.N)")
    ap.add_argument("--entry-cap-usd", type=float, help="the fixed per-entry cap (the owner's $2.50 from harness-v1.7; $1.50 through round 4)")
    ap.add_argument("--dev-total-usd", type=float, default=budget.DEV_TOTAL_CAP_USD,
                    help="the DEV total the HARD check uses (rule B4; $40.00 unless the owner writes another figure in chat)")
    ap.add_argument("--ledger-ceiling-usd", type=float, default=budget.LEDGER_CEILING_USD, help="the owner's ledger ceiling; raise only when the owner writes a new figure in chat")
    ap.add_argument("--resume", action="store_true", help="after an interruption: keep the valid records already written, run only the other entries")
    ap.add_argument("--log-file", help="write everything this process prints to this file (line-buffered, appended): for a run with no console")
    args = ap.parse_args(argv)
    if args.log_file:
        sys.stdout = sys.stderr = open(args.log_file, "a", buffering=1, encoding="utf-8", errors="replace")
    if args.selftest:
        return _selftest()
    if args.round is None or args.tag is None or args.entry_cap_usd is None:
        print("REFUSED: --round, --tag and --entry-cap-usd are required", file=sys.stderr)
        return 2
    if not 1 <= args.round <= 6:
        print("REFUSED: the protocol allows at most 6 DEV rounds", file=sys.stderr)
        return 2
    if abs(args.entry_cap_usd - budget.ENTRY_CAP_USD) > 1e-9:
        print(f"REFUSED: the pre-registered entry cap is ${budget.ENTRY_CAP_USD:.2f}", file=sys.stderr)
        return 2
    check_pre_registration()

    from app.services import gate_budget

    round_cap = round(len(DEV_ENTRIES) * args.entry_cap_usd, 2)
    gate_budget.check_gate_caps(round_cap, args.entry_cap_usd, len(DEV_ENTRIES))
    odir = ROOT / "runs" / "corpus_v2_batch" / args.tag / "dev"
    spend = budget.read_spend(ROOT, exclude=odir if args.resume else None)  # a resumed round's own records are what it continues, not a reason to refuse it
    guard = budget.round_guard(spend, ledger_ceiling_usd=args.ledger_ceiling_usd, round_cap_usd=round_cap, dev_total_cap_usd=args.dev_total_usd)
    print(f"budget: ledger ${guard.ledger_usd:.4f} (base ${budget.LEDGER_BASE_USD} + v1.5 DEV spend ${spend.total_usd:.4f}); ceiling ${args.ledger_ceiling_usd:.2f}; "
          f"DEV total cap ${args.dev_total_usd:.2f}; round cap ${round_cap:.2f}; TEST reserve ${budget.TEST_RESERVE_USD:.2f}", flush=True)
    if not guard.ok:
        for reason in guard.reasons:
            print(f"REFUSED: {reason}", file=sys.stderr, flush=True)
        return 4

    import run_corpus_v1_batch as drv

    try:
        frozen = {**drv.preflight("corpus-v2", args.tag), "arm": "treatment", "total_cap_usd": round_cap, "already_spent_usd": 0.0}
    except drv.PreflightError as exc:
        print(f"PREFLIGHT REFUSED ({args.tag}): {exc}", file=sys.stderr, flush=True)
        return 3
    plan = plan_entries(drv.entries_for("corpus-v2"))
    print(f"preflight OK at {frozen['head_commit'][:12]} (tag {args.tag}); DEV round {args.round}; fixed entry cap ${args.entry_cap_usd}; entries: "
          + ", ".join(f"#{r['id']} {r['name']}" for r in plan), flush=True)
    if not args.go:
        print("DRY RUN: nothing was run and nothing was spent (pass --go to run).")
        return 0

    odir.mkdir(parents=True, exist_ok=True)
    smoke = None
    for attempt in (1, 2):  # the v1.4.1 gate's first smoke failed on a slow line and passed on the retry: one more try, never more
        smoke = drv.run_smoke()
        (odir / f"upload_smoke_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json").write_text(json.dumps(smoke, indent=2) + "\n", encoding="utf-8")
        if smoke.get("ok"):
            break
        print(f"upload smoke test {attempt} failed", flush=True)
    if not (smoke or {}).get("ok"):
        print("REFUSING TO START: the pre-batch upload smoke test failed twice", file=sys.stderr, flush=True)
        return 3

    spent, records = 0.0, []
    for row in plan:
        path = odir / f"{row['id']:02d}_{row['name']}.json"
        if args.resume and path.is_file() and not drv.record_problems(path, row["name"], frozen):
            record = json.loads(path.read_text(encoding="utf-8"))
            records.append(record)
            spent += float(record["cost_guard"]["spent_usd"])
            print(f"#{row['id']:2} {row['name']} RESUMED from its valid record: {(record.get('result') or {}).get('verdict')}", flush=True)
            continue
        try:
            drv.PER_ENTRY_CAP_USD = gate_budget.entry_cap_for(round_cap, args.entry_cap_usd, spent)
        except gate_budget.GateBudgetError as exc:
            print(f"STOP: {exc}", flush=True)
            break
        meta = {**frozen, "entry_id": row["id"], "category": row["category"], "rules_matched": row["rules_matched"], "per_entry_cap_usd": drv.PER_ENTRY_CAP_USD,
                "total_cap_usd": round_cap, "dev_round": args.round, "protocol": "harness-v1.5 dev/test: DEV round"}
        for run_number in (1, 2):
            print(f"#{row['id']:2} {row['name']} starting (entry cap ${drv.PER_ENTRY_CAP_USD}; run {run_number})", flush=True)
            drv._run_live("corpus-v2", row["name"], frozen["corpus_hash"], meta, path)
            record = json.loads(path.read_text(encoding="utf-8"))
            spent += float(record["cost_guard"]["spent_usd"])
            result = record.get("result") or {}
            print(f"#{row['id']:2} -> {result.get('verdict')} {result.get('taxonomy_code') or result.get('reason_code') or ''} "
                  f"${record['cost_guard']['spent_usd']:.4f} API-reported + estimates (round total ${spent:.4f}; record {path.name})", flush=True)
            if run_number == 1 and not record.get("error") and should_retry_infra(record):
                keep = odir / "infra_retries"
                keep.mkdir(exist_ok=True)
                first = keep / f"{path.stem}.attempt1.json"
                path.replace(first)  # the first record, byte for byte, kept as evidence
                (keep / f"{path.stem}.attempt1.note.json").write_text(json.dumps({
                    "note": "INFRA_ERROR with no baseline execution: re-run once (METHODOLOGY re-queue rule); this record is the first attempt, moved unmodified",
                    "entry": row["id"], "tag": args.tag, "round": args.round, "reason_code": result.get("reason_code"),
                    "cost_usd_counted_in_ledger": record["cost_guard"]["spent_usd"]}, indent=2) + "\n", encoding="utf-8")
                continue
            break
        records.append(record)
        if record.get("error"):
            print(f"STOP: entry #{row['id']} ended without a verdict: {record['error']}", flush=True)
            break
    summary = {
        "round": args.round, "tag": args.tag, "entry_cap_usd": args.entry_cap_usd, "round_cap_usd": round_cap,
        "finished_at": datetime.now(timezone.utc).isoformat(), "entries": [
            {"entry": (r.get("batch") or {}).get("entry_id"), "name": (r.get("corpus_entry") or {}).get("name"), "verdict": (r.get("result") or {}).get("verdict"),
             "code": (r.get("result") or {}).get("taxonomy_code") or (r.get("result") or {}).get("reason_code"), "spent_usd": r["cost_guard"]["spent_usd"],
             "estimated_usd": r["cost_guard"].get("estimated_sandbox_spent_usd", 0.0)} for r in records],
        "round_spent_usd": round(spent, 6), "complete": len(records) == len(plan),
    }
    (odir / "round_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(summary, indent=2), flush=True)
    print(f"DEV ROUND {args.round} at {args.tag}: {'complete' if summary['complete'] else 'INCOMPLETE'}; spent ${spent:.4f} API-reported + estimates", flush=True)
    return 0 if summary["complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
