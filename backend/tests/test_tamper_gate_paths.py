"""Tamper gate: every touched file is checked; paths are normalized once and
used for both the gate and `git apply`.

Found live (DECISIONS.md 2026-09-24): `check_patch` skipped any touched file
missing from `original_sources`, and the orchestrator passed only the
repairer's target file — so a diff deleting `evaluate()` from a *different*
file PASSed and was applied.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from app.services.cost_guard import CostGuard
from app.services.intake import RepoIntake
from app.services.orchestrator import PipelineDeps, run_pipeline
from app.services.sandbox import SandboxRunResult, StepResult
from app.services.tamper_gate import GateRule, check_patch, prepare_patch

OTHER_PY = "def main():\n    model = build()\n    evaluate(model)\n\nmain()\n"
EVAL_DELETION_IN_OTHER = (
    "--- a/src/other.py\n+++ b/src/other.py\n@@ -1,5 +1,4 @@\n"
    " def main():\n     model = build()\n-    evaluate(model)\n \n main()\n"
)


def _rules(result):
    return {v.rule for v in result.violations}


# --- (a) the offline repro: a non-target file is now checked ---------------


def test_a_eval_deletion_in_a_file_the_caller_did_not_pass_is_rejected():
    result = check_patch(EVAL_DELETION_IN_OTHER, {"src/target.py": "print(1)\n"}, eval_call_names=frozenset({"evaluate"}))
    assert result.decision == "REJECT"
    assert GateRule.UNVERIFIED_FILE in _rules(result)


def test_a_same_diff_with_the_file_loaded_is_rejected_for_the_real_reason():
    result = check_patch(EVAL_DELETION_IN_OTHER, {"src/other.py": OTHER_PY}, eval_call_names=frozenset({"evaluate"}))
    assert result.decision == "REJECT"
    assert GateRule.DELETED_EVAL_CALL in _rules(result)


# --- (b) traversal / (c) absolute ------------------------------------------


@pytest.mark.parametrize(
    "header",
    ["../outside.py", "a/../outside.py", "src/../../outside.py", "b/src/../../../etc/passwd"],
)
def test_b_path_traversal_is_rejected(header):
    diff = f"--- {header}\n+++ {header}\n@@ -1 +1 @@\n-x = 1\n+x = 2\n"
    result = check_patch(diff, {header: "x = 1\n"})
    assert result.decision == "REJECT"
    assert GateRule.UNSAFE_PATH in _rules(result)


@pytest.mark.parametrize("header", ["/src/train.py", "/etc/passwd", "C:/Users/x/train.py", "\\\\server\\share\\x.py"])
def test_c_absolute_path_is_rejected(header):
    diff = f"--- {header}\n+++ {header}\n@@ -1 +1 @@\n-x = 1\n+x = 2\n"
    result = check_patch(diff, {"src/train.py": "x = 1\n"})
    assert result.decision == "REJECT"
    assert GateRule.UNSAFE_PATH in _rules(result)


def test_whole_file_deletion_is_rejected():
    diff = "--- a/train.py\n+++ /dev/null\n@@ -1 +0,0 @@\n-x = 1\n"
    result = check_patch(diff, {"train.py": "x = 1\n"})
    assert result.decision == "REJECT"
    assert GateRule.FILE_DELETION in _rules(result)


def test_rename_is_rejected():
    diff = "--- a/train.py\n+++ b/train2.py\n@@ -1 +1 @@\n-x = 1\n+x = 2\n"
    result = check_patch(diff, {"train.py": "x = 1\n"})
    assert result.decision == "REJECT"
    assert GateRule.UNSAFE_PATH in _rules(result)


def test_protected_path_still_rejected_after_normalization():
    diff = "--- ./tests/test_x.py\n+++ ./tests/test_x.py\n@@ -1 +1 @@\n-x = 1\n+x = 2\n"
    result = check_patch(diff, {"tests/test_x.py": "x = 1\n"})
    assert GateRule.PROTECTED_PATH_MODIFIED in _rules(result)


@pytest.mark.skipif(os.name == "nt", reason="creating symlinks needs elevated privileges on Windows")
def test_symlinked_path_is_rejected(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.py").write_text("x = 1\n", encoding="utf-8")
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "link").symlink_to(outside, target_is_directory=True)
    diff = "--- a/link/secret.py\n+++ b/link/secret.py\n@@ -1 +1 @@\n-x = 1\n+x = 2\n"
    result = check_patch(diff, {"link/secret.py": "x = 1\n"}, repo_root=repo)
    assert result.decision == "REJECT"
    assert GateRule.UNSAFE_PATH in _rules(result)


# --- (d) a legitimate 2-file repair PASSes ---------------------------------

TRAIN_PY = "import numpy as np\n\n\ndef main():\n    print(np.zeros(2))\n\n\nmain()\n"
REQS = "numpy\n"
TWO_FILE_DIFF = (
    "--- a/requirements.txt\n+++ b/requirements.txt\n@@ -1 +1 @@\n-numpy\n+numpy==1.26.4\n"
    "--- a/train.py\n+++ b/train.py\n@@ -2,7 +2,7 @@\n \n \n def main():\n"
    "-    print(np.zeros(2))\n+    print(np.zeros(3))\n \n \n main()\n"
)


def test_d_legit_two_file_repair_passes():
    result = check_patch(TWO_FILE_DIFF, {"train.py": TRAIN_PY, "requirements.txt": REQS})
    assert result.decision == "PASS", result.violations
    assert set(result.touched_paths) == {"train.py", "requirements.txt"}


# --- normalization is the single source of truth --------------------------


@pytest.mark.parametrize(
    "src_header,tgt_header",
    [("src/x.py", "src/x.py"), ("a/src/x.py", "b/src/x.py"), ("./src/x.py", "./src/x.py"), ("a/./src/x.py", "src/x.py")],
)
def test_header_variants_normalize_to_one_canonical_form(src_header, tgt_header):
    diff = f"--- {src_header}\n+++ {tgt_header}\n@@ -1 +1 @@\n-x = 1\n+x = 2\n"
    prepared = prepare_patch(diff)
    assert prepared.violations == ()
    assert prepared.paths == ("src/x.py",)
    assert prepared.canonical_diff.startswith("--- a/src/x.py\n+++ b/src/x.py\n@@ -1")
    assert prepared.canonical_diff.endswith("-x = 1\n+x = 2\n")


# --- end to end: the orchestrator loads every touched file and applies the
# --- canonical diff (real `git apply`) --------------------------------------


class _Chat:
    def __init__(self, responses):
        self._responses = list(responses)

    def chat_completion(self, **kwargs):
        return self._responses.pop(0)


class _Sandbox:
    def __init__(self, results):
        self._results = list(results)
        self.calls = 0

    def __call__(self, **kwargs):
        self.calls += 1
        return self._results.pop(0)


def _res(code, stderr=""):
    return SandboxRunResult(steps=(StepResult("run", code, "", stderr, 1.0, 0.001),))


def _run(tmp_path, files, entry, repair_diffs, sandbox_results):
    for rel, content in files.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(content, encoding="utf-8")
    intake = RepoIntake(
        local_path=tmp_path,
        commit_sha="a" * 40,
        dependency_files={"requirements.txt": files.get("requirements.txt", "numpy\n")},
        declared_dependencies=frozenset({"numpy"}),
        notebook_paths=(),
        entrypoint_candidates=(entry,),
        python_version_hint=None,
    )
    sandbox = _Sandbox(sandbox_results)
    deps = PipelineDeps(
        recon_client=_Chat([json.dumps({"entrypoint": entry, "confidence": 0.9})]),
        recon_model="r",
        repair_client=_Chat([json.dumps({"diff": d, "explanation": "fix"}) for d in repair_diffs]),
        repair_model="p",
        adjudicator_client=None,
        adjudicator_model=None,
        sandbox_api_key="k",
        sandbox_wall_clock_seconds=60,
        sandbox_runner=sandbox,
        max_attempts=len(repair_diffs),
    )
    result = run_pipeline(
        repo_url="https://example.com/r",
        commit_sha="a" * 40,
        workdir=tmp_path,
        intake_result=intake,
        deps=deps,
        cost_guard=CostGuard(daily_cost_ceiling_usd=100),
        run_id="paths",
    )
    return result, sandbox


def test_orchestrator_rejects_eval_deletion_in_a_non_target_file(tmp_path):
    """The live hole, end to end: the repairer is pointed at train.py but its
    diff deletes the eval call in src/other.py."""
    files = {"train.py": "from src.other import main\nmain()\n", "src/other.py": OTHER_PY}
    result, sandbox = _run(
        tmp_path, files, "train.py", [EVAL_DELETION_IN_OTHER], [_res(1, "ZeroDivisionError: division by zero")]
    )
    assert result.attempts[0].gate_decision == "REJECT"
    assert GateRule.DELETED_EVAL_CALL in {v["rule"] for v in result.attempts[0].gate_violations}
    assert (tmp_path / "src/other.py").read_text(encoding="utf-8") == OTHER_PY
    assert sandbox.calls == 1


def test_orchestrator_applies_the_canonical_diff_for_prefixless_headers(tmp_path):
    """gpt-2 live attempt 1 used `--- src/x.py` headers with no a/ b/ prefix;
    `git apply -p1` stripped `src/` and failed. The canonical diff applies."""
    src = "import os\n\n\ndef main():\n    print(1 / 0)\n\n\nmain()\n"
    fixed = "--- src/gen.py\n+++ src/gen.py\n@@ -4,5 +4,5 @@\n def main():\n-    print(1 / 0)\n+    print(1 / 1)\n \n \n main()\n"
    result, sandbox = _run(
        tmp_path, {"src/gen.py": src}, "src/gen.py", [fixed], [_res(1, "ZeroDivisionError: division by zero"), _res(0)]
    )
    assert result.verdict == "RUNS_AFTER_REPAIR", result.full_log
    assert "print(1 / 1)" in (tmp_path / "src/gen.py").read_text(encoding="utf-8")
    assert result.attempts[0].diff_text.startswith("--- a/src/gen.py\n+++ b/src/gen.py\n")


def test_orchestrator_two_file_repair_is_applied(tmp_path):
    result, _ = _run(
        tmp_path,
        {"train.py": TRAIN_PY, "requirements.txt": REQS},
        "train.py",
        [TWO_FILE_DIFF],
        [_res(1, "ZeroDivisionError: division by zero"), _res(0)],
    )
    assert result.verdict == "RUNS_AFTER_REPAIR", result.full_log
    assert (tmp_path / "requirements.txt").read_text(encoding="utf-8") == "numpy==1.26.4\n"
    assert "np.zeros(3)" in (tmp_path / "train.py").read_text(encoding="utf-8")


def test_symlinked_path_is_rejected_platform_independent(tmp_path, monkeypatch):
    """Same rule as test_symlinked_path_is_rejected, runnable on Windows
    (where creating a real symlink needs admin): the filesystem is asked,
    via Path.is_symlink, whether a path component is a link."""
    (tmp_path / "link").mkdir()
    (tmp_path / "link" / "secret.py").write_text("x = 1\n", encoding="utf-8")
    real_is_symlink = Path.is_symlink
    monkeypatch.setattr(Path, "is_symlink", lambda self: self.name == "link" or real_is_symlink(self))
    diff = "--- a/link/secret.py\n+++ b/link/secret.py\n@@ -1 +1 @@\n-x = 1\n+x = 2\n"
    result = check_patch(diff, {"link/secret.py": "x = 1\n"}, repo_root=tmp_path)
    assert result.decision == "REJECT"
    assert GateRule.UNSAFE_PATH in _rules(result)
    # Negative control: same diff, no symlink -> PASS.
    monkeypatch.setattr(Path, "is_symlink", real_is_symlink)
    assert check_patch(diff, {"link/secret.py": "x = 1\n"}, repo_root=tmp_path).decision == "PASS"
