"""Originals of the v1.3.3 patch fixtures whose repository licence does not allow committing them here.

`fixtures/v133/patches/SOURCES.json` lists, per stored v1.3.2 patch, the repository, the pinned commit, each file's git blob SHA-1 / SHA-256 and
the licence status. Only permissive repositories (MIT/BSD/Apache) keep their original file in git (with `fixtures/v133/NOTICE.md`); for every other one
the file is fetched from GitHub at the pinned commit into a gitignored cache and checked against the recorded blob SHA-1 before any test uses it.
Offline, those tests are skipped (marker `requires_network`); they run in CI and live.
"""

from __future__ import annotations

import hashlib
import json
import urllib.request
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures" / "v133"
PATCHES = FIXTURES / "patches"
CACHE = FIXTURES / "_fetched"


def sources() -> dict:
    return json.loads((PATCHES / "SOURCES.json").read_text(encoding="utf-8"))


def blob_sha1(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def cache_path(repo: str, commit: str, rel: str, cache: Path = CACHE) -> Path:
    return cache / f"{repo.rsplit('github.com/', 1)[-1].replace('/', '__')}@{commit}" / rel


def _raw_url(repo: str, commit: str, rel: str) -> str:
    return f"https://raw.githubusercontent.com/{repo.rsplit('github.com/', 1)[-1]}/{commit}/{rel}"


def ensure_original(case: str, cache: Path = CACHE, timeout: float = 30.0) -> Path:
    """A directory holding the case's original file(s) with the repository's own layout, verified against SOURCES.json.
    Raises OSError if a file cannot be fetched (no network), ValueError if its bytes differ from the recorded blob."""
    entry = sources()[case]
    committed = PATCHES / case / "original"
    if entry["original_committed"]:
        return committed
    target = cache / f"{case}"
    for rel, want in entry["files"].items():
        src = cache_path(entry["repo"], entry["commit"], rel, cache)
        if not src.is_file():
            with urllib.request.urlopen(urllib.request.Request(_raw_url(entry["repo"], entry["commit"], rel), headers={"User-Agent": "rerun-fixtures"}),
                                        timeout=timeout) as response:
                data = response.read()
            src.parent.mkdir(parents=True, exist_ok=True)
            src.write_bytes(data)
        data = src.read_bytes()
        if blob_sha1(data) != want["git_blob_sha1"]:
            raise ValueError(f"{case}: {rel} at {entry['commit'][:10]} does not match the recorded git blob {want['git_blob_sha1'][:10]}")
        dest = target / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
    return target
