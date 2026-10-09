"""harness-v1.10 flag mode after the independent review of rc6: the flag mode decides exactly what the checks-off (harness-v1.9.0) flow decides.

The review reproduced three ways rc6's flag mode changed a decision, all because the tracer ran inside the candidate run being judged: its report on stderr defeated
the exit-zero check (an argparse usage text with exit 0 became a pass), its output kept a silent run alive at the smoke limit, and a repository line starting with its
marker could end the run on an exception. From rc7 the flag mode runs the static half only (pure); the tracer runs in refuse mode alone. Each test below runs the same
repository, model replies and fake cloud with behaviour_mode "off" and "flag" and requires the same decisions (the review's reproductions, kept as regressions)."""

from __future__ import annotations

import v140_cloud
from app.services import behaviour
from test_behaviour_orchestrator import APT_CANDIDATE, BUNDLE, DECLINE, FAILURE, PLAIN, TRACED, _deps_mode, _fixture, _nonce_of, _report, _run
from test_v140_pipeline import _Chat, _edit, _Ultra

USAGE = "usage: main.py [-h] --data DATA\n"
EXECS = (TRACED, PLAIN, "python main.py")
BOMB = "RERUN_BEHAVIOUR " + "[" * 60000 + "]" * 60000 + "\n"


def _shape(r):
    return (r.verdict, r.taxonomy_code, [(a.origin, a.gate_decision, a.candidate, a.chosen, a.exit_code) for a in r.attempts])


def _both(tmp_path, monkeypatch, cloud_of, replies, choices, **deps_over):
    out = {}
    for mode in ("off", "flag"):
        where = tmp_path / mode
        where.mkdir(parents=True, exist_ok=True)
        _fixture(where)
        cloud = cloud_of(monkeypatch)
        deps = _deps_mode(_Chat(list(replies), "repair model"), _Ultra(list(choices)), mode)
        for k, v in deps_over.items():
            setattr(deps, k, v)
        result, _ = _run(where, deps)
        out[mode] = (result, cloud)
    return out


def _usage_cloud(monkeypatch):
    def behaviour_of(shell, built, files):
        if shell not in EXECS:
            return None
        if not any("numpy==1.19.5" in b for b in built):
            return 1, "", "ModuleNotFoundError: No module named 'numpy'\n"
        if any("libfoo-dev" in b for b in built):
            return 0, USAGE, (_report(_nonce_of(built)) if shell == TRACED else "")   # the real tracer writes its report after the usage text
        return 1, "", FAILURE

    return v140_cloud.install(monkeypatch, behaviour_of)


def test_an_exit_zero_the_v190_flow_overrules_stays_overruled_in_flag_mode(tmp_path, monkeypatch):
    runs = _both(tmp_path, monkeypatch, _usage_cloud, [APT_CANDIDATE, DECLINE, DECLINE], [{"chosen": 1, "reasoning": "the header"}])
    off, flag = runs["off"][0], runs["flag"][0]
    assert off.verdict != "RUNS_AFTER_REPAIR"                                      # D-46: a usage-only exit 0 is not a pass
    assert _shape(flag) == _shape(off)


def _layer_cloud(monkeypatch):
    def behaviour_of(shell, built, files):
        if shell not in EXECS:
            return None
        if not any("numpy==1.19.5" in b for b in built):
            return 1, "", "ModuleNotFoundError: No module named 'numpy'\n"
        src = files.get("main.py", b"").decode()
        ran_before = any(b in EXECS for b in built)
        report = _report(_nonce_of(built)) if shell == TRACED else ""
        if any("libfoo-dev" in b for b in built):
            if "flush=True" in src and ran_before:
                return 0, "RERUN_SMOKE_ALIVE: still running after 60s with output and no traceback", report
            return 1, "", "Traceback (most recent call last):\n  File \"main.py\", line 3, in <module>\nFileNotFoundError: cache/data.bin\n" + report
        return 1, "", FAILURE + report

    return v140_cloud.install(monkeypatch, behaviour_of)


def test_the_next_round_branches_from_the_same_image_in_both_modes(tmp_path, monkeypatch):
    round2 = _edit("print(VALUE)\n", "print(VALUE, flush=True)\n", "flush the output")
    runs = _both(tmp_path, monkeypatch, _layer_cloud, [APT_CANDIDATE, DECLINE, DECLINE, round2, DECLINE, DECLINE],
                 [{"chosen": 1, "reasoning": "the header"}, {"chosen": 1, "reasoning": "flush"}], max_attempts=2)
    assert _shape(runs["flag"][0]) == _shape(runs["off"][0])


