"""Write seal_verification.json for harness-v1.4.3 (option B over CHANGED files, METHODOLOGY "Seal of harness-v1.4.3").

The sandbox-touching files are sandbox.py, sandbox_limits.py, runner_env.py, smoke_exec.py and runner_hooks.py. harness-v1.4.3 changes `sandbox.py` (D-41 output limit and stream flags,
D-42 `run_on_image`). EVERY entry of the harness-v1.4.2 seal lists sandbox.py, so none is carried over: each is re-verified by a live record of this seal
(reports/corpus-v2.1/v1.4.3/seal/run_seal_v143.py -> runs/sandbox_verification/v1.4.3-seal/<stage>/), the entry keeps its id and description and its records are the same checks re-run,
and two entries are new (the raised output limit and the truncation flag; `run_on_image`).

The writer stops unless: SEAL_RUN.json says every stage ran and passed against the blobs the five sandbox-touching files have NOW (an edit between the live seal and this writer would
otherwise be accepted), every listed record exists, passed and has a run id, and a record that carries `code_blobs` carries the current ones.

    backend/.venv/Scripts/python.exe scripts/write_seal_verification_v143.py            # after the live seal passed, before the seal commit
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from write_seal_verification import SB, blob, extra_checks, path_checks  # noqa: E402

TAG = "harness-v1.4.3"
PREVIOUS_TAG = "harness-v1.4.2"
NEW = "runs/sandbox_verification/v1.4.3-seal"
STAGES = ("new", "v141", "v142", "v140", "final")
SANDBOX_FILES = ("backend/app/services/sandbox.py", "backend/app/services/sandbox_limits.py", "backend/app/services/runner_env.py",
                 "backend/app/services/smoke_exec.py", "backend/app/services/runner_hooks.py")
# where each earlier seal's records were re-run
MOVED = {"runs/sandbox_verification/final-v1.4.0/": f"{NEW}/final/", "runs/sandbox_verification/v1.4.0-seal/": f"{NEW}/v140/",
         "runs/sandbox_verification/v1.4.1-seal/": f"{NEW}/v141/", "runs/sandbox_verification/v1.4.2-seal/": f"{NEW}/v142/"}

NEW_PATHS = [
    ("output_limit_raised_and_truncation_flag_read", "a failing command that writes 200,000 bytes on stderr gets the whole stream back with the API's `truncated` flag false and its size and "
     "hash recorded; one that writes 5 MiB gets exactly the 4 MiB limit the client asked for, with the flag true and its last line NOT returned, and the harness labels it OUTPUT_TRUNCATED; a stream whose cut falls inside a multi-byte character comes back without an exception, the half character replaced (D-41)",
     [SB], [f"{NEW}/new/S1_200kb_stderr_whole.json", f"{NEW}/new/S2_stream_over_the_limit_flagged.json", f"{NEW}/new/S2b_cut_inside_a_multibyte_character.json"]),
    ("run_on_image_for_the_sustained_run", "`run_on_image` reopens a kept image by its id and runs one command once, disposable; given a 3 s limit for a 20 s command the record shows the stop path "
     "the API took (the server's result with `timed_out`, or the client's wait) (D-42)",
     [SB], [f"{NEW}/new/S3_run_on_image_reopens_a_kept_image.json", f"{NEW}/new/S4_run_on_image_stopped_at_its_limit.json"]),
]


HARNESS_PATHS = ("backend/app", "backend/pyproject.toml", "scripts", "frontend/src", ".gitattributes")
RC_TAG = "harness-v1.4.3-rc"


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()


def previous_entries() -> list[dict]:
    text = subprocess.run(["git", "show", f"{PREVIOUS_TAG}:seal_verification.json"], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    return json.loads(text)["paths"]


def moved(rel: str) -> str:
    for old, new in MOVED.items():
        if rel.startswith(old):
            return new + rel[len(old):]
    raise SystemExit(f"{rel}: not a record of an earlier seal this writer knows how to map")


def records_of(entry: dict) -> list[str]:
    """The v1.4.3 records of an earlier entry: the same checks, re-run. The kill check lists whatever kill records the final stage needed to see both stop paths."""
    if entry["id"] == "kill_at_operation_limit":
        return sorted(f"{NEW}/final/{p.name}" for p in (ROOT / NEW / "final").glob("kill_at_operation_limit_py310*.json"))
    return [moved(r) for r in entry["records"]]


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
            raise SystemExit(f"SEAL_RUN.json: {f} changed after the live seal (ran against {str(doc.get('blobs', {}).get(f))[:10]}, file now {blobs_now[f][:10]}): the verification is stale")
    return doc


def check_release_candidate(run: dict, git=None) -> None:
    """The live seal ran against the tag harness-v1.4.3-rc, and the harness paths are still exactly that tag's (data commits since are fine). The blob check above covers the five
    sandbox-touching files; this covers every other harness file the seal's claims rest on."""
    git = git or _git
    try:
        rc = git("rev-parse", "--verify", f"refs/tags/{RC_TAG}^{{commit}}")
    except subprocess.CalledProcessError as exc:
        raise SystemExit(f"the tag {RC_TAG} does not exist") from exc
    if run.get("rc_commit") != rc:
        raise SystemExit(f"SEAL_RUN.json ran against {str(run.get('rc_commit'))[:10]}, the tag {RC_TAG} is {rc[:10]}")
    changed = git("diff", "--name-only", RC_TAG, "HEAD", "--", *HARNESS_PATHS)
    if changed:
        raise SystemExit(f"the harness paths differ from {RC_TAG}: {changed.splitlines()[:5]}")


