"""harness-v1.8: the test gaps the independent review of the Phase 2 change named (each one a way a green suite could have hidden a defect).

  1. Docker / conda are stops only at the END of the output (`entry_blockers.stop_of`), not anywhere in a long log: the boundary, tested at both sides.
  2. No new regex is quadratic: each new text reader is timed on one very long line with no newline (a progress stream is one; the sandbox returns up to 4 MiB). On the first
     version of `entry_blockers` (`[^\\n]*(?:literal)[^\\n]*`) a 20,000-character line took 2 to 5 seconds, so 300,000 characters would have run for minutes.
  3. A held-out check for the diagnosis rules: the 14-record key is what the rules were written from; every OTHER committed record is read by the rules too, and the six that
     get an evidence-driven finding were each read by hand (below), while the other ~120 blocked records stay on their class default. A rule that starts firing on a record
     it should not, or stops firing on one it should, changes this list.
  4. T11 against a real shell: `false | sh` exits 0 without pipefail and 1 under the wrapper the harness hands the sandbox.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from app.services import classifier, command_shell, diagnosis, entry_blockers, prerelease_pin, system_packages, time_machine
from test_v18_diagnosis import KEY, ROOT, _attempt, _chain, _record

LONG = 300_000


def _fast(fn, *args, limit: float = 3.0):
    start = time.perf_counter()
    out = fn(*args)
    elapsed = time.perf_counter() - start
    assert elapsed < limit, f"{getattr(fn, '__name__', fn)} took {elapsed:.1f}s on {LONG:,} characters"
    return out


# --------------------------------------------------------------------------------------------------------------------- 1. the end-of-output rule

DOCKER = "start.sh: 27: docker: not found"


def test_docker_is_a_stop_when_it_is_among_the_last_three_lines():
    assert entry_blockers.stop_of(127, "", f"preparing\nrunning\n{DOCKER}\n")["code"] == "DOCKER_REQUIRED"
    assert entry_blockers.stop_of(127, "", f"{DOCKER}\nnext line\nlast line\n")["code"] == "DOCKER_REQUIRED"  # third from the end
    assert entry_blockers.stop_of(127, f"{DOCKER}\n", "")["code"] == "DOCKER_REQUIRED"  # the program wrote it to stdout


def test_docker_four_lines_from_the_end_is_not_a_stop():
    assert entry_blockers.stop_of(1, "", f"{DOCKER}\nl2\nl3\nl4\n") is None


def test_a_python_failure_after_the_docker_line_means_docker_did_not_end_the_run():
    assert entry_blockers.stop_of(1, "", f"{DOCKER}\nTraceback (most recent call last):\n  File \"a.py\", line 1\nValueError: x\n") is None
    assert entry_blockers.stop_of(1, "", f"{DOCKER}\nValueError: bad value\n") is None


def test_conda_follows_the_same_rule_and_a_longer_name_is_not_conda():
    assert entry_blockers.stop_of(127, "", "graph-tool_install.sh: 3: conda: not found\n")["code"] == "CONDA_REQUIRED"
    assert entry_blockers.stop_of(127, "", "install.sh: 3: miniconda: not found\n") is None
    assert entry_blockers.stop_of(1, "", "conda: not found\na\nb\nc\n") is None


def test_a_successful_run_is_never_stopped():
    assert entry_blockers.stop_of(0, "", f"{DOCKER}\n") is None and entry_blockers.stop_of(None, "", f"{DOCKER}\n") is None


# --------------------------------------------------------------------------------------------------------------------- 2. pathological input

@pytest.fixture(scope="module")
def one_long_line() -> str:
    return "docker conda not found cannot connect to Resource " * (LONG // 50)  # near-misses of several rules, one line, no newline


def test_the_entry_blockers_read_one_long_line_in_linear_time(one_long_line):
    assert _fast(entry_blockers.stop_of, 1, "", one_long_line) is None
    display = "x" * LONG + " cannot connect to X server :0"
    out = _fast(entry_blockers.stop_of, 1, "", display)
    assert out["code"] == "DISPLAY_REQUIRED" and len(out["evidence"]) <= 300


def test_the_system_package_and_lock_and_pin_readers_read_one_long_line_in_linear_time(one_long_line):
    _fast(system_packages.need_in, one_long_line)
    _fast(system_packages.need_in, one_long_line, True)
    _fast(system_packages.renamed_apt_package, one_long_line)
    _fast(system_packages.vcs_git_protocol_lines, one_long_line)
    _fast(system_packages.rewrite_git_protocol, one_long_line)
    _fast(time_machine.lock_failure_cause, one_long_line)
    _fast(prerelease_pin.relax_for, one_long_line, ("torch==1.5.0rc1",))
    _fast(command_shell.pipes_into_interpreter, "gen | " + "a " * (LONG // 2))
    cap = _fast(system_packages.need_in, "x" * LONG + "\nfatal error: ft2build.h: No such file or directory")
    assert cap is not None and len(cap.evidence) <= 500  # a megabyte line is not an evidence line


def test_the_classifier_and_the_diagnosis_read_one_long_line_in_linear_time(one_long_line):
    _fast(classifier.classify, 1, one_long_line, "")
    record = {"verdict": "BLOCKED", "error_chain": _chain(one_long_line[:20_000]), "attempts": [_attempt(stderr=one_long_line, env=[])],
              "baseline": {"evidence": one_long_line}, "full_log": one_long_line}
    _fast(diagnosis.diagnose, record, limit=10.0)


# --------------------------------------------------------------------------------------------------------------------- 3. the held-out records

# The six committed records OUTSIDE the key that the rules diagnose (all harness versions up to v1.7.2). Each was read by hand against its own output on 2026-10-07:
HELD_OUT = {
    "corpus_v2_batch/harness-v1.3.2/control/02_DeformableFriends__NeuralTracking.json": "DOCKER_REQUIRED",  # `start_nnrt.sh: 27: docker: not found`: an earlier run of a key entry
    "corpus_v2_batch/harness-v1.3.2/treatment/02_DeformableFriends__NeuralTracking.json": "DOCKER_REQUIRED",  # the same repository, repaired nine times, ended on the daemon error
    "corpus_v2_batch/harness-v1.4.1/gate/07_albertometelli__pfqi.json": "SYSTEM_PACKAGE_MISSING",  # `pkg-config: not found`: the D-24 case
    "corpus_v2_batch/harness-v1.7.1/dev/16_bckim92__sequential-knowledge-transformer.json": "MODULE_NOT_ON_PYPI",  # `language_evaluation` is a GitHub-only package
    "live_scan/oos_v1.7.2/2026-10-05_n0kovo__fb_friend_list_scraper_certificate.json": "ERA_PAIR_MISMATCH",  # an earlier scan of a key entry
    "live_scan/oos_v1.7.2/2026-10-05_njanakiev__openstreetmap-heatmap_certificate.json": "EMBEDDED_RUNTIME_REQUIRED",  # `bpy` is Blender's embedded Python
}


def _scan_committed_records() -> dict[str, str]:
    key = {e["record"] for e in KEY}
    found: dict[str, str] = {}
    for p in sorted((ROOT / "runs").glob("**/*.json")):
        rel = p.relative_to(ROOT).as_posix()
        if "dev_v18" in rel or "harness-v1.8" in rel or rel.startswith("runs/v1.9/") or rel in key or p.stat().st_size > 30_000_000:
            continue  # the v1.8 DEV re-runs and anything later are new evidence, not held-out evidence
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except ValueError:
            continue
        if not isinstance(d, dict) or not (("result" in d and isinstance(d["result"], dict) and "error_chain" in d["result"]) or ("diffs" in d and "error_chain" in d)):
            continue
        rec = _record(rel)
        if rec["verdict"] in ("RUNS_CLEAN", "RUNS_AFTER_REPAIR"):
            continue
        finding = diagnosis.diagnose(rec)
        if finding is not None:
            found[rel.removeprefix("runs/")] = finding.cause
    return found


def test_the_rules_fire_on_exactly_the_held_out_records_that_were_read_by_hand():
    assert _scan_committed_records() == HELD_OUT


@pytest.mark.parametrize("error", [
    "ZeroDivisionError: division by zero",
    "ModuleNotFoundError: No module named 'numpy'",
    "RuntimeError: CUDA out of memory. Tried to allocate 2.00 GiB",
    "FileNotFoundError: [Errno 2] No such file or directory: 'data/train.csv'",
    "ValueError: docker image name must not be empty",
    "KeyError: 'conda'",
])
def test_an_ordinary_error_with_no_evidence_beyond_itself_gets_no_finding(error):
    assert diagnosis.diagnose({"verdict": "BLOCKED", "error_chain": _chain(error), "attempts": []}) is None


# --------------------------------------------------------------------------------------------------------------------- 4. T11 against a real shell

def _bash() -> str | None:
    exe = shutil.which("bash")
    if exe is None:
        return None
    try:
        probe = subprocess.run([exe, "-c", "echo $BASH_VERSION"], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    return exe if probe.returncode == 0 and probe.stdout.strip() else None


@pytest.mark.skipif(_bash() is None, reason="no working bash on this machine")
def test_a_failing_producer_piped_into_an_interpreter_fails_under_the_wrapper_and_not_without_it():
    bash = _bash()
    documented = "false | sh"  # the shape of `python generate_script.py | bash` when the script dies before writing anything
    assert subprocess.run([bash, "-c", documented], capture_output=True, timeout=30).returncode == 0  # the status the harness-v1.7.2 sandbox was handed: a clean run
    wrapped = command_shell.with_pipefail(documented)
    assert wrapped != documented
    assert subprocess.run([bash, "-c", wrapped], capture_output=True, timeout=30).returncode == 1  # now the producer's failure
    ok = command_shell.with_pipefail("true | sh")
    assert subprocess.run([bash, "-c", ok], capture_output=True, timeout=30).returncode == 0  # a pipeline whose stages all succeed is unchanged
    benign = "yes | head -1 > /dev/null"
    assert command_shell.with_pipefail(benign) == benign  # SIGPIPE from `head` is not turned into a failure
