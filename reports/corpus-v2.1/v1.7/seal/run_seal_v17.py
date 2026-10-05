"""Seal of harness-v1.7.1 (option B over CHANGED files; METHODOLOGY "harness-v1.7 — PRE-REGISTRATION", rule G): live checks of what v1.7 changed in the sandbox-touching files.

    backend/.venv/Scripts/python.exe reports/corpus-v2.1/v1.7/seal/run_seal_v17.py                                     # PLAN: what would run, ESTIMATED cost
    backend/.venv/Scripts/pythonw.exe reports/corpus-v2.1/v1.7/seal/run_seal_v17.py --go --max-usd X --log-file F       # live (launch_seal.cmd, Task Scheduler, owner)

Among the sandbox-touching files (scripts/run_corpus_v1_batch.py SANDBOX_TOUCHING_FILES) harness-v1.7 changes `runner_hooks.py` (R1 c the memory hook; R2 the CPU shim's
reference for LU without pivoting and the finders' re-entrancy guard; R3 the data-preparation launcher) and `runner_env.py` (R1 c the memory environment; R4 the apt-archive
step; R5 the torch companion swap). `sandbox.py`, `sandbox_limits.py` and `smoke_exec.py` are byte-identical to harness-v1.6.0 (and to harness-v1.4.3). Stages:

  v142       the hooks on a kept image, the exit hook gap, the exit wrapper on 3.10 and 3.6, the evidence command after a calm run and a self-SIGKILL: the v1.4.3 seal's
             `v142` stage, unchanged, against the new runner_hooks.py (it re-verifies the four entries that list runner_hooks.py, as the v1.5.1 seal did).
  runner_env the four checks of the v1.4.3 seal's `final` stage that list runner_env.py: torch 1.10.2 on Python 3.6 (exec-stack fix), the newest matched torch family on
             3.10, torch 1.8.1 with the NumPy cap on 3.9, a failing runner step tagged runner_setup.
  v17        the new paths, through the real runner:
               N1 python:3.10-slim + the runner's torch + the CPU shim + the memory hook, the command under the memory environment: torch.lu(pivot=False) is answered by the
                  reference (L @ U == A), a DataLoader(num_workers=2, pin_memory=True) runs with 0 workers and no pinning, MALLOC_ARENA_MAX / OMP_NUM_THREADS are set (R1 c, R2);
               N2 python:3.6-slim: the data-preparation launcher runs a README-documented script under its caps and the documented command finds its output (R3);
               N3 python:3.6-slim: the apt-archive step, then `apt-get install -y build-essential` succeeds and gcc runs (R4: the owner's live check);
               N4 python:3.7-slim (harness-v1.7.1): the runner's torch install with every pin of the companion swap (torch==1.2.0 kept, torchvision 0.5.0 -> 0.4.0,
                  Pillow==6.2.2 beside it), then `pip install -r` of RERUN's requirements copy of a file that pins what DEV #5 pins, then torch, torchvision and PIL
                  import at 1.2.0 / 0.4.0 / 6.2.2 (R5). Attempt 1 at harness-v1.7.0-rc failed here (runs/sandbox_verification/v1.7-seal/v17/N4_*).

Every record goes to runs/sandbox_verification/v1.7.1-seal/<stage>/; SEAL_RUN.json says which commit and which blobs of the five files the stages ran against. Reuses the v1.4.3
seal driver (precondition against the release-candidate tag, a stage that fails stops the seal, SEAL_RUN.json after every stage). Never runs without --go and --max-usd.
"""
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
_spec = importlib.util.spec_from_file_location("run_seal_v143", ROOT / "reports" / "corpus-v2.1" / "v1.4.3" / "seal" / "run_seal_v143.py")
base = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(base)

OUT = ROOT / "runs" / "sandbox_verification" / "v1.7.1-seal"  # harness-v1.7.1; attempt 1 (harness-v1.7.0-rc) stays in v1.7-seal
RC_TAG = "harness-v1.7.1-rc"
MAX_SEAL_USD = 1.50  # the owner's seal bound since v1.4.3
RUNNER_ENV_RECORDS = ("torch_py36_pin1.10.2.json", "torch_py310_imports_torchvision.json", "torch_py39_pin1.8.1_numpy_cap.json", "phase_runner_setup_failure_py310.json")
# ESTIMATED: N1 and N4 install torch (the v1.4.3 seal's torch checks cost $0.17-0.26 API-reported); N2 is a small operation; N3 runs apt on python:3.6-slim.
V17_ESTIMATES = {"N1_cpu_reference_lu_and_memory_hook": 0.30, "N2_data_prep_launcher_py36": 0.02, "N3_apt_archive_build_essential_py36": 0.08,
                 "N4_companion_swap_with_requirements_py37": 0.20}
