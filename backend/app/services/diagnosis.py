"""harness-v1.8: an evidence-driven diagnosis of what blocks a repository, read off the record (owner, 2026-10-07: "the fixable_by / 'human must supply' text must be
derived from the record's evidence, not a fixed sentence per class").

PURE. No network, no model call, no filesystem. Input: the same certificate-visible fields `blocker.report` always read (`verdict`, `error_chain`, `attempts`),
plus `indeterminate_reason`, `baseline` and `full_log` when the caller has them. Output: a `Finding` or None. None means no rule matched: the caller keeps the old
per-class sentence and says so (`diagnosis: "class_default"`), so a reader can tell a specific diagnosis from a default one.

Why rules over evidence and not prose from a model (the same reason blocker.py gave): the certificate is read by someone who did not run the audit, the text must
be reproducible from the record by anyone, and it is scored by a written key and a script (reports/dev/v18/check_diagnosis.py), not by me reading my own output.

What a rule may use, and nothing else: lines of the run's own output (the chain's `error`, each attempt's `stderr_tail` / `stdout_tail`), what the attempts proposed
(`env_delta`: package, version) and what the gate said about it (`gate_violations`), and RERUN's own structured actions (`time_machine_action`). Every `error_line` is a
verbatim line of that output (ANSI colour codes removed); every `basis` entry quotes its source. A fact that is not in the record is not asserted: where a rule states
something about the world (MuJoCo 2.1.0 is free, NLTK's `ptb` is a stub), the table below says where it was checked.

The rules were written from the 14 blocker records of the 21 held-out entries (now DEV-CONTAMINATED), against an answer key committed before this module existed
(reports/dev/v18/diagnosis_key.json). They are general: each keys on a pattern of evidence, never on a repository.
"""

from __future__ import annotations

import ast
import difflib
import re
from dataclasses import dataclass

from app.services import system_packages
from app.services.import_names import dist_for_import

DETERMINISTIC = "deterministic"
HUMAN = "human"
PLATFORM = "platform"

_ANSI = re.compile(r"\x1b\[[0-9;]*m")
LINE_MAX = 300


def strip_ansi(text: str | None) -> str:
    return _ANSI.sub("", text or "")


@dataclass(frozen=True)
class Finding:
    cause: str  # a stable id: DOCKER_REQUIRED, CONDA_REQUIRED, NLTK_RESOURCE_MISSING, ...
    fixable_by: str
    sentence: str  # what a human must supply (the old `what_a_human_must_supply`, now from the evidence)
    next_action: str  # one concrete thing a researcher can do
    error_line: str  # a verbatim line of the record's own output
    basis: tuple[dict, ...]  # [{"source": "attempts[7].stderr_tail", "quote": "..."}]
    family: str | None = None  # set when the cause belongs to another family than the class's (docker: not a "Code" matter)

    def as_dict(self) -> dict:
        return {"cause": self.cause, "fixable_by": self.fixable_by, "what_a_human_must_supply": self.sentence, "next_action": self.next_action,
                "error_line": self.error_line, "basis": [dict(b) for b in self.basis]}


