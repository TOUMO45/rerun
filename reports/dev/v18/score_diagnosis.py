"""harness-v1.8, Phase 3: the actionable-diagnosis scorer. The rubric is `DIAGNOSIS_RUBRIC.md`; this script applies it mechanically to a committed answer key.

    backend/.venv/Scripts/python.exe reports/dev/v18/score_diagnosis.py --key reports/dev/v18/diagnosis_dev_key.json [--as stored|derived|both] [--write OUT.json]

For each key entry (one per NON-RUNNING record) it reads the record, takes the blocker the run STORED and/or the blocker the CURRENT rules derive from the record's own fields, and tests four
criteria (A1 verbatim, A2 right cause, A3 concrete next action, A4 anchored in the final state). ACTIONABLE = all four. The score is a count, stratified by blocker family, and it is
reported BESIDE the run rate and never merged with it. Nothing here reads a diagnosis to decide what the key says: the key is written from the raw log first (see the rubric, "Procedure").
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend"))
from app.services import blocker as blocker_mod  # noqa: E402
from app.services import diagnosis  # noqa: E402

STOP = frozenset("error errors line file files module name found none object attribute type value command failed return returned status exit code that this with from have been which when "
                 "then than into only also does more most some such these those their there where while would could should about after before other another sandbox record run runs "
                 "ran the and for are not but can will its was were has had you your our out one two".split())


def load(path: Path) -> dict:
    """The record in the shape `blocker.report` takes, plus the blocker the run stored."""
    d = json.loads(path.read_text(encoding="utf-8"))
    if "result" in d:  # a batch record
        r, cert = d["result"], d.get("certificate") or {}
        return {"verdict": r["verdict"], "error_chain": r.get("error_chain") or [], "attempts": r.get("attempts") or [], "indeterminate_reason": r.get("indeterminate_reason") or "",
                "baseline": cert.get("baseline"), "full_log": cert.get("full_log") or "", "stored": r.get("blocker")}
    return {"verdict": d["verdict"], "error_chain": d.get("error_chain") or [], "attempts": d.get("diffs") or d.get("attempts") or [], "indeterminate_reason": d.get("indeterminate_reason") or "",
            "baseline": d.get("baseline"), "full_log": d.get("full_log") or "", "stored": d.get("blocker")}


def _flat(text: str) -> str:
    return re.sub(r"\s+", " ", diagnosis.strip_ansi(text or "")).strip()


def tokens(text: str) -> set[str]:
    return {t.lower() for t in re.findall(r"[A-Za-z_][\w.\-+/]{3,}", diagnosis.strip_ansi(text or "")) if t.lower() not in STOP}


def judge(entry: dict, rec: dict, blk: dict | None) -> dict:
    """The four criteria for one (key entry, record, blocker). Every failing criterion says why."""
    out = {"A1": False, "A2": False, "A3": False, "A4": False, "why": []}
    if not blk:
        out["why"].append("no blocker report")
        return out
    line = _flat(blk.get("error_line") or blk.get("evidence") or "")
    text = f"{blk.get('what_a_human_must_supply') or ''} {blk.get('next_action') or ''}"
    waived = bool(entry.get("no_output_expected"))  # a TIMEOUT: there is no failing line by nature; the rubric waives A1 and A3 for it, A2 still applies
    ctx = diagnosis._Ctx({k: rec[k] for k in ("verdict", "error_chain", "attempts", "indeterminate_reason", "baseline", "full_log")})
    everything = _flat("\n".join(t for _, t in ctx.blobs) + "\n" + rec["indeterminate_reason"] + "\n" + json.dumps(rec["attempts"], ensure_ascii=False))
    # A1: the quoted line is a line of the record's own output
    out["A1"] = waived or (bool(line) and line in everything)
    if not out["A1"]:
        out["why"].append("A1: the quoted line is not in the record's own output")
    # A2: the cause the key proves, and none of the claims it forbids
    musts = [bool(re.search(p, text)) for p in entry.get("must", [])]
    nots = [bool(re.search(p, text)) for p in entry.get("must_not", [])]
    fixable_ok = (blk.get("fixable_by") in entry["fixable_by"]) if entry.get("fixable_by") else True
    out["A2"] = bool(entry.get("establishable", True)) and all(musts) and not any(nots) and fixable_ok
    if not entry.get("establishable", True):
        out["why"].append("A2: the record does not establish the cause (the key says so); counted as not actionable")
    else:
        out["why"] += [f"A2: missing {p!r}" for p, ok in zip(entry.get("must", []), musts) if not ok]
        out["why"] += [f"A2: forbidden claim {p!r} is present" for p, bad in zip(entry.get("must_not", []), nots) if bad]
        if not fixable_ok:
            out["why"].append(f"A2: fixable_by {blk.get('fixable_by')!r} not in {entry['fixable_by']}")
    # A3: the next action names something from the evidence (a token of the quoted line, or a backticked artifact beside it)
    grounded = bool(tokens(line) & tokens(text)) or bool(re.search(r"`[^`]{2,}`", blk.get("next_action") or ""))
    out["A3"] = waived or grounded
    if not out["A3"]:
        out["why"].append("A3: the next action names nothing the evidence names")
    # A4: the line is what the run ENDED on (the last link of the error chain, the output of the last attempt that ran something, the baseline's evidence when nothing ran, or the stop's own
    # reason), not a line from an earlier attempt or step
    final = waived or (bool(line) and any(line in t for t in final_texts(rec)))
    out["A4"] = bool(final)
    if not out["A4"]:
        out["why"].append("A4: the quoted line is not in the run's final state (it is from an earlier attempt or step)")
    out["actionable"] = all(out[k] for k in ("A1", "A2", "A3", "A4"))
    return out


def strings(node) -> list[str]:
    """Every string value in a record's structures, decoded (no JSON escaping), for the key's proof check."""
    if isinstance(node, str):
        return [node]
    if isinstance(node, dict):
        return [t for v in node.values() for t in strings(v)]
    if isinstance(node, (list, tuple)):
        return [t for v in node for t in strings(v)]
    return []


def final_texts(rec: dict) -> list[str]:
    """The flattened text of the run's FINAL state (the same definition `diagnosis._Ctx.find_final` uses, plus the stop's reason)."""
    texts = [_flat(rec["indeterminate_reason"])]
    if rec["error_chain"]:
        texts.append(_flat(rec["error_chain"][-1].get("error")))
    ran = [a for a in rec["attempts"] if (a or {}).get("stderr_tail") or (a or {}).get("stdout_tail")]
    if ran:
        texts += [_flat(ran[-1].get("stderr_tail")), _flat(ran[-1].get("stdout_tail"))]
    else:
        texts.append(_flat((rec.get("baseline") or {}).get("evidence")))
    return texts


def derive(rec: dict) -> dict | None:
    return blocker_mod.report({k: rec[k] for k in ("verdict", "error_chain", "attempts", "indeterminate_reason", "baseline", "full_log")})


def score(key: dict, which: str) -> dict:
    rows = []
    for entry in key["entries"]:
        rec = load(ROOT / entry["record"])
        blk = rec["stored"] if which == "stored" else derive(rec)
        j = judge(entry, rec, blk)
        rows.append({"id": entry["id"], "name": entry["name"], "verdict": rec["verdict"], "family": (blk or {}).get("family"), "cause": (blk or {}).get("cause"),
                     "diagnosis": (blk or {}).get("diagnosis"), **{k: j[k] for k in ("A1", "A2", "A3", "A4")}, "actionable": bool(j.get("actionable")), "why": j["why"]})
    fam: dict[str, Counter] = defaultdict(Counter)
    for r in rows:
        fam[r["family"] or "(none)"]["actionable" if r["actionable"] else "not"] += 1
    return {"as": which, "n": len(rows), "actionable": sum(r["actionable"] for r in rows), "by_family": {f: dict(c) for f, c in sorted(fam.items())}, "rows": rows}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--key", required=True)
    ap.add_argument("--as", dest="which", default="both", choices=("stored", "derived", "both"))
    ap.add_argument("--write")
    ap.add_argument("--check-key", action="store_true", help="verify that every entry's `proof` is a line of its record's own raw output, then stop")
    args = ap.parse_args()
    key = json.loads(Path(args.key).read_text(encoding="utf-8"))
    if args.check_key:
        bad = 0
        for entry in key["entries"]:
            rec = load(ROOT / entry["record"])
            raw = _flat(" ".join(strings({k: rec[k] for k in ("error_chain", "attempts", "baseline", "indeterminate_reason", "full_log")})))
            ok = _flat(entry["proof"]) in raw
            bad += not ok
            print(f"  {entry['id']:4} proof {'found' if ok else 'NOT FOUND'}: {entry['proof'][:90]}")
        return 1 if bad else 0
    results = {w: score(key, w) for w in (("stored", "derived") if args.which == "both" else (args.which,))}
    for w, res in results.items():
        print(f"\n=== blocker as {w}: actionable {res['actionable']} of {res['n']} non-running entries ===")
        for r in res["rows"]:
            marks = "".join("Y" if r[k] else "-" for k in ("A1", "A2", "A3", "A4"))
            print(f"  {r['id']:4} {r['name'][:28]:28} {r['verdict'][:6]:6} {str(r['cause'])[:30]:30} {r['diagnosis'] or '':13} {marks} {'ACTIONABLE' if r['actionable'] else ''}")
            for why in r["why"]:
                print(f"         - {why}")
        print("  by family:", res["by_family"])
    if args.write:
        Path(args.write).write_text(json.dumps({"key": args.key, "results": results}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
