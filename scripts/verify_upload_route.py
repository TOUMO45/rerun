"""Live verification of the normal (archive) upload route after the verify-script change (harness-v1.3.2: exec-bit
comparison): a synthetic tree with a git-100755 and a git-100644 file goes through sandbox.run_build_and_execute in a
real Nebius sandbox; the extraction check must pass, `./run.sh` must be executable, `a/b.txt` must not be.

  backend/.venv/Scripts/python.exe scripts/verify_upload_route.py <image> <out.json>
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


def main(image: str, out: Path) -> int:
    from app.config import get_settings
    from app.services import sandbox

    files = {"run.sh": b"#!/bin/sh\necho RAN_OK\n", "a/b.txt": b"data\n", "tools/x.py": b"print(1)\n"}
    modes = {"run.sh": "100755", "a/b.txt": "100644", "tools/x.py": "100755"}
    s = get_settings()
    rec = {"image": image, "started_at": datetime.now(timezone.utc).isoformat(), "files": sorted(files)}
    try:
        r = sandbox.run_build_and_execute(
            api_key=s.nebius_api_key, project_id=s.nebius_project_id, base_image=image, install_commands=[],
            execute_command="./run.sh && test -x tools/x.py && ! test -x a/b.txt && test ! -e .rerun_upload_v1 && echo MODES_OK",
            wall_clock_seconds=300, upload_files=files, file_modes=modes)
        rec.update(run_id=str(r.sandbox_id), cost_usd=r.total_cost_usd, stdout=r.final.stdout.strip()[-300:],
                   stderr=r.final.stderr.strip()[-300:], ok=r.succeeded and "RAN_OK" in r.final.stdout and "MODES_OK" in r.final.stdout)
    except Exception as exc:  # recorded, never hidden
        rec.update(ok=False, error=f"{type(exc).__name__}: {str(exc)[:800]}", stderr=getattr(exc, "stderr", ""))
    print(json.dumps(rec, indent=1))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rec, indent=2) + "\n", encoding="utf-8", newline="\n")
    return 0 if rec["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1], Path(sys.argv[2])))
