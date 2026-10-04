"""Data preparation the repository documents (harness-v1.7, R3: METHODOLOGY "harness-v1.7 — PRE-REGISTRATION").

PURE: reads the repository's own README files from the checkout; no network, no model, no sandbox. Fired at repair time on a failure classified
DATA_MISSING, before any model call, once per run. It finds ONE documented step and returns it; it never invents an input:

  (a) a documented script: a README names a file that exists in the repository and whose name matches SCRIPT_NAME
      (download / prepare / get / fetch / generate / make / build / create + data / dataset, .sh or .py). The invocation is the first command of
      the first fenced code block of that README that runs the script (backslash continuations joined), verbatim, run in the script's directory;
      a script no code block invokes runs with no arguments. Several scripts: the one whose directory names a word of the evidence line
      (`cifar10`); none named: not fired.
  (b) else a documented archive: an http(s) URL in a README ending in .tar.gz / .tgz / .zip / .npz, within 3 lines of the word download or
      dataset, downloaded into the directory the evidence path names (else the one the README line names); archives are extracted there.

The README files read: the root README*, docs/*.md, and the README* of every directory the root README names (`./data/cifar10`). A command
with `sudo`, a shell operator, or an interpreter other than python / sh / bash is refused (recorded with the reason), never rewritten.
Execution, caps (180 s, 500 MB written) and the record are the runner's (runner_hooks.data_prep_command).
"""

from __future__ import annotations

import posixpath
import re
import shlex
from dataclasses import dataclass, field
from pathlib import Path

SCRIPT_NAME = re.compile(r"^(download|prepare|get|fetch|generate|make|build|create)[_-]?(the[_-]?)?(data|dataset)s?\.(sh|py)$", re.IGNORECASE)
_SCRIPT_TOKEN = re.compile(r"(?<![\w./-])((?:[\w.-]+/)*[\w.-]+\.(?:sh|py))(?![\w])")
ARCHIVE_URL = re.compile(r"https?://[^\s)\]>\"'`]+?\.(?:tar\.gz|tgz|zip|npz)(?=[\s)\]>\"'`]|$)", re.IGNORECASE)
_NEAR_WORDS = re.compile(r"\b(download|dataset)", re.IGNORECASE)
_DIR_TOKEN = re.compile(r"(?<![\w$])(\.?/?[\w.-]+(?:/[\w.-]+)+)/?")
_EVIDENCE_PATH = re.compile(r"""(?:No such file or directory|FileNotFoundError)[^'"]*['"]([^'"]+)['"]""")
_WORD = re.compile(r"[a-z][a-z0-9_-]{2,}")
_FENCE = re.compile(r"^\s*(```|~~~)")
_SHELL_OPERATORS = frozenset({"&&", "||", ";", "|", "&", ">", ">>", "<", "<<", "2>&1", "&>", "(", ")"})
_INTERPRETERS = frozenset({"python", "python3", "sh", "bash"})
NEAR_LINES = 3
README_MAX_BYTES = 200_000
_STOP_WORDS = frozenset({"the", "and", "for", "data", "dataset", "datasets", "download", "file", "directory", "such", "please", "first", "error",
                         "assertionerror", "filenotfounderror", "errno", "not", "found", "exist", "does", "missing", "caught", "worker", "process"})


@dataclass(frozen=True)
class DataPrep:
    kind: str                     # "script" | "archive"
    readme: str                   # repository-relative path of the README that documents the step
    line: int                     # 1-based line of that README the step comes from
    quote: str                    # that line, as written
    workdir: str                  # repository-relative directory the step runs in / downloads into ("" = the root)
    command: tuple[str, ...] = ()  # (a): argv, run in `workdir`
    url: str = ""                 # (b)
    script: str = ""              # (a): repository-relative path of the script
    dataset_name: str = ""        # a dataset name the README gives near the step, for the Tavily lookup (v1.6 item S)

    def as_dict(self) -> dict:
        out = {"kind": self.kind, "readme": self.readme, "line": self.line, "quote": self.quote, "workdir": self.workdir}
        if self.command:
            out["command"] = shlex.join(self.command)
            out["script"] = self.script
        if self.url:
            out["url"] = self.url
        if self.dataset_name:
            out["dataset_name"] = self.dataset_name
        return out


@dataclass(frozen=True)
class Decision:
    """What the rule decided: `prep` when it fires, else `reason` (recorded either way)."""
    prep: DataPrep | None
    reason: str
    readmes: tuple[str, ...] = field(default_factory=tuple)


