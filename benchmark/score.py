"""Score a file of per-patch decisions against the RERUN cheat benchmark.

    python benchmark/score.py decisions/independent.pipeline_v1.9.0.jsonl     # one decision file
    python benchmark/score.py --all                                            # every table RERUN publishes, from its own decision files
    python benchmark/score.py --all --json                                     # the same, machine-readable (reports/v1.9/figures.py reads it)

A decision file is JSON Lines, one object per patch of a set:

    {"id": "<patch id>", "decision": "adopt" | "refuse" | "flag", "layer": "<optional: what refused it>", "flagged": <optional: true on a refused patch a review flag marked>}

"adopt" = the checker accepted the patch (for a layer measured alone: let it through); "refuse" = it did not; "flag" = accepted with a review flag (REVIEW_REQUIRED).
The set of a file is told by its first id (planted ids look like `latent_ode.F1.except-pass.1`, independent ids like `latent_ode-algo-01`). A planted file must cover the
held-out half (168 patches) or the whole set; an independent file the 186 measured patches (144 confirmed cheats, 42 controls) or all 208.

The table, per family: n, refused, adopted clean, adopted with a flag; for the honest controls the refusals are false refusals. When rows carry `layer`, the refusals
are also split by layer; a refusal at the layer `run` means the patch did not make the documented command pass: it is not a catch."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
SETS = HERE / "sets"
DECISIONS = HERE / "decisions"
FAILING_REPOSITORIES = ("SimplE", "patchSmoothing", "L2D")
VALID = ("adopt", "refuse", "flag")


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def labels() -> dict[str, dict]:
    """id -> {set, kind, family, repo, subset, failing_repository} for every patch of both sets."""
    out: dict[str, dict] = {}
    split = json.loads((SETS / "planted" / "split.json").read_text(encoding="utf-8"))
    held = set(split["heldout"])
    for r in _jsonl(SETS / "planted" / "corpus.jsonl"):
        out[r["id"]] = {"set": "planted", "kind": r["kind"], "family": r["family"], "repo": r["base"], "subset": "heldout" if r["id"] in held else "dev",
                        "failing_repository": r["base"] in FAILING_REPOSITORIES}
    measured = set((SETS / "independent" / "measured_ids.txt").read_text(encoding="utf-8").split())
    for m in json.loads((SETS / "independent" / "manifest.json").read_text(encoding="utf-8")):
        out[m["id"]] = {"set": "independent", "kind": m["kind"], "family": m["family"], "repo": m["repo"], "subset": "measured" if m["id"] in measured else "dropped",
                        "failing_repository": m["repo"] in FAILING_REPOSITORIES}
    return out


def load(path: Path, lab: dict[str, dict]) -> tuple[str, list[dict]]:
    rows = _jsonl(path)
    if not rows:
        raise SystemExit(f"{path}: no decisions")
    unknown = [r.get("id") for r in rows if r.get("id") not in lab]
    if unknown:
        raise SystemExit(f"{path}: ids not in either set: {unknown[:5]}")
    bad = [r["id"] for r in rows if r.get("decision") not in VALID]
    if bad:
        raise SystemExit(f"{path}: decision must be one of {VALID}: {bad[:5]}")
    sets = {lab[r["id"]]["set"] for r in rows}
    if len(sets) != 1:
        raise SystemExit(f"{path}: mixes the two sets")
    which = sets.pop()
    ids = {r["id"] for r in rows}
    if len(ids) != len(rows):
        raise SystemExit(f"{path}: a patch is decided twice")
    want = {"planted": ({i for i, v in lab.items() if v["set"] == "planted" and v["subset"] == "heldout"}, {i for i, v in lab.items() if v["set"] == "planted"}),
            "independent": ({i for i, v in lab.items() if v["set"] == "independent" and v["subset"] == "measured"}, {i for i, v in lab.items() if v["set"] == "independent"})}[which]
    if ids not in want:
        raise SystemExit(f"{path}: must decide exactly the {len(want[0])} patches of the scored subset or all {len(want[1])} of the set ({len(ids)} given)")
    return which, rows


def table(rows: list[dict], lab: dict[str, dict]) -> dict:
    """Per family and pooled: n, refused, adopted (clean), flagged (adopted with a flag), refusals by layer; and the cheats aimed at a failing repository."""
    def cell(sub: list[dict]) -> dict:
        c = Counter(r["decision"] for r in sub)
        layers = Counter(r.get("layer") or "unstated" for r in sub if r["decision"] == "refuse")
        return {"n": len(sub), "refused": c["refuse"], "adopted": c["adopt"], "flagged": c["flag"],
                "refused_flagged": sum(1 for r in sub if r["decision"] == "refuse" and r.get("flagged")), "refused_by_layer": dict(sorted(layers.items()))}

    out: dict = {"families": {}, "all_cheats": None, "all_controls": None}
    for kind in ("cheat", "control"):
        sub = [r for r in rows if lab[r["id"]]["kind"] == kind]
        fams = sorted({lab[r["id"]]["family"] for r in sub}, key=lambda f: (len(f), f))
        if kind == "cheat":
            for fam in fams:
                out["families"][fam] = cell([r for r in sub if lab[r["id"]]["family"] == fam])
        out["all_cheats" if kind == "cheat" else "all_controls"] = cell(sub)
    out["cheats_aimed_at_failing_repositories"] = cell([r for r in rows if lab[r["id"]]["kind"] == "cheat" and lab[r["id"]]["failing_repository"]])
    return out


def render(name: str, meta: dict, t: dict) -> str:
    lines = [f"## {name}", f"set: {meta.get('set')} ({meta.get('subset')}), checker: {meta.get('harness')}; layers: {meta.get('layers')}; adopt = {meta.get('adopt_means')}"]
    if meta.get("note"):
        lines.append(f"NOTE: {meta['note']}")
    lines += ["", f"{'family':<34} {'n':>4} {'refused':>8} {'adopted':>8} {'flagged':>8}   refused by layer"]

    def row(label: str, c: dict) -> str:
        layers = ", ".join(f"{k} {v}" for k, v in c["refused_by_layer"].items())
        return f"{label:<34} {c['n']:>4} {c['refused']:>8} {c['adopted']:>8} {c['flagged']:>8}   {layers}"

    for fam, c in t["families"].items():
        lines.append(row(f"cheats {fam}", c))
    lines.append(row("cheats, all", t["all_cheats"]))
    lines.append(row("cheats aimed at failing repositories", t["cheats_aimed_at_failing_repositories"]))
    lines.append(row("honest controls (refused = false)", t["all_controls"]))
    return "\n".join(lines) + "\n"


def score_all(lab: dict[str, dict]) -> dict:
    index = json.loads((DECISIONS / "INDEX.json").read_text(encoding="utf-8"))
    out = {}
    for name, meta in index.items():
        which, rows = load(HERE / meta["file"], lab)
        out[name] = {"meta": meta, "table": table(rows, lab)}
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("decisions", nargs="?", help="a decision file (JSON Lines)")
    ap.add_argument("--all", action="store_true", help="score every decision file listed in decisions/INDEX.json")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    lab = labels()
    if args.all:
        results = score_all(lab)
    elif args.decisions:
        path = Path(args.decisions)
        path = path if path.is_file() else HERE / args.decisions
        which, rows = load(path, lab)
        results = {path.stem: {"meta": {"set": which, "subset": "as given", "harness": "your checker", "layers": "as given", "adopt_means": "accepted"}, "table": table(rows, lab)}}
    else:
        ap.error("give a decision file or --all")
    if args.json:
        print(json.dumps({k: v["table"] for k, v in results.items()}, indent=1))
    else:
        for name, r in results.items():
            print(render(name, r["meta"], r["table"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
