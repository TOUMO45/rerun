"""The Batch Lab job entrypoint (RERUN directive §7): runs inside one
Nebius Serverless Job container, clones ONE corpus repo pinned to its
recorded commit SHA, runs RERUN's own single-repo pipeline against it,
and prints a single JSON verdict line to stdout for the batch runner to
collect via `get_job_logs` (see `runner.py`'s module docstring — this is
the piece that module explicitly said didn't exist yet).

Usage (matches `runner.run_single_repo_job`'s constructed job args):

    python -m app.batch.run_single_repo \\
        --repo-url https://github.com/org/repo \\
        --commit-sha <40-char sha> \\
        --name repo-display-name

Exit code is 0 whenever a verdict was reached at all — including
BLOCKED/INDETERMINATE, which are successful *measurements*, not job
failures. Exit code is non-zero only for an infrastructure failure (bad
credentials, can't even clone) that produced no verdict at all, since
that's a real job failure the batch runner needs to distinguish from a
repo that was validly, honestly found not to reproduce.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from pathlib import Path

from app.config import get_settings
from app.services import intake
from app.services.cost_guard import get_shared_cost_guard
from app.services.orchestrator import build_pipeline_deps, reason_code_of, run_pipeline


def run_one_repo(
    repo_url: str,
    commit_sha: str,
    name: str,
    *,
    settings=None,
    run_pipeline_fn=None,
    clone_fn=None,
) -> dict:
    """The testable core: clone at the pinned commit, run the pipeline,
    return a result dict in exactly the shape
    `runner.aggregate_batch_results` expects. `settings`/`run_pipeline_fn`/
    `clone_fn` are injectable so this can be tested without live
    credentials or a real Nebius sandbox call, the same pattern used
    throughout this codebase.

    Defaults resolve to the real `run_pipeline`/`clone_repo_at_commit` at
    *call* time, not at function-definition time — a `def foo(x=real_fn)`
    default is bound once when the module is first imported, so
    monkeypatching the module-level name afterward (as tests do) would
    silently have no effect on calls that rely on that default. This bit
    a test during this session before being caught and fixed.
    """
    settings = settings or get_settings()
    run_pipeline_fn = run_pipeline_fn or run_pipeline
    clone_fn = clone_fn or intake.clone_repo_at_commit
    # §9's daily cost ceiling is a PROCESS-WIDE in-memory singleton
    # (cost_guard.get_shared_cost_guard, @lru_cache'd). That's correct and
    # sufficient for the web app, which is one long-running process
    # handling every request. It is NOT sufficient here: each corpus
    # repo's batch job is its own separate Nebius Serverless Job
    # container — a genuinely separate OS process with its own memory —
    # so `get_shared_cost_guard()` returns a *fresh*, independently-zeroed
    # guard in every container. A 20-repo batch run can spend up to 20x
    # the configured daily ceiling in aggregate before any single
    # container's own local check would ever trip. Fixing this for real
    # would need spend tracked in some resource shared across containers
    # (a DB row, an external service) — out of scope for this fix; noted
    # here, not silently assumed away, since §9 states the ceiling as a
    # general safety guarantee and this is a real gap in it for the batch
    # path specifically. See DECISIONS.md.
    started = time.monotonic()
    workdir = Path(tempfile.mkdtemp(prefix=f"rerun_batch_{name}_"))
    try:
        resolved_sha = clone_fn(repo_url, workdir, commit_sha)
        intake_result = intake.parse_intake(workdir, resolved_sha)

        if not intake.repo_has_python_code(workdir, intake_result.dependency_files):
            return {
                "name": name,
                "repo_url": repo_url,
                "verdict": "NOT_ATTEMPTABLE",
                "taxonomy_code": None,
                "attempts_used": 0,
                "duration_seconds": round(time.monotonic() - started, 1),
            }

        deps = build_pipeline_deps(settings)
        cost_guard = get_shared_cost_guard()
        result = run_pipeline_fn(
            repo_url=repo_url,
            commit_sha=resolved_sha,
            workdir=workdir,
            intake_result=intake_result,
            deps=deps,
            cost_guard=cost_guard,
            run_id=f"batch-{name}",
        )
        return {
            "name": name,
            "repo_url": repo_url,
            "verdict": result.verdict,
            "taxonomy_code": result.taxonomy_code,
            # e.g. ENTRYPOINT_UNCLEAR, RECON_MODEL_ERROR, PIPELINE_ERROR:recon:ValueError —
            # the aggregator uses it to keep RERUN's own failures out of the denominator.
            "reason_code": reason_code_of(result.indeterminate_reason),
            "attempts_used": len(result.attempts),
            "duration_seconds": round(time.monotonic() - started, 1),
        }
    finally:
        # A bare shutil.rmtree(..., ignore_errors=True) silently fails to
        # fully delete a real git clone on Windows (git's own object files
        # are read-only) — confirmed directly, not assumed. See
        # intake.cleanup_workdir's docstring. Every batch job leaking its
        # clone would add up across a real 20-repo run.
        intake.cleanup_workdir(workdir)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo-url", required=True)
    parser.add_argument("--commit-sha", required=True)
    parser.add_argument("--name", required=True)
    args = parser.parse_args(argv)

    try:
        output = run_one_repo(args.repo_url, args.commit_sha, args.name)
    except intake.IntakeError as exc:
        # A real infrastructure failure (couldn't even clone) — distinct
        # from a valid BLOCKED/INDETERMINATE/NOT_ATTEMPTABLE verdict,
        # which IS a successful measurement and must exit 0.
        print(json.dumps({"name": args.name, "repo_url": args.repo_url, "error": str(exc)}))
        return 1

    print(json.dumps(output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
