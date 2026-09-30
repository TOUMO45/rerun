"""Offline check of the v1.3.3 batch dependency scan against the real corpus-v2 repositories (no sandbox, no model).

    PYTHONPATH=backend python scripts/dep_scan_check.py --cache <dir> --out reports/corpus-v2.1/v1.3.3/dep_scan_d1.json

For each corpus-v2 entry: clone the pinned commit (GitHub only), scan the whole tree, build the batch install set,
and compare it with what the v1.3.2 records show one-at-a-time repair meeting: every `No module named 'X'` in the
CONTROL and TREATMENT error chains. `covered` = X's top-level module is in the batch (as a distribution the map gives it)
or is internal; `missed` = neither. The scan never runs repository code.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "scripts"))

from app.services import dep_scan  # noqa: E402
from app.services.import_names import mapping_for  # noqa: E402
from arm_tables import load  # noqa: E402

RUNS = ROOT / "runs/corpus_v2_batch/harness-v1.3.2"
MODULE_RE = re.compile(r"No module named ['\"]([\w.\-]+)['\"]")


def _git(*args: str, cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True, timeout=300)


def fetch(url: str, sha: str, dest: Path) -> Path:
    if (dest / ".rerun_ok").exists():
        return dest
    dest.mkdir(parents=True, exist_ok=True)
    _git("init", "-q", cwd=dest)
    _git("fetch", "-q", "--depth", "1", url, sha, cwd=dest)
    _git("checkout", "-q", "FETCH_HEAD", cwd=dest)
    (dest / ".rerun_ok").write_text(sha)
    return dest


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--only", type=int, nargs="*")
    args = ap.parse_args()
    control, treatment = {r["batch"]["entry_id"]: r for r in load(RUNS / "control")}, {r["batch"]["entry_id"]: r for r in load(RUNS / "treatment")}
    strata = {e["id"]: e["stratum"] for e in json.loads((ROOT / "reports/corpus-v2.1/strata.json").read_text(encoding="utf-8"))["entries"]}
    rows = []
    for i, c in sorted(control.items()):
        if args.only and i not in args.only:
            continue
        entry = c["corpus_entry"]
        tree = fetch(entry["repo_url"], entry["commit_sha"], args.cache / entry["name"])
        scan = dep_scan.scan_repo(tree)
        declared = frozenset(c["intake"]["declared_dependencies"])
        batch = dep_scan.batch_install_set(scan, declared)
        met = []
        for arm in (c, treatment.get(i)):
            for link in (arm or {}).get("result", {}).get("error_chain", []):
                m = MODULE_RE.search(link["error"])
                if m and m.group(1).split(".")[0] not in met:
                    met.append(m.group(1).split(".")[0])
        covered, missed = [], []
        for module in met:
            dist = (mapping_for(module).distribution if mapping_for(module) else module)
            if (dist in batch.names or module in batch.names or module.lower() in scan.internal
                    or any(n.startswith(module + ".") for n in batch.names)):  # namespace roots: ruamel -> ruamel.yaml
                covered.append(module)
            else:
                missed.append(module)
        rows.append({
            "id": i, "name": entry["name"], "stratum": strata.get(i), "files_scanned": scan.files_scanned, "truncated": scan.truncated,
            "batch_install": list(batch.names), "internal_excluded": list(batch.internal), "optional_skipped": list(batch.optional),
            "python2_only": list(batch.python2_only), "already_declared": list(batch.declared),
            "modules_one_at_a_time_met": met, "covered": covered, "missed": missed,
        })
        print(f"#{i} {entry['name']}: batch={len(batch.names)} internal={len(batch.internal)} met={met} missed={missed}", flush=True)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(rows, indent=1) + "\n", encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
