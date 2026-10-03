"""harness-v1.3.3: Tavily citation plumbing (D-3, Best Use of Tavily), the search query (D-4) and classifier noise (D-9).

Offline: a fake search client and fake models; the classifier, patch pipeline, tamper gate and passport run for real."""

from __future__ import annotations

import json
from pathlib import Path

from app.services import classifier, tavily
from app.services.cost_guard import CostGuard
from app.services.intake import RepoIntake
from app.services.orchestrator import PipelineDeps, run_pipeline
from app.services.passport import verify_certificate
from app.services.sandbox import SandboxRunResult, StepResult

# --- classifier: noise is not the error (D-9) -------------------------------------------------------------------------------

TF_WARNING = (
    "2026-09-30 13:50:27.517460: W tensorflow/stream_executor/platform/default/dso_loader.cc:55] "
    "Could not load dynamic library 'libnvinfer.so.6'; dlerror: libnvinfer.so.6: cannot open shared object file: No such file or directory"
)
GET_VARIABLE = "AttributeError: module 'tensorflow' has no attribute 'get_variable'"


def test_entry_12_a_benign_tensorflow_warning_is_not_classified_as_the_failure():
    stderr = f"{TF_WARNING}\nTraceback (most recent call last):\n  File \"SimplE.py\", line 20, in <module>\n{GET_VARIABLE}\n"
    c = classifier.classify(1, stderr)
    # harness-v1.6: the removed TensorFlow 1.x API is API_REMOVED (was RUNTIME_ERROR_OTHER); the evidence is still the exception line, never the warning
    assert c.code == classifier.TaxonomyCode.API_REMOVED and c.evidence == GET_VARIABLE


def test_entry_12_before_the_fix_the_same_text_was_sys_lib_missing():
    """Negative control on the old behaviour: without denoising the warning line matches the shared-library rule."""
    import re

    assert any(p.search(TF_WARNING) for rule in classifier._RULES if rule.code == "SYS_LIB_MISSING" for p in rule.patterns)  # noqa: SLF001
    assert re.search("cannot open shared object file", TF_WARNING)


def test_a_real_missing_shared_library_error_is_still_sys_lib_missing():
    stderr = "Traceback (most recent call last):\nImportError: libcudart.so.10.1: cannot open shared object file: No such file or directory\n"
    assert classifier.classify(1, stderr).code == classifier.TaxonomyCode.SYS_LIB_MISSING


def test_a_tensorflow_ERROR_line_is_kept_only_warning_and_info_levels_are_noise():
    error_line = "2026-09-30 13:50:27.517460: E tensorflow/stream_executor/cuda/cuda_driver.cc:318] failed call to cuInit: CUDA_ERROR_NO_DEVICE"
    assert "failed call to cuInit" in classifier.denoise(error_line)
    assert classifier.denoise(TF_WARNING) == ""


def test_entry_3_a_progress_fragment_is_not_recorded_as_the_error():
    stderr = "%17.5" * 40 + "%17.6" * 20
    c = classifier.classify(1, stderr)
    assert c.code == classifier.TaxonomyCode.RUNTIME_ERROR_OTHER
    assert c.evidence.startswith("exit code 1") and "17.6" not in c.evidence


def test_progress_bars_with_carriage_returns_keep_the_last_frame_and_the_real_error():
    stderr = "  0%|          | 0/10\r 50%|#####     | 5/10\r100%|##########| 10/10\nTraceback (most recent call last):\nRuntimeError: boom\n"
    c = classifier.classify(1, stderr)
    assert c.evidence == "RuntimeError: boom"


def test_denoised_evidence_still_appears_verbatim_in_the_raw_log():
    raw = f"{TF_WARNING}\n 50%|#####     | 5/10\r100%|##########| 10/10\n{GET_VARIABLE}\n"
    assert classifier.classify(1, raw).evidence in raw  # the env gate checks evidence against the raw log


# --- the query (D-4) --------------------------------------------------------------------------------------------------------------


def test_the_query_carries_error_framework_python_and_what_was_already_tried():
    q = tavily.build_query("RUNTIME_ERROR_OTHER", "ImportError: cannot import name 'Iterable' from 'collections'",
                           framework="pytorch", python_version="3.8", tried=("add tabulate==0.8.7",))
    assert q.startswith("python 3.8 pytorch runtime error other fix: ImportError: cannot import name 'Iterable'")
    assert q.endswith("| already tried: add tabulate==0.8.7")
    assert tavily.build_query("DEP_MISSING", "x") == "python dep missing fix: x"  # unchanged when nothing is known


def test_framework_and_python_detection():
    assert tavily.detect_framework({"numpy", "torch", "tensorflow"}) == "pytorch"
    assert tavily.detect_framework({"numpy", "chainer"}) == "chainer" and tavily.detect_framework({"numpy"}) == ""
    assert tavily.python_minor("python:3.8-slim") == "3.8" and tavily.python_minor(None) == ""


# --- orchestrator: the citation reaches the record and the passport ---------------------------------------------------------------

OLD_TRAIN = "from collections import Iterable\n\ndef run(x):\n    return isinstance(x, Iterable)\n\nprint(run([1]))\n"
ERROR = "ImportError: cannot import name 'Iterable' from 'collections' (/usr/local/lib/python3.10/collections/__init__.py)"
RESULTS = [
    {"title": "Fix: cannot import name Iterable", "url": "https://example.org/a", "content": "use collections.abc"},
    {"title": "What changed in Python 3.10", "url": "https://docs.python.org/3.10/whatsnew", "content": "ABCs moved to collections.abc"},
    {"title": "unrelated blog", "url": "https://example.org/blog", "content": "meh"},
]


class _Search:
    def __init__(self):
        self.queries = []

    def search(self, query, **kwargs):
        self.queries.append(query)
        return {"results": RESULTS}


