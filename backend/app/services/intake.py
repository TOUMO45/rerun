"""Repo intake (RERUN directive §3 must-have #1, first half of recon).

Clones a target repo (read-only — §2.5: cloning public repos is fine,
RERUN never pushes to or authenticates against an external target) and
parses its dependency/entrypoint/notebook surface with plain file parsing.
No model call happens in this module: everything here is either a
subprocess `git` call or straightforward text/YAML parsing. The *semantic*
judgment calls (which entrypoint is most likely correct, what the repo's
data requirements really are) belong to `recon.py`'s Nemotron Nano call,
which consumes this module's structured output as its input — this module
only gathers the raw facts a model or a human could read directly off disk.
"""

from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
from dataclasses import dataclass, field
from pathlib import Path, PurePath

import yaml

# `git clone`'s default `core.symlinks=true` on Linux (the real deployment
# target) clones a committed symlink as a real filesystem symlink. Found
# live during this session's audit: a bare `repo_path.rglob(pattern)`
# follows symlinked directories by default, and `Path.is_file()`/
# `read_text()` follow a symlinked *file* to its target — so a malicious
# repo committing a symlink (a file, or worse, a whole directory) pointing
# outside the cloned checkout could make RERUN read, and potentially feed
# into a model prompt or upload into the sandbox, arbitrary files from the
# backend host's filesystem. `os.walk(..., followlinks=False)` is the
# stdlib's own explicit, documented way to refuse to descend into a
# symlinked directory; combined with skipping any symlinked *file* found
# along the way, this closes both the directory- and file-level traversal
# at the one place all of this module's scans go through. Real repos have
# no legitimate reason for their own dependency/entrypoint files to be
# symlinks pointing outside themselves.
def _walk_real_files(repo_path: Path, suffix: str):
    for dirpath, _dirnames, filenames in os.walk(repo_path, followlinks=False):
        current = Path(dirpath)
        for filename in filenames:
            if not filename.endswith(suffix):
                continue
            file_path = current / filename
            if file_path.is_symlink():
                continue
            yield file_path


# Found live: every read_text() call in this module (and the analogous
# ones in orchestrator.py) read a repo-controlled file's FULL content
# into memory with no size check at all, before any sandbox isolation,
# cost-guard check, or tamper-gate rule even runs — intake happens
# directly on the RERUN backend host. Confirmed reading a genuine 96MB
# file (a single moderately-sized example, not an attempt to actually
# exhaust anything) completes with no protection whatsoever; a repo with
# several very large files (or one much larger one) could exhaust
# backend memory from the very first, public POST /runs step alone. Real
# dependency/entrypoint source files are essentially always well under a
# few hundred KB; this cap is generous, not tight.
_MAX_SCANNED_FILE_BYTES = 2_000_000


def read_text_capped(path: Path, max_bytes: int = _MAX_SCANNED_FILE_BYTES) -> str | None:
    """Reads a file's text content, refusing (returning None) if it's
    larger than `max_bytes` — checked with a cheap `stat()` first, never
    by reading the whole file and discarding it afterward."""
    try:
        if path.stat().st_size > max_bytes:
            return None
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


DEPENDENCY_FILENAMES = (
    "requirements.txt",
    "requirements-dev.txt",
    "setup.py",
    "setup.cfg",
    "pyproject.toml",
    "environment.yml",
    "environment.yaml",
    "Pipfile",
)

ENTRYPOINT_NAME_HINTS = (
    "main.py",
    "train.py",
    "run.py",
    "run_experiment.py",
    "run_experiments.py",
    "reproduce.py",
    "experiment.py",
)


class IntakeError(RuntimeError):
    pass


class RepoNotFoundError(IntakeError):
    pass


class RepoPrivateError(IntakeError):
    pass


class RepoNotPythonError(IntakeError):
    pass


