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
    # Path safety (added 2026-09-25 after the live runs exposed that a diff
    # touching a file the gate was never given passed unchecked).
    UNSAFE_PATH = "UNSAFE_PATH"  # absolute, ../, outside repo root, symlink, rename
    FILE_DELETION = "FILE_DELETION"  # +++ /dev/null — deleting a whole file
    UNVERIFIED_FILE = "UNVERIFIED_FILE"  # touched file whose original the gate did not get


DEFAULT_PROTECTED_PATTERNS: frozenset[str] = frozenset(
    {
        "app/services/classifier.py",
        "app/services/tamper_gate.py",
        "app/batch/corpus.yaml",
        "corpus.yaml",
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


def _is_protected_path(path: str, protected_patterns: frozenset[str]) -> bool:
    normalized = path.replace("\\", "/").lstrip("./")
    if normalized in protected_patterns:
        return True
    for pattern in protected_patterns:
        if normalized.endswith("/" + pattern) or normalized == pattern:
            return True
    filename = normalized.rsplit("/", 1)[-1]
    if filename.startswith("test_") or filename.endswith("_test.py"):
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
) -> GateResult:
    """Check a unified diff against every §5.3 rejection rule.

    `original_sources` maps normalized repo-relative path -> full original
    content, and must cover EVERY file the diff modifies: a touched file
    whose original is missing is REJECTED (UNVERIFIED_FILE), never skipped.
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

        if _is_protected_path(path, protected_patterns):
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
    )
