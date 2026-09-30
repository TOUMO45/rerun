"""Static import scan of a whole repository tree -> the ONE batch of packages to install (harness-v1.3.3, D-1/D-5/D-12).

Replaces one-at-a-time repair of `ModuleNotFoundError` (each repair attempt fixed one name; chains such as
sklearn -> ruamel.yaml -> language_evaluation, or six -> h5py -> skimage, used all three attempts). Pure: reads files
under `root`, never runs them, no network.

    scan = scan_repo(root)
    batch = batch_install_set(scan, declared_dependencies)
    batch.distributions     # what to install, in one step: import -> PyPI distribution (cited mapping table)
    batch.internal          # imports that resolve INSIDE the tree (never a PyPI package)
    batch.optional          # imports only ever guarded by try/except ImportError (skipped: optional extras)
    batch.python2_only      # py2 stdlib names (urllib2, cPickle...): no PyPI package can satisfy them

A module is INTERNAL (the repository's own) if any of these holds anywhere in the tree:
  - a `<name>.py` file, or a directory `<name>/` that contains Python (a package, regular or namespace);
  - a compiled module `<name>.so` / `<name>.pyd` / `<name>.cpython-*.so`;
  - a native extension the repository's own build script declares (`Extension('<name>._ext', ...)`,
    `CUDAExtension`, `CppExtension`, cffi `set_source`, `create_extension`), e.g. `operators._ext` (corpus-v2 entry 19):
    its top-level package `operators` is the repo's; the `_ext` submodule needs the repo's documented build step and is
    never a PyPI distribution.
`shadows_repo_module` is the dependency-confusion guard: an install whose name matches an internal module is refused
(corpus-v2 entry 19 pip-installed the unrelated PyPI project `operators==1.0.0` for the repo's own `operators._ext`).
"""

from __future__ import annotations

import ast
import os
import re
import sys
import warnings
from dataclasses import dataclass
from pathlib import Path

from app.services.import_names import ImportMapping, mapping_for

MAX_PY_FILES = 4000
MAX_PY_BYTES = 400_000
_SKIP_DIRS = {".git", "__pycache__", "node_modules", "site-packages", ".ipynb_checkpoints"}

# Modules present in older interpreters' stdlib but removed from the one this backend runs on.
_STDLIB_EXTRA = {"__future__", "distutils", "imp", "asynchat", "asyncore", "smtpd"}
# Python 2 standard-library names: a Python 3 sandbox cannot install them from anywhere.
PYTHON2_ONLY = frozenset({
    "urllib2", "urlparse", "ConfigParser", "cPickle", "cStringIO", "Queue", "StringIO", "Tkinter", "tkMessageBox",
    "tkFileDialog", "commands", "httplib", "HTMLParser", "__builtin__", "xmlrpclib", "SocketServer", "thread",
    "md5", "sha", "sets", "exceptions", "copy_reg", "anydbm", "dummy_thread", "repr", "UserDict", "UserList",
    "UserString", "cookielib", "Cookie", "htmlentitydefs", "BaseHTTPServer", "SimpleHTTPServer", "CGIHTTPServer",
    "ttk", "tkSimpleDialog",
})
# Build tooling every python:X-slim image already ships; `setup.py` importing it is not a dependency.
_PROVIDED = frozenset({"setuptools", "pkg_resources", "pip", "wheel"})
_EXT_DECL_RE = re.compile(
    r"(?:Extension|CppExtension|CUDAExtension|set_source|create_extension)\(\s*(?:name\s*=\s*)?['\"]([\w.]+)['\"]"
)
_IMPORT_ERRORS = {"ImportError", "ModuleNotFoundError", "Exception", "BaseException"}


# Namespace roots whose PyPI distribution is named after the SECOND component (`import ruamel.yaml` -> `ruamel.yaml`, not the
# pipreqs table's `ruamel-base`, which does not provide it: corpus-v2 entry 16 met `ruamel.yaml` one attempt late).
NAMESPACE_ROOTS = frozenset({"ruamel"})


