"""The TEST phase of the v1.5 dev/test protocol (METHODOLOGY, section T): the 8 TEST entries of corpus-v2, TREATMENT, ONCE each, at the frozen tag, then the sustained runs.

    backend/.venv/Scripts/python.exe reports/corpus-v2.1/v1.5/test/run_test_phase.py --selftest
    backend/.venv/Scripts/python.exe reports/corpus-v2.1/v1.5/test/run_test_phase.py --tag harness-v1.5-final --test-cap-usd C --entry-cap-usd 1.50           # DRY RUN
    backend/.venv/Scripts/python.exe reports/corpus-v2.1/v1.5/test/run_test_phase.py --tag harness-v1.5-final --test-cap-usd C --entry-cap-usd 1.50 --go      # spends money

Nothing here is run before the freeze: the TEST firewall (devtest/firewall.py) is lifted only by this script, only after the tag `harness-v1.5-final` exists locally AND on origin at the
same commit, the harness paths at HEAD are that tag's, and the tag is not the tag of any DEV round. Entries run in ascending id, once each; an entry that ends INFRA_ERROR with no
baseline execution is re-run ONCE (the first record is kept unmodified under infra_retries/ with a note); no other re-run exists. After the 8 entries, the D-42 sustained run of every RUNS_*
entry whose smoke run was alive at its limit (app.services.sustained_run), funded from what the TEST cap has left, split equally among the runs that need one.

The primary metric is computed HERE, from the definition pre-registered in METHODOLOGY ("Confirmed"), and written to test_result.json with the DEV rounds' counts beside it:
a TEST entry counts iff its verdict is RUNS_CLEAN / RUNS_AFTER_REPAIR and (i) its final run is `baseline_complete` or `smoke_exited`, or (ii) its sustained outcome is `completed`, or
(iii) its sustained outcome is `running_at_limit` with `funded_seconds` = 600 and no funding limit. Everything else is listed as not confirmed, with its outcome. The count is reported
whatever it is; the target (3 of 8) is stated beside it, never used to choose what is run.

Run it DETACHED (Task Scheduler, pythonw, --log-file; reports/corpus-v2.1/v1.5/test/launch_test.cmd): a paid batch is never a child of a session (D-43).
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
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

TARGET = 3
TEST_ENTRIES = tuple(sorted(split.split()["test"]))
RUNS_VERDICTS = ("RUNS_CLEAN", "RUNS_AFTER_REPAIR")
HARNESS_PATHS = ("backend/app", "backend/pyproject.toml", "scripts", "frontend/src", ".gitattributes")
FINAL_TAG = "harness-v1.5-final"
SUSTAINED_SECONDS = 600


def _load(rel: str, name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()


def check_frozen(tag: str, git=_git) -> None:
    """The freeze is real: the final tag exists locally and on origin at the same commit, HEAD's harness paths are the tag's, and it is not a DEV round's tag."""
    if tag != FINAL_TAG:
        raise SystemExit(f"REFUSED: the TEST phase runs at {FINAL_TAG} only (got {tag})")
    try:
        local = git("rev-parse", f"refs/tags/{tag}^{{commit}}")
    except subprocess.CalledProcessError as exc:
        raise SystemExit(f"REFUSED: the tag {tag} does not exist: freeze first") from exc
    remote = git("ls-remote", "origin", f"refs/tags/{tag}^{{}}") or git("ls-remote", "origin", f"refs/tags/{tag}")
    if not remote or remote.split()[0] != local:
        raise SystemExit(f"REFUSED: origin does not have {tag} at {local} (got {remote!r}): push the tag before any TEST entry runs")
    changed = git("diff", "--name-only", tag, "HEAD", "--", *HARNESS_PATHS)
    if changed:
        raise SystemExit(f"REFUSED: the harness paths differ from {tag}: {changed.splitlines()[:5]}")
    for dev_tag in git("tag", "--list", "harness-v1.[5-9].[0-9]*").splitlines():
        if git("rev-parse", f"refs/tags/{dev_tag}^{{commit}}") == local:
            raise SystemExit(f"REFUSED: {tag} is the same commit as the DEV round tag {dev_tag}: the freeze must be its own commit")