class _Ctx:
    """The record, with its text blobs ordered from the most recent to the oldest."""

    def __init__(self, record: dict):
        self.record = record
        self.chain: list[dict] = list(record.get("error_chain") or ())
        self.attempts: list[dict] = list(record.get("attempts") or ())
        self.reason: str = record.get("indeterminate_reason") or ""
        self.blobs: list[tuple[str, str]] = []
        for i in range(len(self.attempts) - 1, -1, -1):
            a = self.attempts[i] or {}
            for key in ("stderr_tail", "stdout_tail"):
                if a.get(key):
                    self.blobs.append((f"attempts[{i}].{key}", strip_ansi(a[key])))
        for i in range(len(self.chain) - 1, -1, -1):
            if self.chain[i].get("error"):
                self.blobs.append((f"error_chain[{i}].error", strip_ansi(self.chain[i]["error"])))
        base = record.get("baseline") or {}
        if base.get("evidence"):
            self.blobs.append(("baseline.evidence", strip_ansi(base["evidence"])))
        if record.get("full_log"):
            self.blobs.append(("full_log", strip_ansi(record["full_log"])))

    def find(self, pattern: re.Pattern | str, *, flags: int = 0, exclude: tuple[str, ...] = ()) -> tuple[str, str, re.Match] | None:
        """(source, the whole line, the match) of the first blob (most recent first) in which `pattern` matches; blobs whose source is in `exclude` are skipped."""
        rx = re.compile(pattern, flags) if isinstance(pattern, str) else pattern
        for source, text in self.blobs:
            if source in exclude:
                continue
            # the last match in a blob is the one the run ended on
            found = None
            for m in rx.finditer(text):
                found = m
            if found is not None:
                return source, _line_of(text, found), found
        return None

    def find_recorded_first(self, pattern: re.Pattern | str, *, flags: int = 0) -> tuple[str, str, re.Match] | None:
        """Like `find`, but the lines the harness itself recorded as the failure (`error_chain`, `baseline.evidence`) are searched before the attempts' output: when
        both show the cause, the quoted line is the one the record names as the blocker, not a later symptom (a candidate that installed `docker.io` met
        `Cannot connect to the Docker daemon`; the recorded blocker is `docker: not found`)."""
        rx = re.compile(pattern, flags) if isinstance(pattern, str) else pattern
        ordered = ([b for b in self.blobs if b[0].startswith(("error_chain", "baseline"))] + [b for b in self.blobs if not b[0].startswith(("error_chain", "baseline"))])
        for source, text in ordered:
            found = None
            for m in rx.finditer(text):
                found = m
            if found is not None:
                return source, _line_of(text, found), found
        return None

    def find_recorded_only(self, pattern: re.Pattern | str, *, flags: int = 0) -> tuple[str, str, re.Match] | None:
        """Like `find`, but ONLY the lines the harness recorded as the failure (`error_chain`, `baseline.evidence`): an old attempt's output may show a line the run has
        since moved past (independent review, finding 4)."""
        rx = re.compile(pattern, flags) if isinstance(pattern, str) else pattern
        for source, text in self.blobs:
            if not source.startswith(("error_chain", "baseline")):
                continue
            found = None
            for m in rx.finditer(text):
                found = m
            if found is not None:
                return source, _line_of(text, found), found
        return None

    def find_final(self, pattern: re.Pattern | str, *, flags: int = 0) -> tuple[str, str, re.Match] | None:
        """Like `find`, but ONLY in the run's FINAL state: the last link of the error chain and the output of the last attempt that ran something (or, when no attempt ran,
        the baseline's evidence). A rule that says "RERUN already fixed X" must not quote a line from an earlier attempt as if the run still ended on it (harness-v1.8, DEV
        re-run of TEST-B #3 video_prediction: the git:// failure was gone after RERUN's rewrite; the run ended on a different build error, and the diagnosis still said
        "change git:// to https://")."""
        rx = re.compile(pattern, flags) if isinstance(pattern, str) else pattern
        last_attempt = max((i for i, a in enumerate(self.attempts) if (a or {}).get("stderr_tail") or (a or {}).get("stdout_tail")), default=None)
        wanted = {f"error_chain[{len(self.chain) - 1}].error"} if self.chain else set()
        if last_attempt is not None:
            wanted |= {f"attempts[{last_attempt}].stderr_tail", f"attempts[{last_attempt}].stdout_tail"}
        else:
            wanted.add("baseline.evidence")
        for source, text in self.blobs:
            if source not in wanted:
                continue
            found = None
            for m in rx.finditer(text):
                found = m
            if found is not None:
                return source, _line_of(text, found), found
        return None

    def find_after(self, index: int, pattern: re.Pattern | str, *, flags: int = 0) -> tuple[str, str, re.Match] | None:
        """Like `find`, but only in the output of attempts AFTER attempt number `index` (a position in the attempts list): what a step's effect looked like in the runs
        that followed it."""
        rx = re.compile(pattern, flags) if isinstance(pattern, str) else pattern
        for source, text in self.blobs:
            m = re.match(r"attempts\[(\d+)\]\.", source)
            if not m or int(m.group(1)) <= index:
                continue
            found = None
            for hit in rx.finditer(text):
                found = hit
            if found is not None:
                return source, _line_of(text, found), found
        return None

    def rule_action_index(self, rule: str, *, key: str | None = None, contains: str | None = None) -> int | None:
        """The position of the LAST attempt whose `time_machine_action` is of `rule` (and whose `key` list holds `contains`, when asked), else None."""
        found = None
        for i, a in enumerate(self.attempts):
            act = (a or {}).get("time_machine_action") or {}
            if act.get("rule") == rule and (key is None or contains in (act.get(key) or ())):
                found = i
        return found

    def has_rule_action(self, *rules: str) -> bool:
        """Did a RERUN deterministic step of one of these rules run in this record (`time_machine_action.rule`)?"""
        return any(((a or {}).get("time_machine_action") or {}).get("rule") in rules for a in self.attempts)

    def text_blobs(self, source_prefix: str) -> list[str]:
        return [t for s, t in self.blobs if s.startswith(source_prefix)]

    def last_link(self) -> dict | None:
        return self.chain[-1] if self.chain else None

    def attempt_texts(self) -> str:
        """Everything the attempts proposed, as text (patches and reasons), for the rules that need to know a tool was named."""
        out = []
        for a in self.attempts:
            for key in ("diff_text", "model_patch"):
                if a.get(key):
                    out.append(str(a[key]))
        return "\n".join(out)

    def gate_text(self) -> str:
        return "\n".join(str((a or {}).get("gate_violations") or "") for a in self.attempts)

    def env_changes(self) -> list[tuple[int, dict]]:
        out = []
        for i, a in enumerate(self.attempts):
            d = (a or {}).get("env_delta")
            if isinstance(d, str):
                try:
                    d = ast.literal_eval(d)
                except (ValueError, SyntaxError):
                    d = []
            for c in d or []:
                if isinstance(c, dict):
                    out.append((i, c))
        return out


def _line_of(text: str, m: re.Match) -> str:
    start = text.rfind("\n", 0, m.start()) + 1
    end = text.find("\n", m.end())
    return text[start: end if end != -1 else len(text)].strip()[:LINE_MAX]


def _b(source: str, quote: str) -> dict:
    return {"source": source, "quote": quote[:LINE_MAX]}


# ----------------------------------------------------------------------------------------------------------------------------------- rules

_DOCKER = re.compile(r"(?:docker: (?:command )?not found|Cannot connect to the Docker daemon|permission denied while trying to connect to the Docker daemon)")


def _docker(ctx: _Ctx) -> Finding | None:
    hit = ctx.find_recorded_only(_DOCKER)
    if not hit:
        return None
    source, line, _ = hit
    script = re.match(r"^(\S+\.sh): \d+:", line)
    where = f"the documented command's script `{script.group(1)}`" if script else "the documented command"
    return Finding(
        "DOCKER_REQUIRED", PLATFORM,
        f"a machine with Docker: {where} runs `docker`, and this sandbox has no Docker client and no daemon to connect to",
        "run the documented command on a host with Docker installed, or run the steps the script performs without the container",
        line, (_b(source, line),), family="Resources")


