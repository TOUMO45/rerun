"""Step 2 (2026-09-24): baseline vs RERUN, passport bundle v2, and
execution-only certificate wording."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text

from app.batch.runner import aggregate_batch_results
from app.services import adjudicator
from app.services.cost_guard import CostGuard
from app.services.intake import RepoIntake
from app.services.orchestrator import PipelineDeps, PipelineResult, run_pipeline
from app.services.passport import compute_passport_hash, verify_certificate
from app.services.sandbox import SandboxRunResult, StepResult
from app.services.time_machine import LockResult

REPO_ROOT = Path(__file__).resolve().parents[2]
VERIFIER = REPO_ROOT / "scripts" / "verify_passport.py"


def _verify_standalone(cert: dict, tmp_path: Path) -> subprocess.CompletedProcess:
    path = tmp_path / "cert.json"
    path.write_text(json.dumps(cert), encoding="utf-8")
    return subprocess.run([sys.executable, str(VERIFIER), str(path)], capture_output=True, text=True)


# --- old (v1) certificates keep verifying -------------------------------------


@pytest.mark.parametrize("record", ["live_run_gpt2_v3.json", "live_run_ttpt_v2.json", "live_run_simple.json"])
def test_committed_v1_live_certificates_still_verify(record, tmp_path):
    cert = json.loads((REPO_ROOT / "runs" / record).read_text(encoding="utf-8"))["certificate"]
    assert "bundle_version" not in cert  # genuinely a v1 certificate
    assert verify_certificate(cert)
    proc = _verify_standalone(cert, tmp_path)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "PASSPORT VERIFIED" in proc.stdout


# --- v2 bundle ------------------------------------------------------------


def _v2_cert(**overrides) -> dict:
    cert = {
        "repo_url": "https://github.com/o/r",
        "commit_sha": "a" * 40,
        "build_plan": {},
        "full_log": "[baseline] as-is run: FAILS",
        "diffs": [],
        "verdict": "RUNS_AFTER_REPAIR",
        "timestamp": "2026-09-24T00:00:00+00:00",
        "bundle_version": 2,
        "baseline": {"result": "FAILS", "exit_code": 1, "taxonomy_code": "SYS_LIB_MISSING"},
        "recovery": True,
    }
    cert.update(overrides)
    cert["reproduction_passport_hash"] = compute_passport_hash(cert)
    return cert


def test_v2_certificate_verifies_in_backend_and_standalone(tmp_path):
    cert = _v2_cert()
    assert verify_certificate(cert)
    assert _verify_standalone(cert, tmp_path).returncode == 0


@pytest.mark.parametrize(
    "field,value",
    [("baseline", {"result": "RUNS_CLEAN"}), ("recovery", False), ("bundle_version", 1)],
)
def test_v2_fields_are_covered_by_the_hash(field, value, tmp_path):
    cert = _v2_cert()
    cert[field] = value
    assert not verify_certificate(cert)
    assert _verify_standalone(cert, tmp_path).returncode != 0


def test_unknown_bundle_version_never_verifies(tmp_path):
    cert = _v2_cert()
    cert["bundle_version"] = 99
    assert not verify_certificate(cert)
    assert _verify_standalone(cert, tmp_path).returncode != 0


# --- the orchestrator records the baseline and computes recovery ----------------

LOG = "  error: command 'gcc' failed: No such file or directory\n"


class _Chat:
    def __init__(self, responses):
        self._responses = list(responses)

    def chat_completion(self, **kwargs):
        return self._responses.pop(0)


def _run(tmp_path, sandbox_results, *, recon_confidence=0.9, lock=None, repair=()):
    (tmp_path / "requirements.txt").write_text("regex==2017.4.5\n", encoding="utf-8")
    (tmp_path / "gen.py").write_text("import regex\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "-c", "user.email=t@e.st", "-c", "user.name=t", "commit", "-q", "-m", "x"], cwd=tmp_path, check=True)
    results = list(sandbox_results)
    deps = PipelineDeps(
        recon_client=_Chat([json.dumps({"entrypoint": "gen.py", "confidence": recon_confidence})]),
        recon_model="r",
        repair_client=_Chat([json.dumps(r) for r in repair]),
        repair_model="p",
        adjudicator_client=None,
        adjudicator_model=None,
        sandbox_api_key="k",
        sandbox_wall_clock_seconds=60,
        sandbox_runner=lambda **kw: results.pop(0),
        max_attempts=max(1, len(repair)),
        lock_compiler=lock or (lambda *a: LockResult(True, ("regex==2017.4.5",), ())),
    )
    intake = RepoIntake(tmp_path, "a" * 40, {"requirements.txt": "regex==2017.4.5\n"}, frozenset({"regex"}), (), ("gen.py",), None)
    return run_pipeline(repo_url="https://example.com/r", commit_sha="a" * 40, workdir=tmp_path, intake_result=intake,
                        deps=deps, cost_guard=CostGuard(daily_cost_ceiling_usd=100), run_id="baseline")


def _res(code, stderr=""):
    return SandboxRunResult(steps=(StepResult("run", code, "", stderr, 1.0, 0.0),))


def test_baseline_failure_then_completion_is_a_recovery(tmp_path):
    result = _run(tmp_path, [_res(1, LOG), _res(0)])
    assert result.verdict == "RUNS_AFTER_REPAIR"
    assert result.baseline["result"] == "FAILS"
    assert result.baseline["taxonomy_code"] == "SYS_LIB_MISSING"
    assert result.baseline["install_commands"] == ["pip install -r requirements.txt"]
    assert result.recovery is True
    cert = result.certificate()
    assert cert["bundle_version"] == 3 and cert["recovery"] is True
    assert verify_certificate(cert)


def test_baseline_pass_is_runs_clean_and_not_a_recovery(tmp_path):
    result = _run(tmp_path, [_res(0)])
    assert (result.verdict, result.baseline["result"], result.recovery) == ("RUNS_CLEAN", "RUNS_CLEAN", False)


def test_baseline_failure_that_stays_blocked_is_not_a_recovery(tmp_path):
    result = _run(
        tmp_path, [_res(1, LOG), _res(1, LOG)],
        repair=[{"code_diff": None, "env_delta": [], "explanation": "no"}],
    )
    assert (result.verdict, result.baseline["result"], result.recovery) == ("BLOCKED", "FAILS", False)


def test_no_baseline_when_the_run_never_executes(tmp_path):
    result = _run(tmp_path, [], recon_confidence=0.1)
    assert result.verdict == "INDETERMINATE"
    assert result.baseline == {"result": "NOT_RUN"}
    assert result.recovery is False
    assert verify_certificate(result.certificate())


# --- execution-only wording ---------------------------------------------------


@pytest.mark.parametrize(
    "prose",
    [
        "The repository reproduces the paper's results.",
        "Results were reproduced after one fix.",
        "This artifact is fully reproducible.",
        "Successful REPRODUCTION of the main table.",
    ],
)
def test_model_prose_claiming_reproduction_is_replaced(prose):
    client = _Chat([json.dumps({"verdict": "RUNS_AFTER_REPAIR", "prose": prose})])
    result = adjudicator.adjudicate(client, "m", verdict="RUNS_AFTER_REPAIR", attempts_used=1)
    assert "reproduc" not in result.certificate_prose.replace(adjudicator.SCOPE_BOUNDARY_LINE, "").lower()
    assert "ran to completion" in result.certificate_prose
    assert result.used_templated_fallback


def test_negative_control_execution_wording_is_kept():
    prose = "The command ran to completion after installing a compiler."
    client = _Chat([json.dumps({"verdict": "RUNS_AFTER_REPAIR", "prose": prose})])
    result = adjudicator.adjudicate(client, "m", verdict="RUNS_AFTER_REPAIR", attempts_used=1)
    assert result.certificate_prose.startswith(prose)
    assert not result.used_templated_fallback


@pytest.mark.parametrize("verdict", ["RUNS_CLEAN", "RUNS_AFTER_REPAIR", "BLOCKED", "INDETERMINATE", "NOT_ATTEMPTABLE", "TIMEOUT"])
def test_templated_prose_never_claims_reproduction(verdict):
    prose = adjudicator.templated_certificate_prose(verdict, "X", 1)
    assert not adjudicator.makes_reproduction_claim(prose)


# --- persistence: old DBs gain the columns; the API round-trips a v2 cert ---------


def test_init_db_adds_the_v2_columns_to_an_existing_database(tmp_path):
    from app.db import init_db

    engine = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE certificates (id VARCHAR(36) PRIMARY KEY, run_id VARCHAR(36), verdict VARCHAR(32), "
            "certificate_prose TEXT, full_log TEXT, build_plan JSON, diffs JSON, "
            "reproduction_passport_hash VARCHAR(64), timestamp VARCHAR(64))"
        ))
        conn.execute(text("INSERT INTO certificates (id, run_id, verdict, full_log, build_plan, diffs, reproduction_passport_hash, timestamp) "
                          "VALUES ('c1', 'r1', 'BLOCKED', '', '{}', '[]', 'h', 't')"))
    init_db(engine)
    init_db(engine)  # idempotent
    columns = {c["name"] for c in inspect(engine).get_columns("certificates")}
    assert {"bundle_version", "baseline", "recovery"} <= columns
    with engine.connect() as conn:
        assert conn.execute(text("SELECT verdict FROM certificates WHERE id='c1'")).scalar() == "BLOCKED"


def test_v2_certificate_round_trips_through_the_api(client, fake_paper_repo, monkeypatch):
    created = client.post("/runs", json={"repo_url": str(fake_paper_repo)}).json()
    real_sha = subprocess.run(["git", "-C", str(fake_paper_repo), "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    cert = _v2_cert(repo_url=str(fake_paper_repo), commit_sha=real_sha, timestamp=datetime.now(timezone.utc).isoformat())
    fake_result = PipelineResult(
        verdict=cert["verdict"], taxonomy_code=None, indeterminate_reason="", attempts=(), build_plan={},
        full_log=cert["full_log"], certificate_prose="ran to completion", reproduction_passport_hash=cert["reproduction_passport_hash"],
        timestamp=cert["timestamp"], repo_url=cert["repo_url"], commit_sha=real_sha, bundle_version=2,
        baseline=cert["baseline"], recovery=True,
    )

    class _S:
        nebius_configured = True
        nebius_api_key = "k"
        nebius_base_url = "https://x/v1"
        nebius_model_recon = nebius_model_repairer = nebius_model_adjudicator = nebius_model_planner = "m"
        nebius_sandbox_wall_clock_seconds = 60
        max_attempts_per_run = 3
        daily_cost_ceiling_usd = 25.0
        tavily_configured = False
        nebius_sandbox_image = "python:3.11-slim"
        nebius_project_id = ""
        nebius_sandbox_backend = "token_factory"

    monkeypatch.setattr("app.routers.runs.get_settings", lambda: _S())
    monkeypatch.setattr("app.routers.runs.run_pipeline", lambda **kwargs: fake_result)
    client.post(f"/runs/{created['id']}/execute")
    run = client.get(f"/runs/{created['id']}").json()
    body = client.get(f"/runs/{created['id']}/certificate").json()
    assert (body["bundle_version"], body["recovery"], body["baseline"]["result"]) == (2, True, "FAILS")
    downloaded = {
        "repo_url": run["repo_url"], "commit_sha": run["commit_sha"], "build_plan": body["build_plan"],
        "full_log": body["full_log"], "diffs": body["diffs"], "verdict": body["verdict"], "timestamp": body["timestamp"],
        "bundle_version": body["bundle_version"], "baseline": body["baseline"], "recovery": body["recovery"],
        "reproduction_passport_hash": body["reproduction_passport_hash"],
    }
    assert verify_certificate(downloaded)


# --- batch: recovery = baseline FAIL -> final completed ---------------------------


def test_aggregate_counts_recovery_from_baseline_failures():
    batch = aggregate_batch_results([
        {"name": "a", "verdict": "RUNS_CLEAN", "baseline": "RUNS_CLEAN", "recovery": False},
        {"name": "b", "verdict": "RUNS_AFTER_REPAIR", "baseline": "FAILS", "recovery": True},
        {"name": "c", "verdict": "BLOCKED", "baseline": "FAILS", "recovery": False},
        {"name": "d", "verdict": "BLOCKED"},  # older record without a baseline
        {"name": "e", "verdict": "INDETERMINATE", "reason_code": "PIPELINE_ERROR:x:Y", "baseline": "FAILS"},
    ])
    assert (batch["baseline_recorded"], batch["baseline_passed"], batch["baseline_failed"],
            batch["recovered_from_baseline_failure"]) == (3, 1, 2, 1)
