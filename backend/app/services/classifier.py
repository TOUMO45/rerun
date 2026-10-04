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
import sys
from dataclasses import dataclass, field


class TaxonomyCode:
    """String constants for every failure taxonomy code in §5.2."""

    DEP_UNPINNED_CONFLICT = "DEP_UNPINNED_CONFLICT"
    DEP_MISSING = "DEP_MISSING"
    # Split of the original §5.2 DEP_YANKED_GONE (2026-09-24, after the TTPT
    # live run labelled a never-published package "yanked"):
    DEP_YANKED = "DEP_YANKED"  # the package is on the index; the requested version is not installable
    DEP_NOT_ON_PYPI = "DEP_NOT_ON_PYPI"  # the index has no installable distribution for the name at all
    # harness-v1.6: a third-party package installed, but a newer release than the authors used no longer has the
    # name the code imports or calls (`cannot import name 'compare_psnr' from 'skimage.measure'`, `module 'numpy'
    # has no attribute 'float'`). Until v1.6 these fell through to RUNTIME_ERROR_OTHER and were repaired by editing
    # code, when the deterministic fix is the era lock (the release the authors had).
    API_REMOVED = "API_REMOVED"
    # harness-v1.6: pip could not BUILD a declared package from source (a metadata/wheel build failure), as opposed to
    # not finding it (DEP_NOT_ON_PYPI / DEP_YANKED) or a resolver conflict.
    DEP_BUILD_FAILED = "DEP_BUILD_FAILED"
    PY_VERSION_INCOMPAT = "PY_VERSION_INCOMPAT"
    SYS_LIB_MISSING = "SYS_LIB_MISSING"
    # harness-v1.6: the base image's distribution has left the apt mirrors (an archived Debian release answers 404 /
    # "no longer has a Release file"). RERUN chose the image, so this is never the repository's fault: attribution
    # ENV, verdict INDETERMINATE (see error_chain.attribute and the orchestrator's `_note_failure`).
    APT_MIRROR_GONE = "APT_MIRROR_GONE"
    DATA_MISSING = "DATA_MISSING"
    DATA_CREDENTIALS = "DATA_CREDENTIALS"
    ENTRYPOINT_UNCLEAR = "ENTRYPOINT_UNCLEAR"
    HARDCODED_PATH = "HARDCODED_PATH"
    GPU_REQUIRED = "GPU_REQUIRED"
    NETWORK_BLOCKED = "NETWORK_BLOCKED"
    RUNTIME_ERROR_OTHER = "RUNTIME_ERROR_OTHER"
    # Sandbox-side failures (Phase 2). Verdict INDETERMINATE, never BLOCKED: an
    # infrastructure limit or a platform refusal is not evidence about the paper's code.
    SANDBOX_QUOTA = "SANDBOX_QUOTA"  # a Nebius limit: upload rejected, fs delta, disk full
    SANDBOX_INCOMPAT = "SANDBOX_INCOMPAT"  # the platform refuses to load a valid artifact
    # harness-v1.4.2-rc (D-38, D-40): the process was killed by SIGKILL (exit 137 / -9: the memory limit's OOM kill, or the sandbox itself).
    RESOURCE_LIMIT = "RESOURCE_LIMIT"

    FAMILY = {
        DEP_UNPINNED_CONFLICT: "Dependencies",
        DEP_MISSING: "Dependencies",
        DEP_YANKED: "Dependencies",
        DEP_NOT_ON_PYPI: "Dependencies",
        API_REMOVED: "Dependencies",
        DEP_BUILD_FAILED: "Dependencies",
        PY_VERSION_INCOMPAT: "Environment",
        SYS_LIB_MISSING: "Environment",
        APT_MIRROR_GONE: "Environment",
        DATA_MISSING: "Data",
        DATA_CREDENTIALS: "Data",
        ENTRYPOINT_UNCLEAR: "Documentation",
        HARDCODED_PATH: "Code",
        GPU_REQUIRED: "Resources",
        NETWORK_BLOCKED: "Environment",
        RUNTIME_ERROR_OTHER: "Code",
        SANDBOX_QUOTA: "Platform",
        SANDBOX_INCOMPAT: "Platform",
        RESOURCE_LIMIT: "Platform",
    }

    SANDBOX_CODES = frozenset({SANDBOX_QUOTA, SANDBOX_INCOMPAT, RESOURCE_LIMIT})

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


