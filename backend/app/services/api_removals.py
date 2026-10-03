"""Removed-API version bounds (harness-v1.5.1, F2; failure class: the code uses an API that a NEWER release of a package removed).

A repository written against torch 1.5 or TensorFlow 1.x fails on a fresh install with an error that says exactly which API is gone and nothing else is wrong with the
environment: `ImportError: cannot import name 'zero_gradients' from 'torch.autograd.gradcheck'` (torch removed it in 1.9), `AttributeError: module 'tensorflow' has no
attribute 'get_variable'` (TensorFlow 2 removed the 1.x graph API). The repair is not a code patch but an older release of that one package, on a Python that can install it.
DEV entries 17 and 12 (records harness-v1.5.0/dev/17_Haichao-Zhang__FeatureScatter.json, 12_Mehran-k__SimplE.json): the model proposed source patches and a `torch<1.9.0`
pin the Python 3.10 image could not install, and neither entry got past it.

This module is the table and the arithmetic, pure: `match(text)` finds a rule in a failing run's output, `plan(rule, python)` gives the env changes (a `pin` of one exact
release and, when the current Python cannot install it, a `python` change). The orchestrator applies them through the SAME env gate a model proposal faces, as a deterministic
step before any model call, and records it as `time_machine_action`. A rule exists only for a failure that has been RECORDED (METHODOLOGY, protocol rule G): a signature that
nobody has seen fail is not a rule. The exact release and the Pythons that can install it are data from the package's own wheel listing (torch: torch_wheels, the PyTorch CPU
index snapshot; TensorFlow 1.15.5: PyPI, cp36 and cp37 manylinux2010 wheels, retrieved 2026-10-02).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.services import python_policy, torch_wheels

_PYTHON_ORDER = {minor: i for i, minor in enumerate(python_policy.PREFERENCE)}


@dataclass(frozen=True)
class Removal:
    rule: str
    pattern: re.Pattern
    package: str
    bound: str  # the documented bound the pin satisfies ("<1.9")
    why: str
    # None: the exact release and its Pythons come from the torch wheel snapshot; otherwise (release, Pythons that can install it) from the package's own wheel listing.
    fixed: tuple[str, tuple[str, ...]] | None = None
    # Packages the fixed release needs pinned beside it (see Companion).
    companions: tuple["Companion", ...] = ()
    # Other distributions that provide the same import and would conflict with the pinned release (`tensorflow-gpu`, `tensorflow-cpu` in a lock written for TensorFlow 2): when the
    # requirements or the lock hold one, it is REMOVED (the pinned release provides the import); it is never pinned to the old family (PyPI has no tensorflow-cpu 1.15.5).
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class Companion:
    """A package pinned beside the rule's release. `mode`:
      "ensure"             pin it unless the repository's requirements / era lock already pin it with `==` to a release below `ok_below` (TensorFlow 1.15.5's generated protocol-buffer
                           code fails to import under protobuf >= 3.21, "Descriptors cannot be created directly", and an unpinned resolve takes the newest protobuf the Python allows);
      "replace_if_present" pin it only if the requirements / lock hold it, unless that pin is `==` and below `ok_below` (when given): the requirements or the era lock pin it to the
                           release of the NEWER family and the older release cannot be installed beside that. DEV entry 12, harness-v1.5.1 round 2: an era lock for TensorFlow 2.1 holds
                           `tensorboard==2.1.0` and `tensorflow-estimator==2.1.0`, and pip answered `Cannot install ... tensorboard==2.1.0 ... conflicting dependencies`. TensorFlow 1.15.5
                           requires gast==0.2.2, numpy<1.19, protobuf>=3.6.1, tensorboard>=1.15.0,<1.16.0 and tensorflow-estimator==1.15.1 (PyPI metadata retrieved 2026-10-03).
    `by_python` overrides `release` for a Python minor. A name absent from the requirements is never added in mode "replace_if_present": pip resolves it from the new release's own metadata."""
    package: str
    release: str
    mode: str = "replace_if_present"
    by_python: tuple[tuple[str, str], ...] = ()
    ok_below: str = ""

    def __post_init__(self) -> None:
        if self.mode not in ("ensure", "replace_if_present"):
            raise ValueError(f"unknown companion mode {self.mode!r}")


