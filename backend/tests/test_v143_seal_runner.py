"""The v1.4.3 seal runner (reports/corpus-v2.1/v1.4.3/seal/run_seal_v143.py), exercised OFFLINE before any money is spent: its plan, its refusals, its precondition, the new checks (S1-S4) end to
end against the fake ConTree cloud through the real sandbox runner, the wiring of the earlier seals' stages, and how a stage that stops is recorded. The live seal measures what this
cannot: the real API's limit and flags."""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

import pytest

import v140_cloud
from app.services import sandbox
from app.services.cost_guard import CostGuard
from test_v142_seal_runner import _behaviour as behaviour_v142

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "reports" / "corpus-v2.1" / "v1.4.3" / "seal" / "run_seal_v143.py"
BLOBS = {f: f"blob-{Path(f).name}" for f in ("backend/app/services/sandbox.py", "backend/app/services/sandbox_limits.py", "backend/app/services/runner_env.py",
                                              "backend/app/services/smoke_exec.py", "backend/app/services/runner_hooks.py")}


@pytest.fixture
def seal(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("run_seal_v143", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "OUT", tmp_path / "seal")
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "blobs", lambda: dict(BLOBS))
    return module


def emit_behaviour(seal):
    """`python3 emit.py N CODE` and `python3 emit_glyph.py N`: what the writers print, computed from the same constants the seal expects."""
    def behaviour(shell, built, files):
        m = re.fullmatch(r"python3 emit\.py (\d+) (\d+)", shell)
        if m:
            return int(m.group(2)), "stdout-line\n", seal.expected_stderr(int(m.group(1)))
        g = re.fullmatch(r"python3 emit_glyph\.py (\d+)", shell)
        if g:
            return 1, "", chr(0x2588) * int(g.group(1))
        return None

    return behaviour


# --- plan and refusals --------------------------------------------------------------------------------------------------------

def test_the_plan_runs_nothing_and_fits_the_owners_cap(seal, capsys, monkeypatch):
    assert seal.main([]) == 0
    out = capsys.readouterr().out
    assert "PLAN ONLY" in out and "ESTIMATED" in out
    rows = seal.plan()
    assert {r["stage"] for r in rows} == set(seal.STAGES)
    total = sum(r["usd"] for r in rows)
    assert 1.0 < total < seal.MAX_SEAL_USD  # the whole re-verification costs about what the earlier seals' records say, under the cap
    assert not [r for r in rows if "E1b" in r["op"]]  # the informational allocation probe is not repeated
    assert {"S1", "S2", "S2b", "S3", "S4"} <= {r["op"] for r in rows if r["stage"] == "new"}


def test_no_run_without_go_a_cap_and_not_above_the_owners_bound(seal, capsys, monkeypatch):
    assert seal.MAX_SEAL_USD == 1.50
    assert seal.main(["--go"]) == 2 and "--max-usd is required" in capsys.readouterr().err
    assert seal.main(["--go", "--max-usd", "1.51"]) == 2
    assert seal.main(["--go", "--max-usd", "0"]) == 2


def test_the_seal_runs_only_against_the_release_candidate(seal):
    clean = {("rev-parse", "--verify"): "rc-sha", ("diff", "--name-only"): "", ("status", "--porcelain"): "", ("rev-parse", "harness-v1.4.3-rc"): "rc-sha", ("rev-parse", "HEAD"): "head-sha"}

    def git(*args):
        return next(v for k, v in clean.items() if args[: len(k)] == k)

    assert seal.precondition(git) == {"harness_rc_tag": "harness-v1.4.3-rc", "rc_commit": "rc-sha", "head": "head-sha"}
    clean[("diff", "--name-only")] = "backend/app/services/sandbox.py\n"
    with pytest.raises(SystemExit, match="not those of harness-v1.4.3-rc"):
        seal.precondition(git)
    clean[("diff", "--name-only")], clean[("status", "--porcelain")] = "", " M scripts/x.py\n"
    with pytest.raises(SystemExit, match="uncommitted"):
        seal.precondition(git)


