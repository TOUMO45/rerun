"""End-to-end tests for orchestrator.py's pipeline logic.

The model layer (recon/repair/adjudicator) and the sandbox layer are
faked — no live Nebius call. But `classifier.py` and `tamper_gate.py`
run FOR REAL, unmocked, in every test here. This is deliberate: the
directive's own §14 red-team pass asks "can a rejected-then-corrected
repair actually reach RUNS_AFTER_REPAIR without the gate ever seeing the
final diff?" — the only way to actually answer that is to run the real
gate inside the real loop, which is exactly what
`test_reject_then_pass_reaches_runs_after_repair` does.
"""

from __future__ import annotations

import difflib
import json
import textwrap
from pathlib import Path

import pytest

from app.services.cost_guard import CostGuard
from app.services.intake import RepoIntake
from app.services.orchestrator import PipelineDeps, run_pipeline
from app.services.passport import verify_certificate
from app.services.sandbox import SandboxError, SandboxRunResult, StepResult


class _FakeChatClient:
    """Returns successive canned responses, one per call — lets a test
    script a whole conversation (e.g. repair attempt 1 vs attempt 2)."""

    def __init__(self, responses: list[str]):
        self._responses = list(responses)
        self.calls: list[dict] = []

    def chat_completion(self, **kwargs):
        self.calls.append(kwargs)
        if not self._responses:
            raise RuntimeError("fake chat client ran out of scripted responses")
        return self._responses.pop(0)


class _FakeSandboxRunner:
    """Returns successive canned SandboxRunResults — one per call to
    run_build_and_execute — regardless of what it was actually asked to
    build/run, since orchestration wiring (not sandbox execution) is what
    these tests verify."""

    def __init__(self, results: list[SandboxRunResult]):
        self._results = list(results)
        self.calls: list[dict] = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        if not self._results:
            raise RuntimeError("fake sandbox runner ran out of scripted results")
        return self._results.pop(0)


def _sandbox_result(exit_code: int, stdout: str = "", stderr: str = "", cost: float = 0.001) -> SandboxRunResult:
    return SandboxRunResult(steps=(StepResult("run", exit_code, stdout, stderr, 1.0, cost),))


def _intake(entrypoint_content: dict[str, str], dependency_files: dict[str, str] | None = None) -> RepoIntake:
    return RepoIntake(
        local_path=Path("unused"),
        commit_sha="a" * 40,
        dependency_files=dependency_files or {"requirements.txt": "numpy\n"},
        declared_dependencies=frozenset({"numpy"}),
        notebook_paths=(),
        entrypoint_candidates=tuple(entrypoint_content.keys()),
        python_version_hint=None,
    )


def _write_files(workdir: Path, files: dict[str, str]) -> None:
    for rel_path, content in files.items():
        (workdir / rel_path).parent.mkdir(parents=True, exist_ok=True)
        (workdir / rel_path).write_text(content, encoding="utf-8")


def _base_deps(recon_client, repair_client, adjudicator_client, sandbox_runner) -> PipelineDeps:
    # adjudicator_client=None (the common case in these tests) means
    # adjudicator.adjudicate() takes its templated-fallback path — these
    # tests are about orchestration wiring, not adjudicator prose, so most
    # of them pass None here rather than a scripted client.
    adjudicator_model = "nvidia/nemotron-3-ultra" if adjudicator_client is not None else None
    return PipelineDeps(
        recon_client=recon_client,
        recon_model="nvidia/nemotron-3-nano",
        repair_client=repair_client,
        repair_model="nvidia/nemotron-3-super",
        adjudicator_client=adjudicator_client,
        adjudicator_model=adjudicator_model,
        sandbox_api_key="fake-key-for-test-construction-only",
        sandbox_wall_clock_seconds=60,
        sandbox_runner=sandbox_runner,
    )


def _unified_diff(path: str, old: str, new: str) -> str:
    return "".join(
        difflib.unified_diff(
            old.splitlines(keepends=True),
            new.splitlines(keepends=True),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
        )
    )


# --- INDETERMINATE short-circuit: sandbox must never be touched -------------


