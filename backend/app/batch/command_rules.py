"""corpus-v1 amendment 1 (2026-09-28): is a recorded corpus command a RUN of
the paper's code, or something else (an install, a download, preprocessing,
a setup script, or a command with an unfilled placeholder)?

PURE: looks only at the command string recorded in corpus.yaml — never at a
run outcome. Every rule is a regex over one part of the command, applied
identically to every entry; an entry is COMMAND_NOT_A_RUN if ANY rule
matches, else it is in the PRIMARY endpoint. The rules write down exactly the
post-draw review's prose (METHODOLOGY.md, "corpus-v1 — draw result"), before
any corpus-v1 entry was executed.
"""

from __future__ import annotations

import re
import shlex

PRIMARY = "PRIMARY"
COMMAND_NOT_A_RUN = "COMMAND_NOT_A_RUN"

# The runnable target: `python|python3|bash|sh <path>.py|.sh` or `python -m <mod>`,
# after optional leading `VAR=value` assignments (the prereg E5 shape).
_TARGET_RE = re.compile(
    r"^(?:[A-Z_][A-Z0-9_]*=\S+\s+)*(?:python3?|bash|sh)\s+"
    r"(?:-m\s+(?P<module>[A-Za-z_][\w.]*)|(?P<script>\S+\.(?:py|sh)))(?=\s|$)"
)

# A "stem" is the script's file name without its extension, or a module's
# last dotted component. Stem regexes ignore case; argument regexes do not
# (R5's ALL_CAPS test depends on case).
RULES: dict[str, dict] = {
    "R1_INSTALL": {
        "stem_regex": r"^(setup|install)$",
        "arg_regex": r"^(install|develop)$",
        "description": "an install step: a setup.py/install script, or an `install`/`develop` argument",
    },
    "R2_DOWNLOAD": {
        "stem_regex": r"download",
        "description": "a download step (stem contains 'download')",
    },
    "R3_PREPROCESS": {
        "stem_regex": r"^(pre_?)?process",
        "description": "a (pre)processing step (stem starts with 'process' or 'preprocess')",
    },
    "R4_SETUP_SCRIPT": {
        "stem_regex": r"^(pre_?run|prepare|setup_|init_?env)",
        "description": "a setup/preparation script (stem starts with pre_run, prepare, setup_ or init_env)",
    },
    "R5_PLACEHOLDER": {
        "arg_regex": r"\$\{?[A-Za-z_]|\[[^\]]*\|[^\]]*\]|(?:^|=)[A-Z]+(?:_[A-Z]+)+$",
        "description": "an unfilled placeholder in an argument after the target: a $VAR/${VAR} reference, "
        "an [a|b] choice list, or a whole value in ALL_CAPS with at least one underscore "
        "(CONF_FILE, LOG_DIR; not TTL2, D4)",
    },
}


def stem_and_args(command: str) -> tuple[str, list[str]]:
    match = _TARGET_RE.match(command.strip())
    if match is None:
        raise ValueError(f"not a corpus command shape: {command!r}")
    if match.group("module"):
        stem = match.group("module").split(".")[-1]
    else:
        stem = match.group("script").replace("\\", "/").rsplit("/", 1)[-1].rsplit(".", 1)[0]
    rest = command.strip()[match.end():]
    try:
        args = shlex.split(rest)
    except ValueError:
        args = rest.split()
    return stem, args


def matched_rules(command: str) -> list[str]:
    """Every rule id that matches `command` (empty = a genuine run command)."""
    stem, args = stem_and_args(command)
    hits = []
    for rule_id, rule in RULES.items():
        stem_hit = "stem_regex" in rule and re.search(rule["stem_regex"], stem, re.IGNORECASE)
        arg_hit = "arg_regex" in rule and any(re.search(rule["arg_regex"], a) for a in args)
        if stem_hit or arg_hit:
            hits.append(rule_id)
    return hits


def classify_command(command: str) -> str:
    return COMMAND_NOT_A_RUN if matched_rules(command) else PRIMARY
