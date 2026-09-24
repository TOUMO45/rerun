"""Time machine: rebuild a repository's environment as of its own era.

Deterministic — no model involved. Three facts, each with a recorded source:

1. **Era date** — the latest commit touching the repo's dependency files
   (requirements*.txt, setup.py, setup.cfg, pyproject.toml, environment.yml),
   read from the GitHub API at the pinned commit. Found live (gpt-2): the
   pinned commit was a 2024 README edit, but requirements.txt last changed
   2019-03-04; dating by the pinned commit offered 2024-era packages and
   guaranteed a TF 2.x install for TF 1.x code. The pinned commit's own date
   is only a fallback, and the certificate says which was used.
2. **Python version** — the newest CPython whose first release is at least
   `PYTHON_LAG_DAYS` before the era date (ecosystem wheels lag a release),
   from python.org's release table; an exact version declared by the repo
   wins. All of 3.6–3.13 were verified live to exist as sandbox images.
3. **Lock** — the WHOLE dependency set (declared requirements + third-party
   modules the code imports but never declared) resolved at once with
   `uv pip compile --exclude-newer <era>` for Linux and the chosen Python, so
   one step fixes every missing/incompatible package from that era instead
   of one per repair attempt. Packages the index has never heard of are
   dropped from the lock and reported (they go to source search instead).
"""

from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Callable

from app.services.env_repair import imported_top_level_modules

# python.org devguide "Status of Python versions" — first release dates,
# retrieved 2026-09-24. Only versions verified available as sandbox images.
PYTHON_RELEASES: tuple[tuple[str, date], ...] = (
    ("3.6", date(2016, 12, 23)),
    ("3.7", date(2018, 6, 27)),
    ("3.8", date(2019, 10, 14)),
    ("3.9", date(2020, 10, 5)),
    ("3.10", date(2021, 10, 4)),
    ("3.11", date(2022, 10, 24)),
    ("3.12", date(2023, 10, 2)),
    ("3.13", date(2024, 10, 7)),
)
PYTHON_RELEASES_SOURCE = "https://devguide.python.org/versions/ (first release dates, retrieved 2026-09-24)"
PYTHON_LAG_DAYS = 180

DEPENDENCY_FILE_RE = re.compile(r"^(requirements[^/]*\.txt|setup\.py|setup\.cfg|pyproject\.toml|environment\.ya?ml)$")
MAX_DEP_FILES = 10

# Import name -> distribution name where they differ (common ML cases).
IMPORT_TO_DIST = {
    "sklearn": "scikit-learn",
    "cv2": "opencv-python",
    "yaml": "pyyaml",
    "PIL": "pillow",
    "bs4": "beautifulsoup4",
    "skimage": "scikit-image",
    "google.protobuf": "protobuf",
    "tf": "tensorflow",
    "torch_geometric": "torch-geometric",
    "Crypto": "pycryptodome",
    "dateutil": "python-dateutil",
    "attr": "attrs",
}
_STDLIB_EXTRA = {"__future__", "distutils", "imp", "asynchat", "asyncore", "smtpd"}

HttpGet = Callable[[str], "tuple[int, object]"]


@dataclass(frozen=True)
class EraDate:
    date: date
    source: str  # "dependency-files" | "pinned-commit"
    detail: dict = field(default_factory=dict)  # path -> last-change date, or notes

    def as_dict(self) -> dict:
        return {"date": self.date.isoformat(), "source": self.source, "detail": self.detail}


def find_dependency_files(workdir: Path) -> list[str]:
    found = []
    for path in sorted(workdir.rglob("*")):
        if ".git" in path.parts or not path.is_file() or path.is_symlink():
            continue
        if DEPENDENCY_FILE_RE.match(path.name):
            found.append(path.relative_to(workdir).as_posix())
        if len(found) >= MAX_DEP_FILES:
            break
    return found


def _github_owner_repo(repo_url: str) -> tuple[str, str] | None:
    match = re.match(r"^https://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?/?$", repo_url or "")
    return (match.group(1), match.group(2)) if match else None


