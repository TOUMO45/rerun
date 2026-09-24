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


def _base_deps(recon_client, repair_client, adjudicator_client, sandbox_runner, tavily_client=None) -> PipelineDeps:
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
        tavily_client=tavily_client,
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
    # The stable recon code travels in indeterminate_reason, which is what
    # the API stores and Certificate.tsx renders.
    assert result.indeterminate_reason.startswith("ENTRYPOINT_UNCLEAR: ")
    assert result.taxonomy_code is None
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


def test_configured_default_sandbox_image_reaches_the_build_plan_and_sandbox_call():
    # NEBIUS_SANDBOX_IMAGE (PipelineDeps.default_sandbox_image) must
    # actually change what the sandbox is asked to run, not just exist as
    # an unread setting between config.py and planner.py.
    train_py = "def run():\n    print('ok')\n\nrun()\n"
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        workdir = Path(d)
        _write_files(workdir, {"train.py": train_py})
        intake = _intake({"train.py": train_py})

        recon_client = _FakeChatClient([json.dumps({"entrypoint": "train.py", "confidence": 0.9})])
        sandbox_runner = _FakeSandboxRunner([_sandbox_result(0, stdout="ok\n")])
        deps = _base_deps(recon_client, _FakeChatClient([]), None, sandbox_runner)
        deps.default_sandbox_image = "python:3.12-bullseye"

        result = run_pipeline(
            repo_url="https://example.com/repo",
            commit_sha="a" * 40,
            workdir=workdir,
            intake_result=intake,
            deps=deps,
            cost_guard=CostGuard(daily_cost_ceiling_usd=100),
            run_id="run-15",
        )

    assert result.build_plan["base_image"] == "python:3.12-bullseye"
    assert sandbox_runner.calls[0]["base_image"] == "python:3.12-bullseye"


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


# --- BLOCKED: repair keeps passing-but-not-fixing until attempts exhausted --


def test_blocked_after_exactly_max_attempts_even_when_every_patch_passes_the_gate(tmp_path):
    """Different code path than test_blocked_after_exhausting_attempts:
    that test only exercises DECLINED proposals (the repairer never even
    proposes a diff), so the loop never reaches apply_diff/re-execute at
    all. This test's repairer proposes a genuinely gate-PASSING diff on
    every attempt (a harmless comment, real unified diff, real gate,
    real re-execution) that never actually fixes the crash — verifying
    the bounded loop (§5.4: max_attempts_per_run) stops at EXACTLY that
    many attempts, not one more or one fewer, even when every single
    attempt takes the full apply-and-re-execute path rather than being
    declined or rejected up front.
    """
    train_py = textwrap.dedent(
        """\
        def run():
            raise RuntimeError('boom')

        run()
        """
    )
    _write_files(tmp_path, {"train.py": train_py})
    intake = _intake({"train.py": train_py})

    recon_client = _FakeChatClient([json.dumps({"entrypoint": "train.py", "confidence": 0.9})])

    # Each successive diff is computed against the PREVIOUS attempt's own
    # output, since apply_diff really writes to disk between attempts —
    # a harmless, additive comment that never touches the real bug.
    contents = [train_py]
    diffs = []
    for i in range(1, 4):
        previous = contents[-1]
        updated = previous + f"# repair attempt {i} note\n"
        diffs.append(_unified_diff("train.py", previous, updated))
        contents.append(updated)

    repair_client = _FakeChatClient(
        [json.dumps({"diff": d, "explanation": f"attempt {i}"}) for i, d in enumerate(diffs, start=1)]
    )

    # Initial failure, then one re-execution failure per repair attempt —
    # the crash is never actually fixed by any of the three patches.
    sandbox_runner = _FakeSandboxRunner(
        [_sandbox_result(1, stderr="RuntimeError: boom") for _ in range(4)]
    )

    deps = _base_deps(recon_client, repair_client, None, sandbox_runner)
    cost_guard = CostGuard(daily_cost_ceiling_usd=100, max_attempts_per_run=3)

    result = run_pipeline(
        repo_url="https://example.com/repo",
        commit_sha="a" * 40,
        workdir=tmp_path,
        intake_result=intake,
        deps=deps,
        cost_guard=cost_guard,
        run_id="run-max-attempts",
    )

    assert result.verdict == "BLOCKED"
    assert len(result.attempts) == 3
    assert all(a.gate_decision == "PASS" for a in result.attempts)
    assert cost_guard.attempts_used("run-max-attempts") == 3
    # Exactly 3 repair-model calls (one per attempt), not 2 or 4.
    assert len(repair_client.calls) == 3
    # Exactly 4 sandbox calls: the initial execution plus one
    # re-execution per attempt — never a 5th (a 4th repair attempt).
    assert len(sandbox_runner.calls) == 4
    # All three patches really were applied to disk in order.
    final_content = (tmp_path / "train.py").read_text(encoding="utf-8")
    assert final_content == contents[-1]
    assert final_content.count("# repair attempt") == 3


