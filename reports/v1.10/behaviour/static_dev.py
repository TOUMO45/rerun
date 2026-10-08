"""harness-v1.10 task 4, development: the STATIC half of the behavioural checks (backend/app/services/behaviour.py) over the planted corpus's DEV half and the SPENT held-out half.

    backend/.venv/Scripts/python.exe reports/v1.10/behaviour/static_dev.py [--half dev|heldout|both] [--out <json>]

Both halves are development material from here on (the held-out half was spent by the full-pipeline measurement of Task 1); nothing printed here is a measurement of v1.10.
It reports, per family and kind, how many patches the static findings refuse and by which named reason; for the honest controls, how many are refused (false refusals).
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend"))
from app.services import behaviour, tamper_gate  # noqa: E402

CHECKOUTS = ROOT / ".cache" / "planted_repos"


def rows_of(half: str) -> list[dict]:
    corpus = {json.loads(l)["id"]: json.loads(l) for l in (ROOT / "reports/v1.9/planted/corpus.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()}
    split = json.loads((ROOT / "reports/v1.9/planted/split.json").read_text(encoding="utf-8"))
    ids = split["dev"] + split["heldout"] if half == "both" else split[half]
    return [corpus[i] for i in sorted(ids)]


def judge(row: dict, bases: dict) -> list[behaviour.Finding]:
    repo = Path(bases[row["base"]]["checkout"])
    prepared = tamper_gate.prepare_patch(row["diff"])
    originals = {p: (repo / p).read_text(encoding="utf-8") for p in prepared.paths if (repo / p).is_file()}
    news = tamper_gate.patched_sources(row["diff"], originals)
    return behaviour.candidate_findings(originals, {p: news.get(p) for p in prepared.paths if p in news})


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--half", default="both")
    ap.add_argument("--out")
    ap.add_argument("--show", help="print the findings of the patches of this kind/family prefix, e.g. control or F3")
    args = ap.parse_args()
    bases_doc = json.loads((ROOT / "reports/v1.9/planted/bases.json").read_text(encoding="utf-8"))["bases"]
    bases = {b["name"]: {**b, "checkout": str(CHECKOUTS / b["repo"].replace("/", "_"))} for b in bases_doc}
    table: dict = defaultdict(lambda: Counter())
    detail = []
    for row in rows_of(args.half):
        try:
            found = judge(row, bases)
        except Exception as exc:  # noqa: BLE001
            found = []
            table[(row["kind"], row["family"])]["error"] += 1
            detail.append({"id": row["id"], "error": f"{type(exc).__name__}: {exc}"})
            continue
        key = (row["kind"], row["family"])
        table[key]["n"] += 1
        if found:
            table[key]["refused"] += 1
            for r in sorted({f.reason for f in found}):
                table[key][r] += 1
        detail.append({"id": row["id"], "base": row["base"], "kind": row["kind"], "family": row["family"], "style": row.get("style"),
                       "findings": [f.as_dict() for f in found]})
        if args.show and (row["kind"].startswith(args.show) or row["family"].startswith(args.show)) and found:
            print(row["id"], [(f.reason, f.detail[:110]) for f in found][:3])
    for (kind, fam), c in sorted(table.items()):
        reasons = {k: v for k, v in c.items() if k not in ("n", "refused", "error")}
        print(f"{kind:8} {fam:4} n={c['n']:3} refused={c['refused']:3} {reasons}")
    if args.out:
        Path(args.out).write_text(json.dumps({"half": args.half, "rows": detail}, indent=1) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
