"""Write seal_verification.json for harness-v1.7.0 (option B over CHANGED files, METHODOLOGY "harness-v1.7 — PRE-REGISTRATION").

`runner_hooks.py` and `runner_env.py` changed among the five sandbox-touching files. The entries of the harness-v1.6.0 seal (= harness-v1.5.1's) that list one of them are
re-verified by the live records of run_seal_v17.py: the four that list runner_hooks.py by its `v142` stage, the four that list runner_env.py by its `runner_env` stage (an entry
listing both would need both; none does). The other entries are carried over UNCHANGED, only if every code file they list still has the blob they were verified against. Four
new entries cover the v1.7 paths (stage `v17`: N1-N4).

The writer stops unless SEAL_RUN.json says every stage ran and passed against the blobs the five files have NOW, the harness paths are the release candidate's, every listed
record exists, passed, has a run id and, for a re-verified or new entry, carries the current blobs of the changed files.

    backend/.venv/Scripts/python.exe reports/corpus-v2.1/v1.7/seal/write_seal_verification_v17.py      # after the live seal passed, before the tag
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

TAG = "harness-v1.7.0"
PREVIOUS_TAG = "harness-v1.6.0"
RC_TAG = "harness-v1.7.0-rc"
NEW = "runs/sandbox_verification/v1.7-seal"
HOOKS = "backend/app/services/runner_hooks.py"
ENV = "backend/app/services/runner_env.py"
SANDBOX = "backend/app/services/sandbox.py"
CHANGED = (HOOKS, ENV)
SANDBOX_FILES = (SANDBOX, "backend/app/services/sandbox_limits.py", ENV, "backend/app/services/smoke_exec.py", HOOKS)
HARNESS_PATHS = ("backend/app", "backend/pyproject.toml", "scripts", "frontend/src", ".gitattributes")
STAGES = ("v142", "runner_env", "v17")
NEW_ENTRIES = (
    ("cpu_reference_lu_and_memory_hook", "python:3.10-slim + the runner's CPU torch + the CPU shim and the memory hook, under the memory environment: torch.lu(pivot=False) "
     "answered by the reference kernel, a DataLoader(num_workers=2, pin_memory=True) run with 0 workers and no pinning (harness-v1.7 R1 c, R2)",
     (SANDBOX, HOOKS, ENV), ("N1_cpu_reference_lu_and_memory_hook.json",)),
    ("data_prep_launcher_py36", "python:3.6-slim: the data-preparation launcher runs a README-documented script under its caps; the documented command finds the output (R3)",
     (SANDBOX, HOOKS), ("N2_data_prep_launcher_py36.json",)),
    ("apt_archive_build_essential_py36", "python:3.6-slim (bullseye): the apt-archive step, then apt-get install -y build-essential succeeds and gcc runs (R4)",
     (SANDBOX, ENV), ("N3_apt_archive_build_essential_py36.json",)),
    ("companion_swap_installs", "python:3.7-slim: the runner's torch install with the companion swap (torch==1.2.0 kept, torchvision 0.5.0 -> 0.4.0) installs and imports (R5)",
     (SANDBOX, ENV), ("N4_companion_torch_1_2_0_torchvision_0_4_0.json",)),
)


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()


def previous_entries() -> list[dict]:
    return json.loads(_git("show", f"{PREVIOUS_TAG}:seal_verification.json"))["paths"]


def reverified_records(entry: dict) -> list[str]:
    """The v1.7 record of each earlier record of an entry that lists a changed file: the same check, the same file name, in this seal's stage for that file."""
    lists = [f for f in CHANGED if f in entry["code_files"]]
    if len(lists) != 1:
        raise SystemExit(f"{entry['id']}: lists {lists}; this writer re-verifies an entry that lists exactly one changed file")
    stage = "v142" if lists[0] == HOOKS else "runner_env"
    out = []
    for rel in entry["records"]:
        expected_dir = "/v142/" if stage == "v142" else "/final/"
        if expected_dir not in rel:
            raise SystemExit(f"{entry['id']}: record {rel} is not from the stage this writer re-runs for {lists[0]}")
        out.append(f"{NEW}/{stage}/{rel.rsplit('/', 1)[1]}")
    return out


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
    if run.get("rc_commit") != rc:
        raise SystemExit(f"SEAL_RUN.json ran against {str(run.get('rc_commit'))[:10]}, the tag {RC_TAG} is {rc[:10]}")
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
        records = reverified_records(entry) if lists_changed else list(entry["records"])
        for f, recorded in entry["code_files"].items():
            if f not in CHANGED and blobs_now[f] != recorded:
                raise SystemExit(f"{pid}: {f} changed since its verification in the {PREVIOUS_TAG} seal: it cannot be carried over")
        loaded = [_load(pid, rel, live_files=tuple(f for f in CHANGED if f in entry["code_files"]) if lists_changed else (), blobs_now=blobs_now) for rel in records]
        path_checks(pid, loaded)
        entries.append({"id": pid, "description": entry["description"], "live_nebius": True, "code_files": {f: blob(f) for f in entry["code_files"]},
                        "records": records, "run_ids": [r["run_id"] for r in loaded]})
        reverified += lists_changed
        carried += not lists_changed
    for pid, description, files, names in NEW_ENTRIES:
        records = [f"{NEW}/v17/{name}" for name in names]
        loaded = [_load(pid, rel, live_files=tuple(f for f in CHANGED if f in files), blobs_now=blobs_now) for rel in records]
        entries.append({"id": pid, "description": description, "live_nebius": True, "code_files": {f: blob(f) for f in files},
                        "records": records, "run_ids": [r["run_id"] for r in loaded]})
    out = {"harness_tag": TAG, "written_at": datetime.now(timezone.utc).isoformat(),
           "rule": "option B over changed files (METHODOLOGY, harness-v1.7 pre-registration): runner_hooks.py and runner_env.py changed, so every entry that lists one of "
                   "them is re-verified by a live record of this seal, and the v1.7 paths have their own live records; an entry whose code files are all unchanged is "
                   "carried over with its records; a code file changed after its verification invalidates the entry",
           "reverified_from": PREVIOUS_TAG,
           "seal_run": {"head": run.get("head"), "rc_commit": run.get("rc_commit"), "started_at": run.get("started_at"),
                        "stage_costs_usd": {s: run["stages"][s]["cost_usd"] for s in STAGES}},
           "paths": entries}
    (ROOT / "seal_verification.json").write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"seal_verification.json: {len(entries)} paths ({reverified} re-verified live, {carried} carried over, {len(NEW_ENTRIES)} new), "
          f"{sum(len(e['run_ids']) for e in entries)} live run ids")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
