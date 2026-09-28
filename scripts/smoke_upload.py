"""Live upload checks through RERUN's real sandbox client (harness-v1.2).

  probe   The pre-registered upload-cap probe (METHODOLOGY, "Upload cap"):
          synthetic archives of PROBE_SIZES_MB, uploaded, extracted and
          verified in a real Nebius sandbox. The cap is the largest probed size
          that passes; if the smallest fails, no cap can be set (stop).
  smoke   The pre-batch smoke test: a small upload plus a ~SMOKE_LARGE_MB one.
          Required before every batch (the batch driver calls it).

Synthetic data is incompressible (seeded random bytes, 50 MB files), so the
archive size is the transfer size. Nothing about any corpus entry is used.

Usage (repo root):
  backend/.venv/Scripts/python.exe scripts/smoke_upload.py probe --out runs/upload_probe/probe.json
  backend/.venv/Scripts/python.exe scripts/smoke_upload.py smoke
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

PROBE_SIZES_MB = (150, 500)
SMOKE_LARGE_MB = 150
FILE_MB = 50
SEED = 20260928


def synthetic_files(total_mb: int) -> dict[str, bytes]:
    rng = random.Random(SEED + total_mb)
    files, remaining, i = {}, total_mb, 0
    while remaining > 0:
        size = min(FILE_MB, remaining)
        files[f"data/blob_{i:03d}.bin"] = rng.randbytes(size * 1_000_000)
        remaining -= size
        i += 1
    files["run.sh"] = b"#!/bin/sh\necho UPLOAD_OK $(ls data | wc -l) file(s) $(du -sb data | cut -f1) bytes\n"
    return files


def upload_once(total_mb: int | None) -> dict:
    """Upload + extract + verify + run ./run.sh through sandbox.run_build_and_execute."""
    from app.config import get_settings
    from app.services import sandbox, timeouts

    settings = get_settings()
    files = synthetic_files(total_mb) if total_mb else {"run.sh": b"#!/bin/sh\necho UPLOAD_OK small\n"}
    modes = {path: ("100755" if path == "run.sh" else "100644") for path in files}
    archive_bytes = len(sandbox.build_upload_archive(files, modes, mtime=0)[0])
    record = {
        "requested_mb": total_mb or 0,
        "archive_bytes": archive_bytes,
        "transport_timeout_s": timeouts.sandbox_transport_timeout(archive_bytes),
        "started_at": datetime.now(timezone.utc).isoformat(),
    }
    started = time.monotonic()
    try:
        result = sandbox.run_build_and_execute(
            api_key=settings.nebius_api_key,
            project_id=settings.nebius_project_id,
            base_image="python:3.11-slim",
            install_commands=[],
            execute_command="./run.sh",
            wall_clock_seconds=900,
            upload_files=files,
            file_modes=modes,
        )
        record.update(
            ok=result.succeeded and "UPLOAD_OK" in result.final.stdout,
            exit_code=result.final.exit_code,
            stdout=result.final.stdout.strip()[-300:],
            stderr=result.final.stderr.strip()[-300:],
            cost_usd=result.total_cost_usd,
        )
    except Exception as exc:  # recorded, never hidden
        record.update(ok=False, error=f"{type(exc).__name__}: {str(exc)[:500]}")
    record["seconds"] = round(time.monotonic() - started, 1)
    record["effective_mb_per_s"] = round(archive_bytes / 1e6 / record["seconds"], 2) if record["seconds"] else None
    print(json.dumps(record), flush=True)
    return record


def probe() -> dict:
    runs = []
    for size in PROBE_SIZES_MB:
        runs.append(upload_once(size))
        if not runs[-1]["ok"]:
            break
    passing = [r["archive_bytes"] for r in runs if r["ok"]]
    return {
        "kind": "upload-cap probe (pre-registered)",
        "sizes_mb": list(PROBE_SIZES_MB),
        "runs": runs,
        "cap_bytes": max(passing) if passing else None,
        "decision": (f"cap = {max(passing):,} bytes (largest probed archive that uploaded and verified)"
                     if passing else "no probed size passed — no cap can be set; stop"),
    }


def smoke() -> dict:
    runs = [upload_once(None), upload_once(SMOKE_LARGE_MB)]
    return {"kind": "pre-batch upload smoke test", "runs": runs, "ok": all(r["ok"] for r in runs)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("mode", choices=("probe", "smoke"))
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)
    outcome = probe() if args.mode == "probe" else smoke()
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(outcome, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({k: v for k, v in outcome.items() if k != "runs"}))
    ok = outcome.get("ok", outcome.get("cap_bytes") is not None)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
