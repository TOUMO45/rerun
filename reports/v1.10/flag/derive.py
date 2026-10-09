"""harness-v1.10 flag mode (owner, 2026-10-09): the flag-mode table, DERIVED FROM COMMITTED RECORDS, never measured by a run of the flag mode.

The flag mode keeps every harness-v1.9.0 decision and marks an adopted patch the v1.10 checks would have refused. So, per patch of the independent set's measured
186 (144 confirmed cheats, 42 honest controls):

  * the decision is the patch's outcome in the harness-v1.9.0 measurement (`reports/v1.10/independent/measure_v190/results.jsonl`): adopted, or not adopted at a layer
    (gate, exit-zero audit, did not pass the run, adjudicator);
  * the flag is what the release candidate that was measured (`harness-v1.10.0-rc4`, `reports/v1.10/independent/measure_v110/results.jsonl`) found: a static finding
    (`behaviour.static`) or a trace finding (`behaviour.trace.findings`). A patch the gate refused at rc4 was never judged by the checks: it carries no flag.

What the derivation cannot see, stated beside every number it gives: the tracer ran at rc4 only for patches the static half let through, so **no cheat was ever traced**
(every confirmed cheat was refused statically or by the gate), and a patch that the static half flagged was not traced either; and cheats written to fit the allow-list
are **unmeasured**. The flag-mode use was chosen after these results were seen (METHODOLOGY.md, flag-mode decisions).

Writes `flag_table.json` (the counts and the per-patch decisions it reads them from) and `FLAG_TABLE.md`. Run: python reports/v1.10/flag/derive.py [--check]"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
V190 = "reports/v1.10/independent/measure_v190/results.jsonl"
V110 = "reports/v1.10/independent/measure_v110/results.jsonl"
OUT_JSON = Path(__file__).with_name("flag_table.json")
OUT_MD = Path(__file__).with_name("FLAG_TABLE.md")
LABEL = "derived from committed records"
LAYERS = ("gate", "audit", "run", "adjudicator")


def _rows(rel: str) -> dict[str, dict]:
    return {r["id"]: r for r in (json.loads(x) for x in (ROOT / rel).read_text(encoding="utf-8").splitlines() if x.strip())}


def per_patch() -> list[dict]:
    v190, v110 = _rows(V190), _rows(V110)
    if set(v190) != set(v110):
        raise SystemExit("the two measurements do not cover the same patches")
    out = []
    for pid in sorted(v190):
        a, b = v190[pid], v110[pid]
        beh = b.get("behaviour") or {}
        static = [f["reason"] for f in beh.get("static") or ()]
        trace_rec = beh.get("trace") or {}
        trace = [f["reason"] for f in trace_rec.get("findings") or ()]
        flagged = bool(static or trace)
        adopted = a["outcome"] == "adopted"
        out.append({"id": pid, "kind": a["kind"], "family": a["family"], "population": a["population"],
                    "v190_outcome": a["outcome"], "rc4_outcome": b["outcome"],
                    "flag": {"flagged": flagged, "static": sorted(set(static)), "trace": sorted(set(trace)),
                             "traced_at_rc4": bool(trace_rec), "judged_by_the_checks": b["outcome"] != "gate"},
                    # the benchmark's decision vocabulary: adopt (adopted, no flag), flag (adopted with REVIEW_REQUIRED), refuse (not adopted)
                    "decision": ("flag" if flagged else "adopt") if adopted else "refuse",
                    "layer": None if adopted else a["outcome"]})
    return out


def _cell(rows: list[dict]) -> dict:
    layers = Counter(r["layer"] for r in rows if r["layer"])
    return {"n": len(rows), "adopted": sum(1 for r in rows if r["layer"] is None),
            "not_adopted": sum(layers.values()), "not_adopted_by_layer": {k: layers.get(k, 0) for k in LAYERS}}


def table(rows: list[dict]) -> dict:
    out: dict = {"label": LABEL, "groups": {}}
    for kind, name in (("cheat", "cheats"), ("control", "honest controls")):
        sub = [r for r in rows if r["kind"] == kind]
        out["groups"][name] = {
            "all": _cell(sub),
            "flagged": _cell([r for r in sub if r["flag"]["flagged"]]),
            "clean (judged, no finding)": _cell([r for r in sub if not r["flag"]["flagged"] and r["flag"]["judged_by_the_checks"]]),
            "never judged (refused by the gate)": _cell([r for r in sub if not r["flag"]["judged_by_the_checks"]]),
        }
    cheats = [r for r in rows if r["kind"] == "cheat"]
    out["cheats_by_family"] = {fam: {"n": len(s), "adopted_flagged": sum(1 for r in s if r["decision"] == "flag"),
                                     "adopted_clean": sum(1 for r in s if r["decision"] == "adopt"), "not_adopted": sum(1 for r in s if r["decision"] == "refuse")}
                               for fam in sorted({r["family"] for r in cheats}) for s in [[r for r in cheats if r["family"] == fam]]}
    pop_a = [r for r in cheats if r["population"] == "A"]
    out["cheats_aimed_at_failing_repositories"] = {"n": len(pop_a), "adopted_flagged": sum(1 for r in pop_a if r["decision"] == "flag"),
                                                    "adopted_clean": sum(1 for r in pop_a if r["decision"] == "adopt")}
    controls = [r for r in rows if r["kind"] == "control"]
    passed = [r for r in controls if r["v190_outcome"] in ("adopted", "adjudicator")]
    out["controls_that_passed_the_run_at_v190"] = {"n": len(passed), "flagged": sum(1 for r in passed if r["flag"]["flagged"]),
                                                   "adopted_flagged": sum(1 for r in passed if r["decision"] == "flag"),
                                                   "adopted_clean": sum(1 for r in passed if r["decision"] == "adopt")}
    out["tracer"] = {"cheats_traced_at_rc4": sum(1 for r in cheats if r["flag"]["traced_at_rc4"]),
                     "controls_traced_at_rc4": sum(1 for r in controls if r["flag"]["traced_at_rc4"]),
                     "trace_findings_on_controls": sum(1 for r in controls if r["flag"]["trace"])}
    out["reasons_on_adopted_flagged"] = dict(Counter(reason for r in rows if r["decision"] == "flag" for reason in r["flag"]["static"] + r["flag"]["trace"]))
    out["limits"] = ["The behavioural tracer was exercised by no cheat: every confirmed cheat was refused statically or by the gate at rc4, so none was run with the tracer.",
                     "A patch the static half flagged at rc4 was not run at rc4, so its trace is unknown (in flag mode it would run, traced).",
                     "Cheats written to fit the allow-list are unmeasured (the independent author never saw it).",
                     "The flag-mode use of the checks was chosen after these results were seen; nothing here was measured by a run of the flag mode."]
    out["sources"] = [V190, V110]
    return out


def render_md(t: dict) -> str:
    g = t["groups"]
    lines = ["# The flag mode on the independent set — " + LABEL, "",
             "Generated by `reports/v1.10/flag/derive.py` from the committed harness-v1.9.0 and harness-v1.10.0-rc4 measurements of the independent set (144 confirmed cheats, "
             "42 honest controls). **Derived from committed records, not measured by a run of the flag mode; the flag-mode use was chosen after these results were seen.** "
             "The decision is harness-v1.9.0's; the flag is what rc4's checks found.", "",
             "| | n | adopted | not adopted: gate / audit / did not pass the run / adjudicator |", "|---|---|---|---|"]
    for name, cells in g.items():
        for sub, c in cells.items():
            by = c["not_adopted_by_layer"]
            lines.append(f"| {name}, {sub} | {c['n']} | {c['adopted']} | {by['gate']} / {by['audit']} / {by['run']} / {by['adjudicator']} |")
    a = t["cheats_aimed_at_failing_repositories"]
    p = t["controls_that_passed_the_run_at_v190"]
    lines += ["", f"Cheats aimed at the repositories whose run really fails: {a['n']}; adopted with REVIEW_REQUIRED {a['adopted_flagged']}, adopted clean {a['adopted_clean']}.",
              f"Honest controls that passed the run at harness-v1.9.0: {p['n']}; flagged {p['flagged']} (adopted with the flag {p['adopted_flagged']}, adopted clean {p['adopted_clean']}).",
              "", "| cheat family | n | adopted with REVIEW_REQUIRED | adopted clean | not adopted |", "|---|---|---|---|---|"]
    for fam, c in t["cheats_by_family"].items():
        lines.append(f"| {fam} | {c['n']} | {c['adopted_flagged']} | {c['adopted_clean']} | {c['not_adopted']} |")
    tr = t["tracer"]
    lines += ["", f"Tracer: cheats traced at rc4 {tr['cheats_traced_at_rc4']}; honest controls traced {tr['controls_traced_at_rc4']}, with a trace finding {tr['trace_findings_on_controls']}.",
              "", "**Limits.**", *[f"* {x}" for x in t["limits"]], ""]
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="fail if the committed files are not what the records give")
    args = ap.parse_args(argv)
    rows = per_patch()
    doc = {**table(rows), "patches": rows}
    text = json.dumps(doc, indent=1, ensure_ascii=False) + "\n"
    md = render_md(doc)
    if args.check:
        ok = OUT_JSON.is_file() and OUT_JSON.read_text(encoding="utf-8").replace("\r\n", "\n") == text and OUT_MD.is_file() and OUT_MD.read_text(encoding="utf-8").replace("\r\n", "\n") == md
        print("flag table matches the records" if ok else "flag table is not what the records give: rebuild it", file=sys.stdout if ok else sys.stderr)
        return 0 if ok else 1
    OUT_JSON.write_text(text, encoding="utf-8", newline="\n")
    OUT_MD.write_text(md, encoding="utf-8", newline="\n")
    print(f"wrote {OUT_JSON.relative_to(ROOT)} and {OUT_MD.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
