"""resource_adapt (harness-v1.7, R1 (d): METHODOLOGY "harness-v1.7 — PRE-REGISTRATION"). NOT semantics-preserving: a fallback, always labelled.

PURE: reads the repository's Python files from the checkout (AST, nothing executed) and rewrites the documented command's arguments. Used only after
the memory hook (R1 c) is in place and the re-execution was still killed for memory (exit 137 / -9 or an OOM line), and only for a documented
command that runs a Python entry directly (`[VAR=value ...] python [flags] script.py ...` or `python -m module ...`): a shell script is not adapted.

The batch-size options are the argparse options (`add_argument("--...", ...)`) of the entry script and of the repository modules it imports directly
whose name matches BATCH_OPTION. Each option's value is the one on the command line, else the literal int `default=` of its add_argument call; an
option with neither is not adapted. Every such option is set to half its value (an int, at least 1) on the re-execution; at most two rounds (1/2,
then 1/4 of the original). The verdict carries RESOURCE-ADAPTED with the exact arguments; the ladder carries `resource_adapted`.
"""

from __future__ import annotations

import ast
import re
import shlex
from dataclasses import dataclass
from pathlib import Path

BATCH_OPTION = re.compile(r"^--(train[-_]|test[-_]|eval[-_]|val[-_])?(batch[-_]?size|bs)([-_](train|test|eval|val))?$")
MAX_ROUNDS = 2
LABEL = "RESOURCE-ADAPTED"
_PYTHON_EXE = re.compile(r"^(.*/)?python(3(\.\d+)?)?$")
_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_SHELL_OPERATORS = frozenset({"&&", "||", ";", "|", "&", ">", ">>", "<", "<<", "2>&1", "&>", "(", ")"})
_MAX_FILE_BYTES = 400_000


@dataclass(frozen=True)
class Entry:
    tokens: tuple[str, ...]   # the documented command, split as the shell splits it
    script: str | None        # repository-relative entry script (`python x.py`)
    module: str | None        # `python -m pkg.mod`
    args_at: int              # index of the first argument after the script / module


def entry_of(command: str) -> tuple[Entry | None, str]:
    """The Python entry of a documented command, or (None, why it is not adapted)."""
    try:
        tokens = shlex.split(command, comments=True)
    except ValueError as exc:
        return None, f"the command cannot be parsed ({exc})"
    if any(t in _SHELL_OPERATORS or "$(" in t or "`" in t for t in tokens):
        return None, "the command uses shell operators"
    i = 0
    while i < len(tokens) and _ASSIGNMENT.match(tokens[i]):
        i += 1
    if i >= len(tokens) or not _PYTHON_EXE.match(tokens[i]):
        return None, "the command does not run a Python entry directly (a shell script is not adapted)"
    i += 1
    while i < len(tokens) and tokens[i].startswith("-") and tokens[i] not in ("-m", "-c"):
        i += 1
    if i >= len(tokens) or tokens[i] == "-c":
        return None, "the command names no script"
    if tokens[i] == "-m":
        if i + 1 >= len(tokens):
            return None, "python -m without a module"
        return Entry(tuple(tokens), None, tokens[i + 1], i + 2), "ok"
    if not tokens[i].endswith(".py"):
        return None, "the command does not run a .py script"
    return Entry(tuple(tokens), tokens[i].lstrip("./"), None, i + 1), "ok"


def _parse(path: Path) -> ast.Module | None:
    try:
        if path.stat().st_size > _MAX_FILE_BYTES:
            return None
        return ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, SyntaxError, ValueError):
        return None


def _entry_file(workdir: Path, entry: Entry) -> Path | None:
    if entry.script:
        path = workdir / entry.script
    else:
        base = workdir / Path(*entry.module.split("."))
        path = base.with_suffix(".py") if base.with_suffix(".py").is_file() else base / "__main__.py"
    return path if path.is_file() else None


def _imported_repo_files(workdir: Path, entry_file: Path, tree: ast.Module) -> list[Path]:
    """The repository's own modules the entry imports directly (`import a.b`, `from a import b`), resolved from the repo root and the entry's dir."""
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            names.append(node.module)
            names += [f"{node.module}.{a.name}" for a in node.names]
    out: list[Path] = []
    for name in names:
        for base in (workdir, entry_file.parent):
            stem = base / Path(*name.split("."))
            for candidate in (stem.with_suffix(".py"), stem / "__init__.py"):
                if candidate.is_file() and candidate not in out and candidate != entry_file:
                    out.append(candidate)
    return out


def batch_options(workdir: Path, entry: Entry) -> dict[str, int | None]:
    """{option string: its literal int default or None} for every BATCH_OPTION add_argument of the entry and its directly imported repo modules."""
    entry_file = _entry_file(workdir, entry)
    if entry_file is None:
        return {}
    tree = _parse(entry_file)
    if tree is None:
        return {}
    found: dict[str, int | None] = {}
    for path in (entry_file, *_imported_repo_files(workdir, entry_file, tree)):
        module = tree if path == entry_file else _parse(path)
        for node in ast.walk(module) if module is not None else ():
            if not (isinstance(node, ast.Call) and getattr(node.func, "attr", getattr(node.func, "id", None)) == "add_argument"):
                continue
            options = [a.value for a in node.args if isinstance(a, ast.Constant) and isinstance(a.value, str) and BATCH_OPTION.match(a.value)]
            if not options:
                continue
            default = next((k.value.value for k in node.keywords if k.arg == "default" and isinstance(k.value, ast.Constant)
                            and isinstance(k.value.value, int) and not isinstance(k.value.value, bool)), None)
            for option in options:
                found.setdefault(option, default)
    return found


@dataclass(frozen=True)
class Adaptation:
    command: str
    changes: tuple[tuple[str, int, int], ...]  # (option, before, after)

    def label(self) -> str:
        return f"{LABEL}: " + ", ".join(f"{o} {a}->{b}" for o, a, b in self.changes)


def adapt(command: str, options: dict[str, int | None], round_no: int) -> tuple[Adaptation | None, str]:
    """The documented command with every batch option at 1/2**round_no of its value (round 1 or 2), or (None, why)."""
    entry, why = entry_of(command)
    if entry is None:
        return None, why
    if round_no < 1 or round_no > MAX_ROUNDS:
        return None, f"at most {MAX_ROUNDS} rounds"
    tokens = list(entry.tokens)
    changes: list[tuple[str, int, int]] = []
    for option, default in sorted(options.items()):
        value, where = None, None
        for k in range(entry.args_at, len(tokens)):
            if tokens[k] == option and k + 1 < len(tokens) and re.fullmatch(r"\d+", tokens[k + 1]):
                value, where = int(tokens[k + 1]), ("next", k + 1)
                break
            if tokens[k].startswith(option + "=") and re.fullmatch(r"\d+", tokens[k][len(option) + 1:]):
                value, where = int(tokens[k][len(option) + 1:]), ("eq", k)
                break
        if value is None:
            value = default
        if value is None:
            continue
        new = max(1, value // (2 ** round_no))
        if new == value:
            continue
        if where is None:
            tokens.append(option)
            tokens.append(str(new))
        elif where[0] == "next":
            tokens[where[1]] = str(new)
        else:
            tokens[where[1]] = f"{option}={new}"
        changes.append((option, value, new))
    if not changes:
        return None, "no batch-size option with a value to halve"
    return Adaptation(" ".join(shlex.quote(t) if not _ASSIGNMENT.match(t) else t.split("=", 1)[0] + "=" + shlex.quote(t.split("=", 1)[1])
                               for t in tokens), tuple(changes)), "ok"
