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
import os
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Callable

from app.services import dep_scan, timeouts
from app.services.import_names import ImportMapping, mapping_for
from app.services.infra import InfraError, checked_http_get, retry_call

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
            ["git", "-C", str(workdir), "log", "-1", "--format=%cs"], capture_output=True, text=True,
            timeout=timeouts.GIT_LOCAL_S,
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
    # harness-v1.1: a GitHub outage or rate limit used to fall back silently
    # to the pinned-commit date, changing the era (and so the environment and
    # the verdict). Now it is retried, then InfraError -> INFRA_ERROR.
    http_get = checked_http_get(http_get)
    if owner_repo and dep_files:
        owner, repo = owner_repo
        for path in dep_files:
            try:
                status, body = http_get(
                    f"https://api.github.com/repos/{owner}/{repo}/commits?path={path}&sha={commit_sha}&per_page=1"
                )
            except InfraError:
                raise
            except Exception as exc:  # a RERUN-side error in the getter, recorded
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
    """Names that resolve inside the repository (kept for callers; the scan in dep_scan is the definition)."""
    return set(dep_scan.internal_module_names(workdir))


def batch_for(workdir: Path, declared: frozenset[str]) -> "dep_scan.BatchInstall":
    """The ONE batch of packages the repository's code imports but never declares (harness-v1.3.3): whole-tree AST scan,
    repo-internal modules (incl. compiled/_ext with a build step) excluded, optional try/except imports skipped."""
    return dep_scan.batch_install_set(dep_scan.scan_repo(workdir), declared)


def undeclared_third_party_imports(workdir: Path, declared: frozenset[str]) -> list[str]:
    """Distribution names for modules the code imports that are neither
    stdlib, the repo's own modules, nor declared."""
    return [dist for dist, _ in undeclared_third_party_imports_with_mappings(workdir, declared)]


def undeclared_third_party_imports_with_mappings(
    workdir: Path, declared: frozenset[str]
) -> list[tuple[str, ImportMapping | None]]:
    """As undeclared_third_party_imports, with the import-map row used for
    each (None = the import name was used unchanged) — recorded in the
    certificate (harness-v1.1)."""
    return list(batch_for(workdir, declared).distributions)


@dataclass(frozen=True)
class LockResult:
    ok: bool
    lock_lines: tuple[str, ...] = ()
    inputs: tuple[str, ...] = ()
    not_on_index: tuple[str, ...] = ()
    command: str = ""
    error: str = ""
    # Names whose era cutoff was relaxed (their first release is shortly AFTER the era estimate): name -> cutoff used.
    relaxed: tuple[tuple[str, str], ...] = ()

    def as_dict(self) -> dict:
        out = {
            "ok": self.ok,
            "lock": list(self.lock_lines),
            "inputs": list(self.inputs),
            "not_on_index": list(self.not_on_index),
            "relaxed": [{"package": n, "cutoff": c} for n, c in self.relaxed],
            "command": self.command,
            "error": self.error[-2000:],
        }
        cause = lock_failure_cause(self.error) if not self.ok else None
        if cause is not None:
            out["cause"] = cause  # harness-v1.8 (T6): why the era lock was unavailable, only on a failed lock
        return out


# harness-v1.8 (T6, the minimum the owner asked for: "classify 'era lock unavailable' with its real cause"). Five of the 21 held-out entries logged "era lock unavailable" and
# fell back to ONE UNPINNED pip step (the newest releases, which is what API_REMOVED failures are made of); the log kept only the last 200 characters of uv's message.
# The causes below were read from those five records (TEST #13 neo_gnns, TEST #19 RBP, TEST #20 fashion-retrieval, TEST-B #5 cwn, OOS fb_friend_list_scraper), now
# DEV-CONTAMINATED. This only NAMES the cause; it changes no lock behaviour (a fix per cause is T6 proper, out of v1.8).
_LOCK_CAUSES = (
    # review (finding 6): the dependency is read from uv's own hint (`torch-scatter = ["torch"]`), never assumed to be torch
    ("BUILD_NEEDS_BUILD_DEPENDENCY", re.compile(r"extra-build-dependencies\]\s*(?P<package>[\w.\-]+)\s*=\s*\[(?P<needs>[^\]\n]*)\]"),
     "uv builds `{package}` in an isolated environment and its build needs {needs}, which is not there; it needs `extra-build-dependencies` or `--no-build-isolation`"),
    ("CUTOFF_BELOW_BUILD_TOOL", re.compile(r"exclude-newer-package|latest version satisfying the requirement is v?(?P<version>[\d.]+), published at"),
     "a requirement of the build is satisfied only by releases newer than the era cut-off date (uv names v{version}, published after it); the cut-off needs `exclude-newer-package` for that package"),
    ("SDIST_METADATA_BUILD_FAILED_ON_HOST", re.compile(r"Couldn't find a setup script in|Build failures usually indicate a problem with the package or the build environment"),
     "uv built an old source distribution on the HOST machine to read its metadata and the build failed; the lock is computed on the host, not in the sandbox"),
    ("REQUIREMENTS_UNSATISFIABLE", re.compile(r"requirements are unsatisfiable|No solution found|resolution impossible", re.IGNORECASE),
     "no set of releases up to the era cut-off satisfies every requirement together"),
)


