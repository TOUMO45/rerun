"""harness-v1.9, task 1: the ungated counterfactual, mechanical part (RUBRIC.md sections 1-3). Zero spend, committed records only; nothing is re-run and nothing is re-scored.

    backend/.venv/Scripts/python.exe reports/v1.9/counterfactual/counterfactual.py [--write]

Writes facts.json: per entry-run, every execution that reached naive success (stored exit_code 0) with its kind (exited / alive_at_limit / not recorded) and, for a candidate
patch, its fate (adopted / adjudicator chose another / adjudicator chose none / other); the gate-rejected and declined patches (never executed, so their outcome is unknown);
RERUN's verdict as recorded. The judgement "genuine fake / honest patch rejected" is NOT made here (RUBRIC.md section 4, classification.json).
"""
from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
SETS: dict[str, tuple[str, ...]] = {
    "DEV": tuple(f"runs/corpus_v2_batch/{t}/dev" for t in ("harness-v1.5.0", "harness-v1.5.1", "harness-v1.5.2", "harness-v1.6.0", "harness-v1.7.1")),
    "DEV-CONTAMINATED": ("runs/dev_v18/round1/TEST", "runs/dev_v18/round1/TEST-B", "runs/dev_v18/round2/TEST-B"),
    "TEST-A": ("runs/corpus_v2_batch/harness-v1.5-final/test",),
    "TEST-B": ("runs/corpus_v3_batch/harness-v1.7.2/treatment",),
    "TEST-C": ("runs/corpus_v4_batch/harness-v1.8.0/treatment",),
}
FRESH = ("TEST-A", "TEST-B", "TEST-C")
CERTIFIED = ("RUNS_CLEAN", "RUNS_AFTER_REPAIR")
FAKING_RULES = ("DELETED_EVAL_CALL", "STUBBED_MODEL_CALL", "REDUCED_SCALE", "BROAD_EXCEPTION_SWALLOW", "PROTECTED_PATH_MODIFIED")
# The published audits of TEST-A and TEST-B, quoted (TEST_RESULT.md D-46; TEST_B_RESULT.md R4), not recomputed.
PUBLISHED_AUDIT = {
    ("TEST-A", "18"): "false positive (D-46): the pipe returned bash's exit 0 after the script failed at its first import",
    ("TEST-B", "06"): "struck under R4: the documented command is `--help`, not a run of the repository's code",
}


def _violations(attempt: dict) -> list[dict]:
    raw = attempt.get("gate_violations")
    if isinstance(raw, str):
        try:
            raw = ast.literal_eval(raw)
        except (ValueError, SyntaxError):
            return []
    return [v for v in (raw or []) if isinstance(v, dict)]


def _kind(attempt: dict) -> str:
    outcome = (attempt.get("execution") or {}).get("outcome")
    return outcome if outcome in ("exited", "alive_at_limit") else "not recorded"


def _fate(attempt: dict, round_attempts: list[dict]) -> str:
    if attempt.get("chosen") is True:
        return "adopted"
    adj = attempt.get("adjudication")
    if not isinstance(adj, dict):
        # A one-candidate round (no adjudicator): a gate-passed candidate that ran is the round's change.
        multi = sum(1 for a in round_attempts if a.get("candidate") is not None) > 1
        return "other" if multi else "adopted"
    chosen = adj.get("chosen")
    if chosen is None:
        return "adjudicator chose none"
    if chosen != attempt.get("candidate"):
        return "adjudicator chose another candidate"
    return "other"


