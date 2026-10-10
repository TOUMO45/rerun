"""The one live run of PLAN.md (owner, 2026-10-10, Step 1): M-FAC at harness-v1.10.0, flag mode, Tavily on, cap $10.00. Refuses before any spend unless every
precondition holds; after the run, withholds any output file that contains a key's value. Started by launch.cmd through Task Scheduler (D-43).

    backend/.venv/Scripts/python.exe reports/v1.10/review_live/launch.py --check   # the preconditions only, no network
    backend/.venv/Scripts/python.exe reports/v1.10/review_live/launch.py --go      # the run
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "runs" / "v1.10" / "review_live"
RECORD = OUT / "14_IST-DASLab__M-FAC_v1100.json"
TAG = "harness-v1.10.0"
HARNESS_PATHS = ("backend/app", "backend/pyproject.toml", "scripts", "frontend/src", ".gitattributes")
CAP_USD = "10.00"


def note(line: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / "launcher.txt", "a", encoding="utf-8", newline="\n") as f:
        f.write(f"{line} {datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds')}\n")


def keys() -> dict[str, str]:
    sys.path.insert(0, str(ROOT / "backend"))
    cwd = os.getcwd()
    os.chdir(ROOT / "backend")
    try:
        from app.config import get_settings
        s = get_settings()
        return {"NEBIUS_API_KEY": s.nebius_api_key or "", "NEBIUS_PROJECT_ID": s.nebius_project_id or "", "TAVILY_API_KEY": s.tavily_api_key or ""}
    finally:
        os.chdir(cwd)


def authenticates() -> dict[str, object]:
    """The cheapest authenticated request per key (free: the model list, the Tavily usage page). Status codes only: an exception is reported by its type name,
    never its text (a header error's text carries the header)."""
    import urllib.error
    import urllib.request
    k = keys()
    calls = {"NEBIUS_API_KEY": ("https://api.tokenfactory.nebius.com/v1/models", k["NEBIUS_API_KEY"]),
             "TAVILY_API_KEY": ("https://api.tavily.com/usage", k["TAVILY_API_KEY"])}
    out: dict[str, object] = {}
    for name, (url, token) in calls.items():
        if not token or any(c.isspace() for c in token):
            out[name] = "not tried"
            continue
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"}), timeout=30) as resp:
                out[name] = resp.status
        except urllib.error.HTTPError as exc:
            out[name] = exc.code
        except Exception as exc:  # noqa: BLE001 - the type only
            out[name] = type(exc).__name__
    return out


def preconditions() -> list[str]:
    problems = []
    for name, status in authenticates().items():
        if status != 200:
            problems.append(f"{name} does not authenticate (the cheapest request returned {status})")
    if subprocess.run(["git", "diff", "--quiet", TAG, "HEAD", "--", *HARNESS_PATHS], cwd=ROOT).returncode != 0:
        problems.append(f"the harness paths at HEAD differ from {TAG}")
    if subprocess.run(["git", "diff", "--quiet", "HEAD", "--", *HARNESS_PATHS], cwd=ROOT).returncode != 0:
        problems.append("the harness paths have uncommitted changes")
    if RECORD.exists():
        problems.append(f"{RECORD.relative_to(ROOT).as_posix()} exists: this is a one-run plan")
    for name, value in keys().items():
        if not value:
            problems.append(f"{name} is not set")
        elif any(c.isspace() for c in value):
            problems.append(f"{name} contains whitespace or a line end")
    return problems


def withhold_secrets() -> bool:
    """True when an output file held a key's value (it is replaced by a one-line notice)."""
    values = [v for v in keys().values() if len(v) >= 8]
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
        return 1 if problems else 0
    if problems:
        note("REFUSED " + "; ".join(problems))
        return 1
    env = {**os.environ, "BEHAVIOUR_MODE": "flag", "PYTHONIOENCODING": "utf-8"}
    meta = {"harness_tag": TAG, "label": "POST-HOC single run in flag mode with Tavily on (reports/v1.10/review_live/PLAN.md), never merged into any count",
            "runner": "this machine, Task Scheduler"}
    note(f"LAUNCH {TAG} BEHAVIOUR_MODE=flag cap ${CAP_USD}")
    with open(OUT / "run_stdout.log", "w", encoding="utf-8", newline="\n") as log:
        code = subprocess.run([sys.executable, "-u", str(ROOT / "scripts" / "live_run.py"), "--name", "IST-DASLab__M-FAC",
                               "--corpus", str(ROOT / "backend" / "app" / "batch" / "corpus_v2" / "corpus.yaml"), "--out", str(RECORD),
                               "--cost-cap-usd", CAP_USD, "--dev-run", "--batch-meta", json.dumps(meta)],
                              cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT).returncode
    withheld = withhold_secrets()
    note(f"RETURNED {code}{' (a record was withheld)' if withheld else ''}")
    return 1 if withheld else code


if __name__ == "__main__":
    sys.exit(main())