def test_a_missing_release_candidate_tag_is_a_clear_refusal_not_a_traceback(seal):
    import subprocess

    def git(*args):
        raise subprocess.CalledProcessError(128, ["git", *args])

    with pytest.raises(SystemExit, match="tag harness-v1.4.3-rc does not exist"):
        seal.precondition(git)


def test_a_summary_of_another_release_candidate_or_other_blobs_is_refused_but_a_later_data_commit_is_not(seal):
    state = {"head": "h1", "rc_commit": "rc1"}
    seal.OUT.mkdir(parents=True)
    (seal.OUT / "SEAL_RUN.json").write_text(json.dumps({"head": "h1", "rc_commit": "rc1", "blobs": BLOBS, "stages": {}}), encoding="utf-8")
    assert seal._load_summary(BLOBS, state)["rc_commit"] == "rc1"
    assert seal._load_summary(BLOBS, {"head": "h2-after-a-data-commit", "rc_commit": "rc1"})["rc_commit"] == "rc1"  # partial records may be committed between invocations
    with pytest.raises(SystemExit, match="another release candidate"):
        seal._load_summary(BLOBS, {"head": "h1", "rc_commit": "rc2"})
    with pytest.raises(SystemExit, match="another release candidate"):
        seal._load_summary({**BLOBS, "backend/app/services/sandbox.py": "edited"}, state)


# --- the new checks -----------------------------------------------------------------------------------------------------------

def _run_new(seal, monkeypatch, **kw):
    cloud = v140_cloud.install(monkeypatch, emit_behaviour(seal), stops=("sleep 20",), **kw)
    guard = CostGuard(daily_cost_ceiling_usd=1.50)
    return cloud, guard, seal.run_new("key", "proj", guard, BLOBS)


def test_the_five_new_checks_pass_against_a_cloud_that_behaves_like_the_api(seal, monkeypatch):
    cloud, guard, docs = _run_new(seal, monkeypatch)
    assert [d["ok"] for d in docs] == [True] * 5
    s1, s2, s2b, s3, s4 = docs
    assert s1["streams"]["stderr"]["bytes"] == s1["expected_bytes"] > 200_000 and s1["streams"]["stderr"]["truncated"] is False
    assert s2["returned_bytes"] == sandbox.OUTPUT_LIMIT_BYTES and s2["streams"]["stderr"]["truncated"] is True and s2["harness_reason"].startswith("OUTPUT_TRUNCATED: ")
    assert s2["requested_bytes"] > sandbox.OUTPUT_LIMIT_BYTES and seal.MARKER not in s2["stderr_tail"]
    assert s2b["ends_with_replacement_character"] is True and s2b["glyph_bytes"] > sandbox.OUTPUT_LIMIT_BYTES and sandbox.OUTPUT_LIMIT_BYTES % 3 == 1
    assert s3["image"] and s3["exit_code"] == 0 and s3["run_id"] == s3["image"] in cloud.images
    assert s4["via"] == "server_result_timed_out" and s4["timed_out"] is True and s4["image"] == s3["image"]
    for name in ("S1_200kb_stderr_whole", "S2_stream_over_the_limit_flagged", "S2b_cut_inside_a_multibyte_character", "S3_run_on_image_reopens_a_kept_image",
                 "S4_run_on_image_stopped_at_its_limit"):
        record = json.loads((seal.OUT / "new" / f"{name}.json").read_text(encoding="utf-8"))
        assert record["code_blobs"] == BLOBS and record["run_id"] and record["ok"] is True
    assert guard.spent_today_usd > 0


def test_s1_fails_if_the_client_still_asks_for_the_old_limit(seal, monkeypatch):
    """Negative control: with the SDK's 65,535 bytes the 200 KB stream comes back cut, and the live seal would stop here."""
    monkeypatch.setattr(sandbox, "OUTPUT_LIMIT_BYTES", 65535)
    _, _, docs = _run_new(seal, monkeypatch)
    assert docs[0]["ok"] is False and docs[0]["streams"]["stderr"]["truncated"] is True and docs[0]["streams"]["stderr"]["bytes"] == 65535