_CONDA = re.compile(r"(?:^|[\s:])conda: (?:command )?not found")
_NOT_ON_PYPI = re.compile(r"Could not find a version that satisfies the requirement ([\w.\-]+) \(from versions: none\)")


def _conda(ctx: _Ctx) -> Finding | None:
    hit = ctx.find_recorded_only(_CONDA)
    if not hit:
        return None
    source, line, _ = hit
    pkg = ctx.find(_NOT_ON_PYPI)
    name = pkg[2].group(1) if pkg else None
    basis = [_b(source, line)] + ([_b(pkg[0], pkg[1])] if pkg else [])
    extra = f", and `{name}` has no distribution on PyPI (pip lists no versions for it), so pip cannot stand in for conda" if name else ""
    return Finding(
        "CONDA_REQUIRED", HUMAN,
        f"a conda environment: the documented command calls `conda`, which this sandbox does not have{extra}",
        "create the conda environment the authors describe (their install script or environment file) outside the sandbox, or install "
        + (f"`{name}` " if name else "the package ") + "from the channel the authors name",
        line, tuple(basis), family="Environment")


_UNRECOGNIZED = re.compile(r"^(?P<prog>\S+): error: unrecognized arguments: (?P<args>.+)$", re.M)
_USAGE_OPT = re.compile(r"\[(--?[\w][\w-]*)")


def _argparse_rejected(ctx: _Ctx) -> Finding | None:
    link = ctx.last_link()
    if link is None or not re.search(r"^SystemExit|unrecognized arguments", strip_ansi(link.get("error"))):
        return None  # the run did not end on the rejection (review, finding 4)
    hit = ctx.find(_UNRECOGNIZED)
    if not hit:
        return None
    source, line, m = hit
    blob = next(t for s, t in ctx.blobs if s == source)
    options = list(dict.fromkeys(_USAGE_OPT.findall(blob)))
    rejected = [tok for tok in m.group("args").split() if tok.startswith("-")]
    near = {tok: (difflib.get_close_matches(tok, options, n=1, cutoff=0.6) or [None])[0] for tok in rejected}
    pairs = [(tok, o) for tok, o in near.items() if o]
    if pairs:
        tok, opt = pairs[0]
        detail = f"the script (`{m.group('prog')}`) defines `{opt}`, not `{tok}`"
        action = f"correct the command in the README to use `{opt}` instead of `{tok}`, or add `{tok}` as an alias in the script's argument parser"
    else:
        detail = f"the script (`{m.group('prog')}`) does not define {', '.join(f'`{t}`' for t in rejected) or 'those arguments'}"
        action = "correct the command in the README to the options the script's `--help` lists"
    return Finding(
        "DOCUMENTED_COMMAND_REJECTED", HUMAN,
        f"a command its own argument parser accepts: the documented command was refused (`{line}`); {detail}",
        action, line, (_b(source, line),), family="Documentation")


_NLTK_RESOURCE = re.compile(r"Resource (\S+?) not found\.?")
# NLTK data packages whose downloadable package is not the data (checked 2026-10-07 against the NLTK downloader index,
# https://raw.githubusercontent.com/nltk/nltk_data/gh-pages/index.xml: `ptb` is "a stub for the full Penn Treebank Corpus version 3", 6 KB).
_NLTK_STUBS = {"ptb": "the Penn Treebank (Linguistic Data Consortium, licensed)"}


def _nltk(ctx: _Ctx) -> Finding | None:
    hit = ctx.find_recorded_only(_NLTK_RESOURCE)
    if not hit:
        return None
    raw_nltk = any("\x1b[93m" in (a.get("stderr_tail") or "") for a in ctx.attempts) or any("\x1b[93m" in (l.get("error") or "") for l in ctx.chain)
    if not (raw_nltk or "nltk" in ctx.attempt_texts().lower() or "NLTK" in "\n".join(t for _, t in ctx.blobs)):
        return None  # "Resource X not found" is NLTK's wording; without any sign of NLTK it is some other library's
    source, line, m = hit
    name = m.group(1)
    if name in _NLTK_STUBS:
        return Finding(
            "NLTK_RESOURCE_LICENSED", HUMAN,
            f"NLTK data resource `{name}`, which is {_NLTK_STUBS[name]}: NLTK's downloadable `{name}` package is only a stub for it, so a download cannot supply it",
            f"obtain the licensed corpus and place it under `nltk_data/corpora/{name}`, or use the data files the repository ships, if it ships any",
            line, (_b(source, line),), family="Data")
    return Finding(
        "NLTK_RESOURCE_MISSING", HUMAN,
        f"NLTK data resource `{name}`, which is downloaded separately from the pip package",
        f"run `python -m nltk.downloader {name}` in the environment before the command (or point `NLTK_DATA` at a folder that holds it)",
        line, (_b(source, line),), family="Data")


_MUJOCO = re.compile(r"You appear to be missing MuJoCo\.\s+We expected to find the file here: (\S+)")


def _mujoco(ctx: _Ctx) -> Finding | None:
    link = ctx.last_link()
    if link is None or not re.search(r"mujoco", strip_ansi(link.get("error")), re.IGNORECASE):
        return None  # the run did not end on mujoco_py (review, finding 4)
    hit = ctx.find(_MUJOCO)
    if not hit:
        return None
    source, line, m = hit
    where = m.group(1)
    ver = re.search(r"mujoco(\d+)", where)
    release = {"200": "2.0", "210": "2.1"}.get(ver.group(1), ver.group(1)) if ver else None
    first = next((l.strip() for l in next(t for s, t in ctx.blobs if s == source).splitlines() if "missing MuJoCo" in l), line)
    return Finding(
        "MUJOCO_LIBRARY_MISSING", HUMAN,
        f"the MuJoCo physics library{f' {release}' if release else ''}: mujoco-py provides only the Python bindings and expected the library at `{where}`",
        "install MuJoCo under `~/.mujoco`: mujoco-py 2.0.x expects `mujoco200`; mujoco-py 2.1.x expects `mujoco210`, the MuJoCo 2.1.0 binaries, "
        "which are free to download (https://github.com/deepmind/mujoco/releases/tag/2.1.0)",
        first[:LINE_MAX], (_b(source, first),), family="Environment")


