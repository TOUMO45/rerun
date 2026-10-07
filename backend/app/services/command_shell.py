"""harness-v1.8 (T11): a documented command with a pipe is run under `bash -o pipefail`, so the pipeline's exit status is the first failure and not the last command's.

PURE. No network, no model call, no filesystem. NOT sandbox-touching: the orchestrator hands the sandbox a different command string; no sandbox file changes.

The evidence. TEST #18 aam-at/adversary_critic (now DEV-CONTAMINATED): the documented command is `python generate_script.py --train=True | bash`. The script died at its
first third-party import (`ModuleNotFoundError: No module named 'decorator'`); `bash`, at the end of the pipe, read nothing and exited 0; the pipeline's status was 0 and the
entry was recorded RUNS_CLEAN, a run that did nothing (D-46's second form). v1.7.2's exit-zero check catches the case where a traceback is the last thing on stderr
of a short run; it states its own limit (a pipeline whose writer crashed late is not caught), and it declined `pipefail` because the command text had to stay the documented
one. That is kept: the certificate's `build_plan.execute_command` is still exactly the documented command. What the sandbox is handed is the same command inside
`bash -o pipefail -c '<command>'`, and the baseline record says so (`baseline.pipefail`, the plan's notes).

Only a pipeline whose LAST stage executes what it reads is wrapped (`| bash`, `| sh`, `| python ...`: the form that was evidenced; independent review, finding 3). A pipe that
ends in `head`, `tee`, `grep` or `wc` keeps the documented semantics: under pipefail `cmd | head -1` would turn the producer's benign SIGPIPE (exit 141, or 120 for a Python
producer) into a failed baseline. Every other command is run exactly as before. The sandbox images are python:X-slim (Debian), which ship bash; the shell the SDK uses for a
plain command is dash, whose `pipefail` support depends on its version, which is why bash is named.
"""

from __future__ import annotations

import re
import shlex

PIPEFAIL_NOTE = ("the documented command pipes into a shell or interpreter, so it is run as `bash -o pipefail -c '<command>'`: the pipeline's exit status is the first failing command's, not the "
                 "last command's (harness-v1.8, T11). The documented text above is unchanged.")


def has_top_level_pipe(command: str) -> bool:
    """True when `command` has a `|` that is a pipe: an unquoted token `|` (not `||`). A pipe inside a `$(...)` is counted too (harmless: pipefail only makes the
    outer status truthful)."""
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        return any(tok == "|" for tok in lexer)
    except ValueError:  # an unterminated quote: not a command this can read; leave it exactly as it is
        return False


_INTERPRETER = re.compile(r"^(?:bash|sh|dash|zsh|ksh|python(?:\d+(?:\.\d+)*)?)$")
_PREFIX = "bash -o pipefail -c "


def pipes_into_interpreter(command: str) -> bool:
    """True when the LAST top-level pipe of `command` feeds a shell or Python interpreter (`... | bash`, `... | sh -s`, `... | python3 -`): a stage that executes what it
    reads, so a producer that died before writing anything leaves it reading nothing and exiting 0 (TEST #18)."""
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        tokens = list(lexer)
    except ValueError:  # an unterminated quote: not a command this can read
        return False
    last = max((i for i, tok in enumerate(tokens) if tok == "|"), default=None)
    if last is None:
        return False
    for tok in tokens[last + 1:]:
        if re.match(r"^[A-Za-z_]\w*=", tok):  # a leading VAR=value
            continue
        return bool(_INTERPRETER.match(tok.rsplit("/", 1)[-1]))
    return False


def with_pipefail(command: str) -> str:
    """`command` run inside bash with pipefail on when it pipes into an interpreter, else `command` itself. Idempotent."""
    if command.startswith(_PREFIX) or not pipes_into_interpreter(command):
        return command
    return f"{_PREFIX}{shlex.quote(command)}"