def _bomb_cloud(monkeypatch):
    def behaviour_of(shell, built, files):
        if shell not in EXECS:
            return None
        if not any("numpy==1.19.5" in b for b in built):
            return 1, "", "ModuleNotFoundError: No module named 'numpy'\n"
        if any("libfoo-dev" in b for b in built):
            return 0, "RERUN_SMOKE_ALIVE: still running after 60s with output and no traceback", BOMB
        return 1, "", FAILURE

    return v140_cloud.install(monkeypatch, behaviour_of)


def test_a_repository_line_with_the_marker_changes_nothing_in_flag_mode(tmp_path, monkeypatch):
    runs = _both(tmp_path, monkeypatch, _bomb_cloud, [APT_CANDIDATE, DECLINE, DECLINE], [{"chosen": 1, "reasoning": "the header"}])
    assert _shape(runs["flag"][0]) == _shape(runs["off"][0]) and runs["off"][0].verdict == "RUNS_AFTER_REPAIR"


def test_the_report_reader_survives_a_hostile_line_in_refuse_mode():
    clean, reports = behaviour.split_report("before\n" + BOMB + "after\n", "n")
    assert clean == "before\nafter\n" and reports == []
    huge = "RERUN_BEHAVIOUR " + '{"nonce": "n", "pad": "' + "x" * (behaviour.REPORT_LINE_LIMIT + 10) + '"}\n'
    assert behaviour.split_report(huge, "n") == ("", [])


def test_the_tracer_is_never_installed_or_named_in_flag_mode(tmp_path, monkeypatch):
    runs = _both(tmp_path, monkeypatch, _usage_cloud, [BUNDLE, DECLINE, DECLINE], [{"chosen": 1, "reasoning": "the header"}])
    flag, cloud = runs["flag"]
    assert TRACED not in cloud.ran and not [c for c in cloud.ran if " behaviour " in c and c.startswith("python3 -c")]
    assert _shape(flag) == _shape(runs["off"][0])


# ---------------------------------------------------------------------------------------------------------------------------------------------------
# attribution in the single-candidate flow (the review's finding 6): every record of the applied flagged patch carries the flag

def _single_cloud(stop_repair: bool):
    def install(monkeypatch):
        def behaviour_of(shell, built, files):
            if shell not in (PLAIN, "python main.py"):
                return None
            if not any("numpy==1.19.5" in b for b in built):
                return 1, "", "ModuleNotFoundError: No module named 'numpy'\n"
            if any("libfoo-dev" in b for b in built):
                return 0, "RERUN_SMOKE_ALIVE: still running after 60s with output and no traceback", ""
            return 1, "", FAILURE

        return v140_cloud.install(monkeypatch, behaviour_of, stops=("libfoo-dev",) if stop_repair else ())
    return install


def _single(tmp_path, monkeypatch, stop_repair: bool):
    tmp_path.mkdir(parents=True, exist_ok=True)
    _fixture(tmp_path)
    _single_cloud(stop_repair)(monkeypatch)
    deps = _deps_mode(_Chat([BUNDLE], "repair model"), _Ultra(), "flag")
    deps.candidates_per_round = 1
    result, _ = _run(tmp_path, deps)
    return result


def test_the_single_candidate_flow_flags_the_adopted_patch(tmp_path, monkeypatch):
    result = _single(tmp_path, monkeypatch, stop_repair=False)
    assert result.verdict == "RUNS_AFTER_REPAIR" and result.outcome_levels.get("review_required") == [behaviour.COMPUTATION_CHANGED]


def test_the_single_candidate_flow_keeps_the_flag_when_the_rerun_is_stopped(tmp_path, monkeypatch):
    result = _single(tmp_path, monkeypatch, stop_repair=True)
    model = [a for a in result.attempts if a.origin == "model"]
    assert any(a.gate_decision == "PASS" and "VALUE = 1" in a.diff_text for a in model)       # the flagged patch was applied
    assert result.outcome_levels.get("review_required") == [behaviour.COMPUTATION_CHANGED]


def test_the_lock_compiler_never_sees_rerun_s_credentials():
    """independent review of rc6 (finding 13): `uv pip compile` may run third-party setup.py code; RERUN's keys are not in its environment."""
    import inspect

    from app.services import time_machine

    env = time_machine.scrubbed_env({"NEBIUS_API_KEY": "k", "NEBIUS_PROJECT_ID": "p", "TAVILY_API_KEY": "t", "PATH": "/usr/bin", "HOME": "/root"})
    assert env == {"PATH": "/usr/bin", "HOME": "/root"}
    assert "env=scrubbed_env()" in inspect.getsource(time_machine._default_runner) or "scrubbed_env" in inspect.getsource(time_machine)


# ---------------------------------------------------------------------------------------------------------------------------------------------------
# the fifth (focused) review, of rc7: its reproductions, kept as regressions for rc8