def test_s2_fails_if_the_api_does_not_flag_the_cut(seal, monkeypatch):
    real_cut = v140_cloud._cut_bytes
    monkeypatch.setattr(v140_cloud, "_cut_bytes", lambda text, limit: (real_cut(text, limit)[0], False))  # an API that cuts but does not say so
    _, _, docs = _run_new(seal, monkeypatch)
    assert docs[1]["ok"] is False and docs[1]["harness_reason"] is None


def test_s2b_would_stop_the_seal_if_the_runner_let_the_sdk_decode_a_cut_character(seal, monkeypatch):
    """The failure the independent review found: asked for text, the SDK raises UnicodeDecodeError inside `.wait()` when the cut falls inside a character. With the byte request
    removed the fake raises exactly there, and the seal's S2b check does not pass."""
    monkeypatch.setattr(sandbox, "_byte_streams", lambda image: {})
    with pytest.raises(UnicodeDecodeError):
        _run_new(seal, monkeypatch)


def test_s4_records_the_client_wait_path_with_an_estimated_cost(seal, monkeypatch):
    real = sandbox.run_on_image

    def client_side(**kw):
        if kw["command"].startswith("sleep 20"):
            raise sandbox.SandboxTimeoutError("sandbox execution exceeded 3s wall clock", command=kw["command"], killed_seconds=3.0)
        return real(**kw)

    monkeypatch.setattr(sandbox, "run_on_image", client_side)
    _, guard, docs = _run_new(seal, monkeypatch)
    s4 = docs[4]
    assert s4["ok"] is True and s4["via"] == "client_wait_timeout" and "ESTIMATED" in s4["cost_tag"] and s4["cost_usd"] == pytest.approx(3 * 0.0152)
    assert guard.cost_events and guard.cost_events[-1]["rate_usd_per_s"] == 0.0152


# --- the earlier stages re-run ---------------------------------------------------------------------------------------------------

def test_every_record_of_an_earlier_script_is_redirected_and_carries_this_seals_blobs_and_name(seal):
    stub = type("M", (), {})()
    written = {}
    stub._record = lambda name, **fields: written.setdefault(name, fields) and written[name]
    seal._redirect(stub, "v141", BLOBS)
    assert stub.OUT == seal.OUT / "v141"
    stub._record("run3_K1", ok=True)
    assert written["run3_K1"]["code_blobs"] == BLOBS and written["run3_K1"]["ok"] is True
    assert written["run3_K1"]["harness"] == "harness-v1.4.3-rc"  # not the earlier script's own release-candidate tag


def test_the_v142_stage_repeats_run_1_and_the_two_evidence_checks_but_not_the_allocation_probe(seal, monkeypatch):
    v140_cloud.install(monkeypatch, behaviour_v142, costs={"": 0.01})
    guard = CostGuard(daily_cost_ceiling_usd=1.50)
    docs = seal.run_v142("key", "", guard, BLOBS)
    names = sorted(p.stem for p in (seal.OUT / "v142").glob("*.json"))
    assert names == ["run1_A_ready_image", "run1_B_branch_run", "run1_C_runner_hooks", "run1_W0_hook_alone_sees_nothing", "run1_W1_wrapper_prints_the_raise_site",
                     "run1_W2_wrapper_on_python36", "run2_E0_calm_run_with_evidence", "run2_E1a_self_sigkill_with_evidence"]
    assert all(d["ok"] for d in docs) and len(docs) == 8
    record = json.loads((seal.OUT / "v142" / "run2_E1a_self_sigkill_with_evidence.json").read_text(encoding="utf-8"))
    assert record["code_blobs"] == BLOBS and record["ok"] is True and record["harness"] == "harness-v1.4.3-rc"


def test_a_stopped_evidence_operation_fails_the_v142_stage_instead_of_returning_quietly(seal, monkeypatch):
    import uuid as uuidlib

    from contree_sdk.sdk.exceptions import OperationTimedOutError

    v140_cloud.install(monkeypatch, behaviour_v142, costs={"": 0.01})
    real_run = v140_cloud.Image.run

    def run(self, shell, timeout, disposable, preserve_env=False, stdout=None, stderr=None):
        if shell.startswith("(\npython3 probe.py\n);") and b"sys.exit(3)" in self.state["files"].get("probe.py", b""):
            raise OperationTimedOutError(operation_uuid=uuidlib.uuid4())
        return real_run(self, shell, timeout, disposable, preserve_env, stdout, stderr)

    monkeypatch.setattr(v140_cloud.Image, "run", run)
    docs = seal.run_v142("key", "", CostGuard(daily_cost_ceiling_usd=1.50), BLOBS)
    assert docs[-1]["ok"] is False and "E0 was stopped" in docs[-1]["note"]


