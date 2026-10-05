"""Blocker report (harness-v1.6, item B).

PURE. No network, no model call. From the LAST link of a stored result's `error_chain`, one record that says what is
in the way of the repository running, who can remove it and what a human would have to supply:

  class / family / phase / attribution   copied from the link (family from the taxonomy)
  evidence                               the link's error line, at most 300 characters
  fixable_by                             "deterministic" (RERUN's own rules: the time machine, the era lock, the
                                         interpreter policy, the apt rule), "model" (a code change the repairer
                                         proposes and the tamper gate decides), "human" (data, credentials, a GPU,
                                         a command only the authors know) or "platform" (the sandbox, the mirrors)
  what_a_human_must_supply               one sentence from a FIXED per-class table, with the package / path / module
                                         filled in from the evidence line when a regex finds it
  sources                                None (the Tavily lookup, item S, is not implemented here)

Why a fixed table and not prose from a model: the certificate is read by someone who did not run the audit, and the
same class must always say the same thing. Every TaxonomyCode has a row (a test asserts it); there is no default row,
so a code added to the taxonomy without a row fails loudly instead of printing nothing.

`report()` is None for a RUNS_CLEAN or RUNS_AFTER_REPAIR verdict (nothing blocks) and for an empty chain (nothing was classified: an
INDETERMINATE decided before execution, a pipeline error).
"""

from __future__ import annotations

import logging
import re

from app.services.classifier import TaxonomyCode

logger = logging.getLogger(__name__)

EVIDENCE_MAX_CHARS = 300

DETERMINISTIC = "deterministic"
MODEL = "model"
HUMAN = "human"
PLATFORM = "platform"

# Templates. `{package}`, `{path}`, `{module}` and `{limit}` are filled from the evidence line; when the regex finds
# nothing the generic wording in `_FALLBACK` is used, so the sentence never carries an empty hole or angle brackets.
_RELEASE = "nothing, if the era lock resolves it; otherwise the exact release of {package} the authors used"
_RELEASE_API = "nothing, if the era lock or a removed-API row resolves it; otherwise the release of {package} the authors used (older or newer)"
_FALLBACK = {"package": "the package", "path": "the path the code opens", "module": "the module", "limit": "the limit"}

# One row per TaxonomyCode: (fixable_by, what_a_human_must_supply). GPU_REQUIRED's sentence depends on the evidence
# (see `_gpu_sentence`); its row holds the general wording.
TABLE: dict[str, tuple[str, str]] = {
    TaxonomyCode.DEP_MISSING: (DETERMINISTIC, _RELEASE),
    TaxonomyCode.DEP_YANKED: (DETERMINISTIC, _RELEASE),
    TaxonomyCode.DEP_UNPINNED_CONFLICT: (DETERMINISTIC, _RELEASE),
    TaxonomyCode.DEP_NOT_ON_PYPI: (DETERMINISTIC, _RELEASE),
    TaxonomyCode.API_REMOVED: (DETERMINISTIC, _RELEASE_API),
    TaxonomyCode.PY_VERSION_INCOMPAT: (DETERMINISTIC, "nothing, if the interpreter policy resolves it; otherwise the Python version the authors used"),
    TaxonomyCode.SYS_LIB_MISSING: (DETERMINISTIC, "nothing, if the apt rule resolves it; otherwise the system package that provides {package}"),
    TaxonomyCode.DEP_BUILD_FAILED: (DETERMINISTIC, "nothing, if the apt rule adds the build dependencies; otherwise a wheel of {package} for this platform"),
    TaxonomyCode.DATA_MISSING: (HUMAN, "the dataset the repository expects at {path}, obtained as its README describes"),
    TaxonomyCode.DATA_CREDENTIALS: (HUMAN, "the credentials (an API key, token or login) the download step asks for"),
    TaxonomyCode.GPU_REQUIRED: (HUMAN, "a CUDA device, or the CPU shim where the call is a plain .cuda()"),
    TaxonomyCode.HARDCODED_PATH: (MODEL, "nothing: the repairer proposes a relative path at {path} and the tamper gate decides"),
    TaxonomyCode.ENTRYPOINT_UNCLEAR: (HUMAN, "the command to run: the README does not name one unambiguously"),
    TaxonomyCode.NETWORK_BLOCKED: (PLATFORM, "an egress rule for the host the code reaches, or the file it downloads"),
    TaxonomyCode.RUNTIME_ERROR_OTHER: (MODEL, "a code change; the repairer proposes one and the tamper gate decides"),
    TaxonomyCode.APT_MIRROR_GONE: (PLATFORM, "a base image whose distribution is still on the mirrors"),
    TaxonomyCode.SANDBOX_QUOTA: (PLATFORM, "a sandbox with a larger quota ({limit})"),
    TaxonomyCode.SANDBOX_INCOMPAT: (PLATFORM, "a sandbox that loads this artifact ({limit})"),
    TaxonomyCode.RESOURCE_LIMIT: (PLATFORM, "a sandbox with more resources ({limit})"),
}

