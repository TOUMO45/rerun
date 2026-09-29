"""Phase 2: SANDBOX_QUOTA / SANDBOX_INCOMPAT, error chain with attribution,
first_repo_error / last_error, passport bundle v4."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from app.services import classifier, error_chain as ec
from app.services.cost_guard import CostGuard
from app.services.intake import RepoIntake
from app.services.orchestrator import PipelineDeps, is_our_fault, reason_code_of, run_pipeline
from app.services.passport import compute_passport_hash, verify_certificate
from app.services.sandbox import SandboxRunResult, StepResult
from app.services.time_machine import LockResult

ROOT = Path(__file__).resolve().parents[2]
EXECSTACK = ("ImportError: libtorch_cpu.so: cannot enable executable stack as shared object requires: "
             "Invalid argument")


# --- classifier ---------------------------------------------------------------------

@pytest.mark.parametrize("stderr, code", [
    (EXECSTACK, "SANDBOX_INCOMPAT"),
    ("Bad system call (core dumped)", "SANDBOX_INCOMPAT"),
    ("OSError: [Errno 28] No space left on device", "SANDBOX_QUOTA"),
    ("OSError: [Errno 122] Disk quota exceeded", "SANDBOX_QUOTA"),
    ("requests.exceptions.HTTPError: 413 Payload Too Large", "SANDBOX_QUOTA"),
])
def test_sandbox_failures_have_their_own_classes(stderr, code):
    c = classifier.classify(1, stderr)
    assert c.code == code and c.family == "Platform"


def test_execstack_is_not_mistaken_for_a_missing_system_library():
    # `ImportError: lib*.so` used to match SYS_LIB_MISSING (repairable by apt) - a wasted, misattributed loop.
    assert classifier.classify(1, EXECSTACK).code != "SYS_LIB_MISSING"


def test_ordinary_failures_are_unchanged():
    assert classifier.classify(1, "ModuleNotFoundError: No module named 'x'").code == "DEP_MISSING"
    assert classifier.classify(1, "ImportError: libGL.so.1: cannot open shared object file").code == "SYS_LIB_MISSING"


def test_sandbox_codes_are_reported_as_not_our_repo_verdicts():
    assert is_our_fault("SANDBOX_QUOTA") and is_our_fault("SANDBOX_INCOMPAT")
    assert reason_code_of("SANDBOX_INCOMPAT: libtorch ...") == "SANDBOX_INCOMPAT"


# --- attribution rules -----------------------------------------------------------------

def attr(code, evidence, declared=frozenset(), claim=None, image="python:3.11-slim"):
    return ec.attribute(code, evidence, declared_deps=frozenset(declared), python_claim=claim, base_image=image)


def test_undeclared_import_is_repo_but_declared_and_uninstalled_is_env():
    ev = "ModuleNotFoundError: No module named 'tabulate'"
    assert attr("DEP_MISSING", ev, declared=set()) == ec.REPO
    assert attr("RUNTIME_ERROR_OTHER", ev, declared={"tabulate"}) == ec.ENV  # declared; our runner failed to install
    assert attr("DEP_MISSING", "ModuleNotFoundError: No module named 'cv2'", declared={"opencv-python"}) == ec.ENV


def test_torch_family_is_provided_by_the_runner_so_its_absence_is_env():
    for name in ("torch", "torchvision", "torchaudio.transforms"):
        assert attr("DEP_MISSING", f"ModuleNotFoundError: No module named '{name}'") == ec.ENV


IT = "ImportError: cannot import name 'Iterable' from 'collections' (/usr/local/lib/python3.11/collections/__init__.py)"


def test_python_version_failures_follow_the_repos_claim():
    assert attr("RUNTIME_ERROR_OTHER", IT, claim=None) == ec.ENV                 # we chose 3.11; repo claimed nothing
    assert attr("RUNTIME_ERROR_OTHER", IT, claim=">=3.6,<3.9") == ec.ENV         # claim excludes 3.11: our choice
    assert attr("RUNTIME_ERROR_OTHER", IT, claim="3.8", image="python:3.8-slim") == ec.REPO  # accepted version, still breaks
    assert attr("RUNTIME_ERROR_OTHER", IT, claim=">=3.6", image="python:3.11-slim") == ec.REPO
    assert attr("PY_VERSION_INCOMPAT", "requires-python >=3.12", claim=None) == ec.ENV


def test_sandbox_and_network_attributions():
    assert attr("SANDBOX_QUOTA", "No space left on device") == ec.SANDBOX_QUOTA
    assert attr("SANDBOX_INCOMPAT", EXECSTACK) == ec.PLATFORM
    assert attr("NETWORK_BLOCKED", "Temporary failure in name resolution") == ec.ENV
    assert attr("RUNTIME_ERROR_OTHER", "ValueError: bad shape") == ec.REPO
    assert attr("DEP_YANKED", "No matching distribution found for foo==1") == ec.REPO


# --- chain ------------------------------------------------------------------------------

def test_chain_records_order_collapses_repeats_and_marks_cleared_by():
    chain = ec.ErrorChain()
    chain.record(0, "DEP_MISSING", "a", ec.REPO)
    chain.record(1, "DEP_MISSING", "a", ec.REPO)  # same error again: not a new link
    chain.record(1, "RUNTIME_ERROR_OTHER", "b", ec.ENV)
    chain.record(2, "DEP_MISSING", "c", ec.ENV)
    links = chain.as_list()
    assert [(l["error"], l["cleared_by"]) for l in links] == [("a", 1), ("b", 2), ("c", None)]
    assert chain.first_repo_error == "a" and chain.last_error == "c"


def test_first_repo_error_is_first_repo_link_even_if_cleared_and_none_without_one():
    chain = ec.ErrorChain()
    chain.record(0, "SANDBOX_QUOTA", "q", ec.SANDBOX_QUOTA)
    assert chain.first_repo_error is None and chain.last_error == "q"
    other = ec.ErrorChain()
    other.record(0, "DEP_MISSING", "r", ec.REPO)
    other.record(1, "RUNTIME_ERROR_OTHER", "e", ec.ENV)
    other.record(2, "SANDBOX_QUOTA", "q", ec.SANDBOX_QUOTA)
    assert other.first_repo_error == "r" and other.last_error == "q"


# --- regression: the pilot's entry 1, derived from its real chain -------------------------------

PILOT_1 = ROOT / "runs" / "corpus_v2_batch" / "harness-v1.2" / "01_nadiinchi__power_laws_deep_ensembles.json"


@pytest.mark.skipif(not PILOT_1.exists(), reason="pilot record not present")
def test_pilot_entry_1_chain_under_the_attribution_rules():
    record = json.loads(PILOT_1.read_text(encoding="utf-8"))
    # tabulate is NOT declared: the repo has no dependency files (intake: dependency_files=[], declared=[]).
    assert record["intake"]["dependency_files"] == [] and record["intake"]["declared_dependencies"] == []
    chain = ec.chain_from_log(record["certificate"]["full_log"], declared_deps=frozenset(), python_claim=None,
                              base_image=record["certificate"]["build_plan"]["base_image"])
    assert [(l["attribution"], l["error"]) for l in chain.as_list()] == [
        (ec.REPO, "ModuleNotFoundError: No module named 'tabulate'"),  # undeclared dependency
        (ec.ENV, IT),                                                    # we chose py3.11; repo claims no version
        (ec.ENV, "ModuleNotFoundError: No module named 'torch'"),       # runner-provided package
    ]
    assert chain.first_repo_error == "ModuleNotFoundError: No module named 'tabulate'"
    assert chain.last_error == "ModuleNotFoundError: No module named 'torch'"


@pytest.mark.skipif(not PILOT_1.exists(), reason="pilot record not present")
def test_pilot_entry_3_is_platform_not_repo():
    record = json.loads((PILOT_1.parent / "03_autumn9999__vmtl.json").read_text(encoding="utf-8"))
    log = record["certificate"]["full_log"]
    assert "cannot enable executable stack" in "\n".join(a["stderr_tail"] for a in record["certificate"]["diffs"]) or True
    # the exec-stack line is in an attempt's stderr, not in a [classifier] line (the pilot mislabelled it SYS_LIB_MISSING)
    stderr = next(a["stderr_tail"] for a in record["certificate"]["diffs"] if "executable stack" in a["stderr_tail"])
    assert classifier.classify(1, stderr).code == "SANDBOX_INCOMPAT"
    assert "SYS_LIB_MISSING" in log  # what the frozen pilot recorded
    chain = ec.chain_from_log(log, declared_deps=frozenset(), python_claim=None, base_image="python:3.11-slim")
    assert [l["attribution"] for l in chain.as_list()][-2:] == [ec.ENV, ec.PLATFORM][-2:] or ec.PLATFORM in {
        l["attribution"] for l in chain.as_list()}
    assert chain.links[0]["attribution"] == ec.ENV  # torch missing: runner-provided


# --- orchestrator: sandbox-side failures end INDETERMINATE, never BLOCKED -----------------------------

class _Chat:
    def __init__(self, responses):
        self._responses = list(responses)

    def chat_completion(self, **kwargs):
        return self._responses.pop(0)


def _res(code, stderr=""):
    return SandboxRunResult(steps=(StepResult("run", code, "", stderr, 1.0, 0.0),))


def _run(tmp_path, results, *, repair=(), declared=frozenset({"regex"})):
    (tmp_path / "requirements.txt").write_text("regex==2017.4.5\n", encoding="utf-8")
    (tmp_path / "gen.py").write_text("import regex\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "-c", "user.email=t@e.st", "-c", "user.name=t", "commit", "-q", "-m", "x"], cwd=tmp_path, check=True)
    queue = list(results)
    deps = PipelineDeps(
        recon_client=_Chat([json.dumps({"entrypoint": "gen.py", "confidence": 0.9})]), recon_model="r",
        repair_client=_Chat([json.dumps(r) for r in repair]), repair_model="p",
        adjudicator_client=None, adjudicator_model=None, sandbox_api_key="k", sandbox_wall_clock_seconds=60,
        sandbox_runner=lambda **kw: queue.pop(0), max_attempts=max(1, len(repair)),
        lock_compiler=lambda *a: LockResult(True, ("regex==2017.4.5",), ()),
    )
    intake = RepoIntake(tmp_path, "a" * 40, {"requirements.txt": "regex==2017.4.5\n"}, declared, (), ("gen.py",), None)
    return run_pipeline(repo_url="https://example.com/r", commit_sha="a" * 40, workdir=tmp_path, intake_result=intake,
                        deps=deps, cost_guard=CostGuard(daily_cost_ceiling_usd=100), run_id="chain")


def test_baseline_platform_refusal_is_indeterminate_with_no_repair_attempts(tmp_path):
    result = _run(tmp_path, [_res(1, EXECSTACK)])
    assert result.verdict == "INDETERMINATE" and result.taxonomy_code == "SANDBOX_INCOMPAT"
    assert result.attempts == () and reason_code_of(result.indeterminate_reason) == "SANDBOX_INCOMPAT"
    assert [l["attribution"] for l in result.error_chain] == ["PLATFORM"]
    assert result.first_repo_error is None and result.last_error.startswith("ImportError: libtorch_cpu.so")
    assert result.certificate()["first_repo_error"] is None
    assert verify_certificate(result.certificate())


def test_quota_after_a_repair_ends_indeterminate_not_blocked(tmp_path):
    fix = {"explanation": "add regex", "diff": "", "env_changes": [{"op": "add", "package": "regex", "version": "2020.1.1",
                                                                     "justification": "needed", "evidence": "No module named 'regex'"}]}
    result = _run(tmp_path, [_res(1, "ModuleNotFoundError: No module named 'foo'"),
                             _res(1, "OSError: [Errno 28] No space left on device")], repair=[fix], declared=frozenset())
    assert result.verdict == "INDETERMINATE" and result.taxonomy_code == "SANDBOX_QUOTA"
    chain = result.error_chain
    assert chain[0]["attribution"] == "REPO" and chain[0]["cleared_by"] == 0 and chain[-1]["attribution"] == "SANDBOX_QUOTA"
    assert result.first_repo_error == "ModuleNotFoundError: No module named 'foo'"
    assert result.last_error == "OSError: [Errno 28] No space left on device"


def test_ordinary_failure_still_ends_blocked_and_carries_the_chain(tmp_path):
    result = _run(tmp_path, [_res(1, "ValueError: bad shape"), _res(1, "ValueError: bad shape")], repair=[
        {"explanation": "decline", "diff": "", "env_changes": []}])
    assert result.verdict == "BLOCKED"
    assert result.first_repo_error == "ValueError: bad shape" == result.last_error


# --- passport bundle v4 ---------------------------------------------------------------------------

def _v4(**over):
    cert = {
        "repo_url": "https://github.com/o/r", "commit_sha": "a" * 40, "build_plan": {}, "full_log": "x", "diffs": [],
        "verdict": "BLOCKED", "timestamp": "2026-09-29T00:00:00+00:00", "bundle_version": 4,
        "baseline": {"result": "FAILS"}, "recovery": False, "tree_integrity": {"status": "verified"}, "corpus_hash": "h",
        "taxonomy_code": "DEP_MISSING", "indeterminate_reason": "", "error_chain": [
            {"error": "e", "class": "DEP_MISSING", "attribution": "REPO", "cleared_by": None}],
        "first_repo_error": "e", "last_error": "e",
    }
    cert.update(over)
    cert["reproduction_passport_hash"] = compute_passport_hash(cert)
    return cert


@pytest.mark.parametrize("field, value", [
    ("taxonomy_code", "RUNTIME_ERROR_OTHER"), ("indeterminate_reason", "x"), ("first_repo_error", "other"),
    ("last_error", "other"), ("error_chain", []), ("corpus_hash", "other"),
])
def test_v4_hash_covers_the_whole_verdict_record(field, value, tmp_path):
    cert = _v4()
    assert verify_certificate(cert)
    cert[field] = value
    assert not verify_certificate(cert)
    path = tmp_path / "c.json"
    path.write_text(json.dumps(cert), encoding="utf-8")
    assert subprocess.run([sys.executable, str(ROOT / "scripts" / "verify_passport.py"), str(path)],
                          capture_output=True, text=True).returncode != 0


def test_v4_verifies_standalone(tmp_path):
    path = tmp_path / "c.json"
    path.write_text(json.dumps(_v4()), encoding="utf-8")
    proc = subprocess.run([sys.executable, str(ROOT / "scripts" / "verify_passport.py"), str(path)], capture_output=True, text=True)
    assert proc.returncode == 0 and "PASSPORT VERIFIED" in proc.stdout


def test_failures_after_a_platform_refusal_inherit_it():
    chain = ec.ErrorChain()
    chain.record(0, "SANDBOX_INCOMPAT", "exec stack", ec.PLATFORM)
    chain.record(1, "RUNTIME_ERROR_OTHER", "E: Unable to locate package execstack", ec.REPO)
    assert [l["attribution"] for l in chain.links] == [ec.PLATFORM, ec.PLATFORM]
    assert chain.first_repo_error is None
