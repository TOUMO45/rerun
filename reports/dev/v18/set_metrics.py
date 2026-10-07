"""harness-v1.8, Phase 3: the per-set numbers the owner asked for, read from COMMITTED RECORDS ONLY (owner, 2026-10-07: "Hours tile stays out. Replace it with measured values from
committed records only: median wall-clock time and median API-reported cost to reach a diagnosis, per set"; "recovery-rate tile only from committed records").

    backend/.venv/Scripts/python.exe reports/dev/v18/set_metrics.py [--write]

Per set: N, RAN (the audited count, the same one `GET /batch/preregistered` serves: a stricken row is not counted), the non-running entries, how many carry a diagnosis (a stored
`blocker`), the MEDIAN wall-clock seconds and the MEDIAN API-reported cost of those entries, and the recovery rate (of the entries whose as-published run failed, the share that ended
RUNS_AFTER_REPAIR). Nothing is estimated or re-scored: a number is a field of a record, and the record is named. TEST, TEST-B and the out-of-sample scan are read as they are
(measurements of time and cost, not a re-score of what they found); the actionable-diagnosis rate is NOT computed here: it is scored by the committed rubric
(`DIAGNOSIS_RUBRIC.md`, `score_diagnosis.py`) and only for sets that have a committed key (the DEV records and TEST-C), never for the frozen ones.

"Cost" is the cost guard's API-REPORTED figure with the estimate of any killed step, as the ledger counts it (D-27, D-36): it is not what the account was billed (BILLED_READINGS.md).
"""
from __future__ import annotations

import argparse
import json
import statistics
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
RAN_VERDICTS = ("RUNS_CLEAN", "RUNS_AFTER_REPAIR")
NOT_RUNNING_WITH_DIAGNOSIS = ("BLOCKED", "INDETERMINATE", "TIMEOUT")
# the audit strikes the committed result files carry (backend/app/routers/batch.py AUDITS): the same two documented commands, struck for the same reason wherever they are re-run
STRIKES = {("test", 18), ("test_b", 6)}


def _json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _seconds(started: str | None, finished: str | None) -> float | None:
    try:
        return (datetime.fromisoformat(finished) - datetime.fromisoformat(started)).total_seconds()
    except (TypeError, ValueError):
        return None


def _median(values: list[float]) -> float | None:
    return round(statistics.median(values), 4) if values else None


def _entry_files(folder: Path) -> list[Path]:
    return sorted(p for p in folder.glob("[0-9][0-9]_*.json") if ".superseded" not in p.name)


def corpus_rows(folder: Path, key: str) -> list[dict]:
    """One row per batch record (`runs/<batch>/<NN>_<name>.json`): the fields the metrics read."""
    rows = []
    for path in _entry_files(folder):
        d = _json(path)
        result, cert, guard = d.get("result") or {}, d.get("certificate") or {}, d.get("cost_guard") or {}
        entry = int(path.name[:2])
        verdict = result.get("verdict")
        rows.append({"entry": entry, "name": path.stem[3:], "verdict": verdict, "struck": (key, entry) in STRIKES and verdict in RAN_VERDICTS,  # a strike applies to a RUNS_* verdict of that command, not to a later honest BLOCKED
                     "has_diagnosis": result.get("blocker") is not None, "seconds": d.get("pipeline_duration_s"), "cost_usd": guard.get("spent_usd"),
                     "baseline_failed": (cert.get("baseline") or {}).get("result") == "FAILS", "source": path.relative_to(ROOT).as_posix()})
    return rows


def oos_rows(summary: Path) -> list[dict]:
    import sys

    sys.path.insert(0, str(ROOT / "reports"))
    from ledger_total import dev_scan_row_cost

    rows = []
    for i, r in enumerate(_json(summary), start=1):
        baseline_failed = False
        cert = ROOT / (r.get("certificate") or "")
        if r.get("certificate") and cert.is_file():
            baseline_failed = (_json(cert).get("baseline") or {}).get("result") == "FAILS"
        rows.append({"entry": i, "name": r.get("name"), "verdict": r.get("verdict"), "struck": False, "has_diagnosis": r.get("blocker") is not None,
                     "seconds": _seconds(r.get("started_at"), r.get("finished_at")), "cost_usd": dev_scan_row_cost(r), "baseline_failed": baseline_failed,
                     "source": summary.relative_to(ROOT).as_posix()})
    return rows


