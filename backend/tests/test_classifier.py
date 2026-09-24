"""Tests for the pure, deterministic failure classifier (§5.2).

Every taxonomy code gets:
  - a "positive" test: a realistic stderr snippet that must produce that code.
  - a "negative control" test: a superficially similar snippet that must
    NOT produce that code (either because the signal is genuinely absent, or
    because a supposedly-matching detail is neutralized, e.g. the module is
    actually declared as a dependency). This is what proves the classifier
    isn't just pattern-matching noise into false positives.
"""

from __future__ import annotations

import pytest

from app.services.classifier import Classification, TaxonomyCode, classify


def _code(stderr: str, **kwargs) -> str:
    return classify(exit_code=1, stderr=stderr, **kwargs).code


# --- DEP_UNPINNED_CONFLICT ---------------------------------------------------


def test_dep_unpinned_conflict_positive():
    stderr = (
        "ERROR: Cannot install foo==1.2 and bar==3.4 because these package "
        "versions have conflicting dependencies.\nResolutionImpossible"
    )
    assert _code(stderr) == TaxonomyCode.DEP_UNPINNED_CONFLICT


def test_dep_unpinned_conflict_negative_control():
    # A plain install failure with no resolver-conflict language must not
    # be misclassified as a conflict.
    stderr = "ERROR: Could not find a version that satisfies the requirement foo==9.9.9"
    assert _code(stderr) != TaxonomyCode.DEP_UNPINNED_CONFLICT


# --- DEP_MISSING --------------------------------------------------------------


def test_dep_missing_positive():
    stderr = "Traceback (most recent call last):\nModuleNotFoundError: No module named 'requests'"
    assert _code(stderr, declared_deps=frozenset({"numpy"})) == TaxonomyCode.DEP_MISSING


def test_dep_missing_negative_control_when_declared():
    # The module IS declared (and aliases resolve, e.g. sklearn -> scikit-learn)
    # so this must NOT be reported as an undeclared missing dependency.
    stderr = "ModuleNotFoundError: No module named 'sklearn'"
    assert (
        _code(stderr, declared_deps=frozenset({"scikit-learn"}))
        != TaxonomyCode.DEP_MISSING
    )


# --- DEP_YANKED / DEP_NOT_ON_PYPI (split of DEP_YANKED_GONE) ----------------

# Verbatim from the TTPT live run (2026-09-24): Dassl is GitHub-only.
_NEVER_ON_PYPI = (
    "ERROR: Could not find a version that satisfies the requirement dassl (from versions: none)\n"
    "ERROR: No matching distribution found for dassl\n"
)
_VERSION_GONE = (
    "ERROR: Could not find a version that satisfies the requirement ancient-pkg==0.0.1 "
    "(from versions: 0.1.0, 0.2.0, 1.0.0)\n"
    "ERROR: No matching distribution found for ancient-pkg==0.0.1\n"
)


def test_dep_not_on_pypi_positive():
    assert _code(_NEVER_ON_PYPI) == TaxonomyCode.DEP_NOT_ON_PYPI
    assert _code("requests.exceptions.HTTPError: 404 Client Error: Not Found for url: https://pypi.org/simple/nope/") == (
        TaxonomyCode.DEP_NOT_ON_PYPI
    )


def test_dep_not_on_pypi_negative_control():
    # The package exists, only the requested version is gone.
    assert _code(_VERSION_GONE) != TaxonomyCode.DEP_NOT_ON_PYPI
    # A 404 from a non-PyPI host is a data problem, not a packaging one.
    stderr = "requests.exceptions.HTTPError: 404 Client Error: Not Found for url: https://data.example.com/dataset.zip"
    assert _code(stderr) not in (TaxonomyCode.DEP_NOT_ON_PYPI, TaxonomyCode.DEP_YANKED)


def test_dep_yanked_positive():
    assert _code(_VERSION_GONE) == TaxonomyCode.DEP_YANKED
    assert _code("WARNING: The candidate selected for download or install is a yanked version: 'x' ...") == (
        TaxonomyCode.DEP_YANKED
    )
    # pip sometimes prints only the second line.
    assert _code("ERROR: No matching distribution found for ancient-pkg==0.0.1") == TaxonomyCode.DEP_YANKED


def test_dep_yanked_negative_control():
    assert _code(_NEVER_ON_PYPI) != TaxonomyCode.DEP_YANKED


def test_dependency_evidence_keeps_the_full_package_name():
    """Live TTPT bug: evidence was cut to 'No matching distribution found for'."""
    evidence = classify(exit_code=1, stderr=_NEVER_ON_PYPI).evidence
    assert "dassl" in evidence
    assert evidence == "ERROR: Could not find a version that satisfies the requirement dassl (from versions: none)"
    evidence = classify(exit_code=1, stderr="ERROR: No matching distribution found for ancient-pkg==0.0.1").evidence
    assert evidence.endswith("ancient-pkg==0.0.1")


def test_evidence_is_the_whole_matching_line_for_other_codes_too():
    stderr = "Traceback (most recent call last):\n  File \"x.py\", line 1\nModuleNotFoundError: No module named 'torch'\n"
    assert classify(exit_code=1, stderr=stderr).evidence == "ModuleNotFoundError: No module named 'torch'"


# --- PY_VERSION_INCOMPAT ------------------------------------------------------


def test_py_version_incompat_positive():
    stderr = "ERROR: Package 'foo' requires a different Python: 3.12.1 not in '<3.10,>=3.8'"
    assert _code(stderr) == TaxonomyCode.PY_VERSION_INCOMPAT