# Which layer a repair should try first for each code. Environment-family
# failures (a missing compiler/system library, an unavailable or conflicting
# package, the wrong interpreter) cannot be fixed by editing repo code — the
# 2026-09-24 live runs spent all three gpt-2 attempts editing Python that never
# ran because `regex==2017.4.5` needed gcc.
ENV_FIRST_CODES = frozenset(
    {
        "SYS_LIB_MISSING",
        "DEP_UNPINNED_CONFLICT",
        "DEP_MISSING",
        "DEP_YANKED",
        "DEP_NOT_ON_PYPI",
        "PY_VERSION_INCOMPAT",
        # harness-v1.6. API_REMOVED: the name the code imports existed in the release the authors used, so the era
        # lock (time machine, attempt 0) is the deterministic fix; a code edit that renames the call is the model's
        # guess at what the authors meant. DEP_BUILD_FAILED: a source build that fails needs the era's wheel, its
        # build dependencies or a compiler, never a change to the repository's Python.
        "API_REMOVED",
        "DEP_BUILD_FAILED",
        # APT_MIRROR_GONE is deliberately listed too: it IS an environment failure and no code edit can touch it.
        # In practice the orchestrator ends the run INDETERMINATE before any repair layer is chosen (the base image
        # itself is what is gone, and the time machine only moves packages, not the distribution), so the layer is
        # only ever read by code paths that report, not repair.
        "APT_MIRROR_GONE",
    }
)


def repair_layer_for(code: str) -> str:
    """'env' for environment-family codes, else 'code'."""
    return "env" if code in ENV_FIRST_CODES else "code"


# harness-v1.6: top-level names that are part of this interpreter's standard library. An `ImportError: cannot import
# name` / `AttributeError: module ... has no attribute` on one of these is a Python-version matter (error_chain's
# PY_INCOMPAT_PATTERNS handle the documented cases) or a code bug, never a third-party API that moved. The set is the
# interpreter's own list, not a hand-written one, so it cannot drift from what Python ships. The sandbox may run an
# OLDER interpreter than this backend, where modules Python has since removed (distutils and imp in 3.12, the PEP 594
# "dead batteries" in 3.13) were still standard: those are added by name, so a line about them is never read as a
# third-party API change either.
_REMOVED_STDLIB = frozenset({
    "distutils", "imp", "asynchat", "asyncore", "smtpd", "aifc", "audioop", "cgi", "cgitb", "chunk", "crypt",
    "imghdr", "mailcap", "msilib", "nis", "nntplib", "ossaudiodev", "pipes", "sndhdr", "spwd", "sunau", "telnetlib",
    "uu", "xdrlib", "lib2to3", "binhex", "formatter", "parser", "symbol", "macpath",
})
STDLIB_MODULE_NAMES: frozenset[str] = frozenset(sys.stdlib_module_names) | _REMOVED_STDLIB


# System executables a build or run step commonly shells out to. A bare
# "[Errno 2] No such file or directory: 'git'" is a missing system binary,
# not missing data (the TTPT v5 live run classified exactly that line as
# DATA_MISSING, 2026-09-24). Only these names count for the Errno-2 and the
# "command not found" forms, so a missing data file without a slash (e.g.
# 'config') stays DATA_MISSING and a missing repo-local script is never
# called a system dependency. (The code keeps its historical name
# SYS_LIB_MISSING — old certificates carry it — and covers missing system
# tools/binaries as well as shared libraries.)
SYSTEM_BINARIES = (
    "git", "gcc", "g++", "cc", "c++", "make", "cmake", "ninja", "nvcc", "gfortran",
    "pkg-config", "swig", "java", "javac", "curl", "wget", "unzip", "tar", "gzip",
    "bzip2", "xz", "ffmpeg", "hg", "svn", "git-lfs", "cargo", "rustc", "go",
    "protoc", "patch", "bash", "sh", "perl", "ld", "as",
    "python", "python2", "python3", "pip", "pip3", "conda", "nvidia-smi",
)
_BINARY_ALT = "|".join(re.escape(b) for b in SYSTEM_BINARIES)


