"""Environment-layer repair: structured edits to the BUILD PLAN, never to repo code.

Many real failures live in the environment, not the code (the 2026-09-24 live
runs: gpt-2's `regex==2017.4.5` needs gcc; TTPT imports Dassl, which is not on
PyPI). A code diff cannot fix those, so the repairer may also return an
`env_delta` — a list of structured changes:

    {"op": "pin",     "package": "regex", "version": "2023.12.25", ...}
    {"op": "unpin",   "package": "regex", ...}
    {"op": "add",     "package": "torch", "version": "2.3.1" | null, ...}
    {"op": "remove",  "package": "tensorflow-gpu", ...}
    {"op": "pip_git", "package": "dassl", "git_url": "https://github.com/o/r", "commit": "<40-hex sha>", ...}
    {"op": "apt",     "package": "build-essential", ...}
    {"op": "python",  "version": "3.8", ...}
    {"op": "pip_no_build_isolation", "package": "dassl", ...}

each with a one-line `justification` and an `evidence` string that must appear
verbatim in the failing run's log. `check_env_delta` is the deterministic env
gate (PURE, like tamper_gate): any violation rejects the whole delta.
`apply_env_delta` turns an approved delta into a new BuildPlan.
"""

from __future__ import annotations

import ast
import re
import shlex
from dataclasses import dataclass, replace
from pathlib import Path

from app.services import dep_scan
from app.services.planner import BuildPlan
from app.services.tamper_gate import Violation

OPS = ("pin", "unpin", "add", "remove", "pip_git", "apt", "python", "command", "pip_no_build_isolation")
MAX_CHANGES = 10
# 3.6–3.13 verified live (2026-09-24) to exist as python:X-slim sandbox images.
SUPPORTED_PYTHON_VERSIONS = ("3.6", "3.7", "3.8", "3.9", "3.10", "3.11", "3.12", "3.13")
MIN_EVIDENCE_CHARS = 8
REQUIREMENTS_OVERRIDE_FILE = ".rerun-requirements.txt"


class EnvRule:
    ENV_INVALID_CHANGE = "ENV_INVALID_CHANGE"  # malformed op / missing fields
    ENV_INVALID_NAME = "ENV_INVALID_NAME"  # pip/apt name or version fails validation
    ENV_REMOVES_IMPORTED = "ENV_REMOVES_IMPORTED"  # removes a package the code imports
    ENV_DATA_URL = "ENV_DATA_URL"  # any URL other than a pinned git source
    ENV_GIT_UNPINNED = "ENV_GIT_UNPINNED"  # git source not pinned to a full commit sha
    ENV_GIT_UNVERIFIED = "ENV_GIT_UNVERIFIED"  # url+commit not verified by RERUN's dep resolver
    ENV_UNJUSTIFIED = "ENV_UNJUSTIFIED"  # missing justification / evidence not in the log
    ENV_UNSUPPORTED = "ENV_UNSUPPORTED"  # e.g. unpin/remove without a requirements.txt
    ENV_TOO_LARGE = "ENV_TOO_LARGE"
    ENV_COMMAND_UNSAFE = "ENV_COMMAND_UNSAFE"  # new shell operators / substitutions
    ENV_COMMAND_PROGRAM_CHANGED = "ENV_COMMAND_PROGRAM_CHANGED"  # different program, script or positional args
    # Same rule name as the tamper gate's: the scale-reduction rule applies to
    # command changes too (fewer epochs/samples/steps via a flag).
    REDUCED_SCALE = "REDUCED_SCALE"
    # pip_no_build_isolation without the build-log evidence that justifies it.
    ENV_BUILD_ISOLATION_UNJUSTIFIED = "ENV_BUILD_ISOLATION_UNJUSTIFIED"
    # Re-proposes a change this run already applied and saw fail.
    ENV_REPEATS_FAILED_CHANGE = "ENV_REPEATS_FAILED_CHANGE"
    # Dependency-confusion guard (harness-v1.3.3, D-12): a package whose name matches a module inside the repository.
    ENV_SHADOWS_REPO_MODULE = "ENV_SHADOWS_REPO_MODULE"


