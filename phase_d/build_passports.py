"""Write the 61 passports and the record index from committed blobs.

    python -m phase_d.build_passports

Output: reports/phase-d/passports/<harness_tag>/<set>/<record file>, reports/phase-d/record_index.md.
Files are written with LF; a stale passport file (no matching record) is removed.
"""

from __future__ import annotations

import sys
from pathlib import Path

from .check_tags import violations
from .passports import PASSPORT_DIR, build_all, passport_path, record_index, serialize
from .records import ROOT

INDEX = "reports/phase-d/record_index.md"


def expected_files(source=None) -> dict[str, bytes]:
    built = build_all(source)
    files = {passport_path(record): serialize(passport) for record, passport in built}
    for (record, passport) in built:
        found = violations(passport)
        if found:
            raise SystemExit(f"{record.path}: untagged numbers in the passport: {found[:5]}")
    files[INDEX] = record_index(built).encode("utf-8")
    return files


def main(root: Path = ROOT) -> int:
    files = expected_files()
    for stale in (root / PASSPORT_DIR).rglob("*.json") if (root / PASSPORT_DIR).is_dir() else []:
        if stale.relative_to(root).as_posix() not in files:
            stale.unlink()
    for rel, content in files.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    print(f"wrote {len(files) - 1} passports and {INDEX}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
