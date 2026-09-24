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

from app.services.planner import BuildPlan
from app.services.tamper_gate import Violation

OPS = ("pin", "unpin", "add", "remove", "pip_git", "apt", "python")
MAX_CHANGES = 10
SUPPORTED_PYTHON_VERSIONS = ("3.7", "3.8", "3.9", "3.10", "3.11", "3.12", "3.13")
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


# PEP 508 distribution name.
_PIP_NAME_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?$")
# A plain version (PEP 440-ish, no operators, no spaces, no URLs).
_VERSION_RE = re.compile(r"^[0-9]+(?:\.[0-9]+)*(?:(?:a|b|rc|\.post|\.dev)[0-9]+)*(?:\+[A-Za-z0-9.]+)?$")
# Same rule planner.py applies to model-suggested apt names.
_APT_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9+.-]*$")
_GIT_URL_RE = re.compile(r"^https://(github\.com|gitlab\.com|bitbucket\.org)/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+?(\.git)?/?$")
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_URL_RE = re.compile(r"[a-z][a-z0-9+.-]*://|www\.", re.IGNORECASE)

# Distribution name -> import name, where they differ (inverse of
# classifier._IMPORT_TO_DIST, plus a few common ML cases).
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

    def as_dict(self) -> dict:
        return {
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


def check_env_delta(
    changes: tuple[EnvChange, ...],
    *,
    log_text: str,
    imported_modules: frozenset[str],
    has_requirements_txt: bool,
    verified_git_sources: frozenset[tuple[str, str]] = frozenset(),
) -> tuple[Violation, ...]:
    """The deterministic env gate. Returns every violation (empty = PASS).

    `verified_git_sources` holds (lowercased https URL, commit) pairs that
    dep_resolver resolved to a real commit this attempt. A pip_git change
    must match one exactly — a model-supplied URL or sha is never trusted."""
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

        if c.op in ("unpin", "remove") and not has_requirements_txt:
            _v(EnvRule.ENV_UNSUPPORTED, f"'{c.op}' needs a requirements.txt to edit", i)

        if c.op == "remove" and import_name_for(c.package).lower() in imported_lower:
            _v(
                EnvRule.ENV_REMOVES_IMPORTED,
                f"cannot remove '{c.package}': the repository's code imports '{import_name_for(c.package)}'",
                i,
            )
    return tuple(violations)


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

    for c in changes:
        if c.op == "python":
            base_image = f"python:{c.version}-slim"
        elif c.op == "apt":
            apt.add(c.package)
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

    install_commands = list(plan.install_commands)
    new_requirements = None
    if lines is not None and any(c.op not in ("python", "apt") for c in changes):
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

    return (
        replace(plan, base_image=base_image, apt_install=tuple(sorted(apt)), install_commands=tuple(install_commands), notes=tuple(notes)),
        new_requirements,
    )