# Modules that exist inside a host application's embedded Python. Only names that no common, unrelated PyPI project shares (review, finding 4: `maya` is a datetime library
# on PyPI and `mathutils` a standalone vector library, so neither is listed).
_EMBEDDED = {"bpy": "Blender", "bmesh": "Blender", "hou": "Houdini", "c4d": "Cinema 4D", "FreeCAD": "FreeCAD"}
_EMBEDDED_ERR = re.compile(r"module '(?P<mod>[\w]+)(?:\.[\w.]+)?' has no attribute|No module named '(?P<mod2>\w+)(?:\.[\w.]+)?'")


def _embedded_runtime(ctx: _Ctx) -> Finding | None:
    link = ctx.last_link()
    if not link or link.get("class") not in ("API_REMOVED", "DEP_MISSING", "RUNTIME_ERROR_OTHER"):
        return None
    m = _EMBEDDED_ERR.search(strip_ansi(link.get("error")))
    mod = (m.group("mod") or m.group("mod2")) if m else None
    used = None
    if mod not in _EMBEDDED:
        # harness-v1.8 (DEV re-run of osm-heatmap, 2026-10-07): the run ended on `'NoneType' object has no attribute 'objects'`, the stand-in for `bpy.data` being None; the module
        # is named in the traceback's own source line (`camera = bpy.data.cameras.new(...)`) in the run's final output, not in the error. Only a NoneType error, and only a source
        # line of the final state, so a mention elsewhere in the record does not count.
        if "NoneType" not in strip_ansi(link.get("error")):
            return None
        used = ctx.find_final(r"\b(?P<mod>bpy|bmesh|hou|c4d|FreeCAD)\.[A-Za-z_]\w*")
        if used is None:
            return None
        mod = used[2].group("mod")
    app = _EMBEDDED[mod]
    line = strip_ansi(link["error"])[:LINE_MAX]
    stand_in = ctx.find(r"'<' not supported between instances of 'NoneType' and 'tuple'")
    note = f" (here `{mod}.app.version` is None, which is what the stand-in reports)" if stand_in and mod == "bpy" else ""
    if used is not None:
        note = f" (the run's own traceback line `{used[1][:80]}` reaches `{mod}` through a stand-in that returns None)"
    basis = [_b(f"error_chain[{len(ctx.chain) - 1}].error", line)] + ([_b(stand_in[0], stand_in[1])] if stand_in and mod == "bpy" and used is None else []) + ([_b(used[0], used[1])] if used else [])
    return Finding(
        "EMBEDDED_RUNTIME_REQUIRED", HUMAN,
        f"{app}: `{mod}` is {app}'s embedded Python API; the script has to run inside {app} of the release it targets, and a `{mod}` installed from PyPI is not necessarily that release (or any {app} at all){note}",
        (f"run the script with Blender, for example `blender --background --python <script>.py`, using a Blender release the script supports" if app == "Blender"
         else f"run the script inside {app}, as the authors do"),
        line, tuple(basis), family="Environment")


_MAIN_AS_FILE = re.compile(r"^python3?(?:\.\d+)?\s+(?:-u\s+)?(?P<pkg>\w+)/__main__\.py\b")


def _package_main_as_file(ctx: _Ctx) -> Finding | None:
    """harness-v1.8 (DEV re-run of the out-of-sample steamctl, D-50): the command runs a package's `__main__.py` as a FILE (`python steamctl/__main__.py`), so Python puts the package's own
    directory first on the path and `import steamctl` fails with `No module named 'steamctl'`. The class default said "the exact release of steamctl the authors used", which is not the
    problem. Only when the command in the record is exactly that form and the missing module is that package."""
    link = ctx.last_link()
    if not link:
        return None
    missing = re.search(r"No module named '(?P<name>\w+)(?:\.[\w.]+)?'", strip_ansi(link.get("error")))
    command = str(((ctx.record.get("baseline") or {}).get("execute_command")) or "").strip()
    shape = _MAIN_AS_FILE.match(command)
    if not missing or not shape or shape.group("pkg") != missing.group("name"):
        return None
    pkg, line = shape.group("pkg"), strip_ansi(link["error"])[:LINE_MAX]
    return Finding(
        "PACKAGE_MAIN_RUN_AS_FILE", HUMAN,
        f"a command that runs the package as a module: the command that was run, `{command}`, runs `{pkg}/__main__.py` as a script, which puts `{pkg}/` itself first on the path, so `{pkg}` is not importable from it",
        f"run `python -m {pkg}` from the repository root instead of `{command}` (and correct the command in the README the same way)",
        line, (_b(f"error_chain[{len(ctx.chain) - 1}].error", line), _b("baseline.execute_command", command)), family="Documentation")


_DOTTED_MODULE = re.compile(r"No module named '(?P<top>\w+)\.(?P<rest>[\w.]+)'")
_OWN_MODULE = re.compile(r"repository\\?'s own module \\?'(\w+)\\?'")


