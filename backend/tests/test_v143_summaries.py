"""harness-v1.4.3-rc, D-41: the new INDETERMINATE reason code OUTPUT_TRUNCATED is known to the certificate prose and the batch summaries (the v1.4.2 review found the same gap for
RESOURCE_LIMIT and EXIT_OUTSIDE_PYTHON: an entry ended with the new code and the summaries read it as the repository's failure)."""

from __future__ import annotations

import sys
from pathlib import Path

from app.services import adjudicator
from app.services.adjudicator import templated_certificate_prose
from app.services.orchestrator import OUR_FAULT_CODES, is_our_fault, reason_code_of

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
REASON = "OUTPUT_TRUNCATED: the command exited with code 1 and the API returned only the start of its stderr stream (stderr 65535 bytes returned; ...)"


def _view(verdict, reason="", first_repo_error=None):
    return {"verdict": verdict, "klass": "", "reason_code": reason, "first_repo_error": first_repo_error, "attributions": [], "spent": 0.0, "attempts": 0, "tavily": False}


def test_the_certificate_prose_says_the_output_was_cut_and_claims_nothing():
    prose = templated_certificate_prose("INDETERMINATE", "RUNTIME_ERROR_OTHER", 0, REASON)
    assert "returned only the start of its output" in prose and "nothing is claimed about the repository" in prose
    assert "Recon could not establish" not in prose and not adjudicator.makes_reproduction_claim(prose)


def test_a_cut_output_is_not_measured_in_the_batch_summaries_and_not_the_repositorys_column():
    import compare_batches

    control = _view("BLOCKED", "", first_repo_error="NameError")
    assert compare_batches.categorize(control, _view("INDETERMINATE", REASON)) == "NOT_MEASURED"
    assert compare_batches.categorize(control, _view("BLOCKED", "")) == "REPO_STILL_FAILING"  # unchanged
    source = (ROOT / "scripts" / "run_corpus_v1_batch.py").read_text(encoding="utf-8")
    assert '"OUTPUT_TRUNCATED"' in source


def test_the_reason_code_is_stable_and_is_not_the_harness_fault_class():
    """Like EXIT_OUTSIDE_PYTHON: the harness cannot say why, and does not call it the repository's fault or an upload/infra fault either."""
    assert reason_code_of(REASON) == "OUTPUT_TRUNCATED" and "OUTPUT_TRUNCATED" not in OUR_FAULT_CODES and not is_our_fault(reason_code_of(REASON))
