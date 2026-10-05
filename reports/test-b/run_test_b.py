"""TEST-B: the 8 entries of corpus-v3 (backend/app/batch/corpus_v3/prereg.json), TREATMENT, ONCE each, at the frozen tag harness-v1.7.2, then the sustained runs.

    backend/.venv/Scripts/python.exe reports/test-b/run_test_b.py --selftest
    backend/.venv/Scripts/python.exe reports/test-b/run_test_b.py --cap-usd 95 --entry-cap-usd 2.50              # DRY RUN: preflight and the plan
    backend/.venv/Scripts/pythonw.exe reports/test-b/run_test_b.py --cap-usd 95 --entry-cap-usd 2.50 --go --log-file F   # spends money (launch_test_b.cmd)

Everything that decides the result is fixed in the pre-registration (corpus_v3/prereg.json, /run and /analysis), sealed in the harness-v1.7.2 tag before the draw:
entries in ascending id, once each (an INFRA_ERROR with no baseline execution is re-run once, the first record kept under infra_retries/), then the D-42 sustained run of every
RUNS_* entry whose smoke run was alive at its limit, funded from what the cap has left. The RAN count (rules R1-R4 and the D-46 audit) is computed HERE and written to
test_b_result.json; it is reported whatever it is. Nothing is re-run and nothing is tuned on a TEST-B result. Run it DETACHED (Task Scheduler, D-43).
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "backend"))

CORPUS = "corpus-v3"
TAG = "harness-v1.7.2"
ENTRY_CAP_USD = 2.50
CAP_USD = 95.00
N_ENTRIES = 8
RUNS_VERDICTS = ("RUNS_CLEAN", "RUNS_AFTER_REPAIR")
SUSTAINED_SECONDS = 600
PREREG = ROOT / "backend" / "app" / "batch" / "corpus_v3" / "prereg.json"

# The D-46 audit (prereg /analysis/d46_audit), fixed before the run.
CHAIN_RE = re.compile(r"\|\||(?<![|])\|(?![|])|;")
STRIKE_PATTERNS = (
    ("a Python traceback", re.compile(r"Traceback \(most recent call last\)")),
    ("a Python exception line", re.compile(r"^\s*[A-Za-z_][\w.]*Error: ", re.MULTILINE)),
    ("a usage message", re.compile(r"^\s*usage:", re.IGNORECASE | re.MULTILINE)),
    ("a missing-credential message", re.compile(r"(api[ _-]?key|access[ _-]?token|credentials?)\b.{0,60}\b(missing|not (set|found|specified|provided)|required|invalid)",
                                                re.IGNORECASE)),
)


def _load(rel: str, name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _sha(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def final_output(record: dict) -> tuple[int | None, str, str]:
    """(exit code, stdout tail, stderr tail) of the run the verdict rests on: the chosen passing attempt, else the baseline (RUNS_CLEAN)."""
    from app.services import outcome_levels

    result = record.get("result") or {}
    attempts = result.get("attempts") or []
    final = next((a for a in reversed(attempts) if a.get("chosen") is True and outcome_levels.attempt_passed(a)), None) \
        or next((a for a in reversed(attempts) if outcome_levels.attempt_passed(a)), None)
    if final is not None:
        return final.get("exit_code"), final.get("stdout_tail") or "", final.get("stderr_tail") or ""
    base = result.get("baseline") or {}
    return base.get("exit_code"), base.get("stdout_tail") or "", base.get("stderr_tail") or ""


def audit(record: dict, command: str, sustained: dict | None) -> dict:
    """PURE. The D-46 audit row of one entry that passed R1-R3: what it printed, and the strike (None = not struck)."""
    code, out, err = final_output(record)
    if sustained and sustained.get("outcome") in ("completed", "running_at_limit"):
        out, err = sustained.get("stdout_tail") or out, sustained.get("stderr_tail") or err
    row = {"command": command, "exit_code": code, "stdout_bytes": len(out.encode("utf-8")), "stderr_bytes": len(err.encode("utf-8")),
           "stdout_sha256": _sha(out), "stderr_sha256": _sha(err), "first_error_like_line": None, "strike": None}
    for line in (out + "\n" + err).splitlines():
        if re.search(r"error|traceback|usage:|not found|missing", line, re.IGNORECASE):
            row["first_error_like_line"] = line.strip()[:300]
            break
    if CHAIN_RE.search(command or ""):
        row["strike"] = "(a) the documented command chains commands ('|', '||' or ';') and the record keeps only the chain's output: it does not show the first command ran"
        return row
    for what, rx in STRIKE_PATTERNS:
        m = rx.search(out) or rx.search(err)
        if m:
            line = next((l for l in (out + "\n" + err).splitlines() if rx.search(l)), m.group(0))
            row["strike"] = f"(b) {what}: {line.strip()[:300]}"
            return row
    return row


def evaluate(records: list[dict], sustained: list[dict], commands: dict[int, str]) -> dict:
    """PURE. The TEST-B result under prereg /analysis: RAN (R1-R4) and the lines beside it."""
    from app.services import outcome_levels

    test_phase = _load("reports/corpus-v2.1/v1.5/test/run_test_phase.py", "run_test_phase")
    by_entry = {d.get("entry"): d for d in sustained if d}
    rows = []
    for record in sorted(records, key=lambda r: (r.get("batch") or {}).get("entry_id")):
        entry = (record.get("batch") or {}).get("entry_id")
        row = test_phase.confirmation(record, by_entry.get(entry))  # R1 + R2: the TEST phase's 'confirmed' rule, unchanged
        result = record.get("result") or {}
        row.update(resource_adapted=outcome_levels.resource_adapted(result) or None, semantic_change=list(outcome_levels.semantic_change(result)) or None,
                   verdict_label=outcome_levels.verdict_label(result), sole_candidate="SOLE CANDIDATE" in str(outcome_levels.verdict_label(result) or "").upper(),
                   ran=False, audit=None)
        if row["confirmed"]:
            code, out, err = final_output(record)
            exit_zero_rule = str(row.get("why", "")).startswith(("(i)", "(ii)"))
            s = by_entry.get(entry) or {}
            if exit_zero_rule and not (s.get("stdout_tail") or s.get("stderr_tail") or out.strip() or err.strip()):
                row["why"] += "; R3: struck, an exit 0 that printed nothing"
            else:
                row["audit"] = audit(record, commands.get(entry, ""), by_entry.get(entry))
                if row["audit"]["strike"]:
                    row["why"] += f"; R4 (D-46 audit): struck, {row['audit']['strike']}"
                else:
                    row["ran"] = True
        rows.append(row)
    ran = [r for r in rows if r["ran"]]
    return {"corpus": CORPUS, "name": "TEST-B", "tag": TAG, "entries": N_ENTRIES, "ran_entries": len(records),
            "primary_measure": "RAN (prereg /analysis/ran_rule R1-R4): the documented command actually ran",
            "ran_count": len(ran), "ran_without_semantic_change": sum(1 for r in ran if not r["semantic_change"]),
            "ran_with_semantic_change": sum(1 for r in ran if r["semantic_change"]), "ran_resource_adapted": sum(1 for r in ran if r["resource_adapted"]),
            "ran_sole_candidate": sum(1 for r in ran if r["sole_candidate"]),
            "confirmed_as_in_the_test_phase": sum(1 for r in rows if r["confirmed"]),
            "runs_verdict_count_at_smoke_level": sum(1 for r in rows if r["verdict"] in RUNS_VERDICTS), "rows": rows,
            "note": "a count over 8 entries, one run each: not a rate; RAN says the documented command ran, not that the paper's result was reproduced; "
                    "never pooled with the TEST phase (harness-v1.7.1 code: 2 of 8 confirmed, 1 of 8 ran)"}


def _selftest() -> int:
    pre = json.loads(PREREG.read_text(encoding="utf-8"))
    assert pre["target_eligible"] == N_ENTRIES and pre["run"]["entry_cap_usd"] == ENTRY_CAP_USD and pre["run"]["test_b_cap_usd"] == CAP_USD
    assert CHAIN_RE.search("python a.py | bash") and CHAIN_RE.search("python a.py || true") and CHAIN_RE.search("cd x; python a.py")
    assert not CHAIN_RE.search("python a.py --x 1 && python b.py") and not CHAIN_RE.search("python main.py --lr 0.1")
    rec = {"result": {"verdict": "RUNS_CLEAN", "attempts": [], "baseline": {"exit_code": 0, "stdout_tail": "", "stderr_tail": "usage: x.py [-h]\n"}}}
    row = audit(rec, "python x.py", None)
    assert row["strike"] and row["strike"].startswith("(b) a usage message"), row
    row = audit({"result": {"verdict": "RUNS_CLEAN", "attempts": [], "baseline": {"exit_code": 0, "stdout_tail": "epoch 1 loss 0.3\n", "stderr_tail": ""}}}, "python x.py", None)
    assert row["strike"] is None, row
    assert evaluate([], [], {})["ran_count"] == 0
    print("selftest OK")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--go", action="store_true", help="actually run (spends money)")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--cap-usd", type=float)
    ap.add_argument("--entry-cap-usd", type=float)
    ap.add_argument("--resume", action="store_true", help="after an interruption: keep the valid records already written, run only the other entries")
    ap.add_argument("--log-file")
    args = ap.parse_args(argv)
    if args.log_file:
        sys.stdout = sys.stderr = open(args.log_file, "a", buffering=1, encoding="utf-8", errors="replace")
    if args.selftest:
        return _selftest()
    if args.cap_usd != CAP_USD or args.entry_cap_usd != ENTRY_CAP_USD:
        print(f"REFUSED: the pre-registered caps are --cap-usd {CAP_USD} --entry-cap-usd {ENTRY_CAP_USD}", file=sys.stderr)
        return 2
    ledger = _load("reports/ledger_total.py", "ledger_total")
    now = ledger.total()
    print(f"ledger ${now:.4f} API-REPORTED; worst case after TEST-B ${now + CAP_USD:.4f} of ${ledger.CEILING_USD:.2f}", flush=True)
    if now + CAP_USD > ledger.CEILING_USD + 1e-9:
        print("REFUSED: the worst case passes the ledger ceiling", file=sys.stderr)
        return 4
    from app.services import gate_budget
    import run_corpus_v1_batch as drv

    gate_budget.check_gate_caps(CAP_USD, ENTRY_CAP_USD, N_ENTRIES)
    try:
        frozen = {**drv.preflight(CORPUS, TAG), "arm": "treatment", "total_cap_usd": CAP_USD, "already_spent_usd": 0.0}
    except drv.PreflightError as exc:
        print(f"PREFLIGHT REFUSED ({TAG}): {exc}", file=sys.stderr, flush=True)
        return 3
    import yaml

    corpus = yaml.safe_load((drv.corpus_dir(CORPUS) / "corpus.yaml").read_text(encoding="utf-8"))["repos"]
    commands = {i: r["command"] for i, r in enumerate(corpus, start=1)}
    plan = drv.entries_for(CORPUS)
    if len(plan) != N_ENTRIES:
        print(f"REFUSED: corpus-v3 has {len(plan)} entries, the registration says {N_ENTRIES}", file=sys.stderr)
        return 3
    odir = drv.out_dir(CORPUS, TAG, "treatment")
    print(f"preflight OK at {frozen['head_commit'][:12]} (tag {TAG}); TEST-B; cap ${CAP_USD}; entry cap ${ENTRY_CAP_USD}; entries: "
          + ", ".join(f"#{r['id']} {r['name']}" for r in plan), flush=True)
    if not args.go:
        print("DRY RUN: nothing was run and nothing was spent (pass --go to run).")
        return 0

    run_dev = _load("reports/corpus-v2.1/v1.5/dev/run_dev_round.py", "run_dev_round")
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
            print(f"#{row['id']} {row['name']} RESUMED from its valid record", flush=True)
            continue
        try:
            drv.PER_ENTRY_CAP_USD = gate_budget.entry_cap_for(CAP_USD, ENTRY_CAP_USD, spent)
        except gate_budget.GateBudgetError as exc:
            print(f"STOP: {exc}", flush=True)
            break
        meta = {**frozen, "entry_id": row["id"], "category": row["category"], "rules_matched": row["rules_matched"], "per_entry_cap_usd": drv.PER_ENTRY_CAP_USD,
                "total_cap_usd": CAP_USD, "protocol": "TEST-B (corpus-v3, pre-registered 2026-10-05)"}
        for run_number in (1, 2):
            print(f"#{row['id']} {row['name']} starting (entry cap ${drv.PER_ENTRY_CAP_USD}; run {run_number})", flush=True)
            drv._run_live(CORPUS, row["name"], frozen["corpus_hash"], meta, path)
            record = json.loads(path.read_text(encoding="utf-8"))
            spent += float(record["cost_guard"]["spent_usd"])
            result = record.get("result") or {}
            print(f"#{row['id']} -> {result.get('verdict')} {result.get('taxonomy_code') or result.get('reason_code') or ''} "
                  f"${record['cost_guard']['spent_usd']:.4f} (TEST-B total ${spent:.4f})", flush=True)
            if run_number == 1 and not record.get("error") and run_dev.should_retry_infra(record):
                keep = odir / "infra_retries"
                keep.mkdir(exist_ok=True)
                path.replace(keep / f"{path.stem}.attempt1.json")
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
            sustained, sustained_cost = gate.sustained_phase(records, paths, gate_cap_usd=CAP_USD, spent_usd=spent, odir=odir,
                                                             api_key=settings.nebius_api_key, project_id=settings.nebius_project_id)
        except Exception as exc:  # noqa: BLE001 - a failed sustained phase must never lose the entry records
            sustained_error = f"{type(exc).__name__}: {str(exc)[:300]}"
            print(f"sustained-run phase failed: {sustained_error}", flush=True)
    result_doc = evaluate(records, sustained, commands)
    result_doc["finished_at"] = datetime.now(timezone.utc).isoformat()
    result_doc["spend"] = {"entries_usd": round(spent, 6), "sustained_runs_usd": round(sustained_cost, 6), "total_usd": round(spent + sustained_cost, 6), "cap_usd": CAP_USD,
                           "note": "entries: cost guard figures per record (API-reported plus the estimate of a killed step); sustained runs as listed (API-reported or ESTIMATED)"}
    if sustained_error:
        result_doc["sustained_error"] = sustained_error
    (odir / "test_b_result.json").write_text(json.dumps(result_doc, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(result_doc, indent=2), flush=True)
    print(f"TEST-B at {TAG}: RAN {result_doc['ran_count']} of {N_ENTRIES} ({result_doc['ran_without_semantic_change']} without a semantic change); "
          f"{'complete' if len(records) == N_ENTRIES else 'INCOMPLETE'}", flush=True)
    return 0 if len(records) == N_ENTRIES else 1


if __name__ == "__main__":
    raise SystemExit(main())