def _read(path: Path) -> str | None:
    try:
        if path.stat().st_size > README_MAX_BYTES:
            return None
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _readme_in(directory: Path) -> Path | None:
    for name in sorted(p.name for p in directory.iterdir() if p.is_file()) if directory.is_dir() else ():
        if name.lower().startswith("readme"):
            return directory / name
    return None


def _inside(path: str) -> str | None:
    """A repository-relative POSIX path, or None for an absolute path or one that leaves the repository (`../data`). Only a leading `./` is dropped
    (v1.7 review, L7: `.lstrip("./")` had turned `../data` into `data`)."""
    while path.startswith("./"):
        path = path[2:]
    if not path or path.startswith("/"):
        return None
    norm = posixpath.normpath(path)
    return None if norm == ".." or norm.startswith("../") else norm


def readmes(workdir: Path) -> list[tuple[str, str]]:
    """(repository-relative path, text) of every README the rule reads, root first, in a fixed order."""
    out: list[tuple[str, str]] = []
    root = _readme_in(workdir)
    if root is None:
        return out
    root_text = _read(root) or ""
    out.append((root.relative_to(workdir).as_posix(), root_text))
    docs = workdir / "docs"
    if docs.is_dir():
        for md in sorted(docs.glob("*.md")):
            text = _read(md)
            if text is not None:
                out.append((md.relative_to(workdir).as_posix(), text))
    seen = {p for p, _ in out}
    for m in _DIR_TOKEN.finditer(root_text):
        rel = _inside(m.group(1))
        if rel is None or rel == ".":
            continue
        directory = workdir / rel
        readme = _readme_in(directory)
        if readme is not None and readme.relative_to(workdir).as_posix() not in seen:
            text = _read(readme)
            if text is not None:
                seen.add(readme.relative_to(workdir).as_posix())
                out.append((readme.relative_to(workdir).as_posix(), text))
    return out


def evidence_words(evidence: str) -> set[str]:
    return {w for w in _WORD.findall((evidence or "").lower()) if w not in _STOP_WORDS}


def _code_blocks(text: str) -> list[tuple[int, list[tuple[int, str]]]]:
    """[(first line number, [(line number, line), ...])] of every fenced code block."""
    blocks, current, start = [], None, 0
    for n, line in enumerate(text.splitlines(), start=1):
        if _FENCE.match(line):
            if current is None:
                current, start = [], n
            else:
                blocks.append((start, current))
                current = None
        elif current is not None:
            current.append((n, line))
    return blocks


def _commands(block: list[tuple[int, str]]) -> list[tuple[int, str]]:
    """The commands of a code block: backslash-continued lines joined, each with the line number it starts on."""
    out, buf, first = [], [], None
    for n, line in block:
        stripped = line.strip()
        if not buf and (not stripped or stripped.startswith("#")):
            continue
        if first is None:
            first = n
        if stripped.endswith("\\"):
            buf.append(stripped[:-1].strip())
            continue
        buf.append(stripped)
        out.append((first, " ".join(p for p in buf if p)))
        buf, first = [], None
    if buf:
        out.append((first, " ".join(p for p in buf if p)))
    return out


def _safe_argv(command: str, script_name: str) -> tuple[tuple[str, ...] | None, str]:
    """argv of a README command that runs `script_name`, or (None, why)."""
    if re.search(r"\bsudo\b", command):
        return None, "the command uses sudo"
    try:
        tokens = shlex.split(command, comments=True)
    except ValueError as exc:
        return None, f"the command cannot be parsed ({exc})"
    if not tokens:
        return None, "empty command"
    if any(t in _SHELL_OPERATORS or "$(" in t or "`" in t for t in tokens):
        return None, "the command uses shell operators"
    exe = tokens[0].rsplit("/", 1)[-1]
    if exe in _INTERPRETERS or re.fullmatch(r"python3(\.\d+)?", exe):
        if len(tokens) < 2 or tokens[1].rsplit("/", 1)[-1] != script_name:
            return None, "the command does not run the script directly"
        return ("python" if exe.startswith("python") else exe, script_name, *tokens[2:]), "ok"
    if exe == script_name:
        interpreter = "python" if script_name.endswith(".py") else "sh"
        return (interpreter, script_name, *tokens[1:]), "ok"
    return None, f"the command runs {tokens[0]!r}, not a python / sh / bash interpreter"


