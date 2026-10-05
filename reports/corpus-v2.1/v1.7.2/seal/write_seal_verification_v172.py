"""Write seal_verification.json for harness-v1.7.2.

Rule: harness-v1.7.2 changes none of the five sandbox-touching files, and the owner asked for every live stage of the harness-v1.7.1 seal to run again at the new
release candidate. So every path of the harness-v1.7.1 seal_verification.json whose records came from the v1.7.1 seal (runs/sandbox_verification/v1.7.1-seal/...)
now points at the same check re-run by this seal (runs/sandbox_verification/v1.7.2-seal/<stage>/<same file name>); a path whose records are older (the v1.4.3 seal)
is carried over with its records. Any code file a path lists must be byte-identical to the blob it was verified with, or the writer stops: a carried-over record
is valid only for the code it ran.

    backend/.venv/Scripts/python.exe reports/corpus-v2.1/v1.7.2/seal/write_seal_verification_v172.py
"""
from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
_spec = importlib.util.spec_from_file_location("write_seal_verification_v17", ROOT / "reports" / "corpus-v2.1" / "v1.7" / "seal" / "write_seal_verification_v17.py")
v17 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(v17)

TAG = "harness-v1.7.2"
PREVIOUS_TAG = "harness-v1.7.1"
RC_TAG = "harness-v1.7.2-rc"
PREVIOUS = "runs/sandbox_verification/v1.7.1-seal"
NEW = "runs/sandbox_verification/v1.7.2-seal"

v17.PREVIOUS_TAG, v17.RC_TAG, v17.NEW = PREVIOUS_TAG, RC_TAG, NEW


def main() -> int:
    blobs_now = {f: v17.blob(f) for f in v17.SANDBOX_FILES}
    run = v17.seal_run(blobs_now)  # every stage passed, against the five files as they are now
    v17.check_release_candidate(run)  # the record ran at the rc tag, and the harness paths have not moved since
    entries, rerun, carried = [], 0, 0
    for entry in v17.previous_entries():
        pid = entry["id"]
        for f, recorded in entry["code_files"].items():
            if blobs_now.get(f, v17.blob(f)) != recorded:
                raise SystemExit(f"{pid}: {f} changed since its verification in the {PREVIOUS_TAG} seal")
        fresh = all(rel.startswith(PREVIOUS + "/") for rel in entry["records"])
        records = [NEW + rel[len(PREVIOUS):] for rel in entry["records"]] if fresh else list(entry["records"])
        loaded = [v17._load(pid, rel, live_files=tuple(entry["code_files"]) if fresh else (), blobs_now={**blobs_now, **{f: v17.blob(f) for f in entry["code_files"]}})
                  for rel in records]
        v17.path_checks(pid, loaded)
        entries.append({"id": pid, "description": entry["description"], "live_nebius": True, "code_files": dict(entry["code_files"]),
                        "records": records, "run_ids": [r["run_id"] for r in loaded]})
        rerun += fresh
        carried += not fresh
    out = {"harness_tag": TAG, "written_at": datetime.now(timezone.utc).isoformat(),
           "rule": "harness-v1.7.2 changes no sandbox-touching file; every live stage of the harness-v1.7.1 seal ran again at harness-v1.7.2-rc (owner's request), so each "
                   "path verified by the v1.7.1 seal points at its re-run here, and each path verified by an older seal is carried over; every listed code file is "
                   "byte-identical to the blob it was verified with",
           "reverified_from": PREVIOUS_TAG,
           "seal_run": {"head": run.get("head"), "rc_commit": run.get("rc_commit"), "started_at": run.get("started_at"),
                        "stage_costs_usd": {s: run["stages"][s]["cost_usd"] for s in v17.STAGES}},
           "paths": entries}
    (ROOT / "seal_verification.json").write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"seal_verification.json: {len(entries)} paths ({rerun} re-run live in this seal, {carried} carried over), "
          f"{sum(len(e['run_ids']) for e in entries)} live run ids")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