_PIN = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)(?:\[[^\]]*\])?\s*==\s*([0-9][^\s;#,]*)")


def _name(line: str) -> str:
    match = re.match(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)", line)
    return re.sub(r"[-_.]+", "-", match.group(1)).lower() if match else ""


def _norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _exact_pin(lines: list[str], package: str):
    """The `==` release some line pins `package` to (a packaging Version), or None (absent, unpinned, a range, or no `packaging`)."""
    try:
        from packaging.version import Version
    except Exception:  # noqa: BLE001
        return None
    for line in lines:
        found = _PIN.match(line)
        if found and _norm(found.group(1)) == _norm(package):
            try:
                return Version(found.group(2))
            except Exception:  # noqa: BLE001
                continue
    return None


def _limit(below: str):
    try:
        from packaging.version import Version

        return Version(below)
    except Exception:  # noqa: BLE001
        return None


RULES: tuple[Removal, ...] = (
    Removal(
        rule="removed_api_torch_zero_gradients",
        pattern=re.compile(r"cannot import name 'zero_gradients' from 'torch\.autograd\.gradcheck'"),
        package="torch",
        bound="<1.9",
        why="torch.autograd.gradcheck.zero_gradients was removed in torch 1.9",
    ),
    Removal(
        rule="removed_api_tensorflow_v1_graph_api",
        # only the two attributes a record shows (DEV entry 12); another TensorFlow 1 name needs its own recorded failure first (protocol rule G)
        pattern=re.compile(r"module 'tensorflow(?:_core)?(?:\._api\.v2)?(?:\.\w+)?' has no attribute '(?:get_variable|Saver)'"),
        package="tensorflow",
        bound="<2",
        why="the TensorFlow 1.x graph API (get_variable, Saver, ...) is not in TensorFlow 2",
        fixed=("1.15.5", ("3.7", "3.6")),
        companions=(
            Companion("protobuf", "3.20.3", "ensure", (("3.6", "3.19.6"),), ok_below="3.21"),
            Companion("tensorboard", "1.15.0", "replace_if_present"),
            Companion("tensorflow-estimator", "1.15.1", "replace_if_present"),
            Companion("gast", "0.2.2", "replace_if_present"),
            Companion("numpy", "1.18.5", "replace_if_present", ok_below="1.19"),
        ),
        aliases=("tensorflow-gpu", "tensorflow-cpu"),
    ),
)


def match(text: str) -> tuple[Removal, str] | None:
    """The first rule whose signature is in `text`, with the matched text (the evidence the env gate checks verbatim against the log); None if no rule matches."""
    for rule in RULES:
        found = rule.pattern.search(text or "")
        if found:
            return rule, found.group(0)
    return None


def companion_actions(rule: Removal, python: str, requirement_lines: list[str]) -> list[tuple[str, str, str | None]]:
    """What to do beside the rule's own pin, given the requirements / era lock (their lines; [] if there are none): [("pin", package, release) | ("remove", alias, None)], in order.
    Pure."""
    held = {_name(line) for line in requirement_lines}
    out: list[tuple[str, str, str | None]] = []
    for alias in rule.aliases:
        if _norm(alias) in held:
            out.append(("remove", alias, None))
    for c in rule.companions:
        present = _norm(c.package) in held
        exact, limit = _exact_pin(requirement_lines, c.package), (_limit(c.ok_below) if c.ok_below else None)
        release = dict(c.by_python).get(python, c.release)
        if c.mode == "ensure":
            # a protobuf the release can import: pinned (==) below the limit; absent, unpinned, a range or pinned above the limit is replaced by the pin
            if not (exact is not None and limit is not None and exact < limit):
                out.append(("pin", c.package, release))
        elif present:
            # replace_if_present: with a limit, only an exact pin at or above it is swapped (an unpinned or ranged line is left to pip, which resolves it under the new release's own
            # requirement); without one, whatever pins it is swapped
            if limit is None or (exact is not None and exact >= limit):
                out.append(("pin", c.package, release))
    return out


def plan(rule: Removal, python: str) -> tuple[str, str | None, str] | None:
    """(release to pin, Python to move to or None to stay, reason) or None when no release satisfies the bound on any available Python.
    Stays on `python` whenever it can install the release; otherwise the policy's most preferred Python that can."""
    if rule.fixed is not None:
        release, minors = rule.fixed
    else:
        minors = torch_wheels.minors_with_wheel(rule.bound)
        release = None
    if not minors:
        return None
    pick = python if python in minors else min(minors, key=lambda m: _PYTHON_ORDER.get(m, 99))
    if release is None:
        release = torch_wheels.newest_release(rule.bound, pick)
    if release is None:
        return None
    move = None if pick == python else pick
    reason = f"{rule.why}; {rule.package}{rule.bound} -> {rule.package}=={release}" + (f" on Python {pick} (Python {python} cannot install it)" if move else f" (Python {python} installs it)")
    return release, move, reason
