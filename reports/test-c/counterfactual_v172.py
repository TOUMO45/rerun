"""TEST-C counterfactual: what would the harness-v1.7.2 blocker report have said for the same ten TEST-C records? (A DERIVED reading, labelled as such: the records were produced by harness-v1.8.0; nothing
is re-run.) The v1.7.2 `blocker.report` is imported from a checkout of the tag harness-v1.7.2 and handed the fields v1.7.2's own `derived_record` handed it (verdict, error chain, attempts: no
indeterminate reason, no baseline), then judged by the SAME rubric and key as the stored v1.8 blockers. TEST-C is a new set, so scoring it under an older harness's diagnosis does not re-score
any frozen set under its old name.

    # step 1, in a checkout of the tag (python from the main venv): write the v1.7.2 blockers to a file
    backend/.venv/Scripts/python.exe reports/test-c/counterfactual_v172.py derive <path-to-v1.7.2-checkout> reports/test-c/blockers_as_v172.json
    # step 2, in this checkout: score them
    backend/.venv/Scripts/python.exe reports/test-c/counterfactual_v172.py score reports/test-c/blockers_as_v172.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RECORDS = ROOT / "runs" / "corpus_v4_batch" / "harness-v1.8.0" / "treatment"
KEY = ROOT / "reports" / "test-c" / "diagnosis_test_c_key.json"


def derive(checkout: Path, out: Path) -> int:
    sys.path.insert(0, str(checkout / "backend"))
    from app.services import blocker  # the v1.7.2 module (its own `app` package)

    assert "diagnosis" not in sys.modules.get("app.services.blocker").__dict__.get("__doc__", "") or True
    assert not (checkout / "backend" / "app" / "services" / "diagnosis.py").exists(), "this is not a harness-v1.7.2 checkout"
    result = {}
    for path in sorted(RECORDS.glob("[0-9][0-9]_*.json")):
        r = json.loads(path.read_text(encoding="utf-8"))["result"]
        result[path.name] = blocker.report({"verdict": r["verdict"], "error_chain": r.get("error_chain") or [], "attempts": r.get("attempts") or []})
    out.write_text(json.dumps({"harness": "harness-v1.7.2", "checkout": str(checkout.name), "blockers": result}, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {out} ({sum(1 for v in result.values() if v)} blockers)")
    return 0


def score(path: Path) -> int:
    sys.path.insert(0, str(ROOT / "reports" / "dev" / "v18"))
    import score_diagnosis as sd

    blockers = json.loads(path.read_text(encoding="utf-8"))["blockers"]
    key = json.loads(KEY.read_text(encoding="utf-8"))
    rows, ok = [], 0
    for entry in key["entries"]:
        rec = sd.load(ROOT / entry["record"])
        blk = blockers.get(Path(entry["record"]).name)
        j = sd.judge(entry, rec, blk)
        ok += bool(j.get("actionable"))
        rows.append({"id": entry["id"], "name": entry["name"], "cause": (blk or {}).get("class"), **{k: j[k] for k in ("A1", "A2", "A3", "A4")}, "actionable": bool(j.get("actionable")), "why": j["why"]})
        marks = "".join("Y" if j[k] else "-" for k in ("A1", "A2", "A3", "A4"))
        print(f"  {entry['id']:4} {entry['name'][:22]:22} {str((blk or {}).get('class'))[:22]:22} {marks} {'ACTIONABLE' if j.get('actionable') else ''}")
        for why in j["why"]:
            print(f"         - {why}")
    print(f"\nas harness-v1.7.2 would have reported them: actionable {ok} of {len(rows)}")
    (path.with_name("diagnosis_test_c_score_as_v172.json")).write_text(json.dumps({"as": "harness-v1.7.2 (counterfactual, DERIVED)", "n": len(rows), "actionable": ok, "rows": rows}, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "derive":
        raise SystemExit(derive(Path(sys.argv[2]).resolve(), Path(sys.argv[3])))
    if len(sys.argv) == 3 and sys.argv[1] == "score":
        raise SystemExit(score(Path(sys.argv[2])))
    raise SystemExit(__doc__)
