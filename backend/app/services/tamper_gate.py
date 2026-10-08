"""The tamper gate (RERUN directive §5.3) — the project's differentiator.

PURE. No network calls, no model calls. Every model-proposed patch is
checked here *before* it is ever applied to a target repo. The gate is
diff- and AST-based (stdlib `ast`, not regex-only, per §4.1's "unidiff +
libcst (or ast)" — `ast` was chosen over `libcst` because the gate only
needs read-only structural analysis, never lossless rewriting; see
DECISIONS.md).

Six rejection rules from §5.3, plus one defensive addition
(`UNPARSEABLE_PATCH`, see module docstring below `GateRule`) that isn't in
the original six but follows the same spirit: a deterministic gate must
never PASS a patch it cannot actually verify.

A note on the reachability analysis (rules 1 and 2): a naive "does the call
still appear in the text/AST" check can be defeated by moving the call
inside a function that is never invoked — the call node is still present,
so a plain count would look unchanged. To close that hole, both rules
compare the *reachable* call sites (calls transitively invoked from
module-level code) before and after the patch, not just their raw count.
This is a single-file, best-effort call graph (it does not follow imports
or track dynamic dispatch) — documented as a known limitation, not a claim
of full soundness.
"""

from __future__ import annotations

import ast
import re
import shlex
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

from unidiff import PatchSet
from unidiff.patch import PatchedFile


class GateRule:
    DELETED_EVAL_CALL = "DELETED_EVAL_CALL"
    STUBBED_MODEL_CALL = "STUBBED_MODEL_CALL"
    REDUCED_SCALE = "REDUCED_SCALE"
    BROAD_EXCEPTION_SWALLOW = "BROAD_EXCEPTION_SWALLOW"
    PROTECTED_PATH_MODIFIED = "PROTECTED_PATH_MODIFIED"
    DIFF_TOO_LARGE = "DIFF_TOO_LARGE"
    # Defensive addition beyond §5.3's six rules: see module docstring.
    UNPARSEABLE_PATCH = "UNPARSEABLE_PATCH"
    # Path safety (added 2026-09-24 after the live runs exposed that a diff
    # touching a file the gate was never given passed unchecked).
    UNSAFE_PATH = "UNSAFE_PATH"  # absolute, ../, outside repo root, symlink, rename
    FILE_DELETION = "FILE_DELETION"  # +++ /dev/null — deleting a whole file
    UNVERIFIED_FILE = "UNVERIFIED_FILE"  # touched file whose original the gate did not get
    # harness-v1.3.3: a patch that never reached `git apply` (did not parse into applicable hunks before the gate).
    UNAPPLICABLE_PATCH = "UNAPPLICABLE_PATCH"
    # harness-v1.3.4 (D-19): the failing run printed no error text, and the patch changes code instead of adding diagnostics.
    BLIND_PATCH_ON_SILENT_EXIT = "BLIND_PATCH_ON_SILENT_EXIT"
    # harness-v1.4.0-rc: every repair candidate is py_compile-checked after the patch (compile() also refuses what ast.parse accepts,
    # e.g. `return` outside a function).
    PY_COMPILE_FAILED = "PY_COMPILE_FAILED"
    # harness-v1.9 (D-74): the patch makes the run go on without an input it cannot find (skip, continue, return, exit 0) instead of failing.
    SKIPPED_MISSING_INPUT = "SKIPPED_MISSING_INPUT"


DEFAULT_PROTECTED_PATTERNS: frozenset[str] = frozenset(
    {
        "app/services/classifier.py",
        "app/services/tamper_gate.py",
        "app/batch/corpus.yaml",
        "corpus.yaml",
        # corpus-v1 (pre-registered draw): every file is protected.
        "app/batch/corpus_v1/prereg.json",
        "app/batch/corpus_v1/population.csv",
        "app/batch/corpus_v1/screening_log.jsonl",
        "app/batch/corpus_v1/corpus.yaml",
        "app/batch/corpus_v1/corpus_hash.txt",
        "batch_results.json",
    }
)

_SCALE_KEYWORDS = (
    "epoch",
    "epochs",
    "num_epochs",
    "n_epochs",
    "sample",
    "samples",
    "num_samples",
    "n_samples",
    "dataset_size",
    "subset_size",
    "max_steps",
    "num_steps",
    "train_size",
    "limit",
)
_SCALE_ASSIGN_RE = re.compile(
    r"\b(" + "|".join(_SCALE_KEYWORDS) + r")\b\s*[:=]\s*(\d+)\b",
    re.IGNORECASE,
)

_TRIVIAL_BODY_TYPES = (ast.Pass,)
_NOOP_EXCEPT_CALL_NAMES = {"print", "log", "warn", "warning", "info", "debug", "error"}


@dataclass(frozen=True)
class Violation:
    rule: str
    reason: str
    file: str = ""

    def as_dict(self) -> dict:
        return {"rule": self.rule, "reason": self.reason, "file": self.file}


@dataclass(frozen=True)
class GateResult:
    decision: str  # "PASS" or "REJECT"
    violations: tuple[Violation, ...] = field(default_factory=tuple)
    # The exact diff the gate analyzed, with canonical `a/<path>` / `b/<path>`
    # headers. The orchestrator applies THIS text (git apply -p1), never the
    # model's raw diff, so the gate and the apply step cannot disagree about
    # which files are touched. Empty if the diff could not be parsed.
    canonical_diff: str = ""
    touched_paths: tuple[str, ...] = ()
    # harness-v1.7 (R6, D-44): the calls in a fixed list (`SEMANTIC_CALLS`) that the patch's changed lines touch. Not a rejection: a patch
    # that passes is still applied; the flag travels to the attempt record, the ladder and the verdict label ("semantic change").
    semantic_change: tuple[str, ...] = ()

    @property
    def passed(self) -> bool:
        return self.decision == "PASS"

    def as_dict(self) -> dict:
        return {
            "decision": self.decision,
            "violations": [v.as_dict() for v in self.violations],
        }


_DEV_NULL = "/dev/null"
_WINDOWS_DRIVE_RE = re.compile(r"^[A-Za-z]:")


def _normalize_header_path(raw: str) -> tuple[str | None, str | None]:
    """Header path -> (repo-relative POSIX path, None) or (None, reason).
    Strips one leading `a/` or `b/` and any `./`; rejects absolute paths and
    any `..` component. `/dev/null` is returned unchanged."""
    path = raw.strip().split("\t", 1)[0].strip()
    if path == _DEV_NULL:
        return _DEV_NULL, None
    if path.startswith(("/", "\\")) or _WINDOWS_DRIVE_RE.match(path):
        return None, f"absolute path '{path}' — patches may only use repo-relative paths"
    path = path.replace("\\", "/")
    if path.startswith(("a/", "b/")):
        path = path[2:]
    while path.startswith("./"):
        path = path[2:]
    parts = [p for p in path.split("/") if p not in ("", ".")]
    if not parts:
        return None, f"empty path in diff header '{raw.strip()}'"
    if ".." in parts:
        return None, f"path '{raw.strip()}' escapes the repository root ('..' component)"
    return "/".join(parts), None


