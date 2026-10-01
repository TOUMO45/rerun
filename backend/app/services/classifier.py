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
    # Split of the original §5.2 DEP_YANKED_GONE (2026-09-24, after the TTPT
    # live run labelled a never-published package "yanked"):
    DEP_YANKED = "DEP_YANKED"  # the package is on the index; the requested version is not installable
    DEP_NOT_ON_PYPI = "DEP_NOT_ON_PYPI"  # the index has no installable distribution for the name at all
    PY_VERSION_INCOMPAT = "PY_VERSION_INCOMPAT"
    SYS_LIB_MISSING = "SYS_LIB_MISSING"
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
        PY_VERSION_INCOMPAT: "Environment",
        SYS_LIB_MISSING: "Environment",
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
    }
)


def repair_layer_for(code: str) -> str:
    """'env' for environment-family codes, else 'code'."""
    return "env" if code in ENV_FIRST_CODES else "code"


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
    # The distribution name may differ from the import name (cv2 ->
    # opencv-python): the cited import map (harness-v1.1) decides.
    from app.services.import_names import dist_for_import

    candidates = {top_level.lower(), dist_for_import(top_level).lower()}
    normalized_declared = {d.lower().replace("_", "-") for d in declared_deps}
    return not any(c.replace("_", "-") in normalized_declared for c in candidates)


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
) -> Classification:
    """Classify a failed sandbox execution into a taxonomy code.

    Precondition: exit_code != 0. A zero exit code is a caller bug, not a
    classification question — callers must handle RUNS_CLEAN before ever
    reaching here.
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
            evidence = _evidence_line(combined, match)
            return Classification(
                code=rule.code,
                family=TaxonomyCode.FAMILY[rule.code],
                evidence=evidence[:500],
                matched_pattern=pattern.pattern,
            )

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
_PROGRESS_RE = re.compile(r"\d+(?:\.\d+)?%.*\d+(?:\.\d+)?%|\d+%\|[^|]*\||^\s*\d+(?:\.\d+)?%\s*$")


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
