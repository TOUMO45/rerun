"""Run the frozen corpus-v1 Batch Lab: all 20 entries, as drawn, on the frozen
harness, and write one run record per entry plus a summary.

Preflight — the batch refuses to start unless ALL hold:
  1. the working tree is clean (no modified/staged tracked files, no untracked
     files outside this batch's own output directory, so a stopped batch can
     resume on the same commit);
  2. HEAD is exactly the commit tagged HARNESS_TAG, and origin has that tag at
     that commit;
  3. amendment-1.json's sha256 equals the value pinned here AND its
     amendment-1.sha256 file (committed before the tag, before any run);
  4. the corpus hash recomputed from corpus.yaml + prereg.json equals the
     hash recorded in corpus.yaml and corpus_hash.txt.

Execution: entries in corpus order, one `scripts/live_run.py` process each,
$PER_ENTRY_CAP_USD hard cap each (the run-local CostGuard). Within each entry
the pipeline runs the as-is baseline (declared install + recorded command)
before RERUN changes anything. The batch stops before any entry whose cap
could take the total past $TOTAL_CAP_USD, and stops at the first run that
ends without a verdict (a driver error). Entries whose record already exists
are skipped (resume).

Every record carries the harness tag + commit, corpus hash, amendment sha256,
the entry's amendment category, repair_mode and tree_integrity.

Usage (repo root):  backend/.venv/Scripts/python.exe scripts/run_corpus_v1_batch.py
                    backend/.venv/Scripts/python.exe scripts/run_corpus_v1_batch.py --summarize-only
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORPUS_DIR = ROOT / "backend" / "app" / "batch" / "corpus_v1"
OUT_DIR = ROOT / "runs" / "corpus_v1_batch"
PYTHON = ROOT / "backend" / ".venv" / "Scripts" / "python.exe"

HARNESS_TAG = "harness-v1"
EXPECTED_AMENDMENT_SHA256 = "63d409a3ffc92b016fde502b90e53500a48287b7a286c7078148ac3650b9622d"
PER_ENTRY_CAP_USD = 2.0
TOTAL_CAP_USD = 40.0


class PreflightError(RuntimeError):
    pass


def _git(*args: str) -> str:
    # rstrip only: `status --porcelain` lines start with a significant space (" M path").
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout.rstrip()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def recompute_corpus_hash() -> str:
    """scripts/draw_corpus.py's corpus_hash_definition, recomputed from the files."""
    import yaml

    data = yaml.safe_load((CORPUS_DIR / "corpus.yaml").read_text(encoding="utf-8"))
    canonical = json.dumps(
        {
            "prereg_sha256": _sha256(CORPUS_DIR / "prereg.json"),
            "entries": sorted(
                ({k: e[k] for k in ("name", "repo_url", "commit_sha", "command")} for e in data["repos"]),
                key=lambda e: e["name"],
            ),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def dirty_paths(porcelain: str, allowed_untracked_prefix: str) -> list[str]:
    """Lines of `git status --porcelain` that make the tree dirty: anything
    except untracked files under the batch's own output directory."""
    bad = []
    for line in porcelain.splitlines():
        if not line.strip():
            continue
        status, path = line[:2], line[3:].strip().strip('"')
        if status == "??" and path.replace("\\", "/").startswith(allowed_untracked_prefix):
            continue
        bad.append(line)
    return bad


def preflight() -> dict:
    out_prefix = OUT_DIR.relative_to(ROOT).as_posix() + "/"
    dirty = dirty_paths(_git("status", "--porcelain", "--untracked-files=all"), out_prefix)
    if dirty:
        raise PreflightError(f"working tree is dirty: {dirty[:10]}")

    try:
        tag_commit = _git("rev-parse", f"{HARNESS_TAG}^{{commit}}")
    except subprocess.CalledProcessError as exc:
        raise PreflightError(f"tag {HARNESS_TAG} does not exist") from exc
    head = _git("rev-parse", "HEAD")
    if head != tag_commit:
        raise PreflightError(f"HEAD {head} is not {HARNESS_TAG} ({tag_commit})")
    remote = _git("ls-remote", "origin", f"refs/tags/{HARNESS_TAG}^{{}}") or _git("ls-remote", "origin", f"refs/tags/{HARNESS_TAG}")
    if not remote or remote.split()[0] != tag_commit:
        raise PreflightError(f"origin does not have {HARNESS_TAG} at {tag_commit} (got {remote!r})")

    amendment_sha = _sha256(CORPUS_DIR / "amendment-1.json")
    recorded_sha = (CORPUS_DIR / "amendment-1.sha256").read_text(encoding="utf-8").split()[0]
    if not (amendment_sha == recorded_sha == EXPECTED_AMENDMENT_SHA256):
        raise PreflightError(
            f"amendment sha256 mismatch: file {amendment_sha}, recorded {recorded_sha}, pinned {EXPECTED_AMENDMENT_SHA256}"
        )

    corpus_hash = recompute_corpus_hash()
    import yaml

    recorded_hash = yaml.safe_load((CORPUS_DIR / "corpus.yaml").read_text(encoding="utf-8"))["corpus_hash"]
    hash_file = (CORPUS_DIR / "corpus_hash.txt").read_text(encoding="utf-8").strip()
    if not (corpus_hash == recorded_hash == hash_file):
        raise PreflightError(f"corpus hash mismatch: recomputed {corpus_hash}, yaml {recorded_hash}, file {hash_file}")

    return {"harness_tag": HARNESS_TAG, "harness_commit": tag_commit, "amendment_sha256": amendment_sha, "corpus_hash": corpus_hash}


def _record_path(entry_id: int, name: str) -> Path:
    return OUT_DIR / f"{entry_id:02d}_{name}.json"


def run_batch(frozen: dict) -> list[dict]:
    amendment = json.loads((CORPUS_DIR / "amendment-1.json").read_text(encoding="utf-8"))
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    spent = 0.0
    for row in amendment["entries"]:
        path = _record_path(row["id"], row["name"])
        if path.exists():
            spent += json.loads(path.read_text(encoding="utf-8"))["cost_guard"]["spent_usd"]
            print(f"#{row['id']:2} {row['name']}: record exists, skipped (resume)", flush=True)
            continue
        if spent + PER_ENTRY_CAP_USD > TOTAL_CAP_USD + 1e-9:
            print(f"STOP: ${spent:.4f} spent; another ${PER_ENTRY_CAP_USD} cap would pass the ${TOTAL_CAP_USD} total", flush=True)
            break
        meta = {**frozen, "entry_id": row["id"], "category": row["category"], "rules_matched": row["rules_matched"],
                "per_entry_cap_usd": PER_ENTRY_CAP_USD, "total_cap_usd": TOTAL_CAP_USD}
        print(f"#{row['id']:2} {row['name']} [{row['category']}] starting", flush=True)
        subprocess.run(
            [str(PYTHON), str(ROOT / "scripts" / "live_run.py"),
             "--corpus", str(CORPUS_DIR / "corpus.yaml"), "--name", row["name"],
             "--cost-cap-usd", str(PER_ENTRY_CAP_USD), "--corpus-hash", frozen["corpus_hash"],
             "--batch-meta", json.dumps(meta), "--out", str(path)],
            cwd=ROOT,
            check=False,
        )
        record = json.loads(path.read_text(encoding="utf-8"))
        spent += record["cost_guard"]["spent_usd"]
        result = record.get("result") or {}
        print(f"#{row['id']:2} {row['name']}: {result.get('verdict')} {result.get('taxonomy_code')} "
              f"${record['cost_guard']['spent_usd']:.4f} (total ${spent:.4f})", flush=True)
        if record.get("error"):
            print(f"STOP: run ended without a verdict: {record['error']}", flush=True)
            break
    return load_records()


def load_records() -> list[dict]:
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(OUT_DIR.glob("[0-9][0-9]_*.json"))]


def summarize(records: list[dict]) -> dict:
    """PURE: the per-entry table for all records and the headline numbers
    over PRIMARY entries only (amendment 1)."""
    rows = []
    for r in records:
        result = r.get("result") or {}
        cert = r.get("certificate") or {}
        baseline = (cert.get("baseline") or {})
        rows.append({
            "id": r["batch"]["entry_id"],
            "name": r["corpus_entry"]["name"],
            "category": r["batch"]["category"],
            "baseline": baseline.get("result"),
            "baseline_taxonomy": baseline.get("taxonomy_code"),
            "verdict": result.get("verdict"),
            "taxonomy_code": result.get("taxonomy_code"),
            "reason_code": result.get("reason_code"),
            "recovery": bool(cert.get("recovery")),
            "repair_mode": r.get("repair_mode"),
            "tree_integrity": (r.get("tree_integrity") or cert.get("tree_integrity") or {}).get("status"),
            "harness_tag": r["batch"]["harness_tag"],
            "harness_commit": r["batch"]["harness_commit"],
            "spent_usd": round(r["cost_guard"]["spent_usd"], 4),
            "error": r.get("error"),
        })
    primary = [row for row in rows if row["category"] == "PRIMARY"]
    failed = [row for row in primary if row["baseline"] == "FAILS"]
    recovered = [row for row in failed if row["verdict"] == "RUNS_AFTER_REPAIR"]
    blocked: dict[str, int] = {}
    for row in primary:
        if row["verdict"] == "BLOCKED":
            blocked[row["taxonomy_code"] or "unknown"] = blocked.get(row["taxonomy_code"] or "unknown", 0) + 1
    verdicts: dict[str, int] = {}
    for row in primary:
        verdicts[row["verdict"] or "none"] = verdicts.get(row["verdict"] or "none", 0) + 1
    return {
        "n_records": len(rows),
        "primary": {
            "n": len(primary),
            "failed_as_published": len(failed),
            "ran_as_published": sum(1 for row in primary if row["baseline"] == "RUNS_CLEAN"),
            "runs_after_repair": len(recovered),
            "blocked_by_reason": dict(sorted(blocked.items())),
            "invalid_harness": sum(1 for row in primary if row["verdict"] == "INVALID_HARNESS"),
            "verdicts": dict(sorted(verdicts.items())),
            "recovered_repair_mode": {
                "deterministic": sum(1 for row in recovered if row["repair_mode"] == "deterministic"),
                "model_assisted": sum(1 for row in recovered if row["repair_mode"] == "model_assisted"),
            },
            "headline": f"PRIMARY: {len(recovered)}/{len(failed)} of {len(primary)}",
        },
        "command_not_a_run": {
            "n": sum(1 for row in rows if row["category"] != "PRIMARY"),
            "verdicts": {v: sum(1 for row in rows if row["category"] != "PRIMARY" and row["verdict"] == v)
                         for v in sorted({row["verdict"] for row in rows if row["category"] != "PRIMARY"}, key=str)},
            "note": "executed identically; never counted in the recovery rate (amendment 1)",
        },
        "total_spent_usd": round(sum(row["spent_usd"] for row in rows), 4),
        "rows": rows,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--summarize-only", action="store_true", help="skip preflight/runs; summarize existing records")
    args = parser.parse_args(argv)
    if not args.summarize_only:
        try:
            frozen = preflight()
        except PreflightError as exc:
            print(f"REFUSING TO START: {exc}", file=sys.stderr)
            return 2
        print(f"preflight OK: {frozen}", flush=True)
        run_batch(frozen)
    summary = summarize(load_records())
    (OUT_DIR / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({k: v for k, v in summary.items() if k != "rows"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
