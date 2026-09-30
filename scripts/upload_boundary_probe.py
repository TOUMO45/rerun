"""Upload-cap boundary probe (harness-v1.3.1 pre-launch). One incompressible file of an
exact byte size is uploaded through the SDK's apply_files (the same call the harness
uses for its archive), then a trivial run confirms the layer is usable. Every size is
attempted, ascending; nothing stops at the first failure. Accept/reject is recorded per size.

  backend/.venv/Scripts/python.exe scripts/upload_boundary_probe.py
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
MIB = 1024 * 1024
SIZES = [("128 MB decimal", 128_000_000), ("127 MiB", 127 * MIB), ("128 MiB", 128 * MIB), ("129 MiB", 129 * MIB)]
OUT = ROOT / "runs" / "upload_probe"


def one(label: str, size: int) -> dict:
    from contree_sdk import ContreeSync
    from contree_sdk.config import ContreeConfig
    from contree_sdk.auth import IAMAuth
    from app.config import get_settings
    from app.services import timeouts

    s = get_settings()
    rec = {"label": label, "bytes": size, "started_at": datetime.now(timezone.utc).isoformat()}
    t0 = time.monotonic()
    stage = "connect"
    try:
        client = ContreeSync(config=ContreeConfig(
            auth=IAMAuth(token=s.nebius_api_key, project_id=s.nebius_project_id),
            transport_timeout=timeouts.sandbox_transport_timeout(size), operation_timeout=timeouts.SANDBOX_OPERATION_S))
        image = client.images.docker("python:3.10-slim")
        stage = "upload"
        up = image.apply_files(files={"probe.bin": os.urandom(size)})
        rec["upload_seconds"] = round(time.monotonic() - t0, 1)
        stage = "run"
        r = up.run(shell="ls -l probe.bin | awk '{print $5}'", timeout=120, disposable=True).wait()
        rec["run_stdout"] = (r.stdout or "").strip()[-100:]
        rec["run_exit"] = r.exit_code
        rec["accepted"] = r.exit_code == 0 and rec["run_stdout"] == str(size)
    except Exception as exc:
        rec.update(accepted=False, failed_at=stage, error=f"{type(exc).__name__}: {str(exc)[:600]}")
    rec["seconds"] = round(time.monotonic() - t0, 1)
    print(json.dumps(rec), flush=True)
    return rec


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    for label, size in SIZES:
        rec = one(label, size)
        name = f"boundary_{size}.json"
        (OUT / name).write_text(json.dumps(rec, indent=2) + "\n", encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
