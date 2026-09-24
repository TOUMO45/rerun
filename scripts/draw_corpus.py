"""Pre-registered corpus draw for RERUN's Batch Lab (corpus-v1).

Two commands, run in this order and committed in between:

  population  Build the sampling frame from the Papers-with-Code archive at the
              PINNED dataset revisions (DuckDB over hf:// parquet, column
              projection + filters pushed to the source; the full parquet files
              are never downloaded) and write population.csv, sorted by paper_url.
  draw        Deterministically shuffle the frame with the pre-registered seed,
              screen candidates in that order until TARGET are eligible, and log
              EVERY draw with its pass/fail reason. Writes screening_log.jsonl,
              corpus.yaml and corpus_hash.txt.

Everything the draw depends on is fixed in prereg.json, committed before `draw`
runs (see METHODOLOGY.md).

Usage (repo root, backend/.venv):
  backend/.venv/Scripts/python.exe scripts/draw_corpus.py population
  backend/.venv/Scripts/python.exe scripts/draw_corpus.py draw
"""

from __future__ import annotations

import csv
import hashlib
import json
import random
import re
import subprocess
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
CORPUS_DIR = ROOT / "backend" / "app" / "batch" / "corpus_v1"
PREREG = CORPUS_DIR / "prereg.json"
POPULATION = CORPUS_DIR / "population.csv"
LOG = CORPUS_DIR / "screening_log.jsonl"
CORPUS_YAML = CORPUS_DIR / "corpus.yaml"
HASH_FILE = CORPUS_DIR / "corpus_hash.txt"


def _prereg() -> dict:
    return json.loads(PREREG.read_text(encoding="utf-8"))


def sha256_file(path: Path) -> str:
    # Raw bytes. All corpus-v1 files are written with "\n" line endings and are
    # `-text` in .gitattributes, so a checkout never changes these bytes.
    return hashlib.sha256(path.read_bytes()).hexdigest()


# --- population ------------------------------------------------------------------


def build_population() -> None:
    import duckdb

    pre = _prereg()
    papers, links = pre["datasets"]["papers"], pre["datasets"]["links"]
    p_url = f"hf://datasets/{papers['id']}@{papers['revision']}/data/*.parquet"
    l_url = f"hf://datasets/{links['id']}@{links['revision']}/data/*.parquet"
    f = pre["frame"]
    sql = f"""
    WITH papers AS (
      SELECT paper_url, title, proceeding FROM read_parquet('{p_url}')
      WHERE regexp_matches(coalesce(proceeding, ''), '{f["proceeding_regex"]}')
    ), links AS (
      SELECT paper_url, rtrim(repo_url, '/') AS repo_url FROM read_parquet('{l_url}')
      WHERE is_official AND regexp_matches(repo_url, '{f["repo_url_regex"]}')
    )
    SELECT p.paper_url,
           any_value(p.title) AS title,
           any_value(p.proceeding) AS proceeding,
           min(l.repo_url) AS repo_url,
           count(DISTINCT l.repo_url) AS n_official_repos
    FROM papers p JOIN links l USING (paper_url)
    GROUP BY p.paper_url
    ORDER BY p.paper_url
    """
    con = duckdb.connect()
    for attempt in range(8):
        try:
            rows = con.execute(sql).fetchall()
            break
        except duckdb.HTTPException as exc:  # Hugging Face rate limit (429) etc.
            wait = 30 * (attempt + 1)
            print(f"HTTP error ({str(exc)[:100]}); retry in {wait}s", flush=True)
            time.sleep(wait)
    else:
        raise SystemExit("gave up after repeated HTTP errors")
    venue_re = re.compile(f["proceeding_regex"])
    with POPULATION.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh, lineterminator="\n")
        writer.writerow(["paper_url", "venue", "year", "proceeding", "repo_url", "n_official_repos", "title"])
        counts: dict[tuple[str, str], int] = {}
        for paper_url, title, proceeding, repo_url, n in rows:
            m = venue_re.match(proceeding)
            venue = m.group(1).replace("NIPS", "NeurIPS")
            year = m.group(2)
            counts[(venue, year)] = counts.get((venue, year), 0) + 1
            writer.writerow([paper_url, venue, year, proceeding, repo_url, n, title])
    for key in sorted(counts):
        print(f"  {key[0]:8s} {key[1]}  {counts[key]}")
    print(f"population: {len(rows)} papers -> {POPULATION.relative_to(ROOT)} sha256={sha256_file(POPULATION)}")


# --- screening ---------------------------------------------------------------------

