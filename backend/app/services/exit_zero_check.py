"""harness-v1.7.2 (D-46): an exit code 0 is no longer read as success whatever the run printed.

PURE. No network, no model call, no filesystem. NOT sandbox-touching: nothing here runs inside the sandbox; it reads the streams the sandbox
returned for the documented command's final step, at verdict time, in the orchestrator.

The evidence. TEST #18 (`aam-at/adversary_critic`, harness-v1.5-final): the documented command `python generate_script.py --train=True | bash`
failed at its first third-party import (`ModuleNotFoundError: No module named 'decorator'`, 154 bytes of stderr, nothing on stdout, about 0.1 s of
run time); the pipe's exit code is `bash`'s, which read nothing and exited 0, and the run was recorded RUNS_CLEAN. DEV #12 (`Mehran-k/SimplE`): its
`main.py` run with no arguments prints `Please specify the model name using -m.` and calls `exit()`, exit code 0. A live UI scan
(`faris-shi/py_weather_cli`, 2026-10-05, `runs/live_scan/`): the adopted repair's run printed only `No openweathermap.org API key specified.` /
`You have to register for one at https://home.openweathermap.org/users/sign_up` and exited 0 in about 2 s; the entry was recorded RUNS_AFTER_REPAIR.

Three deterministic findings, each only on a step that exited 0 in the repository's own phase (`repo_run`):

  traceback  stderr's LAST non-empty line is the exception line that closes a `Traceback (most recent call last):` block (an uncaught exception ends
             the interpreter, so nothing of that process follows it), the block is not an interpreter-shutdown report (`Exception ignored in: ...`,
             printed by a program that then exits normally), the exception is not `SystemExit`, and the step ran for less than
             TRACEBACK_MAX_SECONDS. The run is NOT a pass: it is classified like a failed run from the traceback (classifier.classify, unchanged).
  usage      the step ran for less than USAGE_MAX_SECONDS, printed no traceback, and everything it printed (stdout and stderr, at most
             USAGE_MAX_LINES lines) is an argument/usage message: its first line matches USAGE_RE and every other line is usage-shaped (an
             argparse help block). The run is NOT a pass; when it is the run's last word, the entry ends INDETERMINATE with
             ENTRYPOINT_NEEDS_ARGS_REASON_CODE and the usage line as evidence.
  missing    the step ran for less than USAGE_MAX_SECONDS, printed no traceback, its whole output is short (at most MISSING_MAX_LINES lines and
             MISSING_MAX_CHARS characters), its FIRST line says something is missing or required (MISSING_RE), and no line looks like work
             (WORK_RE: a number with a unit, a percentage, an epoch/step/loss line...). The run is NOT a pass; when it is the run's last word the entry
             ends INDETERMINATE with NEEDS_CREDENTIALS_REASON_CODE when the output names a key / token / credential / registration (CREDENTIAL_RE),
             else ENTRYPOINT_NEEDS_ARGS_REASON_CODE, the first line quoted as evidence.

Conservative on purpose (prefer not to flip a run that did work):
  - a traceback FOLLOWED by any other stderr output (a caught exception logged as a warning, then the program went on) is not a finding;
  - a traceback that is the last thing on stderr of a step that ran TRACEBACK_MAX_SECONDS or longer is not a finding: a program that logged a caught
    exception to stderr and then worked for minutes, printing its progress to stdout, cannot be told from a pipeline whose writer crashed late
    (stated limitation: the late crash of a pipeline's first command is not caught by this rule);
  - a usage-like or "missing" word inside real output (not its first line, or output longer than the limits), or such a message from a run that
    took USAGE_MAX_SECONDS or longer, is not a finding;
  - a smoke run the launcher stopped while it was alive (`RERUN_SMOKE_ALIVE` on stdout) is never a finding (the launcher already refuses an alive
    run that printed a traceback).

Not retroactive: no stored record is re-read; a record keeps its verdict. A run this check overrules carries `exit_zero_check` (on the baseline, on
the attempt's `execution`, on the candidate's stage and on the error-chain link), and the verdict label says "exit 0 overruled".

`set -o pipefail` (the other half of D-46's TEST #18 case) is NOT added: the documented command runs through the sandbox's own shell, which the
offline harness cannot check supports it (dash before 0.5.12 does not), and the command text the baseline runs must stay the documented one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, fields

from app.services.sandbox import SandboxRunResult

ENTRYPOINT_NEEDS_ARGS_REASON_CODE = "ENTRYPOINT_NEEDS_ARGS"
NEEDS_CREDENTIALS_REASON_CODE = "NEEDS_CREDENTIALS"
LABEL = "exit 0 overruled"
# What classifier.classify is given for an overruled run: it refuses exit code 0 by contract (a pass never reaches it); the recorded exit code stays 0.
CLASSIFY_EXIT_CODE = 1

TRACEBACK_MAX_SECONDS = 60.0
USAGE_MAX_SECONDS = 5.0
USAGE_MAX_LINES = 40
USAGE_MAX_CHARS = 4000
MISSING_MAX_LINES = 6
MISSING_MAX_CHARS = 800

_SMOKE_ALIVE = "RERUN_SMOKE_ALIVE"  # smoke_exec.ALIVE_MARKER (not imported: smoke_exec is sandbox-touching and this module only reads its marker)
_TRACEBACK_HEAD = "Traceback (most recent call last):"
_EXCEPTION_LINE_RE = re.compile(r"^(?P<name>[A-Za-z_][\w.]*)(?::\s?(?P<message>.*))?$")
_IGNORED_RE = re.compile(r"^Exception ignored (?:in|on)\b")
_CHAIN_SEPARATORS = ("During handling of the above exception", "The above exception was the direct cause")
USAGE_RE = re.compile(
    r"^\s*usage:|\bplease (?:specify|provide|give|pass|supply|enter|set|choose|select)\b|the following arguments are required"
    r"|\b(?:missing|required) (?:required )?(?:argument|option|parameter)s?\b|(?:^|\s)--help\b|\bno (?:model|dataset|config|input) (?:was )?specified\b",
    re.IGNORECASE,
)
MISSING_RE = re.compile(
    r"\bnot (?:specified|set|provided|given|configured|defined|supplied)\b|\b(?:is|are) (?:required|missing|needed)\b|\bmissing\b|\brequired\b"
    r"|\bno [\w./ -]{0,60}?\b(?:specified|given|provided|set|configured|found)\b|\byou (?:have|need|must) to (?:register|sign up|provide|set|specify)\b"
    r"|\bplease (?:specify|provide|give|pass|supply|enter|set|register|sign up)\b",
    re.IGNORECASE,
)
CREDENTIAL_RE = re.compile(
    r"\bapi[ _-]?key\b|\btoken\b|\bcredentials?\b|\bpassword\b|\bsecret\b|\baccess[ _-]?key\b|\bregister\b|\bsign[ _-]?up\b|\bapi[ _-]?secret\b"
    r"|\b[A-Z][A-Z0-9_]*_(?:KEY|TOKEN|SECRET)\b",
    re.IGNORECASE,
)
WORK_RE = re.compile(r"\d+(?:\.\d+)?\s*%|\b(?:epoch|iter(?:ation)?|step|loss|accuracy|acc|batch)\b\s*[:=]?\s*\d|\d+(?:\.\d+)?\s*(?:s|ms|sec|°[CF]|MB|GB|KB)\b",
                     re.IGNORECASE)
_HELP_SHAPED_RE = re.compile(r"^(?:\s|-|\[|<)|:\s*$|^(?:positional|optional) arguments|^options\b", re.IGNORECASE)


@dataclass(frozen=True)
class Finding:
    kind: str  # "traceback" | "usage" | "missing"
    evidence: str  # the exception line, the usage line, or the "missing" line
    seconds: float
    code: str = ""  # the INDETERMINATE reason code of a "usage" / "missing" finding

    def as_dict(self) -> dict:
        if self.kind == "traceback":
            rule = f"exit code 0, and stderr ends with an uncaught traceback (step ran {self.seconds:.1f} s < {TRACEBACK_MAX_SECONDS:.0f} s)"
        elif self.kind == "usage":
            rule = f"exit code 0 after {self.seconds:.1f} s (< {USAGE_MAX_SECONDS:.0f} s), and the only output is an argument/usage message"
        else:
            rule = (f"exit code 0 after {self.seconds:.1f} s (< {USAGE_MAX_SECONDS:.0f} s), and the whole (short) output says something the run needs is "
                    "missing")
        out = {"overruled": True, "kind": self.kind, "evidence": self.evidence[:500], "seconds": round(self.seconds, 3), "rule": rule,
               "version": "harness-v1.7.2 (D-46)"}
        if self.code:
            out["code"] = self.code
        return out


def _nonblank(text: str) -> list[str]:
    return [line for line in (text or "").splitlines() if line.strip()]


def _uncaught_traceback(stderr: str) -> str | None:
    """The exception line when stderr ENDS with an uncaught traceback, else None."""
    lines = _nonblank(stderr)
    if not lines:
        return None
    heads = [i for i, line in enumerate(lines) if line.strip() == _TRACEBACK_HEAD]
    if not heads:
        return None
    head = heads[-1]
    # The exception line is the first non-indented line after the block's frames; it must be the last thing on stderr (nothing printed after it).
    closing = next((i for i in range(head + 1, len(lines)) if not lines[i].startswith((" ", "\t"))), None)
    if closing != len(lines) - 1:
        return None
    last = lines[-1]
    if last.startswith((" ", "\t")) or last.strip() == _TRACEBACK_HEAD:
        return None  # the block is not closed by an exception line (cut, or still being written)
    match = _EXCEPTION_LINE_RE.match(last.strip())
    if not match or match.group("name").split(".")[-1] == "SystemExit":
        return None
    # The block's own lines: `File ...` frames and their code lines, indented; a chained exception's separators are allowed.
    body = lines[head + 1:-1]
    if not body or not any(line.lstrip().startswith("File ") for line in body):
        return None
    # An interpreter-shutdown report (`Exception ignored in: <function X.__del__>` then a traceback) is printed by a program that exits normally.
    # A chained exception ("During handling of the above exception, ...") is one report: its first block decides.
    start = head
    while start > 0 and lines[start - 1].strip().startswith(_CHAIN_SEPARATORS):
        earlier = [i for i in heads if i < start - 1]
        if not earlier:
            break
        start = earlier[-1]
    if start > 0 and _IGNORED_RE.match(lines[start - 1].strip()):
        return None
    return last.strip()


def _usage_line(stdout: str, stderr: str) -> str | None:
    """The usage line when everything printed is an argument/usage message, else None."""
    text = f"{stdout or ''}\n{stderr or ''}"
    lines = _nonblank(text)
    if not lines or len(lines) > USAGE_MAX_LINES or len(text.strip()) > USAGE_MAX_CHARS:
        return None
    if _TRACEBACK_HEAD in text or _SMOKE_ALIVE in text:
        return None
    first = lines[0].strip()
    if not USAGE_RE.search(first):
        return None
    for line in lines[1:]:
        if not (USAGE_RE.search(line) or _HELP_SHAPED_RE.search(line)):
            return None
    return first


def _missing_line(stdout: str, stderr: str) -> tuple[str, str] | None:
    """(first line, reason code) when the whole short output says something the run needs is missing, else None."""
    text = f"{stdout or ''}\n{stderr or ''}"
    lines = _nonblank(text)
    if not lines or len(lines) > MISSING_MAX_LINES or len(text.strip()) > MISSING_MAX_CHARS:
        return None
    if _TRACEBACK_HEAD in text or _SMOKE_ALIVE in text:
        return None
    first = lines[0].strip()
    if not MISSING_RE.search(first) or any(WORK_RE.search(line) for line in lines):
        return None
    code = NEEDS_CREDENTIALS_REASON_CODE if any(CREDENTIAL_RE.search(line) for line in lines) else ENTRYPOINT_NEEDS_ARGS_REASON_CODE
    return first, code


def check(exit_code: int | None, stdout: str, stderr: str, seconds: float | None, *, phase: str = "repo_run") -> Finding | None:
    """The D-46 finding for one finished step, or None (the exit code stands). Only an exit code 0 of the repository's own command is examined."""
    if exit_code != 0 or phase != "repo_run":
        return None
    if _SMOKE_ALIVE in (stdout or ""):
        return None
    elapsed = float(seconds or 0.0)
    if elapsed < TRACEBACK_MAX_SECONDS:
        exception = _uncaught_traceback(stderr)
        if exception is not None:
            return Finding("traceback", exception, elapsed)
    if elapsed < USAGE_MAX_SECONDS:
        usage = _usage_line(stdout, stderr)
        if usage is not None:
            return Finding("usage", usage, elapsed, ENTRYPOINT_NEEDS_ARGS_REASON_CODE)
        missing = _missing_line(stdout, stderr)
        if missing is not None:
            return Finding("missing", missing[0], elapsed, missing[1])
    return None


