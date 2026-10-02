"""DEV / TEST split of the corpus-v2 entries for the v1.5 dev/test protocol (pre-registered in METHODOLOGY.md, "harness-v1.5 dev/test protocol").

The rule, fixed BEFORE it was run (it is the whole of the choice; no alternative was tried):
  1. the pool is the corpus-v2 entry ids 1..20 except the four gate entries {3, 7, 8, 11} (tuned on for four versions): 16 ids;
  2. the pool is sorted ascending by the SHA-256 hex digest of the id written in decimal ASCII without padding (e.g. sha256(b"5"));
  3. positions 0, 2, 4, ... (counting from 0) are DEV, positions 1, 3, 5, ... are TEST: 8 and 8.

Nothing here reads the corpus, a record or a report: it is arithmetic on the ids. `python split.py` prints the DEV list only; the TEST list is written into METHODOLOGY.md
by the amendment script and is not printed by this module's command line.
"""
from __future__ import annotations

import hashlib

GATE_ENTRIES = (3, 7, 8, 11)
ALL_ENTRIES = tuple(range(1, 21))
RULE = ("sort the 16 entry ids that are not gate entries {3, 7, 8, 11} ascending by the SHA-256 hex digest of the id in decimal ASCII without padding; "
        "positions 0, 2, 4, ... (from 0) are DEV, positions 1, 3, 5, ... are TEST")


def entry_key(entry_id: int) -> str:
    return hashlib.sha256(str(entry_id).encode("ascii")).hexdigest()


def pool() -> list[int]:
    return sorted((i for i in ALL_ENTRIES if i not in GATE_ENTRIES), key=entry_key)


def split() -> dict[str, list[int]]:
    ordered = pool()
    return {"dev": sorted(ordered[0::2]), "test": sorted(ordered[1::2])}


DEV_ENTRIES: tuple[int, ...] = tuple(split()["dev"])


def main() -> int:
    parts = split()
    assert len(parts["dev"]) == 8 and len(parts["test"]) == 8
    assert not set(parts["dev"]) & set(parts["test"]) and not set(parts["dev"] + parts["test"]) & set(GATE_ENTRIES)
    print("DEV:", ", ".join(str(i) for i in parts["dev"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
