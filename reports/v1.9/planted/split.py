"""harness-v1.9, task 2: the seeded split of corpus.jsonl into a dev half (for developing harness-v1.9, task 3) and a held-out half (measured: before the
fixes, and once after them). Stratified by (base, family/control kind) so both halves see every repository and every family.

    backend/.venv/Scripts/python.exe reports/v1.9/planted/split.py [--write]

Within each stratum (sorted), ids are sorted and shuffled with one random.Random(SEED); the first half (rounded up on alternate strata, so the totals stay
balanced) goes to dev, the rest to held-out.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
from pathlib import Path

HERE = Path(__file__).resolve().parent
SEED = 20261008


def split(rows: list[dict]) -> dict:
    strata: dict[tuple[str, str], list[str]] = {}
    for r in rows:
        strata.setdefault((r["base"], r["family"]), []).append(r["id"])
    rng = random.Random(SEED)
    dev, held, up = [], [], True
    for key in sorted(strata):
        ids = sorted(strata[key])
        rng.shuffle(ids)
        k = (len(ids) + (1 if up else 0)) // 2
        if len(ids) % 2:
            up = not up
        dev += ids[:k]
        held += ids[k:]
    return {"seed": SEED, "stratified_by": "base x family", "dev": sorted(dev), "heldout": sorted(held)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()
    text = (HERE / "corpus.jsonl").read_text(encoding="utf-8")
    rows = [json.loads(line) for line in text.splitlines() if line.strip()]
    out = split(rows)
    out["corpus_sha256"] = hashlib.sha256(text.encode("utf-8")).hexdigest()
    by = {r["id"]: r for r in rows}
    for half in ("dev", "heldout"):
        fams: dict[str, int] = {}
        for i in out[half]:
            fams[by[i]["family"]] = fams.get(by[i]["family"], 0) + 1
        print(half, len(out[half]), "cheats", sum(by[i]["kind"] == "cheat" for i in out[half]), "controls", sum(by[i]["kind"] == "control" for i in out[half]),
              dict(sorted(fams.items())))
    if args.write:
        (HERE / "split.json").write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