def _repo_extension(ctx: _Ctx) -> Finding | None:
    link = ctx.last_link()
    if not link or link.get("class") != "DEP_MISSING":
        return None
    m = _DOTTED_MODULE.search(strip_ansi(link.get("error")))
    if not m:
        return None
    top, rest = m.group("top"), m.group("rest")
    own = {x for x in _OWN_MODULE.findall(ctx.gate_text())}
    if top not in own:
        return None
    line = strip_ansi(link["error"])[:LINE_MAX]
    clause = re.search(r"'?\w+'? matches the repository\\?'s own module \\?'" + re.escape(top) + r"\\?'", ctx.gate_text())
    gate_line = clause.group(0) if clause else f"the repository's own module '{top}'"  # the gate's own words, as the record stores them
    return Finding(
        "REPO_EXTENSION_NOT_BUILT", HUMAN,
        f"`{top}.{rest}`: `{top}` is the repository's own package, and `{top}.{rest}` is not in its tree: it is a module the repository builds itself "
        f"(the gate refused to install an unrelated PyPI package named `{top}`)",
        f"run the repository's own build step for `{top}.{rest}` (look for a build script in `{top}/`, a `setup.sh` or Makefile, or "
        f"`python setup.py build_ext --inplace` in its README) before the command",
        line, (_b(f"error_chain[{len(ctx.chain) - 1}].error", line), _b("attempts[*].gate_violations", gate_line)), family="Environment")


# review, finding 4: a `metadata-generation-failed` / `legacy-install-failure` is a REAL package failing to build (a missing header, a compiler), not evidence that the
# module is vendored; only a SyntaxError in the PyPI project's own source, or "no distribution", is.
_BAD_INSTALL = re.compile(r"(SyntaxError|Could not find a version that satisfies|No matching distribution)")
_NO_MODULE = re.compile(r"No module named '([\w]+)'")


def _vendored_module(ctx: _Ctx) -> Finding | None:
    link = ctx.last_link()
    if not link or link.get("class") != "DEP_MISSING":
        return None
    m = _NO_MODULE.search(strip_ansi(link.get("error")))
    if not m:
        return None
    mod = m.group(1)
    tries = [(i, c) for i, c in ctx.env_changes() if str(c.get("package") or "").lower() == mod.lower() and c.get("op") in ("add", "pin")]
    if not tries:
        return None
    failed = []
    for i, c in tries:
        tail = strip_ansi((ctx.attempts[i] or {}).get("stderr_tail"))
        bad = _BAD_INSTALL.search(tail)
        if bad and system_packages.need_in(tail) is None:
            failed.append((i, c, bad.group(1), tail))
    if not failed:
        return None
    i, c, kind, tail = failed[-1]
    sig = next((l.strip() for l in tail.splitlines() if kind in l), kind)
    line = strip_ansi(link["error"])[:LINE_MAX]
    versions = sorted({str(c2.get("version")) for _, c2, _, _ in failed if c2.get("version")})
    ver = f" ({', '.join(versions)})" if versions else ""
    basis = (_b(f"error_chain[{len(ctx.chain) - 1}].error", line), _b(f"attempts[{i}].stderr_tail", sig[:LINE_MAX]))
    not_in_tree = f"the module `{mod}`, which the code imports although the repository does not contain it (the gate admitted `add {mod}`, so no file or package of that name is in the tree)"
    if kind in ("Could not find a version that satisfies", "No matching distribution"):
        # pip says the index has no release under that name at all: the dependency is distributed some other way
        return Finding(
            "MODULE_NOT_ON_PYPI", HUMAN,
            f"{not_in_tree}, and PyPI has no installable release under that name ({sig[:120]}): it is distributed some other way, or has to be supplied",
            f"install `{mod}` from where the authors publish it (their README or setup instructions name the source, often a git URL), or supply `{mod}` from the project this code was derived from",
            line, basis, family="Dependencies")
    return Finding(
        "VENDORED_MODULE_MISSING", HUMAN,
        f"{not_in_tree}, and the PyPI project of that name{ver} did not install ({sig[:120]}): it is a different, unrelated or unbuildable package, not what the code means",
        f"supply `{mod}` (a `{mod}.py` or a `{mod}/` package) from the project this code was derived from and put it where the importing file can see it; "
        f"do not pip-install the PyPI name `{mod}`",
        line, basis, family="Code")


_GIT_FAIL = re.compile(r"fatal: unable to connect to github\.com")


def _git_protocol(ctx: _Ctx) -> Finding | None:
    rewrote = ctx.has_rule_action("git_protocol_rewrite")
    # when RERUN already rewrote the line in this run, the clone failure has to be what the run ENDS on; an earlier attempt's line says only what it was before the rewrite
    last = ctx.last_link() or {}
    hit = (ctx.find_final(_GIT_FAIL) if last.get("class") == "DEP_BUILD_FAILED" else None) if rewrote else ctx.find(_GIT_FAIL)
    if not hit:
        return None
    if rewrote:
        source, line, _ = hit
        return Finding(
            "GIT_CLONE_STILL_FAILS", HUMAN,
            "a source that can be cloned from here: RERUN rewrote the `git://` requirement to `https://` and installed `git`, and the clone still fails, so the repository named is "
            "not reachable from the sandbox (private, moved or deleted)",
            "check that the repository in the requirements line still exists and is public, or give pip another place to get it from (a released package, a local copy)",
            line, (_b(source, line),), family="Dependencies")
    if not any("git://github.com/" in t for _, t in ctx.blobs) and "git://github.com/" not in ctx.attempt_texts():
        return None
    source, line, _ = hit
    clone = next((l.strip() for _, t in ctx.blobs for l in t.splitlines() if "git://github.com/" in l), None)
    basis = [_b(source, line)] + ([_b("attempts[*].stderr_tail", clone)] if clone else [])
    return Finding(
        "GIT_PROTOCOL_RETIRED", DETERMINISTIC,
        "the requirement written with `https://` instead of `git://`: GitHub switched off the unauthenticated git:// protocol in March 2022, so a "
        "`git+git://github.com/...` line cannot be cloned (RERUN's harness-v1.8 rewrites it in its own copy and installs `git`)",
        "change `git+git://github.com/` to `git+https://github.com/` in the requirements file (and install `git`, which pip needs for a `git+` requirement)",
        line, tuple(basis), family="Dependencies")