@dataclass(frozen=True)
class PreparedPatch:
    """Single source of truth for which files a diff touches."""

    canonical_diff: str
    paths: tuple[str, ...]
    added_paths: frozenset[str]
    violations: tuple[Violation, ...]
    patch_set: PatchSet | None


def prepare_patch(diff_text: str) -> PreparedPatch:
    """Parse a model diff, normalize every header path, reject unsafe ones,
    and rebuild it with canonical `a/`/`b/` headers. Pure."""
    try:
        patch_set = PatchSet(diff_text)
    except Exception as exc:  # unidiff raises UnidiffParseError and friends
        return PreparedPatch("", (), frozenset(), (
            Violation(rule=GateRule.UNPARSEABLE_PATCH, reason=f"diff could not be parsed: {exc}"),
        ), None)
    if len(patch_set) == 0:
        return PreparedPatch("", (), frozenset(), (
            Violation(rule=GateRule.UNPARSEABLE_PATCH, reason="diff contains no file changes"),
        ), None)

    violations: list[Violation] = []
    paths: list[str] = []
    added: set[str] = set()
    chunks: list[str] = []
    for patched_file in patch_set:
        src, src_err = _normalize_header_path(patched_file.source_file)
        tgt, tgt_err = _normalize_header_path(patched_file.target_file)
        for err in (src_err, tgt_err):
            if err:
                violations.append(Violation(rule=GateRule.UNSAFE_PATH, reason=err))
        if src_err or tgt_err:
            continue
        if tgt == _DEV_NULL:
            violations.append(Violation(
                rule=GateRule.FILE_DELETION,
                reason=f"patch deletes the whole file '{src}' — deleting files is never a minimal fix",
                file=src,
            ))
            continue
        if src != _DEV_NULL and src != tgt:
            violations.append(Violation(
                rule=GateRule.UNSAFE_PATH,
                reason=f"patch renames/moves '{src}' to '{tgt}' — renames are not allowed",
                file=tgt,
            ))
            continue
        if tgt in paths:
            violations.append(Violation(rule=GateRule.UNSAFE_PATH, reason=f"'{tgt}' appears twice in one diff", file=tgt))
            continue
        if len(patched_file) == 0:
            # harness-v1.3.2 passed a header-only diff (entries 1 and 8): the gate "approved" a change with no content,
            # `git apply` then failed with "No valid patches in input" and the repair attempt was spent on nothing.
            violations.append(Violation(
                rule=GateRule.UNPARSEABLE_PATCH,
                reason=f"the diff for '{tgt}' has headers but no hunks: it changes nothing",
                file=tgt,
            ))
            continue
        paths.append(tgt)
        if src == _DEV_NULL:
            added.add(tgt)
        header = f"--- {'/dev/null' if src == _DEV_NULL else 'a/' + tgt}\n+++ b/{tgt}\n"
        body = "".join(str(hunk) for hunk in patched_file)
        chunks.append(header + body)
    canonical = "".join(chunks)
    if canonical and not canonical.endswith("\n"):
        canonical += "\n"
    return PreparedPatch(canonical, tuple(paths), frozenset(added), tuple(violations), patch_set)


def check_paths_on_disk(repo_root: Path, paths: tuple[str, ...]) -> list[Violation]:
    """Read-only filesystem checks (lstat/resolve only — no reads, no writes):
    every touched path must resolve inside `repo_root` and no component of it
    may be a symlink (a committed symlink could point a 'repo file' at the
    backend host)."""
    violations: list[Violation] = []
    root = repo_root.resolve()
    for rel in paths:
        current = repo_root
        for part in rel.split("/"):
            current = current / part
            if current.is_symlink():
                violations.append(Violation(
                    rule=GateRule.UNSAFE_PATH,
                    reason=f"'{rel}' goes through a symlink ('{current.relative_to(repo_root).as_posix()}')",
                    file=rel,
                ))
                break
        else:
            resolved = (repo_root / rel).resolve()
            if resolved != root and root not in resolved.parents:
                violations.append(Violation(
                    rule=GateRule.UNSAFE_PATH, reason=f"'{rel}' resolves outside the repository root", file=rel
                ))
    return violations


def _is_protected_path(path: str, protected_patterns: frozenset[str], documented_files: frozenset[str] = frozenset()) -> bool:
    normalized = path.replace("\\", "/").lstrip("./")
    if normalized in protected_patterns:
        return True
    for pattern in protected_patterns:
        if normalized.endswith("/" + pattern) or normalized == pattern:
            return True
    # harness-v1.9 (D-55 / D-75): the test-file NAMING rule below protects a repository's tests from being edited into passing. When the documented
    # command itself runs a `test_*.py` file as its program (TEST-B Ordered-Neurons, TEST-C SCIGAN, TEST-B L2D: `python test_SCIGAN.py`), that file is the program,
    # not a test of it: every patch to it was refused, including nine honest ones per entry. Such a file (`documented_scripts`: the first argument of a `python`
    # interpreter, never what pytest or unittest run) is exempt from the naming rule ONLY: the protected patterns above, the `/tests/` directory rule below and
    # every semantic rule still apply to it, and every other test file stays protected.
    filename = normalized.rsplit("/", 1)[-1]
    if normalized not in documented_files and (filename.startswith("test_") or filename.endswith("_test.py")):
        return True
    if "/tests/" in ("/" + normalized):
        return True
    return False


def _apply_patched_file(original_text: str, patched_file: PatchedFile) -> str:
    """Reconstruct the post-patch file content from the original text plus
    the file's hunks, using unidiff's 1-based source_start/source_length."""
    original_lines = original_text.splitlines(keepends=True)
    new_lines: list[str] = []
    cursor = 0
    for hunk in patched_file:
        start_idx = max(hunk.source_start - 1, 0)
        new_lines.extend(original_lines[cursor:start_idx])
        for line in hunk:
            if line.is_context or line.is_added:
                new_lines.append(line.value)
        cursor = start_idx + hunk.source_length
    new_lines.extend(original_lines[cursor:])
    return "".join(new_lines)


def _added_target_lines(patched_file: PatchedFile) -> set[int]:
    lines: set[int] = set()
    for hunk in patched_file:
        for line in hunk:
            if line.is_added and line.target_line_no is not None:
                lines.add(line.target_line_no)
    return lines


def _removed_source_lines(patched_file: PatchedFile) -> set[int]:
    lines: set[int] = set()
    for hunk in patched_file:
        for line in hunk:
            if line.is_removed and line.source_line_no is not None:
                lines.add(line.source_line_no)
    return lines


def _call_short_name(node: ast.Call) -> str:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def _call_full_expr(node: ast.Call) -> str:
    try:
        return ast.unparse(node.func)
    except Exception:
        return _call_short_name(node)


def _matches_target(node: ast.Call, target_names_lower: frozenset[str]) -> bool:
    if not target_names_lower:
        return False
    short = _call_short_name(node).lower()
    full = _call_full_expr(node).lower()
    return short in target_names_lower or full in target_names_lower