def test_py_version_incompat_negative_control():
    stderr = "SyntaxError: invalid syntax\n  print 'hello'\n        ^"
    assert _code(stderr) != TaxonomyCode.PY_VERSION_INCOMPAT


# --- SYS_LIB_MISSING --------------------------------------------------------


def test_sys_lib_missing_positive():
    stderr = "ImportError: libGL.so.1: cannot open shared object file: No such file or directory"
    assert _code(stderr) == TaxonomyCode.SYS_LIB_MISSING


def test_sys_lib_missing_negative_control():
    stderr = "ModuleNotFoundError: No module named 'cv2'"
    assert _code(stderr) != TaxonomyCode.SYS_LIB_MISSING


# --- DATA_MISSING --------------------------------------------------------------


def test_data_missing_positive():
    stderr = "FileNotFoundError: [Errno 2] No such file or directory: 'data/train.csv'"
    assert _code(stderr) == TaxonomyCode.DATA_MISSING


def test_data_missing_negative_control():
    # A missing-module error is not a missing-data error, even though both
    # can superficially look like "something wasn't found".
    stderr = "ModuleNotFoundError: No module named 'pandas'"
    assert _code(stderr, declared_deps=frozenset()) != TaxonomyCode.DATA_MISSING


# --- DATA_CREDENTIALS --------------------------------------------------------


def test_data_credentials_positive():
    stderr = "requests.exceptions.HTTPError: 401 Client Error: Unauthorized for url: https://api.example.com/dataset"
    assert _code(stderr) == TaxonomyCode.DATA_CREDENTIALS


def test_data_credentials_negative_control():
    # A generic FileNotFoundError has no auth signal and must not be
    # upgraded into a credentials problem.
    stderr = "FileNotFoundError: [Errno 2] No such file or directory: 'weights.pt'"
    assert _code(stderr) != TaxonomyCode.DATA_CREDENTIALS


# --- HARDCODED_PATH --------------------------------------------------------


def test_hardcoded_path_positive():
    stderr = "FileNotFoundError: [Errno 2] No such file or directory: '/home/jsmith/data/train.csv'"
    assert _code(stderr) == TaxonomyCode.HARDCODED_PATH


def test_hardcoded_path_negative_control():
    # A relative path failure is an ordinary missing-data case, not evidence
    # of a hardcoded author-machine path.
    stderr = "FileNotFoundError: [Errno 2] No such file or directory: 'data/train.csv'"
    assert _code(stderr) != TaxonomyCode.HARDCODED_PATH


# --- GPU_REQUIRED --------------------------------------------------------------


def test_gpu_required_positive():
    stderr = "AssertionError: Torch not compiled with CUDA enabled"
    assert _code(stderr) == TaxonomyCode.GPU_REQUIRED


def test_gpu_required_negative_control():
    stderr = "AssertionError: expected shape (3, 4) but got (4, 3)"
    assert _code(stderr) != TaxonomyCode.GPU_REQUIRED


# --- NETWORK_BLOCKED --------------------------------------------------------


def test_network_blocked_positive():
    stderr = "socket.gaierror: [Errno -3] Temporary failure in name resolution"
    assert _code(stderr) == TaxonomyCode.NETWORK_BLOCKED


def test_network_blocked_negative_control():
    # A clean HTTP 404 is not a network-level block.
    stderr = "requests.exceptions.HTTPError: 404 Client Error: Not Found for url: https://data.example.com/x.zip"
    assert _code(stderr) != TaxonomyCode.NETWORK_BLOCKED


# --- RUNTIME_ERROR_OTHER (the catch-all) -------------------------------------


def test_runtime_error_other_positive():
    stderr = "ZeroDivisionError: division by zero"
    assert _code(stderr) == TaxonomyCode.RUNTIME_ERROR_OTHER


def test_runtime_error_other_negative_control():
    # Anything that DOES match a specific rule must never fall through to
    # the generic catch-all — that would silently hide real signal.
    stderr = "ModuleNotFoundError: No module named 'requests'"
    assert _code(stderr, declared_deps=frozenset()) != TaxonomyCode.RUNTIME_ERROR_OTHER


# --- ENTRYPOINT_UNCLEAR is asserted to exist as a shared constant, but is
# never produced by classify() itself (it's a recon-time decision, §6.1) ----


def test_entrypoint_unclear_is_not_reachable_from_classify():
    # classify() must never emit ENTRYPOINT_UNCLEAR: that verdict is decided
    # before execution even starts (recon confidence), not from exit
    # code/stderr. This guards against someone accidentally wiring a
    # post-execution regex to it later.
    stderr = "no entrypoint found, candidates were train.py, run_experiment.py"
    assert _code(stderr) != TaxonomyCode.ENTRYPOINT_UNCLEAR


# --- Structural guarantees ----------------------------------------------------


def test_every_taxonomy_code_has_a_declared_family():
    for code in TaxonomyCode.ALL:
        assert code in TaxonomyCode.FAMILY


def test_classify_rejects_zero_exit_code():
    with pytest.raises(ValueError):
        classify(exit_code=0, stderr="")


def test_classification_evidence_is_populated():
    result = classify(exit_code=1, stderr="ZeroDivisionError: division by zero")
    assert isinstance(result, Classification)
    assert result.evidence
    assert result.family == TaxonomyCode.FAMILY[TaxonomyCode.RUNTIME_ERROR_OTHER]