README_NAMES = ("README.md", "README.rst", "README", "readme.md", "Readme.md", "README.MD", "README.txt")
_CMD_RE = re.compile(
    r"^(?:[A-Z_][A-Z0-9_]*=\S+\s+)*(python3?|bash|sh)\s+(?:(-m)\s+([A-Za-z_][\w.]*)|(\S+\.(?:py|sh)))(?=\s|$)"
)
_PLACEHOLDER_RE = re.compile(r"<[^>]+>|\{[^}]*\}|/path/to|path/to/|YOUR_|your_|xxx|\.\.\.", re.IGNORECASE)
_PREFIX_RE = re.compile(r"^\s*(?:[$>%#]\s+|!\s*|`+)")


class RateLimited(Exception):
    pass


def _github_api(client: httpx.Client, path: str) -> tuple[int, dict]:
    while True:
        r = client.get(f"https://api.github.com{path}", headers={"Accept": "application/vnd.github+json"})
        if r.status_code in (403, 429) and r.headers.get("x-ratelimit-remaining") == "0":
            reset = int(r.headers.get("x-ratelimit-reset", time.time() + 60))
            wait = max(reset - time.time(), 0) + 5
            print(f"    GitHub API rate limit — waiting {wait:.0f}s", flush=True)
            time.sleep(wait)
            continue
        try:
            return r.status_code, r.json()
        except ValueError:
            return r.status_code, {}


def _raw(client: httpx.Client, owner_repo: str, sha: str, path: str) -> tuple[int, str]:
    r = client.get(f"https://raw.githubusercontent.com/{owner_repo}/{sha}/{path}")
    return r.status_code, (r.text if r.status_code == 200 else "")


def _commands_in(readme: str) -> list[tuple[int, str]]:
    """(line number, command) candidates in reading order; backslash
    continuations joined; leading prompt markers stripped."""
    out = []
    lines = readme.splitlines()
    i = 0
    while i < len(lines):
        start = i
        line = _PREFIX_RE.sub("", lines[i].strip()).strip("`").strip()
        while line.endswith("\\") and i + 1 < len(lines):
            i += 1
            line = line[:-1].rstrip() + " " + lines[i].strip()
        i += 1
        if _CMD_RE.match(line):
            out.append((start + 1, line))
    return out


def _target_path(match: re.Match) -> str:
    if match.group(2):  # python -m module
        return match.group(3).replace(".", "/")
    return match.group(4).removeprefix("./")


def screen(client: httpx.Client, candidate: dict) -> dict:
    repo_url = candidate["repo_url"]
    owner_repo = repo_url.removeprefix("https://github.com/")
    result = {"checks": {}}

    # E3 — reachable public repo; pin its default-branch HEAD now.
    import os

    ls = subprocess.run(
        ["git", "ls-remote", "--exit-code", repo_url.removesuffix(".git") + ".git", "HEAD"],
        capture_output=True, text=True, timeout=60,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
    )
    if ls.returncode != 0 or not ls.stdout.strip():
        result["checks"]["E3_reachable"] = False
        result["reason"] = "E3: repository unreachable (deleted, private, or renamed without redirect)"
        return result
    sha = ls.stdout.split()[0]
    result["checks"]["E3_reachable"] = True
    result["commit_sha"] = sha

    # E4 — primary language Python (GitHub linguist).
    status, meta = _github_api(client, f"/repos/{owner_repo}")
    language = meta.get("language") if status == 200 else None
    result["checks"]["E4_python"] = language == "Python"
    result["language"] = language
    if language != "Python":
        result["reason"] = f"E4: primary language is {language!r}, not Python" if status == 200 else f"E4: GitHub API HTTP {status}"
        return result

    # E5 — a documented run command in the README whose script/module exists.
    readme_name, readme = None, ""
    for name in README_NAMES:
        code, text = _raw(client, owner_repo, sha, name)
        if code == 200 and text.strip():
            readme_name, readme = name, text
            break
    if not readme_name:
        result["checks"]["E5_command"] = False
        result["reason"] = "E5: no README at the repository root"
        return result
    skipped_placeholder = 0
    for line_no, command in _commands_in(readme):
        if _PLACEHOLDER_RE.search(command):
            skipped_placeholder += 1
            continue
        match = _CMD_RE.match(command)
        target = _target_path(match)
        candidates = [target] if not match.group(2) else [target + ".py", target + "/__main__.py"]
        for path in candidates:
            code, _ = _raw(client, owner_repo, sha, path)
            if code == 200:
                result["checks"]["E5_command"] = True
                result.update(command=command, command_source=f"{readme_name} line {line_no}", script=path)
                result["eligible"] = True
                return result
    result["checks"]["E5_command"] = False
    result["reason"] = (
        f"E5: no runnable documented command in {readme_name}"
        + (f" ({skipped_placeholder} candidate(s) skipped for placeholders)" if skipped_placeholder else "")
    )
    return result