# N4 at 0.20: attempt 1's N4 cost $0.1073 API-reported (torch 1.2.0 + torchvision on python:3.7-slim); v1.7.1 adds one `pip install -r` of five small pins. The guard
# starts a check only with 1.5 x its estimate left: at 0.30 that was $0.45 against about $0.50 left after attempt 1's other stages ($1.0001), too thin (v1.7.1 review).
WALL_SECONDS = {"N1_cpu_reference_lu_and_memory_hook": 600, "N2_data_prep_launcher_py36": 240, "N3_apt_archive_build_essential_py36": 420,
                "N4_companion_swap_with_requirements_py37": 720}

N1_PROBE = b'''import json, os, sys, warnings
warnings.simplefilter("ignore")
import torch
from torch.utils.data import DataLoader
A = torch.rand(6, 6, dtype=torch.float64) + 12 * torch.eye(6, dtype=torch.float64)
LU, piv = torch.lu(A, pivot=False)
L = torch.tril(LU, -1) + torch.eye(6, dtype=torch.float64)
U = torch.triu(LU)
loader = DataLoader(list(range(10)), batch_size=2, num_workers=2, pin_memory=True)
batches = [b.tolist() for b in loader]
print("V17_SEAL " + json.dumps({"torch": torch.__version__, "lu_err": float((L @ U - A).abs().max()), "pivots": piv.tolist(),
                                 "num_workers": loader.num_workers, "pin_memory": loader.pin_memory, "batches": len(batches),
                                 "env": {k: os.environ.get(k) for k in ("MALLOC_ARENA_MAX", "OMP_NUM_THREADS")}}))
'''

N2_FILES = {
    "README.md": b"# toy\n\nGo to `./data/toy`, follow the instructions in `README.md` to download and partition the dataset.\n",
    "data/toy/README.md": b"# TOY dataset\n\n```\npython generate_data.py \\\n    --n 3\n```\n",
    "data/toy/generate_data.py": (b"import argparse, os\np = argparse.ArgumentParser()\np.add_argument('--n', type=int)\na = p.parse_args()\n"
                                  b"os.makedirs('all_data', exist_ok=True)\nopen(os.path.join('all_data', 'x.txt'), 'w').write('x' * (1000 * a.n))\n"),
    "check.py": b"import os, sys\nsys.exit(0 if os.path.getsize('data/toy/all_data/x.txt') == 3000 else 3)\n",
}


def _v17_record(name: str, blobs_now: dict, **fields) -> dict:
    return base._record("v17", name, blobs_now, **fields)