def main() -> int:
    blobs_now = {f: blob(f) for f in SANDBOX_FILES}
    run = seal_run(blobs_now)
    check_release_candidate(run)
    plan = [(e["id"], e["description"], list(e["code_files"]), records_of(e)) for e in previous_entries()] + NEW_PATHS
    entries = []
    for pid, description, code_files, records in plan:
        if not records:
            raise SystemExit(f"{pid}: no v1.4.3 record")
        run_ids, loaded = [], []
        for rel in records:
            if not (ROOT / rel).is_file():
                raise SystemExit(f"{pid}: record {rel} is missing")
            rec = json.loads((ROOT / rel).read_text(encoding="utf-8"))
            loaded.append(rec)
            if not rec.get("ok") or not rec.get("run_id"):
                raise SystemExit(f"{rel}: not a passing live record (ok={rec.get('ok')}, run_id={rec.get('run_id')})")
            for f, recorded in (rec.get("code_blobs") or {}).items():
                if recorded != blobs_now.get(f, recorded):
                    raise SystemExit(f"{rel}: {f} changed after its live run (record {recorded[:10]}, file now {blobs_now[f][:10]}): the verification is stale")
            extra_checks(pid, rec)
            run_ids.append(rec["run_id"])
        path_checks(pid, loaded)
        entries.append({"id": pid, "description": description, "live_nebius": True, "code_files": {f: blob(f) for f in code_files}, "records": list(records), "run_ids": run_ids})
    out = {"harness_tag": TAG, "written_at": datetime.now(timezone.utc).isoformat(),
           "rule": "option B over changed files (METHODOLOGY, harness-v1.4.3): sandbox.py changed and every entry lists it, so every entry is re-verified by a live record of this seal; a WSL dry run is a "
                   "smoke test, not verification; a code file changed after its verification invalidates the entry",
           "reverified_from": PREVIOUS_TAG, "seal_run": {"head": run.get("head"), "rc_commit": run.get("rc_commit"), "started_at": run.get("started_at"),
                                                         "stage_costs_usd": {s: run["stages"][s]["cost_usd"] for s in STAGES}},
           "paths": entries}
    (ROOT / "seal_verification.json").write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"seal_verification.json: {len(entries)} paths ({len(entries) - len(NEW_PATHS)} re-verified, {len(NEW_PATHS)} new), {sum(len(e['run_ids']) for e in entries)} live run ids")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
