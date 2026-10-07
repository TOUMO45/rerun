"""harness-v1.8 (T3): two deterministic repairs of the INSTALL LINES a repository (or RERUN's plan from its README) carries, found in the records of two
held-out entries (now DEV-CONTAMINATED):

  - TEST-B #3 alexlee-gk/video_prediction: the requirements name `git+git://github.com/alexlee-gk/lpips-tensorflow.git`; GitHub switched off the
    unauthenticated `git://` protocol on 2022-03-15, so `git clone` times out (`fatal: unable to connect to github.com: ... Connection timed out`;
    reproduced 2026-10-07: `git ls-remote git://github.com/...` times out, the `https://` URL answers). pip's wrapper line
    (`error: subprocess-exited-with-error`) was recorded as the cause. pip also needs the `git` binary for any `git+` requirement.
  - The same entry's plan carried `apt libgl1-mesa-glx`, a package Debian 12 no longer ships: `E: Package 'libgl1-mesa-glx' has no installation
    candidate`, classified RUNTIME_ERROR_OTHER, which skipped the time machine and left 9 repair attempts to patch around an apt line.

PURE. No network, no model call, no filesystem. NOT sandbox-touching: the orchestrator applies the result through the plan's existing fields.
The repository's own files are never edited (the rewrite goes into RERUN's copy of the requirements, `.rerun-requirements.txt`), and every use is a
recorded, labelled DEPENDENCY CHANGE (`outcome_levels.dependency_change`).
"""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass, replace

from app.services import env_repair, system_packages

GIT_PROTOCOL_RULE = "git_protocol_rewrite"
APT_RENAME_RULE = "apt_package_renamed"

_GIT_CLONE_FAIL = re.compile(r"(?:fatal: unable to connect to github\.com|git clone [^\n]*git://github\.com/[^\n]*did not run successfully|"
                             r"Could not read from remote repository)")


@dataclass(frozen=True)
class InstallFix:
    rule: str
    key: str  # one use per run per key
    evidence: str  # a line of the failing log, verbatim
    detail: dict  # what changed, for the recorded action
    plan: object  # the new BuildPlan
    requirements: str | None  # RERUN's copy of the requirements text, or None when the plan has none


def _log_line(log: str, needle_re: re.Pattern) -> str | None:
    m = needle_re.search(log)
    if not m:
        return None
    start = log.rfind("\n", 0, m.start()) + 1
    end = log.find("\n", m.end())
    return log[start: end if end != -1 else len(log)].strip()


def _rewrite_requirements(plan, requirements: str | None):
    """(new plan, new requirements text or None, number of rewritten lines, lines as written -> as rewritten). Only github.com's `git://` is touched."""
    pairs: list[dict] = []
    new_text = None
    install = list(plan.install_commands)
    if requirements is not None and system_packages.vcs_git_protocol_lines(requirements):
        lines = requirements.splitlines()
        out = []
        for line in lines:
            fixed, n = system_packages.rewrite_git_protocol(line)
            if n:
                pairs.append({"from": line.strip(), "to": fixed.strip()})
            out.append(fixed)
        new_text = "\n".join(out) + "\n"
        write = f"printf '%s\\n' {' '.join(shlex.quote(line) for line in out)} > {env_repair.REQUIREMENTS_OVERRIDE_FILE}"
        install = [
            f"{write} && pip install -r {env_repair.REQUIREMENTS_OVERRIDE_FILE}"
            if cmd.strip() == "pip install -r requirements.txt" or cmd.endswith(f"pip install -r {env_repair.REQUIREMENTS_OVERRIDE_FILE}")
            else cmd
            for cmd in install
        ]
    if new_text is not None and install == list(plan.install_commands):
        # review (LOW): the file was rewritten but no install command reads the override copy, so nothing would have used it: not recorded as applied
        pairs, new_text = [], None
    # inline occurrences in any install command (a printf of the requirements the repair built earlier, or `pip install git+git://...`)
    for i, cmd in enumerate(install):
        fixed, n = system_packages.rewrite_git_protocol(cmd)
        if n:
            pairs.append({"from": f"(install command {i + 1}) git://github.com/", "to": "https://github.com/"})
            install[i] = fixed
    if not pairs:
        return None
    return replace(plan, install_commands=tuple(install)), new_text, pairs


def fix_for(log: str, plan, requirements: str | None, applied: frozenset[str] = frozenset()) -> InstallFix | None:
    """The first install-line repair the failing `log` calls for, or None. `applied` holds the keys already used in this run (each once)."""
    log = log or ""
    # 1. a Debian package that has been renamed (the apt step failed, so no layer holds it: the plan's apt list is what changes)
    renamed = system_packages.renamed_apt_package(log)
    if renamed is not None:
        old, new, line = renamed
        key = f"{APT_RENAME_RULE}:{old}"
        if old in plan.apt_install and key not in applied:
            apt = tuple(sorted((set(plan.apt_install) - {old}) | {new}))
            return InstallFix(APT_RENAME_RULE, key, line, {"package": old, "from": old, "to": new}, replace(plan, apt_install=apt), None)
    # 2. the retired git:// protocol
    line = _log_line(log, _GIT_CLONE_FAIL)
    if line is not None and "git://github.com/" in (log + " ".join(plan.install_commands) + (requirements or "")):
        key = GIT_PROTOCOL_RULE
        rewritten = _rewrite_requirements(plan, requirements)
        if rewritten is not None and key not in applied:
            new_plan, new_text, pairs = rewritten
            apt = tuple(sorted(set(new_plan.apt_install) | {"git"}))  # pip needs the git binary for any `git+` requirement
            new_plan = replace(new_plan, apt_install=apt)
            return InstallFix(GIT_PROTOCOL_RULE, key, line, {"lines": pairs, "apt_added": [p for p in apt if p not in plan.apt_install]}, new_plan, new_text)
    return None