@dataclass(frozen=True)
class ExitZeroOverruled(SandboxRunResult):
    """A SandboxRunResult whose final step exited 0 but which this module overruled: `succeeded` is False, every recorded exit code is unchanged."""

    exit_zero_check: dict = field(default_factory=dict)

    @property
    def succeeded(self) -> bool:
        return False


def overrule(result):
    """`result` unchanged, or an ExitZeroOverruled copy carrying the finding. Anything that is not a SandboxRunResult (a duck-typed fake) is unchanged."""
    if not isinstance(result, SandboxRunResult) or isinstance(result, ExitZeroOverruled) or not result.steps:
        return result
    final = result.final
    found = check(final.exit_code, final.stdout, final.stderr, final.elapsed_seconds, phase=final.phase)
    if found is None:
        return result
    return ExitZeroOverruled(**{f.name: getattr(result, f.name) for f in fields(SandboxRunResult)}, exit_zero_check=found.as_dict())


def finding_of(result) -> dict | None:
    return getattr(result, "exit_zero_check", None) or None


def stop_of(result) -> dict | None:
    """The finding of an overruled run that ENDS the entry (a "usage" or "missing" finding), else None. A "traceback" finding does not end it: the
    run is classified and repaired like any failed run."""
    found = finding_of(result)
    return found if found and found.get("kind") in ("usage", "missing") else None


