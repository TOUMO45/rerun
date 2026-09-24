"""Clone integrity gate: the bytes RERUN uploads to the sandbox must be the
bytes the repository actually committed.

Found live (TTPT, 2026-09-24): this Windows host has global
`core.autocrlf=true`, so `git clone` rewrote every text file to CRLF.
RERUN uploaded those files to a Linux sandbox, `run_ttpt.sh` died with
`invalid option name` (`set -o pipefail\\r`), and the failure was blamed on
the repository. Two fixes:

1. `intake` clones with `-c core.autocrlf=false -c core.eol=lf` (and
   `GIT_LFS_SKIP_SMUDGE=1`, so LFS pointer files stay what was committed).
2. This gate, before every upload: compute the git blob SHA-1 of every file
   about to be uploaded and compare it with `git ls-tree -r <commit>`. Any
   mismatch — changed bytes, or a file the commit doesn't contain — means
   the harness would test something other than the repository, so the run
   ends INVALID_HARNESS (RERUN's fault, never a verdict on the repo), naming
   the files. Files changed by gate-approved repair patches are expected to
   differ; they are excluded by path and listed.
"""

from __future__ import annotations

import hashlib
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

INVALID_HARNESS = "INVALID_HARNESS"


class HarnessIntegrityError(RuntimeError):
    """The working tree about to be uploaded is not the committed tree."""

    def __init__(self, message: str, record: dict):
        super().__init__(message)
        self.record = record


def git_blob_sha1(content: bytes) -> str:
    """Exactly git's object id for a blob: sha1(b"blob <len>\\0" + content)."""
    return hashlib.sha1(b"blob %d\0" % len(content) + content).hexdigest()


def committed_blobs(workdir: Path, commit: str) -> dict[str, str]:
    """{repo-relative posix path: blob sha} for every regular/executable file
    in the commit (symlinks and submodules are not uploaded, so skipped)."""
    out = subprocess.run(
        ["git", "-C", str(workdir), "ls-tree", "-r", "-z", commit],
        capture_output=True,
        timeout=60,
    )
    if out.returncode != 0:
        raise HarnessIntegrityError(
            f"cannot list the committed tree: {out.stderr.decode('utf-8', 'replace').strip()}",
            {"status": "failed", "reason": "git ls-tree failed"},
        )
    blobs: dict[str, str] = {}
    for entry in out.stdout.split(b"\0"):
        if not entry:
            continue
        meta, _, path = entry.partition(b"\t")
        mode, obj_type, sha = meta.decode().split(" ")
        if obj_type == "blob" and mode in ("100644", "100755"):
            blobs[path.decode("utf-8", "surrogateescape")] = sha
    return blobs


def tree_sha(workdir: Path, commit: str) -> str:
    out = subprocess.run(
        ["git", "-C", str(workdir), "rev-parse", f"{commit}^{{tree}}"], capture_output=True, text=True, timeout=30
    )
    return out.stdout.strip() if out.returncode == 0 else ""


@dataclass
class IntegrityRecord:
    status: str  # "verified"
    tree_sha: str
    files_checked: int
    excluded_patched: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "status": self.status,
            "tree_sha": self.tree_sha,
            "files_checked": self.files_checked,
            "excluded_patched": sorted(self.excluded_patched),
        }


def verify_upload(
    workdir: Path,
    commit: str,
    upload_files: dict[str, Path],
    patched_paths: frozenset[str] = frozenset(),
) -> IntegrityRecord:
    """Raise HarnessIntegrityError on any mismatch; else return the record."""
    if not (workdir / ".git").exists():
        raise HarnessIntegrityError(
            f"'{workdir}' is not a git checkout — cannot prove the upload matches the commit",
            {"status": "failed", "reason": "not a git checkout"},
        )
    expected = committed_blobs(workdir, commit)
    mismatched, untracked = [], []
    checked = 0
    for rel, path in sorted(upload_files.items()):
        if rel in patched_paths:
            continue
        sha = expected.get(rel)
        if sha is None:
            untracked.append(rel)
            continue
        checked += 1
        if git_blob_sha1(Path(path).read_bytes()) != sha:
            mismatched.append(rel)
    if mismatched or untracked:
        parts = []
        if mismatched:
            parts.append(f"{len(mismatched)} file(s) differ from the committed blob: {', '.join(mismatched[:10])}")
        if untracked:
            parts.append(f"{len(untracked)} file(s) not in the commit: {', '.join(untracked[:10])}")
        record = {
            "status": "failed",
            "tree_sha": tree_sha(workdir, commit),
            "mismatched": mismatched,
            "not_in_commit": untracked,
        }
        raise HarnessIntegrityError("; ".join(parts), record)
    return IntegrityRecord("verified", tree_sha(workdir, commit), checked, list(patched_paths))
