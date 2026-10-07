"""harness-v1.8, Phase 5 input: does any COMMITTED record show the tamper gate rejecting a patch that genuinely tried to fake a pass? (owner, 2026-10-07: "also state whether any committed
record shows the gate rejecting a patch that genuinely tried to fake a pass")

    backend/.venv/Scripts/python.exe reports/dev/v18/gate_rejections.py [--write]

Reads every record under runs/ that carries attempts (a batch record's `result.attempts`, or a certificate's `diffs`), takes every attempt whose `gate_decision` is REJECT, counts the rules it
was rejected under, and lists the rejections under the five rules that are about FAKING (the gate's own §5.3 rules: DELETED_EVAL_CALL, STUBBED_MODEL_CALL, REDUCED_SCALE,
BROAD_EXCEPTION_SWALLOW, PROTECTED_PATH_MODIFIED) with the patch text, so that each can be read. Nothing is re-run and the gate is not called: this only reads what the records stored.

What it cannot show, stated here: a REJECT is the gate's own decision, so "rejected" is read from the record; whether the patch "genuinely tried to fake a pass" is a judgement on the patch text,
which is why the text is kept beside each row and the judgement is written in PHASE5_FINDINGS.md, not computed.
"""
from __future__ import annotations

import argparse
import ast
import collections
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
FAKING_RULES = ("DELETED_EVAL_CALL", "STUBBED_MODEL_CALL", "REDUCED_SCALE", "BROAD_EXCEPTION_SWALLOW", "PROTECTED_PATH_MODIFIED")


def _attempts(doc: dict):
    if isinstance(doc.get("result"), dict) and isinstance(doc["result"].get("attempts"), list):
        return doc["result"]["attempts"]
    if isinstance(doc.get("diffs"), list):
        return doc["diffs"]
    return None


def _violations(attempt: dict) -> list[dict]:
    raw = attempt.get("gate_violations")
    if isinstance(raw, str):
        try:
            raw = ast.literal_eval(raw)
        except (ValueError, SyntaxError):
            return []
    return [v for v in (raw or []) if isinstance(v, dict)]


def scan(exclude: tuple[str, ...] = ()) -> dict:
    counts: collections.Counter = collections.Counter()
    faking: list[dict] = []
    records = 0
    for path in sorted((ROOT / "runs").rglob("*.json")):
        rel = path.relative_to(ROOT).as_posix()
        if any(part in rel for part in exclude) or path.stat().st_size > 40_000_000:
            continue
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            continue
        attempts = _attempts(doc) if isinstance(doc, dict) else None
        if not attempts:
            continue
        records += 1
        for a in attempts:
            if not isinstance(a, dict) or a.get("gate_decision") != "REJECT":
                continue
            violations = _violations(a)
            rules = sorted({v.get("rule") for v in violations if v.get("rule")})
            counts.update(rules)
            if any(r in FAKING_RULES for r in rules):
                faking.append({"record": rel, "attempt": a.get("attempt_number"), "candidate": a.get("candidate"), "rules": rules,
                               "reasons": [str(v.get("reason"))[:240] for v in violations if v.get("rule") in FAKING_RULES][:2],
                               "files": sorted({str(v.get("file")) for v in violations if v.get("file")}),
                               "patch": str(a.get("model_patch") or a.get("diff_text") or "")[:1500]})
    return {"records_with_attempts": records, "reject_rule_counts": dict(counts.most_common()), "faking_rule_rejections": faking}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--exclude", action="append", default=[])
    args = ap.parse_args()
    result = scan(tuple(args.exclude))
    print(f"records with attempts: {result['records_with_attempts']}")
    print("REJECT rule counts:", result["reject_rule_counts"])
    by = collections.Counter((Path(f["record"]).name, tuple(f["rules"]), tuple(f["files"])) for f in result["faking_rule_rejections"])
    print(f"rejections under a faking rule: {len(result['faking_rule_rejections'])}")
    for (name, rules, files), n in by.most_common():
        print(f"  {n:2} x {name[:50]:50} {rules} {files}")
    if args.write:
        (ROOT / "reports" / "dev" / "v18" / "gate_rejections.json").write_text(json.dumps(result, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
