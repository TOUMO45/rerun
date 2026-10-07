"""harness-v1.8 (T5): a missing C header or tool named by a failed build is fixed by RERUN's own apt step, before any model proposal, on
SYS_LIB_MISSING and on DEP_BUILD_FAILED.

The evidence is two committed records of the 21 held-out entries (now DEV-CONTAMINATED, owner 2026-10-07):
  - TEST-B #8 CSAILVision/gandissect, `runs/corpus_v3_batch/harness-v1.7.2/treatment/08_CSAILVision__gandissect.json`: the chain ends on
    `src/checkdep_freetype2.c:1:10: fatal error: ft2build.h: No such file or directory`, a SYS_LIB_MISSING whose fix (`apt libfreetype6-dev`) was
    proposed on a losing branch and then barred as "already tried and failed".
  - TEST #13 seongjunyun/neo_gnns, `runs/corpus_v2_batch/harness-v1.5-final/test/13_seongjunyun__neo_gnns.json`: the chain ends on
    `subprocess.CalledProcessError: Command '['which', 'g++']' returned non-zero exit status 1.`, classified DEP_BUILD_FAILED because it sits inside
    pip's build wrapper, so the v1.1 compiler rule never fired.
The error lines are read from those records, not retyped. Offline: a scripted sandbox; the real classifier, env gate and orchestrator run.
On the harness-v1.7.2 code the pipeline tests fail (the model is asked, or the step is not taken)."""

from __future__ import annotations

import json
from pathlib import Path

from app.services import classifier
from test_d24_build_essential import NUMPY_MISSING, _fail, _ok, _pipeline

ROOT = Path(__file__).resolve().parents[2]
GANDISSECT = ROOT / "runs" / "corpus_v3_batch" / "harness-v1.7.2" / "treatment" / "08_CSAILVision__gandissect.json"
NEO_GNNS = ROOT / "runs" / "corpus_v2_batch" / "harness-v1.5-final" / "test" / "13_seongjunyun__neo_gnns.json"


def _chain_error(path: Path, cls: str) -> str:
    chain = json.loads(path.read_text(encoding="utf-8"))["result"]["error_chain"]
    return next(link["error"] for link in reversed(chain) if link["class"] == cls)


HEADER_LINE = _chain_error(GANDISSECT, "SYS_LIB_MISSING")
WHICH_LINE = _chain_error(NEO_GNNS, "DEP_BUILD_FAILED")
# The failing runs: a header error as a compiler prints it; and pip's failed-build wrapper around the `which g++` exception.
HEADER_STDERR = f"  building 'matplotlib.ft2font' extension\n{HEADER_LINE}\n    1 | #include <ft2build.h>\n      |          ^~~~~~~~~~~~\ncompilation terminated.\n"
WHICH_STDERR = (
    "  Preparing metadata (setup.py): started\n"
    "  error: subprocess-exited-with-error\n"
    "  \n"
    "  Traceback (most recent call last):\n"
    f"    {WHICH_LINE}\n"
    "  \n"
    "error: metadata-generation-failed\n"
    "× Encountered error while generating package metadata.\n"
)
FFMPEG = "/bin/sh: 1: ffmpeg: not found\n"
UNKNOWN_HEADER = "fatal error: frobnicate/zzz.h: No such file or directory\n"


def test_the_records_are_the_scenario():
    assert "ft2build.h" in HEADER_LINE and classifier.classify(1, HEADER_STDERR, "", declared_deps=()).code == "SYS_LIB_MISSING"
    assert "which" in WHICH_LINE and "g++" in WHICH_LINE
    assert classifier.classify(1, WHICH_STDERR, "", declared_deps=()).code == "DEP_BUILD_FAILED"  # why the v1.1 rule never saw it


def test_baseline_header_error_adds_the_dev_package_without_a_model_call(tmp_path):
    result, repair = _pipeline(tmp_path, [_fail(HEADER_STDERR), _ok()])
    assert repair.calls == [] and result.verdict == "RUNS_AFTER_REPAIR"
    tm = result.attempts[0]
    assert tm.origin == "time_machine" and tm.time_machine["apt_added"] == ["libfreetype6-dev"]
    assert tm.time_machine["apt_reason"] == HEADER_LINE
    assert result.certificate()["build_plan"]["apt_install"] == ["libfreetype6-dev"]


def test_repair_time_header_error_is_a_recorded_deterministic_step_and_uses_no_model_attempt(tmp_path):
    result, repair = _pipeline(tmp_path, [_fail(NUMPY_MISSING), _fail(HEADER_STDERR), _ok()])
    assert repair.calls == [] and result.verdict == "RUNS_AFTER_REPAIR"
    steps = [a for a in result.attempts if a.time_machine_action]
    assert len(steps) == 1
    action = steps[0].time_machine_action
    assert action["rule"] == "missing_header_apt" and action["matched_error"] == HEADER_LINE
    assert action["apt_added"] == ["libfreetype6-dev"] and action["needed"] == {"kind": "header", "item": "ft2build.h"}
    assert steps[0].origin == "time_machine" and steps[0].attempt_number == 0  # did not use up a model attempt
    assert result.certificate()["build_plan"]["apt_install"] == ["libfreetype6-dev"]