def test_indeterminate_recon_never_calls_sandbox(tmp_path):
    train_py = "def run():\n    pass\n"
    _write_files(tmp_path, {"train.py": train_py})
    intake = _intake({"train.py": train_py})

    recon_client = _FakeChatClient([json.dumps({"entrypoint": "train.py", "confidence": 0.1})])  # too low
    sandbox_runner = _FakeSandboxRunner([])  # must never be called
    deps = _base_deps(recon_client, _FakeChatClient([]), None, sandbox_runner)

    result = run_pipeline(
        repo_url="https://example.com/repo",
        commit_sha="a" * 40,
        workdir=tmp_path,
        intake_result=intake,
        deps=deps,
        cost_guard=CostGuard(daily_cost_ceiling_usd=100),
        run_id="run-1",
    )

    assert result.verdict == "INDETERMINATE"
    assert sandbox_runner.calls == []


# --- RUNS_CLEAN: first execution succeeds ------------------------------------


def test_runs_clean_first_try():
    train_py = "def run():\n    print('ok')\n\nrun()\n"
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        workdir = Path(d)
        _write_files(workdir, {"train.py": train_py})
        intake = _intake({"train.py": train_py})

        recon_client = _FakeChatClient([json.dumps({"entrypoint": "train.py", "confidence": 0.9})])
        sandbox_runner = _FakeSandboxRunner([_sandbox_result(0, stdout="ok\n")])
        deps = _base_deps(recon_client, _FakeChatClient([]), None, sandbox_runner)

        result = run_pipeline(
            repo_url="https://example.com/repo",
            commit_sha="a" * 40,
            workdir=workdir,
            intake_result=intake,
            deps=deps,
            cost_guard=CostGuard(daily_cost_ceiling_usd=100),
            run_id="run-2",
        )

    assert result.verdict == "RUNS_CLEAN"
    assert result.attempts == ()
    assert len(sandbox_runner.calls) == 1


# --- THE §14 red-team scenario: REJECT then PASS -> RUNS_AFTER_REPAIR ------


def test_reject_then_pass_reaches_runs_after_repair(tmp_path):
    train_py = textwrap.dedent(
        """\
        def evaluate(m):
            return m

        def run():
            x = 1 / 0
            evaluate(None)

        run()
        """
    )
    _write_files(tmp_path, {"train.py": train_py})
    intake = _intake({"train.py": train_py})

    recon_client = _FakeChatClient(
        [json.dumps({"entrypoint": "train.py", "confidence": 0.9, "eval_call_names": ["evaluate"]})]
    )

    bad_diff = _unified_diff(
        "train.py",
        train_py,
        textwrap.dedent(
            """\
            def evaluate(m):
                return m

            def run():
                x = 1 / 0

            run()
            """
        ),
    )
    good_diff = _unified_diff(
        "train.py",
        train_py,
        textwrap.dedent(
            """\
            def evaluate(m):
                return m

            def run():
                x = 1
                evaluate(None)

            run()
            """
        ),
    )
    repair_client = _FakeChatClient(
        [
            json.dumps({"diff": bad_diff, "explanation": "removed the redundant eval call"}),
            json.dumps({"diff": good_diff, "explanation": "fixed the division by zero"}),
        ]
    )

    sandbox_runner = _FakeSandboxRunner(
        [
            _sandbox_result(1, stderr="ZeroDivisionError: division by zero"),  # initial failure
            _sandbox_result(0, stdout="done\n"),  # after the good patch
        ]
    )

    deps = _base_deps(recon_client, repair_client, None, sandbox_runner)

    result = run_pipeline(
        repo_url="https://example.com/repo",
        commit_sha="a" * 40,
        workdir=tmp_path,
        intake_result=intake,
        deps=deps,
        cost_guard=CostGuard(daily_cost_ceiling_usd=100),
        run_id="run-3",
    )

    assert result.verdict == "RUNS_AFTER_REPAIR"
    assert len(result.attempts) == 2
    assert result.attempts[0].gate_decision == "REJECT"
    assert result.attempts[1].gate_decision == "PASS"
    # The file on disk must reflect the GOOD patch only — the bad one was
    # never applied, proving the gate — not the loop's optimism — decided.
    final_content = (tmp_path / "train.py").read_text(encoding="utf-8")
    assert "evaluate(None)" in final_content
    assert "x = 1\n" in final_content
    # Only one re-execution happened (after the PASS), not one per attempt.
    assert len(sandbox_runner.calls) == 2


# --- BLOCKED: repair keeps declining until attempts are exhausted -----------


