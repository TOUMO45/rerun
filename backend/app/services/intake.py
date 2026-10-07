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
import time
from dataclasses import dataclass, field
from pathlib import Path, PurePath

import yaml

from app.services import data_prep, timeouts
from app.services.infra import retry_call

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


# git's messages when the host is unreachable (not an answer about the repo).
_GIT_NETWORK_RE = re.compile(
    r"Could not resolve host|Connection timed out|Connection reset|Connection refused|Operation timed out|"
    r"early EOF|RPC failed|The requested URL returned error: (?:429|5\d\d)|gnutls_handshake|SSL_ERROR|"
    r"Failed to connect",
    re.IGNORECASE,
)


class _GitNetworkError(RuntimeError):
    pass


def _sleep(seconds: float) -> None:
    time.sleep(seconds)


class IntakeError(RuntimeError):
    pass


class RepoNotFoundError(IntakeError):
    pass


class RepoPrivateError(IntakeError):
    pass


class RepoNotPythonError(IntakeError):
    pass


class RepoUrlInvalidError(IntakeError):
    pass


# What POST /runs accepts: a public GitHub repository over HTTPS and nothing else. The URL reaches
# `git ls-remote` / `git clone` on the backend host: a value read as an option (`--upload-pack=<cmd>`)
# runs a command there, and a `file://` / `ext::` / local path reads the host itself.
_GITHUB_REPO_URL = re.compile(r"https://(?i:(?:www\.)?github\.com)/[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})/(?P<repo>[A-Za-z0-9_.-]{1,100}?)(?:\.git)?/?")


def validate_repo_url(url: str, *, allow_local: bool = False) -> None:
    """Refuse anything but `https://github.com/<owner>/<repo>[.git][/]` before any git command sees it.
    `allow_local` (tests only, Settings.allow_local_repo_paths) also admits an absolute local path,
    which is how the test suite feeds a fixture repository (a missing one then fails as "not found")."""
    match = _GITHUB_REPO_URL.fullmatch(url)  # fullmatch: a trailing newline is refused too
    if match and match.group("repo") not in (".", ".."):
        return
    # `//host/share` and `\\host\share` are absolute on Windows: a UNC path would make git reach out over SMB.
    if allow_local and not url.startswith(("-", "//", "\\\\")) and Path(url).is_absolute():
        return
    raise RepoUrlInvalidError(f"'{url[:200]}' is not a public GitHub repository URL (expected https://github.com/<owner>/<repo>)")


def _refuse_option_like(url: str) -> None:
    """Last line of defence for every git call that takes a URL: a value starting with '-' is never a repository."""
    if url.startswith("-"):
        raise RepoUrlInvalidError(f"'{url[:200]}' is not a repository URL")


