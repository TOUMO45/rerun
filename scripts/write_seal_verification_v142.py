"""Write seal_verification.json for harness-v1.4.2 (option B over CHANGED files only, METHODOLOGY "Seal of harness-v1.4.2").

The sandbox-touching files are sandbox.py, sandbox_limits.py, runner_env.py, smoke_exec.py and runner_hooks.py. harness-v1.4.2 changes only `runner_hooks.py` among them
(the extended CPU shim, the evidence command and its parser). So:

  - every harness-v1.4.1 entry whose code files are ALL byte-identical now (same `git hash-object`) is carried over unchanged, with its records (verified against these
    very blobs: the 11 v1.4.0 entries, the additive apt layer and the resume check);
  - an entry that lists a changed file is NOT carried: it must be re-verified by a live record of the v1.4.2 seal
    (reports/corpus-v2.1/v1.4.2/seal/run_seal_v142.py -> runs/sandbox_verification/v1.4.2-seal/), or this script stops;
  - the v1.4.2 path (the evidence command after a kill) is a new entry.

    backend/.venv/Scripts/python.exe scripts/write_seal_verification_v142.py            # after the live seal passed, before the seal commit
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from write_seal_verification import SB, blob  # noqa: E402

TAG = "harness-v1.4.2"
PREVIOUS_TAG = "harness-v1.4.1"
NEW = "runs/sandbox_verification/v1.4.2-seal"
HOOKS = "backend/app/services/runner_hooks.py"

# (id, description, code files, records). The first three replace the v1.4.1 entries of the same id (runner_hooks.py changed again in v1.4.2).
PATHS = [
    ("runner_hooks_on_a_kept_image", "the exit-site hook and the CPU shim installed as setup steps on top of a kept image; the hook prints the "
     "exit site of a sys.exit(3) inside a function (re-verified: runner_hooks.py changed in v1.4.2)",
     [SB, HOOKS], [f"{NEW}/run1_C_runner_hooks.json"]),
    ("exit_hook_gap_and_exit_wrapper", "a bare `raise SystemExit(1)` with the hook installed leaves nothing on stderr (the gap); through the exit "
     "wrapper the traceback of the raise is printed and the exit code is kept (python 3.10; re-verified)",
     [SB, HOOKS], [f"{NEW}/run1_W0_hook_alone_sees_nothing.json", f"{NEW}/run1_W1_wrapper_prints_the_raise_site.json"]),
    ("exit_wrapper_python36", "the exit wrapper on python:3.6-slim, the oldest sandbox image (re-verified)",
     [SB, HOOKS], [f"{NEW}/run1_W2_wrapper_on_python36.json"]),
    ("resource_evidence_after_a_kill", "the evidence command runs the command unchanged in a subshell, keeps its exit status and prints the sandbox's own limits and kill "
     "traces on stderr: a calm run (exit 3) and a process that SIGKILLs itself (exit 137, `Killed`, kill evidenced), both parsed by the harness's own parser",
     [SB, HOOKS], [f"{NEW}/run2_E0_calm_run_with_evidence.json", f"{NEW}/run2_E1a_self_sigkill_with_evidence.json"]),
]


def previous_entries() -> list[dict]:
    text = subprocess.run(["git", "show", f"{PREVIOUS_TAG}:seal_verification.json"], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    return json.loads(text)["paths"]


def carried_over(replaced: set[str]) -> tuple[list[dict], list[str]]:
    """The v1.4.1 entries still valid: not replaced by a v1.4.2 entry and every code file unchanged. Returns (entries, notes)."""
    kept, notes = [], []
    for entry in previous_entries():
        if entry["id"] in replaced:
            notes.append(f"{entry['id']}: replaced by a v1.4.2 verification")
            continue
        changed = [f for f, recorded in entry["code_files"].items() if blob(f) != recorded]
        if changed:
            raise SystemExit(f"{entry['id']}: {changed} changed since harness-v1.4.1 and no v1.4.2 verification replaces this entry")
        for rec in entry["records"]:
            if not (ROOT / rec).is_file():
                raise SystemExit(f"{entry['id']}: its earlier record {rec} is missing")
        kept.append(entry)
        notes.append(f"{entry['id']}: carried over (code files unchanged since the verification)")
    return kept, notes


def main() -> int:
    entries = []
    for pid, description, code_files, records in PATHS:
        run_ids = []
        for rel in records:
            rec = json.loads((ROOT / rel).read_text(encoding="utf-8"))
            if not rec.get("ok") or not rec.get("run_id"):
                raise SystemExit(f"{rel}: not a passing live record (ok={rec.get('ok')}, run_id={rec.get('run_id')})")
            # The live run recorded the blobs of the files it ran against; an edit between the run and now invalidates it (same rule as a carried-over entry).
            recorded = rec.get("code_blobs") or {}
            for f in code_files:
                if f not in recorded:
                    raise SystemExit(f"{rel}: the record carries no blob for {f}: it cannot show the file is the one the live run used")
                if recorded[f] != blob(f):
                    raise SystemExit(f"{rel}: {f} changed after its live run (record {recorded[f][:10]}, file now {blob(f)[:10]}): the verification is stale")
            run_ids.append(rec["run_id"])
        entries.append({"id": pid, "description": description, "live_nebius": True, "code_files": {f: blob(f) for f in code_files},
                        "records": list(records), "run_ids": run_ids})
    kept, notes = carried_over({e["id"] for e in entries})
    out = {"harness_tag": TAG, "written_at": datetime.now(timezone.utc).isoformat(),
           "rule": "option B over changed files only (METHODOLOGY, harness-v1.4.2): an entry whose code files are unchanged since its live verification "
                   "is carried over; an entry that lists a changed file is re-verified by a live record or the writer stops; a WSL dry run is a "
                   "smoke test, not verification; a code file changed after its verification invalidates the entry",
           "carried_over_from": PREVIOUS_TAG,
           "paths": [*kept, *entries]}
    (ROOT / "seal_verification.json").write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8", newline="\n")
    print("\n".join(notes))
    print(f"seal_verification.json: {len(out['paths'])} paths ({len(kept)} carried over, {len(entries)} verified for v1.4.2), "
          f"{sum(len(e['run_ids']) for e in out['paths'])} live run ids")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
