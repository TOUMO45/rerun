"""harness-v1.10 pass: shared helpers of the full-pipeline measurement (reports/v1.10/pipeline/).

The measurement drives the harness's OWN decision procedure on a planted patch, with the harness code taken from a tag's git worktree (never from the working tree), so a
rule edited after the tag cannot leak into a measurement of the tag:

    gate (tamper_gate.check_patch + py_compile_violations, the way the orchestrator calls them)
    -> apply the patch as a branch of a kept environment image and run the documented command under the smoke launcher (a REAL sandbox run)
    -> the exit-zero check (exit_zero_check.overrule) and the classifier, as `_execute_once` / `_candidate_stage` use them
    -> the candidate adjudicator (adjudicator.adjudicate_candidates, the real model call) with the failure being repaired
    -> the verdict RUNS_AFTER_REPAIR and the final, downgrade-only adjudicator (adjudicator.adjudicate)
    -> the outcome labels (outcome_levels)

Why not `run_pipeline` itself: it builds an image and runs the documented command first; on every base repository the deterministic rules (era lock, CPU shim, removed-API
table, apt archive) fix the recorded failure before any model is asked for a candidate, so a planted code patch would never be proposed. The candidate-evaluation procedure is
what a model's patch meets once the loop does run; it is rebuilt here from the same functions (listed above) and a REAL sandbox. Nothing about it is simulated except the
proposer: the planted patch stands where the repairer model's patch would.
"""
from __future__ import annotations

import base64
import hashlib
import json
import subprocess
import sys
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
HARNESS_PATHS = ("backend/app", "backend/pyproject.toml", "scripts", "frontend/src", ".gitattributes")

SMOKE_SECONDS = 60
RUN_TIMEOUT_S = 150.0  # apply + smoke window + start-up margin; the sandbox stops a step at this limit


def git(*args: str, cwd: Path = ROOT) -> str:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


def load_harness(worktree: Path, tag: str):
    """Put `worktree`'s backend first on sys.path and return the imported modules. Refuses unless the worktree's HEAD is the tag's commit, its harness paths are clean and
    `app` really was imported from it."""
    worktree = Path(worktree).resolve()
    head, want = git("rev-parse", "HEAD", cwd=worktree), git("rev-parse", f"{tag}^{{commit}}")
    if head != want:
        raise SystemExit(f"{worktree} HEAD {head} is not {tag} = {want}")
    if git("status", "--porcelain", "--", *HARNESS_PATHS, cwd=worktree):
        raise SystemExit(f"{worktree}: harness paths are not clean")
    sys.path.insert(0, str(worktree / "backend"))
    import app  # noqa: PLC0415

    if not Path(app.__file__).resolve().is_relative_to(worktree):
        raise SystemExit(f"app imported from {app.__file__}, not from {worktree}")
    from app.config import get_settings  # noqa: PLC0415
    from app.services import adjudicator, classifier, exit_zero_check, outcome_levels, sandbox, smoke_exec, tamper_gate  # noqa: PLC0415
    from app.services.cost_guard import CostGuard  # noqa: PLC0415
    from app.services.model_client import NebiusChatClient  # noqa: PLC0415
    from app.services.orchestrator import _candidate_stage, build_pipeline_deps  # noqa: PLC0415

    class H:  # a namespace
        pass

    h = H()
    h.worktree, h.tag, h.head = worktree, tag, head
    h.settings = get_settings()
    h.deps = build_pipeline_deps(h.settings)
    h.client = NebiusChatClient(api_key=h.settings.nebius_api_key, base_url=h.settings.nebius_base_url)
    h.CostGuard = CostGuard
    h.adjudicator, h.classifier, h.exit_zero_check, h.outcome_levels, h.sandbox, h.smoke_exec, h.tamper_gate = (
        adjudicator, classifier, exit_zero_check, outcome_levels, sandbox, smoke_exec, tamper_gate)
    h.candidate_stage = _candidate_stage
    try:  # harness-v1.10 and later: the behavioural checks (app/services/behaviour.py); absent from harness-v1.9.0 and earlier
        from app.services import behaviour  # noqa: PLC0415

        h.behaviour = behaviour
    except ImportError:
        h.behaviour = None
    return h


def overlay_command(files: dict[str, str]) -> str:
    """One shell command that writes `files` (repo-relative path -> new text) into the image's tree and verifies each by sha-256; exit 97 on a mismatch (the run is void)."""
    spec = {p: {"z": base64.b64encode(zlib.compress(t.encode("utf-8"), 9)).decode("ascii"), "sha": hashlib.sha256(t.encode("utf-8")).hexdigest()} for p, t in files.items()}
    code = (
        "import base64,hashlib,json,os,sys,zlib\n"
        "spec=json.loads(base64.b64decode(sys.argv[1]).decode())\n"
        "bad=[]\n"
        "for p,v in spec.items():\n"
        "    d=zlib.decompress(base64.b64decode(v['z']))\n"
        "    os.makedirs(os.path.dirname(p) or '.',exist_ok=True)\n"
        "    open(p,'wb').write(d)\n"
        "    if hashlib.sha256(open(p,'rb').read()).hexdigest()!=v['sha']: bad.append(p)\n"
        "if bad:\n"
        "    sys.stderr.write('RERUN_OVERLAY_MISMATCH '+' '.join(bad)+'\\n'); sys.exit(97)\n"
        "print('RERUN_OVERLAY_APPLIED %d file(s)' % len(spec))\n"
    )
    arg = base64.b64encode(json.dumps(spec, sort_keys=True).encode("utf-8")).decode("ascii")
    return f"python3 -c \"import base64;exec(base64.b64decode('{base64.b64encode(code.encode('utf-8')).decode('ascii')}').decode('utf-8'))\" {arg}"


def run_on_image(h, image: str, command: str, files: dict[str, str] | None, *, timeout: float = RUN_TIMEOUT_S, extras: tuple[str, ...] = (), env: dict | None = None):
    """ONE real, disposable sandbox run of the documented `command` under the smoke launcher on the kept `image`, after `files` (post-patch texts) are written into its tree.
    `extras` (harness-v1.10): setup commands run first (the behavioural tracer's install); `env`: variables for the command only (smoke_exec.wrap(env=)). Returns the sandbox StepResult."""
    smoke = h.smoke_exec.wrap(command, SMOKE_SECONDS, env=env) if env else h.smoke_exec.wrap(command, SMOKE_SECONDS)
    full = " && ".join([*([overlay_command(files)] if files else []), *extras, smoke])
    return h.sandbox.run_on_image(api_key=h.settings.nebius_api_key, project_id=getattr(h.settings, "nebius_project_id", ""), image_id=image, command=full, timeout_seconds=timeout)


def sandbox_result(h, step):
    """The step as the orchestrator holds a run: a SandboxRunResult, exit-zero-checked (an overruled exit code 0 is not a pass)."""
    return h.exit_zero_check.overrule(h.sandbox.SandboxRunResult(steps=(step,)))


def tails(step, n: int = 1500) -> dict:
    return {"stdout_tail": (step.stdout or "")[-n:], "stderr_tail": (step.stderr or "")[-n:]}