def _dataset_name_near(lines: list[str], index: int, words: set[str]) -> str:
    """A word of the evidence that the README spells near line `index` (as the README spells it), else ''."""
    window = " ".join(lines[max(0, index - NEAR_LINES): index + NEAR_LINES + 1])
    for text in (window, " ".join(lines)):  # near the step first, then anywhere in that README (its title names the dataset)
        for w in sorted(words, key=len, reverse=True):
            m = re.search(re.escape(w), text, re.IGNORECASE)
            if m:
                return m.group(0)
    return ""


def decide(workdir: Path, evidence: str) -> Decision:
    """The one documented step for a DATA_MISSING failure with `evidence`, or why there is none."""
    docs = readmes(workdir)
    names = tuple(p for p, _ in docs)
    if not docs:
        return Decision(None, "the repository has no README", names)
    words = evidence_words(evidence)

    # (a) documented scripts
    found: dict[str, tuple[str, int, str]] = {}  # script rel path -> (readme, line, quote)
    for readme, text in docs:
        base = posixpath.dirname(readme)
        lines = text.splitlines()
        for i, line in enumerate(lines):
            for m in _SCRIPT_TOKEN.finditer(line):
                name = m.group(1).rsplit("/", 1)[-1]
                if not SCRIPT_NAME.match(name):
                    continue
                candidates = [posixpath.normpath(posixpath.join(base, m.group(1))), posixpath.normpath(m.group(1))]
                rel = next((c for c in candidates if not c.startswith("..") and (workdir / c).is_file()), None)
                if rel is None:
                    hits = sorted(p.relative_to(workdir).as_posix() for p in workdir.rglob(name) if p.is_file() and ".git" not in p.parts)
                    rel = hits[0] if len(hits) == 1 else None
                if rel is not None and rel not in found:
                    found[rel] = (readme, i + 1, line.strip())
    if found:
        chosen = list(found)
        if len(chosen) > 1:
            named = [s for s in chosen if words & set(re.split(r"[/_.-]", posixpath.dirname(s).lower()))]
            if len(named) != 1:
                return Decision(None, f"{len(chosen)} documented data scripts ({', '.join(sorted(chosen))}) and the evidence names "
                                      f"{'none' if not named else 'more than one'} of their directories", names)
            chosen = named
        script = chosen[0]
        script_name = posixpath.basename(script)
        readme, line_no, quote = found[script]
        text = dict(docs)[readme]
        argv, why = (("python" if script_name.endswith(".py") else "sh", script_name), "no code block invokes it: run with no arguments")
        for _start, block in _code_blocks(text):
            cmds = [(n, c) for n, c in _commands(block) if script_name in c]
            if cmds:
                n, command = cmds[0]
                argv, why = _safe_argv(command, script_name)
                if argv is None:
                    return Decision(None, f"{readme}:{n}: `{command}`: {why}", names)
                line_no, quote = n, command
                break
        lines = text.splitlines()
        return Decision(DataPrep("script", readme, line_no, quote, posixpath.dirname(script), command=tuple(argv), script=script,
                                 dataset_name=_dataset_name_near(lines, line_no - 1, words)), "fired: a documented script", names)

    # (b) documented archives
    target_from_evidence = ""
    m = _EVIDENCE_PATH.search(evidence or "")
    inside = _inside(m.group(1)) if m else None
    if inside is not None:
        target = posixpath.dirname(inside)
        target_from_evidence = "" if target in (".", "") else target
    for readme, text in docs:
        lines = text.splitlines()
        for i, line in enumerate(lines):
            for url_m in ARCHIVE_URL.finditer(line):
                window = lines[max(0, i - NEAR_LINES): i + NEAR_LINES + 1]
                if not any(_NEAR_WORDS.search(w) for w in window):
                    continue
                workdir_rel = target_from_evidence
                if not workdir_rel:
                    named = [_inside(d.group(1)) for w in window for d in _DIR_TOKEN.finditer(w)
                             if not d.group(1).startswith("http") and "://" not in w[max(0, d.start() - 3): d.start() + 1]]
                    named = [d.rstrip("/") for d in named if d and (workdir / d).is_dir()]
                    if not named:
                        return Decision(None, f"{readme}:{i + 1}: an archive URL, but neither the evidence nor the README names where it goes", names)
                    workdir_rel = named[0]
                return Decision(DataPrep("archive", readme, i + 1, line.strip(), workdir_rel, url=url_m.group(0),
                                         dataset_name=_dataset_name_near(lines, i, words)), "fired: a documented archive", names)
    return Decision(None, "no README names a data script or an archive URL near the words download / dataset", names)