def test_gate_approved_patch_that_fails_real_git_apply_does_not_crash_the_pipeline(tmp_path):
    """Found live during this session's audit: tamper_gate.py's own AST
    reconstruction (_apply_patched_file) never cross-validates a diff's
    claimed context/removed lines against the real file it was given —
    it only trusts the diff's own structure. A diff built against a
    slightly stale or misremembered view of the file (a realistic model
    failure mode, not contrived) can therefore PASS the gate yet still
    be refused by the real `git apply` orchestrator.py's
    _apply_diff_with_git runs next. That raised OrchestratorError was
    never caught anywhere in orchestrator.py, crashing the whole pipeline
    with an unhandled exception instead of producing an honest verdict —
    directly against §0's "never fake a result... the taxonomy/verdict
    system exists precisely to say so honestly."
    """
    real_content = textwrap.dedent(
        """\
        def train():
            model = build_model()
            fit(model)
            evaluate(model)

        train()
        """
    )
    _write_files(tmp_path, {"train.py": real_content})
    intake = _intake({"train.py": real_content})

    # The diff's own claimed "before" text doesn't match the real file —
    # git apply will refuse it on context mismatch, even though the gate,
    # which never checks this, will pass it.
    claimed_original = real_content.replace("build_model()", "SOME_STALE_HALLUCINATED_CALL()")
    bad_diff = _unified_diff("train.py", claimed_original, real_content)

    recon_client = _FakeChatClient([json.dumps({"entrypoint": "train.py", "confidence": 0.9})])
    repair_client = _FakeChatClient(
        [
            json.dumps({"diff": bad_diff, "explanation": "fix"}),
            json.dumps({"diff": None, "explanation": "giving up"}),
            json.dumps({"diff": None, "explanation": "giving up"}),
        ]
    )
    sandbox_runner = _FakeSandboxRunner([_sandbox_result(1, stderr="RuntimeError: boom")])
    deps = _base_deps(recon_client, repair_client, None, sandbox_runner)

    result = run_pipeline(
        repo_url="https://example.com/repo",
        commit_sha="a" * 40,
        workdir=tmp_path,
        intake_result=intake,
        deps=deps,
        cost_guard=CostGuard(daily_cost_ceiling_usd=100, max_attempts_per_run=3),
        run_id="run-bad-apply",
    )

    assert result.verdict == "BLOCKED"
    assert len(result.attempts) == 3
    assert result.attempts[0].gate_decision == "PASS"  # the gate really did PASS it
    assert "failed to apply" in result.attempts[0].stderr_tail
    # The failed apply must never have touched the file on disk.
    assert (tmp_path / "train.py").read_text(encoding="utf-8") == real_content


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

    certificate = result.certificate()
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

    certificate = result.certificate()
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

    # Since model spend counts toward the ceiling (2026-09-24), an exhausted
    # budget stops the run before recon's model call — our own limit, so a
    # RECON_MODEL_ERROR (excluded from the Batch Lab denominator), never a
    # verdict on the repo. The sandbox is still never touched.
    assert result.verdict == "INDETERMINATE"
    assert result.indeterminate_reason.startswith("RECON_MODEL_ERROR: ")
    assert "daily cost ceiling" in result.indeterminate_reason
    assert recon_client.calls == []
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