def lock_failure_cause(error: str) -> dict | None:
    """{"id", "detail", "quote"} for the first known cause in uv's message, else None (an unknown failure keeps only the message)."""
    text = error or ""
    for cause_id, rx, template in _LOCK_CAUSES:
        m = rx.search(text)
        if m:
            groups = {k: (v or "the package") for k, v in m.groupdict().items()} if m.groupdict() else {}
            # the quote is ONE line of uv's message: the line the match ENDS on (the hint's `torch-scatter = ["torch"]` row, not the header line before it)
            end = m.end() - 1 if m.end() > m.start() else m.end()
            line = text[max(0, text.rfind("\n", 0, end) + 1): (text.find("\n", end) if text.find("\n", end) != -1 else len(text))].strip()
            return {"id": cause_id, "detail": template.format(package=groups.get("package", "the package"), version=groups.get("version", "?"),
                                                              needs=groups.get("needs", "a package")), "quote": line[:300]}
    return None


_NOT_FOUND_RE = re.compile(r"Because ([A-Za-z0-9][A-Za-z0-9._-]*) was not found in the package registry")
# uv's message when NO release of a name exists on or before the era cutoff (`--exclude-newer`): corpus-v2 entry 1 asked
# for `curves`, whose only release is from 2025; one such name failed the whole era lock (D-1/D-5). It is dropped and
# reported like a name the index has never heard of; the rest of the lock proceeds.
_NO_VERSIONS_RE = re.compile(r"Because there are no versions of ([A-Za-z0-9][A-Za-z0-9._-]*)")
# The era is an ESTIMATE (the last change to a dependency file, or the pinned commit date). A package whose first release
# comes shortly after it (corpus-v2 entry 20: pycocoevalcap, 6 weeks) is allowed one year past the era, per package
# (`uv --exclude-newer-package`); one with nothing inside that window (entry 1: `curves`, 2025) is dropped.
ERA_RELAX_DAYS = 365
# uv's messages when the index itself is unreachable (not an answer about a package).
_UV_NETWORK_RE = re.compile(
    r"Failed to fetch|error sending request|operation timed out|dns error|tcp connect error|"
    r"Connection (?:reset|refused)|Network is unreachable|HTTP status server error|client error \(Connect\)",
    re.IGNORECASE,
)


class _IndexUnreachable(RuntimeError):
    pass


def _sleep(seconds: float) -> None:
    import time as _time

    _time.sleep(seconds)

Runner = Callable[[list[str], str], "tuple[int, str, str]"]  # (argv, stdin_text) -> (rc, stdout, stderr)


# harness-v1.10 flag mode (independent review of rc6): `uv pip compile` may build old sdists, i.e. run third-party setup.py code; it needs none of RERUN's credentials
SECRET_ENV_PREFIXES = ("NEBIUS_", "TAVILY_")


def scrubbed_env(environ=None) -> dict:
    """The environment a lock compilation runs in: the process's, without RERUN's credentials."""
    return {k: v for k, v in (os.environ if environ is None else environ).items() if not k.startswith(SECRET_ENV_PREFIXES)}


def _default_runner(argv: list[str], stdin_text: str) -> tuple[int, str, str]:
    proc = subprocess.run(argv, input=stdin_text, capture_output=True, text=True, timeout=timeouts.UV_COMPILE_S, env=scrubbed_env())
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


