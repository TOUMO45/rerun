"""Outcome ladder of the DEV and gate entries, computed offline from the committed records (no network, no spend; standard library only).

TEST firewall (METHODOLOGY rule F): records are listed and opened only through `reports/corpus-v2.1/v1.5/devtest/firewall.py`, so a TEST entry is refused by its file name
before it is opened. (Disclosure: on 2026-10-03 an ad-hoc exploratory script globbed every record before this module was written; its output was discarded, nothing was
derived from it, and this committed script is the only one whose output is reported.)

Per record, the ladder is `backend/app/services/outcome_levels.compute` (harness-v1.6, item L) applied to the stored fields, so that this offline table and the
`outcome_levels` field of a v1.6 record are one function (a test asserts it):
  FIRST_ERROR_CLEARED  error_chain[0] was no longer the failure after a later attempt (`cleared_by`; for a pre-v1.6 RUNS_AFTER_REPAIR record with one link the verdict says so);
                       `first_error_cleared_by` = the origin of that attempt (time_machine / a rule name / model);
  ENV_RESOLVED         the last link of the error chain is not a dependency or system-library class, or the verdict is RUNS_*;
  ENTRYPOINT_RUNS      result.verdict is RUNS_CLEAN or RUNS_AFTER_REPAIR (the smoke criterion, as recorded).
  BLOCKER              the last link of result.error_chain: class@phase (attribution), with the first line of the error.
Every figure is a count of stored fields (API-REPORTED by the project's tagging rule). Output: levels.json, levels.md beside this script.
"""
from __future__ import annotations
import json, sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "reports" / "corpus-v2.1" / "v1.5" / "devtest"))
import firewall  # noqa: E402

sys.path.insert(0, str(ROOT / "backend"))
from app.services import outcome_levels  # noqa: E402  (harness-v1.6: the SAME pure function the harness stores on new records)

def main() -> int:
    rows = []
    for f in firewall.analysis_records(ROOT / "runs" / "corpus_v2_batch", "harness-v1.*/*/[0-9][0-9]_*.json"):
        try: r = json.loads(firewall.read_record_text(f))
        except ValueError: continue
        res = r.get("result") or {}
        if "verdict" not in res: continue
        chain = res.get("error_chain") or []
        first, last = (chain[0] if chain else {}), (chain[-1] if chain else {})
        levels = outcome_levels.compute({"verdict": res.get("verdict"), "error_chain": chain, "attempts": res.get("attempts") or []})
        rows.append({
            "version": f.parts[-3], "arm": f.parts[-2], "entry": firewall.entry_id_of(f), "record": f.relative_to(ROOT).as_posix(),
            "verdict": res.get("verdict"), "taxonomy": res.get("taxonomy_code"),
            "first_class": first.get("class"), "first_phase": first.get("phase"), "first_cleared": levels["first_error_cleared"],
            "first_cleared_origin": levels["first_error_cleared_by"] if levels["first_error_cleared"] else None,
            "env_resolved": levels["env_resolved"],
            "entrypoint_runs": levels["entrypoint_runs"],
            "blocker_class": last.get("class"), "blocker_phase": last.get("phase"), "blocker_attribution": last.get("attribution"),
            "blocker_error": (last.get("error") or "")[:140], "chain_length": len(chain),
        })
    out = ROOT / "reports" / "dev" / "levels"
    (out / "levels.json").write_text(json.dumps({"rows": rows}, indent=1), encoding="utf-8")
    by = defaultdict(list)
    for row in rows: by[(row["version"], row["arm"])].append(row)
    L = ["# Outcome ladder of the DEV and gate entries, from the committed records (offline; every figure is a count of stored fields)", "",
         "TEST entries are absent by the firewall (rule F). Definitions are in `compute_levels.py`. FIRST_ERROR_CLEARED = the as-published failure was cleared by a later attempt,",
         "with the origin of that attempt (`time_machine` / rule names = deterministic, no model call; `model` = a model proposal that passed the gate). ENV_RESOLVED = the last recorded",
         "blocker is not a dependency or system-library error (the environment stopped being what blocks the run). ENTRYPOINT_RUNS = verdict RUNS_* (smoke criterion, as recorded).", "",
         "| version | arm | records | FIRST_ERROR_CLEARED (by origin) | ENV_RESOLVED | ENTRYPOINT_RUNS | final blockers (class@phase: n) |", "|---|---|---|---|---|---|---|"]
    for (v, a), rs in sorted(by.items()):
        n = len(rs); fc = Counter(r["first_cleared_origin"] for r in rs if r["first_cleared"])
        env = sum(r["env_resolved"] for r in rs); runs = sum(r["entrypoint_runs"] for r in rs)
        bl = Counter(f"{r['blocker_class']}@{r['blocker_phase']}" for r in rs if not r["entrypoint_runs"])
        L.append(f"| {v} | {a} | {n} | {sum(fc.values())} ({', '.join(f'{k}: {c}' for k, c in fc.most_common())}) | {env} | {runs} | "
                 + ", ".join(f"{k}: {c}" for k, c in bl.most_common()) + " |")
    L += ["", "## Per record", "", "| entry | version | arm | verdict | first error (class@phase) | cleared by | ENV_RESOLVED | final blocker | error |", "|---|---|---|---|---|---|---|---|---|"]
    for row in sorted(rows, key=lambda r: (r["entry"], r["version"], r["arm"])):
        L.append(f"| {row['entry']:02d} | {row['version']} | {row['arm']} | {row['verdict']} | {row['first_class']}@{row['first_phase']} | {row['first_cleared_origin'] or '-'} | "
                 f"{'yes' if row['env_resolved'] else 'no'} | {row['blocker_class']}@{row['blocker_phase']} ({row['blocker_attribution']}) | `{row['blocker_error'].replace('|','/').replace(chr(10),' ')}` |")
    (out / "levels.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L[:7 + len(by)]))
    return 0

if __name__ == "__main__":
    sys.exit(main())