def run_v17(api_key, project_id, guard, blobs_now):
    from app.services import data_prep, runner_env, runner_hooks, sandbox

    docs = []

    def op(name, **kw):
        needed = 1.5 * V17_ESTIMATES[name]
        if guard.remaining_today_usd < needed:
            raise SystemExit(f"STOP: ${guard.remaining_today_usd:.4f} left under the seal cap, below 1.5 x the ${V17_ESTIMATES[name]:.2f} estimate of {name}; not started")
        try:
            result = sandbox.run_build_and_execute(api_key=api_key, project_id=project_id, wall_clock_seconds=WALL_SECONDS[name], **kw)
        except sandbox.SandboxTimeoutError as exc:
            recorded = guard.record_killed_operation(exc.completed_cost_usd, exc.killed_seconds, note=f"{name}: {exc.command[:80]}")
            _v17_record(name, blobs_now, ok=False, killed=True, message=str(exc)[:400], cost_usd=recorded,
                        cost_tag="API-REPORTED completed steps + ESTIMATED killed step", run_id=exc.sandbox_id)
            return None
        guard.record_spend(result.total_cost_usd)
        return result

    def outputs(result) -> str:
        return "\n".join(f"{s.stdout}\n{s.stderr}" for s in (*result.rerun_steps, *result.steps))

    # N1: R1 c + R2 on the runner's newest CPU torch
    torch_setup = runner_env.plan_torch_setup(["import torch"], None) or runner_env.TorchSetup(("torch", "torchvision", "torchaudio"), "seal", ("torch",))
    n1 = op("N1_cpu_reference_lu_and_memory_hook", base_image="python:3.10-slim", install_commands=["true"],
            execute_command=runner_env.with_memory_env("python3 probe.py"), upload_files={"probe.py": N1_PROBE}, torch_setup=torch_setup,
            runner_extras=(runner_hooks.install_command(runner_hooks.CPU_SHIM), runner_hooks.install_command(runner_hooks.MEMORY_HOOK)))
    if n1 is None:
        return [*docs, {"ok": False, "note": "N1 stopped at its clock"}]
    text = outputs(n1)
    line = next((l for l in text.splitlines() if l.startswith("V17_SEAL ")), None)
    got = json.loads(line[len("V17_SEAL "):]) if line else {}
    ok = (n1.final.exit_code == 0 and got.get("lu_err", 1.0) < 1e-10 and got.get("pivots") == [1, 2, 3, 4, 5, 6] and got.get("num_workers") == 0
          and got.get("pin_memory") is False and got.get("batches") == 5 and got.get("env") == {"MALLOC_ARENA_MAX": "2", "OMP_NUM_THREADS": "4"}
          and "cpu_ref:torch.lu" in runner_hooks.shim_paths_fired(text) and "DataLoader num_workers 2->0" in runner_hooks.memory_hook_changes(text))
    docs.append(_v17_record("N1_cpu_reference_lu_and_memory_hook", blobs_now, ok=ok, probe=got, shim_paths=runner_hooks.shim_paths_fired(text),
                            memory_hook_changes=runner_hooks.memory_hook_changes(text), **base._result_doc(n1)))
    if not ok:
        return docs

    # N2: R3, the data-preparation launcher on Python 3.6
    with tempfile.TemporaryDirectory() as tmp:
        for rel, data in N2_FILES.items():
            path = Path(tmp) / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        decision = data_prep.decide(Path(tmp), "AssertionError: Download toy dataset!!")
    if decision.prep is None:
        return [*docs, _v17_record("N2_data_prep_launcher_py36", blobs_now, ok=False, note=f"the decision did not fire offline: {decision.reason}")]
    n2 = op("N2_data_prep_launcher_py36", base_image="python:3.6-slim", install_commands=["true"], execute_command="python3 check.py",
            upload_files=dict(N2_FILES), runner_extras=(runner_hooks.data_prep_command(decision.prep),))
    if n2 is None:
        return [*docs, {"ok": False, "note": "N2 stopped at its clock"}]
    prep_record = runner_hooks.parse_data_prep(outputs(n2))
    ok = n2.final.exit_code == 0 and prep_record is not None and prep_record.get("exit_code") == 0 and prep_record.get("bytes_written", 0) >= 3000
    docs.append(_v17_record("N2_data_prep_launcher_py36", blobs_now, ok=ok, decision=decision.prep.as_dict(), data_prep=prep_record, **base._result_doc(n2)))
    if not ok:
        return docs

    # N3: R4, the owner's live check: build-essential on python:3.6-slim after the apt-archive step
    n3 = op("N3_apt_archive_build_essential_py36", base_image="python:3.6-slim",
            install_commands=[runner_env.with_apt_archive("apt-get update && apt-get install -y build-essential")],
            execute_command="gcc --version | head -n 1 && echo V17_GCC_OK")
    if n3 is None:
        return [*docs, {"ok": False, "note": "N3 stopped at its clock"}]
    text = outputs(n3)
    rewrote = runner_env.apt_archive_rewrote(text)
    ok = n3.final.exit_code == 0 and "V17_GCC_OK" in n3.final.stdout and rewrote == ["bullseye"]
    docs.append(_v17_record("N3_apt_archive_build_essential_py36", blobs_now, ok=ok, rewrote=rewrote, sources=dict(runner_env.EOL_APT_SOURCES), **base._result_doc(n3)))
    if not ok:
        return docs

    # N4: R5 (harness-v1.7.1), the companion swap through the path a run takes. Attempt 1 (harness-v1.7.0-rc) installed torch 1.2.0 + torchvision 0.4.0 and
    # `import torchvision` raised ImportError PILLOW_VERSION (runs/sandbox_verification/v1.7-seal/v17/N4_*). Now: the runner's torch step with every pin of the swap
    # (Pillow==6.2.2 beside torchvision 0.4.0), then the repository's `pip install -r requirements.txt` from RERUN's copy (orchestrator._companion_requirements, the
    # code a run uses) of a file that pins what DEV #5 pins (torch, torchvision, Pillow, numpy, six), then the imports.
    from app.services import orchestrator, planner

    swap = runner_env.companion_swap(("torch==1.2.0", "torchvision==0.5.0", "torchaudio"))
    reqs = "numpy==1.17.2\nPillow==9.0.0\nsix==1.12.0\ntorch==1.2.0\ntorchvision==0.5.0\n"
    plan_n4, copy, pins = orchestrator._companion_requirements(planner.BuildPlan("python:3.7-slim", (), ("pip install -r requirements.txt",), "true"),
                                                               swap, reqs, "seal N4")
    setup = runner_env.plan_torch_setup([reqs], None, overrides=swap.overrides())
    n4 = op("N4_companion_swap_with_requirements_py37", base_image="python:3.7-slim", install_commands=list(plan_n4.install_commands), torch_setup=setup,
            upload_files={"requirements.txt": reqs.encode("utf-8")},
            execute_command="python3 -c \"import torch, torchvision, PIL; print('V17_COMPANION', torch.__version__, torchvision.__version__, PIL.__version__)\"")
    if n4 is None:
        return [*docs, {"ok": False, "note": "N4 stopped at its clock"}]
    parts = next((l for l in n4.final.stdout.splitlines() if l.startswith("V17_COMPANION")), "").split()
    ok = (n4.final.exit_code == 0 and len(parts) == 4 and parts[1].startswith("1.2.0") and parts[2].startswith("0.4.0") and parts[3] == "6.2.2"
          and copy is not None and "torchvision==0.4.0" in copy and "Pillow==6.2.2" in copy)
    docs.append(_v17_record("N4_companion_swap_with_requirements_py37", blobs_now, ok=bool(ok), swap=swap.as_dict(), specs=list(setup.specs),
                            requirements_pins=pins, requirements_copy=copy, installed=" ".join(parts), **base._result_doc(n4)))
    return docs


