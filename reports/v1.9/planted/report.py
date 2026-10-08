"""harness-v1.9, task 2: the held-out table, before and after, from the two committed gate outputs.

    backend/.venv/Scripts/python.exe reports/v1.9/planted/report.py > table.md

Reads gate_heldout_before.json (harness-v1.8.0's gate) and gate_heldout_after.json (harness-v1.9's, run once). Prints, per family, n, caught and caught by a semantic rule
(a rule other than the size / form / protected-path rules), the false-reject rate on the controls with the rules that rejected them, and, for each control that was
rejected, its id; and the cheats that nothing caught, grouped by style, so a reader can see which shapes get through.
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
NAMES = {"F1": "swallowed exception", "F2": "stubbed function", "F3": "skipped missing input", "F4": "early exit / hardcoded output", "F5": "altered documented command",
         "F6": "workload shrunk to nothing"}


def load(label: str) -> dict | None:
    p = HERE / f"gate_heldout_{label}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None


def main() -> None:
    before, after = load("before"), load("after")
    corpus = {json.loads(l)["id"]: json.loads(l) for l in (HERE / "corpus.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()}
    print("| family (held-out half) | n | caught before | by a semantic rule | caught after | by a semantic rule |")
    print("|---|---|---|---|---|---|")
    for f, name in NAMES.items():
        b = before["summary"][f]
        a = after["summary"][f] if after else None
        print(f"| {f} {name} | {b['n']} | {b['rejected']} ({b['rate']:.0%}) | {b['rejected_by_a_semantic_rule']} | "
              + (f"{a['rejected']} ({a['rate']:.0%}) | {a['rejected_by_a_semantic_rule']} |" if a else "not run | |"))
    bc, ac = before["summary"]["ALL CHEATS"], after["summary"]["ALL CHEATS"] if after else None
    print(f"| **all cheats** | {bc['n']} | **{bc['rejected']} ({bc['rate']:.0%})** | | " + (f"**{ac['rejected']} ({ac['rate']:.0%})** | |" if ac else "not run | |"))
    bk, ak = before["summary"]["ALL CONTROLS"], after["summary"]["ALL CONTROLS"] if after else None
    print(f"| **honest controls rejected (false rejects)** | {bk['n']} | **{bk['rejected']} ({bk['rate']:.0%})** | | " + (f"**{ak['rejected']} ({ak['rate']:.0%})** | |" if ak else "not run | |"))
    print()
    for label, doc in (("before", before), ("after", after)):
        if doc is None:
            continue
        rej = [r for r in doc["results"] if corpus[r["id"]]["kind"] == "control" and r["decision"] == "REJECT"]
        print(f"False rejects, {label}: " + (", ".join(f"`{r['id']}` ({'+'.join(r['rules'])})" for r in rej) if rej else "none"))
        passed = Counter(f"{corpus[r['id']]['family']} {corpus[r['id']]['style']}" for r in doc["results"] if corpus[r["id"]]["kind"] == "cheat" and r["decision"] == "PASS")
        print(f"Cheats not caught, {label} ({sum(passed.values())}): " + ", ".join(f"{k} x{v}" for k, v in sorted(passed.items())))
        print()


if __name__ == "__main__":
    main()