def test_blocked_after_exhausting_attempts():
    train_py = "def run():\n    raise RuntimeError('boom')\n\nrun()\n"
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        workdir = Path(d)
        _write_files(workdir, {"train.py": train_py})
        intake = _intake({"train.py": train_py})

        recon_client = _FakeChatClient([json.dumps({"entrypoint": "train.py", "confidence": 0.9})])
        repair_client = _FakeChatClient([json.dumps({"diff": None, "explanation": "cannot fix"})] * 3)
        sandbox_runner = _FakeSandboxRunner([_sandbox_result(1, stderr="RuntimeError: boom")])

        deps = _base_deps(recon_client, repair_client, None, sandbox_runner)
        cost_guard = CostGuard(daily_cost_ceiling_usd=100, max_attempts_per_run=3)

        result = run_pipeline(
            repo_url="https://example.com/repo",
            commit_sha="a" * 40,
            workdir=workdir,
            intake_result=intake,
            deps=deps,
            cost_guard=cost_guard,
            run_id="run-4",
        )

    assert result.verdict == "BLOCKED"
    assert len(result.attempts) == 3
    assert all(a.gate_decision == "DECLINED" for a in result.attempts)
    assert cost_guard.attempts_used("run-4") == 3
    # Only the initial execution happened — a DECLINED proposal never
    # triggers a re-execution.
    assert len(sandbox_runner.calls) == 1


# --- Sandbox-level error (e.g. wall-clock exceeded) doesn't crash ----------


def test_sandbox_error_produces_timeout_verdict_not_a_crash():
    train_py = "def run(): pass\n"
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        workdir = Path(d)
        _write_files(workdir, {"train.py": train_py})
        intake = _intake({"train.py": train_py})

        recon_client = _FakeChatClient([json.dumps({"entrypoint": "train.py", "confidence": 0.9})])

        def _raising_runner(**kwargs):
            raise SandboxError("sandbox execution exceeded 60s wall clock")

        deps = _base_deps(recon_client, _FakeChatClient([]), None, _raising_runner)

        result = run_pipeline(
            repo_url="https://example.com/repo",
            commit_sha="a" * 40,
            workdir=workdir,
            intake_result=intake,
            deps=deps,
            cost_guard=CostGuard(daily_cost_ceiling_usd=100),
            run_id="run-5",
        )

    assert result.verdict == "TIMEOUT"


# --- The final certificate's passport hash is real and verifiable ----------


def test_final_certificate_passport_hash_verifies():
    train_py = "def run():\n    print('ok')\n\nrun()\n"
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        workdir = Path(d)
        _write_files(workdir, {"train.py": train_py})
        intake = _intake({"train.py": train_py})

        recon_client = _FakeChatClient([json.dumps({"entrypoint": "train.py", "confidence": 0.9})])
        sandbox_runner = _FakeSandboxRunner([_sandbox_result(0, stdout="ok\n")])
        deps = _base_deps(recon_client, _FakeChatClient([]), None, sandbox_runner)

        result = run_pipeline(
            repo_url="https://example.com/repo",
            commit_sha="a" * 40,
            workdir=workdir,
            intake_result=intake,
            deps=deps,
            cost_guard=CostGuard(daily_cost_ceiling_usd=100),
            run_id="run-6",
        )

    certificate = {
        "repo_url": result.repo_url,
        "commit_sha": result.commit_sha,
        "build_plan": result.build_plan,
        "full_log": result.full_log,
        "diffs": [a.as_dict() for a in result.attempts],
        "verdict": result.verdict,
        "timestamp": result.timestamp,
        "reproduction_passport_hash": result.reproduction_passport_hash,
    }
    assert verify_certificate(certificate) is True


def test_tampered_certificate_fails_verification():
    train_py = "def run():\n    print('ok')\n\nrun()\n"
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        workdir = Path(d)
        _write_files(workdir, {"train.py": train_py})
        intake = _intake({"train.py": train_py})

        recon_client = _FakeChatClient([json.dumps({"entrypoint": "train.py", "confidence": 0.9})])
        sandbox_runner = _FakeSandboxRunner([_sandbox_result(0, stdout="ok\n")])
        deps = _base_deps(recon_client, _FakeChatClient([]), None, sandbox_runner)

        result = run_pipeline(
            repo_url="https://example.com/repo",
            commit_sha="a" * 40,
            workdir=workdir,
            intake_result=intake,
            deps=deps,
            cost_guard=CostGuard(daily_cost_ceiling_usd=100),
            run_id="run-7",
        )

    certificate = {
        "repo_url": result.repo_url,
        "commit_sha": result.commit_sha,
        "build_plan": result.build_plan,
        "full_log": result.full_log,
        "diffs": [a.as_dict() for a in result.attempts],
        "verdict": "RUNS_CLEAN",  # already true here, so flip full_log instead
        "timestamp": result.timestamp,
        "reproduction_passport_hash": result.reproduction_passport_hash,
    }
    certificate["full_log"] = certificate["full_log"] + "\n(tampered)"
    assert verify_certificate(certificate) is False


