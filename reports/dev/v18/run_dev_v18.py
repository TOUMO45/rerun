"""harness-v1.8, Phase 2: re-run the 21 old held-out entries as DEV-CONTAMINATED (owner, 2026-10-07: "run the 21 under v1.8 as DEV-CONTAMINATED in runs/dev_v18/, never
attributed to TEST, TEST-B or OOS. 'Never re-run' meant never re-score under their old names").

    backend/.venv/Scripts/python.exe reports/dev/v18/run_dev_v18.py --selftest
    backend/.venv/Scripts/python.exe reports/dev/v18/run_dev_v18.py --sets TEST-B,TEST --cap-usd 30                 # DRY RUN: the plan and the worst case
    backend/.venv/Scripts/pythonw.exe reports/dev/v18/run_dev_v18.py --sets TEST-B,TEST,OOS --cap-usd 55 --go --log-file F   # spends money (launch_dev_v18.cmd)

What it runs: the SAME pipeline and the same corpus rows the original runs used (scripts/live_run.py through the batch driver's `_run_live`; the OOS repositories through
reports/live_scan/run_live_scan.py, i.e. RERUN's own API, exactly what the UI does), but on the CURRENT WORKING TREE, not a sealed tag: this is development, so there is no
preflight and no seal claim. Every corpus record is written under runs/dev_v18/<set>/ and carries `batch.dev_label` = "DEV-CONTAMINATED (was <set>)"; every OOS summary row
under runs/dev_v18/OOS/ carries `dev_label` (the same text). Nothing here is read by a TEST, TEST-B or OOS result file, and no number from these records is ever attributed to
those sets. Entry cap $2.50 (the owner's). The ledger worst case is printed first and the run refuses to start, or stops, when it would pass the owner's $300 API-reported ceiling
or the cap given with --cap-usd; because the cost guard has overshot the entry cap once (T17: $4.18 recorded on one entry, D-60), the check before each entry reserves
that highest reading (ENTRY_RESERVE_USD), not the cap. The provenance of the code that ran (HEAD, modified and untracked harness files, a hash of the harness tree) is in every
record's batch block. Run it DETACHED (a paid batch is never a child of a session, D-43).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "reports"))

ENTRY_CAP_USD = 2.50
ENTRY_RESERVE_USD = 4.18  # the highest single-entry reading on record (T17 / D-60): what the pre-entry checks hold back, since the guard can overshoot the cap
OUT = ROOT / "runs" / "dev_v18"
TEST_IDS = (1, 2, 6, 10, 13, 18, 19, 20)  # corpus-v2: the 8 TEST entries (METHODOLOGY "harness-v1.5 dev/test protocol"); DEV-CONTAMINATED from 2026-10-07
SETS = {"TEST": ("corpus-v2", TEST_IDS), "TEST-B": ("corpus-v3", tuple(range(1, 9))), "OOS": (None, ())}
_SUBDIR_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,39}")
_HARNESS_ROOTS = ("backend/app/", "scripts/")  # what the provenance block lists and hashes


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()


def safe_subdir(value: str) -> str:
    """A sub-folder NAME for runs/dev_v18: letters, digits, dot, dash, underscore; no separators, no `..`, no absolute path. Raises ValueError otherwise."""
    if value == "":
        return ""
    if not _SUBDIR_RE.fullmatch(value) or ".." in value:
        raise ValueError(f"--out-subdir must be one plain folder name (letters, digits, . _ -; at most 40 characters), got {value!r}")
    return value


def finite_positive(value: float, flag: str) -> float:
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{flag} must be a finite number above zero, got {value!r}")
    return value


def provenance() -> dict:
    """What code ran: HEAD, the modified and the UNTRACKED files under the harness paths (new modules are untracked until committed), and a sha256 over every harness
    source file's path and bytes, so two records with the same hash ran the same code whatever git says."""
    head = _git("rev-parse", "HEAD")
    changed, untracked = [], []
    for line in _git("status", "--porcelain", "--untracked-files=all").splitlines():
        path = line[3:].strip().strip('"')
        if path.startswith(_HARNESS_ROOTS) and path.endswith(".py"):
            (untracked if line.startswith("??") else changed).append(path)
    digest = hashlib.sha256()
    files = sorted(p for root in _HARNESS_ROOTS for p in (ROOT / root).rglob("*.py") if "__pycache__" not in p.parts and ".venv" not in p.parts)
    for p in files:
        digest.update(p.relative_to(ROOT).as_posix().encode() + b"\0" + hashlib.sha256(p.read_bytes()).digest())
    return {"head_commit": head, "tree_dirty_tracked_files": bool(changed), "modified_harness_files": sorted(changed), "untracked_harness_files": sorted(untracked),
            "harness_files_hashed": len(files), "harness_tree_sha256": digest.hexdigest()}


