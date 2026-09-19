"""Deterministic failure taxonomy classifier (RERUN directive §5.2).

PURE. No network calls, no model calls, no filesystem access beyond what the
caller hands it as strings. Given the exit code and captured stderr/stdout of
a sandboxed execution attempt, decide which taxonomy code best explains the
failure. This module must never call an LLM: every code path here has to be
traceable to a regex or a plain conditional a human can read in one sitting.

`classify()` is only ever called on a *failed* execution (exit_code != 0).
A clean run (exit_code == 0) is `RUNS_CLEAN` and never reaches this module.
`ENTRYPOINT_UNCLEAR` is decided by `recon.py` *before* anything executes
(see §6.1, `INDETERMINATE`) and is exposed here only as a shared constant
plus a small helper so both call sites agree on the code string.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


class TaxonomyCode:
    """String constants for every failure taxonomy code in §5.2."""

    DEP_UNPINNED_CONFLICT = "DEP_UNPINNED_CONFLICT"
    DEP_MISSING = "DEP_MISSING"
    DEP_YANKED_GONE = "DEP_YANKED_GONE"
    PY_VERSION_INCOMPAT = "PY_VERSION_INCOMPAT"
    SYS_LIB_MISSING = "SYS_LIB_MISSING"
    DATA_MISSING = "DATA_MISSING"
    DATA_CREDENTIALS = "DATA_CREDENTIALS"
    ENTRYPOINT_UNCLEAR = "ENTRYPOINT_UNCLEAR"
    HARDCODED_PATH = "HARDCODED_PATH"
    GPU_REQUIRED = "GPU_REQUIRED"
    NETWORK_BLOCKED = "NETWORK_BLOCKED"
    RUNTIME_ERROR_OTHER = "RUNTIME_ERROR_OTHER"

    FAMILY = {
        DEP_UNPINNED_CONFLICT: "Dependencies",
        DEP_MISSING: "Dependencies",
        DEP_YANKED_GONE: "Dependencies",
        PY_VERSION_INCOMPAT: "Environment",
        SYS_LIB_MISSING: "Environment",
        DATA_MISSING: "Data",
        DATA_CREDENTIALS: "Data",
        ENTRYPOINT_UNCLEAR: "Documentation",
        HARDCODED_PATH: "Code",
        GPU_REQUIRED: "Resources",
        NETWORK_BLOCKED: "Environment",
        RUNTIME_ERROR_OTHER: "Code",
    }

    ALL = tuple(FAMILY.keys())


@dataclass(frozen=True)
class Classification:
    code: str
    family: str
    evidence: str
    matched_pattern: str = ""

    def as_dict(self) -> dict:
        return {
            "code": self.code,
            "family": self.family,
            "evidence": self.evidence,
            "matched_pattern": self.matched_pattern,
        }


@dataclass(frozen=True)
class _Rule:
    code: str
    patterns: tuple[re.Pattern, ...]
    # Optional extra predicate for rules that need more than a regex match
    # (e.g. "is this module name actually undeclared?").
    extra_check: object = field(default=None)


def _p(*patterns: str) -> tuple[re.Pattern, ...]:
    return tuple(re.compile(pat, re.IGNORECASE | re.MULTILINE) for pat in patterns)


# Known distro-provided modules that are part of the standard library or
# always present, so a ModuleNotFoundError for one of these is never
# "just an undeclared pip dependency" — it points at something stranger
# (e.g. a broken venv) and should fall through toward RUNTIME_ERROR_OTHER
# rather than being misreported as DEP_MISSING.
_STDLIB_ISH = {"os", "sys", "re", "json", "typing", "itertools", "functools"}

# Common cases where the PyPI distribution name differs from the import name,
# so "declared in requirements.txt" can be matched against "what failed to
# import" without a false DEP_MISSING.
_IMPORT_TO_DIST = {
    "sklearn": "scikit-learn",
    "cv2": "opencv-python",
    "yaml": "pyyaml",
    "PIL": "pillow",
    "bs4": "beautifulsoup4",
}

_RULES: tuple[_Rule, ...] = (
    # --- Data / credentials (checked early: very specific signal) --------
    _Rule(
        TaxonomyCode.DATA_CREDENTIALS,
        _p(
            r"\b(401|403)\s+Client Error",
            r"\bUnauthorized\b.*\b(api[_ -]?key|token|login|credential)",
            r"kaggle\.json",
            r"please\s+(set|provide|configure)\s+your\s+(api[_ -]?key|token|credentials)",
            r"HTTP Basic: Access denied",
            r"authentication (required|failed)",
        ),
    ),
    # --- Dependencies ------------------------------------------------------
    _Rule(
        TaxonomyCode.DEP_UNPINNED_CONFLICT,
        _p(
            r"ResolutionImpossible",
            r"conflicting dependencies",
            r"version solving failed",
            r"Cannot install .* because these package versions have conflicting",
            r"versions? have conflicting dependencies",
        ),
    ),
    _Rule(
        TaxonomyCode.DEP_YANKED_GONE,
        _p(
            r"No matching distribution found for",
            r"Could not find a version that satisfies the requirement",
            r"404 Client Error.*pypi\.org",
            r"is not a valid editable requirement",
        ),
    ),
    _Rule(
        TaxonomyCode.DEP_MISSING,
        _p(
            r"ModuleNotFoundError:\s*No module named ['\"]([\w.\-]+)['\"]",
            r"ImportError:\s*No module named ['\"]?([\w.\-]+)['\"]?",
        ),
    ),
    # --- Environment ---------------------------------------------------
    _Rule(
        TaxonomyCode.PY_VERSION_INCOMPAT,
        _p(
            r"requires[- ]python",
            r"requires a different Python",
            r"Unsupported Python version",
            r"This package requires Python",
            r"SyntaxError: invalid syntax.*\(.*python_requires",
            r"is not supported.*Python \d\.\d+",
        ),
    ),
    _Rule(
        TaxonomyCode.SYS_LIB_MISSING,
        _p(
            r"error while loading shared libraries",
            r"cannot open shared object file",
            r"ImportError:\s*lib[\w.]+\.so",
            r"fatal error:\s*[\w./]+\.h:\s*No such file or directory",
            r"error:\s*command '.*gcc.*' failed",
        ),
    ),
    _Rule(
        TaxonomyCode.GPU_REQUIRED,
        _p(
            r"torch\.cuda\.is_available\(\)\s*is\s*False",
            r"No CUDA GPUs are available",
            r"Torch not compiled with CUDA enabled",
            r"CUDA[- ]capable device is not detected",
            r"AssertionError:.*[Cc][Uu][Dd][Aa]",
            r"RuntimeError:.*CUDA (error|driver)",
        ),
    ),
    _Rule(
        TaxonomyCode.NETWORK_BLOCKED,
        _p(
            r"Temporary failure in name resolution",
            r"Name or service not known",
            r"Network is unreachable",
            r"Connection refused",
            r"NewConnectionError",
            r"Failed to establish a new connection",
        ),
    ),
    # --- Code ------------------------------------------------------------
    _Rule(
        TaxonomyCode.HARDCODED_PATH,
        _p(
            r"FileNotFoundError.*(/home/[\w.\-]+/|/Users/[\w.\-]+/|C:\\\\Users\\\\[\w.\-]+\\\\)",
            r"No such file or directory:.*(/home/[\w.\-]+/|/Users/[\w.\-]+/|C:\\\\Users\\\\[\w.\-]+\\\\)",
        ),
    ),
    # --- Data --------------------------------------------------------------
    _Rule(
        TaxonomyCode.DATA_MISSING,
        _p(
            r"FileNotFoundError",
            r"No such file or directory",
            r"404 Client Error(?!.*pypi\.org)",
            r"URLError.*data",
        ),
    ),
)


def _undeclared_module(match: re.Match, declared_deps: frozenset[str] | None) -> bool:
    """True if the module named in a ModuleNotFoundError/ImportError match is
    not among the repo's declared dependencies (case- and alias-insensitive).

    If the caller didn't supply a declared-deps set, we can't tell whether it
    was declared, so we default to "undeclared" (best effort, per §5.2).
    """
    if declared_deps is None:
        return True
    module = match.group(1) if match.groups() else ""
    top_level = module.split(".")[0]
    candidates = {top_level.lower(), _IMPORT_TO_DIST.get(top_level, top_level).lower()}
    normalized_declared = {d.lower().replace("_", "-") for d in declared_deps}
    return not any(c.replace("_", "-") in normalized_declared for c in candidates)


def classify(
    exit_code: int,
    stderr: str,
    stdout: str = "",
    declared_deps: frozenset[str] | None = None,
) -> Classification:
    """Classify a failed sandbox execution into a taxonomy code.

    Precondition: exit_code != 0. A zero exit code is a caller bug, not a
    classification question — callers must handle RUNS_CLEAN before ever
    reaching here.
    """
    if exit_code == 0:
        raise ValueError("classify() must only be called on a non-zero exit code")

    combined = f"{stderr}\n{stdout}"

    for rule in _RULES:
        for pattern in rule.patterns:
            match = pattern.search(combined)
            if not match:
                continue
            if rule.code == TaxonomyCode.DEP_MISSING and not _undeclared_module(
                match, declared_deps
            ):
                # Declared but still failed to import: not our rule's story,
                # keep scanning other rules / fall through to the catch-all.
                continue
            evidence = match.group(0).strip()
            return Classification(
                code=rule.code,
                family=TaxonomyCode.FAMILY[rule.code],
                evidence=evidence[:500],
                matched_pattern=pattern.pattern,
            )

    tail = stderr.strip().splitlines()[-1] if stderr.strip() else f"exit code {exit_code}"
    return Classification(
        code=TaxonomyCode.RUNTIME_ERROR_OTHER,
        family=TaxonomyCode.FAMILY[TaxonomyCode.RUNTIME_ERROR_OTHER],
        evidence=tail[:500],
    )