_RULES: tuple[_Rule, ...] = (
    # --- Sandbox platform (checked before everything else: whatever fails ----
    # downstream of a platform refusal or an exhausted quota is a consequence,
    # and a repair cannot fix it). `libtorch_cpu.so: cannot enable executable
    # stack` would otherwise match the SYS_LIB_MISSING shared-object rules.
    _Rule(
        TaxonomyCode.SANDBOX_INCOMPAT,
        _p(
            r"cannot enable executable stack as shared object requires",
            r"RERUN_SANDBOX_INCOMPAT",
            r"\bBad system call\b",
            r"\bseccomp\b.*(denied|blocked|violation|not permitted)",
            r"Operation not permitted:? .*\bseccomp\b",
        ),
    ),
    _Rule(
        TaxonomyCode.SANDBOX_QUOTA,
        _p(
            r"No space left on device",
            r"\[Errno 28\]",
            r"Disk quota exceeded",
            r"\[Errno 122\]",
            r"\b413\b.{0,40}(Request Entity Too Large|Payload Too Large)",
            r"(Request Entity Too Large|Payload Too Large)",
            r"upload (was )?(rejected|refused)",
            r"filesystem (delta|changes?) (limit|exceeded)",
        ),
    ),
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
    # --- The base image's distribution left the apt mirrors (harness-v1.6) --
    # Checked before both SYS_LIB_MISSING rules: an `apt-get update` that 404s
    # on an INDEX (InRelease / Release / Packages) means every apt install
    # after it fails too, and the "missing tool" that follows is a consequence
    # of the mirror, not a repository dependency. A 404 on one package file
    # under deb.debian.org/debian/pool/ is NOT this: it is a stale index that
    # `apt-get update` fixes (v1.6 review, defect 1), and the rule must not end
    # the run INDETERMINATE for it. The exception is a pool 404 on
    # security.debian.org / archive.debian.org / a `/debian-security/` path:
    # those are the EOL mirrors (DEV #16, bullseye's updates moved away) and
    # no update brings the file back.
    _Rule(
        TaxonomyCode.APT_MIRROR_GONE,
        _p(
            r"E: The repository '.*' (no longer has a Release file|does not have a Release file)",
            # Anchored on the URL scheme: a bare `\S+/` is quadratic on a long run of non-space characters (D-41's bounded-digits lesson).
            r"https?://\S+/(InRelease|Release|Packages\S*)\s+404",
            r"E: Failed to fetch https?://(security\.debian\.org|archive\.debian\.org)\S*\s+404",
            r"E: Failed to fetch https?://\S*/debian-security/\S*\s+404",
        ),
    ),
    # --- Missing system binary (a system dependency, never DATA_MISSING) --
    # Checked before every other rule: when a tool pip or a script shells out
    # to is absent, whatever fails downstream of it is a consequence.
    _Rule(
        TaxonomyCode.SYS_LIB_MISSING,
        _p(
            r"Cannot find command '[^']+'",  # pip (VCS backends)
            # bash / dash: only for names on the fixed tool list — a repo's own
            # script or helper that isn't found (`run_exp: command not found`)
            # is a repository problem, not a missing system dependency.
            r"(?<![\w./+-])(?:" + _BINARY_ALT + r"): command not found",  # bash
            r"\bsh: \d+: (?:" + _BINARY_ALT + r"): not found",  # dash
            r"/usr/bin/env: '?[\w.+-]+'?: No such file or directory",  # missing interpreter
            r"No such file or directory: '(?:/usr(?:/local)?/s?bin/|/s?bin/)?(?:" + _BINARY_ALT + r")'",
            r"executable file not found in \$PATH",
            r"(?:unable|failed) to execute '?(?:" + _BINARY_ALT + r")'?",
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
    # harness-v1.6: pip found the package but could not build it (a source
    # distribution whose metadata or wheel build died). Checked before the
    # NOT_ON_PYPI / YANKED rules because a failed build log also carries a
    # trailing "ERROR: Failed to build ..." summary and never a "from
    # versions:" line, so nothing is taken from them; checked after the
    # resolver-conflict rule because a conflict is reported before any build.
    _Rule(
        TaxonomyCode.DEP_BUILD_FAILED,
        _p(
            r"Encountered error while generating package metadata",
            r"error: subprocess-exited-with-error",
            r"Failed building wheel for",
            r"ERROR: Failed to build installable wheels",
        ),
    ),
    # Order matters: pip prints "(from versions: none)" and then "No matching
    # distribution found for X" for a name the index has nothing for, so the
    # NOT_ON_PYPI signals are checked first. Caveat, stated honestly: "none"
    # also appears when a package exists but has no distribution compatible
    # with this interpreter/platform — the log alone cannot tell those apart.
    _Rule(
        TaxonomyCode.DEP_NOT_ON_PYPI,
        _p(
            r"Could not find a version that satisfies the requirement .*\(from versions: none\)",
            r"404 Client Error.*pypi\.org",
            r"is not a valid editable requirement",
        ),
    ),
    _Rule(
        TaxonomyCode.DEP_YANKED,
        _p(
            r"Could not find a version that satisfies the requirement .*\(from versions: [^)\s][^)]*\)",
            r"candidate selected for download or install is a yanked version",
            r"No matching distribution found for",
        ),
    ),
    _Rule(
        TaxonomyCode.DEP_MISSING,
        _p(
            r"ModuleNotFoundError:\s*No module named ['\"]([\w.\-]+)['\"]",
            r"ImportError:\s*No module named ['\"]?([\w.\-]+)['\"]?",
        ),
    ),
    # harness-v1.6: a name that moved out of a third-party package. Group 1
    # of each pattern is the MODULE (checked by `_third_party_module`: not
    # the standard library, not the repository's own code); the second group
    # is the name, kept for the evidence line only. Checked after DEP_MISSING
    # (a package that is not installed at all is the more basic fact) and
    # before the Environment rules. A `torch._C` attribute starting with
    # `_cuda_` is left to the GPU_REQUIRED rule below (harness-v1.5.1, F3):
    # a CPU-only torch lacks it in EVERY release, so no era has it.
    _Rule(
        TaxonomyCode.API_REMOVED,
        _p(
            r"ImportError: cannot import name '(?P<name>\w+)' from '(?P<module>[\w.]+)'",
            r"AttributeError: module '(?P<module>[\w.]+)' has no attribute '(?P<name>(?!_cuda_)\w+)'",
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
            # harness-v1.5.1 (F3, corpus-v2 entry 14): a CPU-only torch has no `torch._C._cuda_*` functions, so a call into one raises this instead of the line above
            r"module 'torch\._C' has no attribute '_cuda_\w+'",
            r"CUDA[- ]capable device is not detected",
            r"AssertionError:.*[Cc][Uu][Dd][Aa]",
            r"RuntimeError:.*CUDA (error|driver)",
            # harness-v1.6: torch >= 2.x phrases the same fact as "accelerator"; an op with no CPU kernel; the two legacy
            # ways of asking for CUDA tensors by type (`set_default_tensor_type(torch.cuda.FloatTensor)`, `torch.cuda.FloatTensor(...)`).
            r"Cannot access accelerator device when none is available",
            r"is not implemented on the CPU",
            # An exception prefix is required on the same line (v1.6 review, defect 3): the bare name also appears in
            # source lines a traceback echoes (`dtype = torch.cuda.FloatTensor if args.cuda else ...`) and in
            # deprecation warnings (`UserWarning: torch.cuda.FloatTensor ... is deprecated`), neither of which is the failure.
            r"(TypeError|RuntimeError|AssertionError|AttributeError):.*set_default_tensor_type\(torch\.cuda",
            r"(TypeError|RuntimeError|AssertionError|AttributeError):.*torch\.cuda\.\w+Tensor",
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
            # harness-v1.6: a repository's own guard for its data ("AssertionError: please download the dataset first",
            # "AssertionError: data dir not found"), and a missing file raised inside a DataLoader worker, which torch
            # re-raises with its own prefix so the FileNotFoundError line sits in the worker's trace.
            # Guard phrasing only (v1.6 review, defect 4): "download" anywhere, or a data word together with a
            # not-there word; `AssertionError: dataset must be one of [...]` (argument validation) is not missing data.
            r"AssertionError:(?=.*\bdownload)",
            r"AssertionError:(?=.*\b(dataset|data (dir|path|folder))\b)(?=.*\b(not found|does not exist|missing|please|first|prepare)\b)",
            r"Caught FileNotFoundError in DataLoader worker",
        ),
    ),
)

# harness-v1.6: DEP_BUILD_FAILED is the generic wrapper pip prints around a failed source build. When the build log also
# shows WHY the build died, that inner cause is the classification: an undeclared build-time module (DEP_MISSING: the
# no-build-isolation repair keys on it), a missing compiler or header (SYS_LIB_MISSING: the build-essential rule keys on
# it), the wrong interpreter (PY_VERSION_INCOMPAT). Any other rule after it in `_RULES` (data, GPU, network, paths) is a
# runtime matter and does not explain a build, so the wrapper wins over those.
# DEP_YANKED / DEP_NOT_ON_PYPI (v1.6 review, defect 2): a build whose setup_requires cannot be resolved prints pip's
# "Could not find a version that satisfies" inside the wrapper, and the deterministic dep_resolver path keys on those.
_BUILD_INNER_CAUSES = frozenset({TaxonomyCode.DEP_MISSING, TaxonomyCode.SYS_LIB_MISSING, TaxonomyCode.PY_VERSION_INCOMPAT,
                                 TaxonomyCode.DEP_YANKED, TaxonomyCode.DEP_NOT_ON_PYPI})
# The codes a pip failure AFTER an apt 404 line carries (v1.6 review, defect 1): when one of them matches later in the
# output than the apt line, the later failure is the one the run ended on and it wins over APT_MIRROR_GONE.
_DEP_CODES = frozenset({TaxonomyCode.DEP_UNPINNED_CONFLICT, TaxonomyCode.DEP_BUILD_FAILED, TaxonomyCode.DEP_NOT_ON_PYPI,
                        TaxonomyCode.DEP_YANKED, TaxonomyCode.DEP_MISSING, TaxonomyCode.API_REMOVED})
_PIP_BLOCK_END_RE = re.compile(r"^\s*(ERROR: |Successfully installed\b)", re.MULTILINE)
_SUCCESSFULLY_INSTALLED_RE = re.compile(r"^Successfully installed\b", re.MULTILINE)
_BUILD_WRAPPER_PATTERNS = next(r.patterns for r in _RULES if r.code == TaxonomyCode.DEP_BUILD_FAILED)


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
    # The distribution name may differ from the import name (cv2 ->
    # opencv-python): the cited import map (harness-v1.1) decides.
    from app.services.import_names import dist_for_import

    candidates = {top_level.lower(), dist_for_import(top_level).lower()}
    normalized_declared = {d.lower().replace("_", "-") for d in declared_deps}
    return not any(c.replace("_", "-") in normalized_declared for c in candidates)


def _third_party_module(match: re.Match, repo_modules: frozenset[str] | None) -> bool:
    """True if the module named in an API_REMOVED match (`module` group) is a third-party package: its top-level
    name is neither in the standard library nor one of the repository's own modules.

    `repo_modules` is the set dep_scan.internal_module_names builds from the tree (lower-cased). When the caller
    cannot supply it (None), the repository's modules are unknown and only the standard library is excluded: the
    same "best effort, default to the rule" stance `_undeclared_module` takes for declared_deps.
    """
    module = match.group("module") if "module" in match.groupdict() else ""
    top_level = module.split(".")[0]
    if not top_level or top_level in STDLIB_MODULE_NAMES:
        return False
    return repo_modules is None or top_level.lower() not in repo_modules


def _last_exception_line(text: str) -> str:
    """The last `SomeError: message` line of `text` (stripped of pip's indentation), or "" when there is none."""
    found = ""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped and _EXCEPTION_LINE_RE.match(stripped):
            found = stripped
    return found


def _build_wrapper_span(text: str) -> tuple[int, int] | None:
    """(start, end) of pip's failed-build block in `text`: from the first wrapper line to the end of the last one, or None
    when no wrapper pattern matches. Everything the build printed sits inside it; what the command printed after it is
    outside it."""
    matches = [m for p in _BUILD_WRAPPER_PATTERNS for m in p.finditer(text)]
    if not matches:
        return None
    start = min(m.start() for m in matches)
    last_end = max(m.end() for m in matches)
    line_end = text.find("\n", last_end)
    return start, (line_end if line_end != -1 else len(text))


def _build_evidence(text: str, start: int) -> str:
    """The build's own exception line: the last one between the wrapper match at `start` and the next `ERROR:` /
    `Successfully installed` line (pip's summary of that build), so an exception a LATER build or the command printed is
    never quoted as this build's cause."""
    after = text[start:]
    first_line_end = after.find("\n")
    rest_from = first_line_end + 1 if first_line_end != -1 else len(after)
    boundary = _PIP_BLOCK_END_RE.search(after, rest_from)
    return _last_exception_line(after[: boundary.start() if boundary else len(after)])


def _search_outside(pattern: re.Pattern, text: str, masked: tuple[int, int] | None) -> re.Match | None:
    """The first match of `pattern` in `text` that does not START inside `masked`."""
    for match in pattern.finditer(text):
        if masked is None or not (masked[0] <= match.start() <= masked[1]):
            return match
    return None


def _evidence_line(text: str, match: re.Match) -> str:
    """The whole log line containing the match — not just the matched
    phrase. The live TTPT run recorded evidence as "No matching distribution
    found for" with the package name cut off, which is useless both to a
    human and to the repairer."""
    start = text.rfind("\n", 0, match.start()) + 1
    end = text.find("\n", match.end())
    return text[start : end if end != -1 else len(text)].strip()


# 128 + SIGKILL (a shell reports a killed child this way) and the negative return code a launcher sees for a killed process. Other signals are NOT
# listed on purpose: SIGSEGV (139) and SIGABRT (134) are crashes of the program or its native code, SIGTERM (143) may be the program's own.
SIGKILL_EXIT_CODES = frozenset({137, -9})


def classify(
    exit_code: int,
    stderr: str,
    stdout: str = "",
    declared_deps: frozenset[str] | None = None,
    repo_modules: frozenset[str] | None = None,
) -> Classification:
    """Classify a failed sandbox execution into a taxonomy code.

    Precondition: exit_code != 0. A zero exit code is a caller bug, not a
    classification question — callers must handle RUNS_CLEAN before ever
    reaching here.

    `repo_modules` (harness-v1.6): the repository's own importable names
    (dep_scan.internal_module_names, lower-cased), so an `ImportError: cannot
    import name` from one of them is a code bug and not API_REMOVED. None =
    unknown: only the standard library is excluded.
    """
    if exit_code == 0:
        raise ValueError("classify() must only be called on a non-zero exit code")

    # harness-v1.3.3 (D-9): rules and evidence see the output WITHOUT progress bars and library log chatter. A benign
    # TensorFlow `W ... Could not load dynamic library 'libnvinfer.so.6'` line used to be classified SYS_LIB_MISSING while the real
    # failure (`AttributeError: module 'tensorflow' has no attribute 'get_variable'`) sat below it (corpus-v2 entry 12), and a
    # progress fragment ("17.6") was recorded as the error (entry 3).
    raw_output = f"{stderr}\n{stdout}"
    if exit_code in SIGKILL_EXIT_CODES:
        # harness-v1.4.2-rc (D-38): a SIGKILL is not the repository's error text and not a silent exit: the kernel's OOM killer or the sandbox ended
        # the process (corpus-v2 #11, harness-v1.4.1 gate: `1/40 [00:01<00:53, 1.37s/it]Killed`, exit 137, the line lost in denoise() as a progress bar).
        shell_said = bool(re.search(r"\bKilled\b", raw_output))
        return Classification(
            code=TaxonomyCode.RESOURCE_LIMIT,
            family=TaxonomyCode.FAMILY[TaxonomyCode.RESOURCE_LIMIT],
            evidence=f"exit code {exit_code}: the process was killed by SIGKILL" + (" (the shell printed 'Killed')" if shell_said else ""),
            matched_pattern=f"exit code in {sorted(SIGKILL_EXIT_CODES)}",
        )
    stderr, stdout = denoise(stderr), denoise(stdout)
    combined = f"{stderr}\n{stdout}"

    # harness-v1.6: pip's failed-build wrapper (DEP_BUILD_FAILED) names no cause and pip may go on after it (another sdist
    # version, or `Successfully installed`). So: when a `Successfully installed` line follows the block, the block is
    # not the failure at all and nothing inside it may match any rule (`masked`); otherwise the wrapper is held back
    # (`build_wrapper`) while the rules that can name the build's inner cause (`_BUILD_INNER_CAUSES`, matched anywhere)
    # and every other rule (matched only AFTER the block: a runtime failure the command printed later) are checked.
    build_span = _build_wrapper_span(combined)
    masked = build_span if build_span and _SUCCESSFULLY_INSTALLED_RE.search(combined, build_span[1]) else None
    build_wrapper: Classification | None = None
    # While the wrapper is held: `build_inner` = the first inner-cause rule matching inside the block (it names why the
    # build died); `build_later` = the first rule of any kind matching AFTER the block (what the command printed next,
    # which is what the run ended on and wins over both).
    build_inner: Classification | None = None
    build_later: Classification | None = None
    # v1.6 review, defect 1: an APT_MIRROR_GONE match is held back while the DEP_* rules are checked; a DEP_* failure
    # that occurs LATER in the output than the apt line is the one the run ended on and wins.
    apt_hold: tuple[Classification, int] | None = None
    for rule in _RULES:
        if build_wrapper is not None and build_later is not None:
            break
        for pattern in rule.patterns:
            match = _search_outside(pattern, combined, masked)
            if not match:
                continue
            if build_wrapper is not None and match.start() <= build_span[1]:
                if rule.code not in _BUILD_INNER_CAUSES or build_inner is not None:
                    continue  # inside the failed build's block: the build is the failure, not what it printed
                after = _search_outside(pattern, combined, (0, build_span[1]))
                if after is not None:  # the same rule also matches after the block: that later match is the one that counts
                    match = after
            if apt_hold is not None and rule.code in _DEP_CODES and match.start() <= apt_hold[1]:
                continue  # before the apt line: the apt failure is the later one
            if rule.code == TaxonomyCode.DEP_MISSING and not _undeclared_module(
                match, declared_deps
            ):
                # Declared but still failed to import: not our rule's story,
                # keep scanning other rules / fall through to the catch-all.
                continue
            if rule.code == TaxonomyCode.API_REMOVED and not _third_party_module(match, repo_modules):
                # The standard library or the repository's own module: a Python-version matter or a code bug, which
                # the later rules / the catch-all describe; never "a third-party API moved".
                continue
            evidence = _evidence_line(combined, match)
            classification = Classification(
                code=rule.code,
                family=TaxonomyCode.FAMILY[rule.code],
                evidence=evidence[:500],
                matched_pattern=pattern.pattern,
            )
            if rule.code == TaxonomyCode.DEP_BUILD_FAILED:
                # The wrapper line ("Encountered error while generating package metadata") names no cause. When the build's
                # own output holds a Python exception line, THAT is the evidence (harness-v1.1's rule: the exception, never
                # the pip notice); the wrapper's pattern stays recorded as what matched.
                inner = _build_evidence(combined, build_span[0])  # from the block's FIRST line, whichever pattern matched
                if inner:
                    classification = Classification(rule.code, classification.family, inner[:500], pattern.pattern)
                build_wrapper = classification
                break
            if rule.code == TaxonomyCode.APT_MIRROR_GONE:
                apt_hold = (classification, match.start())
                break
            if apt_hold is not None and rule.code not in _DEP_CODES:
                return apt_hold[0]  # the DEP_* rules found nothing later than the apt line: the apt failure stands
            if build_wrapper is not None:
                if match.start() > build_span[1]:
                    build_later = classification
                else:
                    build_inner = classification
                break
            return classification
    if apt_hold is not None:
        return apt_hold[0]
    if build_wrapper is not None:
        return build_later or build_inner or build_wrapper

    return Classification(
        code=TaxonomyCode.RUNTIME_ERROR_OTHER,
        family=TaxonomyCode.FAMILY[TaxonomyCode.RUNTIME_ERROR_OTHER],
        evidence=fallback_evidence(stderr, stdout, exit_code)[:500],
    )


# Lines that are never the failure (harness-v1.3.3): library log lines at WARNING/INFO level and progress bars.
_LOG_NOISE_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?:? ?[WI] "  # TensorFlow: 2026-09-30 13:50:27.517460: W tensorflow/...
    r"|^[WI]\d{4} \d{2}:\d{2}:\d{2}(?:\.\d+)?\s"  # absl / glog: W0930 13:50:27.517460 1234 file.cc:12]
    r"|^\[?(?:INFO|DEBUG)\]?[: ]"  # python logging at INFO/DEBUG
    r"|^\d{4}-\d{2}-\d{2} [\d:,.]+ - \S+ - (?:INFO|DEBUG|WARNING) - ",
)
# harness-v1.4.3-rc: the digit runs are bounded. `\d+` made the search quadratic on one very long run of digits (8,000 digits: 1.2 s, 32,000: 19.5 s, measured), and the
# output limit that the sandbox client now asks for (4 MiB, was 65,535 bytes) lets such a line reach it. No real progress value has more than 12 digits.
_PROGRESS_RE = re.compile(r"\d{1,12}(?:\.\d{1,12})?%.*\d{1,12}(?:\.\d{1,12})?%|\d{1,12}%\|[^|]*\||^\s*\d{1,12}(?:\.\d{1,12})?%\s*$")


def denoise(text: str) -> str:
    """`text` without carriage-return overwrites (keep the last frame), progress bars and INFO/WARNING library log lines.
    Every kept line is a substring of the original, so evidence quoted from it still appears verbatim in the raw log."""
    kept = []
    for line in (text or "").split("\n"):
        if "\r" in line:
            frames = [f for f in line.split("\r") if f.strip()]
            line = frames[-1] if frames else ""
        stripped = line.strip()
        if stripped and (_LOG_NOISE_RE.match(stripped) or _PROGRESS_RE.search(stripped)):
            continue
        kept.append(line)
    return "\n".join(kept)


# Lines that are never the failure (harness-v1.1): pip's upgrade notices,
# warnings and deprecations. Corpus-v1 entry #1 on harness-v1 was classified
# with the evidence "[notice] To update, run: pip install --upgrade pip".
_NOISE_LINE_RE = re.compile(
    r"^\s*(\[notice\]|WARNING:|DEPRECATION:|warnings\.warn\(|\S*Warning: )", re.IGNORECASE
)
_ERROR_MARKER_RE = re.compile(
    r"error|exception|traceback|failed|failure|fatal|×|✗|cannot|could not|not found|no such", re.IGNORECASE
)


_EXCEPTION_LINE_RE = re.compile(r"^[A-Za-z_][\w.]*(Error|Exception|Exit|Interrupt): \S")


def fallback_evidence(stderr: str, stdout: str = "", exit_code: int = 1) -> str:
    """Evidence when no rule matched, ignoring noise lines, stderr before
    stdout: the LAST Python exception line (`RuntimeError: ...`); else the
    last line carrying an error marker; else the last non-noise line; else
    the exit code."""

    def _signal(text: str) -> list[str]:
        return [line.strip() for line in (text or "").splitlines() if line.strip() and not _NOISE_LINE_RE.match(line)]

    err, out = _signal(stderr), _signal(stdout)
    for pattern in (_EXCEPTION_LINE_RE, _ERROR_MARKER_RE):
        for lines in (err, out):
            marked = [line for line in lines if pattern.search(line)]
            if marked:
                return marked[-1]
    for lines in (err, out):
        if lines:
            return lines[-1]
    return f"exit code {exit_code} (the output held only progress bars, warnings or nothing: no error text to show)"


# harness-v1.3.4 (D-19): does the output carry an error the repairer can act on? A Python traceback, an exception line, a
# faulthandler / fatal-error trace, or a compiler/pip error block. A non-zero exit with none of these is a SILENT FAILURE: the
# repairer is told so and a blind code patch is refused unless it only adds diagnostics.
_ACTIONABLE_ERROR_RE = re.compile(
    r"Traceback \(most recent call last\)|^[A-Za-z_][\w.]*(?:Error|Exception|Exit|Interrupt|Warning): \S"
    r"|Fatal Python error|Windows fatal exception|Segmentation fault|Aborted \(core dumped\)|^error: |^ERROR: |^E: |\bfatal error: |Killed$|MemoryError",
    re.MULTILINE,
)


def has_actionable_error(stderr: str, stdout: str = "") -> bool:
    return bool(_ACTIONABLE_ERROR_RE.search(denoise(stderr) + "\n" + denoise(stdout)))


def head_and_tail(text: str, head_lines: int = 40, tail_lines: int = 80) -> str:
    """The first `head_lines` and last `tail_lines` lines of `text` (denoised), with a marker where lines were skipped."""
    lines = denoise(text or "").split("\n")
    if len(lines) <= head_lines + tail_lines:
        return "\n".join(lines)
    return "\n".join(lines[:head_lines] + [f"[... {len(lines) - head_lines - tail_lines} line(s) skipped ...]"] + lines[-tail_lines:])