# Classes that records written before a taxonomy change carry (DEP_YANKED_GONE was split into DEP_YANKED and DEP_NOT_ON_PYPI
# on 2026-09-24): read as the row of the class they became. An explicit list, not a fallthrough: any other unknown class
# is a programming error and raises.
_HISTORICAL: dict[str, str] = {"DEP_YANKED_GONE": TaxonomyCode.DEP_YANKED}

# GPU_REQUIRED: the operation has no CPU implementation at all, so no shim can stand in for the device. "Cannot access
# accelerator device when none is available" is NOT that (v1.6 review, defect 5): it says no GPU is present, and the
# CPU shim may still answer it, so it gets the general sentence.
_NO_CPU_KERNEL = re.compile(r"is not implemented on the CPU", re.IGNORECASE)
_GPU_NO_CPU_SENTENCE = "a CUDA device: the operation has no CPU implementation"

# Placeholder extraction. Each list is tried in order; the first match wins.
_PATH_RES = (
    re.compile(r"(?:No such file or directory|FileNotFoundError)[^'\"]*['\"]([^'\"]+)['\"]"),
    re.compile(r"FileNotFoundError:\s*(\S+)"),
)
_PACKAGE_RES = (
    re.compile(r"No module named ['\"]?([\w.\-]+)['\"]?"),
    re.compile(r"Failed building wheel for ([\w.\-]+)"),
    # "Failed to build installable wheels for some pyproject.toml based projects (pygame)" / "...: pygame, numpy"
    re.compile(r"Failed to build installable wheels for[^(:]*(?:\(|:\s*)([\w.\-]+)"),
    re.compile(r"satisfies the requirement ([\w.\-]+)"),
    re.compile(r"No matching distribution found for ([\w.\-]+)"),
    re.compile(r"Cannot install ([\w.\-]+)"),
    re.compile(r"yanked version: '?([\w.\-]+)"),
    re.compile(r"cannot open shared object file.*?(lib[\w.]+\.so[\w.]*)|(lib[\w.]+\.so[\w.]*): cannot open"),
    re.compile(r"fatal error:\s*([\w./]+\.h)"),
    re.compile(r"(?:command|execute) '?([\w+./-]+?)'? (?:failed|not found)|Cannot find command '([^']+)'|: ([\w+.-]+): (?:command )?not found"),
)
_MODULE_RES = (
    re.compile(r"cannot import name '\w+' from '([\w.]+)'"),
    re.compile(r"module '([\w.]+)' has no attribute"),
)
_LIMIT_RES = (
    re.compile(r"(Disk quota exceeded|No space left on device|Request Entity Too Large|Payload Too Large)"),
    re.compile(r"(cannot enable executable stack[^;]*|Bad system call|seccomp)"),
    re.compile(r"(exit code \d+: the process was killed by SIGKILL)"),
)


def _first(patterns: tuple[re.Pattern, ...], text: str) -> str | None:
    for pattern in patterns:
        m = pattern.search(text)
        if m:
            value = next((g for g in m.groups() if g), None)
            if value:
                return value
    return None


def _fill(template: str, evidence: str) -> str:
    """The template with every placeholder replaced by what the evidence says, or by the generic wording."""
    values = {
        "package": _first(_PACKAGE_RES, evidence),
        "path": _first(_PATH_RES, evidence),
        "module": _first(_MODULE_RES, evidence),
        "limit": _first(_LIMIT_RES, evidence),
    }
    out = template
    for key, found in values.items():
        hole = "{" + key + "}"
        if hole in out:
            out = out.replace(hole, found if found else _FALLBACK[key])
    return out


def _gpu_row(evidence: str, attempts=()) -> tuple[str, str]:
    """GPU_REQUIRED: (fixable_by, sentence). harness-v1.7 (R2): an operation without a CPU kernel still needs a CUDA device for THIS run; the
    sentence says whether a CPU reference for it exists and whether this run's shim carried it. It never claims a fix the record does not show
    (v1.7 review, M5: the blocker is recomputed when an older certificate is served, so it must not rewrite what an older run could do)."""
    from app.services import runner_hooks  # stdlib-only module; imported here to keep blocker's import list as it was

    kernel = runner_hooks.reference_kernel_for(evidence)
    if kernel is not None:
        name = runner_hooks.CPU_REFERENCE_KERNELS[kernel]["label"]
        had = any("LU without pivoting" in str(((a or {}).get("time_machine_action") or {}).get("limit") or "")
                  for a in attempts if ((a or {}).get("time_machine_action") or {}).get("rule") == "cpu_shim")
        if had:
            return HUMAN, f"{_GPU_NO_CPU_SENTENCE}; this run's CPU shim carried the reference for {name} and the run still stopped here"
        return HUMAN, f"{_GPU_NO_CPU_SENTENCE} (a CPU reference for {name} exists from harness-v1.7; this run's shim did not carry it)"
    if _NO_CPU_KERNEL.search(evidence):
        return HUMAN, _GPU_NO_CPU_SENTENCE
    return TABLE[TaxonomyCode.GPU_REQUIRED]


