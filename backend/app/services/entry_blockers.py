"""harness-v1.7.2: a FAILED run whose error says the entry point could not do its work for a reason no code change can supply.

Found by the live scan of 2026-10-05 (reports/live_scan/SCAN_2026-10-05.md), read from the repositories at their scanned commits:
  - TomAnthony/pdf-to-powerpoint `convert.py` starts with `pdf_file = sys.argv[1]`: run with no argument (the UI passes none) it raises
    `IndexError: list index out of range` on that line. The program needs an input (a PDF); a model "repair" could only invent one.
  - sdushantha/insta-dl `insta-dl.py` builds a tkinter window at module level: in a headless sandbox tkinter raises
    `_tkinter.TclError: no display name and no $DISPLAY environment variable`. The platform has no display; no code change gives it one.
And, from the v1.7.2 re-scan of insta-dl: once a dependency step installed tkinter and a model patch took the window out, the script asked
    `input("Enter Instagram username: ")` and failed `EOFError: EOF when reading a line`: it needs a person at a keyboard.
All three end INDETERMINATE with the evidence line quoted, before any classification, repair or model call (the same stop as exit_zero_check's
usage case).

harness-v1.8 (T9) adds two more causes of the same kind, found in the TEST / TEST-B records (now DEV-CONTAMINATED):
  - DeformableFriends/NeuralTracking: the documented command is `sh start_nnrt.sh`, whose line 27 runs `docker`: `start_nnrt.sh: 27: docker: not found`. The
    run ended BLOCKED RUNTIME_ERROR_OTHER ("fixable by model") after nine repair attempts, one of which installed `docker.io` and met
    `Cannot connect to the Docker daemon`. The sandbox has no container runtime; no code change or package gives it one.
  - twitter-research/cwn: the documented command is `sh graph-tool_install.sh`, whose line 3 runs `conda`: `graph-tool_install.sh: 3: conda: not found`
    (graph_tool is conda-only). Ten repair attempts followed.
Both are read from the END of the failing output (the last lines the run printed), so a `docker` or `conda` mention earlier in a log that went on to fail for
another reason does not stop a run. An argparse rejection of the documented command (rocgan: `unrecognized arguments: --config`) is diagnosed (diagnosis.py) but
is NOT a stop: a patch that adds the missing option is a legitimate repair. Deliberately narrow: an IndexError counts only when the failing line itself reads sys.argv; argparse's own "the following
arguments are required" message counts only with argparse's exit status 2; a display error only with one of the known messages.
"""

from __future__ import annotations

import re

from app.services.exit_zero_check import ENTRYPOINT_NEEDS_ARGS_REASON_CODE

DISPLAY_REQUIRED_REASON_CODE = "DISPLAY_REQUIRED"
NEEDS_INTERACTIVE_INPUT_REASON_CODE = "NEEDS_INTERACTIVE_INPUT"
DOCKER_REQUIRED_REASON_CODE = "DOCKER_REQUIRED"
CONDA_REQUIRED_REASON_CODE = "CONDA_REQUIRED"
_TAIL_LINES = 25  # the stops below read only the last lines of the output: what the run ENDED on
_END_LINES = 3  # docker / conda: the line must be among the last three non-empty lines
_PYTHON_FAILURE_AFTER = re.compile(r"Traceback \(most recent call last\)|^\s*[A-Za-z_][\w.]*(?:Error|Exception)\b", re.M)  # ... and no Python failure may follow it

# the last frame of a traceback: `  File "...", line N, in <module>` then the source line, then the exception line
_LAST_FRAME = re.compile(r'File "[^"]+", line \d+, in [^\n]+\n\s+(?P<source>[^\n]+)\n(?:[^\n]*\n)*?(?P<exc>(?:IndexError|EOFError): [^\n]*)\s*$')
_ARGPARSE_REQUIRED = re.compile(r"^(?P<line>(?:usage: [^\n]*\n(?:[^\n]*\n)*?)?[^\n]*error: the following arguments are required: [^\n]*)\s*$", re.M)
# harness-v1.8 (independent review, finding 1): these three were `[^\n]*(?:literal)[^\n]*`, which is quadratic on one long line with no newline (20,000 characters: 2 to 5 s each;
# a tqdm-style progress stream is one such line; the sandbox returns up to 4 MiB). They now search the LITERAL (linear) and widen to its line with rfind / find, and the text
# searched is capped at its last MAX_SCAN_CHARS: what the run ended on is at the end.
MAX_SCAN_CHARS = 262_144
_DOCKER = re.compile(r"docker: (?:command )?not found|Cannot connect to the Docker daemon|permission denied while trying to connect to the Docker daemon")
_CONDA = re.compile(r"(?:^|[\s:])conda: (?:command )?not found", re.M)
_NO_DISPLAY = re.compile(r"no display name and no \$DISPLAY environment variable|cannot connect to X server|couldn't connect to display|could not connect to display")


