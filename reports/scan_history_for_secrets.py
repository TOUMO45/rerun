"""Scan for secret-shaped strings and report where they sit WITHOUT printing them: the commit(s) that hold the blob, the path, the pattern's name and the
first four characters of the match.

    backend/.venv/Scripts/python.exe reports/scan_history_for_secrets.py           # every ref, tag, stash and reflog; exit 1 if anything is found
    backend/.venv/Scripts/python.exe reports/scan_history_for_secrets.py --head    # every commit in HEAD's history (backend/tests/test_no_secrets.py runs this)
    backend/.venv/Scripts/python.exe reports/scan_history_for_secrets.py --tracked # the tracked files as they are in the working tree (catches a record before it is committed)

Written after the two dispatches of the v1.10 seal workflow (2026-10-09): secrets with trailing newlines made the HTTP clients put the header value into their
error text, and that text reached the records the workflow committed to a results branch. Part of the final gate (owner, 2026-10-10)."""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NUL = bytes([0])

# A redaction note left in a record is not a secret: "tvly-[REDACTED: ...]" and "v1.[REDACTED: ...]" do not match (the bracket ends the run).
PATTERNS: dict[str, re.Pattern[bytes]] = {
    "tavily key": re.compile(rb"tvly-[A-Za-z0-9_\-]{20,}"),
    "nebius static key": re.compile(rb"v1\.Cm[A-Za-z0-9_.\-]{40,}"),
    "bearer token": re.compile(rb"Bearer [A-Za-z0-9._\-]{30,}"),
    "nvidia api key": re.compile(rb"nvapi-[A-Za-z0-9_\-]{20,}"),
    "hugging face token": re.compile(rb"hf_[A-Za-z0-9]{30,}"),
    "github token": re.compile(rb"(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}"),
    "aws access key": re.compile(rb"AKIA[A-Z0-9]{16}"),
    "openai-style key": re.compile(rb"sk-[A-Za-z0-9]{32,}"),
    "private key block": re.compile(rb"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "assignment of a long literal to a secret-named variable": re.compile(
        rb"(?i)\b(?:api[_-]?key|secret[_-]?key|access[_-]?token|auth[_-]?token|password)\b\s*[=:]\s*['\"][A-Za-z0-9_\-./+]{24,}['\"]"),
}
# A match that says it is not a secret is skipped: the harness's tests use placeholder keys such as a 29-character "sk-f...fake..." literal in
# backend/tests/test_model_client.py. A real key is random and does not contain these words.
PLACEHOLDER = re.compile(rb"(?i)fake|dummy|example|placeholder|redacted|not-a-real|xxxxxxxx")


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, check=True).stdout.decode("utf-8", "replace")


def scan_text(data: bytes) -> list[tuple[str, str]]:
    """(pattern name, first four characters) of each pattern's first secret-shaped match in one file's bytes; a placeholder is skipped, a binary file is not read."""
    found: list[tuple[str, str]] = []
    if NUL in data[:8000]:
        return found
    for name, pattern in PATTERNS.items():
        for m in pattern.finditer(data):
            if PLACEHOLDER.search(m.group(0)):
                continue
            found.append((name, m.group(0)[:4].decode("utf-8", "replace")))
            break
    return found


def scan_tracked() -> list[tuple[str, str, str]]:
    """(path, pattern name, first four characters) over the tracked files as they are in the working tree."""
    found: list[tuple[str, str, str]] = []
    for rel in git("ls-files", "-z").split("\x00"):
        path = ROOT / rel
        if rel and path.is_file():
            found += [(rel, name, prefix) for name, prefix in scan_text(path.read_bytes())]
    return found


def reachable_blobs(head_only: bool) -> dict[str, set[str]]:
    """blob sha -> the paths it was seen at."""
    args = ["rev-list", "--objects", "HEAD"] if head_only else ["rev-list", "--objects", "--all", "--reflog"]
    seen: dict[str, set[str]] = {}
    for line in git(*args).splitlines():
        parts = line.split(" ", 1)
        if len(parts) == 2 and parts[1]:
            seen.setdefault(parts[0], set()).add(parts[1])
    proc = subprocess.run(["git", "cat-file", "--batch-check=%(objectname) %(objecttype)"], cwd=ROOT, input="\n".join(seen).encode(), capture_output=True, check=True)
    kinds = dict(line.split()[:2] for line in proc.stdout.decode().splitlines() if line.strip())
    return {sha: paths for sha, paths in seen.items() if kinds.get(sha) == "blob"}


def scan_history(head_only: bool) -> list[tuple[str, str, str, str]]:
    """(blob sha, a path it was seen at, pattern name, first four characters)."""
    blobs = reachable_blobs(head_only)
    proc = subprocess.Popen(["git", "cat-file", "--batch"], cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    assert proc.stdin and proc.stdout
    findings: list[tuple[str, str, str, str]] = []
    for sha, paths in blobs.items():
        proc.stdin.write((sha + "\n").encode())
        proc.stdin.flush()
        header = proc.stdout.readline().decode().split()
        if len(header) != 3:
            continue
        data = proc.stdout.read(int(header[2]))
        proc.stdout.read(1)  # the newline after the object
        findings += [(sha, sorted(paths)[0], name, prefix) for name, prefix in scan_text(data)]
    proc.stdin.close()
    proc.wait()
    return findings


def commits_holding(sha: str, head_only: bool) -> list[str]:
    return git("log", "--format=%h", f"--find-object={sha}", *(["HEAD"] if head_only else ["--all", "--reflog"])).split()[:4]


def main() -> int:
    ap = argparse.ArgumentParser()
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--head", action="store_true", help="every commit in HEAD's history")
    mode.add_argument("--tracked", action="store_true", help="the tracked files in the working tree")
    args = ap.parse_args()
    if args.tracked:
        found = scan_tracked()
        print(f"{len(found)} secret-shaped string(s) in the tracked files" + (" (path | pattern | first four characters):" if found else ""))
        for rel, name, prefix in found:
            print(f"  {rel} | {name} | {prefix}")
        return 1 if found else 0
    findings = scan_history(args.head)
    scope = "every commit in HEAD's history" if args.head else "every ref, tag, stash and reflog"
    if not findings:
        print(f"no secret-shaped string in {scope}")
        return 0
    print(f"{len(findings)} secret-shaped string(s) in {scope} (commit(s) that hold the blob | blob | path | pattern | first four characters):")
    for sha, path, name, prefix in findings:
        print(f"  {','.join(commits_holding(sha, args.head)) or '?'} | {sha[:7]} | {path} | {name} | {prefix}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
