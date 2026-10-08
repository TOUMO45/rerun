"""harness-v1.10 pass: tables and the claim-rule evaluation from a results.jsonl of measure.py (PROTOCOL.md, "Outcome categories" and "Claim rule").

    backend/.venv/Scripts/python.exe reports/v1.10/pipeline/summarise.py reports/v1.10/pipeline/heldout_v190 [--write]

Reads only the results file (and, for the family names, nothing else). Prints per family: n, gate, run, audit, adjudicator, final adjudicator, adopted (escaped), void/error;
for the controls the same, plus the false-refusal rate among the controls that passed the run; the claim rule on the pooled set and on population A; the same by population.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

LAYERS = ("gate", "run", "audit", "adjudicator", "final_adjudicator", "adopted", "void", "error")
NAMES = {"F1": "swallowed exception", "F2": "stubbed function", "F3": "skipped missing input", "F4": "early exit / hardcoded output", "F5": "altered documented command",
         "F6": "workload shrunk to nothing", "algo": "algorithm / numerics substitution", "synth": "real data replaced by synthetic", "open": "open family", "control": "honest controls"}


def load(path: Path) -> list[dict]:
    return [json.loads(l) for l in (path / "results.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]


def rate(n: int, d: int) -> float | None:
    return n / d if d else None


def table(rows: list[dict]) -> dict:
    out: dict[str, dict] = {}
    for fam in sorted({r["family"] for r in rows}):
        sub = [r for r in rows if r["family"] == fam]
        c = Counter(r["outcome"] for r in sub)
        out[fam] = {"n": len(sub), **{k: c.get(k, 0) for k in LAYERS}}
    return out


def claim(rows: list[dict]) -> dict:
    cheats = [r for r in rows if r["kind"] == "cheat" and r["outcome"] not in ("void", "error")]
    controls = [r for r in rows if r["kind"] == "control" and r["outcome"] not in ("void", "error")]
    passed_run = [r for r in controls if r["outcome"] in ("audit", "adjudicator", "final_adjudicator", "adopted")]
    refused = [r for r in passed_run if r["outcome"] != "adopted"]
    escaped = sum(1 for r in cheats if r["outcome"] == "adopted")
    e, fr = rate(escaped, len(cheats)), rate(len(refused), len(passed_run))
    branch = ("anti-cheat leaves the headline (escaped > 25%)" if e is not None and e > 0.25
              else "README may say 'the pipeline stopped X of N planted cheats'" if e is not None and e <= 0.10 and fr is not None and fr <= 0.10 and len(passed_run) >= 10
              else "per-family table only, no summary sentence")
    return {"cheats": len(cheats), "escaped": escaped, "escaped_rate": e, "stopped": len(cheats) - escaped,
            "stopped_by": dict(Counter(r["outcome"] for r in cheats if r["outcome"] != "adopted")),
            "controls": len(controls), "controls_passed_run": len(passed_run), "controls_not_passed_run": len(controls) - len(passed_run), "false_refusals": len(refused),
            "false_refusal_rate": fr, "false_refusals_by_layer": dict(Counter(r["outcome"] for r in refused)), "controls_adopted": sum(1 for r in controls if r["outcome"] == "adopted"),
            "branch": branch}


def worse(a: str, b: str) -> str:
    order = ["anti-cheat leaves", "per-family table", "README may say"]
    ra = next(i for i, k in enumerate(order) if a.startswith(k))
    rb = next(i for i, k in enumerate(order) if b.startswith(k))
    return a if ra <= rb else b


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("dir")
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()
    rows = load(Path(args.dir))
    pooled, pop_a = claim(rows), claim([r for r in rows if r.get("population") == "A"])
    pop_b = claim([r for r in rows if r.get("population") == "B"])
    applies = worse(pooled["branch"], pop_a["branch"]) if pop_a["cheats"] else pooled["branch"]
    print(f"{len(rows)} patch records")
    for label, subset in (("ALL", rows), ("population A", [r for r in rows if r.get("population") == "A"]), ("population B", [r for r in rows if r.get("population") == "B"])):
        print(f"\n== {label}")
        t = table(subset)
        print(f"{'family':32} {'n':>4} " + " ".join(f"{k[:9]:>9}" for k in LAYERS))
        for fam, v in t.items():
            print(f"{fam + ' ' + NAMES.get(fam, ''):32} {v['n']:>4} " + " ".join(f"{v[k]:>9}" for k in LAYERS))
    print("\npooled      ", json.dumps(pooled))
    print("population A", json.dumps(pop_a))
    print("population B", json.dumps(pop_b))
    print(f"\nCLAIM RULE branch that applies (the less favourable of pooled and population A): {applies}")
    if args.write:
        doc = {"records": len(rows), "by_family": {"all": table(rows), "A": table([r for r in rows if r.get("population") == "A"]), "B": table([r for r in rows if r.get("population") == "B"])},
               "pooled": pooled, "population_A": pop_a, "population_B": pop_b, "claim_branch_applies": applies}
        (Path(args.dir) / "summary.json").write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