def pinned_commit_date(workdir: Path) -> date | None:
    try:
        out = subprocess.run(
            ["git", "-C", str(workdir), "log", "-1", "--format=%cs"], capture_output=True, text=True, timeout=15
        )
        return date.fromisoformat(out.stdout.strip()) if out.returncode == 0 and out.stdout.strip() else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def era_date(repo_url: str, commit_sha: str, workdir: Path, http_get: HttpGet) -> EraDate | None:
    """Latest change to any dependency file at the pinned commit (GitHub
    API — the shallow clone has no history), else the pinned commit date."""
    dep_files = find_dependency_files(workdir)
    owner_repo = _github_owner_repo(repo_url)
    detail: dict = {}
    if owner_repo and dep_files:
        owner, repo = owner_repo
        for path in dep_files:
            try:
                status, body = http_get(
                    f"https://api.github.com/repos/{owner}/{repo}/commits?path={path}&sha={commit_sha}&per_page=1"
                )
            except Exception as exc:  # recorded, never fatal
                detail[path] = f"lookup failed: {type(exc).__name__}"
                continue
            if status == 200 and isinstance(body, list) and body:
                stamp = str(((body[0].get("commit") or {}).get("committer") or {}).get("date", ""))[:10]
                try:
                    detail[path] = date.fromisoformat(stamp).isoformat()
                except ValueError:
                    detail[path] = f"unparseable date {stamp!r}"
            else:
                detail[path] = f"no history (HTTP {status})"
        dates = [date.fromisoformat(v) for v in detail.values() if re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(v))]
        if dates:
            return EraDate(max(dates), "dependency-files", detail)
    fallback = pinned_commit_date(workdir)
    if fallback is None:
        return None
    if not dep_files:
        detail["note"] = "no dependency files in the repository"
    elif not owner_repo:
        detail["note"] = "not a github.com repository; dependency-file history unavailable"
    return EraDate(fallback, "pinned-commit", detail)


def python_for_era(era: date, declared_hint: str | None = None) -> tuple[str, str]:
    """(version, reason)."""
    if declared_hint and re.fullmatch(r"3\.\d{1,2}", declared_hint.strip()):
        known = {v for v, _ in PYTHON_RELEASES}
        if declared_hint.strip() in known:
            return declared_hint.strip(), "declared by the repository"
    eligible = [v for v, released in PYTHON_RELEASES if released <= era - timedelta(days=PYTHON_LAG_DAYS)]
    if not eligible:
        oldest = PYTHON_RELEASES[0][0]
        return oldest, f"era {era} predates every supported Python by the {PYTHON_LAG_DAYS}-day rule; oldest supported used"
    return eligible[-1], (
        f"newest CPython first released ≥{PYTHON_LAG_DAYS} days before the era date {era} ({PYTHON_RELEASES_SOURCE})"
    )


def _norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def local_module_names(workdir: Path) -> set[str]:
    names = set()
    for path in workdir.rglob("*.py"):
        if ".git" in path.parts:
            continue
        names.add(path.stem)
        for parent in path.relative_to(workdir).parents:
            if parent.name:
                names.add(parent.name)
    return names


def undeclared_third_party_imports(workdir: Path, declared: frozenset[str]) -> list[str]:
    """Distribution names for modules the code imports that are neither
    stdlib, the repo's own modules, nor declared."""
    stdlib = set(getattr(sys, "stdlib_module_names", ())) | _STDLIB_EXTRA
    local = local_module_names(workdir)
    declared_norm = {_norm(d) for d in declared}
    out = []
    for module in sorted(imported_top_level_modules(workdir)):
        if module in stdlib or module in local or module.startswith("_"):
            continue
        dist = IMPORT_TO_DIST.get(module, module)
        if _norm(dist) in declared_norm or _norm(module) in declared_norm:
            continue
        out.append(dist)
    return out


@dataclass(frozen=True)
class LockResult:
    ok: bool
    lock_lines: tuple[str, ...] = ()
    inputs: tuple[str, ...] = ()
    not_on_index: tuple[str, ...] = ()
    command: str = ""
    error: str = ""

    def as_dict(self) -> dict:
        return {
            "ok": self.ok,
            "lock": list(self.lock_lines),
            "inputs": list(self.inputs),
            "not_on_index": list(self.not_on_index),
            "command": self.command,
            "error": self.error[-2000:],
        }


_NOT_FOUND_RE = re.compile(r"Because ([A-Za-z0-9][A-Za-z0-9._-]*) was not found in the package registry")

Runner = Callable[[list[str], str], "tuple[int, str, str]"]  # (argv, stdin_text) -> (rc, stdout, stderr)


def _default_runner(argv: list[str], stdin_text: str) -> tuple[int, str, str]:
    proc = subprocess.run(argv, input=stdin_text, capture_output=True, text=True, timeout=300)
    return proc.returncode, proc.stdout, proc.stderr


REQUIREMENTS_OVERRIDE_FILE = ".rerun-requirements.txt"


