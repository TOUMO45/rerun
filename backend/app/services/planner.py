"""Planner (RERUN directive §3 must-have #2): produces an explicit,
inspectable build plan *before* anything executes.

Deliberately mostly deterministic, plain code — which dependency file is
present dictates the install command, full stop. Nemotron Super is only
consulted for the one thing plain code can't decide: which base Docker
image / apt packages a given declared dependency set is likely to need
(e.g. `opencv-python` usually wants `libgl1`). This matches §2.8's
anti-goal ("the repair loop must be explicit code the judges can read, not
hidden inside a framework abstraction") extended to planning: a judge
reading `build_plan()` should be able to predict its output for a given
`RepoIntake` without running an LLM in their head.

If the model step fails or returns nothing useful, planning still
succeeds with the deterministic base plan — the model call here is an
enhancement, not a dependency, unlike recon's entrypoint decision.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.services.intake import RepoIntake
from app.services.model_client import ModelCallError, call_json_model
from app.services.recon import ReconResult

_APT_SYSTEM_PROMPT = """You install system (apt) packages for Python ML/data-science \
repos before pip install runs, based on their declared pip dependencies. Respond with \
ONLY a JSON object: {"apt_packages": ["<package names>"]} — an empty list if none of \
the declared dependencies are known to need one. Only include packages you are \
genuinely confident about (e.g. opencv-python needs libgl1 and libglib2.0-0); when \
unsure, return an empty list rather than guessing."""

# Small, deterministic, well-known table for dependencies that commonly need
# a system library — used as a fallback/floor even if the model step is
# skipped or fails, so DEMO_MODE and credential-less test runs still get a
# reasonable plan for common cases.
_KNOWN_APT_NEEDS: dict[str, tuple[str, ...]] = {
    "opencv-python": ("libgl1", "libglib2.0-0"),
    "opencv-python-headless": ("libglib2.0-0",),
}


@dataclass(frozen=True)
class BuildPlan:
    base_image: str
    apt_install: tuple[str, ...]
    install_commands: tuple[str, ...]
    execute_command: str
    notes: tuple[str, ...] = field(default_factory=tuple)

    def as_dict(self) -> dict:
        return {
            "base_image": self.base_image,
            "apt_install": list(self.apt_install),
            "install_commands": list(self.install_commands),
            "execute_command": self.execute_command,
            "notes": list(self.notes),
        }

    def as_shell_steps(self) -> tuple[str, ...]:
        """The exact ordered shell commands the sandbox will run, in order —
        this is the "explicit, inspectable build plan" §3 requires the UI
        to render before anything executes (§8 S2's "Build plan" stage)."""
        steps = []
        if self.apt_install:
            steps.append("apt-get update && apt-get install -y " + " ".join(self.apt_install))
        steps.extend(self.install_commands)
        return tuple(steps)


def _base_image_for(python_version_hint: str | None) -> str:
    default = "python:3.11-slim"
    if not python_version_hint:
        return default
    # Only trust an exact-looking "3.x" hint for the image tag; anything
    # more complex (range specifiers like ">=3.8,<3.11") stays on the
    # directive's fixed 3.11 default rather than guessing which point
    # release to pick.
    digits = python_version_hint.strip()
    if digits.replace(".", "").isdigit() and digits.count(".") == 1:
        return f"python:{digits}-slim"
    return default


def _deterministic_install_commands(intake: RepoIntake) -> tuple[str, ...]:
    commands: list[str] = []
    files = intake.dependency_files
    if "requirements.txt" in files:
        commands.append("pip install -r requirements.txt")
    elif "environment.yml" in files or "environment.yaml" in files:
        commands.append("pip install -r <(python -c \"import yaml,sys; d=yaml.safe_load(open('environment.yml')); "
                         "print('\\n'.join(p for p in (d.get('dependencies') or []) if isinstance(p,str) and p!='python'))\")")
    elif "pyproject.toml" in files:
        commands.append("pip install .")
    elif "setup.py" in files:
        commands.append("pip install .")
    else:
        commands.append("true  # no declared dependency file found; nothing to install")
    return tuple(commands)


def _known_apt_packages(declared_dependencies: frozenset[str]) -> tuple[str, ...]:
    found: set[str] = set()
    for dep in declared_dependencies:
        found.update(_KNOWN_APT_NEEDS.get(dep.lower(), ()))
    return tuple(sorted(found))


def build_plan(
    intake: RepoIntake,
    recon: ReconResult,
    *,
    client=None,
    model: str | None = None,
    cost_guard=None,
) -> BuildPlan:
    """Build the deterministic base plan, then optionally enrich apt
    packages via Nemotron Super. `client`/`model` are optional — omitting
    them (or the model call failing) still produces a valid, honest plan
    from the deterministic table alone; a `notes` entry records which path
    was taken so the certificate is never silent about it.
    """
    if recon.is_indeterminate or not recon.entrypoint:
        raise ValueError("build_plan requires a non-indeterminate recon result with a chosen entrypoint")

    notes: list[str] = []
    base_image = _base_image_for(recon.python_version or intake.python_version_hint)
    install_commands = _deterministic_install_commands(intake)
    apt_packages = set(_known_apt_packages(intake.declared_dependencies))

    if client is not None and model is not None:
        try:
            raw = call_json_model(
                client,
                model=model,
                system_prompt=_APT_SYSTEM_PROMPT,
                user_prompt=f"Declared pip dependencies: {sorted(intake.declared_dependencies)}",
                cost_guard=cost_guard,
            )
            model_apt = raw.get("apt_packages") or []
            if isinstance(model_apt, list):
                apt_packages |= {str(p) for p in model_apt}
                notes.append("apt package list enriched by Nemotron Super")
        except ModelCallError as exc:
            notes.append(f"apt-package model enrichment skipped: {exc}")
    else:
        notes.append("apt package list from the deterministic known-needs table only (no model client supplied)")

    return BuildPlan(
        base_image=base_image,
        apt_install=tuple(sorted(apt_packages)),
        install_commands=install_commands,
        execute_command=f"python {recon.entrypoint}",
        notes=tuple(notes),
    )
