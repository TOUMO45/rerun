"""harness-v1.6, item C (rule G.1): every new or widened classifier rule replays a RECORDED DEV or gate failure. The stderr tail of the attempt that
recorded the failure is classified exactly as the live classifier would classify it (same function, the stored exit code), and must now carry the
blocker class the pre-registration names. TEST records are never opened (the firewall refuses them by file name)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from app.services import blocker, classifier

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "reports" / "corpus-v2.1" / "v1.5" / "devtest"))
import firewall  # noqa: E402

# (record, the class the v1.5 record ended on, the class v1.6 names, fixable_by)
CASES = [
    ("harness-v1.5.1/dev/09_omarfoq__fedem.json", "RUNTIME_ERROR_OTHER", "DATA_MISSING", "human"),            # AssertionError: Download cifar10 dataset!!
    ("harness-v1.5.1/dev/12_Mehran-k__SimplE.json", "RUNTIME_ERROR_OTHER", "API_REMOVED", "deterministic"),  # module 'tensorflow' has no attribute 'get_variable'
    ("harness-v1.5.1/dev/14_IST-DASLab__M-FAC.json", "RUNTIME_ERROR_OTHER", "GPU_REQUIRED", "human"),        # Cannot access accelerator device when none is available
    ("harness-v1.5.1/dev/16_bckim92__sequential-knowledge-transformer.json", "RUNTIME_ERROR_OTHER", "APT_MIRROR_GONE", "platform"),  # security.debian.org 404
    ("harness-v1.4.3/gate/08_edenton__svg.json", "RUNTIME_ERROR_OTHER", "API_REMOVED", "deterministic"),     # cannot import name 'compare_psnr' from 'skimage.measure'
    ("harness-v1.4.3/gate/07_albertometelli__pfqi.json", "RUNTIME_ERROR_OTHER", "DEP_BUILD_FAILED", "deterministic"),  # error while generating package metadata
]


def _recorded_failure(rel: str) -> tuple[dict, dict]:
    path = ROOT / "runs" / "corpus_v2_batch" / rel
    if not path.is_file():
        pytest.skip(f"{rel} is not in this checkout")
    res = json.loads(firewall.read_record_text(path))["result"]
    last = res["error_chain"][-1]
    attempts = [a for a in res["attempts"] if last["error"][:60] in (a.get("stderr_tail") or "") + (a.get("stdout_tail") or "")]
    assert attempts, "the recorded last error must appear in a stored attempt tail"
    return last, attempts[-1]


@pytest.mark.parametrize("rel, recorded_class, v16_class, fixable_by", CASES)
def test_a_recorded_dev_or_gate_failure_is_named_by_the_v16_rules(rel, recorded_class, v16_class, fixable_by):
    last, attempt = _recorded_failure(rel)
    assert last["class"] == recorded_class, "the v1.5 record stands as written; only v1.6's reading of the same text changes"
    exit_code = attempt.get("exit_code") if attempt.get("exit_code") not in (None, 0) else 1
    got = classifier.classify(exit_code, attempt.get("stderr_tail") or "", attempt.get("stdout_tail") or "")
    assert got.code == v16_class, (got.code, got.evidence[:200])
    report = blocker.report({"verdict": "BLOCKED", "error_chain": [{**last, "class": got.code, "error": got.evidence}], "attempts": []})
    assert report["class"] == v16_class and report["fixable_by"] == fixable_by and report["what_a_human_must_supply"]


def test_a_recorded_dev_failure_that_v15_already_named_keeps_its_class():
    """Negative control: a recorded failure that is a plain code error (DEV #4, `NameError: name 'restore' is not defined`) stays RUNTIME_ERROR_OTHER:
    the new rules name the recorded blockers above and nothing else."""
    last, attempt = _recorded_failure("harness-v1.5.1/dev/04_damo-cv__img-comp-reference.json")
    got = classifier.classify(1, attempt.get("stderr_tail") or "", attempt.get("stdout_tail") or "")
    assert last["class"] == got.code == "RUNTIME_ERROR_OTHER" and "NameError" in got.evidence