def _step_state(ctx: _Ctx, index: int) -> str:
    """What the run after RERUN's deterministic step at attempt `index` looked like: "stopped" (the step's own run did not finish: the spend cap stopped it, nothing was
    observed), "observed" (its re-execution ran and `stderr_tail` / `stdout_tail` hold what that run printed, AFTER the step), or "unknown" (no output recorded)."""
    a = ctx.attempts[index] or {}
    action = a.get("time_machine_action") or {}
    tail = (a.get("stderr_tail") or "").lstrip()
    if action.get("stopped") or tail.startswith("stopped before completion"):
        return "stopped"
    return "observed" if (a.get("stderr_tail") or a.get("stdout_tail")) else "unknown"


def _system_need(ctx: _Ctx) -> Finding | None:
    link = ctx.last_link()
    if not link or link.get("class") not in ("SYS_LIB_MISSING", "DEP_BUILD_FAILED"):
        return None
    need = system_packages.need_in(strip_ansi(link.get("error")))
    source = f"error_chain[{len(ctx.chain) - 1}].error"
    if need is None:
        hit = ctx.find(r"(fatal error: [\w./+-]+: No such file or directory|Command '\['which', '[\w+.-]+'\]' returned non-zero exit status|command '[\w+.-]+' failed: No such file or directory)",
                       exclude=("full_log",))  # the log's narration lines are not the run's output
        if hit:
            need = system_packages.need_in(hit[1])
            source = hit[0]
    if need is None:
        return None
    pkg = need.packages[0]
    what = f"`{need.item}`" + (" (the C/C++ compiler)" if need.kind == "compiler" else "")
    added_at = max((i for i, a in enumerate(ctx.attempts) if pkg in ((a or {}).get("time_machine_action") or {}).get("apt_added", ())), default=None)
    if added_at is not None:
        # RERUN's own apt step already added this package in this run. What may be said depends on what the run AFTER the step showed (harness-v1.8, DEV re-run of TEST #13
        # neo_gnns and #19 RBP: the operation after the apt step was stopped by the spend cap, nothing was observed, and the diagnosis claimed the step had failed):
        state = _step_state(ctx, added_at)
        if state == "stopped" or state == "unknown":
            return Finding(
                "SYSTEM_PACKAGE_ADDED_UNTESTED", DETERMINISTIC,
                f"nothing yet: RERUN's apt step added `{pkg}` for {what}, and the run after the step did not finish, so the record does not show whether that was enough",
                f"run the documented command again with `{pkg}` installed (`apt-get install -y {pkg}`); if the record ends on a spend cap, with a larger per-entry budget",
                need.evidence[:LINE_MAX], (_b(source, need.evidence), _b(f"attempts[{added_at}].time_machine_action.apt_added", pkg)), family="Environment")
        step_out = ctx.attempts[added_at] or {}
        own = system_packages.need_in(strip_ansi(step_out.get("stderr_tail") or "") + "\n" + strip_ansi(step_out.get("stdout_tail") or ""))
        if own is None or own.item != need.item:
            return None  # the run after the step no longer shows the need: it worked, and the run ended on something else, which the other rules (or the class) describe
        need, source = own, f"attempts[{added_at}].stderr_tail"
        return Finding(
            "SYSTEM_PACKAGE_DID_NOT_HELP", HUMAN,
            f"another system package: RERUN's apt step installed `{pkg}` for {what} and the run after it still ends on the same error, so `{pkg}` does not provide it here",
            f"find the system package that ships {what} for this Debian release (`apt-file search` or the package's own build documentation) and install it before the build",
            need.evidence[:LINE_MAX], (_b(source, need.evidence),), family="Environment")
    provides = f"the system package `{pkg}` is missing" if pkg == need.item else f"the system package `{pkg}` provides {what}"
    return Finding(
        "SYSTEM_PACKAGE_MISSING", DETERMINISTIC,
        f"nothing: {provides}; RERUN's harness-v1.8 apt rule installs it",
        f"install `{pkg}` with apt before the build (`apt-get install -y {pkg}`)",
        need.evidence[:LINE_MAX], (_b(source, need.evidence),), family="Environment")


_PRERELEASE = re.compile(r"Could not find a version that satisfies the requirement ([\w.\-]+)==(\d+(?:\.\d+)*)((?:a|b|rc|\.dev)\d*)")