@dataclass(frozen=True)
class ImportRecord:
    module: str  # top-level name
    guarded: bool  # every occurrence sits in a try/except that catches ImportError
    files: int  # number of files importing it
    submodules: tuple[str, ...] = ()  # second components seen, for NAMESPACE_ROOTS only


@dataclass(frozen=True)
class ImportScan:
    imports: tuple[ImportRecord, ...]
    internal: frozenset[str]  # lower-cased names that resolve inside the tree
    files_scanned: int
    truncated: bool = False


@dataclass(frozen=True)
class BatchInstall:
    distributions: tuple[tuple[str, ImportMapping | None], ...]  # (PyPI distribution, mapping used or None), sorted
    internal: tuple[str, ...]
    optional: tuple[str, ...]
    python2_only: tuple[str, ...]
    declared: tuple[str, ...]  # imports whose distribution the repo already declares

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(dist for dist, _ in self.distributions)

    def as_dict(self) -> dict:
        return {
            "install": list(self.names),
            "internal_excluded": list(self.internal),
            "optional_skipped": list(self.optional),
            "python2_only_skipped": list(self.python2_only),
            "already_declared": list(self.declared),
            "import_mappings": [m.as_dict() for _, m in self.distributions if m is not None],
        }


def _norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def stdlib_names() -> frozenset[str]:
    return frozenset(getattr(sys, "stdlib_module_names", ())) | _STDLIB_EXTRA


def _catches_import_error(handler: ast.ExceptHandler) -> bool:
    if handler.type is None:
        return True
    nodes = handler.type.elts if isinstance(handler.type, ast.Tuple) else [handler.type]
    for node in nodes:
        name = node.id if isinstance(node, ast.Name) else node.attr if isinstance(node, ast.Attribute) else ""
        if name in _IMPORT_ERRORS:
            return True
    return False


