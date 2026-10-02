"""The owner's seal -> gate rule (METHODOLOGY, "Seal of harness-v1.4.0", unchanged since): the gate starts by itself only if every seal check passed, the branch-run cost is at most $0.15
API-reported, and the seal's spend is within its cap. Otherwise stop and report. Reads what the seal left; spends nothing.

    backend/.venv/Scripts/python.exe reports/corpus-v2.1/v1.4.3/seal/check_seal_to_gate.py --cap 1.50       # exit 0 = the rule is satisfied, 1 = it is not
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
SEAL = ROOT / "runs" / "sandbox_verification" / "v1.4.3-seal"
STAGES = ("new", "v141", "v142", "v140", "final")
BRANCH_RUN_LIMIT_USD = 0.15
BRANCH_RUN_RECORDS = ("v142/run1_B_branch_run.json", "v140/run1_B_branch_run.json")  # the same operation in two stages: both are checked


def check(cap: float, seal: Path = SEAL) -> tuple[bool, list[str]]:
    problems: list[str] = []
    summary_path = seal / "SEAL_RUN.json"
    if not summary_path.is_file():
        return False, ["SEAL_RUN.json is missing: the seal did not run"]
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    for stage in STAGES:
        entry = summary.get("stages", {}).get(stage)
        if not entry or entry.get("ok") is not True:
            problems.append(f"stage {stage} is missing or did not pass")
            continue
        for rel in entry.get("records", []):
            record = json.loads((ROOT / rel).read_text(encoding="utf-8")) if (ROOT / rel).is_file() else None
            if record is None:
                problems.append(f"{rel}: the record is missing")
            elif record.get("ok") is not True and not record.get("informational"):
                problems.append(f"{rel}: ok is not true")
    for rel in BRANCH_RUN_RECORDS:
        path = seal / rel
        cost = json.loads(path.read_text(encoding="utf-8")).get("measured_branch_run_usd") if path.is_file() else None
        if cost is None:
            problems.append(f"{rel}: no measured branch-run cost")
        elif cost > BRANCH_RUN_LIMIT_USD:
            problems.append(f"{rel}: branch-run cost ${cost:.6f} is above ${BRANCH_RUN_LIMIT_USD}")
    spent = sum(s.get("cost_usd", 0.0) for s in summary.get("stages", {}).values())
    if spent > cap + 1e-9:
        problems.append(f"seal spend ${spent:.4f} is above the cap ${cap:.2f}")
    return not problems, problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cap", type=float, required=True)
    args = ap.parse_args(argv)
    ok, problems = check(args.cap, SEAL)
    print("SEAL -> GATE: " + ("the rule is satisfied" if ok else "NOT satisfied: " + "; ".join(problems)))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