def metrics(rows: list[dict], *, ran_override: int | None = None) -> dict:
    ran = ran_override if ran_override is not None else sum(1 for r in rows if r["verdict"] in RAN_VERDICTS and not r["struck"])
    struck = sum(1 for r in rows if r["struck"])
    diagnosed = [r for r in rows if r["verdict"] in NOT_RUNNING_WITH_DIAGNOSIS and r["has_diagnosis"]]
    failed_first = [r for r in rows if r["baseline_failed"]]
    recovered = [r for r in failed_first if r["verdict"] == "RUNS_AFTER_REPAIR" and not r["struck"]]  # an audited false success is not a recovery
    secs = [float(r["seconds"]) for r in diagnosed if r["seconds"] is not None]
    cost = [float(r["cost_usd"]) for r in diagnosed if r["cost_usd"] is not None]
    return {"n": len(rows), "ran": ran, "struck_by_audit": struck, "non_running": sum(1 for r in rows if r["verdict"] not in RAN_VERDICTS), "diagnosed": len(diagnosed),
            "median_seconds_to_diagnosis": _median(secs), "median_api_reported_cost_usd_to_diagnosis": _median(cost), "measured_over": {"seconds": len(secs), "cost": len(cost)},
            "recovery": {"as_published_failed": len(failed_first), "recovered_after_repair": len(recovered)}}


def collect() -> dict:
    out: dict[str, dict] = {}
    # the audited RAN counts of the frozen sets come from the one place the demo serves them from
    import sys

    sys.path.insert(0, str(ROOT / "backend"))
    from app.routers.batch import preregistered_results

    served = {s["key"]: s for s in preregistered_results(ROOT)["sets"]}
    frozen = (("test", "TEST (harness-v1.5-final)", ROOT / "runs/corpus_v2_batch/harness-v1.5-final/test", "corpus"),
              ("test_b", "TEST-B (harness-v1.7.2)", ROOT / "runs/corpus_v3_batch/harness-v1.7.2/treatment", "corpus"),
              ("oos", "Out-of-sample scan (harness-v1.7.2)", ROOT / "runs/live_scan/oos_v1.7.2/scan_summary.json", "oos"))
    for key, title, path, kind in frozen:
        rows = corpus_rows(path, key) if kind == "corpus" else oos_rows(path)
        counts = {r["entry"]: r["counts"] for r in served[key]["rows"]}
        for r in rows:  # a RUNS_* verdict that the audit attached to the result does not count (TEST #18's neighbours, steamctl's false success) is struck here too
            if r["verdict"] in RAN_VERDICTS and counts.get(r["entry"]) is False:
                r["struck"] = True
        out[key] = {"title": title, "frozen": True, "dev": False, **metrics(rows, ran_override=served[key]["count"]), "sources": sorted({r["source"] for r in rows})}
    dev_corpus = corpus_rows(ROOT / "runs/dev_v18/round1/TEST-B", "test_b") + corpus_rows(ROOT / "runs/dev_v18/round1/TEST", "test")
    out["dev_v18_corpus"] = {"title": "harness-v1.8 DEV re-run of the 16 corpus entries (DEV-CONTAMINATED: the fixes were written from these)", "frozen": False, "dev": True,
                             **metrics(dev_corpus), "sources": sorted({r["source"] for r in dev_corpus})}
    dev_oos = oos_rows(ROOT / "runs/dev_v18/round1-oos/OOS/scan_summary.json")
    out["dev_v18_oos"] = {"title": "harness-v1.8 DEV re-run of the 5 out-of-sample repositories (DEV-CONTAMINATED)", "frozen": False, "dev": True, **metrics(dev_oos),
                          "sources": sorted({r["source"] for r in dev_oos})}
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()
    sets = collect()
    doc = {"what": "Per-set measurements read from committed records (reports/dev/v18/set_metrics.py). Medians are over the non-running entries that carry a diagnosis; "
                   "cost is API-REPORTED with the estimate of killed steps (not billed). Small N: counts, not rates.", "sets": sets}
    for key, s in sets.items():
        print(f"{key:16} n={s['n']:2} ran={s['ran']:2} struck={s['struck_by_audit']} non_running={s['non_running']:2} diagnosed={s['diagnosed']:2} median {s['median_seconds_to_diagnosis']} s, "
              f"${s['median_api_reported_cost_usd_to_diagnosis']} (over {s['measured_over']}); recovery {s['recovery']['recovered_after_repair']}/{s['recovery']['as_published_failed']}")
    if args.write:
        (ROOT / "reports" / "dev" / "v18" / "set_metrics.json").write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
