"""The whole API-REPORTED ledger in one number (owner, chat 2026-10-05: ceiling $300.00, BILLED floor $10.00; print the worst case before every paid phase).

    backend/.venv/Scripts/python.exe reports/ledger_total.py [--next-phase-cap-usd X --what "..."]

Sums, from the records on disk (each with the estimate of any killed step, as each source records it):
  program   reports/corpus-v2.1/v1.5/devtest/budget.py: LEDGER_BASE_USD + read_spend() (every DEV round, the seals and extras in ledger_extras.json)
  TEST      runs/corpus_v2_batch/harness-v1.5-final/test/test_result.json spend.total_usd + its upload smoke tests (read_spend reads dev/ folders only)
  scans     every runs/live_scan/**/scan_summary.json row: cost.guard_total_usd, else cost.sandbox_api_reported_usd
  TEST-B    runs/corpus_v3_batch/*/treatment/test_b_result.json spend.total_usd + its upload smoke test, when it exists
  v1.8 DEV  runs/dev_v18/**: every record's cost_guard.spent_usd (the 16 corpus entries re-run as DEV-CONTAMINATED under harness-v1.8) and every scan_summary.json row (the 5
            out-of-sample repositories re-run the same way), plus upload smoke tests (harness-v1.8, owner 2026-10-07)
A seal of harness-v1.7.2 or later goes into ledger_extras.json by hand, as the earlier seals did (no script writes it).
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CEILING_USD = 300.00
BILLED_FLOOR_USD = 10.00


def _budget():
    spec = importlib.util.spec_from_file_location("budget", ROOT / "reports" / "corpus-v2.1" / "v1.5" / "devtest" / "budget.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["budget"] = mod  # its dataclasses look their module up while the class is built
    spec.loader.exec_module(mod)
    return mod


def _smoke(folder: Path) -> float:
    """The pre-batch upload smoke tests beside a batch's records (their result file's spend leaves them out)."""
    return sum(float(r.get("cost_usd") or 0.0) for p in folder.glob("upload_smoke_*.json")
               for r in json.loads(p.read_text(encoding="utf-8")).get("runs") or [])


def dev_scan_row_cost(row: dict) -> float:
    """One DEV out-of-sample summary row, with the estimate of a killed step: the scan script's `guard_total_usd` is None when its last guard line has no `remaining today`
    figure (a step killed at the wall clock logs `recorded $9.1047 (0.0009 measured + estimate for the killed step)`), and `sandbox_api_reported_usd` then holds only the
    measured part. The estimate part (recorded minus measured) is added, as the ledger counts every other killed step (harness-v1.8 DEV, mud-pi: $9.1047, 0.0009 measured)."""
    cost = row.get("cost") or {}
    reading = cost.get("guard_total_usd")
    if reading is not None:
        return float(reading)
    total = float(cost.get("sandbox_api_reported_usd") or 0.0)
    for line in cost.get("estimated_lines") or []:
        m = re.search(r"recorded \$(?P<recorded>[0-9.]+) \((?P<measured>[0-9.]+) measured \+ estimate", line)
        if m:
            total += max(0.0, float(m.group("recorded")) - float(m.group("measured")))
    return total


def parts() -> dict[str, float]:
    budget = _budget()
    out = {"program (base + DEV + seals + extras)": round(budget.LEDGER_BASE_USD + budget.read_spend(ROOT).total_usd, 6)}
    test = ROOT / "runs" / "corpus_v2_batch" / "harness-v1.5-final" / "test" / "test_result.json"
    out["TEST (harness-v1.5-final)"] = round((float(json.loads(test.read_text(encoding="utf-8"))["spend"]["total_usd"]) if test.is_file() else 0.0)
                                             + _smoke(test.parent), 6)
    scans = 0.0
    for path in (ROOT / "runs" / "live_scan").glob("**/scan_summary.json"):
        for row in json.loads(path.read_text(encoding="utf-8")):
            cost = row.get("cost") or {}
            scans += float(cost.get("guard_total_usd") or cost.get("sandbox_api_reported_usd") or 0.0)
    out["live scans"] = round(scans, 6)
    test_b = 0.0
    for path in (ROOT / "runs" / "corpus_v3_batch").glob("*/treatment/test_b_result.json"):
        test_b += float(json.loads(path.read_text(encoding="utf-8"))["spend"]["total_usd"]) + _smoke(path.parent)
    out["TEST-B"] = round(test_b, 6)
    # harness-v1.8: DEV-CONTAMINATED re-runs of the 21 held-out entries (runs/dev_v18/); records the runner wrote plus the scan summaries
    dev18 = 0.0
    base = ROOT / "runs" / "dev_v18"
    for path in base.glob("**/[0-9][0-9]_*.json"):
        try:
            dev18 += float((json.loads(path.read_text(encoding="utf-8")).get("cost_guard") or {}).get("spent_usd") or 0.0)
        except ValueError:
            continue
    for path in base.glob("**/scan_summary.json"):
        for row in json.loads(path.read_text(encoding="utf-8")):
            dev18 += dev_scan_row_cost(row)
    dev18 += sum(_smoke(p.parent) for p in {q.parent: q for q in base.glob("**/upload_smoke_*.json")}.values())
    out["v1.8 DEV (runs/dev_v18, DEV-CONTAMINATED)"] = round(dev18, 6)
    return out


def total() -> float:
    return round(sum(parts().values()), 6)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--next-phase-cap-usd", type=float, default=0.0)
    ap.add_argument("--what", default="next paid phase")
    args = ap.parse_args()
    for name, usd in parts().items():
        print(f"  {name:<40} ${usd:9.4f}")
    now = total()
    worst = now + args.next_phase_cap_usd
    print(f"  {'ledger now (API-REPORTED)':<40} ${now:9.4f}")
    print(f"  worst case after {args.what}: ${now:.4f} + ${args.next_phase_cap_usd:.2f} = ${worst:.4f} of the ${CEILING_USD:.2f} ceiling "
          f"({'OK' if worst <= CEILING_USD + 1e-9 else 'REFUSED'})")
    return 0 if worst <= CEILING_USD + 1e-9 else 4


if __name__ == "__main__":
    raise SystemExit(main())
