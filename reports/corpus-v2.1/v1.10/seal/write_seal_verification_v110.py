"""Write seal_verification.json for harness-v1.10.

harness-v1.10 changes one of the five sandbox-touching files (`smoke_exec.py`: the launcher can set environment variables for the command it runs) and adds a sixth
(`behaviour.py`: the tracer, a `.pth` hook). The two entries of the harness-v1.7.2 seal_verification.json that list smoke_exec.py (`smoke_launcher`, `checkpoint_real_entry`) are
re-verified by the live records of run_seal_v110.py (stages `smoke` and `v140`); the new entry `behaviour_tracer_on_kept_images` (stage `v110`) covers the tracer on three Python
versions; every other entry is carried over UNCHANGED, only if every code file it lists still has the blob it was verified against.

The writer stops unless SEAL_RUN.json says every stage ran and passed against the blobs the six files have NOW, the harness paths are the release candidate's, every listed record
exists, passed, has a run id and, for a re-verified or new entry, carries the current blobs of the changed files.

    backend/.venv/Scripts/python.exe reports/corpus-v2.1/v1.10/seal/write_seal_verification_v110.py      # after the live seal passed, before the tag
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "scripts"))
from write_seal_verification import blob, extra_checks, path_checks  # noqa: E402

TAG = os.environ.get("RERUN_V110_TAG", "harness-v1.10.0")
RC_TAG = os.environ.get("RERUN_V110_RC_TAG", "harness-v1.10.0-rc")
NEW = "runs/sandbox_verification/v1.10-seal"
SMOKE = "backend/app/services/smoke_exec.py"
BEHAVIOUR = "backend/app/services/behaviour.py"
SANDBOX = "backend/app/services/sandbox.py"
CHANGED = (SMOKE, BEHAVIOUR)
SANDBOX_FILES = (SANDBOX, "backend/app/services/sandbox_limits.py", "backend/app/services/runner_env.py", SMOKE, "backend/app/services/runner_hooks.py", BEHAVIOUR)
HARNESS_PATHS = ("backend/app", "backend/pyproject.toml", "scripts", "frontend/src", ".gitattributes")
STAGES = ("v140", "smoke", "v110")
REVERIFIED_STAGE = {"smoke_launcher": "smoke", "checkpoint_real_entry": "v140"}
NEW_ENTRIES = (
    ("behaviour_tracer_on_kept_images",
     "python:3.6-slim, 3.7-slim and 3.10-slim: the behavioural tracer installed by its real installer (a .pth hook) and the command run under the smoke launcher with RERUN_BEHAVIOUR=1: a program that "
     "ends writes one report; a program still running at the launcher's limit is stopped with SIGTERM and still writes its report; an exit from a line a patch added is named; the tracer is inert "
     "without the variable; a report line printed by the repository (wrong nonce) is taken out and counted as nothing (harness-v1.10)",
     (SANDBOX, SMOKE, BEHAVIOUR)),
)


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()


def previous_entries() -> list[dict]:
    return json.loads((ROOT / "seal_verification.json").read_text(encoding="utf-8"))["paths"]


def reverified_records(entry: dict) -> list[str]:
    stage = REVERIFIED_STAGE[entry["id"]]
    return [f"{NEW}/{stage}/{rel.rsplit('/', 1)[1]}" for rel in entry["records"]]


def seal_run(blobs_now: dict) -> dict:
    path = ROOT / NEW / "SEAL_RUN.json"
    if not path.is_file():
        raise SystemExit(f"{NEW}/SEAL_RUN.json is missing: the live seal did not run (or did not finish)")
    doc = json.loads(path.read_text(encoding="utf-8"))
    for stage in STAGES:
        if not doc.get("stages", {}).get(stage, {}).get("ok"):
            raise SystemExit(f"SEAL_RUN.json: stage {stage} is missing or did not pass")
    for f in SANDBOX_FILES:
        if doc.get("blobs", {}).get(f) != blobs_now[f]:
            raise SystemExit(f"SEAL_RUN.json: {f} changed after the live seal: the verification is stale")
    return doc


def check_release_candidate(run: dict) -> None:
    try:
        rc = _git("rev-parse", "--verify", f"refs/tags/{RC_TAG}^{{commit}}")
    except subprocess.CalledProcessError as exc:
        raise SystemExit(f"the tag {RC_TAG} does not exist") from exc
    try:
        recorded = _git("rev-parse", "--verify", f"{run.get('rc_commit')}^{{commit}}")
    except subprocess.CalledProcessError as exc:
        raise SystemExit(f"SEAL_RUN.json names {str(run.get('rc_commit'))[:10]}, which is not a commit or tag object of this repository") from exc
    if recorded != rc:
        raise SystemExit(f"SEAL_RUN.json ran against {recorded[:10]}, the tag {RC_TAG} is {rc[:10]}")
    changed = _git("diff", "--name-only", RC_TAG, "HEAD", "--", *HARNESS_PATHS)
    if changed:
        raise SystemExit(f"the harness paths differ from {RC_TAG}: {changed.splitlines()[:5]}")


def _load(pid: str, rel: str, *, live_files: tuple[str, ...], blobs_now: dict) -> dict:
    if not (ROOT / rel).is_file():
        raise SystemExit(f"{pid}: record {rel} is missing")
    rec = json.loads((ROOT / rel).read_text(encoding="utf-8"))
    if not rec.get("ok") or not rec.get("run_id"):
        raise SystemExit(f"{rel}: not a passing live record (ok={rec.get('ok')}, run_id={rec.get('run_id')})")
    blobs = rec.get("code_blobs") or {}
    for f in live_files:
        if blobs and blobs.get(f) != blobs_now[f]:
            raise SystemExit(f"{rel}: {f} changed after its live run (the record carries {str(blobs.get(f))[:10]}, the file is {blobs_now[f][:10]})")
    extra_checks(pid, rec)
    return rec


def main() -> int:
    blobs_now = {f: blob(f) for f in SANDBOX_FILES}
    run = seal_run(blobs_now)
    check_release_candidate(run)
    entries, reverified, carried = [], 0, 0
    for entry in previous_entries():
        pid = entry["id"]
        lists_changed = any(f in entry["code_files"] for f in CHANGED)
        if lists_changed and pid not in REVERIFIED_STAGE:
            raise SystemExit(f"{pid}: lists a changed file and has no re-run stage in this seal")
        records = reverified_records(entry) if lists_changed else list(entry["records"])
        for f, recorded in entry["code_files"].items():
            if f not in CHANGED and blobs_now.get(f, blob(f)) != recorded:
                raise SystemExit(f"{pid}: {f} changed since its verification: it cannot be carried over")
        loaded = [_load(pid, rel, live_files=tuple(f for f in CHANGED if f in entry["code_files"]) if lists_changed else (), blobs_now=blobs_now) for rel in records]
        path_checks(pid, loaded)
        entries.append({"id": pid, "description": entry["description"], "live_nebius": True, "code_files": {f: blob(f) for f in entry["code_files"]},
                        "records": records, "run_ids": [r["run_id"] for r in loaded]})
        reverified += lists_changed
        carried += not lists_changed
    for pid, description, files in NEW_ENTRIES:
        records = sorted(p.relative_to(ROOT).as_posix() for p in (ROOT / NEW / "v110").glob("*.json"))
        if len(records) != 15:
            raise SystemExit(f"{pid}: expected the 15 records T1-T5 x 3 images in {NEW}/v110, found {len(records)}")
        loaded = [_load(pid, rel, live_files=CHANGED, blobs_now=blobs_now) for rel in records]
        entries.append({"id": pid, "description": description, "live_nebius": True, "code_files": {f: blob(f) for f in files}, "records": records,
                        "run_ids": [r["run_id"] for r in loaded]})
    out = {"harness_tag": TAG, "written_at": datetime.now(timezone.utc).isoformat(),
           "rule": "harness-v1.10 changes smoke_exec.py and adds behaviour.py to the sandbox-touching files: the two entries that list smoke_exec.py are re-verified by live records of "
                   "this seal, the tracer has its own live entry, and an entry whose code files are all unchanged is carried over with its records; a code file changed after its "
                   "verification invalidates the entry",
           "reverified_from": "harness-v1.7.2 (the entries carried over are the harness-v1.7.2 seal's)",
           "seal_run": {"head": run.get("head"), "rc_commit": run.get("rc_commit"), "started_at": run.get("started_at"),
                        "stage_costs_usd": {s: run["stages"][s]["cost_usd"] for s in STAGES}},
           "paths": entries}
    (ROOT / "seal_verification.json").write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"seal_verification.json: {len(entries)} paths ({reverified} re-verified live, {carried} carried over, {len(NEW_ENTRIES)} new), "
          f"{sum(len(e['run_ids']) for e in entries)} live run ids")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
