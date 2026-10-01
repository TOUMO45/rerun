"""Write seal_verification.json for harness-v1.4.0 (option B, METHODOLOGY "Seal of harness-v1.4.0"): the harness-v1.3.4 checks the four
gate entries exercise, repeated live (scripts/run_seal_verification_v140.py -> runs/sandbox_verification/final-v1.4.0/), and the new
checkpoint / runner-hook checks (reports/corpus-v2.1/v1.4.0/seal/run_seal_v140.py -> runs/sandbox_verification/v1.4.0-seal/).

  backend/.venv/Scripts/python.exe scripts/write_seal_verification_v140.py      # after both runners passed, before the seal commit
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from write_seal_verification import SB, LIM, ENV, SMOKE, blob, extra_checks, path_checks  # noqa: E402

TAG = "harness-v1.4.0"
FINAL = "runs/sandbox_verification/final-v1.4.0"
NEW = "runs/sandbox_verification/v1.4.0-seal"
HOOKS = "backend/app/services/runner_hooks.py"


def _kill_records() -> list[str]:
    return sorted(f"{FINAL}/{p.name}" for p in (ROOT / FINAL).glob("kill_at_operation_limit_py310*.json"))


PATHS = [
    ("download_route_git", "in-sandbox download (git) of corpus-v2 entry 8's own repository (143 MB) + manifest verify",
     [SB, LIM], [f"{FINAL}/download_git_entry8_py310.json"]),
    ("archive_upload_route_exec_bit_verify", "the normal one-tar upload + extraction + manifest verify (exec-bit comparison) + modes",
     [SB], [f"{FINAL}/upload_archive_exec_bit_py36.json"]),
    ("runner_torch_execstack_fix", "runner torch install + patchelf + import, python 3.6 old pin (entry 3's era torch)",
     [SB, LIM, ENV], [f"{FINAL}/torch_py36_pin1.10.2.json"]),
    ("runner_torch_matched_family", "an undeclared `import torchvision` gets the matched torch family (entries 8 and 11 baselines)",
     [SB, ENV], [f"{FINAL}/torch_py310_imports_torchvision.json"]),
    ("runner_numpy_cap_old_torch", "torch < 2.3 with numpy<2 on Python 3.9 (entry 11's era torch)",
     [SB, ENV], [f"{FINAL}/torch_py39_pin1.8.1_numpy_cap.json"]),
    ("runner_setup_phase_tag_on_failure", "a failing runner op is tagged phase=runner_setup and no repo command runs",
     [SB, ENV], [f"{FINAL}/phase_runner_setup_failure_py310.json"]),
    ("kill_at_operation_limit", "a step stopped at its operation limit, through both stop paths",
     [SB], None),
    ("smoke_launcher", "the smoke launcher on Python 3.10 and 3.6 (its own exit now silent for the exit-site hook)",
     [SB, SMOKE], [f"{FINAL}/{n}" for n in ("smoke_alive_py310.json", "smoke_exits_ok_py310.json", "smoke_fails_py310.json",
                                            "smoke_silent_py310.json", "smoke_alive_py36.json", "smoke_fails_py36.json")]),
    # --- new in harness-v1.4.0 ---
    ("checkpoint_layers_and_branch_run", "a checkpoint keeps the tree and setup layers; a later operation reopens the deepest layer by id, runs "
     "no setup step again, applies the branch overlay and runs the command; its result image is kept",
     [SB, LIM], [f"{NEW}/run1_A_ready_image.json", f"{NEW}/run1_B_branch_run.json"]),
    ("runner_hooks_on_a_kept_image", "the exit-site hook and the CPU shim installed as setup steps on top of a kept image; the hook prints the "
     "exit site of a sys.exit(3) inside a function",
     [SB, HOOKS], [f"{NEW}/run1_C_runner_hooks.json"]),
    ("kept_image_reopened_later", "a kept result image reopened after a wait still holds the patched tree",
     [SB], [f"{NEW}/run1_D_reopen_kept_image.json"]),
    ("checkpoint_real_entry", "corpus-v2 entry 7's recorded environment built as a checkpoint, then reopen + apply + execute from its deepest "
     "kept layer (only the setup steps the layer lacks run again)",
     [SB, LIM, SMOKE], [f"{NEW}/run2_E_entry07_checkpoint.json", f"{NEW}/run2_F_reopen_apply_execute.json"]),
]


def main() -> int:
    entries = []
    for pid, description, code_files, records in PATHS:
        records = records if records is not None else _kill_records()
        run_ids, loaded = [], []
        for rel in records:
            rec = json.loads((ROOT / rel).read_text(encoding="utf-8"))
            loaded.append(rec)
            if not rec.get("ok") or not rec.get("run_id"):
                raise SystemExit(f"{rel}: not a passing live record (ok={rec.get('ok')}, run_id={rec.get('run_id')})")
            extra_checks(pid, rec)
            run_ids.append(rec["run_id"])
        path_checks(pid, loaded)
        entries.append({"id": pid, "description": description, "live_nebius": True, "code_files": {f: blob(f) for f in code_files},
                        "records": list(records), "run_ids": run_ids})
    out = {"harness_tag": TAG, "written_at": datetime.now(timezone.utc).isoformat(),
           "rule": "no seal without one real Nebius execution per sandbox-touching path the gate uses (option B, METHODOLOGY, harness-v1.4.0); "
                   "a WSL dry run is a smoke test, not verification; a code file changed after its verification invalidates the entry",
           "paths": entries}
    (ROOT / "seal_verification.json").write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"seal_verification.json: {len(entries)} paths, {sum(len(e['run_ids']) for e in entries)} live run ids")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