def run_runner_env(api_key, project_id, guard, blobs_now):
    """The v1.4.3 seal's `final` stage restricted to the four records that list runner_env.py, each in its own process through scripts/verify_*.py (the same argv as then),
    written to runs/sandbox_verification/v1.7.1-seal/runner_env/. The kill-at-limit check lists sandbox.py only and is not re-run."""
    mod = base._load("scripts/run_seal_verification_v140.py", "run_seal_verification_v140")
    mod.OUT = (OUT / "runner_env").relative_to(ROOT).as_posix()
    (ROOT / mod.OUT).mkdir(parents=True, exist_ok=True)
    plan = [p for p in mod.PLAN if p[0] in RUNNER_ENV_RECORDS]
    assert sorted(p[0] for p in plan) == sorted(RUNNER_ENV_RECORDS), [p[0] for p in plan]
    docs = []
    for record, argv, env, what in plan:
        done = ROOT / mod.OUT / record
        if done.is_file() and json.loads(done.read_text(encoding="utf-8")).get("ok") is True:
            print(f"-> {record}: already passed in an earlier invocation, not run again", flush=True)
            docs.append({"ok": True, "cost_usd": 0.0, "run_id": json.loads(done.read_text(encoding="utf-8")).get("run_id"), "skipped": True})
            continue
        expected = base.previous_cost(f"runs/sandbox_verification/v1.4.3-seal/final/{record}")
        if guard.remaining_today_usd < expected:
            raise SystemExit(f"STOP: ${guard.remaining_today_usd:.4f} left under the seal cap, below the ${expected:.4f} this check cost in the v1.4.3 seal; {record} is not started")
        print(f"-> {record}: {what}", flush=True)
        ok, cost, rec = mod._run(record, argv, env)
        guard.record_spend(cost)
        docs.append({"ok": ok, "cost_usd": cost, "run_id": rec.get("run_id")})
        print(f"   ok={ok} cost ${cost:.4f}", flush=True)
        if not ok:
            return docs
    return docs


def configure() -> None:
    base.OUT = OUT
    base.RC_TAG = RC_TAG
    base.MAX_SEAL_USD = MAX_SEAL_USD
    base.STAGES = ("v142", "runner_env", "v17")
    base.RUNNERS = {"v142": base.run_v142, "runner_env": run_runner_env, "v17": run_v17}
    original_plan = base.plan

    def plan():
        rows = [row for row in original_plan() if row["stage"] == "v142"]
        rows += [{"stage": "runner_env", "op": rec, "usd": base.previous_cost(f"runs/sandbox_verification/v1.4.3-seal/final/{rec}"),
                  "source": "v1.4.3 seal record, API-reported"} for rec in RUNNER_ENV_RECORDS]
        rows += [{"stage": "v17", "op": name, "usd": usd, "source": "ESTIMATED"} for name, usd in V17_ESTIMATES.items()]
        return rows

    base.plan = plan


configure()


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--log-file" in argv:
        i = argv.index("--log-file")
        sys.stdout = sys.stderr = open(argv[i + 1], "a", encoding="utf-8", buffering=1)
        del argv[i:i + 2]
    return base.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
