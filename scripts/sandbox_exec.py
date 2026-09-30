"""Run shell commands in a throwaway Nebius sandbox on a given image, printing each step's output.
Live-verification helper (harness-v1.3.2): a real Nebius execution, not a WSL dry run.

  backend/.venv/Scripts/python.exe scripts/sandbox_exec.py --image python:3.10-slim --out runs/sandbox_verification/x.json -- 'cmd1' 'cmd2'
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


def run(image_name: str, commands: list[str], timeout: float = 900) -> dict:
    from contree_sdk import ContreeSync
    from contree_sdk.auth import IAMAuth
    from contree_sdk.config import ContreeConfig
    from app.config import get_settings
    from app.services import timeouts

    s = get_settings()
    client = ContreeSync(config=ContreeConfig(
        auth=IAMAuth(token=s.nebius_api_key, project_id=s.nebius_project_id),
        transport_timeout=60.0, operation_timeout=timeouts.SANDBOX_OPERATION_S))
    current = client.images.docker(image_name)
    rec = {"image": image_name, "started_at": datetime.now(timezone.utc).isoformat(), "steps": [], "cost_usd": 0.0}
    for i, cmd in enumerate(commands):
        last = i == len(commands) - 1
        t0 = time.monotonic()
        ex = current.run(shell=cmd, timeout=timeout, disposable=last, preserve_env=not last).wait()
        step = {"cmd": cmd, "exit": ex.exit_code, "stdout": (ex.stdout or "")[-4000:], "stderr": (ex.stderr or "")[-2000:],
                "seconds": round(time.monotonic() - t0, 1)}
        try:
            step["cost_usd"] = float(ex.cost)
            rec["cost_usd"] += step["cost_usd"]
        except Exception:
            pass
        rec["steps"].append(step)
        current = ex
        if ex.exit_code != 0:
            break
    return rec


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", required=True)
    ap.add_argument("--out", type=Path)
    ap.add_argument("cmds", nargs="+")
    a = ap.parse_args()
    r = run(a.image, a.cmds)
    for st in r["steps"]:
        print(f"$ {st['cmd'][:200]}\n[exit {st['exit']}, {st['seconds']}s]\n{st['stdout']}{st['stderr']}")
    print("cost", r["cost_usd"])
    if a.out:
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_text(json.dumps(r, indent=2) + "\n", encoding="utf-8", newline="\n")