def _line_of(text: str, match: "re.Match") -> str:
    start = text.rfind("\n", 0, match.start()) + 1
    end = text.find("\n", match.end())
    return text[start: end if end != -1 else len(text)].strip()[:300]


def stop_of(exit_code: int | None, stdout: str, stderr: str) -> dict | None:
    """{"code", "evidence"} when a failed run's own output shows a missing argument or a missing display, else None. Never on a run that exited 0."""
    if exit_code in (0, None):
        return None
    text = (stderr or "").rstrip()[-MAX_SCAN_CHARS:] + "\n"
    frame = _LAST_FRAME.search(text)
    if frame and frame.group("exc").startswith("EOFError") and re.search(r"\b(?:raw_)?input\(", frame.group("source")):
        return {"code": NEEDS_INTERACTIVE_INPUT_REASON_CODE, "evidence": f"{frame.group('source').strip()} -> {frame.group('exc').strip()}"}
    if frame and frame.group("exc").startswith("IndexError") and "sys.argv" in frame.group("source"):
        return {"code": ENTRYPOINT_NEEDS_ARGS_REASON_CODE, "evidence": f"{frame.group('source').strip()} -> {frame.group('exc').strip()}"}
    if exit_code == 2:
        required = _ARGPARSE_REQUIRED.search(text) or _ARGPARSE_REQUIRED.search((stdout or "").rstrip() + "\n")
        if required:
            return {"code": ENTRYPOINT_NEEDS_ARGS_REASON_CODE, "evidence": required.group("line").strip().splitlines()[-1][:300]}
    display = _NO_DISPLAY.search(text)
    if display:
        return {"code": DISPLAY_REQUIRED_REASON_CODE, "evidence": _line_of(text, display)}
    # harness-v1.8 (review finding 5): docker / conda count only when the line is among the LAST THREE non-empty lines of the output: a run that printed
    # `docker: not found` and then went on to fail on a repairable traceback is not a run docker ended.
    ended = [ln[:2000] for ln in f"{text}\n{(stdout or '').rstrip()}".splitlines() if ln.strip()][-_TAIL_LINES:]
    tail = "\n".join(ended[-_END_LINES:])
    for rx, code in ((_DOCKER, DOCKER_REQUIRED_REASON_CODE), (_CONDA, CONDA_REQUIRED_REASON_CODE)):
        found = rx.search(tail)
        if found and not _PYTHON_FAILURE_AFTER.search(tail[found.end():]):
            return {"code": code, "evidence": _line_of(tail, found)}
    return None


def stop_reason(stop: dict) -> str:
    if stop["code"] == NEEDS_INTERACTIVE_INPUT_REASON_CODE:
        return (f"{NEEDS_INTERACTIVE_INPUT_REASON_CODE}: the program waits for a person to type an answer (`{stop['evidence']}`) and a sandbox run "
                "has no keyboard; not a verdict on the repository, and not repaired, since a code change could only invent the answer")
    if stop["code"] == DISPLAY_REQUIRED_REASON_CODE:
        return (f"{DISPLAY_REQUIRED_REASON_CODE}: the program opens a graphical window and the sandbox has no display (`{stop['evidence']}`); "
                "not a verdict on the repository, and no code change can supply a display")
    if stop["code"] == DOCKER_REQUIRED_REASON_CODE:
        return (f"{DOCKER_REQUIRED_REASON_CODE}: the command runs docker and the sandbox has no container runtime (`{stop['evidence']}`); "
                "not a verdict on the repository, and no code change or package can supply one")
    if stop["code"] == CONDA_REQUIRED_REASON_CODE:
        return (f"{CONDA_REQUIRED_REASON_CODE}: the command calls conda and the sandbox has none (`{stop['evidence']}`); the environment is one the authors "
                "build with conda; not a verdict on the repository, and not repaired, since pip is not a substitute for a conda-only package")
    return (f"{ENTRYPOINT_NEEDS_ARGS_REASON_CODE}: the command failed because it did not get the arguments it reads (`{stop['evidence']}`); "
            "a human must supply them (for example an input file); not repaired, since a code change could only invent them")