def _prerelease_pin(ctx: _Ctx) -> Finding | None:
    # when RERUN's own rule already replaced the pin in this run, the line is old news unless the run still ends on it (DEV re-run of ovis: the relaxed pin moved the error to
    # ResolutionImpossible, and the diagnosis kept telling the reader to pin the final release RERUN had pinned)
    hit = ctx.find_final(_PRERELEASE) if ctx.has_rule_action("prerelease_pin_relax") else ctx.find(_PRERELEASE)
    if not hit:
        return None
    source, line, m = hit
    pkg, final, suffix = m.group(1), m.group(2), m.group(3)
    if pkg.lower() not in ("torch", "torchvision", "torchaudio"):
        # RERUN's rule (prerelease_pin) covers the runner's own torch family only; for any other package this is a statement about the pin, not about a rule
        return Finding(
            "PRERELEASE_PIN_UNAVAILABLE", HUMAN,
            f"the pin `{pkg}=={final}{suffix}` names a pre-release that pip does not find on the index; its final release is `{final}`",
            f"pin `{pkg}=={final}` (the final release of the pre-release the repository names) or install the pre-release from where its authors publish it",
            line[:LINE_MAX], (_b(source, line),), family="Dependencies")
    return Finding(
        "PRERELEASE_PIN_UNAVAILABLE", DETERMINISTIC,
        f"nothing: the pin `{pkg}=={final}{suffix}` names a pre-release that was never published to the index; its final release is `{final}`, which RERUN's "
        f"harness-v1.8 rule pins instead (labelled a dependency change)",
        f"pin `{pkg}=={final}` (the final release of the pre-release the repository names)",
        line[:LINE_MAX], (_b(source, line),), family="Dependencies")


_APT_RULES = ("missing_compiler_build_essential", "missing_header_apt", "missing_tool_apt")
_BUILD_FAIL_LINE = re.compile(r"subprocess\.CalledProcessError: Command [^\n]*returned non-zero exit status \d+[^\n]*|error: command '[^'\n]+' failed[^\n]*|[^\n]*did not run successfully[^\n]*")


def _build_after_apt(ctx: _Ctx) -> Finding | None:
    """A source build that still fails in the run AFTER RERUN's apt step (DEV re-run of TEST-B #8 gandissect: `build-essential` was added, its run finished, and matplotlib's
    bundled freetype `./configure` then failed). The class default for DEP_BUILD_FAILED says "nothing, if the apt rule adds the build dependencies", which the record has just
    shown not to hold. Only when the step's own run was observed (a step stopped by the spend cap shows nothing) and the run's last recorded error is a build failure."""
    link = ctx.last_link()
    if not link or link.get("class") != "DEP_BUILD_FAILED":
        return None
    step = max((i for i, a in enumerate(ctx.attempts) if ((a or {}).get("time_machine_action") or {}).get("rule") in _APT_RULES), default=None)
    if step is None or _step_state(ctx, step) != "observed":
        return None
    error = strip_ansi(link.get("error") or "")
    line = next((m.group(0).strip() for m in [_BUILD_FAIL_LINE.search(error)] if m), "")
    added_items = {p for p in ((ctx.attempts[step] or {}).get("time_machine_action") or {}).get("apt_added", ())}
    need = system_packages.need_in(error)
    if not line or (need is not None and set(need.packages) & added_items):
        return None  # the error is the need the step supplied: _system_need speaks to that
    source = f"error_chain[{len(ctx.chain) - 1}].error"
    added = ", ".join(f"`{p}`" for p in sorted(added_items)) or "the system packages it names"
    return Finding(
        "BUILD_FAILS_AFTER_APT_STEP", HUMAN,
        f"the library or tool the build is looking for: RERUN's apt step installed {added} and the build still fails (`{line[:160]}`), so something else is missing; the build's "
        "own log above that line names it",
        "read the build log above the quoted line (for a `./configure` step, its `config.log`) for the library or tool it could not find, then install that package with apt before the build",
        line, (_b(source, line),), family="Environment")


_PINS_CONFLICT = re.compile(r"ERROR: Cannot install (?P<pkgs>[^\n]+?) because these package versions have conflicting dependencies")


def _pins_conflict(ctx: _Ctx) -> Finding | None:
    link = ctx.last_link()
    if not link or link.get("class") != "DEP_UNPINNED_CONFLICT":
        return None  # the run must END on a resolution conflict; a candidate's own failed install is not the run's blocker
    hit = ctx.find(_PINS_CONFLICT, exclude=("full_log",))
    if not hit:
        return None
    source, line, m = hit
    relaxed = next(((a or {}).get("time_machine_action") for a in ctx.attempts if ((a or {}).get("time_machine_action") or {}).get("rule") == "prerelease_pin_relax"), None)
    after = (f"; RERUN had pinned `{relaxed['package']}=={relaxed['to']}` for the pre-release the repository names and the set still does not install" if relaxed else "")
    return Finding(
        "PINS_CONFLICT", HUMAN,
        f"releases that can be installed together: pip found no way to install `{m.group('pkgs')[:200]}` side by side{after}; one of the pins has to move to the release made for the other",
        "pin the packages the quoted line names to releases that agree (each release's own `Requires-Dist` says which release of the other package it needs), then re-run",
        line, (_b(source, line),), family="Dependencies")


_INVALID_REQUIREMENT = re.compile(r"InvalidRequirement: (?P<why>[^\n]+)")


def _invalid_requirement(ctx: _Ctx) -> Finding | None:
    """A dependency's own setup.py lists a requirement string that current setuptools / packaging reject (DEV re-run of TEST-B #3 video_prediction: lpips-tensorflow's
    `install_requires` holds `python_version>"3.7"`). The offending string is the line after the exception in the same output."""
    link = ctx.last_link()
    wanted = ctx.find_final(_INVALID_REQUIREMENT) if link and link.get("class") == "DEP_BUILD_FAILED" else None
    if not wanted:
        return None
    source, line, m = wanted
    text = next((t for src, t in ctx.blobs if src == source), "")
    after = text[text.find(line) + len(line):] if line in text else ""
    offending = next((l.strip() for l in after.splitlines() if l.strip() and not set(l.strip()) <= {"^", "~", " "}), "")
    quoted = f" (`{offending[:100]}`)" if offending and len(offending) < 100 else ""
    basis = (_b(source, line),) + ((_b(source, offending),) if offending and offending in text else ())
    return Finding(
        "REQUIREMENT_STRING_INVALID", HUMAN,
        f"a dependency's own requirement list holds a string that current setuptools / packaging reject{quoted}; it is in the dependency's setup.py, not in the repository's files",
        "build that dependency with a setuptools from its own era (before requirement strings were parsed strictly), or install a release of it whose setup.py is valid",
        line, basis, family="Dependencies")


