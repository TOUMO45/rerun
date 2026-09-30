"""Live verification of the runner's torch setup (harness-v1.3.2): the runner's own plan_torch_setup -> install op ->
fix-and-verify op -> `import`, in a real Nebius sandbox, through sandbox.run_build_and_execute (a WSL dry run is a
smoke test, not verification).

  backend/.venv/Scripts/python.exe scripts/verify_runner_torch.py <image> <out.json> pin <torch-pin> [<pin> ...]
  backend/.venv/Scripts/python.exe scripts/verify_runner_torch.py <image> <out.json> imports <module> [<module> ...]

`pin`     the repo declares the given requirement(s), e.g. torch==1.12.1
`imports` the repo (a temp dir) imports the given module(s) and declares nothing (attempt 1, entry 4)

Environment (negative branches, each verified live too):
  VERIFY_EXPECT=ok                    (default) the run succeeds and the import works
  VERIFY_EXPECT=runner_setup_failure  a runner op fails; the step is tagged phase=runner_setup and no repo command ran
  VERIFY_EXPECT=incompat              as above, and the fix op exited 98 with RERUN_SANDBOX_INCOMPAT (patchelf lacks the flag)
  VERIFY_PATCHELF_PIN=patchelf==0.17.2.1   replace the runner's patchelf pin (to force the flag-absent branch)
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


def main(image: str, out: Path, mode: str, items: list[str]) -> int:
    from app.config import get_settings
    from app.services import runner_env, sandbox

    expect = os.environ.get("VERIFY_EXPECT", "ok")
    if os.environ.get("VERIFY_PATCHELF_PIN"):
        runner_env.FIX_AND_VERIFY = runner_env.FIX_AND_VERIFY.replace("patchelf==0.19.1.0", os.environ["VERIFY_PATCHELF_PIN"])
    if mode == "pin":
        setup = runner_env.plan_torch_setup([f"pip install {' '.join(items)}"], None)
        modules = [i.split("==")[0] for i in items]
    else:
        workdir = Path(tempfile.mkdtemp(prefix="rerun_torchfix_"))
        (workdir / "train.py").write_text("".join(f"import {m}\n" for m in items), encoding="utf-8")
        setup = runner_env.plan_torch_setup(["true"], workdir)
        modules = [m.split(".")[0] for m in items]
    check = "python -c 'import sys, %s; print(\"IMPORT_OK\", sys.version.split()[0], %s)'" % (
        ", ".join(modules), ", ".join(f"{m}.__version__" for m in modules))
    s = get_settings()
    rec = {"image": image, "mode": mode, "items": items, "expect": expect, "install_command": setup.install_command,
           "reason": setup.reason, "started_at": datetime.now(timezone.utc).isoformat()}
    try:
        r = sandbox.run_build_and_execute(
            api_key=s.nebius_api_key, project_id=s.nebius_project_id, base_image=image, install_commands=[],
            execute_command=check, wall_clock_seconds=900, torch_setup=setup)
        final = r.final
        rec.update(run_id=str(r.sandbox_id), cost_usd=r.total_cost_usd, succeeded=r.succeeded, final_phase=final.phase,
                   steps=[{"cmd": st.command[:140], "phase": st.phase, "exit": st.exit_code, "stdout": st.stdout.strip()[-300:],
                           "stderr": st.stderr.strip()[-500:], "seconds": round(st.elapsed_seconds, 1)} for st in r.steps])
        repo_ran = any(st.phase == "repo_run" for st in r.steps)
        if expect == "ok":
            rec["ok"] = r.succeeded and "IMPORT_OK" in final.stdout
        elif expect == "runner_setup_failure":
            rec["ok"] = (not r.succeeded) and final.phase == "runner_setup" and not repo_ran
        elif expect == "incompat":
            rec["ok"] = (final.exit_code == 98 and "RERUN_SANDBOX_INCOMPAT" in final.stderr
                         and final.phase == "runner_setup" and not repo_ran)
        else:
            rec["ok"] = False
    except Exception as exc:  # recorded, never hidden
        rec.update(ok=False, error=f"{type(exc).__name__}: {str(exc)[:800]}")
    print(json.dumps(rec, indent=1))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rec, indent=2) + "\n", encoding="utf-8", newline="\n")
    return 0 if rec["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1], Path(sys.argv[2]), sys.argv[3], sys.argv[4:]))