def confirmation(record: dict, sustained: dict | None) -> dict:
    """PURE. The pre-registered 'confirmed' definition applied to one TEST entry: {verdict, code, kind, sustained_outcome, funded_seconds, confirmed, why}."""
    from app.services import sustained_run

    result = record.get("result") or {}
    verdict = result.get("verdict")
    out = {"entry": (record.get("batch") or {}).get("entry_id"), "name": (record.get("corpus_entry") or {}).get("name"), "verdict": verdict,
           "code": result.get("taxonomy_code") or result.get("reason_code") or "", "kind": None, "sustained_outcome": None, "funded_seconds": None,
           "confirmed": False, "why": ""}
    if verdict not in RUNS_VERDICTS:
        out["why"] = f"verdict {verdict}: not a RUNS_* verdict"
        return out
    final = sustained_run.final_run_of(record)
    out["kind"] = final["kind"] if final else None
    if final and final["kind"] in ("baseline_complete", "smoke_exited"):
        out.update(confirmed=True, why=f"(i) {final['kind']}: the documented command exited 0 by itself")
        return out
    if sustained is None:
        out["why"] = f"{out['kind']}: no sustained run was made or recorded; the smoke verdict stands unconfirmed"
        return out
    outcome = sustained.get("outcome")
    out.update(sustained_outcome=outcome, funded_seconds=sustained.get("funded_seconds"))
    if outcome == "completed":
        out.update(confirmed=True, why="(ii) the sustained run completed (exit 0)")
    elif outcome == "running_at_limit" and sustained.get("funded_seconds") == SUSTAINED_SECONDS and "funding-limited" not in str(sustained.get("label", "")):
        out.update(confirmed=True, why=f"(iii) the command ran the full {SUSTAINED_SECONDS} s without failing")
    else:
        out["why"] = f"not confirmed: sustained outcome {outcome} (funded {sustained.get('funded_seconds')} s): {str(sustained.get('label', ''))[:200]}"
    return out


def evaluate(records: list[dict], sustained: list[dict], dev_rounds: dict[int, int] | None = None) -> dict:
    """PURE. The TEST result: the count over the 8 entries against the target, every entry's confirmation, and the DEV rounds' counts beside it."""
    by_entry = {d.get("entry"): d for d in sustained if d}
    rows = [confirmation(r, by_entry.get((r.get("batch") or {}).get("entry_id"))) for r in sorted(records, key=lambda r: (r.get("batch") or {}).get("entry_id"))]
    count = sum(1 for r in rows if r["confirmed"])
    smoke = sum(1 for r in rows if r["verdict"] in RUNS_VERDICTS)
    return {"split": "TEST (not touched by the v1.5 rounds; prior exposure in v1.3.2 is stated in METHODOLOGY)", "entries": len(TEST_ENTRIES), "ran": len(records),
            "primary_metric": "TEST entries with a RUNS_CLEAN / RUNS_AFTER_REPAIR verdict confirmed by the D-42 sustained check or by completion", "confirmed_count": count,
            "target": TARGET, "target_met": count >= TARGET and len(records) == len(TEST_ENTRIES), "runs_verdict_count_at_smoke_level": smoke,
            "dev_rounds_smoke_level_counts": dev_rounds or {}, "rows": rows,
            "note": "a count over 8 entries, one run each: not a rate; a confirmed run says the documented command ran 600 s or to completion, not that the paper's result was reproduced"}


