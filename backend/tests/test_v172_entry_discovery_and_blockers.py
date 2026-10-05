"""harness-v1.7.2, from the live scan of 2026-10-05 (reports/live_scan/SCAN_2026-10-05.md): entrypoint discovery sees module-level scripts, and a
failed run that lacks its arguments or a display ends INDETERMINATE with the evidence line, with no repair and no model call.

Fixture lines are quoted from the scanned repositories at their scanned commits (a few lines each): TomAnthony/pdf-to-powerpoint df9c37b
`convert.py`, ghewgill/pyqver 197c953 `pyqver3.py`, sdushantha/insta-dl a699bf1 `insta-dl.py`. The stderr texts are what those lines raise when
run with no argument or no display (the interpreter's standard messages)."""

from __future__ import annotations

from app.services import entry_blockers, intake
from app.services.sandbox import SandboxRunResult, StepResult
from test_v151_pins_and_removals import _pipeline

CONVERT = "import sys\nimport os\nfrom pptx import Presentation\n\npdf_file = sys.argv[1]\nprint()\nprint(\"Converting file: \" + pdf_file)\n"
PYQVER3 = "import sys\n\ndef get_versions(source):\n    return {}\n\nVerbose = False\ni = 1\nwhile i < len(sys.argv):\n    a = sys.argv[i]\n    i += 1\n"
INSTA = "import tkinter\n\n__version__ = \"v.0.2.7\"\nwindow = tkinter.Tk()\nwindow.title(\"insta-dl \" + __version__)\nwindow.mainloop()\n"
LIBRARY = "import sys\n\ndef main():\n    args = sys.argv[1:]\n    return args\n"  # sys.argv only inside a function: a library, not a script

ARGV_STDERR = ('Traceback (most recent call last):\n  File "convert.py", line 9, in <module>\n    pdf_file = sys.argv[1]\n'
               "IndexError: list index out of range\n")
DISPLAY_STDERR = ('Traceback (most recent call last):\n  File "insta-dl.py", line 25, in <module>\n    window = tkinter.Tk()\n'
                  '  File "/usr/local/lib/python3.10/tkinter/__init__.py", line 2299, in __init__\n'
                  "    self.tk = _tkinter.create(screenName, baseName, className, interactive, wantobjects, useTk, sync, use)\n"
                  "_tkinter.TclError: no display name and no $DISPLAY environment variable\n")
ARGPARSE_STDERR = "usage: tool.py [-h] input\ntool.py: error: the following arguments are required: input\n"


def test_module_level_scripts_are_candidates_and_libraries_are_not(tmp_path):
    for name, text in {"convert.py": CONVERT, "pyqver3.py": PYQVER3, "insta-dl.py": INSTA, "lib.py": LIBRARY,
                       "setup.py": "import sys\nsys.argv.append('x')\n", "__init__.py": "import sys\nX = sys.argv\n",
                       "notes.py": "# sys.argv is read elsewhere\nX = 1\n"}.items():
        (tmp_path / name).write_text(text, encoding="utf-8")
    assert intake.find_entrypoint_candidates(tmp_path) == ("convert.py", "insta-dl.py", "pyqver3.py")


def test_a_python_2_script_that_does_not_parse_under_python_3_is_still_found(tmp_path):
    (tmp_path / "pyqver2.py").write_text("import sys\nprint \"usage\"\ni = 1\nwhile i < len(sys.argv):\n    i += 1\n", encoding="utf-8")
    assert intake.find_entrypoint_candidates(tmp_path) == ("pyqver2.py",)


def test_the_blockers_name_a_missing_argument_or_display_and_nothing_else():
    assert entry_blockers.stop_of(1, "", ARGV_STDERR) == {"code": "ENTRYPOINT_NEEDS_ARGS", "evidence": "pdf_file = sys.argv[1] -> IndexError: list index out of range"}
    assert entry_blockers.stop_of(2, "", ARGPARSE_STDERR)["code"] == "ENTRYPOINT_NEEDS_ARGS"
    assert entry_blockers.stop_of(1, "", DISPLAY_STDERR) == {"code": "DISPLAY_REQUIRED", "evidence": "_tkinter.TclError: no display name and no $DISPLAY environment variable"}
    # negative controls: an IndexError on a line that is not sys.argv, argparse's message with another exit status, a run that exited 0
    other = 'Traceback (most recent call last):\n  File "a.py", line 3, in <module>\n    x = items[5]\nIndexError: list index out of range\n'
    assert entry_blockers.stop_of(1, "", other) is None
    assert entry_blockers.stop_of(1, "", ARGPARSE_STDERR) is None
    assert entry_blockers.stop_of(0, "", ARGV_STDERR) is None and entry_blockers.stop_of(None, "", DISPLAY_STDERR) is None