def apply_batch_pip(plan, packages: list[str] | tuple[str, ...], apt_added: tuple[str, ...] = ()):
    """Fallback when the era lock cannot be produced at all: ONE `pip install` step for every undeclared import, unpinned,
    on the plan's own interpreter (the policy's choice, incl. a README-declared version). Not era-pinned: the record says so."""
    import shlex
    from dataclasses import replace as _replace

    commands = tuple(plan.install_commands)
    if packages:
        commands += ("pip install " + " ".join(shlex.quote(p) for p in packages),)
    notes = tuple(plan.notes) + (f"time machine fallback (no era lock): one pip step for {len(packages)} undeclared import(s), unpinned",)
    return _replace(plan, apt_install=tuple(sorted(set(plan.apt_install) | set(apt_added))), install_commands=commands, notes=notes)


def managed_build_python(minor: str = "3.8") -> str:
    """Explicit path to a uv-managed CPython `minor` if one is installed,
    else the bare version (uv resolves it). Found on this Windows host: uv's
    `cpython-3.8-…` minor-version link was broken ("Missing expected target
    directory for Python minor version link") while the real
    `cpython-3.8.20-…` install was fine, so the full path is preferred."""
    try:
        out = subprocess.run([uv_executable(), "python", "dir"], capture_output=True, text=True, timeout=timeouts.UV_QUERY_S)
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
    max_drops: int = 8,
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
    relax_cutoff = (era + timedelta(days=1 + ERA_RELAX_DAYS)).isoformat() + "T00:00:00Z"
    base_argv = [
        uv, "pip", "compile", "-", "--no-header", "--no-annotate", "--quiet",
        "--exclude-newer", cutoff,
        "--python-version", python_version,
        "--python-platform", "x86_64-unknown-linux-gnu",
        "--python", build_python,
    ]
    dropped: list[str] = []
    relaxed: dict[str, str] = {}
    current = list(inputs)

    def _argv() -> list[str]:
        return base_argv + [a for name in relaxed for a in ("--exclude-newer-package", f"{name}={relaxed[name]}")]

    def _run_uv(stdin_text: str):
        # harness-v1.1: uv could not reach the package index -> retried, then
        # InfraError('package-index') instead of a failed lock the repair
        # loop would then try to work around.
        rc, out, err = runner(_argv(), stdin_text)
        if rc != 0 and _UV_NETWORK_RE.search(err or ""):
            raise _IndexUnreachable(err[-500:])
        return rc, out, err

    for _ in range(max_drops + 1):
        try:
            rc, out, err = retry_call(
                lambda: _run_uv("\n".join(current) + "\n"),
                source="package-index",
                is_transient=lambda exc: isinstance(exc, (_IndexUnreachable, subprocess.TimeoutExpired)),
                sleep=lambda s: _sleep(s),
            )
        except InfraError:
            raise
        except Exception as exc:  # uv missing, blocked in tests
            return LockResult(False, (), tuple(inputs), tuple(dropped), " ".join(_argv()[1:]), f"{type(exc).__name__}: {exc}", tuple(relaxed.items()))
        if rc == 0:
            lock = tuple(
                line.strip() for line in out.splitlines() if line.strip() and not line.strip().startswith("#")
            )
            return LockResult(True, lock, tuple(inputs), tuple(dropped), " ".join(_argv()[1:]), "", tuple(relaxed.items()))
        missing = _NOT_FOUND_RE.search(err) or _NO_VERSIONS_RE.search(err)
        if not missing:
            return LockResult(False, (), tuple(inputs), tuple(dropped), " ".join(_argv()[1:]), err, tuple(relaxed.items()))
        name = missing.group(1)
        if (
            _NO_VERSIONS_RE.search(err)
            and re.search(r"filtered by `exclude-newer", err)
            and _norm(name) not in {_norm(r) for r in relaxed}
        ):
            # The era is an estimate: first allow this ONE package a year past it, then retry the whole lock.
            relaxed[name] = relax_cutoff
            continue
        dropped.append(name)
        relaxed.pop(name, None)
        current = [line for line in current if _norm(re.split(r"[<>=!~ ;\[]", line)[0]) != _norm(name)]
        if not current:
            break
    return LockResult(False, (), tuple(inputs), tuple(dropped), " ".join(_argv()[1:]), "no resolvable inputs left", tuple(relaxed.items()))
