"""Write seal_verification.json for harness-v1.5.1 (option B over CHANGED files, METHODOLOGY "harness-v1.5 dev/test protocol").

Only `runner_hooks.py` changed among the five sandbox-touching files (F3). The entries of the harness-v1.4.3 seal that list it (four) are re-verified by the live records of
reports/corpus-v2.1/v1.5/seal/run_seal_v151.py (runs/sandbox_verification/v1.5.1-seal/v142/); the other fifteen are carried over UNCHANGED, and only if every code file they list
still has the blob they were verified against (an edit to sandbox.py, say, would make the writer stop).

The writer stops unless: SEAL_RUN.json says the stage ran and passed against the blobs the five files have NOW, the harness paths are the release candidate's, every listed record
exists, passed and has a run id, and a record that carries `code_blobs` carries the current ones.

    backend/.venv/Scripts/python.exe reports/corpus-v2.1/v1.5/seal/write_seal_verification_v151.py      # after the live seal passed, before the seal commit
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "scripts"))
from write_seal_verification import blob, extra_checks, path_checks  # noqa: E402

TAG = "harness-v1.5.1"
PREVIOUS_TAG = "harness-v1.4.3"
RC_TAG = "harness-v1.5.1-rc"
NEW = "runs/sandbox_verification/v1.5.1-seal"
OLD = "runs/sandbox_verification/v1.4.3-seal"
CHANGED_FILE = "backend/app/services/runner_hooks.py"
SANDBOX_FILES = ("backend/app/services/sandbox.py", "backend/app/services/sandbox_limits.py", "backend/app/services/runner_env.py",
                 "backend/app/services/smoke_exec.py", CHANGED_FILE)
HARNESS_PATHS = ("backend/app", "backend/pyproject.toml", "scripts", "frontend/src", ".gitattributes")


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()


def previous_entries() -> list[dict]:
    return json.loads(_git("show", f"{PREVIOUS_TAG}:seal_verification.json"))["paths"]


def reverified_records(entry: dict) -> list[str]:
    """The v1.5.1 record of each v1.4.3 record of an entry that lists the changed file: the same check, the same file name, in this seal's v142 stage."""
    out = []
    for rel in entry["records"]:
        if not rel.startswith(f"{OLD}/v142/"):
            raise SystemExit(f"{entry['id']}: record {rel} is not a v1.4.3 `v142` stage record, so this writer does not know how to re-verify it")
        out.append(f"{NEW}/v142/{rel.rsplit('/', 1)[1]}")
    return out


def seal_run(blobs_now: dict) -> dict:
    path = ROOT / NEW / "SEAL_RUN.json"
    if not path.is_file():
        raise SystemExit(f"{NEW}/SEAL_RUN.json is missing: the live seal did not run (or did not finish)")
    doc = json.loads(path.read_text(encoding="utf-8"))
    if not doc.get("stages", {}).get("v142", {}).get("ok"):
        raise SystemExit("SEAL_RUN.json: stage v142 is missing or did not pass")
    for f in SANDBOX_FILES:
        if doc.get("blobs", {}).get(f) != blobs_now[f]:
            raise SystemExit(f"SEAL_RUN.json: {f} changed after the live seal (ran against {str(doc.get('blobs', {}).get(f))[:10]}, file now {blobs_now[f][:10]}): the verification is stale")
    return doc


def check_release_candidate(run: dict) -> None:
    try:
        rc = _git("rev-parse", "--verify", f"refs/tags/{RC_TAG}^{{commit}}")
    except subprocess.CalledProcessError as exc:
        raise SystemExit(f"the tag {RC_TAG} does not exist") from exc
    if run.get("rc_commit") != rc:
        raise SystemExit(f"SEAL_RUN.json ran against {str(run.get('rc_commit'))[:10]}, the tag {RC_TAG} is {rc[:10]}")
    changed = _git("diff", "--name-only", RC_TAG, "HEAD", "--", *HARNESS_PATHS)
    if changed:
        raise SystemExit(f"the harness paths differ from {RC_TAG}: {changed.splitlines()[:5]}")


def main() -> int:
    blobs_now = {f: blob(f) for f in SANDBOX_FILES}
    run = seal_run(blobs_now)
    check_release_candidate(run)
    entries, reverified, carried = [], 0, 0
    for entry in previous_entries():
        pid = entry["id"]
        lists_changed = CHANGED_FILE in entry["code_files"]
        records = reverified_records(entry) if lists_changed else list(entry["records"])
        for f, recorded in entry["code_files"].items():
            if f != CHANGED_FILE and blobs_now[f] != recorded:
                raise SystemExit(f"{pid}: {f} changed since its verification in the {PREVIOUS_TAG} seal ({recorded[:10]} -> {blobs_now[f][:10]}): it cannot be carried over")
        run_ids, loaded = [], []
        for rel in records:
            if not (ROOT / rel).is_file():
                raise SystemExit(f"{pid}: record {rel} is missing")
            rec = json.loads((ROOT / rel).read_text(encoding="utf-8"))
            loaded.append(rec)
            if not rec.get("ok") or not rec.get("run_id"):
                raise SystemExit(f"{rel}: not a passing live record (ok={rec.get('ok')}, run_id={rec.get('run_id')})")
            if lists_changed:
                for f, recorded in (rec.get("code_blobs") or {}).items():
                    if recorded != blobs_now.get(f, recorded):
                        raise SystemExit(f"{rel}: {f} changed after its live run (record {recorded[:10]}, file now {blobs_now[f][:10]}): the verification is stale")
                if (rec.get("code_blobs") or {}).get(CHANGED_FILE) != blobs_now[CHANGED_FILE]:
                    raise SystemExit(f"{rel}: the record does not carry the current blob of {CHANGED_FILE}")
            extra_checks(pid, rec)
            run_ids.append(rec["run_id"])
        path_checks(pid, loaded)
        entries.append({"id": pid, "description": entry["description"], "live_nebius": True, "code_files": {f: blob(f) for f in entry["code_files"]},
                        "records": records, "run_ids": run_ids})
        reverified += lists_changed
        carried += not lists_changed
    out = {"harness_tag": TAG, "written_at": datetime.now(timezone.utc).isoformat(),
           "rule": "option B over changed files (METHODOLOGY, harness-v1.5 dev/test protocol): runner_hooks.py changed, so every entry that lists it is re-verified by a live record of this seal; "
                   "an entry whose code files are all unchanged is carried over with its records; a code file changed after its verification invalidates the entry",
           "reverified_from": PREVIOUS_TAG, "seal_run": {"head": run.get("head"), "rc_commit": run.get("rc_commit"), "started_at": run.get("started_at"),
                                                         "stage_costs_usd": {"v142": run["stages"]["v142"]["cost_usd"]}},
           "paths": entries}
    (ROOT / "seal_verification.json").write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"seal_verification.json: {len(entries)} paths ({reverified} re-verified live, {carried} carried over), {sum(len(e['run_ids']) for e in entries)} live run ids")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