def test_token_ceiling_already_exhausted_makes_recon_indeterminate_not_a_crash():
    # Proves the cost_guard threaded into recon.run_recon via orchestrator
    # actually reaches model_client.call_json_model — a per-attempt token
    # ceiling exhausted before recon even calls the model must produce a
    # graceful INDETERMINATE (§6.1), never an uncaught exception.
    train_py = "def run():\n    pass\n\nrun()\n"
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        workdir = Path(d)
        _write_files(workdir, {"train.py": train_py})
        intake = _intake({"train.py": train_py})

        recon_client = _FakeChatClient([json.dumps({"entrypoint": "train.py", "confidence": 0.9})])
        sandbox_runner = _FakeSandboxRunner([])  # must never be reached
        deps = _base_deps(recon_client, _FakeChatClient([]), None, sandbox_runner)

        cost_guard = CostGuard(daily_cost_ceiling_usd=100, max_tokens_per_attempt=1)

        result = run_pipeline(
            repo_url="https://example.com/repo",
            commit_sha="a" * 40,
            workdir=workdir,
            intake_result=intake,
            deps=deps,
            cost_guard=cost_guard,
            run_id="run-11",
        )

    assert result.verdict == "INDETERMINATE"
    assert "recon model call failed" in result.indeterminate_reason
    assert result.indeterminate_reason.startswith("RECON_MODEL_ERROR: ")
    assert sandbox_runner.calls == []


# --- Tavily: called at runtime, cited in the certificate --------------------


class _FakeTavilyClient:
    def __init__(self, response: dict):
        self.response = response
        self.last_call: dict | None = None

    def search(self, query, *, max_results, search_depth):
        self.last_call = {"query": query, "max_results": max_results, "search_depth": search_depth}
        return self.response


def test_tavily_is_called_during_repair_and_cited_on_the_attempt():
    train_py = "def run():\n    raise RuntimeError('boom')\n\nrun()\n"
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        workdir = Path(d)
        _write_files(workdir, {"train.py": train_py})
        intake = _intake({"train.py": train_py})

        recon_client = _FakeChatClient([json.dumps({"entrypoint": "train.py", "confidence": 0.9})])
        repair_client = _FakeChatClient([json.dumps({"diff": None, "explanation": "cannot fix"})])
        sandbox_runner = _FakeSandboxRunner([_sandbox_result(1, stderr="RuntimeError: boom")])
        tavily_client = _FakeTavilyClient(
            response={
                "results": [
                    {"title": "Fixing RuntimeError: boom", "url": "https://example.com/fix", "content": "do the thing"}
                ]
            }
        )
        deps = _base_deps(recon_client, repair_client, None, sandbox_runner, tavily_client=tavily_client)

        result = run_pipeline(
            repo_url="https://example.com/repo",
            commit_sha="a" * 40,
            workdir=workdir,
            intake_result=intake,
            deps=deps,
            cost_guard=CostGuard(daily_cost_ceiling_usd=100, max_attempts_per_run=1),
            run_id="run-12",
        )

    # Tavily was actually queried (not skipped just because a client exists).
    assert tavily_client.last_call is not None
    assert "boom" in tavily_client.last_call["query"]

    # The cited source reached the repair prompt Nemotron Super actually saw...
    sent_prompt = repair_client.calls[0]["user_prompt"]
    assert "https://example.com/fix" in sent_prompt

    # ...but it was not USED in any decision (the model declined), so since
    # 2026-09-24 it is logged, not cited on the certificate.
    assert len(result.attempts) == 1
    assert result.attempts[0].tavily_sources == ()
    assert "[citations] not cited (not used in a decision): https://example.com/fix" in result.full_log


def test_tavily_not_configured_still_completes_the_repair_loop():
    # §5 cut ladder: repair must still function without Tavily.
    train_py = "def run():\n    raise RuntimeError('boom')\n\nrun()\n"
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        workdir = Path(d)
        _write_files(workdir, {"train.py": train_py})
        intake = _intake({"train.py": train_py})

        recon_client = _FakeChatClient([json.dumps({"entrypoint": "train.py", "confidence": 0.9})])
        repair_client = _FakeChatClient([json.dumps({"diff": None, "explanation": "cannot fix"})])
        sandbox_runner = _FakeSandboxRunner([_sandbox_result(1, stderr="RuntimeError: boom")])
        deps = _base_deps(recon_client, repair_client, None, sandbox_runner, tavily_client=None)

        result = run_pipeline(
            repo_url="https://example.com/repo",
            commit_sha="a" * 40,
            workdir=workdir,
            intake_result=intake,
            deps=deps,
            cost_guard=CostGuard(daily_cost_ceiling_usd=100, max_attempts_per_run=1),
            run_id="run-13",
        )

    assert result.verdict == "BLOCKED"
    assert result.attempts[0].tavily_sources == ()