def _failure(stderr: str, exit_code: int = 1) -> SandboxRunResult:
    return SandboxRunResult(steps=(StepResult("python convert.py", exit_code, "", stderr, 1.0, 0.01),))


def test_replay_pdf_to_powerpoint_ends_needs_args_with_no_repair_and_no_model_call(tmp_path):
    result, repair, plans, left = _pipeline(tmp_path, [_failure(ARGV_STDERR)], files={"train.py": CONVERT})
    assert not left and not repair.calls and len(plans) == 1
    assert result.verdict == "INDETERMINATE" and result.indeterminate_reason.startswith("ENTRYPOINT_NEEDS_ARGS")
    assert "pdf_file = sys.argv[1]" in result.indeterminate_reason and not result.attempts


def test_replay_insta_dl_ends_display_required_with_no_repair(tmp_path):
    result, repair, plans, left = _pipeline(tmp_path, [_failure(DISPLAY_STDERR)], files={"train.py": INSTA})
    assert not left and not repair.calls and len(plans) == 1
    assert result.verdict == "INDETERMINATE" and result.indeterminate_reason.startswith("DISPLAY_REQUIRED")
    assert "no display name" in result.indeterminate_reason


def test_an_ordinary_failure_still_goes_to_the_classifier_and_the_repair_loop(tmp_path):
    other = 'Traceback (most recent call last):\n  File "train.py", line 1, in <module>\n    import numpy\nModuleNotFoundError: No module named \'numpy\'\n'
    result, repair, plans, left = _pipeline(tmp_path, [_failure(other)] * 6, files={"train.py": "import numpy\n"})
    assert not (result.indeterminate_reason or "").startswith(("ENTRYPOINT_NEEDS_ARGS", "DISPLAY_REQUIRED"))
    # the run reached the repair loop: the fake repair model (no scripted reply) was called and stopped the pipeline there
    assert (result.indeterminate_reason or "").startswith("PIPELINE_ERROR:repairer") and "No module named 'numpy'" in (result.last_error or "")


# --- the v1.7.2 re-scan of insta-dl: the blocker appeared only after earlier steps had fixed the environment --------------------------------
EOF_STDERR = ('Traceback (most recent call last):\n  File "insta-dl.py", line 98, in <module>\n    username = input("Enter Instagram username: ")\n'
              "EOFError: EOF when reading a line\n")


def test_interactive_input_is_named_and_an_eoferror_elsewhere_is_not():
    assert entry_blockers.stop_of(1, "", EOF_STDERR) == {"code": "NEEDS_INTERACTIVE_INPUT",
                                                         "evidence": 'username = input("Enter Instagram username: ") -> EOFError: EOF when reading a line'}
    other = 'Traceback (most recent call last):\n  File "a.py", line 4, in <module>\n    data = pickle.load(f)\nEOFError: Ran out of input\n'
    assert entry_blockers.stop_of(1, "", other) is None


def test_a_blocker_that_appears_after_a_deterministic_step_stops_the_loop_with_no_model_call(tmp_path):
    """Baseline: a removed torch API (the F2 rule pins torch and re-executes, no model). The re-execution then reaches the program's own
    input() prompt and fails EOFError: the loop must stop NEEDS_INTERACTIVE_INPUT instead of handing that failure to the repair model."""
    removed = _failure("ImportError: cannot import name 'zero_gradients' from 'torch.autograd.gradcheck' (/x/gradcheck.py)\n")
    result, repair, plans, left = _pipeline(tmp_path, [removed, _failure(EOF_STDERR)], files={"train.py": "import torch\n"},
                                            dependency_files={"requirements.txt": "torch\n"})
    assert not left and not repair.calls and len(plans) == 2
    assert result.verdict == "INDETERMINATE" and result.indeterminate_reason.startswith("NEEDS_INTERACTIVE_INPUT")
    assert [(a.time_machine_action or {}).get("rule") for a in result.attempts] == ["removed_api_torch_zero_gradients"]


