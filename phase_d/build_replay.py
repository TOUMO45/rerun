"""Write (or check) the REPLAY output from committed record blobs and the stored passports.

    python -m phase_d.build_replay           # write reports/phase-d/replay/<version>.json, <version>.md, index.md
    python -m phase_d.build_replay --check   # rebuild and diff against the stored files; exit 1 on any difference

The passports are verified against a rebuild from the record blobs first; REPLAY is not built on unverified passports.
"""

from __future__ import annotations

import sys
from pathlib import Path

from . import verify_passports
from .records import ROOT
from .replay import REPLAY_DIR, expected_files


def _lf(data: bytes) -> bytes:
    return data.replace(b"\r\n", b"\n")


def check(root: Path = ROOT, source=None) -> list[str]:
    """Every difference between the stored REPLAY files and a rebuild; empty means identical."""
    problems = [f"passports: {p}" for p in verify_passports.verify(root, source)]
    if problems:
        return problems
    expected = expected_files(source, root=root)
    for rel, content in expected.items():
        file = root / rel
        if not file.is_file():
            problems.append(f"missing: {rel}")
        elif _lf(file.read_bytes()) != content:
            problems.append(f"differs from the rebuild: {rel}")
    on_disk = {p.relative_to(root).as_posix() for p in (root / REPLAY_DIR).glob("*")} if (root / REPLAY_DIR).is_dir() else set()
    problems += [f"file without a source: {rel}" for rel in sorted(on_disk - set(expected))]
    return problems


def main(argv: list[str] | None = None, root: Path = ROOT) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if "--check" in argv:
        problems = check(root)
        for p in problems:
            print(f"FAIL {p}")
        print(f"replay check FAILED: {len(problems)} problem(s)" if problems else "replay verified: the stored files are identical to a rebuild")
        return 1 if problems else 0
    stale = verify_passports.verify(root)
    if stale:
        for p in stale:
            print(f"FAIL passports: {p}")
        print("replay not built: the passports do not verify (run python -m phase_d.build_passports)")
        return 1
    files = expected_files(root=root)
    (root / REPLAY_DIR).mkdir(parents=True, exist_ok=True)
    for old in (root / REPLAY_DIR).glob("*"):
        if old.relative_to(root).as_posix() not in files:
            old.unlink()
    for rel, content in files.items():
        (root / rel).write_bytes(content)
    print(f"wrote {len(files)} replay files under {REPLAY_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
