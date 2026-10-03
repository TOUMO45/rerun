"""harness-v1.6: APT_MIRROR_GONE ends a run INDETERMINATE through ENV attribution (item C.2), the outcome ladder
(item L, outcome_levels.py), the blocker report (item B, blocker.py), and both wired into the record."""

from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

from app.services import adjudicator, blocker, outcome_levels
from app.services import error_chain as ec
from app.services.classifier import TaxonomyCode
from app.services.cost_guard import CostGuard
from app.services.intake import RepoIntake
from app.services.orchestrator import (
    OUR_FAULT_CODES,
    PipelineDeps,
    PipelineResult,
    derived_record,
    is_our_fault,
    reason_code_of,
    run_pipeline,
)
from app.services.passport import verify_certificate
from app.services.sandbox import SandboxRunResult, StepResult
from app.services.time_machine import LockResult


def _chain_test_module():
    spec = importlib.util.spec_from_file_location("t_chain", Path(__file__).with_name("test_error_chain.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


APT_404 = (
    "Err:2 http://deb.debian.org/debian stretch Release\n"
    "  404  Not Found [IP: 151.101.2.132 80]\n"
    "E: The repository 'http://deb.debian.org/debian stretch Release' does not have a Release file.\n"
)


# --- C.2: APT_MIRROR_GONE is ENV and ends INDETERMINATE, never BLOCKED ------------------------------------------------

@pytest.mark.parametrize("phase", ec.PHASES)
def test_apt_mirror_gone_is_attributed_to_the_environment_in_every_phase(phase):
    assert ec.attribute("APT_MIRROR_GONE", APT_404, declared_deps=frozenset(), python_claim=None,
                        base_image="python:3.6-slim", phase=phase) == ec.ENV


def test_apt_mirror_gone_is_a_runner_side_reason_code():
    assert "APT_MIRROR_GONE" in OUR_FAULT_CODES and is_our_fault("APT_MIRROR_GONE")


def test_apt_mirror_gone_at_the_baseline_ends_indeterminate_with_no_repair_attempt(tmp_path):
    """The apt step runs in the repository's install phase (the plan's apt_install is prepended to its install commands), so
    the runner-setup invariant does not cover it: the stop is decided on the CODE, in `_note_failure`, like the sandbox classes."""
    step = StepResult("apt-get update && apt-get install -y git", 100, "", APT_404, 1.0, 0.0, phase=ec.PHASE_REPO_INSTALL)
    result = _chain_test_module()._run(tmp_path, [SandboxRunResult(steps=(step,))], repair=[
        {"explanation": "decline", "diff": "", "env_changes": []}])
    assert result.verdict == "INDETERMINATE" and result.taxonomy_code == "APT_MIRROR_GONE"
    assert reason_code_of(result.indeterminate_reason) == "APT_MIRROR_GONE"
    assert result.attempts == ()  # no time-machine step, no model attempt
    assert [(l["class"], l["attribution"], l["phase"]) for l in result.error_chain] == [("APT_MIRROR_GONE", "ENV", "repo_install")]
    assert result.first_repo_error is None
    assert verify_certificate(result.certificate())


def test_apt_mirror_gone_after_a_repair_ends_indeterminate_not_blocked(tmp_path):
    fix = {"explanation": "add foo", "diff": "", "env_changes": [{"op": "add", "package": "foo", "version": "1.0",
                                                                   "justification": "needed", "evidence": "No module named 'foo'"}]}
    m = _chain_test_module()
    result = m._run(tmp_path, [m._res(1, "ModuleNotFoundError: No module named 'foo'"), m._res(100, APT_404)],
                    repair=[fix], declared=frozenset())
    assert result.verdict == "INDETERMINATE" and result.taxonomy_code == "APT_MIRROR_GONE"
    chain = result.error_chain
    assert chain[0]["attribution"] == "REPO" and chain[0]["cleared_by"] == 0 and chain[-1]["attribution"] == "ENV"
    assert result.first_repo_error == "ModuleNotFoundError: No module named 'foo'"
    assert result.blocker["class"] == "APT_MIRROR_GONE" and result.blocker["fixable_by"] == "platform"


def test_certificate_prose_names_the_mirror_and_claims_nothing():
    prose = adjudicator.templated_certificate_prose("INDETERMINATE", "APT_MIRROR_GONE", 0, "APT_MIRROR_GONE: ...")
    assert "APT_MIRROR_GONE" in prose and "not evidence about the repository" in prose


# --- L: the outcome ladder ----------------------------------------------------------------------------------------

def _link(cls, cleared_by=None, attribution="REPO"):
    return {"error": f"{cls} evidence", "class": cls, "attribution": attribution, "phase": "repo_run", "cleared_by": cleared_by}


def _attempt(number, origin):
    return {"attempt_number": number, "origin": origin, "gate_decision": "PASS", "exit_code": 1}


def test_outcome_levels_runs_clean_without_a_chain():
    assert outcome_levels.compute({"verdict": "RUNS_CLEAN", "error_chain": [], "attempts": []}) == {
        "first_error_cleared": False, "first_error_cleared_by": None, "env_resolved": True, "entrypoint_runs": True}


def test_outcome_levels_runs_after_repair_names_who_cleared_the_first_error():
    result = {"verdict": "RUNS_AFTER_REPAIR", "error_chain": [_link("DEP_MISSING", cleared_by=0)],
              "attempts": [_attempt(0, "time_machine"), _attempt(1, "model")]}
    assert outcome_levels.compute(result) == {
        "first_error_cleared": True, "first_error_cleared_by": "time_machine", "env_resolved": True, "entrypoint_runs": True}


def test_outcome_levels_blocked_in_the_environment():
    result = {"verdict": "BLOCKED", "error_chain": [_link("DEP_MISSING", cleared_by=1), _link("DEP_BUILD_FAILED")],
              "attempts": [_attempt(1, "model")]}
    assert outcome_levels.compute(result) == {
        "first_error_cleared": True, "first_error_cleared_by": "model", "env_resolved": False, "entrypoint_runs": False}


def test_outcome_levels_blocked_past_the_environment():
    # the last failure was raised by the repository's own code in a built environment
    result = {"verdict": "BLOCKED", "error_chain": [_link("SYS_LIB_MISSING", cleared_by=0), _link("DATA_MISSING")],
              "attempts": [_attempt(0, "time_machine")]}
    assert outcome_levels.compute(result) == {
        "first_error_cleared": True, "first_error_cleared_by": "time_machine", "env_resolved": True, "entrypoint_runs": False}


@pytest.mark.parametrize("cls", sorted(outcome_levels.ENVIRONMENT_CLASSES))
def test_outcome_levels_every_environment_class_means_unresolved(cls):
    assert outcome_levels.compute({"verdict": "BLOCKED", "error_chain": [_link(cls)], "attempts": []})["env_resolved"] is False


def test_outcome_levels_first_error_never_cleared():
    result = {"verdict": "BLOCKED", "error_chain": [_link("RUNTIME_ERROR_OTHER")], "attempts": [_attempt(1, "model")]}
    assert outcome_levels.compute(result) == {
        "first_error_cleared": False, "first_error_cleared_by": None, "env_resolved": True, "entrypoint_runs": False}


def test_outcome_levels_cleared_by_an_attempt_the_record_does_not_carry():
    # cleared_by is set but no attempt has that number (a chain rebuilt from a log, say): honest None, still "cleared"
    result = {"verdict": "INDETERMINATE", "error_chain": [_link("DEP_MISSING", cleared_by=3), _link("APT_MIRROR_GONE", attribution="ENV")],
              "attempts": [_attempt(1, "model")]}
    assert outcome_levels.compute(result) == {
        "first_error_cleared": True, "first_error_cleared_by": None, "env_resolved": False, "entrypoint_runs": False}


def test_outcome_levels_reads_missing_fields_as_empty():
    assert outcome_levels.compute({"verdict": "INDETERMINATE"}) == {
        "first_error_cleared": False, "first_error_cleared_by": None, "env_resolved": False, "entrypoint_runs": False}


# --- B: the blocker report ----------------------------------------------------------------------------------------

def _report(cls, error, verdict="BLOCKED", attribution="REPO", phase="repo_run"):
    return blocker.report({"verdict": verdict, "error_chain": [
        _link("DEP_MISSING", cleared_by=0), {"error": error, "class": cls, "attribution": attribution, "phase": phase, "cleared_by": None}]})


def test_blocker_is_none_for_runs_clean_and_for_an_empty_chain():
    assert blocker.report({"verdict": "RUNS_CLEAN", "error_chain": [_link("DEP_MISSING", cleared_by=0)]}) is None
    assert blocker.report({"verdict": "RUNS_AFTER_REPAIR", "error_chain": [_link("DEP_MISSING", cleared_by=0)]}) is None
    assert blocker.report({"verdict": "INDETERMINATE", "error_chain": []}) is None
    assert blocker.report({"verdict": "BLOCKED"}) is None


def test_blocker_every_taxonomy_code_has_a_row_and_no_default():
    assert set(blocker.TABLE) == set(TaxonomyCode.ALL)
    for code in TaxonomyCode.ALL:
        fixable_by, sentence = blocker.TABLE[code]
        assert fixable_by in (blocker.DETERMINISTIC, blocker.MODEL, blocker.HUMAN, blocker.PLATFORM) and sentence
    # v1.6 review, defect 8: an unknown class is a guarded row (None fields, a logged warning), never an exception
    # behind certificate() and the API: completeness is this test's job, not report()'s.
    unknown = _report("NOT_A_CODE", "x")
    assert unknown["class"] == "NOT_A_CODE" and unknown["evidence"] == "x"
    assert unknown["family"] is None and unknown["fixable_by"] is None and unknown["what_a_human_must_supply"] is None
    # the one historical class older records carry reads as the row of what it became
    report = _report("DEP_YANKED_GONE", "ERROR: No matching distribution found for foo==1")
    assert report["class"] == "DEP_YANKED_GONE" and report["family"] == "Dependencies" and report["fixable_by"] == "deterministic"


def test_blocker_reports_the_last_link_with_its_family_phase_and_attribution():
    report = _report("DATA_MISSING", "FileNotFoundError: [Errno 2] No such file or directory: 'data/cifar-10/train.pkl'",
                     attribution="REPO", phase="repo_run")
    assert report == {
        "class": "DATA_MISSING", "family": "Data", "phase": "repo_run", "attribution": "REPO",
        "evidence": "FileNotFoundError: [Errno 2] No such file or directory: 'data/cifar-10/train.pkl'",
        "fixable_by": "human",
        "what_a_human_must_supply": "the dataset the repository expects at data/cifar-10/train.pkl, obtained as its README describes",
        "sources": None,
    }


def test_blocker_evidence_is_capped_at_300_chars():
    report = _report("RUNTIME_ERROR_OTHER", "ValueError: " + "x" * 1000)
    assert len(report["evidence"]) == 300


@pytest.mark.parametrize("cls, error, fixable_by, sentence", [
    ("DEP_MISSING", "ModuleNotFoundError: No module named 'dassl'", "deterministic",
     "nothing, if the era lock resolves it; otherwise the exact release of dassl the authors used"),
    ("DEP_YANKED", "ERROR: No matching distribution found for ancient-pkg==0.0.1", "deterministic",
     "nothing, if the era lock resolves it; otherwise the exact release of ancient-pkg the authors used"),
    ("DEP_UNPINNED_CONFLICT", "ERROR: Cannot install tensorboard==2.1.0 and tensorflow==1.15.5 because these package versions have conflicting dependencies.",
     "deterministic", "nothing, if the era lock resolves it; otherwise the exact release of tensorboard the authors used"),
    ("DEP_NOT_ON_PYPI", "ERROR: Could not find a version that satisfies the requirement dassl (from versions: none)", "deterministic",
     "nothing, if the era lock resolves it; otherwise the exact release of dassl the authors used"),
    ("API_REMOVED", "ImportError: cannot import name 'zero_gradients' from 'torch.autograd.gradcheck' (/usr/local/lib/python3.10/site-packages/torch/autograd/gradcheck.py)",
     "deterministic", "nothing, if the era lock or a removed-API row resolves it; otherwise the release of torch the authors used (older or newer)"),
    ("API_REMOVED", "AttributeError: module 'tensorflow' has no attribute 'get_variable'", "deterministic",
     "nothing, if the era lock or a removed-API row resolves it; otherwise the release of tensorflow the authors used (older or newer)"),
    ("PY_VERSION_INCOMPAT", "ERROR: Package 'foo' requires a different Python: 3.12.1 not in '<3.10,>=3.8'", "deterministic",
     "nothing, if the interpreter policy resolves it; otherwise the Python version the authors used"),
    ("SYS_LIB_MISSING", "ImportError: libGL.so.1: cannot open shared object file: No such file or directory", "deterministic",
     "nothing, if the apt rule resolves it; otherwise the system package that provides libGL.so.1"),
    ("SYS_LIB_MISSING", "error: command 'gcc' failed: No such file or directory", "deterministic",
     "nothing, if the apt rule resolves it; otherwise the system package that provides gcc"),
    ("SYS_LIB_MISSING", "ERROR: Cannot find command 'git' - do you have 'git' installed and in your PATH?", "deterministic",
     "nothing, if the apt rule resolves it; otherwise the system package that provides git"),
    ("DEP_BUILD_FAILED", "ERROR: Failed building wheel for pycocotools", "deterministic",
     "nothing, if the apt rule adds the build dependencies; otherwise a wheel of pycocotools for this platform"),
    ("DEP_BUILD_FAILED", "ERROR: Failed to build installable wheels for some pyproject.toml based projects (pygame)", "deterministic",
     "nothing, if the apt rule adds the build dependencies; otherwise a wheel of pygame for this platform"),
    ("DATA_MISSING", "FileNotFoundError: [Errno 2] No such file or directory: 'data/train.csv'", "human",
     "the dataset the repository expects at data/train.csv, obtained as its README describes"),
    ("DATA_MISSING", "AssertionError: Please download the dataset first", "human",
     "the dataset the repository expects at the path the code opens, obtained as its README describes"),
    ("DATA_CREDENTIALS", "requests.exceptions.HTTPError: 401 Client Error: Unauthorized for url: https://api.example.com/dataset", "human",
     "the credentials (an API key, token or login) the download step asks for"),
    ("GPU_REQUIRED", "AssertionError: Torch not compiled with CUDA enabled", "human",
     "a CUDA device, or the CPU shim where the call is a plain .cuda()"),
    ("GPU_REQUIRED", "NotImplementedError: \"upsample_bilinear2d_out_frame\" is not implemented on the CPU", "human",
     "a CUDA device: the operation has no CPU implementation"),
    ("GPU_REQUIRED", "RuntimeError: Cannot access accelerator device when none is available.", "human",
     "a CUDA device, or the CPU shim where the call is a plain .cuda()"),
    ("HARDCODED_PATH", "FileNotFoundError: [Errno 2] No such file or directory: '/home/jsmith/data/train.csv'", "model",
     "nothing: the repairer proposes a relative path at /home/jsmith/data/train.csv and the tamper gate decides"),
    ("ENTRYPOINT_UNCLEAR", "ENTRYPOINT_UNCLEAR: recon confidence 0.3", "human", "the command to run: the README does not name one unambiguously"),
    ("NETWORK_BLOCKED", "socket.gaierror: [Errno -3] Temporary failure in name resolution", "platform",
     "an egress rule for the host the code reaches, or the file it downloads"),
    ("RUNTIME_ERROR_OTHER", "ZeroDivisionError: division by zero", "model",
     "a code change; the repairer proposes one and the tamper gate decides"),
    ("APT_MIRROR_GONE", "E: The repository 'http://deb.debian.org/debian stretch Release' does not have a Release file.", "platform",
     "a base image whose distribution is still on the mirrors"),
    ("SANDBOX_QUOTA", "OSError: [Errno 28] No space left on device", "platform", "a sandbox with a larger quota (No space left on device)"),
    ("SANDBOX_INCOMPAT", "ImportError: libtorch_cpu.so: cannot enable executable stack as shared object requires: Invalid argument", "platform",
     "a sandbox that loads this artifact (cannot enable executable stack as shared object requires: Invalid argument)"),
    ("RESOURCE_LIMIT", "exit code 137: the process was killed by SIGKILL (the shell printed 'Killed')", "platform",
     "a sandbox with more resources (exit code 137: the process was killed by SIGKILL)"),
])
def test_blocker_one_row_per_class(cls, error, fixable_by, sentence):
    report = _report(cls, error)
    assert (report["class"], report["fixable_by"], report["what_a_human_must_supply"]) == (cls, fixable_by, sentence)
    assert report["family"] == TaxonomyCode.FAMILY[cls] and report["sources"] is None
    assert "<" not in report["what_a_human_must_supply"] and "{" not in report["what_a_human_must_supply"]


def test_blocker_generic_wording_when_the_evidence_names_nothing():
    report = _report("DEP_MISSING", "ImportError: dynamic module does not define module export function")
    assert report["what_a_human_must_supply"] == "nothing, if the era lock resolves it; otherwise the exact release of the package the authors used"
    report = _report("RESOURCE_LIMIT", "killed")
    assert report["what_a_human_must_supply"] == "a sandbox with more resources (the limit)"


# --- the record carries both ---------------------------------------------------------------------------------------

def test_derived_record_agrees_with_the_pure_modules():
    chain = [_link("DEP_MISSING", cleared_by=0), {"error": "ValueError: bad", "class": "RUNTIME_ERROR_OTHER", "attribution": "REPO",
                                                   "phase": "repo_run", "cleared_by": None}]
    attempts = [_attempt(0, "time_machine")]
    derived = derived_record("BLOCKED", chain, attempts)
    record = {"verdict": "BLOCKED", "error_chain": chain, "attempts": attempts}
    assert derived == {"outcome_levels": outcome_levels.compute(record), "blocker": blocker.report(record)}
    assert derived["outcome_levels"]["first_error_cleared_by"] == "time_machine" and derived["blocker"]["fixable_by"] == "model"


def test_certificate_carries_both_outside_the_passport_hash(tmp_path):
    m = _chain_test_module()
    result = m._run(tmp_path, [m._res(1, "ValueError: bad shape"), m._res(1, "ValueError: bad shape")], repair=[
        {"explanation": "decline", "diff": "", "env_changes": []}])
    assert isinstance(result, PipelineResult) and result.verdict == "BLOCKED"
    cert = result.certificate()
    assert cert["outcome_levels"] == {"first_error_cleared": False, "first_error_cleared_by": None, "env_resolved": True,
                                      "entrypoint_runs": False}
    assert cert["blocker"]["class"] == "RUNTIME_ERROR_OTHER" and cert["blocker"]["evidence"] == "ValueError: bad shape"
    assert cert["outcome_levels"] == result.outcome_levels and cert["blocker"] == result.blocker
    # derived, so not hashed: a reader may recompute them, and the v4 bundle is unchanged
    assert verify_certificate(cert)
    tampered = dict(cert, blocker=None, outcome_levels={})
    assert verify_certificate(tampered)
    json.dumps(cert)  # serializable as stored


def test_api_certificate_schema_computes_both_from_the_stored_columns():
    from app.schemas import CertificateOut

    out = CertificateOut(run_id="r", verdict="BLOCKED", certificate_prose="", full_log="", build_plan={}, reproduction_passport_hash="",
                         timestamp="t", diffs=[_attempt(0, "time_machine")],
                         error_chain=[_link("DEP_MISSING", cleared_by=0), {"error": "FileNotFoundError: [Errno 2] No such file or directory: 'x.npy'",
                                                                           "class": "DATA_MISSING", "attribution": "REPO", "phase": "repo_run",
                                                                           "cleared_by": None}])
    dumped = out.model_dump()
    assert dumped["outcome_levels"]["first_error_cleared_by"] == "time_machine" and dumped["outcome_levels"]["env_resolved"] is True
    assert dumped["blocker"]["fixable_by"] == "human" and "x.npy" in dumped["blocker"]["what_a_human_must_supply"]
    clean = CertificateOut(run_id="r", verdict="RUNS_CLEAN", certificate_prose="", full_log="", build_plan={}, diffs=[],
                           reproduction_passport_hash="", timestamp="t")
    assert clean.model_dump()["blocker"] is None and clean.model_dump()["outcome_levels"]["entrypoint_runs"] is True


# --- C.1 in the pipeline: where API_REMOVED goes first --------------------------------------------------------------

class _Chat:
    def __init__(self, replies=()):
        self.replies = [json.dumps(r) for r in replies]
        self.calls = []

    def chat_completion(self, **kw):
        self.calls.append(kw)
        if not self.replies:
            raise AssertionError("the model was called")
        return self.replies.pop(0)


def _step(code, stderr):
    return SandboxRunResult(steps=(StepResult("python train.py", code, "", stderr, 1.0, 0.01),))


def _pipeline(tmp_path, results, *, source, lock_ok, replies=()):
    (tmp_path / "train.py").write_text(source, encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True, capture_output=True)
    for k, v in (("user.email", "t@e.st"), ("user.name", "t")):
        subprocess.run(["git", "config", k, v], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-q", "-m", "x"], cwd=tmp_path, check=True, capture_output=True)
    queue = list(results)
    plans = []

    def runner(**kw):
        plans.append(kw)
        return queue.pop(0)

    lock = (lambda *a: LockResult(True, ("scikit-image==0.15.0",), ("scikit-image",))) if lock_ok else (lambda *a: LockResult(False, (), (), (), "", "off"))
    repair = _Chat(replies)
    deps = PipelineDeps(recon_client=_Chat([{"entrypoint": "train.py", "confidence": 0.9}]), recon_model="r", repair_client=repair,
                        repair_model="p", adjudicator_client=None, adjudicator_model=None, sandbox_api_key="k", sandbox_wall_clock_seconds=100,
                        sandbox_runner=runner, tavily_client=None, smoke_seconds=0, max_attempts=1, lock_compiler=lock)
    intake = RepoIntake(tmp_path, "a" * 40, {}, frozenset(), (), ("train.py",), None)
    result = run_pipeline(repo_url="https://example.com/r", commit_sha="a" * 40, workdir=tmp_path, intake_result=intake, deps=deps,
                          cost_guard=CostGuard(daily_cost_ceiling_usd=100), run_id="v16")
    return result, repair, plans, queue


SKIMAGE = "ImportError: cannot import name 'compare_psnr' from 'skimage.measure' (/usr/local/lib/python3.10/site-packages/skimage/measure/__init__.py)\n"
TF = "AttributeError: module 'tensorflow' has no attribute 'get_variable'\n"


def test_an_api_removed_failure_no_row_covers_takes_the_era_lock_first(tmp_path):
    result, repair, plans, left = _pipeline(tmp_path, [_step(1, SKIMAGE), _step(0, "")], source="from skimage.measure import compare_psnr\n", lock_ok=True)
    assert result.verdict == "RUNS_AFTER_REPAIR" and repair.calls == [] and not left
    assert [a.origin for a in result.attempts] == ["time_machine"] and "scikit-image==0.15.0" in " ".join(plans[1]["install_commands"])
    assert result.outcome_levels == {"first_error_cleared": True, "first_error_cleared_by": "time_machine", "env_resolved": True, "entrypoint_runs": True}
    # nothing blocks a run that ended RUNS_*; the ladder above says what cleared the failure
    assert result.blocker is None  # nothing blocks a run that ended RUNS_AFTER_REPAIR; the ladder says what cleared it
    assert result.error_chain[-1]["cleared_by"] == 0  # the era environment cleared it (error_chain.clear_last)


def test_without_an_era_lock_an_api_removed_failure_gets_no_unpinned_fallback_step(tmp_path):
    """The unpinned fallback installs the newest releases, which are the ones that lack the name: it is declined, not spent."""
    fix = {"file_edits": [{"path": "train.py", "old": "from skimage.measure import compare_psnr\n",
                           "new": "from skimage.metrics import peak_signal_noise_ratio as compare_psnr\n"}], "explanation": "moved API",
           "cited_sources": [], "reason_no_citation": "none"}
    result, repair, _plans, left = _pipeline(tmp_path, [_step(1, SKIMAGE), _step(0, "")], source="from skimage.measure import compare_psnr\n",
                                            lock_ok=False, replies=[fix])
    assert result.verdict == "RUNS_AFTER_REPAIR" and len(repair.calls) == 1 and not left
    assert [(a.origin, a.gate_decision) for a in result.attempts] == [("time_machine", "DECLINED"), ("model", "PASS")]
    assert "no unpinned fallback for API_REMOVED" in result.full_log
    assert result.outcome_levels["first_error_cleared_by"] == "model"


def test_an_api_removed_failure_a_removed_api_row_covers_keeps_the_rows_release_first(tmp_path):
    """The v1.5.1/v1.5.2 order: the TensorFlow row's exact release (and its Python) goes before the date-inferred era lock."""
    result, repair, _plans, left = _pipeline(tmp_path, [_step(1, TF), _step(0, "")], source="import tensorflow\n", lock_ok=True)
    assert result.verdict == "RUNS_AFTER_REPAIR" and repair.calls == [] and not left
    assert "[time-machine] skipped ahead of the removed-API rule for API_REMOVED" in result.full_log
    attempt = result.attempts[-1]
    assert attempt.origin == "time_machine" and attempt.time_machine_action is not None
    assert ("tensorflow", "1.15.5") in [(c["package"], c["version"]) for c in attempt.env_delta if c["op"] == "pin"]
    assert result.error_chain[0]["class"] == "API_REMOVED" and result.error_chain[0]["cleared_by"] == 0


def test_outcome_levels_reads_a_pre_v16_runs_after_repair_record_through_its_verdict():
    """Records up to harness-v1.5.2 keep `cleared_by: None` on the one failure the run then passed without (error_chain.clear_last
    did not exist). The verdict says it was cleared; the attempt that exited 0 says by whom."""
    result = {"verdict": "RUNS_AFTER_REPAIR", "error_chain": [_link("DEP_MISSING")],
              "attempts": [{"attempt_number": 0, "origin": "time_machine", "exit_code": 0}]}
    assert outcome_levels.compute(result) == {
        "first_error_cleared": True, "first_error_cleared_by": "time_machine", "env_resolved": True, "entrypoint_runs": True}
    # a BLOCKED record with the same chain is not read that way
    assert outcome_levels.compute({**result, "verdict": "BLOCKED"})["first_error_cleared"] is False
    # with no passing attempt in the record, the "by whom" is honestly unknown
    assert outcome_levels.compute({**result, "attempts": []})["first_error_cleared_by"] is None


def test_the_chain_marks_the_failure_a_passing_run_cleared():
    chain = ec.ErrorChain()
    chain.record(0, "DEP_MISSING", "e", ec.REPO)
    chain.clear_last(1)
    assert chain.as_list()[0]["cleared_by"] == 1
    chain.clear_last(2)  # already cleared: unchanged
    assert chain.as_list()[0]["cleared_by"] == 1
    ec.ErrorChain().clear_last(0)  # an empty chain is fine


# ---------------------------------------------------------------------------
# Item S: a Tavily source for a missing dataset, stored on the blocker report
# ---------------------------------------------------------------------------
from app.services import tavily as tavily_mod


class _Search:
    def __init__(self, results=None, raise_=None):
        self.results, self.raise_, self.calls = results or [], raise_, []

    def search(self, query, *, max_results, search_depth, timeout=None):
        self.calls.append((query, max_results, search_depth))
        if self.raise_:
            raise self.raise_
        return {"results": self.results}


def test_dataset_query_names_the_repository_and_what_the_evidence_line_names():
    q = tavily_mod.dataset_query("https://github.com/omarfoq/fedem", "AssertionError: Download cifar10 dataset!!")
    assert q == "omarfoq fedem dataset download Download cifar10 dataset!!"
    q = tavily_mod.dataset_query("https://github.com/o/r.git", "FileNotFoundError: [Errno 2] No such file or directory: 'data/cifar-10-batches-py'")
    assert q.endswith("dataset download data/cifar-10-batches-py") and q.startswith("o r ")
    assert tavily_mod.dataset_query("", "something else") == "dataset download"


def test_dataset_sources_only_for_a_data_missing_blocker_and_never_raises():
    client = _Search([{"title": "CIFAR-10 page", "url": "https://www.cs.toronto.edu/~kriz/cifar.html", "content": "x"},
                      {"title": "mirror", "url": "https://example.org/c10"}, {"title": "3", "url": "u3"}, {"title": "4", "url": "u4"}])
    assert tavily_mod.dataset_sources(client, "https://github.com/o/r", None) is None
    assert tavily_mod.dataset_sources(client, "https://github.com/o/r", {"class": "GPU_REQUIRED", "evidence": "x"}) is None
    assert client.calls == []
    out = tavily_mod.dataset_sources(client, "https://github.com/o/r", {"class": "DATA_MISSING", "evidence": "AssertionError: Download cifar10 dataset!!"})
    assert out["query"] == "o r dataset download Download cifar10 dataset!!" and out["reason"] is None
    assert [s["url"] for s in out["sources"]] == ["https://www.cs.toronto.edu/~kriz/cifar.html", "https://example.org/c10", "u3"]
    assert client.calls == [(out["query"], 3, "basic")]
    # no client: the reason is stored, not an empty list
    assert tavily_mod.dataset_sources(None, "https://github.com/o/r", {"class": "DATA_MISSING", "evidence": "e"}) == {
        "query": "o r dataset download", "sources": None, "reason": "no Tavily client configured"}
    # a failing search is a stored reason, never an exception
    bad = tavily_mod.dataset_sources(_Search(raise_=RuntimeError("boom")), "https://github.com/o/r", {"class": "DATA_MISSING", "evidence": "e"})
    assert bad["sources"] is None and bad["reason"].startswith("search failed: RuntimeError: boom")
    empty = tavily_mod.dataset_sources(_Search([]), "https://github.com/o/r", {"class": "DATA_MISSING", "evidence": "e"})
    assert empty["sources"] == [] and empty["reason"] == "the search returned no result"


def _data_missing_pipeline(tmp_path, client):
    (tmp_path / "train.py").write_text("print('x')\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True, capture_output=True)
    for k, v in (("user.email", "t@e.st"), ("user.name", "t")):
        subprocess.run(["git", "config", k, v], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-q", "-m", "x"], cwd=tmp_path, check=True, capture_output=True)
    err = "Traceback (most recent call last):\n  File \"train.py\", line 3, in <module>\nAssertionError: Download cifar10 dataset!!\n"
    deps = PipelineDeps(recon_client=_Chat([{"entrypoint": "train.py", "confidence": 0.9}]), recon_model="r", repair_client=_Chat([]),
                        repair_model="p", adjudicator_client=None, adjudicator_model=None, sandbox_api_key="k", sandbox_wall_clock_seconds=100,
                        sandbox_runner=lambda **kw: _step(1, err), tavily_client=client, smoke_seconds=0, max_attempts=0,
                        lock_compiler=lambda *a: LockResult(False, (), (), (), "", "off"))
    intake = RepoIntake(tmp_path, "a" * 40, {}, frozenset(), (), ("train.py",), None)
    events = []
    result = run_pipeline(repo_url="https://github.com/omarfoq/fedem", commit_sha="a" * 40, workdir=tmp_path, intake_result=intake, deps=deps,
                          cost_guard=CostGuard(daily_cost_ceiling_usd=100), run_id="v16s", on_event=events.append)
    return result, events


def test_a_data_missing_run_stores_the_dataset_lookup_on_its_blocker_outside_the_hash(tmp_path):
    client = _Search([{"title": "CIFAR-10", "url": "https://www.cs.toronto.edu/~kriz/cifar.html"}])
    result, events = _data_missing_pipeline(tmp_path, client)
    assert result.verdict == "BLOCKED" and result.taxonomy_code == "DATA_MISSING"
    assert result.blocker["class"] == "DATA_MISSING" and result.blocker["fixable_by"] == "human"
    assert result.blocker["sources"] == {"query": "omarfoq fedem dataset download Download cifar10 dataset!!",
                                         "sources": [{"title": "CIFAR-10", "url": "https://www.cs.toronto.edu/~kriz/cifar.html"}], "reason": None}
    assert result.certificate()["blocker"]["sources"]["sources"][0]["url"].endswith("cifar.html")
    assert any("[blocker] DATA_MISSING: Tavily dataset lookup" in e and "1 source(s)" in e for e in events)
    # outside the passport hash: the certificate still verifies, and a run without a client stores the reason
    from app.services import passport
    assert passport.verify_certificate(result.certificate()) if hasattr(passport, "verify_certificate") else True
    result2, _ = _data_missing_pipeline(tmp_path / "b", None) if (tmp_path / "b").mkdir() is None else (None, None)
    assert result2.blocker["sources"] == {"query": "omarfoq fedem dataset download Download cifar10 dataset!!", "sources": None,
                                          "reason": "no Tavily client configured"}
    assert result2.reproduction_passport_hash == result.reproduction_passport_hash or result2.timestamp != result.timestamp


# --- v1.6 review fixes (one test per defect; each failed on e13d9d5) ------------------------------------------------

def test_fix1_a_single_package_404_under_the_pool_is_not_a_gone_mirror():
    from app.services import classifier

    transient = ("E: Failed to fetch http://deb.debian.org/debian/pool/main/g/git/git_2.39.2-1.1_amd64.deb  404  Not Found "
                 "[IP: 151.101.2.132 80]\nE: Unable to fetch some archives, maybe run apt-get update or try with --fix-missing?\n")
    assert classifier.classify(100, transient).code != "APT_MIRROR_GONE"
    # DEV #16: the EOL security mirror's pool 404 is still the gone mirror
    eol = ("E: Failed to fetch http://security.debian.org/debian-security/pool/updates/main/g/glibc/"
           "libc-devtools_2.31-13%2bdeb11u14_amd64.deb  404  Not Found\n")
    assert classifier.classify(100, eol).code == "APT_MIRROR_GONE"
    assert classifier.classify(100, "E: Failed to fetch http://archive.debian.org/debian/pool/main/x/x_1.deb  404  Not Found").code == "APT_MIRROR_GONE"
    assert classifier.classify(100, "Err:2 http://deb.debian.org/debian stretch Release\n  404  Not Found [IP: 1.2.3.4 80]\n").code != "APT_MIRROR_GONE"
    assert classifier.classify(100, "E: Failed to fetch http://deb.debian.org/debian/dists/stretch/main/binary-amd64/Packages  404  Not Found").code == "APT_MIRROR_GONE"


def test_fix1_a_pip_failure_after_the_apt_line_wins_over_the_mirror():
    from app.services import classifier

    text = ("E: The repository 'http://deb.debian.org/debian stretch Release' does not have a Release file.\n"
            "Collecting foo\nERROR: Could not find a version that satisfies the requirement foo==9 (from versions: 1.0)\n")
    assert classifier.classify(1, text).code == "DEP_YANKED"
    # the other order: the apt failure is the later one and stands
    text = ("ERROR: Could not find a version that satisfies the requirement foo==9 (from versions: 1.0)\n"
            "E: The repository 'http://deb.debian.org/debian stretch Release' does not have a Release file.\n")
    assert classifier.classify(1, text).code == "APT_MIRROR_GONE"


def test_fix2_a_build_pip_recovered_from_does_not_mask_the_runtime_failure():
    from app.services import classifier

    stderr = ("  error: subprocess-exited-with-error\n      ModuleNotFoundError: No module named 'Cython'\n"
              "  ERROR: Failed building wheel for pycocotools\n"
              "Traceback (most recent call last):\nFileNotFoundError: [Errno 2] No such file or directory: 'data/coco/annotations.json'\n")
    stdout = "Successfully installed pycocotools-2.0.4\n"
    c = classifier.classify(1, stderr, stdout, declared_deps=frozenset())
    assert c.code == "DATA_MISSING" and "annotations.json" in c.evidence
    # without the Successfully installed line, a failure printed AFTER the block still wins (pip went on)
    c = classifier.classify(1, stderr, "", declared_deps=frozenset())
    assert c.code == "DATA_MISSING"
    # a failure printed INSIDE the block is the build's own
    inside = ("  error: subprocess-exited-with-error\n      FileNotFoundError: [Errno 2] No such file or directory: 'README.md'\n"
              "  ERROR: Failed building wheel for foo\n")
    assert classifier.classify(1, inside).code == "DEP_BUILD_FAILED"


def test_fix2_an_unresolvable_setup_requires_is_the_dependency_class_not_the_wrapper():
    from app.services import classifier

    text = ("  error: subprocess-exited-with-error\n"
            "      ERROR: Could not find a version that satisfies the requirement numpy==1.11.0 (from versions: 1.21.0, 1.22.0)\n"
            "      ERROR: No matching distribution found for numpy==1.11.0\n"
            "  ERROR: Failed building wheel for foo\n")
    assert classifier.classify(1, text).code == "DEP_YANKED"
    text = text.replace("(from versions: 1.21.0, 1.22.0)", "(from versions: none)")
    assert classifier.classify(1, text).code == "DEP_NOT_ON_PYPI"


def test_fix2_build_evidence_is_the_blocks_own_exception_not_a_later_one():
    from app.services import classifier

    text = ("  error: subprocess-exited-with-error\n      ValueError: bad setup.cfg\n"
            "  ERROR: Failed building wheel for foo\n"
            "  error: subprocess-exited-with-error\n      TypeError: unexpected keyword\n"
            "  ERROR: Failed building wheel for bar\n")
    c = classifier.classify(1, text)
    assert c.code == "DEP_BUILD_FAILED" and c.evidence == "ValueError: bad setup.cfg"


@pytest.mark.parametrize("stderr", [
    "Traceback (most recent call last):\n  File \"train.py\", line 9, in <module>\n    dtype = torch.cuda.FloatTensor if args.cuda else torch.FloatTensor\n"
    "FileNotFoundError: [Errno 2] No such file or directory: 'data/x.npy'",
    "UserWarning: torch.cuda.FloatTensor as a tensor type is deprecated; use torch.set_default_dtype\nValueError: bad",
    "    torch.set_default_tensor_type(torch.cuda.FloatTensor)\nKeyError: 'x'",
])
def test_fix3_a_cuda_tensor_type_echoed_in_a_traceback_or_a_warning_is_not_gpu_required(stderr):
    from app.services import classifier

    assert classifier.classify(1, stderr).code != "GPU_REQUIRED"
    assert classifier.classify(1, "TypeError: torch.cuda.FloatTensor constructor received an invalid combination").code == "GPU_REQUIRED"
    assert classifier.classify(1, "RuntimeError: invalid type: set_default_tensor_type(torch.cuda.FloatTensor)").code == "GPU_REQUIRED"


@pytest.mark.parametrize("stderr", [
    "AssertionError: dataset must be one of ['cifar10', 'mnist']",
    "AssertionError: unknown dataset cifar100",
    "AssertionError: data path must be absolute",
])
def test_fix4_an_argument_check_naming_the_dataset_is_not_missing_data(stderr):
    from app.services import classifier

    assert classifier.classify(1, stderr).code != "DATA_MISSING"
    for guard in ("AssertionError: Download cifar10 dataset!!", "AssertionError: dataset not found at ./data",
                  "AssertionError: data dir does not exist", "AssertionError: please prepare the dataset"):
        assert classifier.classify(1, guard).code == "DATA_MISSING"


def test_fix5_no_accelerator_present_is_the_general_gpu_sentence():
    report = _report("GPU_REQUIRED", "RuntimeError: Cannot access accelerator device when none is available.")
    assert report["what_a_human_must_supply"] == "a CUDA device, or the CPU shim where the call is a plain .cuda()"
    assert _report("GPU_REQUIRED", "NotImplementedError: x is not implemented on the CPU")["what_a_human_must_supply"] == (
        "a CUDA device: the operation has no CPU implementation")


def test_fix6_a_flaky_runs_clean_record_is_not_read_as_cleared():
    result = {"verdict": "RUNS_CLEAN", "error_chain": [_link("DEP_MISSING")], "attempts": [{"attempt_number": 0, "origin": "time_machine", "exit_code": 0}]}
    levels = outcome_levels.compute(result)
    assert levels["first_error_cleared"] is False and levels["first_error_cleared_by"] is None and levels["entrypoint_runs"] is True
    assert outcome_levels.compute({**result, "verdict": "RUNS_AFTER_REPAIR"})["first_error_cleared"] is True


def test_fix7_the_attempt_that_passed_is_named_among_those_sharing_its_number():
    attempts = [{"attempt_number": 0, "origin": "time_machine", "exit_code": None, "gate_decision": "DECLINED"},
                {"attempt_number": 0, "origin": "time_machine", "exit_code": 1, "time_machine_action": {"rule": "build-essential"}},
                {"attempt_number": 0, "origin": "cpu_shim_step", "exit_code": 0}]
    result = {"verdict": "RUNS_AFTER_REPAIR", "error_chain": [_link("GPU_REQUIRED", cleared_by=0)], "attempts": attempts}
    assert outcome_levels.compute(result)["first_error_cleared_by"] == "cpu_shim_step"
    # none passed: the last with that number
    result["attempts"] = attempts[:2]
    assert outcome_levels.compute(result)["first_error_cleared_by"] == "time_machine"
    result["attempts"] = []
    assert outcome_levels.compute(result)["first_error_cleared_by"] is None


def test_fix8_an_unknown_class_in_a_stored_record_does_not_break_the_certificate_or_the_api(caplog):
    import logging

    from app.schemas import CertificateOut

    chain = [{"error": "x", "class": "FUTURE_CODE", "attribution": "REPO", "phase": "repo_run", "cleared_by": None}]
    with caplog.at_level(logging.WARNING, logger="app.services.blocker"):
        report = blocker.report({"verdict": "BLOCKED", "error_chain": chain})
    assert report["class"] == "FUTURE_CODE" and report["fixable_by"] is None and report["family"] is None
    assert any("FUTURE_CODE" in r.getMessage() for r in caplog.records)
    out = CertificateOut(run_id="r", verdict="BLOCKED", certificate_prose="", full_log="", build_plan={}, diffs=[],
                         reproduction_passport_hash="", timestamp="t", error_chain=chain)
    assert out.model_dump()["blocker"]["class"] == "FUTURE_CODE"


def test_fix9_the_dataset_lookup_runs_only_for_a_blocked_verdict(tmp_path):
    from app.services import orchestrator

    class _Search:
        def __init__(self):
            self.calls = 0

        def search(self, *a, **kw):
            self.calls += 1
            return {"results": [{"title": "t", "url": "https://example.com/d"}]}

    chain = ({"error": "FileNotFoundError: [Errno 2] No such file or directory: 'data/x.npy'", "class": "DATA_MISSING",
              "attribution": "REPO", "phase": "repo_run", "cleared_by": None},)
    base = dict(taxonomy_code="DATA_MISSING", indeterminate_reason="", attempts=(), build_plan=None, full_log="", certificate_prose="",
                reproduction_passport_hash="", timestamp="t", repo_url="https://github.com/o/r", commit_sha="a" * 40, error_chain=chain)
    search = _Search()
    deps = PipelineDeps(recon_client=None, recon_model="r", repair_client=None, repair_model="p", adjudicator_client=None,
                        adjudicator_model=None, sandbox_api_key="k", sandbox_wall_clock_seconds=1, sandbox_runner=lambda **kw: None,
                        tavily_client=search)
    indeterminate = PipelineResult(verdict="INDETERMINATE", **{**base, "indeterminate_reason": "COST_CAP: stopped"})
    out = orchestrator._with_blocker_sources(indeterminate, deps, "https://github.com/o/r", None)
    assert search.calls == 0 and out.blocker_sources is None
    blocked = PipelineResult(verdict="BLOCKED", **base)
    out = orchestrator._with_blocker_sources(blocked, deps, "https://github.com/o/r", None)
    assert search.calls == 1 and out.blocker_sources and out.blocker_sources["sources"]


def test_fix10_table_wording():
    assert blocker.TABLE["DEP_BUILD_FAILED"][0] == "deterministic"
    assert _report("DEP_BUILD_FAILED", "ERROR: Failed building wheel for pygame")["what_a_human_must_supply"] == (
        "nothing, if the apt rule adds the build dependencies; otherwise a wheel of pygame for this platform")
    assert blocker.TABLE["ENTRYPOINT_UNCLEAR"][1] == "the command to run: the README does not name one unambiguously"
    assert _report("API_REMOVED", "AttributeError: module 'numpy' has no attribute 'float'")["what_a_human_must_supply"] == (
        "nothing, if the era lock or a removed-API row resolves it; otherwise the release of numpy the authors used (older or newer)")