def _non_local_funcdefs(tree: ast.Module) -> dict[str, ast.AST]:
    """Functions resolvable by a bare/attribute call from anywhere in the
    file: module-level functions and class methods. Deliberately EXCLUDES
    functions nested inside another function (local/closure defs) — those
    are only reachable as a name inside their own enclosing function's
    body, never as `name()` from anywhere else, so including them in a
    single flat, name-keyed dict is a scope error, not a scope
    *approximation*. Found live: an entirely unrelated, never-called
    helper function containing a locally-nested function that happens to
    share a name with a real, actually-called module-level function (e.g.
    both named `train`) previously corrupted resolution of the real
    call — `ast.walk`'s traversal order let the irrelevant nested
    definition overwrite the real one in the flat dict, making a
    completely benign patch look like it deleted the reachable eval call.
    See DECISIONS.md.
    """
    parent_of: dict[ast.AST, ast.AST] = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parent_of[child] = parent

    def is_nested_in_function(node: ast.AST) -> bool:
        current = parent_of.get(node)
        while current is not None:
            if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef)):
                return True
            current = parent_of.get(current)
        return False

    funcdefs: dict[str, ast.AST] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not is_nested_in_function(node):
            funcdefs[node.name] = node
    return funcdefs


def _reachable_matching_calls(tree: ast.Module, target_names: frozenset[str]) -> list[ast.Call]:
    """Best-effort, single-file call graph: which calls to `target_names`
    are actually reachable from module-level execution, transitively
    through locally-defined functions. See module docstring for the
    "wrapped in a never-called function" motivation.
    """
    target_lower = frozenset(t.lower() for t in target_names)
    if not target_lower:
        return []

    funcdefs = _non_local_funcdefs(tree)

    def calls_in(node: ast.AST) -> list[ast.Call]:
        return [n for n in ast.walk(node) if isinstance(n, ast.Call)]

    module_level_stmts = [
        s
        for s in tree.body
        if not isinstance(
            s, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Import, ast.ImportFrom)
        )
    ]

    reachable_calls: list[ast.Call] = []
    frontier: list[ast.Call] = []
    for stmt in module_level_stmts:
        frontier.extend(calls_in(stmt))
    reachable_calls.extend(frontier)

    seen_funcs: set[str] = set()
    while frontier:
        next_frontier: list[ast.Call] = []
        for call in frontier:
            name = _call_short_name(call)
            if name in funcdefs and name not in seen_funcs:
                seen_funcs.add(name)
                inner = calls_in(funcdefs[name])
                reachable_calls.extend(inner)
                next_frontier.extend(inner)
        frontier = next_frontier

    return [c for c in reachable_calls if _matches_target(c, target_lower)]


def _check_deleted_eval_call(
    old_tree: ast.Module | None,
    new_tree: ast.Module | None,
    eval_call_names: frozenset[str],
    path: str,
) -> Violation | None:
    if not eval_call_names or old_tree is None or new_tree is None:
        return None
    old_calls = _reachable_matching_calls(old_tree, eval_call_names)
    new_calls = _reachable_matching_calls(new_tree, eval_call_names)
    if len(old_calls) > 0 and len(new_calls) < len(old_calls):
        names = sorted({_call_short_name(c) for c in old_calls})
        return Violation(
            rule=GateRule.DELETED_EVAL_CALL,
            reason=(
                f"reachable calls to evaluation/metric/assertion function(s) "
                f"{names} dropped from {len(old_calls)} to {len(new_calls)} "
                f"after the patch (deleted, commented out, or moved into "
                f"code that is never called)"
            ),
            file=path,
        )
    return None


def _is_trivial_stub_body(body: list[ast.stmt]) -> bool:
    stmts = [s for s in body if not isinstance(s, ast.Expr) or not isinstance(s.value, ast.Constant)]
    if not stmts:
        return True
    if len(stmts) != 1:
        return False
    stmt = stmts[0]
    if isinstance(stmt, ast.Pass):
        return True
    if isinstance(stmt, ast.Return):
        value = stmt.value
        if value is None:
            return True
        return _is_literal_expr(value)
    return False


def _is_literal_expr(node: ast.expr) -> bool:
    if isinstance(node, ast.Constant):
        return True
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return all(_is_literal_expr(elt) for elt in node.elts)
    if isinstance(node, ast.Dict):
        return all(_is_literal_expr(v) for v in node.values if v is not None)
    return False


def _count_trivial_matches(tree: ast.Module | None, target_lower: set[str]) -> int:
    if tree is None:
        return 0
    return sum(
        1
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name.lower() in target_lower
        and _is_trivial_stub_body(node.body)
    )


def _check_stubbed_model_call(
    old_tree: ast.Module | None,
    new_tree: ast.Module | None,
    new_source: str,
    model_call_names: frozenset[str],
    path: str,
) -> Violation | None:
    """Compares the *count* of trivially-stubbed functions matching a model
    call name before and after the patch, rather than flagging any match
    found anywhere in the new file — found live: a completely unrelated,
    untouched patch to a file could otherwise get falsely rejected purely
    because that file already contained, before any patching, a
    pass-bodied placeholder sharing a name with the real model call (an
    extremely common, entirely legitimate pattern: an abstract base
    class's method meant to be overridden by a real subclass). Comparing
    counts — the same before/after pattern _check_deleted_eval_call
    already uses — only flags a genuine *increase*, i.e. this patch
    actually introduced a new trivial stub, without needing to identify
    which specific occurrence changed. See DECISIONS.md.
    """
    if not model_call_names or new_tree is None:
        return None
    target_lower = {n.lower() for n in model_call_names}

    old_count = _count_trivial_matches(old_tree, target_lower)
    new_count = _count_trivial_matches(new_tree, target_lower)
    if new_count > old_count:
        return Violation(
            rule=GateRule.STUBBED_MODEL_CALL,
            reason=(
                f"trivially-stubbed functions matching a model/inference call "
                f"identified during recon increased from {old_count} to {new_count} "
                f"after the patch (a pass body or a hardcoded literal return)"
            ),
            file=path,
        )

    mock_call_re = re.compile(r"\b(Mock|MagicMock)\s*\(|@?patch\s*\(", re.IGNORECASE)
    name_re = re.compile(r"\b(" + "|".join(re.escape(n) for n in model_call_names) + r")\b")
    for line in new_source.splitlines():
        if mock_call_re.search(line) and name_re.search(line):
            return Violation(
                rule=GateRule.STUBBED_MODEL_CALL,
                reason="patch introduces a Mock/MagicMock/patch() targeting a real model/inference call",
                file=path,
            )
    return None