def change_key(c: "EnvChange") -> tuple:
    """Normalized identity of an env change for the failed-move memory:
    what it does, not why (justification/evidence are ignored)."""
    return (
        c.op,
        _norm(c.package) if c.package else "",
        (c.version or "").strip(),
        (c.git_url or "").strip().rstrip("/").removesuffix(".git").lower(),
        (c.commit or "").strip().lower(),
        " ".join((c.command or "").split()),
    )


# PEP 508 distribution name.
_PIP_NAME_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?$")
# A plain version (PEP 440-ish, no operators, no spaces, no URLs).
_VERSION_RE = re.compile(r"^[0-9]+(?:\.[0-9]+)*(?:(?:a|b|rc|\.post|\.dev)[0-9]+)*(?:\+[A-Za-z0-9.]+)?$")
# Same rule planner.py applies to model-suggested apt names.
_APT_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9+.-]*$")
_GIT_URL_RE = re.compile(r"^https://(github\.com|gitlab\.com|bitbucket\.org)/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+?(\.git)?/?$")
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_URL_RE = re.compile(r"[a-z][a-z0-9+.-]*://|www\.", re.IGNORECASE)

# Distribution name -> import name, where they differ. Used only by the env
# gate's "never remove a package the code imports" check (the reverse
# direction of the harness-v1.1 import map, which is import -> distribution).
_DIST_TO_IMPORT = {
    "scikit-learn": "sklearn",
    "opencv-python": "cv2",
    "opencv-python-headless": "cv2",
    "pyyaml": "yaml",
    "pillow": "PIL",
    "beautifulsoup4": "bs4",
    "tensorflow-gpu": "tensorflow",
    "tensorflow-cpu": "tensorflow",
    "protobuf": "google",
}


@dataclass(frozen=True)
class EnvChange:
    op: str
    package: str | None = None
    version: str | None = None
    git_url: str | None = None
    commit: str | None = None
    justification: str = ""
    evidence: str = ""
    command: str | None = None

    def as_dict(self) -> dict:
        return {
            "command": self.command,
            "op": self.op,
            "package": self.package,
            "version": self.version,
            "git_url": self.git_url,
            "commit": self.commit,
            "justification": self.justification,
            "evidence": self.evidence,
        }


def parse_env_delta(raw) -> tuple[tuple[EnvChange, ...], tuple[Violation, ...]]:
    """Model JSON -> EnvChanges. Malformed entries are violations (never
    silently dropped): a half-understood delta must not be half-applied."""
    if raw in (None, [], {}):
        return (), ()
    if not isinstance(raw, list):
        return (), (Violation(rule=EnvRule.ENV_INVALID_CHANGE, reason="env_delta must be a list of changes"),)
    changes: list[EnvChange] = []
    violations: list[Violation] = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            violations.append(Violation(rule=EnvRule.ENV_INVALID_CHANGE, reason=f"env_delta[{i}] is not an object"))
            continue

        def _s(key):
            value = item.get(key)
            return None if value is None else str(value).strip()

        changes.append(
            EnvChange(
                op=_s("op") or "",
                package=_s("package"),
                version=_s("version"),
                git_url=_s("git_url"),
                commit=_s("commit"),
                justification=_s("justification") or "",
                evidence=_s("evidence") or "",
                command=_s("command"),
            )
        )
    return tuple(changes), tuple(violations)


def _norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def import_name_for(dist: str) -> str:
    return _DIST_TO_IMPORT.get(_norm(dist), _norm(dist).replace("-", "_"))


