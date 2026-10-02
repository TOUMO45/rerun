"""The v1.4.3 seal runner (reports/corpus-v2.1/v1.4.3/seal/run_seal_v143.py), exercised OFFLINE before any money is spent: its plan, its refusals, its precondition, the new checks (S1-S4) end to
end against the fake ConTree cloud through the real sandbox runner, and the wiring of the earlier seals' stages. The live seal measures what this cannot: the real API's limit and flags."""

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
    return module


def emit_behaviour(seal):
    """`python3 emit.py N CODE`: what the writer prints, computed from the same constants the seal expects."""
    def behaviour(shell, built, files):
        m = re.fullmatch(r"python3 emit\.py (\d+) (\d+)", shell)
        if m:
            return int(m.group(2)), "stdout-line\n", seal.expected_stderr(int(m.group(1)))
        return None

    return behaviour


# --- plan and refusals --------------------------------------------------------------------------------------------------------

def test_the_plan_runs_nothing_and_fits_the_owners_cap(seal, capsys):
    assert seal.main([]) == 0
    out = capsys.readouterr().out
    assert "PLAN ONLY" in out and "ESTIMATED" in out
    rows = seal.plan()
    assert {r["stage"] for r in rows} == set(seal.STAGES)
    total = sum(r["usd"] for r in rows)
    assert 1.0 < total < seal.MAX_SEAL_USD  # the whole re-verification costs about what the earlier seals' records say, under the cap
    assert not [r for r in rows if "E1b" in r["op"]]  # the informational allocation probe is not repeated


def test_no_run_without_go_a_cap_and_not_above_the_owners_bound(seal, capsys):
    assert seal.MAX_SEAL_USD == 1.50
    assert seal.main(["--go"]) == 2 and "--max-usd is required" in capsys.readouterr().err
    assert seal.main(["--go", "--max-usd", "1.51"]) == 2
    assert seal.main(["--go", "--max-usd", "0"]) == 2


def test_the_seal_runs_only_against_the_release_candidate(seal):
    clean = {("diff", "--name-only"): "", ("status", "--porcelain"): "", ("rev-parse", "harness-v1.4.3-rc"): "rc-sha", ("rev-parse", "HEAD"): "head-sha"}

    def git(*args):
        return next(v for k, v in clean.items() if args[: len(k)] == k)

    assert seal.precondition(git) == {"harness_rc_tag": "harness-v1.4.3-rc", "rc_commit": "rc-sha", "head": "head-sha"}
    clean[("diff", "--name-only")] = "backend/app/services/sandbox.py\n"
    with pytest.raises(SystemExit, match="not those of harness-v1.4.3-rc"):
        seal.precondition(git)
    clean[("diff", "--name-only")], clean[("status", "--porcelain")] = "", " M scripts/x.py\n"
    with pytest.raises(SystemExit, match="uncommitted"):
        seal.precondition(git)


def test_a_summary_of_another_commit_or_other_blobs_is_refused(seal):
    state = {"head": "h1"}
    seal.OUT.mkdir(parents=True)
    (seal.OUT / "SEAL_RUN.json").write_text(json.dumps({"head": "h1", "blobs": BLOBS, "stages": {}}), encoding="utf-8")
    assert seal._load_summary(BLOBS, state)["head"] == "h1"
    with pytest.raises(SystemExit, match="another commit"):
        seal._load_summary(BLOBS, {"head": "h2"})
    with pytest.raises(SystemExit, match="another commit"):
        seal._load_summary({**BLOBS, "backend/app/services/sandbox.py": "edited"}, state)


# --- the new checks -----------------------------------------------------------------------------------------------------------

def _run_new(seal, monkeypatch, **kw):
    cloud = v140_cloud.install(monkeypatch, emit_behaviour(seal), stops=("sleep 20",), **kw)
    guard = CostGuard(daily_cost_ceiling_usd=1.50)
    return cloud, guard, seal.run_new("key", "proj", guard, BLOBS)