class _Chat:
    def __init__(self, replies):
        self.replies = [json.dumps(r) for r in replies]
        self.calls = []

    def chat_completion(self, **kwargs):
        self.calls.append(kwargs)
        return self.replies.pop(0)


def _pipeline(tmp_path: Path, repair_replies, sandbox_results, search):
    (tmp_path / "train.py").write_text(OLD_TRAIN, encoding="utf-8")
    import subprocess

    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True, capture_output=True)
    for key, value in (("core.autocrlf", "false"), ("core.eol", "lf")):
        subprocess.run(["git", "config", key, value], cwd=tmp_path, check=True, capture_output=True)
    intake = RepoIntake(tmp_path, "a" * 40, {}, frozenset(), (), ("train.py",), None)
    results = list(sandbox_results)
    deps = PipelineDeps(
        recon_client=_Chat([{"entrypoint": "train.py", "confidence": 0.9}]), recon_model="r",
        repair_client=_Chat(repair_replies), repair_model="p", adjudicator_client=None, adjudicator_model=None,
        sandbox_api_key="k", sandbox_wall_clock_seconds=100, sandbox_runner=lambda **kw: results.pop(0),
        tavily_client=search, smoke_seconds=0,
    )
    result = run_pipeline(repo_url="https://example.com/r", commit_sha="a" * 40, workdir=tmp_path, intake_result=intake, deps=deps,
                          cost_guard=CostGuard(daily_cost_ceiling_usd=100), run_id="tv")
    return result, deps


def _fail():
    return SandboxRunResult(steps=(StepResult("python train.py", 1, "", ERROR, 1.0, 0.01),))


def _ok():
    return SandboxRunResult(steps=(StepResult("python train.py", 0, "True", "", 1.0, 0.01),))


FIX = {"file_edits": [{"path": "train.py", "old": "from collections import Iterable\n", "new": "from collections.abc import Iterable\n"}]}


def test_a_fix_that_used_a_search_result_carries_its_url_into_the_record_and_the_passport(tmp_path):
    search = _Search()
    result, _ = _pipeline(tmp_path, [{**FIX, "cited_sources": [2], "explanation": "ABCs moved in 3.10 (source 2)"}], [_fail(), _ok()], search)
    assert result.verdict == "RUNS_AFTER_REPAIR", result.full_log
    attempt = result.attempts[-1]
    assert [s["url"] for s in attempt.tavily_sources] == ["https://docs.python.org/3.10/whatsnew"]  # non-empty, the right one
    assert attempt.tavily_sources[0]["cited_via"] == "model_declared" and attempt.tavily_sources[0]["content"]
    assert "[citations] cited (model declared it used source [2])" in result.full_log
    cert = result.certificate()  # what the passport hashes and the dashboard shows
    assert cert["diffs"][-1]["tavily_sources"][0]["url"] == "https://docs.python.org/3.10/whatsnew"
    assert verify_certificate(cert)  # the hash covers it: edit the URL and it fails (next test)


def test_editing_a_cited_url_after_the_fact_breaks_the_passport_hash(tmp_path):
    result, _ = _pipeline(tmp_path, [{**FIX, "cited_sources": [1], "explanation": "x"}], [_fail(), _ok()], _Search())
    cert = result.certificate()
    assert verify_certificate(cert)
    cert["diffs"][-1]["tavily_sources"][0]["url"] = "https://evil.example/fake"
    assert not verify_certificate(cert)


def test_a_bad_citation_number_is_ignored_and_logged(tmp_path):
    result, _ = _pipeline(tmp_path, [{**FIX, "cited_sources": [9], "explanation": "x"}], [_fail(), _ok()], _Search())
    assert result.attempts[-1].tavily_sources == ()
    assert "[citations] ignored: the model cited source [9] but only 3 were offered" in result.full_log


def test_a_fix_that_cites_nothing_records_nothing(tmp_path):
    result, _ = _pipeline(tmp_path, [{**FIX, "cited_sources": [], "reason_no_citation": "none of the results applied", "explanation": "x"}],
                          [_fail(), _ok()], _Search())
    assert result.verdict == "RUNS_AFTER_REPAIR" and result.attempts[-1].tavily_sources == ()
    assert result.attempts[-1].reason_no_citation == "none of the results applied"


def test_a_citation_on_a_rejected_attempt_is_not_recorded_nothing_was_used(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_x.py").write_text("a\n", encoding="utf-8")
    protected = {"file_edits": [{"path": "tests/test_x.py", "old": "a", "new": "b"}], "cited_sources": [1], "explanation": "x"}
    result, _ = _pipeline(tmp_path, [protected, protected, protected], [_fail()], _Search())
    assert result.attempts and all(a.gate_decision == "REJECT" for a in result.attempts)  # a test file is a protected path
    assert all(a.tavily_sources == () for a in result.attempts)


def test_the_second_search_for_the_same_error_is_not_identical_to_the_first(tmp_path):
    """Entry 1 of v1.3.2 ran the same query twice because the error was unchanged. Now the second carries what the run already tried."""
    env_fix = {"env_delta": [{"op": "add", "package": "tabulate", "version": "0.8.7", "justification": "x", "evidence": ERROR}], "explanation": "x",
               "cited_sources": [], "reason_no_citation": "none applied"}
    search = _Search()
    _pipeline(tmp_path, [env_fix, {"explanation": "give up"}, {"explanation": "give up"}], [_fail(), _fail()], search)
    assert len(search.queries) >= 2
    assert search.queries[0] != search.queries[1]
    assert "already tried: add tabulate==0.8.7" in search.queries[1] and "already tried" not in search.queries[0]
    assert all("python 3.10" in q for q in search.queries)  # the plan's interpreter is in the query
