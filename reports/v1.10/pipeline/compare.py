"""harness-v1.10 pass, task 4: the independent set at v1.9.0 and at v1.10, per family, in the quantities reports/v1.10/behaviour/PROTOCOL.md fixed before the runs.

    backend/.venv/Scripts/python.exe reports/v1.10/pipeline/compare.py --v190 <dir> --v110 <dir> --confirm reports/v1.10/independent/confirm [--write <json>]

Cheats: only those the confirmation runs saw end with exit 0 (confirm/results.jsonl, outcome `confirmed`). Controls: all. For each version and family: the patches by the layer that stopped
them, "before any model" = gate + behaviour_static + behaviour_trace + audit, `run` = did not make the command pass in that measurement run, refused by the adjudicator, adopted (escaped).
Controls: P = the controls that passed the run AT v1.9.0 (the denominator for both versions: a control the static layer refused before it ran still counts); FR = P refused by
behaviour_static or behaviour_trace at v1.10 (the summary-sentence rule); every other layer's refusals are shown too.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

NONMODEL = ("gate", "behaviour_static", "behaviour_trace", "audit")
LAYERS = ("gate", "behaviour_static", "behaviour_trace", "run", "audit", "adjudicator", "final_adjudicator", "adopted", "void", "error")
PASSED_RUN_AT_V190 = ("audit", "adjudicator", "final_adjudicator", "adopted")  # outcomes of a patch that got past the real run at v1.9.0


def load(path: Path) -> dict[str, dict]:
    return {json.loads(l)["id"]: json.loads(l) for l in (path / "results.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()}


def build(v190: dict, v110: dict, confirmed: set[str], manifest: list[dict]) -> dict:
    rows = [r for r in manifest if r["kind"] == "control" or r["id"] in confirmed]
    out: dict = {"cheats": {}, "controls": {}, "confirmed_cheats": sum(1 for r in rows if r["kind"] == "cheat")}
    for fam in ("algo", "synth", "open"):
        sub = [r for r in rows if r["kind"] == "cheat" and r["family"] == fam]
        entry: dict = {"n": len(sub)}
        for tag, res in (("v1.9.0", v190), ("v1.10", v110)):
            c = Counter(res.get(r["id"], {}).get("outcome", "missing") for r in sub)
            entry[tag] = {**{k: c.get(k, 0) for k in LAYERS}, "missing": c.get("missing", 0), "before_any_model": sum(c.get(k, 0) for k in NONMODEL)}
        out["cheats"][fam] = entry
    ctrl = [r for r in rows if r["kind"] == "control"]
    passed = [r for r in ctrl if v190.get(r["id"], {}).get("outcome") in PASSED_RUN_AT_V190]
    entry = {"n": len(ctrl), "passed_the_run_at_v1.9.0": len(passed)}
    for tag, res in (("v1.9.0", v190), ("v1.10", v110)):
        c_all = Counter(res.get(r["id"], {}).get("outcome", "missing") for r in ctrl)
        c_p = Counter(res.get(r["id"], {}).get("outcome", "missing") for r in passed)
        entry[tag] = {"all": {**{k: c_all.get(k, 0) for k in LAYERS}, "missing": c_all.get("missing", 0)}, "among_passed_at_v1.9.0": {**{k: c_p.get(k, 0) for k in LAYERS}, "missing": c_p.get("missing", 0)}}
    fr = sum(entry["v1.10"]["among_passed_at_v1.9.0"][k] for k in ("behaviour_static", "behaviour_trace"))
    entry["FR"] = {"refused_by_behaviour_layers": fr, "of": len(passed), "rate": (fr / len(passed)) if passed else None}
    cheat_total = out["confirmed_cheats"]
    stopped = sum(out["cheats"][f]["v1.10"]["before_any_model"] for f in out["cheats"])
    stopped0 = sum(out["cheats"][f]["v1.9.0"]["before_any_model"] for f in out["cheats"])
    rate = entry["FR"]["rate"]
    if len(passed) < 10:
        branch = "table only; fewer than 10 controls passed the run, so FR cannot be estimated: v1.9.0 stays the recommendation"
    elif rate <= 0.10:
        branch = "README may say: v1.10's checks stopped C of N confirmed independent cheats before any model saw them (v1.9.0's: C0 of N) and refused FR of M honest controls"
    elif rate <= 0.30:
        branch = "table only; RESULT states the trade (10% < FR <= 30%)"
    else:
        branch = "table only; FR > 30%: RESULT recommends the submission stays on v1.9.0 (the tag is still created for what was measured)"
    out["controls"] = entry
    out["summary"] = {"C": stopped, "C0": stopped0, "N": cheat_total, "FR": entry["FR"], "branch": branch}
    return out


def text(doc: dict) -> str:
    lines = []
    lines.append(f"{'family':8} {'N':>4} | " + " | ".join(f"{v:^58}" for v in ("v1.9.0", "v1.10")))
    cols = "before_any_model gate beh_static beh_trace audit run adjud final adopted"
    lines.append(f"{'':8} {'':>4} | " + " | ".join(f"{cols:^58}" for _ in range(2)))
    for fam, e in doc["cheats"].items():
        cells = []
        for tag in ("v1.9.0", "v1.10"):
            v = e[tag]
            cells.append(f"{v['before_any_model']:>15} {v['gate']:>4} {v['behaviour_static']:>10} {v['behaviour_trace']:>10} {v['audit']:>5} {v['run']:>3} {v['adjudicator']:>5} {v['final_adjudicator']:>5} {v['adopted']:>7}")
        lines.append(f"{fam:8} {e['n']:>4} | " + " | ".join(cells))
    c = doc["controls"]
    lines.append(f"\ncontrols: {c['n']}; passed the real run at v1.9.0: {c['passed_the_run_at_v1.9.0']}")
    for tag in ("v1.9.0", "v1.10"):
        for scope in ("all", "among_passed_at_v1.9.0"):
            lines.append(f"  {tag:7} {scope:24} " + ", ".join(f"{k}={v}" for k, v in c[tag][scope].items() if v))
    lines.append(f"FR (behaviour layers, among the {c['passed_the_run_at_v1.9.0']} controls that passed at v1.9.0): {c['FR']}")
    lines.append(f"branch: {doc['summary']['branch']}")
    lines.append(f"C = {doc['summary']['C']} of N = {doc['summary']['N']} stopped before any model at v1.10; C0 = {doc['summary']['C0']} at v1.9.0")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--v190", required=True)
    ap.add_argument("--v110", required=True)
    ap.add_argument("--confirm", required=True)
    ap.add_argument("--manifest", default=str(Path(__file__).resolve().parents[1] / "independent" / "manifest.json"))
    ap.add_argument("--write")
    args = ap.parse_args()
    confirm = load(Path(args.confirm))
    confirmed = {i for i, r in confirm.items() if r.get("outcome") == "confirmed"}
    doc = build(load(Path(args.v190)), load(Path(args.v110)), confirmed, json.loads(Path(args.manifest).read_text(encoding="utf-8")))
    print(text(doc))
    if args.write:
        Path(args.write).write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
