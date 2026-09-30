"""Write seal_verification.json (seal rule; harness-v1.3.3 since 2026-09-30, v1.3.2 before): every sandbox-touching code path of the sealed harness, the
git blob of each code file it verified, and the REAL Nebius execution(s) (run ids in runs/sandbox_verification/final/)
that verified it. The batch driver's preflight refuses to start unless the file is complete and current.

A WSL dry run is a smoke test, not verification: only records whose `run_id` came from a Nebius sandbox count.

  python scripts/write_seal_verification.py            # after the final live verification runs, before the seal commit
"""
from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TAG = "harness-v1.3.3"
FINAL = "runs/sandbox_verification/final-v1.3.3"  # written by scripts/run_seal_verification_v133.py
SB, LIM, ENV = ("backend/app/services/sandbox.py", "backend/app/services/sandbox_limits.py",
                "backend/app/services/runner_env.py")
SMOKE = "backend/app/services/smoke_exec.py"

PATHS = [
    ("download_route_git", "in-sandbox download: git clone --filter=blob:none + pinned checkout + HEAD/status checks, then manifest verify (entry 2, the attempt-1 exit-97 case)",
     [SB, LIM], ["download_git_entry2_py310.json"]),
    ("download_route_tarball_fallback", "in-sandbox download where git cannot be installed (python:3.6-slim, archived apt): GitHub tarball + manifest verify",
     [SB, LIM], ["download_tarball_fallback_py36.json"]),
    ("archive_upload_route_exec_bit_verify", "the normal one-tar upload + extraction + manifest verify (exec-bit comparison) + modes",
     [SB], ["upload_archive_exec_bit_py36.json"]),
    ("runner_torch_execstack_fix", "runner torch install + patchelf (runner-owned prefix, flag verified) + import on python 3.6 / 3.8 / 3.10, old torch pins",
     [SB, LIM, ENV], ["torch_py36_pin1.10.2.json", "torch_py38_pin1.12.1.json", "torch_py310_pin1.12.1.json"]),
    ("runner_torch_matched_family", "an undeclared `import torchvision` gets torch + torchvision (+ torchaudio) as a matched set (attempt-1 entry 4)",
     [SB, ENV], ["torch_py310_imports_torchvision.json"]),
    ("runner_setup_phase_tag_on_failure", "a failing runner op is tagged phase=runner_setup by the real runner and no repo command runs",
     [SB, ENV], ["phase_runner_setup_failure_py310.json"]),
    ("patchelf_flag_absent_is_incompat", "a patchelf without --clear-execstack: exit 98 + RERUN_SANDBOX_INCOMPAT, phase runner_setup (attempt-1 entry 3 cause)",
     [SB, ENV], ["patchelf_flag_absent_incompat_py310.json"]),
    # --- new in harness-v1.3.3 ---
    ("runner_numpy_cap_old_torch", "torch < 2.3 is installed with numpy<2 in the same pip command and `import torch` works on Python 3.9 (corpus-v2 entry 11)",
     [SB, ENV], ["torch_py39_pin1.8.1_numpy_cap.json"]),
    ("kill_at_operation_limit", "a step that would run 300 s is stopped at a 25 s operation limit; SandboxTimeoutError carries the killed step's duration and the completed steps' cost",
     [SB], ["kill_at_operation_limit_py310.json", "kill_at_operation_limit_py310_extra1.json"]),
    ("smoke_launcher", "the smoke launcher: a still-running command with output passes and is stopped; a finishing command and a failing command keep exit code and output; a silent one fails; on Python 3.10 and 3.6",
     [SB, SMOKE], ["smoke_alive_py310.json", "smoke_exits_ok_py310.json", "smoke_fails_py310.json", "smoke_silent_py310.json",
                   "smoke_alive_py36.json", "smoke_fails_py36.json"]),
]


def path_checks(pid: str, recs: list[dict]) -> None:
    """Checks across all records of one path."""
    if pid == "kill_at_operation_limit":
        # The API reports a stopped step in two ways (a race, seen live on the same call): the server returns the step's result with
        # state.timed_out, or the client's wait expires first. Both branches of sandbox.py must have been seen in a real run.
        vias = {r.get("via") for r in recs}
        if vias != {"server_result_timed_out", "client_wait_timeout"}:
            raise SystemExit(f"{pid}: both stop paths must be verified live, records show {sorted(map(str, vias))}")
        server = next(r for r in recs if r.get("via") == "server_result_timed_out")
        if not (server.get("completed_cost_usd", 0) > 0 and "exit code" in server.get("message", "")):
            raise SystemExit(f"{pid}: the server-result record carries no measured cost / exit code")


def extra_checks(pid: str, rec: dict) -> None:
    """Content checks beyond `ok`, for the records whose claim is more than "it ran"."""
    if pid == "runner_numpy_cap_old_torch":
        import re

        match = re.search(r"IMPORT_OK\s+\S+\s+(\S+)\s+(\S+)", rec.get("stdout", "") or json.dumps(rec))
        if not match or not match.group(2).startswith("1."):
            raise SystemExit(f"{pid}: numpy version in the sandbox is not 1.x ({match.groups() if match else 'no IMPORT_OK line'})")
    if pid == "kill_at_operation_limit" and not (rec.get("via") in ("server_result_timed_out", "client_wait_timeout") and rec.get("run_id")
                                                 and 15 < rec.get("elapsed_seconds", 0) < 120):
        raise SystemExit(f"{pid}: stop path / id / duration not as expected: {rec.get('via')}, {rec.get('run_id')}, {rec.get('elapsed_seconds')}")



def blob(path: str) -> str:
    return subprocess.run(["git", "hash-object", path], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()


def main() -> int:
    entries = []
    for pid, description, code_files, records in PATHS:
        run_ids, loaded = [], []
        for name in records:
            rec = json.loads((ROOT / FINAL / name).read_text(encoding="utf-8"))
            loaded.append(rec)
            if not rec.get("ok") or not rec.get("run_id"):
                raise SystemExit(f"{name}: not a passing live record (ok={rec.get('ok')}, run_id={rec.get('run_id')})")
            extra_checks(pid, rec)
            run_ids.append(rec["run_id"])
        path_checks(pid, loaded)
        entries.append({"id": pid, "description": description, "live_nebius": True,
                        "code_files": {f: blob(f) for f in code_files},
                        "records": [f"{FINAL}/{n}" for n in records], "run_ids": run_ids})
    out = {"harness_tag": TAG, "written_at": datetime.now(timezone.utc).isoformat(),
           "rule": "no seal without one real Nebius execution per new sandbox-touching path; a WSL dry run is a smoke test, "
                   "not verification; a code file changed after its verification invalidates the entry",
           "paths": entries}
    (ROOT / "seal_verification.json").write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"seal_verification.json: {len(entries)} paths, {sum(len(e['run_ids']) for e in entries)} live run ids")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
