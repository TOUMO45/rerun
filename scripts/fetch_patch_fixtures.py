"""Fetch the originals of the v1.3.3 patch fixtures that are not committed (licence), verify each against the recorded git blob SHA-1.

    python scripts/fetch_patch_fixtures.py            # fetch what is missing into backend/tests/fixtures/v133/_fetched/ (gitignored)
    python scripts/fetch_patch_fixtures.py --check    # verify only, no network: exits 1 if something is missing or does not match

The tests that need these files are marked `requires_network` and are skipped when they cannot be fetched.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend" / "tests"))

import fixture_fetch as ff  # noqa: E402


def main() -> int:
    check_only = "--check" in sys.argv
    bad = 0
    for case, entry in sorted(ff.sources().items()):
        if entry["original_committed"]:
            print(f"{case}: committed ({entry['license_status']})")
            continue
        try:
            if check_only:
                for rel, want in entry["files"].items():
                    path = ff.cache_path(entry["repo"], entry["commit"], rel)
                    assert path.is_file() and ff.blob_sha1(path.read_bytes()) == want["git_blob_sha1"], f"{rel} missing or different"
            else:
                ff.ensure_original(case)
            print(f"{case}: ok ({entry['repo']}@{entry['commit'][:10]}, {entry['license_status']})")
        except (OSError, ValueError, AssertionError) as exc:
            bad += 1
            print(f"{case}: FAILED: {exc}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
