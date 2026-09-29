"""Does torch load inside a Nebius sandbox? (Phase 3: the executable-stack refusal.)

Pilot entry 3 found that the sandbox refuses torch's shared objects:
`libtorch_cpu.so: cannot enable executable stack as shared object requires: Invalid argument`.
This script answers, per stage, with a real `python -c "import torch"`:

  a  the newest torch CPU wheel (`--index-url https://download.pytorch.org/whl/cpu`), optionally a pinned
     version (`--torch-spec torch==1.13.1`), then import;
  b  if a is refused: `pip install patchelf`, clear the exec-stack flag on every .so under torch/lib whose
     PT_GNU_STACK is RWE (parsed from the ELF program headers, no binutils needed), then import again.

Each run records glibc (`ldd --version`), kernel (`uname -r`), the python and torch versions, the RWE libraries
found, every step's exit code, and the cost. Every Nebius script gets a local WSL dry run first: `--dry-run-wsl`.

Usage (repo root):
  backend/.venv/Scripts/python.exe scripts/torch_sandbox_check.py --stage a --dry-run-wsl
  backend/.venv/Scripts/python.exe scripts/torch_sandbox_check.py --stage a --out runs/torch_check/a.json
  backend/.venv/Scripts/python.exe scripts/torch_sandbox_check.py --stage b --out runs/torch_check/b.json
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
sys.path.insert(0, str(ROOT / "scripts"))

DIAGNOSTICS = (
    "echo GLIBC $(ldd --version 2>&1 | head -1); echo KERNEL $(uname -r); echo PYTHON $(python -V 2>&1); "
    "echo ARCH $(uname -m)"
)
IMPORT_TORCH = "python -c 'import torch; print(\"TORCH_OK\", torch.__version__)'"


def commands_for(stage: str, torch_spec: str) -> tuple[list[str], str]:
    """Stage a = the runner's own torch install op; stage b adds the runner's own fix-and-verify op.
    Both come from app.services.runner_env, so this checks exactly what the runner runs."""
    from app.services import runner_env

    setup = runner_env.TorchSetup((torch_spec,), "torch_sandbox_check")
    install = [setup.install_command]
    if stage == "b":
        install.append(setup.fix_command)
    return install, f"{DIAGNOSTICS}; {IMPORT_TORCH}"


def run_stage(stage: str, torch_spec: str, dry_run_wsl: bool, base_image: str) -> dict:
    from app.config import get_settings

    if dry_run_wsl:
        import wsl_dryrun as sandbox_runner_module
    else:
        from app.services import sandbox as sandbox_runner_module

    settings = get_settings()
    install, execute = commands_for(stage, torch_spec)
    record = {
        "stage": stage, "torch_spec": torch_spec, "base_image": base_image, "dry_run_wsl": dry_run_wsl,
        "install_commands": install, "execute_command": execute,
        "started_at": datetime.now(timezone.utc).isoformat(),
    }
    t0 = time.monotonic()
    try:
        result = sandbox_runner_module.run_build_and_execute(
            api_key=settings.nebius_api_key, project_id=settings.nebius_project_id, base_image=base_image,
            install_commands=install, execute_command=execute, wall_clock_seconds=1500,
        )
        record["steps"] = [
            {"command": s.command[:200], "exit_code": s.exit_code, "stdout": s.stdout[-4000:], "stderr": s.stderr[-4000:],
             "seconds": round(s.elapsed_seconds, 2), "cost_usd": s.cost_usd}
            for s in result.steps
        ]
        final = result.final
        record["torch_ok"] = final.exit_code == 0 and "TORCH_OK" in final.stdout
        record["sandbox_id"] = result.sandbox_id
        record["cost_usd"] = round(result.total_cost_usd, 4)
        for line in (s for st in result.steps for s in st.stdout.splitlines()):
            for key in ("GLIBC", "KERNEL", "PYTHON", "ARCH"):
                if line.startswith(key + " "):
                    record[key.lower()] = line[len(key) + 1:]
        record["execstack_cleared"] = sorted({ln for st in result.steps for ln in st.stdout.splitlines()
                                              if ln.startswith("RERUN_EXECSTACK_CLEARED")})
        record["exec_stack_refused"] = "cannot enable executable stack" in (final.stderr + final.stdout)
    except Exception as exc:  # recorded, never hidden
        record["error"] = f"{type(exc).__name__}: {exc}"
        record["torch_ok"] = False
    record["wall_seconds"] = round(time.monotonic() - t0, 2)
    record["finished_at"] = datetime.now(timezone.utc).isoformat()
    return record


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--stage", choices=("a", "b"), required=True)
    ap.add_argument("--torch-spec", default="torch", help="e.g. torch==1.13.1 (default: newest)")
    ap.add_argument("--base-image", default="python:3.11-slim")
    ap.add_argument("--dry-run-wsl", action="store_true")
    ap.add_argument("--out", type=Path)
    args = ap.parse_args(argv)
    record = run_stage(args.stage, args.torch_spec, args.dry_run_wsl, args.base_image)
    text = json.dumps(record, indent=2)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n", encoding="utf-8", newline="\n")
    print(text)
    return 0 if record.get("torch_ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