def test_the_final_stage_stops_before_a_check_the_cap_cannot_cover_and_at_the_first_failure(seal, monkeypatch):
    plan = [("torch_py310_imports_torchvision.json", ["x"], {}, "torch"), ("smoke_alive_py310.json", ["y"], {}, "smoke")]
    calls = []

    class Stub:
        PLAN = plan
        MAX_KILL_RUNS = 2
        KILL = ("kill_at_operation_limit_py310{n}.json", ["k"], {}, "kill")
        OUT = ""

        @staticmethod
        def _run(record, argv, env):
            calls.append(record)
            return (record != "smoke_alive_py310.json"), 0.01, {"run_id": record, "via": "client_wait_timeout"}

    monkeypatch.setattr(seal, "_load", lambda rel, name: Stub)
    low = CostGuard(daily_cost_ceiling_usd=0.10)  # the torch check cost $0.2504 in the v1.4.0 seal
    with pytest.raises(SystemExit, match="not started"):
        seal.run_final("key", "", low, BLOBS)
    assert calls == []
    guard = CostGuard(daily_cost_ceiling_usd=1.50)
    docs = seal.run_final("key", "", guard, BLOBS)
    assert calls == ["torch_py310_imports_torchvision.json", "smoke_alive_py310.json"] and [d["ok"] for d in docs] == [True, False]  # stopped at the first failure


def test_on_a_resume_the_final_stage_does_not_pay_again_for_a_record_that_passed(seal, monkeypatch, tmp_path):
    out = seal.OUT / "final"
    out.mkdir(parents=True)
    (out / "torch_py310_imports_torchvision.json").write_text(json.dumps({"ok": True, "run_id": "earlier"}), encoding="utf-8")
    calls = []

    class Stub:
        PLAN = [("torch_py310_imports_torchvision.json", ["x"], {}, "torch"), ("smoke_alive_py310.json", ["y"], {}, "smoke")]
        MAX_KILL_RUNS = 1
        KILL = ("kill_at_operation_limit_py310{n}.json", ["k"], {}, "kill")
        OUT = ""

        @staticmethod
        def _run(record, argv, env):
            calls.append(record)
            return True, 0.01, {"run_id": record, "via": "server_result_timed_out"}

    monkeypatch.setattr(seal, "_load", lambda rel, name: Stub)
    monkeypatch.setattr(seal, "previous_cost", lambda rel: 0.01)
    docs = seal.run_final("key", "", CostGuard(daily_cost_ceiling_usd=1.50), BLOBS)
    assert "torch_py310_imports_torchvision.json" not in calls and calls[0] == "smoke_alive_py310.json"
    assert docs[0] == {"ok": True, "cost_usd": 0.0, "run_id": "earlier", "skipped": True}


# --- how a stage that stops is recorded -------------------------------------------------------------------------------------------

def _summary():
    return {"head": "h", "rc_commit": "rc", "blobs": BLOBS, "stages": {}}


def test_a_stage_that_raises_is_recorded_with_the_money_it_spent_and_stops_the_seal(seal):
    guard = CostGuard(daily_cost_ceiling_usd=1.50)

    def stopping(api_key, project_id, g, blobs_now):
        g.record_spend(0.25)
        raise SystemExit("STOP: the seal cap leaves too little for K1")

    summary = _summary()
    code = seal.execute_stages(["new", "v141"], summary, guard, BLOBS, api_key="k", project_id="p", wait_seconds=0, cap=1.5, runners={"new": stopping, "v141": None})
    assert code == 1
    stage = summary["stages"]["new"]
    assert stage["ok"] is False and stage["cost_usd"] == pytest.approx(0.25) and stage["attempts"] == 1 and "SystemExit" in stage["stopped_by"]
    assert "v141" not in summary["stages"]  # nothing further ran
    assert json.loads((seal.OUT / "SEAL_RUN.json").read_text(encoding="utf-8"))["stages"]["new"]["cost_usd"] == pytest.approx(0.25)