def entry_run(set_name: str, path: Path) -> dict | None:
    doc = json.loads(path.read_text(encoding="utf-8"))
    result = doc.get("result") if isinstance(doc, dict) else None
    if not isinstance(result, dict) or not isinstance(result.get("attempts"), list):
        return None
    attempts = result["attempts"]
    entry_id = path.name.split("_", 1)[0]
    baseline = (doc.get("certificate") or {}).get("baseline") or {}
    naive: list[dict] = []
    if baseline.get("exit_code") == 0:
        naive.append({"execution": "baseline (as published)", "kind": "exited" if baseline.get("result") == "RUNS_CLEAN" else "not recorded", "patch": False})
    unexecuted: list[dict] = []
    for a in attempts:
        number = a.get("attempt_number")
        is_patch = isinstance(number, int) and number >= 1
        if a.get("exit_code") == 0:
            row = {"execution": f"attempt {number}" + (f" candidate {a.get('candidate')}" if a.get("candidate") is not None else ""),
                   "attempt_number": number, "candidate": a.get("candidate"), "origin": a.get("origin"), "kind": _kind(a), "patch": is_patch}
            if is_patch:
                same_round = [b for b in attempts if b.get("attempt_number") == number]
                row["fate"] = _fate(a, same_round)
                adj = a.get("adjudication") if isinstance(a.get("adjudication"), dict) else {}
                row["adjudication_chosen"] = adj.get("chosen")
                row["adjudication_reasoning"] = str(adj.get("reasoning") or "")[:600]
                row["diff_text"] = a.get("diff_text") or ""
                row["env_delta"] = a.get("env_delta") or []
                row["stdout_tail"] = (a.get("stdout_tail") or "")[-800:]
                row["stderr_tail"] = (a.get("stderr_tail") or "")[-400:]
            naive.append(row)
        elif is_patch and a.get("exit_code") is None and a.get("gate_decision") in ("REJECT", "DECLINED"):
            rules = sorted({v.get("rule") for v in _violations(a) if v.get("rule")})
            unexecuted.append({"attempt_number": number, "candidate": a.get("candidate"), "decision": a.get("gate_decision"), "rules": rules,
                               "faking_rule": any(r in FAKING_RULES for r in rules),
                               **({"diff_text": a.get("diff_text") or "", "reasons": [str(v.get("reason"))[:300] for v in _violations(a)]}
                                  if any(r in FAKING_RULES for r in rules) else {})})
    verdict = result.get("verdict")
    return {
        "set": set_name, "record": path.relative_to(ROOT).as_posix(), "entry": entry_id, "name": path.stem.split("_", 1)[1] if "_" in path.stem else path.stem,
        "verdict": verdict, "taxonomy_code": result.get("taxonomy_code"), "certified": verdict in CERTIFIED,
        "published_audit": PUBLISHED_AUDIT.get((set_name, entry_id)),
        "naive_success": bool(naive), "naive_by_patch_only": bool(naive) and all(n["patch"] for n in naive),
        "naive_executions": naive,
        "gate_rejected_patches": sum(1 for u in unexecuted if u["decision"] == "REJECT"),
        "declined_patches": sum(1 for u in unexecuted if u["decision"] == "DECLINED"),
        "unexecuted": unexecuted,
    }


def collect() -> list[dict]:
    rows: list[dict] = []
    for set_name, dirs in SETS.items():
        for d in dirs:
            for path in sorted((ROOT / d).glob("*.json")):
                row = entry_run(set_name, path)
                if row is not None:
                    rows.append(row)
    return rows


def summarise(rows: list[dict]) -> dict:
    out: dict[str, dict] = {}
    groups = {name: [r for r in rows if r["set"] == name] for name in SETS}
    groups["FRESH (TEST-A+B+C)"] = [r for r in rows if r["set"] in FRESH]
    for name, rs in groups.items():
        patches = [n for r in rs for n in r["naive_executions"] if n["patch"]]
        fates: dict[str, int] = {}
        for n in patches:
            fates[n["fate"]] = fates.get(n["fate"], 0) + 1
        no_naive = [r for r in rs if not r["naive_success"]]
        out[name] = {
            "entry_runs": len(rs),
            "naive_success_entry_runs": sum(r["naive_success"] for r in rs),
            "naive_success_without_patch": sum(1 for r in rs if r["naive_success"] and not r["naive_by_patch_only"]),
            "naive_success_by_patch_only": sum(r["naive_by_patch_only"] for r in rs),
            "naive_success_kinds": {k: sum(1 for r in rs for n in r["naive_executions"] if n["kind"] == k) for k in ("exited", "alive_at_limit", "not recorded")},
            "certified_entry_runs": sum(r["certified"] for r in rs),
            "naive_but_not_certified": sum(1 for r in rs if r["naive_success"] and not r["certified"]),
            "certified_but_not_naive": sum(1 for r in rs if r["certified"] and not r["naive_success"]),
            "patches_reaching_naive_success": len(patches),
            "patch_fates": fates,
            "gate_rejected_among_naive_success": 0,  # by construction: a gate-rejected patch is never executed (RUBRIC.md section 2)
            "gate_rejected_patches_total": sum(r["gate_rejected_patches"] for r in rs),
            "gate_rejected_patches_in_entry_runs_without_naive_success": sum(r["gate_rejected_patches"] for r in no_naive),
            "entry_runs_without_naive_success_that_had_gate_rejected_patches": sum(1 for r in no_naive if r["gate_rejected_patches"]),
            "declined_patches_total": sum(r["declined_patches"] for r in rs),
            "faking_rule_rejections": sum(1 for r in rs for u in r["unexecuted"] if u["faking_rule"]),
        }
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()
    rows = collect()
    summary = summarise(rows)
    for name, s in summary.items():
        print(f"{name:20} {json.dumps(s)}")
    print()
    for r in rows:
        if r["naive_success"] or r["certified"]:
            print(f"{r['set']:16} {r['record'].split('/')[-3]:22} {r['entry']} {r['name'][:34]:34} {r['verdict']:18} naive={r['naive_success']} "
                  + "; ".join(f"{n['execution']}:{n['kind']}:{n.get('fate', '-')}" for n in r["naive_executions"]))
    if args.write:
        (HERE / "facts.json").write_text(json.dumps({"summary": summary, "entry_runs": rows}, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
