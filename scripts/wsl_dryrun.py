"""Local dry-run stand-in for sandbox.run_build_and_execute (standing rule,
2026-09-29: every script that runs on Nebius gets a local WSL dry run first).

Same signature and result type as the real runner. It builds the upload with
the REAL `sandbox.build_upload_archive`, then — on WSL's own Linux filesystem
(NTFS can't hold exec bits) — runs the REAL `sandbox.EXTRACT_COMMAND`
(extract, delete the archive, manifest check) followed by the install and
execute commands under `sh`. Only the transport differs: a local copy instead
of the Nebius API. A failed manifest check raises UploadIntegrityError exactly
as the real runner does.
"""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

WSL_DISTRO = "kali-linux"


def _wsl_path(windows_path: Path) -> str:
    out = subprocess.run(["wsl.exe", "-d", WSL_DISTRO, "--", "wslpath", "-a", str(windows_path).replace("\\", "/")],
                         capture_output=True, text=True, timeout=60)
    return out.stdout.strip()


def run_build_and_execute(
    *,
    api_key: str = "",
    project_id: str = "",
    base_image: str,
    install_commands,
    execute_command: str,
    wall_clock_seconds: float,
    upload_files=None,
    file_modes=None,
    download_source=None,  # accepted for signature parity; a dry run never fetches (the source is local)
    torch_setup=None,  # accepted for parity; Kali's pip is externally managed, torch is verified live (runs/torch_check/)
):
    from app.services import sandbox

    archive = sandbox.build_upload_archive(upload_files, file_modes)[0] if upload_files else None
    if archive is not None and sandbox.UPLOAD_CAP_BYTES is not None and len(archive) > sandbox.UPLOAD_CAP_BYTES:
        raise sandbox.UploadTooLargeError(len(archive), sandbox.UPLOAD_CAP_BYTES)
    host = Path(os.environ.get("TEMP", "/tmp")) / f"rerun_dryrun_{os.getpid()}.tar"
    started = time.monotonic()
    host.write_bytes(archive or b"")
    upload_seconds = round(time.monotonic() - started, 2)
    steps = [c for c in [*install_commands, execute_command] if c]
    extract = "{ " + sandbox.EXTRACT_COMMAND + "; } || exit $?; " if archive is not None else ""
    script = (
        'set -e; D=$(mktemp -d); cp "$SRC" "$D/' + sandbox.UPLOAD_ARCHIVE + '"; cd "$D"; '
        # A newline before ")" so a trailing `# comment` in a step cannot swallow the closing parenthesis.
        + extract + " && ".join("( " + c + "\n)" for c in steps) + '; rc=$?; cd /; rm -rf "$D"; exit $rc'
    )
    t0 = time.monotonic()
    try:
        out = subprocess.run(
            ["wsl.exe", "-d", WSL_DISTRO, "--exec", "env", f"SRC={_wsl_path(host)}", "sh", "-c", script],
            capture_output=True, text=True, timeout=wall_clock_seconds,
        )
    finally:
        host.unlink(missing_ok=True)
    elapsed = time.monotonic() - t0
    if archive is not None and out.returncode == sandbox.UPLOAD_MISMATCH_EXIT and "RERUN_UPLOAD_MISMATCH" in out.stderr:
        raise sandbox.UploadIntegrityError(f"post-extraction check failed (exit code {out.returncode})", stderr=out.stderr)
    stdout = "\n".join(line for line in out.stdout.splitlines() if not line.startswith("RERUN_UPLOAD_VERIFIED"))
    return sandbox.SandboxRunResult(
        steps=(sandbox.StepResult(execute_command, out.returncode, stdout, out.stderr, elapsed, 0.0),),
        sandbox_id="wsl-dry-run",
        upload_seconds=upload_seconds,
        extract_seconds=None,
    )
