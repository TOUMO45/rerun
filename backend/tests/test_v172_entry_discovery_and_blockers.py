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
