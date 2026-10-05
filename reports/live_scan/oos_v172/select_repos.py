"""Out-of-sample scan of harness-v1.7.2: how the 5 repositories are picked (written and committed BEFORE the selection runs; owner, chat 2026-10-05).

Rule (fixed here, run once, after the harness-v1.7.2 tag):
  * Five GitHub topics, one repository each, chosen to vary the kind of Python program, none of them research code:
        cli, web-scraping, game, data-visualization, automation
  * For each topic, the GitHub search API (unauthenticated, https://api.github.com/search/repositories) with
        q = "topic:<topic> language:Python stars:30..400 size:<20000 pushed:2019-01-01..2023-12-31 archived:false fork:false"
        sort = stars, order = desc, per_page = 50
    The pushed window keeps old-enough code that its environment has drifted (what RERUN is for) without picking abandoned stubs; the star window and size cap keep
    repositories small and real.
  * Walk the results in the API's order and take the FIRST repository that passes all of:
        - its URL is not in any record RERUN has ever written or listed (the firewall below), and not already taken for another topic;
        - the default branch has at least one .py file at the top level or one directory down (GitHub contents API), so intake can find Python code.
  * Nothing else is looked at: no README is read, nothing is run, and a repository is never swapped for another after it is picked.

Firewall: every repo URL found in runs/ (corpus records, live UI runs, live scans), backend/app/batch/corpus_v1 and corpus_v2 (corpus.yaml and screening_log.jsonl,
which lists every candidate ever screened), reports/ (any JSON, YAML or Markdown file), compared case-insensitively without a trailing ".git" or "/".

Writes reports/live_scan/oos_v172/selection.json with the raw search responses' repository lists (name, stars, pushed_at), every skip and its reason, and the picks.
"""
from __future__ import annotations

import json
import re
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent / "selection.json"
TOPICS = ("cli", "web-scraping", "game", "data-visualization", "automation")
QUERY = "topic:{topic} language:Python stars:30..400 size:<20000 pushed:2019-01-01..2023-12-31 archived:false fork:false"
URL_RE = re.compile(r"https?://github\.com/([A-Za-z0-9][A-Za-z0-9-]*)/([A-Za-z0-9_.-]+)", re.IGNORECASE)


def _norm(owner: str, repo: str) -> str:
    repo = repo[:-4] if repo.lower().endswith(".git") else repo
    return f"{owner}/{repo}".rstrip("/").lower()


def firewall() -> set[str]:
    seen: set[str] = set()
    roots = [ROOT / "runs", ROOT / "reports", ROOT / "backend" / "app" / "batch"]
    for base in roots:
        for path in base.rglob("*"):
            if path.suffix.lower() not in {".json", ".jsonl", ".yaml", ".yml", ".md", ".csv", ".log", ".txt"} or not path.is_file():
                continue
            if path.resolve() == OUT:
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            seen.update(_norm(m.group(1), m.group(2)) for m in URL_RE.finditer(text))
    return seen


def _get(url: str) -> object:
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": "rerun-oos-selection"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def has_python(full_name: str) -> bool:
    top = _get(f"https://api.github.com/repos/{full_name}/contents/")
    if any(item["type"] == "file" and item["name"].endswith(".py") for item in top):
        return True
    for item in top:
        if item["type"] == "dir" and not item["name"].startswith("."):
            time.sleep(1)
            if any(sub["type"] == "file" and sub["name"].endswith(".py") for sub in _get(item["url"])):
                return True
    return False


def main() -> int:
    if OUT.exists():
        raise SystemExit(f"{OUT} exists: the selection runs once and is never redone")
    blocked = firewall()
    doc = {"rule": __doc__, "ran_at": datetime.now(timezone.utc).isoformat(), "firewall_size": len(blocked), "topics": [], "picks": []}
    taken: set[str] = set()
    for topic in TOPICS:
        q = QUERY.format(topic=topic)
        url = "https://api.github.com/search/repositories?" + urllib.parse.urlencode({"q": q, "sort": "stars", "order": "desc", "per_page": 50})
        items = _get(url)["items"]
        row = {"topic": topic, "query": q, "results": [{"full_name": i["full_name"], "stars": i["stargazers_count"], "pushed_at": i["pushed_at"]} for i in items],
               "skipped": [], "pick": None}
        for item in items:
            name = item["full_name"]
            key = name.lower()
            if key in blocked:
                row["skipped"].append({"full_name": name, "reason": "firewall: already in a RERUN record or list"})
                continue
            if key in taken:
                row["skipped"].append({"full_name": name, "reason": "already picked for another topic"})
                continue
            time.sleep(1)
            if not has_python(name):
                row["skipped"].append({"full_name": name, "reason": "no .py file at the top level or one directory down"})
                continue
            row["pick"] = f"https://github.com/{name}"
            taken.add(key)
            break
        doc["topics"].append(row)
        if row["pick"]:
            doc["picks"].append(row["pick"])
        time.sleep(7)  # unauthenticated search API: 10 requests per minute
    OUT.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8", newline="\n")
    print("\n".join(doc["picks"]))
    return 0 if len(doc["picks"]) == len(TOPICS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
