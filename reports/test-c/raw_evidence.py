"""TEST-C audit helper: print the RAW evidence of each non-running record, WITHOUT the blocker report, so that the answer key can be written from the log first (rubric: reports/dev/v18/DIAGNOSIS_RUBRIC.md,
"Procedure": the key is written from each record's raw log before any blocker text is read, committed, and only then scored).

    backend/.venv/Scripts/python.exe reports/test-c/raw_evidence.py [--dir runs/corpus_v4_batch/harness-v1.8.0/treatment] [--entry N]

It prints, per entry: the verdict and class, the documented command, the baseline's exit code and evidence line, the error chain (the lines only), RERUN's deterministic steps and gate decisions
(rule names), and the last lines of the last attempt that ran something. It never reads `result.blocker`, `certificate.blocker`, `what_a_human_must_supply` or `next_action`; a test pins that.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DIR = ROOT / "runs" / "corpus_v4_batch" / "harness-v1.8.0" / "treatment"
RUNS = ("RUNS_CLEAN", "RUNS_AFTER_REPAIR")


def _plain(text: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", text or "")


def render(record: dict, tail_lines: int = 14) -> str:
    result = record.get("result") or {}
    cert = record.get("certificate") or {}
    entry = record.get("corpus_entry") or {}
    out = [f"=== #{(record.get('batch') or {}).get('entry_id')} {entry.get('name')}  verdict {result.get('verdict')}  class {result.get('taxonomy_code') or result.get('reason_code') or '-'}",
           f"command: {entry.get('command')}"]
    if result.get("indeterminate_reason"):
        out.append(f"indeterminate_reason: {_plain(result['indeterminate_reason'])[:500]}")
    base = cert.get("baseline") or {}
    out.append(f"baseline: {base.get('result')} exit {base.get('exit_code')} class {base.get('taxonomy_code')} evidence: {_plain(base.get('evidence'))[:300]}")
    for i, link in enumerate(result.get("error_chain") or []):
        out.append(f"chain[{i}] {link.get('class')} ({link.get('phase')}, cleared_by {link.get('cleared_by')}): {_plain(link.get('error'))[:300]}")
    attempts = result.get("attempts") or []
    for i, a in enumerate(attempts):
        action = a.get("time_machine_action") or {}
        env = a.get("env_delta")
        out.append(f"attempt[{i}] #{a.get('attempt_number')}.{a.get('candidate')} origin {a.get('origin')} gate {a.get('gate_decision')} exit {a.get('exit_code')} chosen {a.get('chosen')}"
                   + (f" rule {action.get('rule')}" if action.get("rule") else "") + (f" env_delta {len(env)}" if env else "")
                   + (f" gate_violations {str(a.get('gate_violations'))[:160]}" if a.get("gate_decision") == "REJECT" else ""))
    ran = [a for a in attempts if a.get("stderr_tail") or a.get("stdout_tail")]
    if ran:
        last = ran[-1]
        lines = [ln for ln in _plain((last.get("stderr_tail") or "") + "\n" + (last.get("stdout_tail") or "")).splitlines() if ln.strip()]
        out.append(f"-- last output of attempt #{last.get('attempt_number')}.{last.get('candidate')} (last {tail_lines} non-empty lines):")
        out += [f"   | {ln[:200]}" for ln in lines[-tail_lines:]]
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=str(DEFAULT_DIR))
    ap.add_argument("--entry", type=int)
    ap.add_argument("--all", action="store_true", help="also the RUNS_* entries (default: non-running only)")
    args = ap.parse_args()
    for path in sorted(Path(args.dir).glob("[0-9][0-9]_*.json")):
        if ".attempt" in path.name:
            continue
        record = json.loads(path.read_text(encoding="utf-8"))
        if args.entry is not None and int(path.name[:2]) != args.entry:
            continue
        if not args.all and (record.get("result") or {}).get("verdict") in RUNS:
            continue
        print(render(record) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