def apply_lock(plan, python_version: str, lock_lines: list[str], apt_added: tuple[str, ...] = ()):
    """Era plan: python:X-slim, the lock written by the install step itself
    into a RERUN-owned file (the repo's requirements.txt is never edited),
    then `pip install --no-deps .` if the original plan installed the repo
    as a package."""
    import shlex
    from dataclasses import replace as _replace

    write = f"printf '%s\\n' {' '.join(shlex.quote(line) for line in lock_lines)} > {REQUIREMENTS_OVERRIDE_FILE}"
    commands = [f"{write} && pip install -r {REQUIREMENTS_OVERRIDE_FILE}"]
    if any(cmd.strip() == "pip install ." for cmd in plan.install_commands):
        commands.append("pip install --no-deps .")
    notes = tuple(plan.notes) + (f"time machine: python {python_version}, {len(lock_lines)} locked package(s)",)
    return _replace(
        plan,
        base_image=f"python:{python_version}-slim",
        apt_install=tuple(sorted(set(plan.apt_install) | set(apt_added))),
        install_commands=tuple(commands),
        notes=notes,
    )


def managed_build_python(minor: str = "3.8") -> str:
    """Explicit path to a uv-managed CPython `minor` if one is installed,
    else the bare version (uv resolves it). Found on this Windows host: uv's
    `cpython-3.8-…` minor-version link was broken ("Missing expected target
    directory for Python minor version link") while the real
    `cpython-3.8.20-…` install was fine, so the full path is preferred."""
    try:
        out = subprocess.run([uv_executable(), "python", "dir"], capture_output=True, text=True, timeout=30)
        base = Path(out.stdout.strip())
    except (OSError, subprocess.SubprocessError):
        return minor
    exe = "python.exe" if sys.platform == "win32" else "bin/python3"
    for candidate in sorted(base.glob(f"cpython-{minor}.*"), reverse=True):
        if (candidate / exe).exists():
            return str(candidate / exe)
    return minor


def uv_executable() -> str:
    candidate = Path(sys.executable).with_name("uv.exe" if sys.platform == "win32" else "uv")
    return str(candidate) if candidate.exists() else "uv"


def compile_lock(
    requirement_lines: list[str],
    extra_packages: list[str],
    era: date,
    python_version: str,
    *,
    runner: Runner | None = None,
    uv: str | None = None,
    build_python: str | None = None,
    max_drops: int = 5,
) -> LockResult:
    """`uv pip compile --exclude-newer <era+1d>` for Linux + `python_version`.
    Old sdists are built for metadata with a managed `build_python` (uv only
    ships managed CPython ≥3.8; verified 2026-09-24)."""
    runner = runner or _default_runner
    uv = uv or uv_executable()
    build_python = build_python or managed_build_python()
    inputs = [
        line.split("#", 1)[0].strip()
        for line in requirement_lines
        if line.split("#", 1)[0].strip() and not line.strip().startswith(("-", "git+", "http"))
    ]
    inputs += [p for p in extra_packages if _norm(p) not in {_norm(re.split(r"[<>=!~ ;\[]", i)[0]) for i in inputs}]
    cutoff = (era + timedelta(days=1)).isoformat() + "T00:00:00Z"
    argv = [
        uv, "pip", "compile", "-", "--no-header", "--no-annotate", "--quiet",
        "--exclude-newer", cutoff,
        "--python-version", python_version,
        "--python-platform", "x86_64-unknown-linux-gnu",
        "--python", build_python,
    ]
    dropped: list[str] = []
    current = list(inputs)
    for _ in range(max_drops + 1):
        try:
            rc, out, err = runner(argv, "\n".join(current) + "\n")
        except Exception as exc:  # uv missing, timeout, blocked in tests
            return LockResult(False, (), tuple(inputs), tuple(dropped), " ".join(argv[1:]), f"{type(exc).__name__}: {exc}")
        if rc == 0:
            lock = tuple(
                line.strip() for line in out.splitlines() if line.strip() and not line.strip().startswith("#")
            )
            return LockResult(True, lock, tuple(inputs), tuple(dropped), " ".join(argv[1:]))
        missing = _NOT_FOUND_RE.search(err)
        if not missing:
            return LockResult(False, (), tuple(inputs), tuple(dropped), " ".join(argv[1:]), err)
        name = missing.group(1)
        dropped.append(name)
        current = [line for line in current if _norm(re.split(r"[<>=!~ ;\[]", line)[0]) != _norm(name)]
        if not current:
            break
    return LockResult(False, (), tuple(inputs), tuple(dropped), " ".join(argv[1:]), "no resolvable inputs left")
