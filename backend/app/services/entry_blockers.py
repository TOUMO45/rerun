"""harness-v1.7.2: a FAILED run whose error says the entry point could not do its work for a reason no code change can supply.

Found by the live scan of 2026-10-05 (reports/live_scan/SCAN_2026-10-05.md), read from the repositories at their scanned commits:
  - TomAnthony/pdf-to-powerpoint `convert.py` starts with `pdf_file = sys.argv[1]`: run with no argument (the UI passes none) it raises
    `IndexError: list index out of range` on that line. The program needs an input (a PDF); a model "repair" could only invent one.
  - sdushantha/insta-dl `insta-dl.py` builds a tkinter window at module level: in a headless sandbox tkinter raises
    `_tkinter.TclError: no display name and no $DISPLAY environment variable`. The platform has no display; no code change gives it one.
Both end INDETERMINATE with the evidence line quoted, before any classification, repair or model call (the same stop as exit_zero_check's
usage case). Deliberately narrow: an IndexError counts only when the failing line itself reads sys.argv; argparse's own "the following
arguments are required" message counts only with argparse's exit status 2; a display error only with one of the known messages.
"""

from __future__ import annotations

import re

from app.services.exit_zero_check import ENTRYPOINT_NEEDS_ARGS_REASON_CODE

DISPLAY_REQUIRED_REASON_CODE = "DISPLAY_REQUIRED"

# the last frame of a traceback: `  File "...", line N, in <module>` then the source line, then the exception line
_LAST_FRAME = re.compile(r'File "[^"]+", line \d+, in [^\n]+\n\s+(?P<source>[^\n]+)\n(?:[^\n]*\n)*?(?P<exc>IndexError: [^\n]*)\s*$')
_ARGPARSE_REQUIRED = re.compile(r"^(?P<line>(?:usage: [^\n]*\n(?:[^\n]*\n)*?)?[^\n]*error: the following arguments are required: [^\n]*)\s*$", re.M)
_NO_DISPLAY = re.compile(r"(?P<line>[^\n]*(?:no display name and no \$DISPLAY environment variable|cannot connect to X server|couldn't connect to display|"
                         r"could not connect to display)[^\n]*)")


def stop_of(exit_code: int | None, stdout: str, stderr: str) -> dict | None:
    """{"code", "evidence"} when a failed run's own output shows a missing argument or a missing display, else None. Never on a run that exited 0."""
    if exit_code in (0, None):
        return None
    text = (stderr or "").rstrip() + "\n"
    frame = _LAST_FRAME.search(text)
    if frame and "sys.argv" in frame.group("source"):
        return {"code": ENTRYPOINT_NEEDS_ARGS_REASON_CODE, "evidence": f"{frame.group('source').strip()} -> {frame.group('exc').strip()}"}
    if exit_code == 2:
        required = _ARGPARSE_REQUIRED.search(text) or _ARGPARSE_REQUIRED.search((stdout or "").rstrip() + "\n")
        if required:
            return {"code": ENTRYPOINT_NEEDS_ARGS_REASON_CODE, "evidence": required.group("line").strip().splitlines()[-1][:300]}
    display = _NO_DISPLAY.search(text)
    if display:
        return {"code": DISPLAY_REQUIRED_REASON_CODE, "evidence": display.group("line").strip()[:300]}
    return None


def stop_reason(stop: dict) -> str:
    if stop["code"] == DISPLAY_REQUIRED_REASON_CODE:
        return (f"{DISPLAY_REQUIRED_REASON_CODE}: the program opens a graphical window and the sandbox has no display (`{stop['evidence']}`); "
                "not a verdict on the repository, and no code change can supply a display")
    return (f"{ENTRYPOINT_NEEDS_ARGS_REASON_CODE}: the command failed because it did not get the arguments it reads (`{stop['evidence']}`); "
            "a human must supply them (for example an input file); not repaired, since a code change could only invent them")