def imported_top_level_modules(repo_root: Path, max_files: int = 2000) -> frozenset[str]:
    """Top-level module names imported anywhere in the repo's own .py files
    (AST, never executed). Unparseable files are skipped."""
    from app.services.intake import _walk_real_files, read_text_capped

    names: set[str] = set()
    for i, path in enumerate(_walk_real_files(repo_root, ".py")):
        if i >= max_files:
            break
        text = read_text_capped(path)
        if text is None:
            continue
        try:
            tree = ast.parse(text)
        except (SyntaxError, ValueError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                names.add(node.module.split(".")[0])
    return frozenset(names)


# Signs that pip is running a package's build backend in an isolated build
# environment (the only place build isolation can hide a locked module).
_BUILD_BACKEND_RE = re.compile(
    r"Getting requirements to build (?:wheel|editable)|Preparing metadata \(pyproject\.toml\)"
    r"|pip-build-env-|build_meta\.py|_in_process\.py"
)
_NO_MODULE_RE = re.compile(r"No module named ['\"]([\w.]+)['\"]")
# How far back from an import error a build-backend frame may be (TTPT v5:
# 214 chars from the last `build_meta.py` frame to "No module named 'numpy'").
_BUILD_WINDOW = 2000
# pip's "Collecting dassl@ git+..." / "Collecting numpy==1.2 (from ...)".
_COLLECTING_RE = re.compile(r"^\s*Collecting ([A-Za-z0-9][A-Za-z0-9._-]*)", re.MULTILINE)


def _dists_for_module(module: str) -> set[str]:
    """Normalized distribution names that provide top-level `module`."""
    from app.services.import_names import dist_for_import

    top = module.split(".")[0]
    names = {_norm(top), _norm(dist_for_import(top))}
    names.update(dist for dist, imp in _DIST_TO_IMPORT.items() if imp == top)
    return names


def build_isolation_evidence(package: str, log_text: str, locked_requirements: tuple[str, ...]) -> str | None:
    """The locked module the package's isolated build backend failed to
    import, or None. Both must hold: pip collects `package` somewhere in the
    log, and a `No module named 'X'` sits inside a build-backend traceback
    (a build signature within the preceding _BUILD_WINDOW chars) with X's
    distribution in the lock. This is exactly the case --no-build-isolation
    fixes: the module IS installed, the isolated build env just can't see it
    (TTPT v5, dassl -> numpy). No cross-line ordering is assumed: the
    orchestrator's log is stderr then stdout, so pip's "Collecting" line
    (stdout) comes after the build traceback (stderr)."""
    found = build_isolation_match(package, log_text, locked_requirements)
    return found[0] if found else None


def build_isolation_match(
    package: str, log_text: str, locked_requirements: tuple[str, ...]
) -> tuple[str, str] | None:
    """(module, the verbatim log line it was named on) — the one
    implementation of the rule `build_isolation_evidence` documents, shared
    by the env gate and the deterministic time-machine step."""
    if not any(_norm(m.group(1)) == _norm(package) for m in _COLLECTING_RE.finditer(log_text)):
        return None
    locked = {name for name in (_requirement_name(line) for line in locked_requirements) if name}
    for match in _NO_MODULE_RE.finditer(log_text):
        window = log_text[max(0, match.start() - _BUILD_WINDOW) : match.start()]
        if _BUILD_BACKEND_RE.search(window) and _dists_for_module(match.group(1)) & locked:
            start = log_text.rfind("\n", 0, match.start()) + 1
            end = log_text.find("\n", match.end())
            return match.group(1), log_text[start : end if end != -1 else len(log_text)].strip()
    return None


def find_build_isolation_candidate(
    log_text: str, locked_requirements: tuple[str, ...], exclude: frozenset[str] = frozenset()
) -> tuple[str, str, str] | None:
    """The first package in the lock (lock order) for which the build-isolation
    rule holds: (package, module, evidence line). `exclude` holds normalized
    names already handled this run."""
    for line in locked_requirements:
        package = _requirement_name(line)
        if not package or package in exclude:
            continue
        found = build_isolation_match(package, log_text, locked_requirements)
        if found:
            return package, found[0], found[1]
    return None


def check_env_delta(
    changes: tuple[EnvChange, ...],
    *,
    log_text: str,
    imported_modules: frozenset[str],
    has_requirements_txt: bool,
    verified_git_sources: frozenset[tuple[str, str]] = frozenset(),
    current_command: str | None = None,
    locked_requirements: tuple[str, ...] | None = None,
    repo_internal_modules: frozenset[str] = frozenset(),
    apt_packages: frozenset[str] = frozenset(),
) -> tuple[Violation, ...]:
    """The deterministic env gate. Returns every violation (empty = PASS).

    `repo_internal_modules` (lower-cased, dep_scan.internal_module_names): an add/pin/pip_git of a package whose name
    matches one is refused — never install a PyPI package that shadows the repository's own module (D-12).
    `apt_packages`: the apt packages the plan already installs; `remove` of one of those edits the apt list.

    `verified_git_sources` holds (lowercased https URL, commit) pairs that
    dep_resolver resolved to a real commit this attempt. A pip_git change
    must match one exactly — a model-supplied URL or sha is never trusted.
    `locked_requirements` is the time machine's resolved lock as currently
    installed (None if no lock was resolved); pip_no_build_isolation is
    only allowed against it."""
    violations: list[Violation] = []

    def _v(rule, reason, i):
        violations.append(Violation(rule=rule, reason=f"env_delta[{i}]: {reason}"))

    if len(changes) > MAX_CHANGES:
        violations.append(
            Violation(rule=EnvRule.ENV_TOO_LARGE, reason=f"{len(changes)} env changes exceed the {MAX_CHANGES}-change ceiling")
        )
    imported_lower = {m.lower() for m in imported_modules}

    for i, c in enumerate(changes):
        if c.op not in OPS:
            _v(EnvRule.ENV_INVALID_CHANGE, f"unknown op '{c.op}' (allowed: {', '.join(OPS)})", i)
            continue

        # Justification tied to a real log line.
        if not c.justification or "\n" in c.justification or len(c.justification) > 300:
            _v(EnvRule.ENV_UNJUSTIFIED, "needs a one-line justification (≤300 chars)", i)
        evidence = (c.evidence or "").strip()
        if len(evidence) < MIN_EVIDENCE_CHARS or evidence not in log_text:
            _v(
                EnvRule.ENV_UNJUSTIFIED,
                f"evidence {evidence[:80]!r} does not appear verbatim in the failing run's log",
                i,
            )

        # No URLs anywhere except a git source's git_url.
        for field_name in ("package", "version", "commit"):
            value = getattr(c, field_name)
            if value and _URL_RE.search(value):
                _v(EnvRule.ENV_DATA_URL, f"{field_name} contains a URL ({value[:80]!r}) — only pinned git sources may", i)
        if c.git_url and c.op != "pip_git":
            _v(EnvRule.ENV_DATA_URL, f"git_url is only allowed for op 'pip_git' (got op '{c.op}')", i)

        if c.op == "command":
            if not c.command or not current_command:
                _v(EnvRule.ENV_INVALID_CHANGE, "command change needs a new command and a current command", i)
            else:
                for rule, reason in check_command_change(current_command, c.command):
                    _v(rule, reason, i)
            continue

        if c.op == "python":
            if c.version not in SUPPORTED_PYTHON_VERSIONS:
                _v(EnvRule.ENV_INVALID_NAME, f"python version {c.version!r} not in {SUPPORTED_PYTHON_VERSIONS}", i)
            continue

        if c.op == "apt":
            if not c.package or not _APT_NAME_RE.match(c.package):
                _v(EnvRule.ENV_INVALID_NAME, f"invalid apt package name {c.package!r}", i)
            continue

        if not c.package or not _PIP_NAME_RE.match(c.package):
            _v(EnvRule.ENV_INVALID_NAME, f"invalid pip package name {c.package!r}", i)
            continue

        if c.op == "pip_no_build_isolation":
            # Build the named package without pip's isolated build env — only
            # when its build backend demonstrably failed to import a module
            # the lock already installs. Nothing else about the package changes.
            if c.version:
                _v(EnvRule.ENV_INVALID_CHANGE, "pip_no_build_isolation takes no version (the lock's spec is kept)", i)
            if locked_requirements is None:
                _v(EnvRule.ENV_UNSUPPORTED, "pip_no_build_isolation needs a resolved lock (the time machine did not produce one)", i)
                continue
            if not any(_requirement_name(line) == _norm(c.package) for line in locked_requirements):
                _v(EnvRule.ENV_UNSUPPORTED, f"'{c.package}' is not in the environment being installed", i)
                continue
            if build_isolation_evidence(c.package, log_text, locked_requirements) is None:
                _v(
                    EnvRule.ENV_BUILD_ISOLATION_UNJUSTIFIED,
                    f"the log does not show '{c.package}''s build backend failing to import a module present in the lock",
                    i,
                )
            continue

        if c.op in ("pin",) and not c.version:
            _v(EnvRule.ENV_INVALID_CHANGE, "pin needs a version", i)
        if c.version and not _VERSION_RE.match(c.version):
            _v(EnvRule.ENV_INVALID_NAME, f"invalid version {c.version!r} (plain version only, no operators)", i)

        if c.op == "pip_git":
            if not c.git_url or not _GIT_URL_RE.match(c.git_url):
                _v(
                    EnvRule.ENV_DATA_URL,
                    f"git_url {c.git_url!r} must be an https URL to a github.com/gitlab.com/bitbucket.org repo",
                    i,
                )
            if not c.commit or not _SHA_RE.match(c.commit):
                _v(EnvRule.ENV_GIT_UNPINNED, f"git source must be pinned to a full 40-hex commit sha (got {c.commit!r})", i)
            elif c.git_url and (c.git_url.rstrip("/").removesuffix(".git").lower(), c.commit) not in verified_git_sources:
                _v(
                    EnvRule.ENV_GIT_UNVERIFIED,
                    f"{c.git_url}@{c.commit} was not verified by RERUN's dependency resolver this attempt",
                    i,
                )

        if c.op in ("pin", "add", "pip_git"):
            shadowed = dep_scan.shadows_repo_module(c.package, repo_internal_modules)
            if shadowed:
                _v(
                    EnvRule.ENV_SHADOWS_REPO_MODULE,
                    f"'{c.package}' matches the repository's own module '{shadowed}'; installing an unrelated PyPI package "
                    "under that name would shadow or be confused with it (missing repo-internal modules need the repo's "
                    "own build step, not pip)",
                    i,
                )

        if c.op == "remove" and c.package.lower() in apt_packages:
            continue  # an apt package this plan installs: handled by apply_env_delta (edits the apt list)

        if c.op in ("unpin", "remove") and not has_requirements_txt:
            _v(EnvRule.ENV_UNSUPPORTED, f"'{c.op}' needs a requirements.txt to edit", i)

        if c.op == "remove" and import_name_for(c.package).lower() in imported_lower:
            _v(
                EnvRule.ENV_REMOVES_IMPORTED,
                f"cannot remove '{c.package}': the repository's code imports '{import_name_for(c.package)}'",
                i,
            )
    return tuple(violations)


# Flags whose numeric value sets how much work a run does. Reuses the tamper
# gate's keywords plus common CLI spellings.
_SCALE_FLAG_WORDS = {
    "epoch", "epochs", "num_epochs", "n_epochs", "sample", "samples", "num_samples", "n_samples", "nsamples",
    "dataset_size", "subset_size", "max_steps", "num_steps", "steps", "train_steps", "total_steps", "train_size",
    "limit", "iters", "iterations", "num_iters", "n_iters", "max_iter", "max_iters", "length", "n", "num",
}
_UNSAFE_TOKENS = {";", "|", "||", "&", ">", ">>", "<", "<<", "`"}


def _command_tokens(command: str) -> list[str]:
    lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|<>")
    lexer.whitespace_split = True
    return list(lexer)


def _segments(tokens: list[str]) -> list[list[str]]:
    segments, current = [], []
    for tok in tokens:
        if tok == "&&":
            segments.append(current)
            current = []
        else:
            current.append(tok)
    segments.append(current)
    return segments


def _split_segment(tokens: list[str]) -> tuple[list[str], dict[str, str | None]]:
    """(positional tokens incl. the program, {normalized flag: value})."""
    positional, flags = [], {}
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok.startswith("-") and len(tok) > 1 and not re.fullmatch(r"-?\d+(\.\d+)?", tok):
            name, eq, value = tok.lstrip("-").partition("=")
            key = name.replace("-", "_").lower()
            if eq:
                flags[key] = value
            elif i + 1 < len(tokens) and not tokens[i + 1].startswith("-"):
                flags[key] = tokens[i + 1]
                i += 1
            else:
                flags[key] = None
        else:
            positional.append(tok)
        i += 1
    return positional, flags


def check_command_change(original: str, new: str) -> list[tuple[str, str]]:
    """The documented command is ground truth: a repair may only add or
    change non-scale flags. Same program/script and positional arguments,
    no new shell operators, and no scale flag reduced, removed or added."""
    try:
        old_tokens, new_tokens = _command_tokens(original), _command_tokens(new)
    except ValueError as exc:
        return [(EnvRule.ENV_COMMAND_UNSAFE, f"command does not parse: {exc}")]
    problems: list[tuple[str, str]] = []
    for tok in set(new_tokens):
        if (tok in _UNSAFE_TOKENS or "$(" in tok or "`" in tok) and new_tokens.count(tok) > old_tokens.count(tok):
            problems.append((EnvRule.ENV_COMMAND_UNSAFE, f"adds shell operator/substitution {tok!r}"))
    old_segments, new_segments = _segments(old_tokens), _segments(new_tokens)
    if len(old_segments) != len(new_segments):
        return problems + [(EnvRule.ENV_COMMAND_PROGRAM_CHANGED, "adds or removes a step of the documented command")]
    for old_seg, new_seg in zip(old_segments, new_segments):
        old_pos, old_flags = _split_segment(old_seg)
        new_pos, new_flags = _split_segment(new_seg)
        if old_pos != new_pos:
            problems.append((
                EnvRule.ENV_COMMAND_PROGRAM_CHANGED,
                f"program/script/positional arguments changed: {' '.join(old_pos)!r} -> {' '.join(new_pos)!r}",
            ))
        for key in set(old_flags) | set(new_flags):
            if key not in _SCALE_FLAG_WORDS:
                continue
            before, after = old_flags.get(key), new_flags.get(key)
            if key in old_flags and key not in new_flags:
                problems.append((EnvRule.REDUCED_SCALE, f"removes scale flag --{key} ({before})"))
            elif key not in old_flags:
                problems.append((EnvRule.REDUCED_SCALE, f"adds scale flag --{key} not in the documented command"))
            else:
                try:
                    if float(after) < float(before):
                        problems.append((EnvRule.REDUCED_SCALE, f"reduces --{key} from {before} to {after}"))
                except (TypeError, ValueError):
                    if after != before:
                        problems.append((EnvRule.REDUCED_SCALE, f"changes scale flag --{key} from {before!r} to {after!r}"))
    return problems


def _requirement_name(line: str) -> str | None:
    stripped = line.split("#", 1)[0].strip()
    if not stripped or stripped.startswith(("-", "git+", "http")):
        return None
    match = re.match(r"^([A-Za-z0-9][A-Za-z0-9._-]*)", stripped)
    return _norm(match.group(1)) if match else None


def _spec(c: EnvChange) -> str:
    if c.op == "pip_git":
        return f"{c.package} @ git+{c.git_url.rstrip('/')}@{c.commit}"
    return f"{c.package}=={c.version}" if c.version else c.package


def apply_env_delta(
    plan: BuildPlan, changes: tuple[EnvChange, ...], requirements_txt: str | None
) -> tuple[BuildPlan, str | None]:
    """Approved delta -> (new BuildPlan, new requirements text or None).

    With a requirements.txt, pip changes edit a RERUN-owned copy
    (`.rerun-requirements.txt`, written by the install step itself — the
    repo's own file is never modified) and the install command points at it.
    Without one, add/pin/pip_git become an extra `pip install` step."""
    base_image = plan.base_image
    apt = set(plan.apt_install)
    extra_specs: list[str] = []
    lines = requirements_txt.splitlines() if requirements_txt is not None else None
    notes = list(plan.notes)

    execute_command = plan.execute_command
    for c in changes:
        if c.op == "pip_no_build_isolation":
            continue  # applied after every other edit to the requirements (below)
        if c.op == "command":
            execute_command = c.command
            notes.append(f"env delta: command -> {c.command} — {c.justification}")
            continue
        if c.op == "python":
            base_image = f"python:{c.version}-slim"
        elif c.op == "apt":
            apt.add(c.package)
        elif (
            c.op == "remove"
            and c.package.lower() in apt
            and not (lines is not None and any(_requirement_name(line) == _norm(c.package) for line in lines))
        ):
            # harness-v1.3.3 (D-10): `remove` of an apt package edits the apt list (it used to fall through to the
            # requirements lines, match nothing, and leave the package installed).
            apt.discard(c.package.lower())
        elif lines is not None:
            key = _norm(c.package)
            matched = [i for i, line in enumerate(lines) if _requirement_name(line) == key]
            if c.op == "remove":
                lines = [line for i, line in enumerate(lines) if i not in matched]
            elif c.op == "unpin":
                for i in matched:
                    lines[i] = c.package
            elif c.op in ("pin", "add", "pip_git"):
                if matched:
                    for i in matched:
                        lines[i] = _spec(c)
                else:
                    lines.append(_spec(c))
        else:
            extra_specs.append(_spec(c))
        notes.append(f"env delta: {c.op} {c.package or c.version} — {c.justification}")

    # Two-stage install for pip_no_build_isolation: the package's line leaves
    # the requirements file (installed first, so the build can see e.g. the
    # locked numpy) and is installed right after with --no-build-isolation.
    no_isolation_specs: list[str] = []
    for c in changes:
        if c.op != "pip_no_build_isolation" or lines is None:
            continue
        key = _norm(c.package)
        moved = [line.strip() for line in lines if _requirement_name(line) == key]
        lines = [line for line in lines if _requirement_name(line) != key]
        no_isolation_specs.extend(moved)
        notes.append(f"env delta: pip_no_build_isolation {c.package} — {c.justification}")

    install_commands = list(plan.install_commands)
    new_requirements = None
    if lines is not None and any(c.op not in ("python", "apt", "command") for c in changes):
        new_requirements = "\n".join(lines) + "\n"
        write = f"printf '%s\\n' {' '.join(shlex.quote(line) for line in lines)} > {REQUIREMENTS_OVERRIDE_FILE}"
        install_commands = [
            f"{write} && pip install -r {REQUIREMENTS_OVERRIDE_FILE}"
            if cmd.strip() in ("pip install -r requirements.txt",) or cmd.endswith(f"pip install -r {REQUIREMENTS_OVERRIDE_FILE}")
            else cmd
            for cmd in install_commands
        ]
    if extra_specs:
        install_commands.append("pip install " + " ".join(shlex.quote(s) for s in extra_specs))
    for spec in no_isolation_specs:
        install_commands.append(f"pip install --no-build-isolation {shlex.quote(spec)}")

    return (
        replace(
            plan,
            base_image=base_image,
            apt_install=tuple(sorted(apt)),
            install_commands=tuple(install_commands),
            execute_command=execute_command,
            notes=tuple(notes),
        ),
        new_requirements,
    )