def _gpu_sentence(evidence: str) -> str:
    return _gpu_row(evidence)[1]


def _api_removed_sentence(evidence: str) -> str:
    """API_REMOVED names the MODULE whose name moved; the release wanted is that module's distribution."""
    module = _first(_MODULE_RES, evidence)
    package = module.split(".")[0] if module else None
    return _RELEASE_API.replace("{package}", package or _FALLBACK["package"])


# harness-v1.7.2: an INDETERMINATE stop on something the run did not have (exit_zero_check, entry_blockers). The verdict says a human or the platform
# must supply it and that no repair was made; the blocker must say the same thing, not describe the last code error in the chain (found live:
# pdf-to-powerpoint's certificate said "RUNTIME_ERROR_OTHER, fixable by model" beside "ENTRYPOINT_NEEDS_ARGS ... not repaired").
INPUT_STOPS: dict[str, tuple[str, str, str]] = {
    "ENTRYPOINT_NEEDS_ARGS": (HUMAN, "Inputs", "the arguments the entry point reads (for example an input file), as the quoted line shows"),
    "NEEDS_CREDENTIALS": (HUMAN, "Inputs", "the key, token or credential the program asks for"),
    "NEEDS_INTERACTIVE_INPUT": (HUMAN, "Inputs", "the answers the program asks a person to type, or a way to pass them without a keyboard"),
    "DISPLAY_REQUIRED": (PLATFORM, "Resources", "a display: a desktop session, or a virtual display such as Xvfb"),
}


def _input_stop(result: dict, chain: list) -> dict | None:
    reason = result.get("indeterminate_reason") or ""
    code = reason.split(":", 1)[0].strip()
    if result.get("verdict") != "INDETERMINATE" or code not in INPUT_STOPS:
        return None
    fixable_by, family, sentence = INPUT_STOPS[code]
    quoted = re.search(r"`([^`]+)`|\('([^']+)'\)", reason)
    return {"class": code, "family": family, "phase": (chain[-1].get("phase") if chain else None) or "repo_run",
            "attribution": None,  # neither the repository's code nor the environment: something the run was not given
            "evidence": ((quoted.group(1) or quoted.group(2)) if quoted else reason)[:EVIDENCE_MAX_CHARS],
            "fixable_by": fixable_by, "what_a_human_must_supply": sentence, "sources": None}


def report(result: dict) -> dict | None:
    """The blocker record for one stored result dict, or None when nothing blocks (see the module docstring)."""
    if result.get("verdict") in ("RUNS_CLEAN", "RUNS_AFTER_REPAIR"):
        # Nothing blocks a run that ended RUNS_*: the failure its chain ends on was cleared (the ladder's
        # `first_error_cleared_by` says by what). A blocker here would describe something no longer in the way.
        return None
    chain = list(result.get("error_chain") or ())
    stop = _input_stop(result, chain)
    if stop is not None:
        return stop
    if not chain:
        return None
    link = chain[-1]
    code = link.get("class") or ""
    evidence = (link.get("error") or "")[:EVIDENCE_MAX_CHARS]
    row = TABLE.get(_HISTORICAL.get(code, code))
    if row is None:
        # A class this table does not know (a record written by a harness this code has never seen). report() sits
        # behind certificate() and the API's computed field, so one odd stored row must not fail every read: the
        # record says plainly that nothing is known about the class, and the gap is logged. Completeness over
        # TaxonomyCode.ALL is asserted by a test, never here.
        logger.warning("blocker: no table row for class %r; the report carries None for its fields", code)
        return {"class": code, "family": None, "phase": link.get("phase"), "attribution": link.get("attribution"),
                "evidence": evidence, "fixable_by": None, "what_a_human_must_supply": None, "sources": None}
    fixable_by, template = row
    if code == TaxonomyCode.GPU_REQUIRED:
        fixable_by, sentence = _gpu_row(evidence, result.get("attempts") or ())
    elif code == TaxonomyCode.API_REMOVED:
        sentence = _api_removed_sentence(evidence)
    else:
        sentence = _fill(template, evidence)
    out = {
        "class": code,
        "family": TaxonomyCode.FAMILY.get(_HISTORICAL.get(code, code)),
        "phase": link.get("phase"),
        "attribution": link.get("attribution"),
        "evidence": evidence,
        "fixable_by": fixable_by,
        "what_a_human_must_supply": sentence,
        "sources": None,
    }
    # harness-v1.7: every label of the run (RESOURCE-ADAPTED, memory hook, dependency change, semantic change), only when set: older reports are unchanged
    from app.services import outcome_levels

    for key, value in (("resource_adapted", outcome_levels.resource_adapted(result)), ("memory_adapted", outcome_levels.memory_adapted(result)),
                       ("dependency_change", outcome_levels.dependency_change(result)),
                       ("exit_zero_overruled", outcome_levels.exit_zero_overruled(result))):  # harness-v1.7.2 (D-46)
        if value:
            out[key] = value
    return out