def _check_reduced_scale(
    patched_file: PatchedFile,
    old_source: str,
    path: str,
) -> Violation | None:
    for hunk in patched_file:
        removed = [l.value for l in hunk if l.is_removed]
        added = [l.value for l in hunk if l.is_added]
        removed_matches = {m.group(1).lower(): int(m.group(2)) for line in removed for m in [_SCALE_ASSIGN_RE.search(line)] if m}
        added_matches = {m.group(1).lower(): int(m.group(2)) for line in added for m in [_SCALE_ASSIGN_RE.search(line)] if m}
        for key, old_value in removed_matches.items():
            new_value = added_matches.get(key)
            if new_value is None or new_value >= old_value:
                continue
            # Allowed only if the *original* file already parameterizes this
            # value from something other than a plain literal elsewhere
            # (e.g. argparse), meaning the patch is restoring a broken
            # default rather than shrinking the experiment.
            already_parameterized = bool(
                re.search(
                    rf"add_argument\([^)]*['\"]--?{re.escape(key)}['\"]",
                    old_source,
                    re.IGNORECASE,
                )
            )
            if already_parameterized:
                continue
            return Violation(
                rule=GateRule.REDUCED_SCALE,
                reason=(
                    f"patch reduces '{key}' from {old_value} to {new_value}, "
                    f"and the original code does not already parameterize it "
                    f"via a CLI argument, so this is not a restored default"
                ),
                file=path,
            )
    return None


def _check_broad_exception_swallow(
    new_tree: ast.Module | None,
    added_lines: set[int],
    path: str,
) -> Violation | None:
    if new_tree is None:
        return None
    for node in ast.walk(new_tree):
        if not isinstance(node, ast.Try):
            continue
        try_start = node.lineno
        try_end = try_start
        for n in ast.walk(node):
            candidate = getattr(n, "end_lineno", None) or getattr(n, "lineno", None)
            if candidate is not None and candidate > try_end:
                try_end = candidate
        span = range(try_start, try_end + 1)
        if not all(ln in added_lines for ln in span):
            continue  # pre-existing try/except, not newly introduced by this patch
        for handler in node.handlers:
            is_broad = handler.type is None or (
                isinstance(handler.type, ast.Name) and handler.type.id in {"Exception", "BaseException"}
            )
            if not is_broad:
                continue
            body = handler.body
            swallows = all(
                isinstance(stmt, ast.Pass)
                or isinstance(stmt, ast.Continue)
                or (
                    isinstance(stmt, ast.Expr)
                    and isinstance(stmt.value, ast.Call)
                    and _call_short_name(stmt.value).lower() in _NOOP_EXCEPT_CALL_NAMES
                )
                for stmt in body
            )
            has_raise = any(isinstance(stmt, ast.Raise) for stmt in ast.walk(handler))
            if swallows and not has_raise:
                return Violation(
                    rule=GateRule.BROAD_EXCEPTION_SWALLOW,
                    reason=(
                        "patch newly introduces a bare/broad except clause that "
                        "swallows the exception (no re-raise) around code that "
                        "previously ran without this guard"
                    ),
                    file=path,
                )
    return None


# --- harness-v1.9 (D-74): a patch that skips a missing input ------------------------------------------------------------------------------------
# TEST-C spline-calibration: six candidates reached exit 0 by skipping every logit file that was not there (`if not os.path.exists(fname): continue`,
# `except FileNotFoundError: continue`, `DATA_FILES = [f for f in DATA_FILES if os.path.exists(f)]`), and no rule refused them; DEV img-comp-reference did
# the same with `return` in three rounds. The adjudicator refused all nine; the gate refused none.
#
# The rule compares the file's SKIP STRUCTURES before and after the patch (a multiset of signatures, not line numbers): a patch is refused when the patched
# file has a skip structure the original did not. So re-indented code, a changed print message and an unrelated edit never count, and an edited line cannot
# hide a skip (turning `if f.endswith('.tmp'): continue` into `... or not os.path.exists(f)`, or the `raise` of an existing check into `continue`).
# A skip structure is one of:
#   (a) a test that a path does NOT exist (`not os.path.exists(p)`, `== 0`, `is False`, `x not in os.listdir(d)`, `not glob.glob(p)`, also through an
#       `import ... as` alias) whose branch gives up;
#   (b) a test that a path exists, guarding a read, whose `else` only logs or skips (resume-from-checkpoint without the checkpoint);
#   (c) a test that a path exists, with no `else`, whose body is the READ that the test guards (a call that is passed the tested path, or an obvious reader);
#   (d) a handler for FileNotFoundError / IOError / OSError / EnvironmentError that gives up, unless the `try` body only creates or removes things
#       (`os.makedirs` / `os.remove` / `rmtree`: those are honest idioms);
#   (e) a handler for a BROAD exception (bare, Exception, BaseException) that gives up around a `try` body that reads an input;
#   (f) a collection filtered down to the paths that exist (list / set / dict comprehension, generator, `filter(os.path.exists, xs)`);
#   (g) a conditional expression that yields a literal when the path is missing (`load(f) if os.path.exists(f) else []`);
#   (h) `with contextlib.suppress(FileNotFoundError)` (or a broad exception around a read).
# "Gives up" = no `raise` other than `raise SystemExit` / `SystemExit(0)`, and every statement is a skip (`pass`, `continue`, `break`, a bare / literal /
# name `return`, an exit with status 0), a message (print / logging / warnings), bookkeeping (`n += 1`, `missing.append(f)`), or an assignment of a literal;
# for (a) and (b) at least one statement ends the work (or the branch is only `pass`). A check that RAISES (fails loudly, naming the path) is honest and
# passes; so is a branch that does real work (downloads or regenerates the input, `return download_and_run(f)`), and a guard that only creates a directory.
# Known strictness, stated: (c) also refuses `if os.path.exists('ckpt.pt'): state = load('ckpt.pt')` (resume if present): that is the skip of an input,
# and it changes what the run computes (DEV img-comp-reference's pretrained model was exactly this).
_EXISTS_CALLS = frozenset({"exists", "isfile", "isdir", "is_file", "is_dir", "access", "lexists", "glob", "iglob", "listdir", "scandir"})
_MESSAGE_CALLS = frozenset({"print", "log", "warn", "warning", "info", "debug", "error", "critical", "exception", "write"})
_BOOKKEEPING_CALLS = frozenset({"append", "add", "extend", "update", "setdefault", "insert", "discard"})
_FS_MUTATION_CALLS = frozenset({"makedirs", "mkdir", "remove", "unlink", "rmtree", "rmdir", "removedirs", "rename", "replace", "symlink", "chmod", "utime", "touch"})
_EXIT_CALLS = frozenset({"exit", "quit", "_exit"})
_MISSING_EXCEPTIONS = frozenset({"FileNotFoundError", "IOError", "OSError", "EnvironmentError"})
_BROAD_EXCEPTIONS = frozenset({"Exception", "BaseException"})
_READER_NAME = re.compile(r"^(?:open|load\w*|read\w*|unpickle\w*|parse\w*|fetch\w*|import_\w+)$", re.IGNORECASE)
_PATHISH_NAME = re.compile(r"(?:file|path|fname|filename|dir|dataset|data|ckpt|checkpoint|logit|weights?)", re.IGNORECASE)


def _exception_names(node: ast.expr | None) -> list[str]:
    if node is None:
        return ["<bare>"]
    elts = list(node.elts) if isinstance(node, ast.Tuple) else [node]
    return [n.id if isinstance(n, ast.Name) else n.attr if isinstance(n, ast.Attribute) else "?" for n in elts]