def test_tavily_search_failure_does_not_crash_the_pipeline():
    train_py = "def run():\n    raise RuntimeError('boom')\n\nrun()\n"
    import tempfile

    class _RaisingTavilyClient:
        def search(self, query, *, max_results, search_depth):
            raise RuntimeError("connection refused")

    with tempfile.TemporaryDirectory() as d:
        workdir = Path(d)
        _write_files(workdir, {"train.py": train_py})
        intake = _intake({"train.py": train_py})

        recon_client = _FakeChatClient([json.dumps({"entrypoint": "train.py", "confidence": 0.9})])
        repair_client = _FakeChatClient([json.dumps({"diff": None, "explanation": "cannot fix"})])
        sandbox_runner = _FakeSandboxRunner([_sandbox_result(1, stderr="RuntimeError: boom")])
        deps = _base_deps(recon_client, repair_client, None, sandbox_runner, tavily_client=_RaisingTavilyClient())

        result = run_pipeline(
            repo_url="https://example.com/repo",
            commit_sha="a" * 40,
            workdir=workdir,
            intake_result=intake,
            deps=deps,
            cost_guard=CostGuard(daily_cost_ceiling_usd=100, max_attempts_per_run=1),
            run_id="run-14",
        )

    assert result.verdict == "BLOCKED"  # not a crash
    assert "search failed" in result.full_log


# --- on_event: real-time progress streaming (§4: SSE /runs/{id}/stream) ----


def test_on_event_fires_for_every_log_line_in_real_time_order():
    train_py = "def run():\n    print('ok')\n\nrun()\n"
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        workdir = Path(d)
        _write_files(workdir, {"train.py": train_py})
        intake = _intake({"train.py": train_py})

        recon_client = _FakeChatClient([json.dumps({"entrypoint": "train.py", "confidence": 0.9})])
        sandbox_runner = _FakeSandboxRunner([_sandbox_result(0, stdout="ok\n")])
        deps = _base_deps(recon_client, _FakeChatClient([]), None, sandbox_runner)

        received: list[str] = []
        result = run_pipeline(
            repo_url="https://example.com/repo",
            commit_sha="a" * 40,
            workdir=workdir,
            intake_result=intake,
            deps=deps,
            cost_guard=CostGuard(daily_cost_ceiling_usd=100),
            run_id="run-16",
            on_event=received.append,
        )

    # on_event received exactly the same lines, in the same order, as the
    # final full_log — not a subset, not reordered, not "only the summary".
    assert received == result.full_log.split("\n")
    assert received[0].startswith("[intake]")
    assert any("[recon]" in line for line in received)
    assert any("[sandbox]" in line for line in received)


def test_on_event_is_optional_and_changes_nothing_when_omitted():
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
            run_id="run-17",
        )

    assert result.verdict == "RUNS_CLEAN"


def test_on_event_fires_even_on_the_indeterminate_short_circuit_path():
    train_py = "def run():\n    pass\n"
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        workdir = Path(d)
        _write_files(workdir, {"train.py": train_py})
        intake = _intake({"train.py": train_py})

        recon_client = _FakeChatClient([json.dumps({"entrypoint": "train.py", "confidence": 0.1})])
        deps = _base_deps(recon_client, _FakeChatClient([]), None, _FakeSandboxRunner([]))

        received: list[str] = []
        result = run_pipeline(
            repo_url="https://example.com/repo",
            commit_sha="a" * 40,
            workdir=workdir,
            intake_result=intake,
            deps=deps,
            cost_guard=CostGuard(daily_cost_ceiling_usd=100),
            run_id="run-18",
            on_event=received.append,
        )

    assert result.verdict == "INDETERMINATE"
    assert any("INDETERMINATE" in line for line in received)
