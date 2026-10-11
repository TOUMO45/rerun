"""The one live run of PLAN.md (owner, 2026-10-11/12, the Tavily gap only): minmaxot at harness-v1.10.0, flag mode, Tavily on, cap $10.00. Refuses before any spend
unless every precondition holds; after the run, withholds any output file that contains a key's value. Started by launch.cmd through Task Scheduler (D-43).
The preconditions and the withholding are those of reports/v1.10/review_live/launch.py (the M-FAC run).

    backend/.venv/Scripts/python.exe reports/v1.10/tavily_live/launch.py --check   # the preconditions only (two free authenticated requests)
    backend/.venv/Scripts/python.exe reports/v1.10/tavily_live/launch.py --go      # the run
"""
from __future__ import annotations

import argparse
import datetime
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
# keys() and authenticates(): the same checks as the M-FAC run, loaded by path (this file has the same name)
_spec = importlib.util.spec_from_file_location("review_launch", ROOT / "reports" / "v1.10" / "review_live" / "launch.py")
review_launch = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(review_launch)

OUT = ROOT / "runs" / "v1.10" / "tavily_live"
RECORD = OUT / "02_stephaneckstein__minmaxot_v1100.json"
TAG = "harness-v1.10.0"
HARNESS_PATHS = ("backend/app", "backend/pyproject.toml", "scripts", "frontend/src", ".gitattributes")
CAP_USD = "10.00"
REPO_URL = "https://github.com/stephaneckstein/minmaxot"
COMMIT = "3f88502bdd096cdc4fe946a9cae17896315459b5"
MIRROR = Path(os.environ.get("TEMP", "")) / "minmaxot_mirror.git"


def note(line: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / "launcher.txt", "a", encoding="utf-8", newline="\n") as f:
        f.write(f"{line} {datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds')}\n")


def mirror_ok() -> bool:
    """The local bare mirror holds the pinned commit (PLAN.md, git source). Without it git reads GitHub at this machine's speed."""
    if not (MIRROR / "HEAD").is_file():
        return False
    return subprocess.run(["git", "--git-dir", str(MIRROR), "cat-file", "-e", f"{COMMIT}^{{commit}}"], capture_output=True).returncode == 0


def preconditions() -> list[str]:
    problems = []
    for name, status in review_launch.authenticates().items():
        if status != 200:
            problems.append(f"{name} does not authenticate (the cheapest request returned {status})")
    if subprocess.run(["git", "diff", "--quiet", TAG, "HEAD", "--", *HARNESS_PATHS], cwd=ROOT).returncode != 0:
        problems.append(f"the harness paths at HEAD differ from {TAG}")
    if subprocess.run(["git", "diff", "--quiet", "HEAD", "--", *HARNESS_PATHS], cwd=ROOT).returncode != 0:
        problems.append("the harness paths have uncommitted changes")
    if RECORD.exists():
        problems.append(f"{RECORD.relative_to(ROOT).as_posix()} exists: this is a one-run plan")
    for name, value in review_launch.keys().items():
        if not value:
            problems.append(f"{name} is not set")
        elif any(c.isspace() for c in value):
            problems.append(f"{name} contains whitespace or a line end")
    plan = "reports/v1.10/tavily_live/PLAN.md"
    if subprocess.run(["git", "cat-file", "-e", f"HEAD:{plan}"], cwd=ROOT, capture_output=True).returncode != 0 \
            or subprocess.run(["git", "diff", "--quiet", "HEAD", "--", plan], cwd=ROOT).returncode != 0:
        problems.append("PLAN.md is not committed as it stands: the plan is committed before the run")
    return problems


def withhold_secrets() -> bool:
    """True when an output file held a key's value (it is replaced by a one-line notice)."""
    values = [v for v in review_launch.keys().values() if len(v) >= 8]
    hit = False
    for path in OUT.iterdir():
        if path.is_file() and path.name != "launcher.txt":
            text = path.read_text(encoding="utf-8", errors="replace")
            if any(v in text for v in values):
                path.write_text("record withheld: it contained a credential's value\n", encoding="utf-8")
                note(f"WITHHELD {path.name}")
                hit = True
    return hit


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--go", action="store_true")
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    problems = preconditions()
    if args.check or not args.go:
        print("preconditions:", "all hold" if not problems else "; ".join(problems))
        print("git source:", f"the local mirror {MIRROR} (holds {COMMIT[:7]})" if mirror_ok() else f"GitHub ({REPO_URL})")
        return 1 if problems else 0
    if problems:
        note("REFUSED " + "; ".join(problems))
        return 1
    env = {**os.environ, "BEHAVIOUR_MODE": "flag", "PYTHONIOENCODING": "utf-8"}
    if mirror_ok():
        env.update({"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": f"url.{MIRROR}.insteadOf", "GIT_CONFIG_VALUE_0": REPO_URL})
        note(f"MIRROR {MIRROR} holds {COMMIT}")
    meta = {"harness_tag": TAG, "label": "POST-HOC single run for the Tavily gap (reports/v1.10/tavily_live/PLAN.md): the wiring check's entry and mode with Tavily on; "
                                         "not an attempt at a flagged result; never merged into any count", "runner": "this machine, Task Scheduler"}
    note(f"LAUNCH {TAG} BEHAVIOUR_MODE=flag cap ${CAP_USD}")
    with open(OUT / "run_stdout.log", "w", encoding="utf-8", newline="\n") as log:
        code = subprocess.run([sys.executable, "-u", str(ROOT / "scripts" / "live_run.py"), "--name", "stephaneckstein__minmaxot",
                               "--corpus", str(ROOT / "backend" / "app" / "batch" / "corpus_v4" / "corpus.yaml"), "--out", str(RECORD),
                               "--cost-cap-usd", CAP_USD, "--dev-run", "--batch-meta", json.dumps(meta)],
                              cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT).returncode
    withheld = withhold_secrets()
    note(f"RETURNED {code}{' (a record was withheld)' if withheld else ''}")
    return 1 if withheld else code


if __name__ == "__main__":
    sys.exit(main())
