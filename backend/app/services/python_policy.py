"""Python version policy for the runner (Phase 3).

Default CPython 3.10 unless the repository declares otherwise; the reason is logged and
recorded in the build plan's notes. Before this, the runner defaulted to 3.11 no matter what,
which turned a whole class of failures (`from collections import Iterable`, removed in 3.10;
`inspect.getargspec`, ...) into results charged to the repository even though RERUN chose the
interpreter. With the policy, the remaining failures of that kind are attributable to the repo
(see error_chain.attribute: REPO iff the repo claims a version we ran, ENV otherwise).

Sources, in precedence order (first one that yields a usable version wins):

  1. `.python-version`            exact `X.Y[.Z]`
  2. `pyproject.toml`             `requires-python = "..."` (PEP 621) or poetry `python = "^3.8"`
  3. `setup.py` / `setup.cfg`     `python_requires`
  4. `environment.yml`            `python=3.8` / `python==3.8` / `python 3.8`
  5. `Pipfile`                    `python_version = "3.8"`
  6. README                       only explicit phrases (`Python 3.8`, `Python >= 3.6`, `python3.7`)

An exact declaration maps to that minor. A specifier set (`>=3.6,<3.9`) maps to the first minor in
PREFERENCE that satisfies it (recent-but-conservative: 3.10, 3.9, 3.8, 3.11, 3.7, 3.12, 3.13, 3.6).
A declaration no available image can satisfy falls back to the default and says so.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

DEFAULT_VERSION = "3.10"
DEFAULT_IMAGE = f"python:{DEFAULT_VERSION}-slim"
# Minors with a python:X-slim image, in the order a specifier is resolved.
PREFERENCE: tuple[str, ...] = ("3.10", "3.9", "3.8", "3.11", "3.7", "3.12", "3.13", "3.6")
SUPPORTED = frozenset(PREFERENCE)

_README_NAMES = ("README.md", "README.rst", "README.txt", "README", "readme.md")
_README_MAX_CHARS = 60_000


@dataclass(frozen=True)
class PythonChoice:
    version: str  # "3.10"
    source: str  # "default" | ".python-version" | "pyproject.toml" | ...
    declared: str | None  # what the repo said, verbatim
    reason: str

    @property
    def image(self) -> str:
        return f"python:{self.version}-slim"

    @property
    def is_declared(self) -> bool:
        return self.source != "default"


def satisfying_minors(spec: str) -> tuple[str, ...]:
    """Every minor (with a python:X-slim image) that satisfies the specifier / exact version, in the order of PREFERENCE; empty if none or unparseable."""
    text = spec.strip().strip("'\"")
    if re.fullmatch(r"3\.\d{1,2}(\.\d+)?(\.\*)?", text):
        minor = ".".join(text.split(".")[:2])
        return (minor,) if minor in SUPPORTED else ()
    # poetry / npm-style carets and tildes: ^3.8 -> >=3.8,<4 ; ~3.8 -> >=3.8,<3.9
    caret = re.fullmatch(r"\^\s*(3\.\d+)(\.\d+)*", text)
    if caret:
        text = f">={caret.group(1)},<4"
    tilde = re.fullmatch(r"~\s*(3)\.(\d+)(\.\d+)*", text)
    if tilde:
        text = f">=3.{tilde.group(2)},<3.{int(tilde.group(2)) + 1}"
    try:
        from packaging.specifiers import SpecifierSet

        specs = SpecifierSet(text)
    except Exception:  # noqa: BLE001 - unparseable (or packaging missing) -> not a usable declaration
        return ()
    return tuple(v for v in PREFERENCE if specs.contains(v, prereleases=True))


def _satisfying(spec: str) -> str | None:
    """First minor in PREFERENCE that satisfies the specifier / exact version, else None."""
    return next(iter(satisfying_minors(spec)), None)


def _from_python_version_file(text: str) -> str | None:
    first = next((ln.strip() for ln in text.splitlines() if ln.strip() and not ln.startswith("#")), "")
    return first or None


def _from_pyproject(text: str) -> str | None:
    m = re.search(r"""requires-python\s*=\s*['"]([^'"]+)['"]""", text)
    if m:
        return m.group(1)
    m = re.search(r"""\[tool\.poetry\.dependencies\][^\[]*?^\s*python\s*=\s*['"]([^'"]+)['"]""", text, re.M | re.S)
    return m.group(1) if m else None


def _from_setup(text: str) -> str | None:
    m = re.search(r"""python_requires\s*[=:]\s*['"]?([<>=!~][^'"\n,]*(?:,\s*[<>=!~][^'"\n,]*)*)['"]?""", text)
    return m.group(1).replace(" ", "") if m else None


def _from_environment_yml(text: str) -> str | None:
    m = re.search(r"^\s*-?\s*python\s*(?:==?|\s)\s*(\d+\.\d+(?:\.\d+)?)\s*$", text, re.M)
    return m.group(1) if m else None


def _from_pipfile(text: str) -> str | None:
    m = re.search(r"""python_(?:full_)?version\s*=\s*['"](\d+\.\d+(?:\.\d+)?)['"]""", text)
    return m.group(1) if m else None


_README_PATTERNS = (
    re.compile(r"\bpython\s*(?:version\s*)?(>=|~=|==|<=)\s*(3\.\d{1,2})", re.I),
    re.compile(r"\bpython\s*(3\.\d{1,2})\s*(\+|or (?:later|higher|newer|above))", re.I),
    re.compile(r"\bpython\s*(?:version\s*)?[:=]?\s*(3\.\d{1,2})\b", re.I),
    re.compile(r"\bpython(3\.\d{1,2})\b", re.I),
)


def _from_readme(text: str) -> str | None:
    """Only explicit statements; returns an exact version or a `>=` specifier."""
    versions: list[str] = []
    for line in text[:_README_MAX_CHARS].splitlines():
        for i, pattern in enumerate(_README_PATTERNS):
            for m in pattern.finditer(line):
                if i == 0:
                    versions.append(f"{m.group(1)}{m.group(2)}")
                elif i == 1:
                    versions.append(f">={m.group(1)}")
                else:
                    versions.append(m.group(1))
    if not versions:
        return None
    exact = sorted({v for v in versions if re.fullmatch(r"3\.\d{1,2}", v)})
    if len(set(versions)) == 1:
        return versions[0]
    if exact and len(exact) == len(set(versions)):
        # several exact versions mentioned (e.g. "tested on 3.6 and 3.7"): any is acceptable
        return ">=" + exact[0] + ",<=" + exact[-1]
    return versions[0]


def resolve(files: dict[str, str], readme: str | None = None) -> PythonChoice:
    """`files`: repo-root file name -> text (`.python-version`, `pyproject.toml`, `setup.py`, `setup.cfg`,
    `environment.yml`, `Pipfile`, ...). Pure."""
    sources = (
        (".python-version", lambda: _from_python_version_file(files.get(".python-version", ""))),
        ("pyproject.toml", lambda: _from_pyproject(files.get("pyproject.toml", ""))),
        ("setup.py", lambda: _from_setup(files.get("setup.py", ""))),
        ("setup.cfg", lambda: _from_setup(files.get("setup.cfg", ""))),
        ("environment.yml", lambda: _from_environment_yml(files.get("environment.yml") or files.get("environment.yaml") or "")),
        ("Pipfile", lambda: _from_pipfile(files.get("Pipfile", ""))),
        ("README", lambda: _from_readme(readme or "")),
    )
    skipped: list[str] = []
    for source, extract in sources:
        declared = extract()
        if not declared:
            continue
        version = _satisfying(declared)
        if version:
            return PythonChoice(
                version, source, declared,
                f"declared by {source} ({declared}); resolved to the first available minor that satisfies it",
            )
        skipped.append(f"{source} {declared!r}")
    reason = f"no usable Python declaration; RERUN default {DEFAULT_VERSION}"
    if skipped:
        reason += f" (declared but not satisfiable by an available image: {', '.join(skipped)})"
    return PythonChoice(DEFAULT_VERSION, "default", None, reason)


def resolve_from_repo(workdir: Path) -> PythonChoice:
    """Read the declaration sources from a cloned repo (size-capped) and resolve."""
    from app.services.intake import read_text_capped

    names = (".python-version", "pyproject.toml", "setup.py", "setup.cfg", "environment.yml", "environment.yaml", "Pipfile")
    files: dict[str, str] = {}
    for name in names:
        path = workdir / name
        if path.is_file() and not path.is_symlink():
            text = read_text_capped(path)
            if text is not None:
                files[name] = text
    readme = None
    for name in _README_NAMES:
        path = workdir / name
        if path.is_file() and not path.is_symlink():
            readme = read_text_capped(path)
            if readme is not None:
                break
    return resolve(files, readme)