def test_a_stage_cost_is_cumulative_over_its_attempts_and_a_passed_stage_is_skipped_on_a_resume(seal):
    guard = CostGuard(daily_cost_ceiling_usd=1.50)
    summary = _summary()
    attempts = []

    def flaky(api_key, project_id, g, blobs_now):
        attempts.append(1)
        g.record_spend(0.10)
        if len(attempts) == 1:
            raise SystemExit("first attempt stops")
        return [{"ok": True}]

    run = lambda: seal.execute_stages(["new"], summary, guard, BLOBS, api_key="k", project_id="p", wait_seconds=0, cap=1.5, runners={"new": flaky})  # noqa: E731
    assert run() == 1  # the first attempt stops
    run()  # the second passes the stage (the seal as a whole is not complete: the other stages have not run)
    stage = summary["stages"]["new"]
    assert stage["ok"] is True and stage["attempts"] == 2 and stage["cost_usd"] == pytest.approx(0.20)  # 0.10 + 0.10: the first attempt's spend is not forgotten
    again = []
    seal.execute_stages(["new"], summary, guard, BLOBS, api_key="k", project_id="p", wait_seconds=0, cap=1.5, runners={"new": lambda *a: again.append(1) or [{"ok": True}]})
    assert again == []  # already passed: not run again unless named with --stage
    seal.execute_stages(["new"], summary, guard, BLOBS, api_key="k", project_id="p", wait_seconds=0, cap=1.5, explicit=True,
                        runners={"new": lambda *a: again.append(1) or [{"ok": True}]})
    assert again == [1]


def test_a_stage_with_a_failing_record_in_its_directory_is_not_ok_even_if_the_code_returned_quietly(seal):
    """The older stage code returned early when an operation was stopped (it wrote its own failing record): the stage must not be marked passed."""
    guard = CostGuard(daily_cost_ceiling_usd=1.50)

    def quiet(api_key, project_id, g, blobs_now):
        directory = seal.OUT / "v141"
        directory.mkdir(parents=True)
        (directory / "run2_L2_additive_apt_layer.json").write_text(json.dumps({"ok": False, "killed": True}), encoding="utf-8")
        (directory / "run2_L1.json").write_text(json.dumps({"ok": True}), encoding="utf-8")
        return [{"ok": True}]

    summary = _summary()
    assert seal.execute_stages(["v141"], summary, guard, BLOBS, api_key="k", project_id="p", wait_seconds=0, cap=1.5, runners={"v141": quiet}) == 1
    assert summary["stages"]["v141"]["ok"] is False and summary["stages"]["v141"]["failing_records"] == 1


def test_an_informational_failing_record_does_not_fail_a_stage(seal):
    guard = CostGuard(daily_cost_ceiling_usd=1.50)

    def run(api_key, project_id, g, blobs_now):
        directory = seal.OUT / "v142"
        directory.mkdir(parents=True)
        (directory / "run2_E1b.json").write_text(json.dumps({"ok": False, "informational": True}), encoding="utf-8")
        return [{"ok": True}]

    summary = _summary()
    seal.execute_stages(["v142"], summary, guard, BLOBS, api_key="k", project_id="p", wait_seconds=0, cap=1.5, runners={"v142": run})
    assert summary["stages"]["v142"]["ok"] is True


def test_a_sandbox_touching_file_changing_while_a_stage_runs_fails_the_stage(seal, monkeypatch):
    guard = CostGuard(daily_cost_ceiling_usd=1.50)
    summary = _summary()

    def edits(api_key, project_id, g, blobs_now):
        monkeypatch.setattr(seal, "blobs", lambda: {**BLOBS, "backend/app/services/sandbox.py": "edited meanwhile"})
        return [{"ok": True}]

    assert seal.execute_stages(["new"], summary, guard, BLOBS, api_key="k", project_id="p", wait_seconds=0, cap=1.5, runners={"new": edits}) == 1
    assert summary["stages"]["new"]["ok"] is False and summary["stages"]["new"]["blobs_changed_while_running"] is True