def test_a_compiler_missing_inside_pips_build_wrapper_gets_build_essential(tmp_path):
    """TEST #13: DEP_BUILD_FAILED, not SYS_LIB_MISSING. The v1.1 rule is keyed on SYS_LIB_MISSING and never fired."""
    result, repair = _pipeline(tmp_path, [_fail(NUMPY_MISSING), _fail(WHICH_STDERR), _ok()])
    assert repair.calls == [] and result.verdict == "RUNS_AFTER_REPAIR"
    action = next(a.time_machine_action for a in result.attempts if a.time_machine_action)
    assert action["rule"] == "missing_compiler_build_essential" and action["apt_added"] == ["build-essential"]
    assert action["matched_error"] == WHICH_LINE
    assert result.certificate()["build_plan"]["apt_install"] == ["build-essential"]


def test_a_missing_tool_from_the_table_is_deterministic_too(tmp_path):
    cmake = "/bin/sh: 1: cmake: not found\nerror: metadata-generation-failed\n"
    result, repair = _pipeline(tmp_path, [_fail(NUMPY_MISSING), _fail(cmake), _ok()])
    assert repair.calls == [] and result.verdict == "RUNS_AFTER_REPAIR"
    action = next(a.time_machine_action for a in result.attempts if a.time_machine_action)
    assert action["rule"] == "missing_tool_apt" and action["apt_added"] == ["cmake"]


def test_a_tool_the_table_does_not_know_still_goes_to_the_model(tmp_path):
    fix = {"env_delta": [{"op": "apt", "package": "ffmpeg", "justification": "ffmpeg is missing", "evidence": "/bin/sh: 1: ffmpeg: not found"}],
           "cited_sources": [], "reason_no_citation": "no reference offered", "explanation": "system package"}
    result, repair = _pipeline(tmp_path, [_fail(NUMPY_MISSING), _fail(FFMPEG), _ok()], replies=[fix])
    assert len(repair.calls) == 1 and not any(a.time_machine_action for a in result.attempts)


def test_a_header_the_table_does_not_know_still_goes_to_the_model(tmp_path):
    declined = {"cannot_fix": True, "explanation": "no", "cited_sources": [], "reason_no_citation": "none"}
    result, repair = _pipeline(tmp_path, [_fail(NUMPY_MISSING), _fail(UNKNOWN_HEADER)], replies=[declined] * 6, max_attempts=1)
    assert len(repair.calls) >= 1 and not any(a.time_machine_action for a in result.attempts)


def test_the_step_fires_once_and_does_not_loop(tmp_path):
    """The header is still missing after the package went in (a wrong mapping, or a broken mirror): the model is asked, no second step."""
    declined = {"cannot_fix": True, "explanation": "nothing to change", "cited_sources": [], "reason_no_citation": "none offered"}
    result, repair = _pipeline(tmp_path, [_fail(NUMPY_MISSING), _fail(HEADER_STDERR), _fail(HEADER_STDERR)], replies=[declined] * 6, max_attempts=1)
    assert sum(1 for a in result.attempts if a.time_machine_action) == 1 and len(repair.calls) >= 1
    assert result.certificate()["build_plan"]["apt_install"] == ["libfreetype6-dev"] and result.verdict == "BLOCKED"


# --------------------------------------------------------------------------- the lookup tables

def test_header_table_names():
    from app.services import system_packages as sp

    for header, package in (("ft2build.h", "libfreetype6-dev"), ("png.h", "libpng-dev"), ("openssl/ssl.h", "libssl-dev"), ("yaml.h", "libyaml-dev"),
                            ("ffi.h", "libffi-dev"), ("GL/glew.h", "libglew-dev")):
        need = sp.need_in(f"x.c:1:10: fatal error: {header}: No such file or directory")
        assert need is not None and need.packages == (package,) and need.kind == "header"
    assert sp.need_in(UNKNOWN_HEADER) is None


def test_the_last_miss_wins_for_a_whole_build_log():
    from app.services import system_packages as sp

    log = ("fatal error: png.h: No such file or directory\n  (pip fell back to a wheel)\n"
           "fatal error: ft2build.h: No such file or directory\n")
    assert sp.need_in(log).item == "png.h"  # the classifier's own evidence line: the first match
    assert sp.need_in(log, last=True).item == "ft2build.h"  # a whole build log: what the run ended on


def test_debian_renames_and_git_protocol():
    from app.services import system_packages as sp

    assert sp.renamed_apt_package("E: Package 'libgl1-mesa-glx' has no installation candidate") == (
        "libgl1-mesa-glx", "libgl1", "E: Package 'libgl1-mesa-glx' has no installation candidate")
    assert sp.renamed_apt_package("E: Package 'libjasper-dev' has no installation candidate") is None  # removed with no successor: never guessed
    text, n = sp.rewrite_git_protocol("git+git://github.com/alexlee-gk/lpips-tensorflow.git#egg=lpips-tf\ngit://example.org/x.git\n")
    assert n == 1 and text.startswith("git+https://github.com/alexlee-gk/lpips-tensorflow.git") and "git://example.org/x.git" in text