def stop_reason(found: dict) -> str:
    """The INDETERMINATE reason of a stop_of finding: its code, what the run printed, and that nothing is claimed about the repository."""
    seconds, evidence = found.get("seconds", 0.0), found.get("evidence", "")
    if found.get("kind") == "usage":
        return (f"{ENTRYPOINT_NEEDS_ARGS_REASON_CODE}: the command exited 0 after {seconds:.1f} s and printed only an argument/usage message "
                f"({evidence!r}): the entry point needs arguments this run did not give it, so nothing ran; not a verdict on the repository "
                "(harness-v1.7.2, D-46).")
    code = found.get("code") or ENTRYPOINT_NEEDS_ARGS_REASON_CODE
    what = ("a key, token or credential this run does not have" if code == NEEDS_CREDENTIALS_REASON_CODE
            else "an input (an argument, a setting or a file) this run did not give it")
    return (f"{code}: the command exited 0 after {seconds:.1f} s and printed only that something it needs is missing ({evidence!r}): it needs {what}, "
            "so nothing ran; not a verdict on the repository (harness-v1.7.2, D-46).")


def classify_exit_code(exit_code: int | None) -> int | None:
    """The exit code classifier.classify is given: an overruled run's 0 becomes CLASSIFY_EXIT_CODE (classify() refuses 0 by contract, so no earlier
    call ever passed it one: every earlier classification is unchanged)."""
    return CLASSIFY_EXIT_CODE if exit_code == 0 else exit_code