from app.services import adjudicator as _adjudicator  # noqa: E402
from app.services import outcome_levels as _levels  # noqa: E402
from app.services.orchestrator import OrchestratorError  # noqa: E402
from test_behaviour_orchestrator import _cloud  # noqa: E402


def _apply_fails(workdir, diff):
    raise OrchestratorError("error: patch failed: main.py:2")


def test_a_patch_that_never_applied_carries_its_flag_but_no_review(tmp_path, monkeypatch):
    _fixture(tmp_path)
    _cloud(monkeypatch, report={})
    deps = _deps_mode(_Chat([BUNDLE], "repair model"), _Ultra(), "flag")
    deps.candidates_per_round = 1
    deps.apply_diff = _apply_fails
    result, _ = _run(tmp_path, deps)
    last = [a for a in result.attempts if a.origin == "model"][-1]
    assert last.gate_decision == "PASS" and last.exit_code is None                              # never applied, never run
    assert last.behaviour["flagged"] is True and last.behaviour["not_applied"] is True
    assert not result.outcome_levels.get("review_required")


def test_the_multi_candidate_record_of_a_patch_that_did_not_apply_keeps_its_flag_unadopted(tmp_path, monkeypatch):
    from app.services import orchestrator as orch

    _fixture(tmp_path)
    _cloud(monkeypatch, report={})

    def no_files(*a, **k):
        raise OrchestratorError("error: patch failed")

    monkeypatch.setattr(orch, "_candidate_files", no_files)
    result, _ = _run(tmp_path, _deps_mode(_Chat([BUNDLE, DECLINE, DECLINE], "repair model"), _Ultra(), "flag"))
    rec = [a for a in result.attempts if a.origin == "model" and a.gate_decision == "PASS"]
    assert rec and rec[0].behaviour["flagged"] is True and rec[0].behaviour["not_applied"] is True
    assert not result.outcome_levels.get("review_required")


def _evidence(tmp_path, monkeypatch, **deps_over):
    seen = {}
    real = _adjudicator.adjudicate

    def spy(*a, **kw):
        seen.setdefault(spy.mode, []).append(kw.get("evidence_summary"))
        return real(*a, **kw)

    monkeypatch.setattr(_adjudicator, "adjudicate", spy)
    for mode in ("off", "flag"):
        spy.mode = mode
        where = tmp_path / mode
        where.mkdir(parents=True, exist_ok=True)
        _fixture(where)
        _cloud(monkeypatch, report={})
        deps = _deps_mode(_Chat([BUNDLE, DECLINE, DECLINE], "repair model"), _Ultra(), mode)
        for k, v in deps_over.items():
            setattr(deps, k, v)
        _run(where, deps)
    return seen


def test_the_final_adjudicator_sees_the_same_evidence_in_both_modes(tmp_path, monkeypatch):
    seen = _evidence(tmp_path / "single", monkeypatch, candidates_per_round=1, apply_diff=_apply_fails)
    assert seen["flag"] == seen["off"]


def test_the_final_adjudicator_sees_the_same_evidence_with_the_default_three_candidates(tmp_path, monkeypatch):
    from app.services import orchestrator as orch

    def no_files(*a, **k):
        raise OrchestratorError("error: patch failed")

    monkeypatch.setattr(orch, "_candidate_files", no_files)
    seen = _evidence(tmp_path / "multi", monkeypatch)
    assert seen["flag"] == seen["off"]


def test_a_figures_file_with_nan_is_no_headline(tmp_path):
    import json
    from pathlib import Path

    from app.routers import batch

    good = json.loads((Path(__file__).resolve().parents[2] / "reports" / "v1.9" / "figures.json").read_text(encoding="utf-8"))
    target = tmp_path / "reports" / "v1.9"
    target.mkdir(parents=True)
    for bad_value in (float("nan"), float("inf")):
        bad = {**good, "figures": {**good["figures"], "diagnosis_strict_pct": {**good["figures"]["diagnosis_strict_pct"], "value": bad_value}}}
        (target / "figures.json").write_text(json.dumps(bad), encoding="utf-8")
        assert batch.headline(tmp_path, []) is None


def test_the_credential_scrub_ignores_case_like_settings_does():
    from app.services import time_machine

    assert time_machine.scrubbed_env({"tavily_api_key": "t", "Nebius_Api_Key": "k", "PATH": "/usr/bin"}) == {"PATH": "/usr/bin"}


def test_review_findings_skip_a_record_that_never_applied():
    flagged = {"mode": "flag", "flagged": True, "static": [{"reason": "COMPUTATION_CHANGED"}]}
    base = {"origin": "model", "gate_decision": "PASS", "exit_code": None, "diff_text": "x"}
    assert _levels.review_required({"verdict": "BLOCKED", "attempts": [{**base, "behaviour": {**flagged, "not_applied": True}}]}) == ()