def _imports_in(tree: ast.AST) -> list[tuple[str, bool, str]]:
    """(top-level module, guarded, dotted name) for every absolute import; guarded = inside a `try` whose handlers catch
    ImportError."""
    found: list[tuple[str, bool, str]] = []

    def visit(node: ast.AST, guarded: bool) -> None:
        if isinstance(node, ast.Import):
            found.extend((alias.name.split(".")[0], guarded, alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                found.append((node.module.split(".")[0], guarded, node.module))
        elif isinstance(node, ast.Try):
            body_guarded = guarded or any(_catches_import_error(h) for h in node.handlers)
            for child in node.body:
                visit(child, body_guarded)
            for part in (node.handlers, node.orelse, node.finalbody):
                for child in part:
                    visit(child, guarded)
            return
        for child in ast.iter_child_nodes(node):
            visit(child, guarded)

    visit(tree, False)
    return found


def _walk(root: Path):
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = sorted(d for d in dirnames if d not in _SKIP_DIRS)
        yield Path(dirpath), sorted(filenames)


def internal_module_names(root: Path) -> frozenset[str]:
    """Lower-cased names importable from inside the tree (see the module docstring for the definition)."""
    names: set[str] = set()
    for current, filenames in _walk(root):
        rel = current.relative_to(root)
        has_python = False
        for filename in filenames:
            path = current / filename
            if path.is_symlink():
                continue
            if filename.endswith(".py"):
                has_python = True
                stem = filename[:-3]
                if stem != "__init__":
                    names.add(stem.lower())
                lowered = filename.lower()
                if lowered == "setup.py" or "build" in lowered:
                    try:
                        if path.stat().st_size <= MAX_PY_BYTES:
                            text = path.read_text(encoding="utf-8", errors="ignore")
                            names.update(m.group(1).split(".")[0].lower() for m in _EXT_DECL_RE.finditer(text))
                    except OSError:
                        pass
            elif filename.endswith((".so", ".pyd")):
                names.add(filename.split(".", 1)[0].lower())
        if has_python:
            names.update(part.lower() for part in rel.parts)
    names.discard("")
    return frozenset(names)


def scan_repo(root: Path) -> ImportScan:
    counts: dict[str, list[int]] = {}  # module -> [files, unguarded files]
    subs: dict[str, set[str]] = {}
    files_scanned, truncated = 0, False
    for current, filenames in _walk(root):
        for filename in filenames:
            if not filename.endswith(".py"):
                continue
            path = current / filename
            if path.is_symlink():
                continue
            if files_scanned >= MAX_PY_FILES:
                truncated = True
                break
            files_scanned += 1
            try:
                if path.stat().st_size > MAX_PY_BYTES:
                    continue
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")  # repositories' own invalid escape sequences are not our output
                    tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
            except (OSError, SyntaxError, ValueError):
                continue
            seen_here: dict[str, bool] = {}
            for module, guarded, dotted in _imports_in(tree):
                seen_here[module] = seen_here.get(module, True) and guarded
                parts = dotted.split(".")
                if module in NAMESPACE_ROOTS and len(parts) > 1:
                    subs.setdefault(module, set()).add(parts[1])
            for module, all_guarded in seen_here.items():
                entry = counts.setdefault(module, [0, 0])
                entry[0] += 1
                entry[1] += 0 if all_guarded else 1
        if truncated:
            break
    records = tuple(
        ImportRecord(m, unguarded == 0, files, tuple(sorted(subs.get(m, ()))))
        for m, (files, unguarded) in sorted(counts.items())
    )
    return ImportScan(records, internal_module_names(root), files_scanned, truncated)


def batch_install_set(scan: ImportScan, declared: frozenset[str]) -> BatchInstall:
    stdlib = stdlib_names()
    declared_norm = {_norm(d) for d in declared}
    distributions: dict[str, ImportMapping | None] = {}
    internal, optional, py2, already = [], [], [], []
    for record in scan.imports:
        module = record.module
        if module in stdlib or module in _PROVIDED or module.startswith("_"):
            continue
        if module.lower() in scan.internal:
            internal.append(module)
            continue
        if module in PYTHON2_ONLY:
            py2.append(module)
            continue
        if module in NAMESPACE_ROOTS and record.submodules:
            targets = [(f"{module}.{sub}", None) for sub in record.submodules]
        else:
            mapping = mapping_for(module)
            targets = [(mapping.distribution if mapping else module, mapping)]
        if all(_norm(dist) in declared_norm for dist, _ in targets) or _norm(module) in declared_norm:
            already.append(module)
            continue
        if record.guarded:
            optional.append(module)
            continue
        for dist, mapping in targets:
            if _norm(dist) not in declared_norm:
                distributions.setdefault(dist, mapping)
    return BatchInstall(
        tuple(sorted(distributions.items(), key=lambda kv: _norm(kv[0]))),
        tuple(sorted(set(internal))), tuple(sorted(set(optional))), tuple(sorted(set(py2))), tuple(sorted(set(already))),
    )


def import_names_for_distribution(package: str) -> set[str]:
    """Every import name `package` could be imported as (lower-cased): the name itself, `-`->`_`, the dist->import
    table of the env gate, and every module the cited import map sends to this distribution."""
    from app.services.env_repair import import_name_for  # local import: env_repair imports this module's callers

    norm = _norm(package)
    names = {norm, norm.replace("-", "_"), import_name_for(package).lower()}
    from app.services import import_names

    for module, row in import_names._rows().items():  # noqa: SLF001 - read-only view of the cited table
        if _norm(row[0]) == norm:
            names.add(module.lower())
    return names


def shadows_repo_module(package: str, internal: frozenset[str]) -> str | None:
    """The internal module name that `package` would shadow or be confused with, else None."""
    hit = import_names_for_distribution(package) & internal
    return sorted(hit)[0] if hit else None