def _selftest() -> int:
    assert tuple(split.split()["test"]) == TEST_ENTRIES and len(TEST_ENTRIES) == 8
    assert evaluate([], [])["confirmed_count"] == 0 and evaluate([], [])["target_met"] is False
    row = confirmation({"result": {"verdict": "BLOCKED"}, "batch": {"entry_id": 1}}, None)
    assert row["confirmed"] is False and "not a RUNS_" in row["why"]
    print("selftest ok: the confirmation definition and the entry list")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--go", action="store_true", help="actually run (spends money)")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--tag", default=FINAL_TAG)
    ap.add_argument("--test-cap-usd", type=float, help="the TEST phase cap: the ledger ceiling less the ledger at the freeze (entries at their cap AND the sustained runs)")
    ap.add_argument("--entry-cap-usd", type=float, help="the fixed per-entry cap (the owner's $1.50)")
    ap.add_argument("--resume", action="store_true", help="after an interruption: keep the valid records already written, run only the other entries")
    ap.add_argument("--log-file", help="write everything this process prints to this file (line-buffered, appended)")
    args = ap.parse_args(argv)
    if args.log_file:
        sys.stdout = sys.stderr = open(args.log_file, "a", buffering=1, encoding="utf-8", errors="replace")
    if args.selftest:
        return _selftest()
    if args.test_cap_usd is None or args.entry_cap_usd is None:
        print("REFUSED: --test-cap-usd and --entry-cap-usd are required", file=sys.stderr)
        return 2
    if abs(args.entry_cap_usd - budget.ENTRY_CAP_USD) > 1e-9:
        print(f"REFUSED: the pre-registered entry cap is ${budget.ENTRY_CAP_USD:.2f}", file=sys.stderr)
        return 2
    run_dev = _load("reports/corpus-v2.1/v1.5/dev/run_dev_round.py", "run_dev_round")
    run_dev.check_pre_registration()
    from app.services import gate_budget

    round_cap = round(len(TEST_ENTRIES) * args.entry_cap_usd, 2)
    gate_budget.check_gate_caps(args.test_cap_usd, args.entry_cap_usd, len(TEST_ENTRIES))
    spend = budget.read_spend(ROOT)
    ledger = budget.LEDGER_BASE_USD + spend.total_usd
    if ledger + args.test_cap_usd > budget.LEDGER_CEILING_USD + 1e-9:
        print(f"REFUSED: ledger ${ledger:.4f} + the TEST cap ${args.test_cap_usd:.2f} passes the ${budget.LEDGER_CEILING_USD:.2f} ledger ceiling", file=sys.stderr)
        return 4
    check_frozen(args.tag)
    import run_corpus_v1_batch as drv

    try:
        frozen = {**drv.preflight("corpus-v2", args.tag), "arm": "treatment", "total_cap_usd": args.test_cap_usd, "already_spent_usd": 0.0}
    except drv.PreflightError as exc:
        print(f"PREFLIGHT REFUSED ({args.tag}): {exc}", file=sys.stderr, flush=True)
        return 3
    os.environ[firewall.FROZEN_ENV] = "1"  # the freeze: from here the TEST entries may be opened and run
    rows = {r["id"]: r for r in drv.entries_for("corpus-v2")}
    plan = [rows[i] for i in TEST_ENTRIES]
    odir = ROOT / "runs" / "corpus_v2_batch" / args.tag / "test"
    print(f"preflight OK at {frozen['head_commit'][:12]} (tag {args.tag}); TEST phase; ledger ${ledger:.4f}; TEST cap ${args.test_cap_usd}; entry cap ${args.entry_cap_usd}; entries: "
          + ", ".join(f"#{r['id']} {r['name']}" for r in plan), flush=True)
    if not args.go:
        print("DRY RUN: nothing was run and nothing was spent (pass --go to run).")
        return 0

    odir.mkdir(parents=True, exist_ok=True)
    smoke = None
    for attempt in (1, 2):
        smoke = drv.run_smoke()
        (odir / f"upload_smoke_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json").write_text(json.dumps(smoke, indent=2) + "\n", encoding="utf-8")
        if smoke.get("ok"):
            break
        print(f"upload smoke test {attempt} failed", flush=True)
    if not (smoke or {}).get("ok"):
        print("REFUSING TO START: the pre-batch upload smoke test failed twice", file=sys.stderr, flush=True)
        return 3

    spent, records, paths = 0.0, [], {}
    for row in plan:
        path = odir / f"{row['id']:02d}_{row['name']}.json"
        if args.resume and path.is_file() and not drv.record_problems(path, row["name"], frozen):
            record = json.loads(path.read_text(encoding="utf-8"))
            records.append(record)
            paths[row["name"]] = path
            spent += float(record["cost_guard"]["spent_usd"])
            print(f"#{row['id']:2} {row['name']} RESUMED from its valid record: {(record.get('result') or {}).get('verdict')}", flush=True)
            continue
        try:
            drv.PER_ENTRY_CAP_USD = gate_budget.entry_cap_for(args.test_cap_usd, args.entry_cap_usd, spent)
        except gate_budget.GateBudgetError as exc:
            print(f"STOP: {exc}", flush=True)
            break
        meta = {**frozen, "entry_id": row["id"], "category": row["category"], "rules_matched": row["rules_matched"], "per_entry_cap_usd": drv.PER_ENTRY_CAP_USD,
                "total_cap_usd": args.test_cap_usd, "protocol": "harness-v1.5 dev/test: TEST phase"}
        for run_number in (1, 2):
            print(f"#{row['id']:2} {row['name']} starting (entry cap ${drv.PER_ENTRY_CAP_USD}; run {run_number})", flush=True)
            drv._run_live("corpus-v2", row["name"], frozen["corpus_hash"], meta, path)
            record = json.loads(path.read_text(encoding="utf-8"))
            spent += float(record["cost_guard"]["spent_usd"])
            result = record.get("result") or {}
            print(f"#{row['id']:2} -> {result.get('verdict')} {result.get('taxonomy_code') or result.get('reason_code') or ''} "
                  f"${record['cost_guard']['spent_usd']:.4f} API-reported + estimates (TEST total ${spent:.4f}; record {path.name})", flush=True)
            if run_number == 1 and not record.get("error") and run_dev.should_retry_infra(record):
                keep = odir / "infra_retries"
                keep.mkdir(exist_ok=True)
                path.replace(keep / f"{path.stem}.attempt1.json")  # the first record, byte for byte
                (keep / f"{path.stem}.attempt1.note.json").write_text(json.dumps({
                    "note": "INFRA_ERROR with no baseline execution: re-run once (METHODOLOGY re-queue rule); this record is the first attempt, moved unmodified",
                    "entry": row["id"], "tag": args.tag, "reason_code": result.get("reason_code"), "cost_usd_counted_in_ledger": record["cost_guard"]["spent_usd"]}, indent=2) + "\n",
                    encoding="utf-8")
                continue
            break
        records.append(record)
        paths[row["name"]] = path
        if record.get("error"):
            print(f"STOP: entry #{row['id']} ended without a verdict: {record['error']}", flush=True)
            break

    sustained, sustained_cost, sustained_error = [], 0.0, None
    if records:
        from app.config import get_settings

        gate = _load("reports/corpus-v2.1/v1.4.3/gate/run_gate_v143.py", "run_gate_v143")
        settings = get_settings()
        try:
            sustained, sustained_cost = gate.sustained_phase(records, paths, gate_cap_usd=args.test_cap_usd, spent_usd=spent, odir=odir,
                                                             api_key=settings.nebius_api_key, project_id=settings.nebius_project_id)
        except Exception as exc:  # noqa: BLE001 - a failed sustained phase must never lose the entry records
            sustained_error = f"{type(exc).__name__}: {str(exc)[:300]}"
            print(f"sustained-run phase failed: {sustained_error}", flush=True)
        for doc in sustained:
            print(f"sustained #{doc.get('entry')} {doc.get('name')}: {doc.get('outcome')}: {doc.get('label')} "
                  f"(${doc.get('cost_usd', 0.0):.4f} API-reported, ${doc.get('cost_estimated_usd', 0.0):.4f} estimated)", flush=True)
    dev_counts = {}
    for path in sorted((ROOT / "runs" / "corpus_v2_batch").glob("harness-v*/dev/round_summary.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        dev_counts[int(doc["round"])] = sum(1 for e in doc["entries"] if e.get("verdict") in RUNS_VERDICTS)
    result_doc = evaluate(records, sustained, dev_counts)
    result_doc["tag"] = args.tag
    result_doc["finished_at"] = datetime.now(timezone.utc).isoformat()
    result_doc["spend"] = {"entries_usd": round(spent, 6), "sustained_runs_usd": round(sustained_cost, 6), "total_usd": round(spent + sustained_cost, 6),
                           "cap_usd": args.test_cap_usd, "note": "entries: cost guard figures per record (API-reported plus the estimate of a killed step); sustained runs as listed"}
    if sustained_error:
        result_doc["sustained_error"] = sustained_error
    (odir / "test_result.json").write_text(json.dumps(result_doc, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(result_doc, indent=2), flush=True)
    print(f"TEST PHASE at {args.tag}: {result_doc['confirmed_count']} of {len(TEST_ENTRIES)} confirmed (target {TARGET}); "
          f"{result_doc['runs_verdict_count_at_smoke_level']} with a RUNS_* verdict; {'complete' if len(records) == len(TEST_ENTRIES) else 'INCOMPLETE'}", flush=True)
    return 0 if len(records) == len(TEST_ENTRIES) else 1


if __name__ == "__main__":
    raise SystemExit(main())
