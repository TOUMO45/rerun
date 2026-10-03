"""Error chain and attribution (Phase 2).

PURE. Every classified failure a run sees, in order, each with an attribution:

  REPO            the repository is at fault (undeclared dependency, code bug,
                  a Python-version failure under a version the repo accepts, ...)
  ENV             RERUN's runner caused it (a package the repo DOES declare that we
                  failed to install; torch, which the runner provides by policy; a
                  Python version the repo never claimed; runner network policy; a
                  base image whose distribution left the apt mirrors, APT_MIRROR_GONE)
  SANDBOX_QUOTA   a Nebius infrastructure limit (upload rejected, fs delta, disk full)
  PLATFORM        the platform refuses to load a valid artifact (SANDBOX_INCOMPAT)

A link is `{error, class, attribution, phase, cleared_by}`; `cleared_by` is the repair
attempt after which the run no longer failed this way: a different error followed it, or
(harness-v1.6, `clear_last`) the run passed. None if the error was never seen to clear.

`first_repo_error` = the first link attributed REPO, whether or not a later repair
cleared it. `last_error` = the last link, kept for debugging. ENV / SANDBOX_* / PLATFORM
failures are reported separately and excluded from the Reproducibility Recovery Rate.

Deliberate exception to "undeclared package -> REPO": `torch`, `torchvision` and
`torchaudio` are provided by the runner (phase 3), so their absence is ENV even when the
repo does not declare them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

REPO = "REPO"
ENV = "ENV"
SANDBOX_QUOTA = "SANDBOX_QUOTA"
PLATFORM = "PLATFORM"

RUNNER_PROVIDED_PACKAGES = frozenset({"torch", "torchvision", "torchaudio"})

# Where in the run a failure happened (harness-v1.3.2). Attribution keys on this FIRST.
PHASE_RUNNER_SETUP = "runner_setup"  # RERUN's own ops, before the repo's first command
PHASE_REPO_INSTALL = "repo_install"  # the repo's install commands
PHASE_REPO_RUN = "repo_run"          # the repo's command
PHASES = (PHASE_RUNNER_SETUP, PHASE_REPO_INSTALL, PHASE_REPO_RUN)

_MISSING_MODULE = re.compile(r"No module named ['\"]?([\w.\-]+)['\"]?")

# Python-3.x incompatibilities that are properties of the interpreter, not of the
# repo's logic: removed/moved stdlib names. Each pattern is documented, not guessed.
PY_INCOMPAT_PATTERNS: tuple[re.Pattern, ...] = tuple(
    re.compile(p) for p in (
        r"cannot import name '(?:Iterable|Mapping|MutableMapping|Sequence|Callable|Hashable|Sized|Container|"
        r"Set|MutableSet|MutableSequence|Generator|Iterator)' from 'collections'",
        r"module 'collections' has no attribute '(?:Iterable|Mapping|MutableMapping|Sequence|Callable)'",
        r"module 'inspect' has no attribute '(?:getargspec|formatargspec)'",
        r"module 'asyncio' has no attribute 'coroutine'",
        r"module 'time' has no attribute 'clock'",
        r"No module named '(?:distutils|imp|asynchat|asyncore|smtpd)(?:\.[\w.]+)?'",
        r"Missing parentheses in call to 'print'",
    )
)


def is_python_incompat(text: str) -> bool:
    return any(p.search(text) for p in PY_INCOMPAT_PATTERNS)


def python_minor(base_image: str | None) -> tuple[int, int] | None:
    """(3, 11) from 'python:3.11-slim'; None if the image tag carries no version."""
    m = re.search(r"python:(\d+)\.(\d+)", base_image or "")
    return (int(m.group(1)), int(m.group(2))) if m else None


def claim_accepts(claim: str | None, chosen: tuple[int, int] | None) -> bool | None:
    """Does the repo's declared Python claim accept `chosen`? None = no claim (or no way
    to tell). `claim` is an exact 'X.Y' or a PEP 440 specifier set ('>=3.6,<3.9')."""
    if not claim or chosen is None:
        return None
    text = claim.strip()
    version = f"{chosen[0]}.{chosen[1]}"
    if re.fullmatch(r"\d+\.\d+(\.\d+)?", text):
        return text.split(".")[:2] == [str(chosen[0]), str(chosen[1])]
    try:
        from packaging.specifiers import SpecifierSet

        return SpecifierSet(text).contains(version, prereleases=True)
    except Exception:  # noqa: BLE001 - an unparseable claim is "no claim"
        return None


def _module_of(evidence: str) -> str | None:
    m = _MISSING_MODULE.search(evidence or "")
    return m.group(1) if m else None


def _declared(module: str, declared_deps: frozenset[str] | None) -> bool | None:
    if declared_deps is None:
        return None
    from app.services.import_names import dist_for_import

    top = module.split(".")[0]
    names = {top.lower(), dist_for_import(top).lower()}
    normalized = {d.lower().replace("_", "-") for d in declared_deps}
    return any(n.replace("_", "-") in normalized for n in names)


def attribute(
    code: str,
    evidence: str,
    *,
    declared_deps: frozenset[str] | None,
    python_claim: str | None,
    base_image: str | None,
    phase: str = PHASE_REPO_RUN,
) -> str:
    """The attribution of one classified failure (see the module docstring).

    INVARIANT (harness-v1.3.2): a failure raised while a RUNNER SETUP op was executing is ENV, PLATFORM or SANDBOX_QUOTA,
    never REPO, whatever the error text says. Attempt 1, entry 3: RERUN's own `patchelf --clear-execstack` failed on
    python:3.6-slim and the text ("getting info about ...: No such file or directory") was read as DATA_MISSING/REPO."""
    if phase == PHASE_RUNNER_SETUP:
        return SANDBOX_QUOTA if code in ("SANDBOX_QUOTA", "RESOURCE_LIMIT") else PLATFORM if code == "SANDBOX_INCOMPAT" else ENV
    if code in ("SANDBOX_QUOTA", "RESOURCE_LIMIT"):  # harness-v1.4.2-rc: a SIGKILL (the sandbox's resource limit) is an infrastructure limit, not the repository's error
        return SANDBOX_QUOTA
    if code == "SANDBOX_INCOMPAT":
        return PLATFORM
    if code == "NETWORK_BLOCKED":
        return ENV  # runner network policy, not a repo property
    if code == "APT_MIRROR_GONE":
        # harness-v1.6: the base image RERUN chose has a distribution the apt mirrors no longer serve (an archived
        # Debian release). The repository cannot fix which image it runs on; the orchestrator ends the run
        # INDETERMINATE on this code (`_note_failure`), never BLOCKED.
        return ENV
    if code == "PY_VERSION_INCOMPAT" or is_python_incompat(evidence):
        accepted = claim_accepts(python_claim, python_minor(base_image))
        return REPO if accepted else ENV  # accepted -> repo code breaks on a claimed version; else we chose it
    module = _module_of(evidence)
    if module is not None:
        top = module.split(".")[0].lower()
        if top in RUNNER_PROVIDED_PACKAGES:
            return ENV
        if _declared(module, declared_deps):
            return ENV  # the repo declares it and our runner failed to install it
        return REPO  # imported but not declared: undeclared dependency
    return REPO


@dataclass
class ErrorChain:
    """Ordered failures of one run. `record()` collapses consecutive repeats of the same
    error and, when a different error follows, marks the previous link cleared by the
    attempt that produced the change."""

    links: list[dict] = field(default_factory=list)

    def record(self, attempt_number: int, code: str, error: str, attribution: str, phase: str = PHASE_REPO_RUN) -> None:
        if self.links and self.links[-1]["error"] == error and self.links[-1]["class"] == code:
            return
        # Whatever fails after a platform refusal / exhausted quota is a consequence of it (the
        # pilot's repairer went on to `apt install execstack`), never the repository's fault.
        upstream = next((l["attribution"] for l in self.links if l["attribution"] in (PLATFORM, SANDBOX_QUOTA)), None)
        if upstream and attribution == REPO:
            attribution = upstream
        if self.links and self.links[-1]["cleared_by"] is None:
            self.links[-1]["cleared_by"] = attempt_number
        self.links.append({"error": error, "class": code, "attribution": attribution, "phase": phase, "cleared_by": None})

    def clear_last(self, attempt_number: int) -> None:
        """harness-v1.6: the run PASSED after `attempt_number`, so the last failure is no longer the failure. Before v1.6 a
        link was only marked cleared when a different error followed it, and a RUNS_AFTER_REPAIR record kept `cleared_by:
        None` on the failure the repair had just cleared (every stored record up to harness-v1.5.2 reads that way; the outcome
        ladder, outcome_levels.py, reads those older records through the verdict instead)."""
        if self.links and self.links[-1]["cleared_by"] is None:
            self.links[-1]["cleared_by"] = attempt_number

    def as_list(self) -> list[dict]:
        return [dict(link) for link in self.links]

    @property
    def first_repo_error(self) -> str | None:
        return next((link["error"] for link in self.links if link["attribution"] == REPO), None)

    @property
    def last_error(self) -> str | None:
        return self.links[-1]["error"] if self.links else None


CLASSIFIER_LINE = re.compile(r"^\[classifier\] (?P<code>[A-Z_]+): (?P<msg>.*)$")


def chain_from_log(
    log: str,
    *,
    declared_deps: frozenset[str] | None,
    python_claim: str | None,
    base_image: str | None,
) -> ErrorChain:
    """Rebuild the chain from a stored `[classifier]` log (frozen records carry no chain).
    `cleared_by` is not recoverable from the classifier lines alone, so it is set to the
    ordinal of the next classifier line (baseline = 0)."""
    chain = ErrorChain()
    ordinal = 0
    for line in log.splitlines():
        m = CLASSIFIER_LINE.match(line.strip())
        if not m:
            continue
        code = m["code"]
        # Frozen logs predate the sandbox classes: re-read the evidence with today's rules, but only
        # to move a line INTO a sandbox class (the pilot labelled the exec-stack refusal SYS_LIB_MISSING).
        from app.services import classifier

        recoded = classifier.classify(1, m["msg"]).code
        if recoded in classifier.TaxonomyCode.SANDBOX_CODES:
            code = recoded
        chain.record(
            ordinal, code, m["msg"],
            attribute(code, m["msg"], declared_deps=declared_deps, python_claim=python_claim, base_image=base_image),
        )
        ordinal += 1
    return chain
