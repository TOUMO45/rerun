"""harness-v1.8, Phase 2 item (a): re-generate the blocker text for the 14 blocker records of the 21 held-out entries (now DEV-CONTAMINATED) from their own
evidence, and re-judge them against the answer key committed BEFORE the generator existed (diagnosis_key.json).

For every entry the script prints, and writes to diagnosis_regen.json / DIAGNOSIS_REGEN.md:
  - the text the record carries (written by harness-v1.7.x: a fixed per-class sentence), judged by the key;
  - the text `backend/app/services/blocker.report` gives now, judged by the key;
  - whether the new `error_line` is a verbatim line of the record's own output (ANSI colour codes removed).
"Right" means: every `must` regex matches the text (what_a_human_must_supply + next_action), no `must_not` regex matches, fixable_by is in the key's list, and
the error line matches the key's regex and is verbatim. Nothing here is a model's opinion; the key is committed before the generator.

Run:  backend/.venv/Scripts/python.exe reports/dev/v18/check_diagnosis.py [--write]
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend"))

from app.services import blocker, diagnosis  # noqa: E402

KEY = json.loads((Path(__file__).parent / "diagnosis_key.json").read_text(encoding="utf-8"))


def load(record_path: str) -> tuple[dict, dict | None]:
    """(the dict `blocker.report` is given, the blocker the record stored)."""
    d = json.loads((ROOT / record_path).read_text(encoding="utf-8"))
    if "result" in d:  # a batch record
        r, cert = d["result"], d["certificate"]
        rec = {"verdict": r["verdict"], "error_chain": r["error_chain"], "attempts": r["attempts"], "indeterminate_reason": r.get("indeterminate_reason") or "",
               "baseline": cert.get("baseline"), "full_log": cert.get("full_log")}
        return rec, r.get("blocker")
    rec = {"verdict": d["verdict"], "error_chain": d["error_chain"], "attempts": d["diffs"], "indeterminate_reason": d.get("indeterminate_reason") or "",
           "baseline": d.get("baseline"), "full_log": d.get("full_log")}
    return rec, d.get("blocker")


def evidence_text(rec: dict) -> str:
    ctx = diagnosis._Ctx(rec)
    return "\n".join(t for _, t in ctx.blobs)


def judge(entry: dict, fixable_by: str | None, sentence: str, next_action: str, error_line: str, blob: str) -> dict:
    text = f"{sentence or ''} {next_action or ''}"
    missing = [p for p in entry["must"] if not re.search(p, text)]
    forbidden = [p for p in entry["must_not"] if re.search(p, text)]
    fixable_ok = fixable_by in entry["fixable_by"]
    line_ok = bool(re.search(entry["error_line"], error_line or ""))
    verbatim = bool(error_line) and error_line.strip() in diagnosis.strip_ansi(blob)
    return {"right": not missing and not forbidden and fixable_ok and line_ok, "missing": missing, "forbidden": forbidden, "fixable_ok": fixable_ok,
            "line_ok": line_ok, "line_verbatim": verbatim}


def main() -> int:
    rows = []
    for e in KEY["entries"]:
        rec, stored = load(e["record"])
        blob = evidence_text(rec)
        old = judge(e, (stored or {}).get("fixable_by"), (stored or {}).get("what_a_human_must_supply", ""), "", (stored or {}).get("evidence", ""), blob)
        out = blocker.report(rec) or {}
        new = judge(e, out.get("fixable_by"), out.get("what_a_human_must_supply", ""), out.get("next_action", ""), out.get("error_line", ""), blob)
        rows.append({"id": e["id"], "name": e["name"], "kind": e["kind"], "old_text": (stored or {}).get("what_a_human_must_supply"), "old_fixable_by": (stored or {}).get("fixable_by"),
                     "old_judged_right": old["right"], "new_cause": out.get("cause"), "new_diagnosis": out.get("diagnosis"), "new_fixable_by": out.get("fixable_by"),
                     "new_text": out.get("what_a_human_must_supply"), "new_next_action": out.get("next_action"), "new_error_line": out.get("error_line"),
                     "new_judged_right": new["right"], "new_detail": new})
    wrong = [r for r in rows if r["kind"] == "was_wrong"]
    right = [r for r in rows if r["kind"] == "was_right"]
    summary = {
        "entries": len(rows),
        "key_confirms_old_wrong": sum(1 for r in wrong if not r["old_judged_right"]),
        "was_wrong": len(wrong), "was_wrong_now_right": sum(1 for r in wrong if r["new_judged_right"]),
        "was_right": len(right), "was_right_still_right": sum(1 for r in right if r["new_judged_right"]),
        "all_error_lines_verbatim": all(r["new_detail"]["line_verbatim"] for r in rows),
        "evidence_driven": sum(1 for r in rows if r["new_diagnosis"] == "evidence"),
    }
    print(f"{'entry':<28} {'was':<10} {'old right (key)':<16} {'new cause':<28} {'new right':<10} verbatim")
    for r in rows:
        print(f"{r['id']+' '+r['name']:<28} {r['kind']:<10} {str(r['old_judged_right']):<16} {str(r['new_cause']):<28} {str(r['new_judged_right']):<10} {r['new_detail']['line_verbatim']}")
        if not r["new_judged_right"]:
            print("     NOT RIGHT:", {k: v for k, v in r["new_detail"].items() if k in ("missing", "forbidden", "fixable_ok", "line_ok")})
            print("     text:", r["new_text"], "| next:", r["new_next_action"], "| fixable_by:", r["new_fixable_by"], "| line:", r["new_error_line"])
    print(json.dumps(summary, indent=1))
    if "--write" in sys.argv:
        (Path(__file__).parent / "diagnosis_regen.json").write_text(json.dumps({"summary": summary, "rows": rows}, indent=1, ensure_ascii=False), encoding="utf-8")
        lines = ["# Diagnosis re-generated from the records (harness-v1.8, Phase 2 item a)", "",
                 "Answer key: `diagnosis_key.json`, committed before `backend/app/services/diagnosis.py` existed. Script: `check_diagnosis.py`. The 14 entries are the blocker "
                 "records among the 21 held-out entries, now DEV-CONTAMINATED.", "",
                 f"**Was wrong, now right: {summary['was_wrong_now_right']} of {summary['was_wrong']}. Was right, still right: {summary['was_right_still_right']} of {summary['was_right']}.** "
                 f"The key rejects the old stored text for {summary['key_confirms_old_wrong']} of the {summary['was_wrong']} (so the key and my triage judgement agree). "
                 f"Error line verbatim in the record's own output: {'all' if summary['all_error_lines_verbatim'] else 'NOT ALL'}.", "",
                 "| entry | was | new cause | new right | fixable_by (old -> new) |", "|---|---|---|---|---|"]
        for r in rows:
            lines.append(f"| {r['id']} {r['name']} | {r['kind']} | `{r['new_cause']}` ({r['new_diagnosis']}) | {'yes' if r['new_judged_right'] else '**no**'} | {r['old_fixable_by']} -> {r['new_fixable_by']} |")
        lines += ["", "## Texts, entry by entry", ""]
        for r in rows:
            lines += [f"### {r['id']} {r['name']} ({r['kind']}; new text judged {'right' if r['new_judged_right'] else 'NOT right'})", "",
                      f"- old: {r['old_text']}", f"- new: {r['new_text']}", f"- next action: {r['new_next_action']}", f"- error line: `{r['new_error_line']}`", ""]
        (Path(__file__).parent / "DIAGNOSIS_REGEN.md").write_text("\n".join(lines), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
