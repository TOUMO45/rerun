"""Run a frozen Batch Lab corpus (corpus-v1 or corpus-v2), as drawn, on a frozen
harness tag, and write one run record per entry plus a summary.

Preflight — the batch refuses to start unless ALL hold:
  1. the working tree is clean (no modified/staged tracked files, no untracked
     files outside this batch's own output directory, so a stopped batch can
     resume on the same commit);
  2. the harness tag exists, origin has it at the same commit, and HEAD is that
     commit or a descendant of it;
  3. every path changed between the tag and HEAD (`git diff --name-only
     <tag>..HEAD`) is on DATA_ALLOWLIST — run records, DECISIONS/METHODOLOGY,
     and corpus-v2's draw outputs — and the git blob of every harness file and
     every sealed file is identical at HEAD and at the tag (hash check);
  4. corpus-v1: amendment-1.json's sha256 equals the pinned value and its
     .sha256 file; corpus-v2: prereg.json's sha256 equals prereg.sha256 (as
     sealed at the tag);
  5. the corpus hash recomputed from corpus.yaml + prereg.json equals the hash
     recorded in corpus.yaml and corpus_hash.txt.

Execution: entries in corpus order, one `scripts/live_run.py` process each,
$PER_ENTRY_CAP_USD hard cap each (the run-local CostGuard). Within each entry
the pipeline runs the as-is baseline (declared install + recorded command)
before RERUN changes anything. The batch stops before any entry whose cap
could take the total past $TOTAL_CAP_USD, at the first run that ends without
a verdict (a driver error), and — circuit breaker — after CIRCUIT_BREAKER
consecutive INFRA_ERROR verdicts. Entries whose record already exists are
skipped (resume).

Every record carries the harness tag + commit, corpus hash, the entry's
category (corpus-v1 amendment 1; every corpus-v2 entry is PRIMARY),
repair_mode and tree_integrity.

Usage (repo root):
  backend/.venv/Scripts/python.exe scripts/run_corpus_v1_batch.py --corpus corpus-v1 --harness-tag harness-v1.1
  backend/.venv/Scripts/python.exe scripts/run_corpus_v1_batch.py --corpus corpus-v2 --harness-tag harness-v1.1
  ... --summarize-only
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BATCH_DIR = ROOT / "backend" / "app" / "batch"
PYTHON = ROOT / "backend" / ".venv" / "Scripts" / "python.exe"

DEFAULT_HARNESS_TAG = "harness-v1.1"
EXPECTED_AMENDMENT_SHA256 = "63d409a3ffc92b016fde502b90e53500a48287b7a286c7078148ac3650b9622d"
PER_ENTRY_CAP_USD = 2.0
TOTAL_CAP_USD = 40.0
CIRCUIT_BREAKER = 2  # consecutive INFRA_ERROR verdicts

# Paths that may change after the harness tag (data, never code).
DATA_ALLOWLIST = (
    re.compile(r"^runs/"),
    re.compile(r"^DECISIONS\.md$"),
    re.compile(r"^METHODOLOGY\.md$"),
    re.compile(r"^backend/app/batch/corpus_v2/(screening_log\.jsonl|corpus\.yaml|corpus_hash\.txt)$"),
)
# Must be byte-identical (same git blob) at HEAD and at the tag.
HARNESS_PATHS = ("backend/app", "backend/pyproject.toml", "scripts", "frontend/src", ".gitattributes")
SEALED_FILES = (
    "backend/app/batch/corpus_v1/prereg.json",
    "backend/app/batch/corpus_v1/corpus.yaml",
    "backend/app/batch/corpus_v1/corpus_hash.txt",
    "backend/app/batch/corpus_v1/amendment-1.json",
    "backend/app/batch/corpus_v1/amendment-1.sha256",
    "backend/app/batch/corpus_v2/prereg.json",
    "backend/app/batch/corpus_v2/prereg.sha256",
)
DRAW_OUTPUTS = ("screening_log.jsonl", "corpus.yaml", "corpus_hash.txt")


class PreflightError(RuntimeError):
    pass


def _git(*args: str) -> str:
    # rstrip only: `status --porcelain` lines start with a significant space (" M path").
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout.rstrip()


def _git_ok(*args: str) -> bool:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True).returncode == 0


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def corpus_dir(corpus: str) -> Path:
    return BATCH_DIR / corpus.replace("-", "_")


def out_dir(corpus: str, tag: str) -> Path:
    return ROOT / "runs" / f"{corpus.replace('-', '_')}_batch" / tag


def recompute_corpus_hash(cdir: Path) -> str:
    """scripts/draw_corpus.py's corpus_hash_definition, recomputed from the files."""
    import yaml

    data = yaml.safe_load((cdir / "corpus.yaml").read_text(encoding="utf-8"))
    canonical = json.dumps(
        {
            "prereg_sha256": _sha256(cdir / "prereg.json"),
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


def disallowed_changes(changed: list[str]) -> list[str]:
    return [p for p in changed if p and not any(rx.match(p) for rx in DATA_ALLOWLIST)]


def _blob_listing(ref: str, paths: tuple[str, ...]) -> dict[str, str]:
    listing = _git("ls-tree", "-r", ref, "--", *paths)
    out = {}
    for line in listing.splitlines():
        meta, _, path = line.partition("\t")
        if not any(rx.match(path) for rx in DATA_ALLOWLIST):  # e.g. corpus-v2 draw outputs under backend/app
            out[path] = meta.split()[2]
    return out


def preflight(corpus: str, tag: str) -> dict:
    cdir = corpus_dir(corpus)
    prefix = out_dir(corpus, tag).relative_to(ROOT).as_posix() + "/"
    dirty = dirty_paths(_git("status", "--porcelain", "--untracked-files=all"), prefix)
    if dirty:
        raise PreflightError(f"working tree is dirty: {dirty[:10]}")

    try:
        tag_commit = _git("rev-parse", f"{tag}^{{commit}}")
    except subprocess.CalledProcessError as exc:
        raise PreflightError(f"tag {tag} does not exist") from exc
    head = _git("rev-parse", "HEAD")
    if head != tag_commit and not _git_ok("merge-base", "--is-ancestor", tag_commit, head):
        raise PreflightError(f"HEAD {head} is neither {tag} ({tag_commit}) nor a descendant of it")
    remote = _git("ls-remote", "origin", f"refs/tags/{tag}^{{}}") or _git("ls-remote", "origin", f"refs/tags/{tag}")
    if not remote or remote.split()[0] != tag_commit:
        raise PreflightError(f"origin does not have {tag} at {tag_commit} (got {remote!r})")

    changed = [p for p in _git("diff", "--name-only", f"{tag_commit}..{head}").splitlines() if p]
    bad = disallowed_changes(changed)
    if bad:
        raise PreflightError(f"changed since {tag} outside the data allowlist: {bad[:10]}")
    for paths, what in ((HARNESS_PATHS, "harness code"), (SEALED_FILES, "sealed files")):
        at_tag, at_head = _blob_listing(tag_commit, paths), _blob_listing(head, paths)
        if at_tag != at_head:
            differing = sorted(p for p in set(at_tag) | set(at_head) if at_tag.get(p) != at_head.get(p))
            raise PreflightError(f"{what} differ from {tag}: {differing[:10]}")

    frozen = {"harness_tag": tag, "harness_commit": tag_commit, "head_commit": head, "corpus": corpus}
    if corpus == "corpus-v1":
        amendment_sha = _sha256(cdir / "amendment-1.json")
        recorded_sha = (cdir / "amendment-1.sha256").read_text(encoding="utf-8").split()[0]
        if not (amendment_sha == recorded_sha == EXPECTED_AMENDMENT_SHA256):
            raise PreflightError(
                f"amendment sha256 mismatch: file {amendment_sha}, recorded {recorded_sha}, pinned {EXPECTED_AMENDMENT_SHA256}"
            )
        frozen["amendment_sha256"] = amendment_sha
    else:
        prereg_sha = _sha256(cdir / "prereg.json")
        if prereg_sha != (cdir / "prereg.sha256").read_text(encoding="utf-8").split()[0]:
            raise PreflightError("corpus-v2 prereg.json does not match prereg.sha256")
        for name in DRAW_OUTPUTS:
            if not (cdir / name).is_file():
                raise PreflightError(f"corpus-v2 is not drawn yet ({name} missing)")
        frozen["prereg_sha256"] = prereg_sha

    import yaml

    corpus_hash = recompute_corpus_hash(cdir)
    recorded_hash = yaml.safe_load((cdir / "corpus.yaml").read_text(encoding="utf-8"))["corpus_hash"]
    hash_file = (cdir / "corpus_hash.txt").read_text(encoding="utf-8").strip()
    if not (corpus_hash == recorded_hash == hash_file):
        raise PreflightError(f"corpus hash mismatch: recomputed {corpus_hash}, yaml {recorded_hash}, file {hash_file}")
    frozen["corpus_hash"] = corpus_hash
    return frozen


def entries_for(corpus: str) -> list[dict]:
    cdir = corpus_dir(corpus)
    if corpus == "corpus-v1":
        amendment = json.loads((cdir / "amendment-1.json").read_text(encoding="utf-8"))
        return [{"id": r["id"], "name": r["name"], "category": r["category"], "rules_matched": r["rules_matched"]}
                for r in amendment["entries"]]
    import yaml

    repos = yaml.safe_load((cdir / "corpus.yaml").read_text(encoding="utf-8"))["repos"]
    return [{"id": i, "name": r["name"], "category": "PRIMARY", "rules_matched": []} for i, r in enumerate(repos, start=1)]


def _record_path(odir: Path, entry_id: int, name: str) -> Path:
    return odir / f"{entry_id:02d}_{name}.json"


def run_batch(frozen: dict, *, runner=None) -> list[dict]:
    corpus, tag = frozen["corpus"], frozen["harness_tag"]
    odir = out_dir(corpus, tag)
    odir.mkdir(parents=True, exist_ok=True)
    runner = runner or _run_live
    spent, consecutive_infra = 0.0, 0
    for row in entries_for(corpus):
        path = _record_path(odir, row["id"], row["name"])
        if path.exists():
            record = json.loads(path.read_text(encoding="utf-8"))
            spent += record["cost_guard"]["spent_usd"]
            verdict = (record.get("result") or {}).get("verdict")
            consecutive_infra = consecutive_infra + 1 if verdict == "INFRA_ERROR" else 0
            print(f"#{row['id']:2} {row['name']}: record exists, skipped (resume)", flush=True)
            continue
        if spent + PER_ENTRY_CAP_USD > TOTAL_CAP_USD + 1e-9:
            print(f"STOP: ${spent:.4f} spent; another ${PER_ENTRY_CAP_USD} cap would pass the ${TOTAL_CAP_USD} total", flush=True)
            break
        meta = {**frozen, "entry_id": row["id"], "category": row["category"], "rules_matched": row["rules_matched"],
                "per_entry_cap_usd": PER_ENTRY_CAP_USD, "total_cap_usd": TOTAL_CAP_USD}
        print(f"#{row['id']:2} {row['name']} [{row['category']}] starting", flush=True)
        runner(corpus, row["name"], frozen["corpus_hash"], meta, path)
        record = json.loads(path.read_text(encoding="utf-8"))
        spent += record["cost_guard"]["spent_usd"]
        result = record.get("result") or {}
        print(f"#{row['id']:2} {row['name']}: {result.get('verdict')} {result.get('taxonomy_code') or result.get('reason_code') or ''} "
              f"${record['cost_guard']['spent_usd']:.4f} (total ${spent:.4f})", flush=True)
        if record.get("error"):
            print(f"STOP: run ended without a verdict: {record['error']}", flush=True)
            break
        consecutive_infra = consecutive_infra + 1 if result.get("verdict") == "INFRA_ERROR" else 0
        if consecutive_infra >= CIRCUIT_BREAKER:
            print(f"STOP: circuit breaker — {consecutive_infra} consecutive INFRA_ERROR verdicts", flush=True)
            break
    return load_records(odir)


def _run_live(corpus: str, name: str, corpus_hash: str, meta: dict, path: Path) -> None:
    subprocess.run(
        [str(PYTHON), str(ROOT / "scripts" / "live_run.py"),
         "--corpus", str(corpus_dir(corpus) / "corpus.yaml"), "--name", name,
         "--cost-cap-usd", str(PER_ENTRY_CAP_USD), "--corpus-hash", corpus_hash,
         "--batch-meta", json.dumps(meta), "--out", str(path)],
        cwd=ROOT,
        check=False,
    )


def run_smoke() -> dict:
    spec = importlib.util.spec_from_file_location("smoke_upload", ROOT / "scripts" / "smoke_upload.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.smoke()


def load_records(odir: Path) -> list[dict]:
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(odir.glob("[0-9][0-9]_*.json"))]


def summarize(records: list[dict]) -> dict:
    """PURE: the per-entry table for all records and the headline numbers
    over PRIMARY entries only (corpus-v1 amendment 1; all corpus-v2 entries
    are PRIMARY). INFRA_ERROR / INVALID_HARNESS / PIPELINE_ERROR are RERUN's
    fault: reported, never counted as failed-as-published."""
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
    our_fault = ("INFRA_ERROR", "INVALID_HARNESS", "UPLOAD_TOO_LARGE")
    primary = [row for row in rows if row["category"] == "PRIMARY"]
    measured = [row for row in primary if row["verdict"] not in our_fault
                and not (row["reason_code"] or "").startswith("PIPELINE_ERROR")]
    failed = [row for row in measured if row["baseline"] == "FAILS"]
    recovered = [row for row in failed if row["verdict"] == "RUNS_AFTER_REPAIR"]
    blocked: dict[str, int] = {}
    for row in measured:
        if row["verdict"] == "BLOCKED":
            blocked[row["taxonomy_code"] or "unknown"] = blocked.get(row["taxonomy_code"] or "unknown", 0) + 1
    verdicts: dict[str, int] = {}
    for row in primary:
        verdicts[row["verdict"] or "none"] = verdicts.get(row["verdict"] or "none", 0) + 1
    return {
        "n_records": len(rows),
        "primary": {
            "n": len(primary),
            "n_measured": len(measured),
            "failed_as_published": len(failed),
            "ran_as_published": sum(1 for row in measured if row["baseline"] == "RUNS_CLEAN"),
            "runs_after_repair": len(recovered),
            "blocked_by_reason": dict(sorted(blocked.items())),
            "invalid_harness": sum(1 for row in primary if row["verdict"] == "INVALID_HARNESS"),
            "infra_error": sum(1 for row in primary if row["verdict"] == "INFRA_ERROR"),
            "upload_too_large": sum(1 for row in primary if row["verdict"] == "UPLOAD_TOO_LARGE"),
            "pipeline_error": sum(1 for row in primary if (row["reason_code"] or "").startswith("PIPELINE_ERROR")),
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
    parser.add_argument("--corpus", choices=("corpus-v1", "corpus-v2"), required=True)
    parser.add_argument("--harness-tag", default=DEFAULT_HARNESS_TAG)
    parser.add_argument("--summarize-only", action="store_true", help="skip preflight/runs; summarize existing records")
    args = parser.parse_args(argv)
    odir = out_dir(args.corpus, args.harness_tag)
    if not args.summarize_only:
        try:
            frozen = preflight(args.corpus, args.harness_tag)
        except PreflightError as exc:
            print(f"REFUSING TO START: {exc}", file=sys.stderr)
            return 2
        print(f"preflight OK: {frozen}", flush=True)
        # harness-v1.2: every batch starts with the live upload smoke test
        # (small + ~150 MB archive through the real client); no pass, no batch.
        smoke = run_smoke()
        odir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        (odir / f"smoke_{stamp}.json").write_text(json.dumps(smoke, indent=2) + "\n", encoding="utf-8", newline="\n")
        if not smoke.get("ok"):
            print(f"REFUSING TO START: pre-batch upload smoke test failed: {[r.get('error') for r in smoke['runs']]}", file=sys.stderr)
            return 3
        print("upload smoke test OK: " + ", ".join(f"{r['archive_bytes'] / 1e6:.1f} MB in {r['seconds']} s" for r in smoke["runs"]), flush=True)
        run_batch(frozen)
    summary = summarize(load_records(odir))
    odir.mkdir(parents=True, exist_ok=True)
    (odir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({k: v for k, v in summary.items() if k != "rows"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