def validate_repo_accessible(url: str, timeout: float = 30.0) -> None:
    """Cheap pre-flight check (S1 intake, §8): confirm `url` is a reachable,
    public git repo before paying for a full clone. Raises a specific
    subclass so the API layer can return a distinct error message per §8
    ("private repo / not python / no code found" must each be distinct).

    Uses `git ls-remote`, which talks to the remote without downloading
    any repo content — read-only, per §2.5.
    """
    result = subprocess.run(
        ["git", "ls-remote", "--exit-code", url, "HEAD"],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode == 0:
        return
    stderr = result.stderr.lower()
    if "authentication" in stderr or "could not read username" in stderr or "permission denied" in stderr:
        raise RepoPrivateError(f"'{url}' appears to require authentication (private repo?): {result.stderr.strip()}")
    raise RepoNotFoundError(f"'{url}' is not reachable as a public git repo: {result.stderr.strip()}")


def repo_has_python_code(repo_path: Path, dependency_files: dict[str, str] | None = None) -> bool:
    """True if the repo has any signal of being a Python project: a known
    dependency file, or at least one .py file on disk."""
    if dependency_files:
        return True
    return next(_walk_real_files(repo_path, ".py"), None) is not None


@dataclass(frozen=True)
class RepoIntake:
    local_path: Path
    commit_sha: str
    dependency_files: dict[str, str] = field(default_factory=dict)
    declared_dependencies: frozenset[str] = field(default_factory=frozenset)
    notebook_paths: tuple[str, ...] = field(default_factory=tuple)
    entrypoint_candidates: tuple[str, ...] = field(default_factory=tuple)
    python_version_hint: str | None = None

    def as_dict(self) -> dict:
        return {
            "local_path": str(self.local_path),
            "commit_sha": self.commit_sha,
            "dependency_files": sorted(self.dependency_files.keys()),
            "declared_dependencies": sorted(self.declared_dependencies),
            "notebook_paths": list(self.notebook_paths),
            "entrypoint_candidates": list(self.entrypoint_candidates),
            "python_version_hint": self.python_version_hint,
        }


def cleanup_workdir(path: Path) -> None:
    """Delete a cloned repo's working directory, robustly.

    Plain `shutil.rmtree(path, ignore_errors=True)` **silently fails to
    fully delete a real git clone on Windows** — confirmed directly (not
    assumed): git's own object files are written read-only, and Windows
    refuses to unlink a read-only file, so `rmtree` hits a
    `PermissionError` partway through and `ignore_errors=True` just
    swallows it, leaving most of the tree behind with no error raised
    anywhere. Every caller that clones a repo into a temp directory and
    relies on cleanup afterward needs this, not a bare `rmtree` call.
    """

    def _on_rm_error(func, target_path, exc_info):
        Path(target_path).chmod(stat.S_IWRITE)
        func(target_path)

    shutil.rmtree(path, onerror=_on_rm_error)


def clone_repo(url: str, dest: Path, shallow: bool = True) -> str:
    """Shallow-clone `url` into `dest` (read-only) and return the checked-out
    commit SHA. Never pushes, never authenticates — public clone only,
    per §2.5."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["git", "clone"]
    if shallow:
        cmd += ["--depth", "1"]
    cmd += [url, str(dest)]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        raise IntakeError(f"git clone failed for '{url}': {result.stderr.strip()}")

    sha_result = subprocess.run(
        ["git", "-C", str(dest), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if sha_result.returncode != 0:
        raise IntakeError(f"could not read commit SHA for '{dest}': {sha_result.stderr.strip()}")
    return sha_result.stdout.strip()


def clone_repo_at_commit(url: str, dest: Path, commit_sha: str) -> str:
    """Fetch and check out one *specific* pinned commit — not just the
    default branch's current HEAD, which is what a plain shallow
    `clone_repo()` gets. This is what the Batch Lab actually needs
    (`corpus.yaml` pins an exact commit per repo, per METHODOLOGY.md): a
    plain shallow clone would silently drift to whatever HEAD happens to
    be on the day the batch runs, not the commit the corpus was assembled
    against and its `selection_note` was written about.

    Uses `git init` + `git fetch --depth 1 origin <sha>` + `git checkout
    FETCH_HEAD` rather than `git clone` followed by a checkout, since a
    shallow clone's single fetched commit is the default branch tip, not
    an arbitrary older SHA — fetching the SHA directly is the only way to
    get exactly that commit without downloading the repo's full history.
    Requires the remote to allow fetching by commit SHA (GitHub does, for
    public repos; not guaranteed for every git host — if this fails, the
    error message says so explicitly rather than silently falling back to
    HEAD, which would defeat the whole point of pinning).
    """
    dest.mkdir(parents=True, exist_ok=True)
    init_result = subprocess.run(["git", "init", str(dest)], capture_output=True, text=True, timeout=30)
    if init_result.returncode != 0:
        raise IntakeError(f"git init failed for '{dest}': {init_result.stderr.strip()}")

    fetch_result = subprocess.run(
        ["git", "-C", str(dest), "fetch", "--depth", "1", url, commit_sha],
        capture_output=True,
        text=True,
        timeout=300,
    )
    if fetch_result.returncode != 0:
        raise IntakeError(
            f"could not fetch pinned commit '{commit_sha}' from '{url}' — the remote may not allow "
            f"fetching by commit SHA, or the commit no longer exists: {fetch_result.stderr.strip()}"
        )

    checkout_result = subprocess.run(
        ["git", "-C", str(dest), "checkout", "FETCH_HEAD"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if checkout_result.returncode != 0:
        raise IntakeError(f"could not check out fetched commit in '{dest}': {checkout_result.stderr.strip()}")

    sha_result = subprocess.run(
        ["git", "-C", str(dest), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    return sha_result.stdout.strip()


def repo_relative_posix(path: PurePath, repo_path: PurePath) -> str:
    """Repo-relative path in POSIX form. These strings end up in shell
    commands run inside a *Linux* sandbox (`python <entrypoint>`) and in
    the model prompts, so they must never carry Windows backslashes — a
    Windows-hosted backend would otherwise produce `python src\train.py`,
    which is a nonexistent filename on Linux (found in the first live run)."""
    return path.relative_to(repo_path).as_posix()


def find_dependency_files(repo_path: Path) -> dict[str, str]:
    found: dict[str, str] = {}
    for name in DEPENDENCY_FILENAMES:
        candidate = repo_path / name
        if candidate.is_file() and not candidate.is_symlink():
            content = read_text_capped(candidate)
            if content is not None:
                found[name] = content
    return found


def find_notebooks(repo_path: Path) -> tuple[str, ...]:
    return tuple(
        sorted(
            repo_relative_posix(p, repo_path)
            for p in _walk_real_files(repo_path, ".ipynb")
            if ".ipynb_checkpoints" not in p.parts
        )
    )


def find_entrypoint_candidates(repo_path: Path) -> tuple[str, ...]:
    candidates: set[str] = set()
    for py_file in _walk_real_files(repo_path, ".py"):
        if any(part.startswith(".") for part in py_file.parts):
            continue
        rel = repo_relative_posix(py_file, repo_path)
        if py_file.name in ENTRYPOINT_NAME_HINTS:
            candidates.add(rel)
            continue
        text = read_text_capped(py_file)
        if text is None:
            continue
        if re.search(r"""if\s+__name__\s*==\s*['"]__main__['"]\s*:""", text):
            candidates.add(rel)
    return tuple(sorted(candidates))


def parse_requirements_txt(content: str) -> frozenset[str]:
    names: set[str] = set()
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or line.startswith("-"):
            continue
        line = line.split("#", 1)[0].strip()
        match = re.match(r"^([A-Za-z0-9_.\-]+)", line)
        if match:
            names.add(match.group(1).lower())
    return frozenset(names)


def parse_setup_py(content: str) -> frozenset[str]:
    names: set[str] = set()
    match = re.search(r"install_requires\s*=\s*\[(.*?)\]", content, re.DOTALL)
    if match:
        for item in re.findall(r"""['"]([^'"]+)['"]""", match.group(1)):
            pkg = re.match(r"^([A-Za-z0-9_.\-]+)", item.strip())
            if pkg:
                names.add(pkg.group(1).lower())
    return frozenset(names)


def parse_environment_yml(content: str) -> frozenset[str]:
    names: set[str] = set()
    try:
        data = yaml.safe_load(content)
    except yaml.YAMLError:
        return frozenset()
    if not isinstance(data, dict):
        return frozenset()
    for dep in data.get("dependencies", []) or []:
        if isinstance(dep, str):
            pkg = re.match(r"^([A-Za-z0-9_.\-]+)", dep.strip())
            if pkg and pkg.group(1).lower() != "python":
                names.add(pkg.group(1).lower())
        elif isinstance(dep, dict) and "pip" in dep:
            for pip_dep in dep["pip"] or []:
                pkg = re.match(r"^([A-Za-z0-9_.\-]+)", str(pip_dep).strip())
                if pkg:
                    names.add(pkg.group(1).lower())
    return frozenset(names)


def parse_pyproject_toml_deps(content: str) -> frozenset[str]:
    names: set[str] = set()
    match = re.search(r"dependencies\s*=\s*\[(.*?)\]", content, re.DOTALL)
    if match:
        for item in re.findall(r"""['"]([^'"]+)['"]""", match.group(1)):
            pkg = re.match(r"^([A-Za-z0-9_.\-]+)", item.strip())
            if pkg:
                names.add(pkg.group(1).lower())
    return frozenset(names)


def detect_python_version_hint(dependency_files: dict[str, str]) -> str | None:
    setup_py = dependency_files.get("setup.py", "")
    match = re.search(r"python_requires\s*=\s*['\"]([^'\"]+)['\"]", setup_py)
    if match:
        return match.group(1)
    pyproject = dependency_files.get("pyproject.toml", "")
    match = re.search(r"""requires-python\s*=\s*['"]([^'"]+)['"]""", pyproject)
    if match:
        return match.group(1)
    env_yml = dependency_files.get("environment.yml") or dependency_files.get("environment.yaml") or ""
    match = re.search(r"python[=\s]*([\d.]+)", env_yml)
    if match:
        return f"=={match.group(1)}"
    return None


def parse_declared_dependencies(dependency_files: dict[str, str]) -> frozenset[str]:
    names: set[str] = set()
    for filename, content in dependency_files.items():
        if filename in ("requirements.txt", "requirements-dev.txt"):
            names |= parse_requirements_txt(content)
        elif filename == "setup.py":
            names |= parse_setup_py(content)
        elif filename in ("environment.yml", "environment.yaml"):
            names |= parse_environment_yml(content)
        elif filename == "pyproject.toml":
            names |= parse_pyproject_toml_deps(content)
    return frozenset(names)


def parse_intake(workdir: Path, commit_sha: str) -> RepoIntake:
    """Parse an already-cloned repo on disk into a `RepoIntake` — the
    local-file-only half of intake, shared by `run_intake` (clones HEAD
    itself) and the batch runner's `run_single_repo` (clones a pinned
    commit via `clone_repo_at_commit` first)."""
    dependency_files = find_dependency_files(workdir)
    return RepoIntake(
        local_path=workdir,
        commit_sha=commit_sha,
        dependency_files=dependency_files,
        declared_dependencies=parse_declared_dependencies(dependency_files),
        notebook_paths=find_notebooks(workdir),
        entrypoint_candidates=find_entrypoint_candidates(workdir),
        python_version_hint=detect_python_version_hint(dependency_files),
    )


def run_intake(repo_url: str, workdir: Path, shallow: bool = True) -> RepoIntake:
    """Full intake: clone, then parse. The only network/subprocess call is
    the clone itself; everything after is local file parsing."""
    commit_sha = clone_repo(repo_url, workdir, shallow=shallow)
    return parse_intake(workdir, commit_sha)