def draw() -> None:
    pre = _prereg()
    if sha256_file(POPULATION) != pre["population_sha256"]:
        raise SystemExit("population.csv does not match the pre-registered sha256 — refusing to draw")
    if (
        _CMD_RE.pattern != pre["eligibility"]["command_regex"]
        or _PLACEHOLDER_RE.pattern != pre["eligibility"]["placeholder_regex"]
        or not (_PLACEHOLDER_RE.flags & re.IGNORECASE) or pre["eligibility"].get("placeholder_regex_flags") != "IGNORECASE"
    ):
        raise SystemExit("the script's E5 regexes differ from prereg.json — refusing to draw")
    with POPULATION.open(encoding="utf-8", newline="") as fh:
        population = list(csv.DictReader(fh))
    order = list(range(len(population)))
    random.Random(pre["seed"]).shuffle(order)
    target = pre["target_eligible"]
    eligible, seen_repos = [], set()
    LOG.write_text("", encoding="utf-8", newline="\n")
    with httpx.Client(timeout=30, follow_redirects=True, headers={"User-Agent": "rerun-corpus-draw"}) as client:
        for draw_no, idx in enumerate(order, start=1):
            candidate = population[idx]
            entry = {"draw": draw_no, "population_index": idx, **{k: candidate[k] for k in ("paper_url", "venue", "year", "repo_url", "title")}}
            if candidate["repo_url"].lower() in seen_repos:
                entry.update(eligible=False, reason="duplicate: repository already drawn for another paper")
            else:
                seen_repos.add(candidate["repo_url"].lower())
                outcome = screen(client, candidate)
                entry.update(eligible=bool(outcome.pop("eligible", False)), **outcome)
            with LOG.open("a", encoding="utf-8", newline="\n") as fh:
                fh.write(json.dumps(entry) + "\n")
            print(f"#{draw_no:3d} {'ELIGIBLE' if entry['eligible'] else 'fail    '} {candidate['venue']} {candidate['year']} "
                  f"{candidate['repo_url']}  {entry.get('reason', entry.get('command', ''))[:110]}", flush=True)
            if entry["eligible"]:
                eligible.append(entry)
                if len(eligible) == target:
                    break
    write_corpus(pre, eligible)


def write_corpus(pre: dict, eligible: list[dict]) -> None:
    import yaml

    entries = []
    for k, e in enumerate(eligible, start=1):
        owner_repo = e["repo_url"].removeprefix("https://github.com/")
        entries.append({
            "name": owner_repo.replace("/", "__"),
            "repo_url": e["repo_url"],
            "commit_sha": e["commit_sha"],
            "entrypoint_hint": e["script"],
            "command": e["command"],
            "command_source": e["command_source"],
            "paper_url": e["paper_url"],
            "venue": e["venue"],
            "year": int(e["year"]),
            "selection_note": f"corpus-v1 eligible #{k} (draw #{e['draw']}, seed {pre['seed']}): {e['venue']} {e['year']} — {e['title']}",
        })
    canonical = json.dumps(
        {
            "prereg_sha256": sha256_file(PREREG),
            "entries": sorted(({k: x[k] for k in ("name", "repo_url", "commit_sha", "command")} for x in entries), key=lambda x: x["name"]),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    corpus_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    header = (
        "# RERUN corpus-v1 — drawn by scripts/draw_corpus.py under the pre-registration in prereg.json.\n"
        "# Do not edit by hand: any change is a new corpus version (corpus_hash changes).\n"
        f"# corpus_hash: {corpus_hash}\n"
    )
    CORPUS_YAML.write_text(header + yaml.safe_dump({"corpus_version": "corpus-v1", "corpus_hash": corpus_hash, "repos": entries},
                                                   sort_keys=False, allow_unicode=True), encoding="utf-8", newline="\n")
    HASH_FILE.write_text(corpus_hash + "\n", encoding="utf-8", newline="\n")
    print(f"\neligible: {len(entries)} / target {pre['target_eligible']}; corpus_hash {corpus_hash}")


if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) > 1 else ""
    if command == "population":
        build_population()
    elif command == "draw":
        draw()
    else:
        raise SystemExit(__doc__)