def _is_exit_zero_call(call: ast.Call) -> bool:
    if _call_short_name(call) not in _EXIT_CALLS:
        return False
    return not call.args or (isinstance(call.args[0], ast.Constant) and call.args[0].value in (0, None, False))


def _is_exit_zero_raise(stmt: ast.Raise) -> bool:
    exc = stmt.exc
    if isinstance(exc, ast.Name):
        return exc.id == "SystemExit"
    return isinstance(exc, ast.Call) and _call_short_name(exc) == "SystemExit" and (
        not exc.args or (isinstance(exc.args[0], ast.Constant) and exc.args[0].value in (0, None, False)))


def _skip_return(stmt: ast.Return) -> bool:
    v = stmt.value
    return v is None or _is_literal_expr(v) or isinstance(v, (ast.Name, ast.Attribute))


def _gives_up(body: list[ast.stmt], *, need_terminal: bool = True) -> bool:
    if not body:
        return False
    terminal = False
    for stmt in body:
        if isinstance(stmt, (ast.Continue, ast.Break)):
            terminal = True
        elif isinstance(stmt, ast.Return):
            if not _skip_return(stmt):
                return False  # `return download_and_run(f)`: the branch does the work some other way
            terminal = True
        elif isinstance(stmt, ast.Raise):
            if not _is_exit_zero_raise(stmt):
                return False  # fails loudly: honest
            terminal = True
        elif isinstance(stmt, ast.Pass):
            continue
        elif isinstance(stmt, ast.AugAssign):
            continue  # `skipped += 1`
        elif isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
            name = _call_short_name(stmt.value).lower()
            if _is_exit_zero_call(stmt.value):
                terminal = True
            elif name not in _MESSAGE_CALLS and name not in _BOOKKEEPING_CALLS:
                return False
        elif isinstance(stmt, (ast.Assign, ast.AnnAssign)) and stmt.value is not None and _is_literal_expr(stmt.value):
            continue
        elif isinstance(stmt, ast.If) and not stmt.orelse and _gives_up(stmt.body, need_terminal=need_terminal):
            terminal = True  # `if e.errno == 2: continue`
        else:
            return False
    return terminal or not need_terminal or all(isinstance(s, ast.Pass) for s in body)


def _only_fs_mutation(body: list[ast.stmt]) -> bool:
    """True when the statements only create or remove things (`os.makedirs(d)`, `os.remove(p)`): a FileNotFoundError there is not a missing input."""
    calls = [s for s in body if not (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant))]
    return bool(calls) and all(isinstance(s, ast.Expr) and isinstance(s.value, ast.Call) and _call_short_name(s.value) in _FS_MUTATION_CALLS for s in calls)


def _reads_input(body: list[ast.stmt]) -> bool:
    for stmt in body:
        for node in ast.walk(stmt):
            if not isinstance(node, ast.Call):
                continue
            if _READER_NAME.match(_call_short_name(node)):
                return True
            for arg in [*node.args, *(k.value for k in node.keywords)]:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str) and ("/" in arg.value or re.search(r"\.\w{1,5}$", arg.value)):
                    return True
                if isinstance(arg, (ast.Name, ast.Attribute)) and _PATHISH_NAME.search(ast.unparse(arg)):
                    return True
    return False


def _gated_read(body: list[ast.stmt], path_expr: str) -> bool:
    """True when a statement of `body` is a call passed the tested path (not a print, a bookkeeping call or a removal), or an obvious reader."""
    for stmt in body:
        for node in ast.walk(stmt):
            if not isinstance(node, ast.Call):
                continue
            name = _call_short_name(node)
            if name.lower() in _MESSAGE_CALLS or name in _FS_MUTATION_CALLS or name in _BOOKKEEPING_CALLS:
                continue
            if _READER_NAME.match(name) or (path_expr and any(path_expr in ast.unparse(a) for a in [*node.args, *(k.value for k in node.keywords)])):
                return True
    return False


