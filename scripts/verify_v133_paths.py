"""Live verification of the sandbox-touching code paths NEW in harness-v1.3.3 (seal rule): each runs through the real
sandbox.run_build_and_execute in a real Nebius sandbox. A WSL dry run is a smoke test, not verification.

  backend/.venv/Scripts/python.exe scripts/verify_v133_paths.py kill  <image> <out.json>
  backend/.venv/Scripts/python.exe scripts/verify_v133_paths.py smoke <alive|exits_ok|fails|silent> <image> <out.json>

kill   a step that would run 300 s is given a 25 s operation limit: the sandbox must stop it and the call must raise SandboxTimeoutError
       (whichever way the API reports the stop: the server returning the step's result with state.timed_out, measured cost included, or
       the client's wait expiring first, in which case the killed step's duration is reported instead), in well under the step's own length.
       The record's `run_id` is the sandbox image id or the Nebius operation id, and `via` says which path it was.
       (Attempt 1, 2026-09-30, found the first path: the call returned a normal result after ~28 s and the script, which only knew the
       second path, failed.)
smoke  the smoke launcher (smoke_exec.wrap, 10 s limit) on this image:
         alive     prints, then sleeps 120 s        -> exit 0, RERUN_SMOKE_ALIVE in stdout, stopped by the launcher
         exits_ok  prints and exits by itself       -> exit 0, no ALIVE marker, output unchanged
         fails     imports a missing module         -> exit 1 and the ModuleNotFoundError traceback on stderr, unchanged
         silent    sleeps 120 s printing nothing    -> exit 1 and RERUN_SMOKE_FAILED (no output, nothing shows it worked)
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

SMOKE_CASES = {
    "alive": ("python3 -c \"import time; print('step 1 started', flush=True); time.sleep(120)\"", 0, "alive_at_limit"),
    "exits_ok": ("python3 -c \"print('finished by itself')\"", 0, "exited"),
    "fails": ("python3 -c \"import no_such_module_xyz\"", 1, "exited"),
    "silent": ("python3 -c \"import time; time.sleep(120)\"", 1, "failed_while_running"),
}


def _settings():
    from app.config import get_settings

    return get_settings()


def verify_kill(image: str, out: Path) -> int:
    from app.services import sandbox

    s = _settings()
    rec = {"path": "kill_at_operation_limit", "image": image, "started_at": datetime.now(timezone.utc).isoformat(), "limit_seconds": 25}
    started = time.monotonic()
    try:
        sandbox.run_build_and_execute(
            api_key=s.nebius_api_key, project_id=s.nebius_project_id, base_image=image,
            install_commands=[], execute_command="sleep 300", wall_clock_seconds=25,
        )
        rec.update(ok=False, error="the 300 s step returned a result instead of raising SandboxTimeoutError",
                   elapsed_seconds=round(time.monotonic() - started, 1))
    except sandbox.SandboxTimeoutError as exc:
        rec["elapsed_seconds"] = round(time.monotonic() - started, 1)
        cause = exc.__cause__
        run_id = str(getattr(cause, "operation_uuid", "") or exc.sandbox_id or "")
        rec.update(
            message=str(exc), command=exc.command, via=exc.via, killed_seconds=round(exc.killed_seconds, 1),
            completed_cost_usd=exc.completed_cost_usd, run_id=run_id,
            ok="wall clock" in str(exc) and exc.command == "sleep 300" and 15 < rec["elapsed_seconds"] < 120 and bool(run_id)
            and ((exc.via == "server_result_timed_out" and exc.completed_cost_usd > 0) or (exc.via == "client_wait_timeout" and 10 < exc.killed_seconds < 60)),
        )
    except Exception as exc:  # recorded, never hidden
        rec.update(ok=False, error=f"{type(exc).__name__}: {exc}")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rec, indent=2), encoding="utf-8")
    print(json.dumps({k: rec.get(k) for k in ("ok", "run_id", "via", "elapsed_seconds", "killed_seconds", "completed_cost_usd", "message", "error")}, indent=1))
    return 0 if rec.get("ok") else 1


def verify_smoke(scenario: str, image: str, out: Path) -> int:
    from app.services import sandbox, smoke_exec

    command, want_exit, want_outcome = SMOKE_CASES[scenario]
    s = _settings()
    rec = {"path": "smoke_launcher", "scenario": scenario, "image": image, "command": command,
           "started_at": datetime.now(timezone.utc).isoformat(), "smoke_seconds": 10}
    started = time.monotonic()
    try:
        result = sandbox.run_build_and_execute(
            api_key=s.nebius_api_key, project_id=s.nebius_project_id, base_image=image, install_commands=[],
            execute_command=smoke_exec.wrap(command, 10), wall_clock_seconds=90,
        )
        final = result.final
        execution = smoke_exec.execution_record(10, final.exit_code, final.stdout, final.stderr)
        checks = {
            "exit_code": final.exit_code == want_exit,
            "outcome": execution["outcome"] == want_outcome,
            "fast": time.monotonic() - started < 80,
        }
        if scenario == "fails":
            checks["traceback_forwarded"] = "ModuleNotFoundError: No module named 'no_such_module_xyz'" in final.stderr
        if scenario == "exits_ok":
            checks["output_unchanged"] = "finished by itself" in final.stdout and smoke_exec.ALIVE_MARKER not in final.stdout
        if scenario == "alive":
            checks["output_seen"] = "step 1 started" in final.stdout
        rec.update(run_id=result.sandbox_id, exit_code=final.exit_code, stdout=final.stdout[-600:], stderr=final.stderr[-600:],
                   execution=execution, checks=checks, cost_usd=result.total_cost_usd,
                   elapsed_seconds=round(time.monotonic() - started, 1), ok=all(checks.values()))
    except Exception as exc:  # recorded, never hidden
        rec.update(ok=False, error=f"{type(exc).__name__}: {exc}")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rec, indent=2), encoding="utf-8")
    print(json.dumps({k: rec.get(k) for k in ("ok", "run_id", "checks", "cost_usd", "error")}, indent=1))
    return 0 if rec.get("ok") else 1


if __name__ == "__main__":
    args = sys.argv[1:]
    if args[:1] == ["kill"] and len(args) == 3:
        raise SystemExit(verify_kill(args[1], Path(args[2])))
    if args[:1] == ["smoke"] and len(args) == 4 and args[1] in SMOKE_CASES:
        raise SystemExit(verify_smoke(args[1], args[2], Path(args[3])))
    raise SystemExit(__doc__)