def plan(sets: list[str], ids: set[int] | None) -> list[dict]:
    import run_corpus_v1_batch as drv

    rows: list[dict] = []
    for name in sets:
        corpus, wanted = SETS[name]
        if name == "OOS":
            picks = json.loads((ROOT / "reports" / "live_scan" / "oos_v172" / "selection.json").read_text(encoding="utf-8"))["picks"]
            rows += [{"set": "OOS", "corpus": None, "id": i, "name": url.rstrip("/").split("/")[-2] + "__" + url.rstrip("/").split("/")[-1], "url": url}
                     for i, url in enumerate(picks, start=1) if ids is None or i in ids]
            continue
        by_id = {r["id"]: r for r in drv.entries_for(corpus)}
        for i in wanted:
            if ids is None or i in ids:
                rows.append({"set": name, "corpus": corpus, "id": i, "name": by_id[i]["name"], "category": by_id[i]["category"], "rules_matched": by_id[i]["rules_matched"]})
    return rows


def record_is_final(path: Path) -> tuple[bool, dict | None]:
    """(is it a finished record, the record). A file that is not valid JSON, or has no verdict, or carries an `error`, is NOT final: the entry is re-run and the old file kept
    beside it (its spend stays in the ledger, which counts every [0-9][0-9]_*.json)."""
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False, None
    result = record.get("result") if isinstance(record, dict) else None
    return bool(isinstance(result, dict) and result.get("verdict") and not record.get("error")), record if isinstance(record, dict) else None


def move_aside(path: Path) -> Path:
    n = 1
    while True:
        target = path.with_name(f"{path.stem}.superseded{n}.json")
        if not target.exists():
            path.rename(target)
            return target
        n += 1


def oos_cost(row: dict, entry_cap: float) -> tuple[float, bool]:
    """(cost, measured). A summary row with no cost reading (the scan crashed before the guard's last line) counts at the entry cap for THIS invocation's budget, and is not
    presented as measured."""
    import ledger_total

    cost = row.get("cost") or {}
    if cost.get("guard_total_usd") is None and cost.get("sandbox_api_reported_usd") is None:
        return entry_cap, False
    return ledger_total.dev_scan_row_cost(row), True  # includes the estimate of a killed step (a baseline stopped at the wall clock: mud-pi, $9.1047 recorded, 0.0009 measured)