def _skip_findings(tree: ast.Module | None) -> list[tuple[tuple, int, str]]:
    """(signature, line, what) of every skip structure in `tree` (see above); the signature never carries a line number or the body's text."""
    if tree is None:
        return []
    aliases = {a.asname for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) for a in n.names if a.asname and a.name in _EXISTS_CALLS}
    names = _EXISTS_CALLS | aliases

    def exists_call(n: ast.AST) -> bool:
        return isinstance(n, ast.Call) and _call_short_name(n) in names

    def has_exists(expr: ast.AST) -> bool:
        return any(exists_call(n) for n in ast.walk(expr))

    def exists_arg(expr: ast.AST) -> str:
        for n in ast.walk(expr):
            if exists_call(n) and n.args:
                return ast.unparse(n.args[0])
        return ""

    def negated(test: ast.expr) -> bool:
        if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
            return has_exists(test.operand)
        if isinstance(test, ast.BoolOp):
            return any(negated(v) for v in test.values)
        if isinstance(test, ast.Compare):
            sides = (test.left, *test.comparators)
            if any(isinstance(op, ast.NotIn) and exists_call(c) for op, c in zip(test.ops, test.comparators)):
                return True
            if len(test.ops) == 1 and isinstance(test.ops[0], (ast.Eq, ast.Is)):
                return any(exists_call(s) for s in sides) and any(isinstance(s, ast.Constant) and s.value in (False, 0) for s in sides)
        return False

    def literalish(node: ast.expr) -> bool:
        return isinstance(node, ast.Constant) or _is_literal_expr(node)

    out: list[tuple[tuple, int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.If):
            test = ast.dump(node.test)
            if negated(node.test) and _gives_up(node.body):
                out.append((("if-negated", test), node.lineno, "skips when a path does not exist"))
            elif has_exists(node.test) and not negated(node.test):
                if node.orelse and _gives_up(node.orelse, need_terminal=False) and _gated_read(node.body, exists_arg(node.test)):
                    out.append((("if-else", test), node.lineno, "skips in the `else` of a path-exists check"))
                elif not node.orelse and _gated_read(node.body, exists_arg(node.test)):
                    out.append((("if-guard", test), node.lineno, "reads the input only when it exists and does nothing when it is missing"))
        elif isinstance(node, ast.Try):
            for h in node.handlers:
                kinds = set(_exception_names(h.type))
                if not _gives_up(h.body, need_terminal=False):
                    continue
                sig = ("except", ast.dump(h.type) if h.type is not None else "bare", ast.dump(ast.Module(body=h.body, type_ignores=[])))
                if kinds & _MISSING_EXCEPTIONS and not _only_fs_mutation(node.body):
                    out.append((sig, h.lineno, "catches a missing file and gives up instead of failing"))
                elif (kinds & _BROAD_EXCEPTIONS or "<bare>" in kinds) and _reads_input(node.body):
                    out.append((sig, h.lineno, "catches every error around a read of an input and gives up instead of failing"))
        elif isinstance(node, (ast.ListComp, ast.SetComp, ast.GeneratorExp, ast.DictComp)):
            if any(has_exists(cond) for gen in node.generators for cond in gen.ifs):
                out.append((("comprehension", ast.dump(node)), node.lineno, "filters a collection down to the paths that exist"))
        elif isinstance(node, ast.Call) and _call_short_name(node) == "filter" and node.args and (
                has_exists(node.args[0]) or (isinstance(node.args[0], (ast.Name, ast.Attribute)) and ast.unparse(node.args[0]).split(".")[-1] in names)):
            out.append((("filter", ast.dump(node)), node.lineno, "filters a collection down to the paths that exist"))
        elif isinstance(node, ast.IfExp):
            if (has_exists(node.test) and not negated(node.test) and literalish(node.orelse)) or (negated(node.test) and literalish(node.body)):
                out.append((("ifexp", ast.dump(node)), node.lineno, "yields a literal when the path is missing"))
        elif isinstance(node, ast.With):
            for item in node.items:
                ctx = item.context_expr
                if isinstance(ctx, ast.Call) and _call_short_name(ctx) == "suppress":
                    kinds = {n for a in ctx.args for n in _exception_names(a)}
                    if kinds & _MISSING_EXCEPTIONS or (kinds & _BROAD_EXCEPTIONS and _reads_input(node.body)):
                        out.append((("suppress", ast.dump(ctx)), node.lineno, "suppresses a missing file around a read"))
    return out


def _check_skipped_missing_input(old_tree: ast.Module | None, new_tree: ast.Module | None, path: str) -> Violation | None:
    """A violation when the patched file has a skip structure that the original did not (a multiset comparison of signatures)."""
    if new_tree is None:
        return None
    before = Counter(sig for sig, _, _ in _skip_findings(old_tree))
    seen: Counter = Counter()
    for sig, lineno, what in _skip_findings(new_tree):
        seen[sig] += 1
        if seen[sig] > before[sig]:
            return Violation(
                rule=GateRule.SKIPPED_MISSING_INPUT, file=path,
                reason=(f"patch adds code that {what} (line {lineno}): the run would go on without an input it cannot find and could end with exit 0 having done "
                        f"less; a missing input must fail loudly (raise, naming the path) or be supplied"))
    return None


_PY_EXE = re.compile(r"^(?:.*/)?python(?:\d+(?:\.\d+)*)?$")


def documented_scripts(command: str | None) -> frozenset[str]:
    """harness-v1.9 (D-55 / D-75). The repository-relative `.py` file a documented command RUNS: the first positional argument of a `python` interpreter
    (`python test_SCIGAN.py ...`, `CUDA_VISIBLE_DEVICES=0 python3 -u x.py`, `cd src && python3 ./test_a.py`), normalised like diff paths. Nothing else: not a
    later argument (`--config configs/test_cfg.py`), not what `pytest` / `python -m pytest` / `python -m unittest` run, not a script named after `sh`.
    Pure; a path that is not plain and relative is ignored."""
    out: set[str] = set()
    prefix = ""
    for segment in re.split(r"&&|\|\||;|\|", command or ""):
        try:
            tokens = shlex.split(segment, comments=True)
        except ValueError:
            continue
        i = 0
        while i < len(tokens) and re.match(r"^[A-Za-z_]\w*=", tokens[i]):
            i += 1
        if i >= len(tokens):
            continue
        if tokens[i] == "cd" and i + 1 < len(tokens):
            prefix = "" if tokens[i + 1] in (".", "./") else tokens[i + 1].rstrip("/") + "/"
            continue
        if not _PY_EXE.match(tokens[i]):
            continue
        j = i + 1
        while j < len(tokens) and tokens[j].startswith("-"):
            if tokens[j] in ("-m", "-c"):
                j = len(tokens)
                break
            j += 1
        if j < len(tokens) and tokens[j].endswith(".py"):
            norm, err = _normalize_header_path(prefix + tokens[j])
            if not err and norm != _DEV_NULL:
                out.add(norm)
    return frozenset(out)


# Deterministic floor for the names rules 1-2 protect. Recon's model-provided
# eval/model call names are untrusted (a prompt-injected recon can simply
# return empty lists, which would switch DELETED_EVAL_CALL and
# STUBBED_MODEL_CALL off entirely). The orchestrator unions these
# AST-derived names with recon's. Deliberately conservative: a false
# positive only makes the gate stricter about removing such a call.
_HEURISTIC_EVAL_NAME_RE = re.compile(r"eval|metric|accuracy|score|assert", re.IGNORECASE)
_HEURISTIC_MODEL_CALL_NAMES = frozenset(
    {"forward", "predict", "predict_proba", "generate", "infer", "inference", "run_inference", "fit", "train", "train_step"}
)


def _called_short_names(source: str) -> set[str]:
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return set()
    return {name for node in ast.walk(tree) if isinstance(node, ast.Call) and (name := _call_short_name(node))}


def heuristic_eval_call_names(source: str) -> frozenset[str]:
    """Names of functions *called* in `source` that look like evaluation /
    metric / assertion calls (by name, from the AST — never from a model)."""
    return frozenset(n for n in _called_short_names(source) if _HEURISTIC_EVAL_NAME_RE.search(n))


def heuristic_model_call_names(source: str) -> frozenset[str]:
    """Names of functions called in `source` that are conventional
    model inference/training entrypoints (forward, predict, generate, ...)."""
    return frozenset(n for n in _called_short_names(source) if n.lower() in _HEURISTIC_MODEL_CALL_NAMES)


def check_patch(
    diff_text: str,
    original_sources: Mapping[str, str],
    eval_call_names: frozenset[str] = frozenset(),
    model_call_names: frozenset[str] = frozenset(),
    protected_patterns: frozenset[str] = DEFAULT_PROTECTED_PATTERNS,
    max_changed_lines: int = 40,
    repo_root: Path | None = None,
    documented_files: frozenset[str] = frozenset(),
) -> GateResult:
    """Check a unified diff against every §5.3 rejection rule.

    `original_sources` maps normalized repo-relative path -> full original
    content, and must cover EVERY file the diff modifies: a touched file
    whose original is missing is REJECTED (UNVERIFIED_FILE), never skipped.
    `documented_files` (harness-v1.9, D-55): the repository-relative files the documented command runs (`documented_scripts`); they are exempt from
    the test-file naming rule only.
    Paths are normalized by `prepare_patch`; the returned `canonical_diff`
    is what must be applied. If `repo_root` is given, read-only filesystem
    checks (symlinks, escaping the root) run too; otherwise the gate stays
    fully pure.
    """
    prepared = prepare_patch(diff_text)
    violations: list[Violation] = list(prepared.violations)
    if prepared.patch_set is None:
        return GateResult(decision="REJECT", violations=tuple(violations))
    if repo_root is not None:
        violations.extend(check_paths_on_disk(repo_root, prepared.paths))
    normalized_sources = {}
    for key, value in original_sources.items():
        norm, err = _normalize_header_path(key)
        if not err:
            normalized_sources[norm] = value

    total_changed = 0
    by_path = {}
    for patched_file in prepared.patch_set:
        norm, err = _normalize_header_path(patched_file.target_file)
        if not err and norm in prepared.paths:
            by_path[norm] = patched_file
    for path in prepared.paths:
        patched_file = by_path[path]
        total_changed += patched_file.added + patched_file.removed

        if _is_protected_path(path, protected_patterns, documented_files):
            violations.append(
                Violation(
                    rule=GateRule.PROTECTED_PATH_MODIFIED,
                    reason=(
                        f"patch modifies '{path}', which is a protected path "
                        f"(classifier, gate, corpus, or test file) — a patch "
                        f"may only touch the target repo's own code"
                    ),
                    file=path,
                )
            )
            continue

        is_added = path in prepared.added_paths
        old_source = "" if is_added else normalized_sources.get(path)
        if old_source is None:
            # The hole found live on 2026-09-24: this used to `continue`,
            # so a diff editing any file the caller didn't pass was PASSED
            # with zero checks and then applied.
            violations.append(
                Violation(
                    rule=GateRule.UNVERIFIED_FILE,
                    reason=(
                        f"patch modifies '{path}', but the gate was not given its original "
                        f"content (missing from the checkout or not loaded) — cannot verify it"
                    ),
                    file=path,
                )
            )
            continue

        if not path.endswith(".py"):
            continue

        try:
            new_source = _apply_patched_file(old_source, patched_file)
        except Exception:
            violations.append(
                Violation(
                    rule=GateRule.UNPARSEABLE_PATCH,
                    reason=f"could not reconstruct post-patch content for '{path}' from the diff hunks",
                    file=path,
                )
            )
            continue

        old_tree: ast.Module | None
        try:
            old_tree = ast.parse(old_source) if old_source.strip() else ast.parse("")
        except SyntaxError:
            old_tree = None

        try:
            new_tree = ast.parse(new_source)
        except SyntaxError as exc:
            violations.append(
                Violation(
                    rule=GateRule.UNPARSEABLE_PATCH,
                    reason=f"'{path}' does not parse as valid Python after the patch: {exc}",
                    file=path,
                )
            )
            continue

        for check in (
            _check_deleted_eval_call(old_tree, new_tree, eval_call_names, path),
            _check_stubbed_model_call(old_tree, new_tree, new_source, model_call_names, path),
            _check_reduced_scale(patched_file, old_source, path),
            _check_broad_exception_swallow(new_tree, _added_target_lines(patched_file), path),
            _check_skipped_missing_input(old_tree, new_tree, path),
        ):
            if check is not None:
                violations.append(check)

    if total_changed > max_changed_lines:
        violations.append(
            Violation(
                rule=GateRule.DIFF_TOO_LARGE,
                reason=(
                    f"patch changes {total_changed} lines, exceeding the "
                    f"{max_changed_lines}-line ceiling for a minimal fix"
                ),
            )
        )

    decision = "REJECT" if violations else "PASS"
    return GateResult(
        decision=decision,
        violations=tuple(violations),
        canonical_diff=prepared.canonical_diff,
        touched_paths=prepared.paths,
        semantic_change=semantic_change_calls(prepared.canonical_diff or diff_text),
    )


# --- harness-v1.7 (R6, D-44): a patch that changes what the code computes ---------------------------------------------------------------------
# The gate refuses a patch that makes the code do LESS (stubbed calls, reduced scale, swallowed errors); it does not check numerical equivalence.
# DEV #14, round 3: `torch.lu(x, pivot=False)` became the PIVOTING `torch.linalg.lu_factor(x)`, the gate passed it and the entry ended
# RUNS_AFTER_REPAIR. A fixed list of calls whose replacement changes a result: a changed line (added or removed, in a .py file, not a comment)
# that touches one marks the patch. The list is the pre-registered one (METHODOLOGY, harness-v1.7, R6); it errs on the side of marking.
SEMANTIC_CALLS: tuple[tuple[str, re.Pattern], ...] = (
    ("torch.lu", re.compile(r"\btorch\.lu\b(?!_)")),
    ("linalg", re.compile(r"\blinalg\.\w+")),
    ("solve", re.compile(r"\b(?:solve|lstsq|lu_solve|cholesky_solve|triangular_solve)\s*\(")),
    ("inverse", re.compile(r"\b(?:inverse|inv|pinv|pinverse)\s*\(")),
    ("eig", re.compile(r"\b(?:eig|eigh|eigvals|eigvalsh|symeig)\s*\(")),
    ("svd", re.compile(r"\b(?:svd|svd_lowrank|svdvals)\s*\(")),
    ("cholesky", re.compile(r"\bcholesky\s*\(")),
    ("qr", re.compile(r"\bqr\s*\(")),
    ("det", re.compile(r"\b(?:det|slogdet|logdet)\s*\(")),
    ("random seed", re.compile(r"\b(?:manual_seed|manual_seed_all|seed|set_seed|set_random_seed|default_rng|RandomState)\s*\(")),
    ("dtype cast", re.compile(r"\.(?:float|double|half|bfloat16|long|int|short)\s*\(\s*\)|\.to\s*\([^)]*\bdtype\b|\.to\s*\(\s*torch\.(?:float|double|half|bfloat16|int|long)"
                              r"|\bastype\s*\(|\.type\s*\(\s*torch\.|\bset_default_dtype\s*\(|\bset_default_tensor_type\s*\(")),
    ("loss", re.compile(r"\b\w*(?:loss|Loss)\s*\(|\bcriterion\s*\(")),
)


def semantic_change_calls(diff_text: str) -> tuple[str, ...]:
    """PURE. The names (SEMANTIC_CALLS order) of the listed calls that the changed lines of a unified diff touch, in .py files only; comment
    lines and diff headers are skipped. Empty for a diff that touches none (or is not a diff)."""
    found: set[str] = set()
    python_file = False
    for line in (diff_text or "").splitlines():
        if line.startswith("+++ ") or line.startswith("--- "):
            target = line[4:].strip().split("\t")[0]
            if line.startswith("+++ ") or target != _DEV_NULL:
                python_file = target.endswith(".py") if target != _DEV_NULL else python_file
            continue
        if line.startswith("diff --git"):
            python_file = line.rstrip().endswith(".py")
            continue
        if not python_file or not line[:1] in ("+", "-"):
            continue
        code = line[1:].split("#", 1)[0]
        if not code.strip():
            continue
        for name, pattern in SEMANTIC_CALLS:
            if pattern.search(code):
                found.add(name)
    return tuple(name for name, _ in SEMANTIC_CALLS if name in found)


# --- harness-v1.7.2: an injected default input --------------------------------------------------------------------------------------------------
# Live UI scan, 2026-10-05 (`faris-shi/py_weather_cli`, runs/live_scan/): the adopted model patch answered the authors' `raise ValueError('please enter
# the city name')` with `weather_config.city_name = 'Toronto'`: the run then used an input the authors never gave, and no semantic-change label was set.
# A patch "injects a default" when an ADDED line assigns a literal (a string, a number or a bool, never None) to a name and either (a) the same hunk
# REMOVES a `raise` line, or (b) the assignment sits right under an `if` / `elif` (added or kept) whose condition tests that same name for being empty,
# false or None (`not x`, `x is None`, `len(x) == 0`, `x == ''`). Not a rejection: the flag joins R6's list as "injected default". It is stored on the
# attempt record by harness-v1.7.2 and later only (`AttemptRecord.as_dict`); `semantic_change_calls` is unchanged, so a record written before this
# version, read again, is never newly flagged (outcome_levels recomputes an unstored flag with semantic_change_calls alone).
INJECTED_DEFAULT = "injected default"
_LITERAL_ASSIGN_RE = re.compile(
    r"^\s*(?P<target>[A-Za-z_][\w.]*(?:\[\s*(?:'[^']*'|\"[^\"]*\")\s*\])?)\s*=\s*"
    r"(?P<literal>'[^'\n]*'|\"[^\"\n]*\"|-?\d+(?:\.\d+)?|True|False)\s*(?:#.*)?$"
)
_RAISE_RE = re.compile(r"^\s*raise\b")
_GUARD_RE = re.compile(r"^\s*(?:el)?if\b")
_EMPTY_TEST_RE = re.compile(r"\bnot\b|\bis\s+None\b|==\s*0\b|==\s*(?:''|\"\")|\blen\s*\(")


def _assigned_name(target: str) -> str:
    key = re.search(r"\[\s*['\"]([^'\"]*)['\"]\s*\]$", target)
    return key.group(1) if key else target.rsplit(".", 1)[-1]


def injected_default(diff_text: str) -> tuple[str, ...]:
    """PURE. `(INJECTED_DEFAULT,)` when an added line of a .py hunk injects a literal default input (see above), else ()."""
    python_file = False
    hunk: list[tuple[str, str]] = []

    def _hunk_flags() -> bool:
        removes_raise = any(kind == "-" and _RAISE_RE.match(text.split("#", 1)[0]) for kind, text in hunk)
        kept = [(kind, text) for kind, text in hunk if kind != "-"]
        for i, (kind, text) in enumerate(kept):
            if kind != "+":
                continue
            assign = _LITERAL_ASSIGN_RE.match(text)
            if not assign:
                continue
            if removes_raise:
                return True
            above = next((t for _, t in reversed(kept[:i]) if t.strip()), "")
            name = _assigned_name(assign.group("target"))
            if _GUARD_RE.match(above) and re.search(rf"\b{re.escape(name)}\b", above) and _EMPTY_TEST_RE.search(above):
                return True
        return False

    for line in (diff_text or "").splitlines():
        if line.startswith(("+++ ", "--- ", "diff --git", "@@")):
            if python_file and hunk and _hunk_flags():
                return (INJECTED_DEFAULT,)
            hunk = []
            if line.startswith("+++ "):
                python_file = line[4:].strip().split("\t")[0].endswith(".py")
            continue
        if line[:1] in ("+", "-", " "):
            hunk.append((line[:1], line[1:]))
    if python_file and hunk and _hunk_flags():
        return (INJECTED_DEFAULT,)
    return ()


# harness-v1.3.4 (D-19). Added lines a diagnostics-only patch may contain: prints, logging, stderr writes, tracebacks, faulthandler,
# and the imports they need. Anything else (or any removed line) is a code change made without an error to act on.
_DIAGNOSTIC_LINE_RE = re.compile(
    r"^\s*(?:print\(|logging\.[a-z]+\(|logger\.[a-z]+\(|log\.[a-z]+\(|sys\.stderr\.write\(|sys\.stdout\.write\(|sys\.stderr\.flush\(\)"
    r"|sys\.stdout\.flush\(\)|traceback\.print_(?:exc|stack)\(|faulthandler\.(?:enable|dump_traceback)\(|import (?:sys|logging|traceback|faulthandler)\b"
    r"|from (?:sys|logging|traceback|faulthandler) import\b|logging\.basicConfig\(|#)"
)


def diagnostics_only_violation(diff_text: str) -> Violation | None:
    """None if every change in `diff_text` is an added diagnostic line (see _DIAGNOSTIC_LINE_RE) and nothing is removed;
    else the BLIND_PATCH_ON_SILENT_EXIT violation naming the first offending line."""
    try:
        patch_set = PatchSet(diff_text)
    except Exception as exc:  # noqa: BLE001
        return Violation(rule=GateRule.UNPARSEABLE_PATCH, reason=f"diff could not be parsed: {exc}")
    for patched_file in patch_set:
        for hunk in patched_file:
            for line in hunk:
                if line.is_removed and line.value.strip():
                    return Violation(
                        rule=GateRule.BLIND_PATCH_ON_SILENT_EXIT,
                        reason=f"the failing run printed no error text; a patch may then only ADD diagnostics, but this one removes {line.value.strip()[:60]!r}",
                        file=patched_file.target_file,
                    )
                if line.is_added and line.value.strip() and not _DIAGNOSTIC_LINE_RE.match(line.value):
                    return Violation(
                        rule=GateRule.BLIND_PATCH_ON_SILENT_EXIT,
                        reason=f"the failing run printed no error text; a patch may then only ADD diagnostics (print/logging/traceback/faulthandler), but this one adds {line.value.strip()[:60]!r}",
                        file=patched_file.target_file,
                    )
    return None


def patched_sources(diff_text: str, original_sources: Mapping[str, str]) -> dict[str, str]:
    """harness-v1.4.0-rc. The post-patch text of every file `diff_text` touches and whose original is in `original_sources` (an added
    file starts empty), reconstructed the same way the gate reads it. Pure."""
    prepared = prepare_patch(diff_text)
    if prepared.patch_set is None:
        return {}
    normalized = {}
    for key, value in original_sources.items():
        norm, err = _normalize_header_path(key)
        if not err:
            normalized[norm] = value
    out: dict[str, str] = {}
    for patched_file in prepared.patch_set:
        norm, err = _normalize_header_path(patched_file.target_file)
        if err or norm not in prepared.paths:
            continue
        old = "" if norm in prepared.added_paths else normalized.get(norm)
        if old is None:
            continue
        try:
            out[norm] = _apply_patched_file(old, patched_file)
        except Exception:  # noqa: BLE001 - check_patch reports it as UNPARSEABLE_PATCH
            continue
    return out


def py_compile_violations(diff_text: str, original_sources: Mapping[str, str]) -> tuple[Violation, ...]:
    """harness-v1.4.0-rc: every patched .py file must compile (the check `python -m py_compile` makes), with this interpreter's
    grammar, the same one the gate's ast.parse uses. Pure."""
    found: list[Violation] = []
    for path, source in patched_sources(diff_text, original_sources).items():
        if not path.endswith(".py"):
            continue
        try:
            compile(source, path, "exec", dont_inherit=True)
        except (SyntaxError, ValueError) as exc:
            found.append(Violation(rule=GateRule.PY_COMPILE_FAILED,
                                   reason=f"'{path}' does not compile after the patch (py_compile): {exc}", file=path))
    return tuple(found)
