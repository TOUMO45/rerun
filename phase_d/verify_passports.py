"""Verifier: rebuild every passport from the committed record blobs and diff against the stored files.

    python -m phase_d.verify_passports

Passes only if: all 61 passports and the record index are byte-identical to a fresh rebuild (line endings
normalised, because a checkout may rewrite LF to CRLF), there is no extra passport file, every stored
`passport_hash` recomputes, every number is tagged, and every annotation's quoted source exists in the file it names.
A record changed by one byte gets a different record id, so its stored passport no longer matches.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from .build_passports import expected_files
from .check_tags import violations
from .passports import PASSPORT_DIR, passport_hash
from .records import ROOT, BlobSource


def _lf(data: bytes) -> bytes:
    return data.replace(b"\r\n", b"\n")


def _quote_problems(passport: dict, root: Path) -> list[str]:
    problems = []
    sources = [s for note in passport.get("annotations", []) for s in note.get("sources", [])]
    cost_line = (passport.get("badge") or {}).get("links", {}).get("cost_line")
    for src in sources + ([cost_line] if cost_line else []):
        file = root / src["path"]
        if not file.is_file() or src["quote"] not in _lf(file.read_bytes()).decode("utf-8"):
            problems.append(f"quoted source not found in {src['path']}: {src['quote']!r}")
    return problems


def verify(root: Path = ROOT, source: BlobSource | None = None) -> list[str]:
    """Every difference between the stored passports and a rebuild from blobs; empty means verified."""
    problems: list[str] = []
    expected = expected_files(source)
    for rel, content in expected.items():
        file = root / rel
        if not file.is_file():
            problems.append(f"missing: {rel}")
            continue
        stored = _lf(file.read_bytes())
        if stored != content:
            problems.append(f"differs from the rebuild: {rel}")
        if rel.endswith(".json"):
            try:
                passport = json.loads(stored.decode("utf-8"))
            except ValueError:
                problems.append(f"not valid JSON: {rel}")
                continue
            if passport.get("passport_hash") != passport_hash(passport):
                problems.append(f"passport_hash does not recompute: {rel}")
            problems += [f"{rel}: {v}" for v in violations(passport)]
            problems += [f"{rel}: {q}" for q in _quote_problems(passport, root)]
    on_disk = {p.relative_to(root).as_posix() for p in (root / PASSPORT_DIR).rglob("*.json")} if (root / PASSPORT_DIR).is_dir() else set()
    problems += [f"passport without a record: {rel}" for rel in sorted(on_disk - set(expected))]
    return problems


def main() -> int:
    problems = verify()
    for p in problems:
        print(f"FAIL {p}")
    if problems:
        print(f"verification FAILED: {len(problems)} problem(s)")
        return 1
    print("verified: every passport rebuilds from the committed record blobs with zero diff")
    return 0


if __name__ == "__main__":
    sys.exit(main())