def _era_pair(ctx: _Ctx) -> Finding | None:
    link = ctx.last_link()
    if not link or link.get("class") != "API_REMOVED":
        return None
    m = re.search(r"module '(\w+)(?:\.[\w.]+)?' has no attribute", strip_ansi(link.get("error")))
    if not m:
        return None
    mod = m.group(1)
    names = {mod.lower(), "py" + mod.lower(), mod.lower().replace("_", "-"), dist_for_import(mod).lower()}
    pins = [(i, c) for i, c in ctx.env_changes()
            if c.get("op") in ("pin", "add") and c.get("version") and str(c.get("package") or "").lower().replace("_", "-") in {n.replace("_", "-") for n in names}]
    if not pins:
        return None
    i, c = pins[-1]
    tail = strip_ansi((ctx.attempts[i] or {}).get("stderr_tail"))
    if f"/{mod}/" not in tail.replace("\\", "/"):
        return None  # the follow-on error does not come out of that package's own files
    last = next((l.strip() for l in reversed(tail.splitlines()) if re.match(r"^[A-Za-z_][\w.]*(?:Error|Exception): ", l.strip())), "")
    if not last or last == strip_ansi(link["error"]).strip():
        return None
    pkg, ver = c["package"], c["version"]
    line = strip_ansi(link["error"])[:LINE_MAX]
    return Finding(
        "ERA_PAIR_MISMATCH", HUMAN,
        f"a matched set of versions: the newest `{pkg}` removed the name the code uses (`{line}`); pinning `{pkg}=={ver}` (attempt {ctx.attempts[i].get('attempt_number')}) "
        f"moved the error to `{last[:140]}`, which comes from `{mod}`'s own binding to the library it wraps, so `{pkg}` has to be pinned together with that library's release of the same era",
        f"pin `{pkg}` together with the release of the library it wraps that the authors' era had (the record shows `{pkg}=={ver}` alone is not enough), then re-run",
        line, (_b(f"error_chain[{len(ctx.chain) - 1}].error", line), _b(f"attempts[{i}].stderr_tail", last)), family="Dependencies")


# harness-v1.9 (D-73, TEST-C g-meta): the documented command itself carries a placeholder for the data (`--data_dir PATH/G-Meta_Data/arxiv/`), and the run
# ends on a missing file. The class default quoted the code's raise line ("expects at Features file not found in any of: {tried_paths}") and never named
# the placeholder. Placeholders: an upper-case PATH / DATA_DIR / DATASET_PATH / DATA_PATH / YOUR_... token (with what follows it up to a space),
# `/path/to/...`, or a bracketed name (`[model_path]`, `<data_dir>`). Only when the run's last link is DATA_MISSING.
_ERRNO_PATH = re.compile(r"(?:No such file or directory|FileNotFoundError)[^'\"]*['\"]([^'\"]+)['\"]")
_PLACEHOLDER = re.compile(r"(?<![\w/.$=-])(?:(?:PATH|DATA_?DIR|DATA_?PATH|DATASET_?PATH|DATA_?ROOT|YOUR_[A-Z_]+)(?:/[^\s'\"]*)?(?![\w=:])|/path/to/[^\s'\"]*|\[[A-Za-z][\w.-]*\](?!\w)|<[A-Za-z][\w.-]*>(?!\w))")


def _documented_placeholder(ctx: _Ctx) -> Finding | None:
    link = ctx.last_link()
    if not link or link.get("class") != "DATA_MISSING":
        return None
    command = str(((ctx.record.get("baseline") or {}).get("execute_command")) or "").strip()
    found = _PLACEHOLDER.search(command)
    if not found:
        return None
    token, line = found.group(0), strip_ansi(link.get("error"))[:LINE_MAX]
    # When the error names a real path that has nothing to do with the placeholder (DEV img-comp-reference: `original.png` is missing, the command also carries
    # `[model_path]`), the class default that names that path is the better sentence: the rule fires only when the error names no usable path, or the path it
    # names contains the placeholder.
    named = _ERRNO_PATH.search(line)
    path = named.group(1) if named else None
    if path and "{" not in path and not (re.search(r"\s", path) and "/" not in path) and token.strip("[]<>/") not in path:
        return None
    return Finding(
        "DOCUMENTED_PATH_PLACEHOLDER", HUMAN,
        f"the data the documented command points at with the placeholder `{token}`: the command was run as written, so the program looked for its input under a name "
        f"that only stands for the real location",
        f"replace `{token}` in the documented command with the location of the dataset the README describes (download it there first), then run the command again",
        line, (_b(f"error_chain[{len(ctx.chain) - 1}].error", line), _b("baseline.execute_command", command)))


RULES = (_docker, _conda, _argparse_rejected, _mujoco, _nltk, _embedded_runtime, _repo_extension, _package_main_as_file, _vendored_module, _git_protocol, _prerelease_pin, _system_need, _build_after_apt, _pins_conflict, _invalid_requirement, _era_pair,
         _documented_placeholder)


def diagnose(record: dict) -> Finding | None:
    """The first rule that matches the record's evidence, or None (the caller then says the diagnosis is the class default)."""
    ctx = _Ctx(record)
    for rule in RULES:
        found = rule(ctx)
        if found is not None:
            return found
    return None
