"""harness-v1.3.4: D-18 (the lock is never a file target), D-19 (silent failures), D-21 (required citations, consulted/cited),
D-22 (an attempt that ends INVALID_HARNESS is recorded). Offline: fake model and sandbox; the real classifier, patch pipeline, gate,
smoke launcher and passport run."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from app.services import classifier, repairer, smoke_exec, tamper_gate, tree_integrity
from app.services.cost_guard import CostGuard
from app.services.intake import RepoIntake
from app.services.orchestrator import PipelineDeps, run_pipeline
from app.services.passport import verify_certificate
from app.services.patch_pipeline import PatchProblem, resolve_patch
from app.services.sandbox import SandboxRunResult, StepResult, UploadIntegrityError
from app.services.time_machine import LockResult

TRAIN = "import os\nfor i in range(3):\n    print('17.%d%%' % i, end='')\nraise SystemExit(1)\n"
SILENT_STDERR = "%17.5%17.6%17.7%17.8"  # entry 3 of the v1.3.3 gate: a progress stream, exit 1, no error text
REFS = [
    {"title": "unrelated", "url": "https://example.org/one", "content": "meh"},
    {"title": "scikit-image API change", "url": "https://scikit-image.org/docs/api/skimage.metrics.html",
     "content": "compare_psnr was moved: use `from skimage.metrics import peak_signal_noise_ratio as compare_psnr` instead."},
    {"title": "blog", "url": "https://example.org/three", "content": "..."},
]


class _Chat:
    def __init__(self, replies):
        self.replies = [json.dumps(r) for r in replies]
        self.calls = []

    def chat_completion(self, **kw):
        self.calls.append(kw)
        if not self.replies:
            raise RuntimeError("fake chat client ran out of scripted responses")
        return self.replies.pop(0)


class _Search:
    def search(self, query, **kw):
        return {"results": REFS}


def _git(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True, capture_output=True)
    for k, v in (("core.autocrlf", "false"), ("core.eol", "lf"), ("user.email", "t@e.st"), ("user.name", "t")):
        subprocess.run(["git", "config", k, v], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-q", "-m", "x"], cwd=tmp_path, check=True, capture_output=True)  # the era needs a commit date


def _user_prompt(call: dict) -> str:
    return call.get("user_prompt") or json.dumps(call)


def _pipeline(tmp_path, files, replies, results, *, search=None, max_attempts=3, reqs=None):
    for rel, text in files.items():
        (tmp_path / rel).write_text(text, encoding="utf-8", newline="\n")  # LF on every host, as intake's clone guarantees
    _git(tmp_path)
    results = list(results)

    def runner(**kw):
        r = results.pop(0)
        if isinstance(r, Exception):
            raise r
        return r

    repair = _Chat(replies)
    deps = PipelineDeps(
        recon_client=_Chat([{"entrypoint": "train.py", "confidence": 0.9}]), recon_model="r", repair_client=repair, repair_model="p",
        adjudicator_client=None, adjudicator_model=None, sandbox_api_key="k", sandbox_wall_clock_seconds=100, sandbox_runner=runner,
        tavily_client=search, smoke_seconds=0, max_attempts=max_attempts,
        lock_compiler=lambda *a: LockResult(True, ("numpy==1.19.1",), ("numpy",)) if reqs == "lock" else LockResult(False, (), (), (), "", "off"),
    )
    dep_files = {"requirements.txt": reqs} if isinstance(reqs, str) and reqs != "lock" else {}
    intake = RepoIntake(tmp_path, "a" * 40, dep_files, frozenset(), (), ("train.py",), None)
    result = run_pipeline(repo_url="https://example.com/r", commit_sha="a" * 40, workdir=tmp_path, intake_result=intake, deps=deps,
                          cost_guard=CostGuard(daily_cost_ceiling_usd=100), run_id="v134")
    return result, repair


def _fail(stderr, stdout="", code=1):
    return SandboxRunResult(steps=(StepResult("python train.py", code, stdout, stderr, 1.0, 0.01),))


def _ok():
    return SandboxRunResult(steps=(StepResult("python train.py", 0, "ok", "", 1.0, 0.01),))


NO_CITE = {"cited_sources": [], "reason_no_citation": "no reference applied"}


# ===================================================================== D-19 =====================================================


def test_a_silent_exit_is_detected_and_a_traceback_is_not():
    assert not classifier.has_actionable_error(SILENT_STDERR, "")
    assert classifier.has_actionable_error("Traceback (most recent call last):\n  File x\nKeyError: 'a'\n")
    assert classifier.has_actionable_error("", "error: metadata-generation-failed\n")
    assert classifier.has_actionable_error("Fatal Python error: Segmentation fault\n")
    assert not classifier.has_actionable_error("2026-01-01 00:00:00.0: W tensorflow/x] Could not load dynamic library\n")  # noise only


def test_silent_failure_gives_the_repairer_head_tail_exit_code_and_the_no_traceback_rule(tmp_path):
    stdout = "\n".join(f"line {i}" for i in range(200))
    fix = {"file_edits": [{"path": "train.py", "old": "raise SystemExit(1)\n", "new": "print('x')\n"}], **NO_CITE, "explanation": "guess"}
    result, repair = _pipeline(tmp_path, {"train.py": TRAIN}, [fix], [_fail(SILENT_STDERR, stdout, code=1)], max_attempts=1)
    prompt = _user_prompt(repair.calls[0])
    assert "NO TRACEBACK FOUND" in prompt and "do not guess; first add diagnostics" in prompt and "exited with code 1" in prompt
    assert "line 0\n" in prompt and "line 199" in prompt and "[... 80 line(s) skipped ...]" in prompt  # 200 lines: head 40 + tail 80
    assert result.attempts[0].silent_exit is True and result.certificate()["diffs"][0]["silent_exit"] is True


def test_a_blind_code_patch_on_a_silent_exit_is_rejected_by_the_gate(tmp_path):
    blind = {"file_edits": [{"path": "train.py", "old": "raise SystemExit(1)\n", "new": "raise SystemExit(0)\n"}], **NO_CITE, "explanation": "guess"}
    result, _ = _pipeline(tmp_path, {"train.py": TRAIN}, [blind], [_fail(SILENT_STDERR)], max_attempts=1)
    assert result.verdict == "BLOCKED"
    attempt = result.attempts[0]
    assert attempt.gate_decision == "REJECT" and [v["rule"] for v in attempt.gate_violations] == [tamper_gate.GateRule.BLIND_PATCH_ON_SILENT_EXIT]
    assert "printed no error text" in attempt.gate_violations[0]["reason"]
    assert (tmp_path / "train.py").read_text() == TRAIN  # nothing applied


def test_a_diagnostics_only_patch_on_a_silent_exit_passes_and_runs(tmp_path):
    diag = {"file_edits": [{"path": "train.py", "old": "raise SystemExit(1)\n", "new": "import traceback\nprint('about to exit', flush=True)\nraise SystemExit(1)\n"}],
            **NO_CITE, "explanation": "add diagnostics"}
    result, _ = _pipeline(tmp_path, {"train.py": TRAIN}, [diag], [_fail(SILENT_STDERR), _fail("Traceback (most recent call last):\nRuntimeError: real\n")], max_attempts=1)
    assert result.attempts[0].gate_decision == "PASS" and result.attempts[0].exit_code == 1
    assert "print('about to exit', flush=True)" in (tmp_path / "train.py").read_text()


def test_the_silent_exit_rule_does_not_block_environment_changes(tmp_path):
    env = {"env_delta": [{"op": "add", "package": "h5py", "version": "3.1.0", "justification": "x", "evidence": "%17.5%17.6"}], **NO_CITE, "explanation": "env"}
    result, _ = _pipeline(tmp_path, {"train.py": TRAIN}, [env], [_fail(SILENT_STDERR), _ok()], max_attempts=1)
    assert result.verdict == "RUNS_AFTER_REPAIR"


def test_with_a_real_error_the_gate_does_not_apply_the_silent_rule(tmp_path):
    fix = {"file_edits": [{"path": "train.py", "old": "raise SystemExit(1)\n", "new": "raise SystemExit(0)\n"}], **NO_CITE, "explanation": "fix"}
    result, repair = _pipeline(tmp_path, {"train.py": TRAIN}, [fix], [_fail("Traceback (most recent call last):\nSystemExit: 1\n"), _ok()], max_attempts=1)
    assert result.verdict == "RUNS_AFTER_REPAIR" and "NO TRACEBACK FOUND" not in _user_prompt(repair.calls[0])


PY = f'"{sys.executable}"'


def _launch(command: str, seconds: int = 10):
    return subprocess.run(smoke_exec.wrap(command, seconds, python=PY), shell=True, capture_output=True, text=True, timeout=60)


def test_the_launcher_runs_unbuffered_so_output_before_a_hard_exit_survives():
    done = _launch(f"{PY} -c \"import os, sys; print('progress 17.7%', end=''); os._exit(1)\"")  # no flush, hard exit
    assert done.returncode == 1 and "progress 17.7%" in done.stdout


def test_the_launcher_enables_faulthandler_so_a_crash_leaves_a_trace():
    done = _launch(f"{PY} -c \"import ctypes; print('start', flush=True); ctypes.string_at(0)\"")
    assert done.returncode != 0 and ("Fatal Python error" in done.stderr or "Windows fatal exception" in done.stderr)
    assert classifier.has_actionable_error(done.stderr)  # the next repair sees an error, not a silent exit


# ===================================================================== D-18 =====================================================


def test_the_managed_lock_is_shown_under_its_own_name_and_cannot_be_a_file_target(tmp_path):
    (tmp_path / "train.py").write_text("import numpy\n", encoding="utf-8")
    bad = {"file_edits": [{"path": "requirements.txt", "old": "numpy==1.19.1", "new": "numpy==1.21.0"}], **NO_CITE, "explanation": "edit the lock"}
    result, repair = _pipeline(tmp_path, {"train.py": "import numpy\n"}, [bad, bad], [_fail("ModuleNotFoundError: No module named 'numpy'"), _fail("RuntimeError: still\n")],
                               max_attempts=1, reqs="lock")
    prompt = _user_prompt(repair.calls[0])
    assert "RERUN-managed lock (edit via env_delta only)" in prompt and "Dependency file requirements.txt" not in prompt
    attempt = [a for a in result.attempts if a.origin == "model"][0]
    assert attempt.gate_decision in ("REJECT", "DECLINED")
    assert any("not an existing file" in v["reason"] or "managed lock" in v["reason"] for v in attempt.gate_violations)


@pytest.mark.parametrize("name", [".rerun-requirements.txt", "RERUN-managed lock (edit via env_delta only)", "rerun-managed lock"])
def test_patch_pipeline_refuses_the_lock_names_outright(tmp_path, name):
    (tmp_path / ".rerun-requirements.txt").write_text("numpy==1.19.1\n", encoding="utf-8")
    _git(tmp_path)
    with pytest.raises(PatchProblem, match="managed lock"):
        resolve_patch(tmp_path, file_edits=[{"path": name, "old": "numpy==1.19.1", "new": "numpy==1.21.0"}])


def test_a_repositorys_own_requirements_file_is_still_shown_as_itself(tmp_path):
    (tmp_path / "requirements.txt").write_text("numpy\n", encoding="utf-8")
    decline = {"code_diff": None, "env_delta": [], **NO_CITE, "explanation": "no"}
    _, repair = _pipeline(tmp_path, {"train.py": "import numpy\n"}, [decline], [_fail("RuntimeError: x\n")], max_attempts=1, reqs="numpy\n")
    prompt = _user_prompt(repair.calls[0])
    assert "Dependency file requirements.txt" in prompt and "RERUN-managed lock" not in prompt


# ===================================================================== D-21 =====================================================

ERR = "ImportError: cannot import name 'compare_psnr' from 'skimage.measure'"
UTILS = "from skimage.measure import compare_psnr\n"
FIX2 = {"file_edits": [{"path": "train.py", "old": "from skimage.measure import compare_psnr\n",
                        "new": "from skimage.metrics import peak_signal_noise_ratio as compare_psnr\n"}], "explanation": "moved API"}


def test_references_are_numbered_and_the_full_list_is_stored_as_consulted(tmp_path):
    result, repair = _pipeline(tmp_path, {"train.py": UTILS}, [{**FIX2, "cited_sources": [2]}], [_fail(ERR), _ok()], search=_Search(), max_attempts=1)
    prompt = _user_prompt(repair.calls[0])
    assert "[1] unrelated" in prompt and "[2] scikit-image API change" in prompt and "[3] blog" in prompt and REFS[1]["url"] in prompt
    attempt = result.attempts[-1]
    assert [c["number"] for c in attempt.consulted] == [1, 2, 3] and attempt.consulted[1]["url"] == REFS[1]["url"]
    assert [c["url"] for c in attempt.tavily_sources] == [REFS[1]["url"]] and attempt.tavily_sources[0]["cited_via"] == "model_declared"
    cert = result.certificate()
    assert cert["diffs"][-1]["consulted"][1]["number"] == 2 and cert["diffs"][-1]["tavily_sources"][0]["url"] == REFS[1]["url"]
    assert verify_certificate(cert)
    cert["diffs"][-1]["consulted"][1]["url"] = "https://evil"
    assert not verify_certificate(cert)  # the hash covers the consulted list too


def test_fix_text_that_appears_in_reference_2_is_cited_as_2_even_when_the_model_declared_nothing(tmp_path):
    """The operator's fixture: the applied change's text is in reference [2]; the record must say cited=[2] (labelled content_match)."""
    result, _ = _pipeline(tmp_path, {"train.py": UTILS}, [{**FIX2, **NO_CITE}], [_fail(ERR), _ok()], search=_Search(), max_attempts=1)
    attempt = result.attempts[-1]
    assert [c["number"] for c in attempt.consulted] == [1, 2, 3]
    cited = attempt.tavily_sources
    assert [c["url"] for c in cited] == [REFS[1]["url"]] and cited[0]["cited_via"] == "content_match"
    assert "peak_signal_noise_ratio as compare_psnr" in cited[0]["matched_text"]
    assert attempt.reason_no_citation == "no reference applied"  # what the model said is kept beside the deterministic match
    assert "[citations] cited (the applied change's text appears in reference [2])" in result.full_log


def test_a_missing_cited_sources_field_is_re_asked_once_in_the_same_attempt(tmp_path):
    result, repair = _pipeline(tmp_path, {"train.py": UTILS}, [dict(FIX2), {**FIX2, "cited_sources": [2]}], [_fail(ERR), _ok()], search=_Search(), max_attempts=1)
    # harness-v1.6: ERR is API_REMOVED, so the era lock is tried first (declined here: the lock is off) and one MODEL attempt follows
    assert result.verdict == "RUNS_AFTER_REPAIR" and len([a for a in result.attempts if a.origin == "model"]) == 1
    assert len(repair.calls) == 2 and "cited_sources" in json.dumps(repair.calls[1]) and "is missing" in json.dumps(repair.calls[1])
    assert [c["cited_via"] for c in result.attempts[-1].tavily_sources] == ["model_declared"]


def test_a_field_still_missing_after_the_re_ask_keeps_the_fix_and_records_the_omission(tmp_path):
    result, _ = _pipeline(tmp_path, {"train.py": UTILS}, [dict(FIX2), dict(FIX2)], [_fail(ERR), _ok()], search=_Search(), max_attempts=1)
    assert result.verdict == "RUNS_AFTER_REPAIR"
    assert result.attempts[-1].reason_no_citation.startswith("(not given by the model after a re-ask")


def test_no_references_means_no_citation_requirement(tmp_path):
    result, repair = _pipeline(tmp_path, {"train.py": UTILS}, [dict(FIX2)], [_fail(ERR), _ok()], search=None, max_attempts=1)
    assert result.verdict == "RUNS_AFTER_REPAIR" and len(repair.calls) == 1 and result.attempts[-1].consulted == ()


def test_citation_field_problem_rules():
    p = repairer.parse_repair_response({**FIX2})
    assert repairer.citation_field_problem(p, 3) == 'the required field "cited_sources" is missing'
    assert repairer.citation_field_problem(repairer.parse_repair_response({**FIX2, "cited_sources": []}), 3) == '"cited_sources" is empty and "reason_no_citation" is missing'
    assert repairer.citation_field_problem(repairer.parse_repair_response({**FIX2, **NO_CITE}), 3) is None
    assert repairer.citation_field_problem(repairer.parse_repair_response({**FIX2, "cited_sources": [1]}), 3) is None
    assert repairer.citation_field_problem(p, 0) is None


# ===================================================================== D-22 =====================================================


def test_an_attempt_whose_reexecution_is_void_is_recorded_with_its_patch_before_the_verdict(tmp_path):
    """Entry 8 of the v1.3.3 gate: the applied patch existed only in log lines. Now the attempt is in the record and the passport."""
    void = UploadIntegrityError("post-extraction check failed (exit code 97)", stderr="RERUN_UPLOAD_MISMATCH 1 file(s): train.py (content)\n")
    result, _ = _pipeline(tmp_path, {"train.py": UTILS}, [{**FIX2, "cited_sources": [2]}], [_fail(ERR), void], search=_Search(), max_attempts=1)
    assert result.verdict == tree_integrity.INVALID_HARNESS
    model_attempts = [a for a in result.attempts if a.origin == "model"]  # harness-v1.6: a declined era-lock attempt 0 precedes it (ERR is API_REMOVED)
    assert len(model_attempts) == 1
    attempt = model_attempts[0]
    assert attempt.gate_decision == "PASS" and "peak_signal_noise_ratio" in attempt.diff_text and attempt.exit_code is None
    assert "run void (INVALID_HARNESS)" in attempt.stderr_tail and "train.py (content)" in attempt.stderr_tail
    assert [c["url"] for c in attempt.tavily_sources] == [REFS[1]["url"]] and attempt.patch_notes
    cert = result.certificate()
    assert cert["diffs"][-1]["diff_text"] == attempt.diff_text and verify_certificate(cert)