# --- §9 cost guard: daily ceiling must actually stop spend, not just be
# documented ------------------------------------------------------------


def test_sandbox_cost_is_actually_recorded_in_the_cost_guard():
    train_py = "def run():\n    print('ok')\n\nrun()\n"
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        workdir = Path(d)
        _write_files(workdir, {"train.py": train_py})
        intake = _intake({"train.py": train_py})

        recon_client = _FakeChatClient([json.dumps({"entrypoint": "train.py", "confidence": 0.9})])
        sandbox_runner = _FakeSandboxRunner([_sandbox_result(0, stdout="ok\n", cost=0.42)])
        deps = _base_deps(recon_client, _FakeChatClient([]), None, sandbox_runner)
        cost_guard = CostGuard(daily_cost_ceiling_usd=100)

        run_pipeline(
            repo_url="https://example.com/repo",
            commit_sha="a" * 40,
            workdir=workdir,
            intake_result=intake,
            deps=deps,
            cost_guard=cost_guard,
            run_id="run-8",
        )

    # Not just "was called" — the guard's own running total actually
    # reflects the sandbox's real reported cost.
    assert cost_guard.spent_today_usd == pytest.approx(0.42)


def test_daily_cost_ceiling_already_exhausted_refuses_to_start_execution():
    train_py = "def run():\n    print('ok')\n\nrun()\n"
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        workdir = Path(d)
        _write_files(workdir, {"train.py": train_py})
        intake = _intake({"train.py": train_py})

        recon_client = _FakeChatClient([json.dumps({"entrypoint": "train.py", "confidence": 0.9})])
        # Must never be called: the daily budget is already spent before
        # run_pipeline is even invoked.
        sandbox_runner = _FakeSandboxRunner([])
        deps = _base_deps(recon_client, _FakeChatClient([]), None, sandbox_runner)

        cost_guard = CostGuard(daily_cost_ceiling_usd=1.0)
        cost_guard.record_spend(1.5)  # already over the ceiling

        result = run_pipeline(
            repo_url="https://example.com/repo",
            commit_sha="a" * 40,
            workdir=workdir,
            intake_result=intake,
            deps=deps,
            cost_guard=cost_guard,
            run_id="run-9",
        )

    assert result.verdict == "NOT_ATTEMPTABLE"
    assert sandbox_runner.calls == []


def test_daily_cost_ceiling_hit_mid_repair_stops_the_loop_without_crashing():
    train_py = textwrap.dedent(
        """\
        def evaluate(m):
            return m

        def run():
            x = 1 / 0
            evaluate(None)

        run()
        """
    )
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        workdir = Path(d)
        _write_files(workdir, {"train.py": train_py})
        intake = _intake({"train.py": train_py})

        recon_client = _FakeChatClient(
            [json.dumps({"entrypoint": "train.py", "confidence": 0.9, "eval_call_names": ["evaluate"]})]
        )
        good_diff = _unified_diff(
            "train.py",
            train_py,
            textwrap.dedent(
                """\
                def evaluate(m):
                    return m

                def run():
                    x = 1
                    evaluate(None)

                run()
                """
            ),
        )
        repair_client = _FakeChatClient([json.dumps({"diff": good_diff, "explanation": "fixed the division"})])

        # The initial execution spends the entire daily ceiling for real;
        # the re-execution after the gate-approved patch must never be
        # attempted once that ceiling is reached.
        sandbox_runner = _FakeSandboxRunner(
            [_sandbox_result(1, stderr="ZeroDivisionError: division by zero", cost=1.5)]
        )
        deps = _base_deps(recon_client, repair_client, None, sandbox_runner)
        cost_guard = CostGuard(daily_cost_ceiling_usd=1.0)

        result = run_pipeline(
            repo_url="https://example.com/repo",
            commit_sha="a" * 40,
            workdir=workdir,
            intake_result=intake,
            deps=deps,
            cost_guard=cost_guard,
            run_id="run-10",
        )

    assert result.verdict == "BLOCKED"
    assert len(sandbox_runner.calls) == 1  # the re-execution never happened
    assert "cost ceiling" in result.full_log
