"""harness-v1.7, R6 (METHODOLOGY "harness-v1.7 — PRE-REGISTRATION"): D-44, a model patch that passes the tamper gate and changes what the code computes.

Recorded: DEV entry 14, round 3 (runs/corpus_v2_batch/harness-v1.5.2/dev/14_IST-DASLab__M-FAC.json): the chosen candidate replaced `torch.lu(x, pivot=False)` by the
pivoting `torch.linalg.lu_factor(x)` and the entry ended RUNS_AFTER_REPAIR. Reporting only: the verdict code and the counts are unchanged; the ladder carries
`semantic_change` and the certificate's label reads "RUNS_AFTER_REPAIR (semantic change)"."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from app.services import outcome_levels, tamper_gate
from app.services.orchestrator import AttemptRecord

ROOT = Path(__file__).resolve().parents[2]
R3 = ROOT / "runs" / "corpus_v2_batch" / "harness-v1.5.2" / "dev" / "14_IST-DASLab__M-FAC.json"
sys.path.insert(0, str(ROOT / "reports" / "corpus-v2.1" / "v1.5" / "devtest"))
import firewall  # noqa: E402


def _diff(old: str, new: str, path: str = "optim.py") -> str:
    return f"--- a/{path}\n+++ b/{path}\n@@ -1,1 +1,1 @@\n-{old}\n+{new}\n"


def test_the_recorded_round3_patch_is_flagged_and_the_verdict_code_is_unchanged():
    result = json.loads(R3.read_text(encoding="utf-8"))["result"]
    chosen = next(a for a in result["attempts"] if a.get("origin") == "model" and a.get("chosen") is True)
    assert "torch.linalg.lu_factor" in chosen["diff_text"] and "pivot=False" in chosen["diff_text"]
    assert tamper_gate.semantic_change_calls(chosen["diff_text"]) == ("torch.lu", "linalg")
    levels = outcome_levels.compute(result)
    assert levels["semantic_change"] == ["torch.lu", "linalg"] and levels["entrypoint_runs"] is True
    assert result["verdict"] == "RUNS_AFTER_REPAIR" and outcome_levels.verdict_label(result) == "RUNS_AFTER_REPAIR (semantic change)"


def test_no_other_dev_or_gate_runs_record_is_flagged():
    flagged = []
    for path in firewall.analysis_records(ROOT / "runs" / "corpus_v2_batch", "harness-v1.*/**/[0-9][0-9]_*.json"):
        result = json.loads(firewall.read_record_text(path))["result"]
        if outcome_levels.semantic_change(result):
            flagged.append(path.relative_to(ROOT / "runs" / "corpus_v2_batch").as_posix())
    assert flagged == ["harness-v1.5.2/dev/14_IST-DASLab__M-FAC.json"]


def test_unchosen_candidates_rejected_patches_and_non_runs_verdicts_are_not_flagged():
    patch = _diff("x = torch.lu(a, pivot=False)[0]", "x = torch.linalg.lu_factor(a)[0]")
    base = {"origin": "model", "gate_decision": "PASS", "diff_text": patch, "exit_code": 0}
    assert outcome_levels.semantic_change({"verdict": "RUNS_AFTER_REPAIR", "attempts": [base]}) == ("torch.lu", "linalg")
    assert outcome_levels.semantic_change({"verdict": "RUNS_AFTER_REPAIR", "attempts": [{**base, "candidate": 2, "chosen": False}]}) == ()
    assert outcome_levels.semantic_change({"verdict": "RUNS_AFTER_REPAIR", "attempts": [{**base, "gate_decision": "REJECT"}]}) == ()
    assert outcome_levels.semantic_change({"verdict": "BLOCKED", "attempts": [base]}) == ()
    assert "semantic_change" not in outcome_levels.compute({"verdict": "RUNS_AFTER_REPAIR", "attempts": [{**base, "origin": "time_machine"}]})


@pytest.mark.parametrize("old,new,name", [
    ("y = np.linalg.inv(a)", "y = np.linalg.pinv(a)", "linalg"),
    ("torch.manual_seed(0)", "torch.manual_seed(1)", "random seed"),
    ("x = x.double()", "x = x", "dtype cast"),
    ("loss = F.cross_entropy(out, y)", "loss = F.nll_loss(out, y)", "loss"),
    ("u, s, v = torch.svd(a)", "u, s, v = torch.linalg.svd(a)", "svd"),
])
def test_each_listed_kind_of_call_is_seen_on_a_changed_line(old, new, name):
    assert name in tamper_gate.semantic_change_calls(_diff(old, new))


def test_comments_unchanged_context_and_non_python_files_are_not_flagged():
    assert tamper_gate.semantic_change_calls(_diff("import foo", "import bar  # loss(x) and torch.lu")) == ()
    context = "--- a/m.py\n+++ b/m.py\n@@ -1,2 +1,2 @@\n x = torch.lu(a)\n-import foo\n+import bar\n"
    assert tamper_gate.semantic_change_calls(context) == ()
    assert tamper_gate.semantic_change_calls(_diff("torch.manual_seed(0)", "torch.manual_seed(1)", path="README.md")) == ()


def test_the_attempt_record_stores_the_flag_only_for_a_gated_model_patch_that_has_one():
    patch = _diff("x = torch.lu(a, pivot=False)[0]", "x = torch.linalg.lu_factor(a)[0]")
    rec = AttemptRecord(1, patch, "PASS", (), 0, "", "").as_dict()
    assert rec["semantic_change"] == ["torch.lu", "linalg"]
    assert "semantic_change" not in AttemptRecord(1, patch, "REJECT", (), None, "", "").as_dict()
    assert "semantic_change" not in AttemptRecord(1, _diff("a = 1", "a = 2"), "PASS", (), 0, "", "").as_dict()
    gate = tamper_gate.check_patch(patch, {"optim.py": "x = torch.lu(a, pivot=False)[0]\n"})
    assert gate.semantic_change == ("torch.lu", "linalg")