def validate_repo_accessible(url: str, timeout: float = 30.0) -> None:
    """Cheap pre-flight check (S1 intake, §8): confirm `url` is a reachable,
    public git repo before paying for a full clone. Raises a specific
    subclass so the API layer can return a distinct error message per §8
    ("private repo / not python / no code found" must each be distinct).

    Uses `git ls-remote`, which talks to the remote without downloading
    any repo content — read-only, per §2.5.
    """
    _refuse_option_like(url)
    result = subprocess.run(
        ["git", "ls-remote", "--exit-code", "--", url, "HEAD"],
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
    # harness-v1.8 (T15, D-52): the candidates (a subset of `entrypoint_candidates`, the last ones) that are there ONLY because the repository's README tells the
    # reader to run them, with the README's command line ("python simplemud.py"). Empty for a repository whose candidates discovery found itself, and for every
    # corpus run (parse_intake without readme_entrypoints), so their intake and recon prompt are exactly what they were.
    readme_entrypoints: dict[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict:
        out = {
            "local_path": str(self.local_path),
            "commit_sha": self.commit_sha,
            "dependency_files": sorted(self.dependency_files.keys()),
            "declared_dependencies": sorted(self.declared_dependencies),
            "notebook_paths": list(self.notebook_paths),
            "entrypoint_candidates": list(self.entrypoint_candidates),
            "python_version_hint": self.python_version_hint,
        }
        if self.readme_entrypoints:  # only when the README added something: an unchanged repository keeps its record byte for byte
            out["readme_entrypoints"] = dict(self.readme_entrypoints)
        return out


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


# Byte-exact checkouts (found live 2026-09-24, TTPT): this Windows host has
# global core.autocrlf=true, which rewrote every text file to CRLF; shell
# scripts then broke in the Linux sandbox and the failure was blamed on the
# repo. These flags override any user/system config for RERUN's own git calls;
# GIT_LFS_SKIP_SMUDGE keeps LFS pointer files exactly as committed.
# tree_integrity.verify_upload proves the result before every upload.
_GIT_BYTE_EXACT = ["-c", "core.autocrlf=false", "-c", "core.eol=lf"]


def _git_env() -> dict:
    return {**os.environ, "GIT_LFS_SKIP_SMUDGE": "1"}


def clone_repo(url: str, dest: Path, shallow: bool = True) -> str:
    """Shallow-clone `url` into `dest` (read-only) and return the checked-out
    commit SHA. Never pushes, never authenticates — public clone only,
    per §2.5."""
    _refuse_option_like(url)
    dest.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["git", *_GIT_BYTE_EXACT, "clone", "--config", "core.autocrlf=false", "--config", "core.eol=lf"]
    if shallow:
        cmd += ["--depth", "1"]
    cmd += ["--", url, str(dest)]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeouts.GIT_FETCH_S, env=_git_env())
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
    _refuse_option_like(url)
    dest.mkdir(parents=True, exist_ok=True)
    init_result = subprocess.run(["git", "init", str(dest)], capture_output=True, text=True, timeout=timeouts.GIT_LOCAL_S)
    if init_result.returncode != 0:
        raise IntakeError(f"git init failed for '{dest}': {init_result.stderr.strip()}")
    # Persist the byte-exact settings in the checkout itself too, so any later
    # git command on it (e.g. `git apply`) behaves the same.
    for key, value in (("core.autocrlf", "false"), ("core.eol", "lf")):
        subprocess.run(["git", "-C", str(dest), "config", key, value], capture_output=True, timeout=timeouts.GIT_LOCAL_S)

    def _fetch():
        result = subprocess.run(
            ["git", *_GIT_BYTE_EXACT, "-C", str(dest), "fetch", "--depth", "1", "--", url, commit_sha],
            capture_output=True,
            text=True,
            timeout=timeouts.GIT_FETCH_S,
            env=_git_env(),
        )
        if result.returncode != 0 and _GIT_NETWORK_RE.search(result.stderr or ""):
            raise _GitNetworkError(result.stderr.strip()[-500:])
        return result

    # harness-v1.1: a network failure talking to the git host is retried with
    # backoff, then InfraError('git') — never a statement about the repository.
    fetch_result = retry_call(
        _fetch,
        source="git",
        is_transient=lambda exc: isinstance(exc, (_GitNetworkError, subprocess.TimeoutExpired)),
        sleep=lambda s: _sleep(s),
    )
    if fetch_result.returncode != 0:
        raise IntakeError(
            f"could not fetch pinned commit '{commit_sha}' from '{url}' — the remote may not allow "
            f"fetching by commit SHA, or the commit no longer exists: {fetch_result.stderr.strip()}"
        )

    checkout_result = subprocess.run(
        ["git", *_GIT_BYTE_EXACT, "-C", str(dest), "checkout", "FETCH_HEAD"],
        capture_output=True,
        text=True,
        timeout=30,
        env=_git_env(),
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
        elif _is_module_level_script(py_file.name, text):
            candidates.add(rel)
    return tuple(sorted(candidates))


# harness-v1.7.2 (live scan 2026-10-05, reports/live_scan/SCAN_2026-10-05.md): three of five small repositories were scripts that run at module
# level with no `__main__` guard (pdf-to-powerpoint `convert.py`: `pdf_file = sys.argv[1]`; pyqver `pyqver2.py`/`pyqver3.py`: argparse; insta-dl
# `insta-dl.py`: a tkinter window and `mainloop()`), so discovery found no candidate and recon stopped ENTRYPOINT_UNCLEAR. A file is now also a
# candidate when an UNINDENTED line (module level, so it runs on import) reads sys.argv, parses arguments or enters a GUI main loop. A text check,
# not an AST: Python 2 scripts (pyqver2.py) do not parse under Python 3. Package, setup, test and docs files are never candidates this way.
_MODULE_LEVEL_RUN = re.compile(r"^(?![ \t#@]|import\b|from\b|def\b|class\b)[^\n]*(?:\bsys\.argv\b|\.parse_args\(|\.mainloop\(|\bgetopt\.getopt\()", re.M)
_NOT_A_SCRIPT = re.compile(r"^(?:__init__|__main__|setup|conftest|conf|test_.*|.*_test)\.py$")


def _is_module_level_script(name: str, text: str) -> bool:
    return not _NOT_A_SCRIPT.match(name) and _MODULE_LEVEL_RUN.search(text) is not None


# harness-v1.8 (T15, D-52; out-of-sample scan 2026-10-05, Frimkron/mud-pi): `simplemud.py` is a module-level `while True:` loop with no `__main__` guard,
# no argparse and no `sys.argv`, so no rule above finds it and recon ended ENTRYPOINT_UNCLEAR "no candidate scripts found" although the README says
# "run `python simplemud.py`". A script the repository's OWN README tells the reader to run is now a candidate too: a command of the form
# `python[3[.N]] [-u] <relative/path>.py [args...]` inside a code fence, an indented code block or an inline code span, whose file exists in the checkout.
# It is evidence the repository gives about itself, not a guess; the README is untrusted text like every other repository file, so the path is
# normalised (`./` dropped), must stay inside the tree, must name an existing real file (no symlink in any component, exact case, no hidden directory,
# not a setup/test/package file: `python setup.py install` is an install command, not an entrypoint) and the command line only ever reaches a model
# prompt (inside the untrusted block) and a record, never a shell: the sandbox command is still `python <candidate>` built by planner.build_plan.
# `python -m ...`, `pip install ...`, a missing path or a path outside the tree add nothing. Only scripts discovery did not already find are added (appended
# after the existing candidates, so their content and order are untouched), capped at MAX_README_ENTRYPOINTS in README order. Used by the recon / UI path
# only (`run_intake`); a corpus run names its own command and `parse_intake` leaves this off unless asked.
MAX_README_ENTRYPOINTS = 8
_README_FILE_NAMES = frozenset({"readme", "readme.md", "readme.rst", "readme.txt", "readme.markdown"})
_README_COMMAND = re.compile(r"^(?:\$\s*)?(?P<exe>python(?:3(?:\.\d+)?)?)(?P<flag>\s+-u)?\s+(?P<path>[\w.\-/]+\.py)(?=[\s;&|<>]|$)(?P<rest>.*)$")
_README_FENCE = re.compile(r"^\s*(```|~~~)")
_README_INDENTED = re.compile(r"^(?:\t| {2,})\S")
_README_INLINE_SPAN = re.compile(r"(`+)(?!`)(.+?)(?<!`)\1(?!`)")
_README_STOP_TOKENS = frozenset({"&&", "||", ";", "|", "&", ">", ">>", "2>&1", "&>"})


def _readme_texts(repo_path: Path):
    """The text of each top-level README (README, README.md/.rst/.txt/.markdown, any case), in name order; a symlinked or oversized README is not read."""
    try:
        names = sorted(os.listdir(repo_path), key=str.lower)
    except OSError:
        return
    for name in names:
        path = repo_path / name
        if name.lower() not in _README_FILE_NAMES or path.is_symlink() or not path.is_file():
            continue
        text = read_text_capped(path, data_prep.README_MAX_BYTES)
        if text is not None:
            yield text


def _readme_code_lines(text: str):
    """The README lines that sit in a code context: inside a ``` / ~~~ fence, an indented line (a tab or two spaces: markdown and RST literal blocks), and
    each inline code span (`...` or ``...``). A backslash continuation is joined to the next line."""
    lines = text.splitlines()
    fence: str | None = None
    i = 0
    while i < len(lines):
        raw = lines[i]
        i += 1
        opening = _README_FENCE.match(raw)
        if opening:
            fence = opening.group(1) if fence is None else (None if fence == opening.group(1) else fence)
            continue
        if fence is not None or _README_INDENTED.match(raw):
            line = raw.strip()
            while line.endswith("\\") and i < len(lines):
                line = line[:-1].rstrip() + " " + lines[i].strip()
                i += 1
            yield line
            if fence is not None:
                continue
        for span in _README_INLINE_SPAN.finditer(raw):
            yield span.group(2).strip()


def _readme_command(line: str) -> tuple[str, str] | None:
    """(path as written, command line) for `python[3] [-u] <path>.py [args]`, else None. The command stops at the first shell operator, redirection, comment or
    substitution, so what is recorded is the run command and nothing that follows it."""
    match = _README_COMMAND.match(line.strip())
    if match is None:
        return None
    args: list[str] = []
    for token in match.group("rest").split():
        if token in _README_STOP_TOKENS or token.startswith(("#", "$(")) or "`" in token or re.match(r"\d?>", token):
            break
        args.append(token.rstrip(";"))
        if token.endswith(";"):
            break
    command = " ".join([match.group("exe"), *(["-u"] if match.group("flag") else []), match.group("path"), *args])
    return match.group("path"), "".join(ch for ch in command if ch.isprintable())[:200]


def _named_script_exists(repo_path: Path, rel: str) -> bool:
    """True if `rel` (repository-relative, POSIX, already normalised) is a real, readable Python file in the checkout: every component present with exactly this
    spelling (the sandbox is case-sensitive), none a symlink, none hidden, and the file not one of the package / setup / test names no candidate ever is."""
    parts = rel.split("/")
    if any(part.startswith(".") for part in parts) or _NOT_A_SCRIPT.match(parts[-1]):
        return False
    current = repo_path
    for part in parts:
        try:
            if part not in os.listdir(current):
                return False
        except OSError:
            return False
        current = current / part
        if current.is_symlink():
            return False
    try:
        return current.is_file() and current.stat().st_size <= _MAX_SCANNED_FILE_BYTES
    except OSError:
        return False


def find_readme_entrypoints(repo_path: Path, exclude=()) -> dict[str, str]:
    """Scripts the repository's README tells the reader to run (see the T15 note above), as {repository-relative path: the README's command line}, in README
    order, without those in `exclude` (the candidates discovery already found)."""
    skip = set(exclude)
    found: dict[str, str] = {}
    for text in _readme_texts(repo_path):
        for line in _readme_code_lines(text):
            named = _readme_command(line)
            if named is None:
                continue
            rel = data_prep._inside(named[0])
            if rel is None or rel in found or rel in skip or not _named_script_exists(repo_path, rel):
                continue
            found[rel] = named[1]
            if len(found) >= MAX_README_ENTRYPOINTS:
                return found
    return found


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


def parse_intake(workdir: Path, commit_sha: str, *, readme_entrypoints: bool = False) -> RepoIntake:
    """Parse an already-cloned repo on disk into a `RepoIntake` — the
    local-file-only half of intake, shared by `run_intake` (clones HEAD
    itself) and the batch runner's `run_single_repo` (clones a pinned
    commit via `clone_repo_at_commit` first).

    harness-v1.8 (T15, D-52): `readme_entrypoints=True` (recon / UI path, `run_intake`) appends the scripts the repository's README names as the command to run
    and discovery did not find; off (the default: corpus runs, scripts/live_run.py) the candidates are exactly what `find_entrypoint_candidates` returns."""
    dependency_files = find_dependency_files(workdir)
    candidates = find_entrypoint_candidates(workdir)
    readme_named = find_readme_entrypoints(workdir, exclude=candidates) if readme_entrypoints else {}
    return RepoIntake(
        local_path=workdir,
        commit_sha=commit_sha,
        dependency_files=dependency_files,
        declared_dependencies=parse_declared_dependencies(dependency_files),
        notebook_paths=find_notebooks(workdir),
        entrypoint_candidates=candidates + tuple(readme_named),
        python_version_hint=detect_python_version_hint(dependency_files),
        readme_entrypoints=readme_named,
    )


def run_intake(repo_url: str, workdir: Path, shallow: bool = True) -> RepoIntake:
    """Full intake: clone, then parse. The only network/subprocess call is
    the clone itself; everything after is local file parsing."""
    commit_sha = clone_repo(repo_url, workdir, shallow=shallow)
    return parse_intake(workdir, commit_sha, readme_entrypoints=True)  # harness-v1.8 (T15): the README's own command is a candidate on this path