def test_the_four_new_checks_pass_against_a_cloud_that_behaves_like_the_api(seal, monkeypatch):
    cloud, guard, docs = _run_new(seal, monkeypatch)
    assert [d["ok"] for d in docs] == [True, True, True, True]
    s1, s2, s3, s4 = docs
    assert s1["streams"]["stderr"]["bytes"] == s1["expected_bytes"] > 200_000 and s1["streams"]["stderr"]["truncated"] is False
    assert s2["returned_bytes"] == sandbox.OUTPUT_LIMIT_BYTES and s2["streams"]["stderr"]["truncated"] is True and s2["harness_reason"].startswith("OUTPUT_TRUNCATED: ")
    assert s2["requested_bytes"] > sandbox.OUTPUT_LIMIT_BYTES and seal.MARKER not in s2["stderr_tail"]
    assert s3["image"] and s3["exit_code"] == 0 and s3["run_id"] == s3["image"] in cloud.images
    assert s4["via"] == "server_result_timed_out" and s4["timed_out"] is True and s4["image"] == s3["image"]
    for name in ("S1_200kb_stderr_whole", "S2_stream_over_the_limit_flagged", "S3_run_on_image_reopens_a_kept_image", "S4_run_on_image_stopped_at_its_limit"):
        record = json.loads((seal.OUT / "new" / f"{name}.json").read_text(encoding="utf-8"))
        assert record["code_blobs"] == BLOBS and record["run_id"] and record["ok"] is True
    assert guard.spent_today_usd > 0


def test_s1_fails_if_the_client_still_asks_for_the_old_limit(seal, monkeypatch):
    """Negative control: with the SDK's 65,535 bytes the 200 KB stream comes back cut, and the live seal would stop here."""
    monkeypatch.setattr(sandbox, "OUTPUT_LIMIT_BYTES", 65535)
    _, _, docs = _run_new(seal, monkeypatch)
    assert docs[0]["ok"] is False and docs[0]["streams"]["stderr"]["truncated"] is True and docs[0]["streams"]["stderr"]["bytes"] == 65535


def test_s2_fails_if_the_api_does_not_flag_the_cut(seal, monkeypatch):
    real_cut = v140_cloud._cut
    monkeypatch.setattr(v140_cloud, "_cut", lambda text, limit: (real_cut(text, limit)[0], False))  # an API that cuts but does not say so
    _, _, docs = _run_new(seal, monkeypatch)
    assert docs[1]["ok"] is False and docs[1]["harness_reason"] is None


def test_s4_records_the_client_wait_path_with_an_estimated_cost(seal, monkeypatch):
    real = sandbox.run_on_image

    def client_side(**kw):
        if kw["command"].startswith("sleep 20"):
            raise sandbox.SandboxTimeoutError("sandbox execution exceeded 3s wall clock", command=kw["command"], killed_seconds=3.0)
        return real(**kw)

    monkeypatch.setattr(sandbox, "run_on_image", client_side)
    _, guard, docs = _run_new(seal, monkeypatch)
    s4 = docs[3]
    assert s4["ok"] is True and s4["via"] == "client_wait_timeout" and "ESTIMATED" in s4["cost_tag"] and s4["cost_usd"] == pytest.approx(3 * 0.0152)
    assert guard.cost_events and guard.cost_events[-1]["rate_usd_per_s"] == 0.0152


# --- the earlier stages re-run ---------------------------------------------------------------------------------------------------

def test_every_record_of_an_earlier_script_is_redirected_and_carries_the_blobs(seal):
    stub = type("M", (), {})()
    written = {}
    stub._record = lambda name, **fields: written.setdefault(name, fields) and written[name]
    seal._redirect(stub, "v141", BLOBS)
    assert stub.OUT == seal.OUT / "v141"
    stub._record("run3_K1", ok=True)
    assert written["run3_K1"]["code_blobs"] == BLOBS and written["run3_K1"]["ok"] is True


def test_the_v142_stage_repeats_run_1_and_the_two_evidence_checks_but_not_the_allocation_probe(seal, monkeypatch):
    v140_cloud.install(monkeypatch, behaviour_v142, costs={"": 0.01})
    guard = CostGuard(daily_cost_ceiling_usd=1.50)
    docs = seal.run_v142("key", "", guard, BLOBS)
    names = sorted(p.stem for p in (seal.OUT / "v142").glob("*.json"))
    assert names == ["run1_A_ready_image", "run1_B_branch_run", "run1_C_runner_hooks", "run1_W0_hook_alone_sees_nothing", "run1_W1_wrapper_prints_the_raise_site",
                     "run1_W2_wrapper_on_python36", "run2_E0_calm_run_with_evidence", "run2_E1a_self_sigkill_with_evidence"]
    assert all(d["ok"] for d in docs) and len(docs) == 8
    record = json.loads((seal.OUT / "v142" / "run2_E1a_self_sigkill_with_evidence.json").read_text(encoding="utf-8"))
    assert record["code_blobs"] == BLOBS and record["ok"] is True


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