def test_the_blocker_agrees_with_an_input_stop_instead_of_describing_the_last_code_error():
    """Found live (runs/live_scan/v1.7.2b/, pdf-to-powerpoint): the verdict said ENTRYPOINT_NEEDS_ARGS, not repaired, while the blocker said
    RUNTIME_ERROR_OTHER, fixable by model. The blocker now follows the stop."""
    from app.services import blocker

    chain = [{"error": "IndexError: list index out of range", "class": "RUNTIME_ERROR_OTHER", "attribution": "REPO", "phase": "repo_run", "cleared_by": None}]
    reason = entry_blockers.stop_reason(entry_blockers.stop_of(1, "", ARGV_STDERR))
    b = blocker.report({"verdict": "INDETERMINATE", "indeterminate_reason": reason, "error_chain": chain})
    assert (b["class"], b["fixable_by"], b["attribution"]) == ("ENTRYPOINT_NEEDS_ARGS", "human", None)
    assert b["evidence"] == "pdf_file = sys.argv[1] -> IndexError: list index out of range"
    display = blocker.report({"verdict": "INDETERMINATE", "indeterminate_reason": entry_blockers.stop_reason(entry_blockers.stop_of(1, "", DISPLAY_STDERR)),
                              "error_chain": chain})
    assert (display["class"], display["fixable_by"]) == ("DISPLAY_REQUIRED", "platform")
    # any other verdict or reason: the chain's last link, exactly as before
    assert blocker.report({"verdict": "BLOCKED", "indeterminate_reason": "", "error_chain": chain})["class"] == "RUNTIME_ERROR_OTHER"


def test_a_candidate_that_causes_its_own_new_error_is_not_adopted(tmp_path):
    """v1.7.2 re-scan of insta-dl (runs/live_scan/v1.7.2b/): a candidate added `python3-tk` (an apt package name) as a pip requirement; its run
    failed because pip has no such package; that self-inflicted error was adopted and the run ended BLOCKED on it, attributed to the repository.
    Now the candidate does not qualify, and the run's last error stays the repository's own."""
    from types import SimpleNamespace

    from app.services.orchestrator import _self_inflicted
    from test_v151_pins_and_removals import _fail

    pip_missing = "ERROR: Could not find a version that satisfies the requirement python3-tk (from versions: none)"
    assert _self_inflicted(SimpleNamespace(evidence=pip_missing), [{"op": "add", "package": "python3-tk"}], frozenset({"requests"})) == "python3-tk"
    assert _self_inflicted(SimpleNamespace(evidence=pip_missing), [{"op": "add", "package": "python3-tk"}], frozenset({"python3_tk"})) is None  # declared
    assert _self_inflicted(SimpleNamespace(evidence=pip_missing), [{"op": "apt", "package": "python3-tk"}], frozenset()) is None  # not a pip change
    assert _self_inflicted(SimpleNamespace(evidence=pip_missing), [{"op": "add", "package": "tk"}], frozenset()) is None  # part of another name

    tk_missing = "Traceback (most recent call last):\n  File \"train.py\", line 1, in <module>\n    import Tkinter as tkinter\nModuleNotFoundError: No module named 'Tkinter'\n"
    fix = {"env_delta": [{"op": "add", "package": "python3-tk", "justification": "provides Tkinter", "evidence": "No module named 'Tkinter'"}],
           "cited_sources": [], "reason_no_citation": "none offered", "explanation": "x"}
    own_error = SandboxRunResult(steps=(StepResult("pip install -r requirements.txt", 1, "", pip_missing + "\n", 1.0, 0.01, phase="repo_install"),))
    result, repair, plans, left = _pipeline(tmp_path, [_fail(tk_missing), own_error], files={"train.py": "import Tkinter as tkinter\n"},
                                            dependency_files={"requirements.txt": "requests\n"}, replies=[fix], max_attempts=1)
    assert len(repair.calls) == 1 and len(plans) == 2
    last = result.error_chain[-1].as_dict() if hasattr(result.error_chain[-1], "as_dict") else result.error_chain[-1]
    assert "No module named 'Tkinter'" in last["error"] and "python3-tk" not in (result.last_error or "")
