"""harness-v1.9, task 2: check out every base repository of bases.json at its pinned commit into .cache/planted_repos (not committed: third-party code; each
patch stores the sha256 of the original it was written against, and run_gate.py refuses a checkout that differs).

    backend/.venv/Scripts/python.exe reports/v1.9/planted/fetch.py
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
REPOS = ROOT / ".cache" / "planted_repos"


def main() -> int:
    REPOS.mkdir(parents=True, exist_ok=True)
    for b in json.loads((HERE / "bases.json").read_text(encoding="utf-8"))["bases"]:
        d = REPOS / b["repo"].replace("/", "_")
        if not d.is_dir():
            subprocess.run(["git", "clone", "-q", "--", f"https://github.com/{b['repo']}", str(d)], check=True)
        subprocess.run(["git", "-C", str(d), "-c", "advice.detachedHead=false", "checkout", "-q", b["commit"]], check=True)
        head = subprocess.run(["git", "-C", str(d), "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
        print(b["name"], head, "ok" if head == b["commit"] else "MISMATCH")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
