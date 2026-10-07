"""harness-v1.8, Phase 2: the 21 DEV-CONTAMINATED re-runs beside the verdicts the same entries had under harness-v1.5 / v1.7.2, read from the committed records only.

    backend/.venv/Scripts/python.exe reports/dev/v18/dev_results.py [--rederive] [--write]

Nothing here is a held-out result: the 21 entries were used to write harness-v1.8 (owner, 2026-10-07). `--rederive` recomputes each DEV record's `blocker` with the CURRENT
diagnosis rules from the record's own fields (a derived, unhashed field) and shows it beside the blocker the run stored. `--write` writes DEV_RESULTS.md / dev_results.json.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend"))
OLD_TEST = ROOT / "runs" / "corpus_v2_batch" / "harness-v1.5-final" / "test"
OLD_TESTB = ROOT / "runs" / "corpus_v3_batch" / "harness-v1.7.2" / "treatment"
OLD_OOS = ROOT / "runs" / "live_scan" / "oos_v1.7.2" / "scan_summary.json"
NEW = ROOT / "runs" / "dev_v18"
RAN = ("RUNS_CLEAN", "RUNS_AFTER_REPAIR")


def _rec(path: Path) -> dict:
    d = json.loads(path.read_text(encoding="utf-8"))
    if "result" in d:
        r, cert = d["result"], d.get("certificate") or {}
        return {"verdict": r.get("verdict"), "code": r.get("taxonomy_code") or r.get("reason_code"), "attempts": r.get("attempts") or [], "error_chain": r.get("error_chain") or [],
                "indeterminate_reason": r.get("indeterminate_reason") or "", "baseline": cert.get("baseline"), "full_log": cert.get("full_log") or "", "blocker": r.get("blocker"),
                "cost": (d.get("cost_guard") or {}).get("spent_usd"), "over_cap_estimated_only": (d.get("cost_guard") or {}).get("over_cap_estimated_only"),
                "seconds": (d.get("timing") or {}).get("elapsed_s") or d.get("elapsed_s")}
    return {}


def _find(folder: Path, i: int) -> Path | None:
    return next(iter(sorted(folder.glob(f"{i:02d}_*.json"))), None)


def _oos_rows(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else []


def collect(rederive: bool) -> list[dict]:
    from app.services import blocker as blocker_mod

    rows: list[dict] = []
    # round 1: all 16 corpus entries; round 2: only TEST-B #2 ovis, re-run after T2 was changed to pair the relaxed torchvision with the pinned torch (see FIXES_harness-v1.8.0.md)
    for set_name, old_dir, new_dir, ids, label in (("TEST-B", OLD_TESTB, NEW / "round1" / "TEST-B", range(1, 9), "TEST-B"), ("TEST", OLD_TEST, NEW / "round1" / "TEST", (1, 2, 6, 10, 13, 18, 19, 20), "TEST"),
                                                   ("TEST-B", OLD_TESTB, NEW / "round2" / "TEST-B", (2,), "TEST-B round 2")):
        for i in ids:
            old_p, new_p = _find(old_dir, i), _find(new_dir, i)
            if label.endswith("round 2") and new_p is None:
                continue
            old, new = (_rec(old_p) if old_p else {}), (_rec(new_p) if new_p else {})
            name = (new_p or old_p).stem[3:] if (new_p or old_p) else str(i)
            row = {"set": label, "id": i, "name": name, "old_verdict": old.get("verdict"), "old_code": old.get("code"), "new_verdict": new.get("verdict"), "new_code": new.get("code"),
                   "new_cost_usd": new.get("cost"), "over_cap_estimated_only": new.get("over_cap_estimated_only"), "old_cost_usd": old.get("cost"),
                   "indeterminate_reason": (new.get("indeterminate_reason") or "")[:140], "attempts": len(new.get("attempts") or [])}
            stored = new.get("blocker") or {}
            row["stored_blocker"] = {k: stored.get(k) for k in ("cause", "diagnosis", "error_line", "next_action", "fixable_by")} if stored else None
            if rederive and new:
                again = blocker_mod.report({k: new[k] for k in ("verdict", "error_chain", "attempts", "indeterminate_reason", "baseline", "full_log")})
                row["rederived_blocker"] = {k: (again or {}).get(k) for k in ("cause", "diagnosis", "error_line", "next_action", "fixable_by")} if again else None
            rows.append(row)
    old_oos = {r.get("repo_url"): r for r in _oos_rows(OLD_OOS)}
    for sub in ("round1-oos", "round1-oos-repeat"):
        for r in _oos_rows(NEW / sub / "OOS" / "scan_summary.json"):
            o = old_oos.get(r.get("repo_url")) or {}
            cost = r.get("cost") or {}
            from importlib import import_module

            sys.path.insert(0, str(ROOT / "reports"))
            usd = import_module("ledger_total").dev_scan_row_cost(r)
            stored = r.get("blocker") or {}
            rows.append({"set": "OOS" + ("-repeat" if sub.endswith("repeat") else ""), "id": None, "name": r.get("name"), "old_verdict": o.get("verdict"), "old_code": o.get("taxonomy_code"),
                         "new_verdict": r.get("verdict"), "new_code": r.get("taxonomy_code"), "new_cost_usd": usd, "over_cap_estimated_only": None, "old_cost_usd": (o.get("cost") or {}).get("guard_total_usd"),
                         "indeterminate_reason": (r.get("indeterminate_reason") or "")[:140], "attempts": None,
                         "stored_blocker": {k: stored.get(k) for k in ("cause", "diagnosis", "error_line", "next_action", "fixable_by")} if stored else None})
    return rows


def render(rows: list[dict]) -> str:
    out = ["| set | # | entry | v1.5 / v1.7.2 | DEV v1.8 | cost (API-reported + estimates) | diagnosis cause (basis) |", "|---|---|---|---|---|---|---|"]
    for r in rows:
        stored = r.get("rederived_blocker") or r.get("stored_blocker") or {}
        old = f"{r['old_verdict']} {r['old_code'] or ''}".strip()
        new = f"{r['new_verdict']} {r['new_code'] or ''}".strip()
        cost = f"${r['new_cost_usd']:.2f}" + (" (over cap, estimate only)" if r.get("over_cap_estimated_only") else "") if r["new_cost_usd"] is not None else ""
        out.append(f"| {r['set']} | {r['id'] or ''} | {r['name']} | {old} | {new} | {cost} | {stored.get('cause') or ''} ({stored.get('diagnosis') or ''}) |")
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rederive", action="store_true")
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()
    rows = collect(args.rederive)
    print(render(rows))
    ran = [r for r in rows if r["set"] in ("TEST", "TEST-B") and r["new_verdict"] in RAN]
    print(f"\nDEV (corpus 16): RAN {len(ran)} of {len([r for r in rows if r['set'] in ('TEST', 'TEST-B')])}; spent ${sum(r['new_cost_usd'] or 0 for r in rows if r['set'] in ('TEST', 'TEST-B')):.2f}")
    if args.write:
        (ROOT / "reports" / "dev" / "v18" / "dev_results.json").write_text(json.dumps(rows, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
