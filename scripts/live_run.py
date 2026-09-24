"""Run RERUN's real single-repo pipeline once, live, against one corpus repo,
and write the full raw run record to JSON.

Nothing here replaces a pipeline component: intake, recon, planner,
sandbox, classifier, Tavily, repairer, tamper gate, adjudicator and
passport are the production code paths (`orchestrator.run_pipeline` with
`build_pipeline_deps(settings)`). This script only adds observation:

  - every log line is timestamped as it is emitted (for per-stage timings);
  - the real OpenAI client is wrapped so each Token Factory response's
    `usage` block and latency are recorded (model_client itself discards
    usage);
  - a run-local CostGuard with a hard daily ceiling (--cost-cap-usd).

Usage (from repo root, with backend/.venv):

    backend/.venv/Scripts/python.exe scripts/live_run.py --name gpt-2 \
        --out runs/first_live_run.json
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))

from openai import OpenAI  # noqa: E402

from app.batch.corpus import load_corpus  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.services import intake  # noqa: E402
from app.services.cost_guard import CostGuard  # noqa: E402
from app.services.model_client import NebiusChatClient  # noqa: E402
from app.services.orchestrator import build_pipeline_deps, reason_code_of, run_pipeline  # noqa: E402

MODEL_CALLS: list[dict] = []


class _RecordingNebiusChatClient(NebiusChatClient):
    """Same class, same chat_completion; only `_client()` is wrapped so the
    raw response's usage/latency is captured before model_client reads
    `.content` from it."""

    def _client(self) -> OpenAI:
        real = super()._client()
        original_create = real.chat.completions.create

        def create(**kwargs):
            started = time.monotonic()
            record = {"model": kwargs.get("model"), "started_at": _now()}
            try:
                response = original_create(**kwargs)
            except Exception as exc:
                record.update(error=f"{type(exc).__name__}: {exc}", latency_s=round(time.monotonic() - started, 2))
                MODEL_CALLS.append(record)
                raise
            choice = response.choices[0]
            extra = choice.message.model_extra or {}
            record.update(
                latency_s=round(time.monotonic() - started, 2),
                finish_reason=choice.finish_reason,
                content_is_none=choice.message.content is None,
                has_reasoning=bool(extra.get("reasoning") or extra.get("reasoning_content")),
                usage=response.usage.model_dump() if response.usage else None,
            )
            MODEL_CALLS.append(record)
            return response

        real.chat.completions.create = create
        return real


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--name", required=True, help="corpus entry name")
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--cost-cap-usd", type=float, default=2.0)
    args = parser.parse_args(argv)

    entry = next((e for e in load_corpus() if e.name == args.name), None)
    if entry is None:
        print(f"no corpus entry named {args.name!r}", file=sys.stderr)
        return 2

    settings = get_settings()
    deps = build_pipeline_deps(settings)
    client = _RecordingNebiusChatClient(api_key=settings.nebius_api_key, base_url=settings.nebius_base_url)
    deps = replace(deps, recon_client=client, repair_client=client, adjudicator_client=client, planner_client=client)
    cost_guard = CostGuard(daily_cost_ceiling_usd=args.cost_cap_usd, max_attempts_per_run=settings.max_attempts_per_run)

    events: list[dict] = []
    t0 = time.monotonic()

    def on_event(line: str) -> None:
        events.append({"t_s": round(time.monotonic() - t0, 2), "at": _now(), "line": line})
        print(f"[{time.monotonic() - t0:7.1f}s] {line[:300]}", flush=True)

    record: dict = {
        "run_kind": "first live end-to-end run",
        "started_at": _now(),
        "corpus_entry": {"name": entry.name, "repo_url": entry.repo_url, "commit_sha": entry.commit_sha},
        "config": {
            "models": {
                "recon": deps.recon_model,
                "planner": deps.planner_model,
                "repairer": deps.repair_model,
                "adjudicator": deps.adjudicator_model,
            },
            "sandbox_backend": settings.nebius_sandbox_backend,
            "sandbox_image_default": deps.default_sandbox_image,
            "sandbox_wall_clock_seconds": deps.sandbox_wall_clock_seconds,
            "max_attempts": deps.max_attempts,
            "tavily_configured": deps.tavily_client is not None,
            "cost_cap_usd": args.cost_cap_usd,
        },
    }

    workdir = Path(tempfile.mkdtemp(prefix=f"rerun_live_{entry.name}_"))
    exit_code = 0
    try:
        clone_started = time.monotonic()
        resolved_sha = intake.clone_repo_at_commit(entry.repo_url, workdir, entry.commit_sha)
        intake_result = intake.parse_intake(workdir, resolved_sha)
        record["intake"] = {
            "duration_s": round(time.monotonic() - clone_started, 2),
            "resolved_sha": resolved_sha,
            "dependency_files": sorted(intake_result.dependency_files),
            "declared_dependencies": sorted(intake_result.declared_dependencies),
            "entrypoint_candidates": list(intake_result.entrypoint_candidates),
            "notebook_paths": list(intake_result.notebook_paths),
        }
        t0 = time.monotonic()
        result = run_pipeline(
            repo_url=entry.repo_url,
            commit_sha=resolved_sha,
            workdir=workdir,
            intake_result=intake_result,
            deps=deps,
            cost_guard=cost_guard,
            run_id=f"live-{entry.name}",
            on_event=on_event,
        )
        record["pipeline_duration_s"] = round(time.monotonic() - t0, 2)
        record["result"] = {
            "verdict": result.verdict,
            "taxonomy_code": result.taxonomy_code,
            "indeterminate_reason": result.indeterminate_reason,
            "reason_code": reason_code_of(result.indeterminate_reason),
            "error_traceback": result.error_traceback,
            "attempts": [a.as_dict() for a in result.attempts],
            "certificate_prose": result.certificate_prose,
        }
        # Exactly the downloadable-certificate shape Certificate.tsx exports
        # and scripts/verify_passport.py checks.
        record["certificate"] = {
            "repo_url": result.repo_url,
            "commit_sha": result.commit_sha,
            "build_plan": result.build_plan or {},
            "full_log": result.full_log,
            "diffs": [a.as_dict() for a in result.attempts],
            "verdict": result.verdict,
            "timestamp": result.timestamp,
            "reproduction_passport_hash": result.reproduction_passport_hash,
        }
    except Exception as exc:  # recorded, never hidden
        record["error"] = f"{type(exc).__name__}: {exc}"
        exit_code = 1
    finally:
        intake.cleanup_workdir(workdir)
        record["finished_at"] = _now()
        record["events"] = events
        record["model_calls"] = MODEL_CALLS
        record["cost_guard"] = {"spent_usd": cost_guard.spent_today_usd, "remaining_usd": cost_guard.remaining_today_usd}
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(record, indent=2), encoding="utf-8")
        print(f"wrote {args.out}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