def _selftest() -> int:
    rows = plan(["TEST", "TEST-B", "OOS"], None)
    assert [r["id"] for r in rows if r["set"] == "TEST"] == list(TEST_IDS) and len([r for r in rows if r["set"] == "TEST-B"]) == 8 and len([r for r in rows if r["set"] == "OOS"]) == 5
    assert [r["id"] for r in plan(["TEST-B", "OOS"], {2, 3}) if r["set"] == "OOS"] == [2, 3]  # --ids filters the OOS picks too
    names = {(r["set"], r["name"]) for r in rows}
    assert ("TEST", "nadiinchi__power_laws_deep_ensembles") in names and ("TEST-B", "yikangshen__Ordered-Neurons") in names
    for bad in ("../x", "..", "a/b", "a\\b", "C:\\x", "/abs", ".hidden", "a" * 41, "x..y"):
        try:
            safe_subdir(bad)
        except ValueError:
            continue
        raise AssertionError(f"accepted {bad!r}")
    assert safe_subdir("") == "" and safe_subdir("round-2_a.1") == "round-2_a.1"
    for bad in (float("nan"), float("inf"), 0.0, -1.0):
        try:
            finite_positive(bad, "--cap-usd")
        except ValueError:
            continue
        raise AssertionError(f"accepted {bad!r}")
    assert oos_cost({"cost": {}}, 2.5) == (2.5, False) and oos_cost({"cost": {"guard_total_usd": 0.0}}, 2.5) == (0.0, True)
    assert oos_cost({"cost": {"sandbox_api_reported_usd": 1.25}}, 2.5) == (1.25, True)
    killed = {"cost": {"sandbox_api_reported_usd": 0, "guard_total_usd": None, "estimated_lines": [
        "[cost_guard] operation stopped at 600s; recorded $9.1047 (0.0009 measured + estimate for the killed step), $0.0000 left"]}}
    assert abs(oos_cost(killed, 2.5)[0] - 9.1038) < 1e-9 and oos_cost(killed, 2.5)[1]  # the estimate counts
    import ledger_total

    assert ledger_total.total() > 0
    prov = provenance()
    assert len(prov["harness_tree_sha256"]) == 64 and prov["harness_files_hashed"] > 50
    print(f"selftest ok: {len(rows)} entries (8 TEST, 8 TEST-B, 5 OOS); ledger ${ledger_total.total():.4f}; harness tree {prov['harness_tree_sha256'][:12]} "
          f"({prov['harness_files_hashed']} files; {len(prov['untracked_harness_files'])} untracked, {len(prov['modified_harness_files'])} modified)")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--go", action="store_true", help="actually run (spends money)")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--sets", default="TEST-B,TEST,OOS", help="comma list of TEST, TEST-B, OOS")
    ap.add_argument("--ids", help="comma list of entry ids, applied to every chosen set (TEST: 1,2,6,10,13,18,19,20; TEST-B: 1-8; OOS: 1-5)")
    ap.add_argument("--cap-usd", type=float, required=False, help="the most this invocation may spend (API-reported + estimates); required with --go")
    ap.add_argument("--entry-cap-usd", type=float, default=ENTRY_CAP_USD)
    ap.add_argument("--out-subdir", default="", help="one plain folder name under runs/dev_v18 (for example a round label)")
    ap.add_argument("--log-file")
    args = ap.parse_args(argv)
    if args.log_file:
        sys.stdout = sys.stderr = open(args.log_file, "a", buffering=1, encoding="utf-8", errors="replace")
    if args.selftest:
        return _selftest()
    try:
        subdir = safe_subdir(args.out_subdir)
        entry_cap = finite_positive(args.entry_cap_usd, "--entry-cap-usd")
        if args.cap_usd is not None:
            finite_positive(args.cap_usd, "--cap-usd")
    except ValueError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr, flush=True)
        return 2
    if abs(entry_cap - ENTRY_CAP_USD) > 1e-9:
        print(f"REFUSED: the entry cap is the owner's ${ENTRY_CAP_USD:.2f}", file=sys.stderr, flush=True)
        return 2
    sets = [s.strip() for s in args.sets.split(",") if s.strip()]
    if not sets or any(s not in SETS for s in sets):
        print(f"REFUSED: unknown or empty set list {sets}", file=sys.stderr, flush=True)
        return 2
    try:
        ids = {int(x) for x in args.ids.split(",")} if args.ids else None
    except ValueError:
        print(f"REFUSED: --ids must be a comma list of integers, got {args.ids!r}", file=sys.stderr, flush=True)
        return 2
    rows = plan(sets, ids)
    import ledger_total

    ledger = ledger_total.total()
    worst = round(len(rows) * entry_cap, 2)
    cap = args.cap_usd if args.cap_usd is not None else worst
    print(f"ledger now ${ledger:.4f} API-reported; {len(rows)} entries x ${entry_cap:.2f} = worst case ${worst:.2f} (one entry has been recorded at ${ENTRY_RESERVE_USD:.2f}, so each "
          f"start holds back that much); this invocation's cap ${cap:.2f}; ceiling ${ledger_total.CEILING_USD:.2f}; worst case after: ${ledger + min(worst, cap):.4f}", flush=True)
    if ledger + min(worst, cap) > ledger_total.CEILING_USD + 1e-9:
        print("REFUSED: the worst case passes the ledger ceiling", file=sys.stderr, flush=True)
        return 4
    for r in rows:
        print(f"  {r['set']:6} #{r['id']} {r['name']}", flush=True)
    if not args.go:
        print("DRY RUN: nothing was run and nothing was spent (pass --go and --cap-usd to run).")
        return 0
    if args.cap_usd is None:
        print("REFUSED: --cap-usd is required with --go", file=sys.stderr, flush=True)
        return 2

    import run_corpus_v1_batch as drv

    prov = provenance()
    base = OUT / subdir if subdir else OUT
    assert OUT.resolve() in (base.resolve(), *base.resolve().parents)  # belt and braces after safe_subdir
    base.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).isoformat()
    smoke = drv.run_smoke()
    (base / f"upload_smoke_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json").write_text(json.dumps(smoke, indent=2) + "\n", encoding="utf-8")
    spent = sum(float(r.get("cost_usd") or 0.0) for r in (smoke.get("runs") or []))  # the smoke test is billed too
    if not smoke.get("ok"):
        print(f"REFUSING TO START: the pre-batch upload smoke test failed (${spent:.4f} spent on it)", file=sys.stderr, flush=True)
        return 3
    drv.PER_ENTRY_CAP_USD = entry_cap
    done: list[dict] = []
    for row in rows:
        if spent + ENTRY_RESERVE_USD > args.cap_usd + 1e-9:
            print(f"STOP: ${spent:.4f} spent; holding back ${ENTRY_RESERVE_USD:.2f} for the next entry would pass this invocation's ${args.cap_usd:.2f}", flush=True)
            break
        if ledger_total.total() + ENTRY_RESERVE_USD > ledger_total.CEILING_USD + 1e-9:
            print("STOP: another entry would pass the ledger ceiling", flush=True)
            break
        label = f"DEV-CONTAMINATED (was {row['set']})"
        if row["set"] == "OOS":
            oos_dir = base / "OOS"
            summary = oos_dir / "scan_summary.json"
            if summary.is_file():
                try:
                    existing = json.loads(summary.read_text(encoding="utf-8"))
                except ValueError:
                    existing = []
                if any(r.get("repo_url") == row["url"] and r.get("verdict") and r.get("stage") not in ("error", "intake_refused", "execute_refused") for r in existing):
                    print(f"OOS #{row['id']} {row['name']}: summary row exists, skipped (resume)", flush=True)
                    continue
            cmd = [str(ROOT / "backend" / ".venv" / "Scripts" / "python.exe"), "-u", str(ROOT / "reports" / "live_scan" / "run_live_scan.py"),
                   "--out-subdir", f"../dev_v18/{subdir + '/' if subdir else ''}OOS", row["url"]]
            print(f"OOS #{row['id']} {row['name']} starting (API path, entry cap ${entry_cap}; {label})", flush=True)
            proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", env=drv._child_env())
            print((proc.stdout or "")[-3000:], flush=True)
            last: dict = {}
            if summary.is_file():
                rowsum = json.loads(summary.read_text(encoding="utf-8"))
                if rowsum and rowsum[-1].get("repo_url") == row["url"]:
                    last = rowsum[-1]
                    last.update(dev_label=label, was="OOS", dev_v18=True, harness="harness-v1.8 working tree, UNSEALED", **{"provenance": prov, "started_at_invocation": stamp})
                    summary.write_text(json.dumps(rowsum, indent=2), encoding="utf-8")
            cost, measured = oos_cost(last, entry_cap)
            spent += cost
            done.append({"set": "OOS", "id": row["id"], "name": row["name"], "verdict": last.get("verdict"), "code": last.get("taxonomy_code"), "spent_usd": cost,
                         "cost_measured": measured})
            print(f"OOS #{row['id']} -> {last.get('verdict') or last.get('stage')} {last.get('taxonomy_code') or ''} ${cost:.4f}"
                  f"{'' if measured else ' (no cost reading: counted at the entry cap, NOT a measurement)'} ({label}; spent ${spent:.4f})", flush=True)
            continue
        odir = base / row["set"]
        odir.mkdir(parents=True, exist_ok=True)
        path = odir / f"{row['id']:02d}_{row['name']}.json"
        if path.is_file():
            final, record = record_is_final(path)
            if final:
                spent += float((record.get("cost_guard") or {}).get("spent_usd") or 0.0)
                print(f"{row['set']} #{row['id']} {row['name']}: record exists, skipped (resume)", flush=True)
                continue
            kept = move_aside(path)
            print(f"{row['set']} #{row['id']} {row['name']}: the existing file is not a finished record; kept as {kept.name} and the entry runs again", flush=True)
        meta = {"protocol": "harness-v1.8 DEV (owner 2026-10-07)", "dev_label": label, "was": row["set"], "dev_v18": True, "entry_id": row["id"], "category": row["category"],
                "rules_matched": row["rules_matched"], "per_entry_cap_usd": entry_cap, "arm": "treatment", "harness": "harness-v1.8 working tree, UNSEALED",
                "started_at": stamp, "corpus": row["corpus"], **prov}
        print(f"{row['set']} #{row['id']} {row['name']} starting (entry cap ${entry_cap}; {label})", flush=True)
        drv._run_live(row["corpus"], row["name"], drv.recompute_corpus_hash(drv.corpus_dir(row["corpus"])), meta, path)
        if not path.is_file():
            print(f"STOP: no record was written for #{row['id']}", flush=True)
            break
        record = json.loads(path.read_text(encoding="utf-8"))
        cost = float((record.get("cost_guard") or {}).get("spent_usd") or 0.0)
        spent += cost
        result = record.get("result") or {}
        done.append({"set": row["set"], "id": row["id"], "name": row["name"], "verdict": result.get("verdict"), "code": result.get("taxonomy_code") or result.get("reason_code"),
                     "spent_usd": cost, "over_cap_estimated_only": (record.get("cost_guard") or {}).get("over_cap_estimated_only")})
        print(f"{row['set']} #{row['id']} -> {result.get('verdict')} {result.get('taxonomy_code') or result.get('reason_code') or ''} ${cost:.4f} (spent ${spent:.4f})", flush=True)
        if record.get("error"):
            print(f"STOP: entry #{row['id']} ended without a verdict: {record['error']}", flush=True)
            break
    summary_name = f"run_summary_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"  # one per invocation: a resumed run does not overwrite the earlier one
    (base / summary_name).write_text(json.dumps({"label": "DEV-CONTAMINATED", "finished_at": datetime.now(timezone.utc).isoformat(), "spent_usd": round(spent, 6),
                                                 "provenance": prov, "entries": done}, indent=2) + "\n", encoding="utf-8")
    print(f"DEV v1.8: {len(done)} entries done, spent ${spent:.4f} API-reported + estimates (this invocation)", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
