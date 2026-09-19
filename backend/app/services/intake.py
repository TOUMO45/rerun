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

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import yaml

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


def find_dependency_files(repo_path: Path) -> dict[str, str]:
    found: dict[str, str] = {}
    for name in DEPENDENCY_FILENAMES:
        candidate = repo_path / name
        if candidate.is_file():
            try:
                found[name] = candidate.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
    return found


def find_notebooks(repo_path: Path) -> tuple[str, ...]:
    return tuple(
        sorted(str(p.relative_to(repo_path)) for p in repo_path.rglob("*.ipynb") if ".ipynb_checkpoints" not in p.parts)
    )


def find_entrypoint_candidates(repo_path: Path) -> tuple[str, ...]:
    candidates: set[str] = set()
    for py_file in repo_path.rglob("*.py"):
        if any(part.startswith(".") for part in py_file.parts):
            continue
        rel = str(py_file.relative_to(repo_path))
        if py_file.name in ENTRYPOINT_NAME_HINTS:
            candidates.add(rel)
            continue
        try:
            text = py_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
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


def run_intake(repo_url: str, workdir: Path, shallow: bool = True) -> RepoIntake:
    """Full intake: clone, then parse. The only network/subprocess call is
    the clone itself; everything after is local file parsing."""
    commit_sha = clone_repo(repo_url, workdir, shallow=shallow)
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
