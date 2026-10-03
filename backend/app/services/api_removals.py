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
    # Packages the fixed release needs pinned beside it when the repository has not pinned them itself: (package, release by Python minor, default). TensorFlow 1.15.5's generated
    # protocol-buffer code fails to import under protobuf >= 3.21 ("Descriptors cannot be created directly"), and an unpinned resolve takes the newest protobuf the Python allows.
    companions: tuple[tuple[str, dict[str, str], str], ...] = ()


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
        why="the TensorFlow 1.x graph API (get_variable, placeholder, Session, train.Saver, ...) is not in TensorFlow 2",
        fixed=("1.15.5", ("3.7", "3.6")),
        companions=(("protobuf", {"3.6": "3.19.6"}, "3.20.3"),),
    ),
)


def match(text: str) -> tuple[Removal, str] | None:
    """The first rule whose signature is in `text`, with the matched text (the evidence the env gate checks verbatim against the log); None if no rule matches."""
    for rule in RULES:
        found = rule.pattern.search(text or "")
        if found:
            return rule, found.group(0)
    return None


def companion_pins(rule: Removal, python: str) -> tuple[tuple[str, str], ...]:
    """(package, release) of the companions to pin beside the rule's package on `python`."""
    return tuple((name, by_python.get(python, default)) for name, by_python, default in rule.companions)


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
