"""Live upload checks through RERUN's real sandbox client (harness-v1.2).

  probe   The pre-registered upload-cap probe (METHODOLOGY, "Upload cap",
          amendment 1): synthetic archives of PROBE_SIZES_MB, ascending,
          stopping at the first failure. Cap = the largest passing size; if the
          smallest fails, no cap can be set (stop). It also sets the assumed
          upload throughput: 0.5 x the slowest measured MB/s among passing steps.
  smoke   The pre-batch smoke test: a small upload plus an upload at the cap
          size (sandbox.UPLOAD_CAP_BYTES). Required before every batch.

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

PROBE_SIZES_MB = (25, 50, 75, 100, 125)
THROUGHPUT_SAFETY = 0.5
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
    files["run.sh"] = (
        # Quoted: an unquoted "file(s)" is a sh syntax error (it voided the
        # first amendment-1 probe run at 25 MB).
        b"#!/bin/sh\necho \"UPLOAD_OK $(ls data | wc -l) files\"\n"
        b"echo EXTRACTED_BYTES $(du -sb . 2>/dev/null | cut -f1)\necho DF $(df -B1 . | tail -1)\n"
    )
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
            upload_seconds=result.upload_seconds,
            extract_seconds=result.extract_seconds,
            upload_mb_per_s=round(archive_bytes / 1e6 / result.upload_seconds, 3) if result.upload_seconds else None,
            # Peak disk: the tree after extraction (the archive is already
            # deleted). `df` inside the sandbox reports a shared ~47 TB rootfs,
            # so a true per-instance peak is not measurable from inside.
            extracted_tree_bytes=_field(result.final.stdout, "EXTRACTED_BYTES"),
            df=_field(result.final.stdout, "DF", whole=True),
        )
    except Exception as exc:  # recorded, never hidden
        record.update(ok=False, error=f"{type(exc).__name__}: {str(exc)[:500]}")
    record["seconds"] = round(time.monotonic() - started, 1)
    record["effective_mb_per_s"] = round(archive_bytes / 1e6 / record["seconds"], 2) if record["seconds"] else None
    print(json.dumps(record), flush=True)
    return record


def _field(stdout: str, key: str, whole: bool = False):
    for line in (stdout or "").splitlines():
        if line.startswith(key + " "):
            value = line[len(key) + 1:].strip()
            return value if whole else (int(value) if value.isdigit() else value)
    return None


def probe() -> dict:
    from app.services import timeouts

    runs = []
    for size in PROBE_SIZES_MB:
        runs.append(upload_once(size))
        if not runs[-1]["ok"]:
            break
    passing = [r for r in runs if r["ok"]]
    cap = max((r["archive_bytes"] for r in passing), default=None)
    rates = [r["upload_mb_per_s"] for r in passing if r.get("upload_mb_per_s")]
    throughput = round(THROUGHPUT_SAFETY * min(rates), 3) if rates else None
    timeout_at_cap = (
        max(timeouts.SANDBOX_TRANSPORT_FLOOR_S, cap / 1e6 / throughput + timeouts.UPLOAD_MARGIN_S)
        if cap and throughput else None
    )
    return {
        "kind": "upload-cap probe (pre-registered, amendment 1)",
        "sizes_mb": list(PROBE_SIZES_MB),
        "runs": runs,
        "cap_bytes": cap,
        "slowest_passing_upload_mb_per_s": min(rates) if rates else None,
        "assumed_min_throughput_mb_per_s": throughput,
        "transport_timeout_at_cap_s": round(timeout_at_cap, 1) if timeout_at_cap else None,
        "decision": (
            f"cap = {cap:,} bytes (largest passing); assumed throughput = "
            + (f"{THROUGHPUT_SAFETY} x {min(rates)} MB/s" if rates else "not measurable (no timed upload)")
            if cap else "the smallest probed size failed — no cap can be set; stop"
        ),
    }


def smoke() -> dict:
    from app.services import sandbox

    cap = sandbox.UPLOAD_CAP_BYTES
    if not cap:
        return {"kind": "pre-batch upload smoke test", "runs": [], "ok": False, "error": "no upload cap set"}
    # The largest whole-MB synthetic archive that stays within the cap.
    cap_mb = max(1, int(cap // 1_000_000) - 1)
    runs = [upload_once(None), upload_once(cap_mb)]
    return {"kind": "pre-batch upload smoke test", "cap_bytes": cap, "runs": runs, "ok": all(r["ok"] for r in runs)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("mode", choices=("probe", "smoke"))
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument(
        "--dry-run", action="store_true",
        help="local WSL dry run: the real archive, extraction, check and payload, no Nebius (sizes 1 and 2 MB)",
    )
    args = parser.parse_args(argv)
    if args.dry_run:
        global PROBE_SIZES_MB
        import importlib.util

        from app.services import sandbox

        spec = importlib.util.spec_from_file_location("wsl_dryrun", ROOT / "scripts" / "wsl_dryrun.py")
        dry = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(dry)
        sandbox.run_build_and_execute = dry.run_build_and_execute
        PROBE_SIZES_MB = (1, 2)
    outcome = probe() if args.mode == "probe" else smoke()
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(outcome, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({k: v for k, v in outcome.items() if k != "runs"}))
    ok = outcome.get("ok", outcome.get("cap_bytes") is not None)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
