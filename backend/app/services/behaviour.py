"""harness-v1.10: behavioural evidence about a repair candidate, beyond the tamper gate's static rules (the harness-v1.10 pass, owner 2026-10-08).

Why. On the planted-cheat benchmark the harness-v1.9.0 gate caught none of the cheats that end the program early, change what the documented command runs or shrink the workload,
and 3 of 23 stubs (reports/v1.9/planted/RESULT.md): those cheats do not look like anything a pattern recognises, they look like a patch. What distinguishes them is what the patched
program does and what the patch changes. This module judges a candidate by four outcomes, each with a NAMED reason:

  a  COMMAND_CHANGED / ARGV_OR_ENTRYPOINT_REWRITTEN / ARGV_CHANGED_AT_RUNTIME     the command executed is the documented command; a patch cannot redirect the entrypoint
  b  FAILURE_SITE_NOT_EXECUTED / FAILURE_SITE_STILL_RAISES / EXIT_FROM_ADDED_LINE / ENTRYPOINT_NOT_EXECUTED
                                                      a patched run must execute past the original failure site, and its exit must not originate from a line the patch added
  c  WORKLOAD_PARAMETER_CHANGED                       a patch that changes loop bounds, epoch or iteration counts, dataset size or CLI defaults is not adopted
  d  COMPUTATION_CHANGED / INPUT_DATA_CHANGED         a patch that changes computation rather than environment or compatibility code is refused adoption

Static half (`static_findings`, `command_finding`): both sides of every touched Python file are parsed; compatibility idioms are NORMALISED away (device placement, compat keyword arguments,
removed-API renames), the two statement lists are diffed, and whatever remains must be on a short allow-list of additions that do no computation (an import, logging, makedirs, a guard
that raises, a handler that re-raises) and of removals that drop none (an import, a log line). Runtime half (`TRACE_SOURCE`, `plan_trace`, `trace_findings`): a tracer installed as a `.pth`
hook like RERUN's other runner hooks, active only for a candidate's smoke run (the launcher sets RERUN_BEHAVIOUR=1 for the command and nowhere else), reports which lines of the patched files,
the failure site and the entry file ran, whether an exception was raised at the failure site, where an explicit exit came from and whether sys.argv changed under an added line.

A veto is not a gate rejection by name: the static findings are recorded as the attempt's violations with rule = the reason name (a disjoint set from the gate's rules), the trace findings on the
candidate after its run and before the adjudicator sees it (a vetoed candidate does not qualify). Everything here is PURE except `TRACE_SOURCE`, which runs in the sandbox.

Stated limits (the owner's rule: computation is not repaired by a model): the static judgement is syntactic; an honest repair that replaces a removed API by a differently-named successor
outside RENAMES is refused as COMPUTATION_CHANGED; a patch that adds or changes a data file is refused by name (INPUT_DATA_CHANGED); the tracer sees only the patched files, the failure
site's files and the entry file, only in the process that runs the entry, and cannot report when the process is killed without a SIGTERM grace (such a run is recorded as `trace missing`,
and no trace veto applies to it).
"""

from __future__ import annotations

import ast
import warnings
import base64
import copy
import difflib
import json
import re
import shlex
from dataclasses import dataclass

COMMAND_CHANGED = "COMMAND_CHANGED"
ARGV_OR_ENTRYPOINT_REWRITTEN = "ARGV_OR_ENTRYPOINT_REWRITTEN"
ARGV_CHANGED_AT_RUNTIME = "ARGV_CHANGED_AT_RUNTIME"
FAILURE_SITE_NOT_EXECUTED = "FAILURE_SITE_NOT_EXECUTED"
FAILURE_SITE_STILL_RAISES = "FAILURE_SITE_STILL_RAISES"
EXIT_FROM_ADDED_LINE = "EXIT_FROM_ADDED_LINE"
ENTRYPOINT_NOT_EXECUTED = "ENTRYPOINT_NOT_EXECUTED"
WORKLOAD_PARAMETER_CHANGED = "WORKLOAD_PARAMETER_CHANGED"
COMPUTATION_CHANGED = "COMPUTATION_CHANGED"
INPUT_DATA_CHANGED = "INPUT_DATA_CHANGED"
STATIC_REASONS = (COMMAND_CHANGED, ARGV_OR_ENTRYPOINT_REWRITTEN, WORKLOAD_PARAMETER_CHANGED, COMPUTATION_CHANGED, INPUT_DATA_CHANGED)
TRACE_REASONS = (ARGV_CHANGED_AT_RUNTIME, FAILURE_SITE_NOT_EXECUTED, FAILURE_SITE_STILL_RAISES, EXIT_FROM_ADDED_LINE, ENTRYPOINT_NOT_EXECUTED)
REASONS = STATIC_REASONS + TRACE_REASONS


@dataclass(frozen=True)
class Finding:
    reason: str
    detail: str
    file: str = ""
    line: int = 0

    def as_dict(self) -> dict:
        return {"reason": self.reason, "detail": self.detail[:300], "file": self.file, "line": self.line}


# ----------------------------------------------------------------------------------------------------------------------------------- normalisation
# Compatibility idioms. A statement that differs from its old self only by these is the SAME computation.
COMPAT_KWARGS = frozenset({"map_location", "encoding", "errors", "non_blocking", "num_workers", "pin_memory", "persistent_workers", "prefetch_factor", "weights_only", "mmap",
                           "device", "newline", "exist_ok"})
# removed-API renames: old dotted name -> the name it became (the successor does the same thing)
RENAMES = {
    "np.float": "float", "np.int": "int", "np.bool": "bool", "np.object": "object", "np.complex": "complex", "np.str": "str", "np.long": "int", "np.unicode": "str",
    "numpy.float": "float", "numpy.int": "int", "numpy.bool": "bool", "numpy.object": "object", "numpy.complex": "complex",
    "collections.Mapping": "collections.abc.Mapping", "collections.MutableMapping": "collections.abc.MutableMapping", "collections.Iterable": "collections.abc.Iterable",
    "collections.Callable": "collections.abc.Callable", "collections.Sequence": "collections.abc.Sequence", "collections.Set": "collections.abc.Set",
    "tf.compat.v1.flags": "tf.flags", "tf.compat.v1.logging": "tf.logging", "tf.compat.v1.app": "tf.app", "tf.compat.v1.placeholder": "tf.placeholder",
    "tf.compat.v1.get_variable": "tf.get_variable", "tf.compat.v1.Session": "tf.Session", "tf.compat.v1.train": "tf.train", "tf.compat.v1.variable_scope": "tf.variable_scope",
    "tf.compat.v1.global_variables_initializer": "tf.global_variables_initializer", "tf.compat.v1.random_uniform": "tf.random_uniform", "tf.compat.v1.ConfigProto": "tf.ConfigProto",
    "tf.compat.v1.reset_default_graph": "tf.reset_default_graph", "tf.compat.v1.app.flags": "tf.app.flags", "tf.compat.v1.GraphKeys": "tf.GraphKeys",
}
_DEVICE_STR = re.compile(r"^(?:cuda(?::\d+)?|cpu|gpu)$", re.IGNORECASE)


def _src(node: ast.AST) -> str:
    try:
        return ast.unparse(node)
    except Exception:  # noqa: BLE001
        return type(node).__name__


def _is_deviceish(node: ast.AST) -> bool:
    """An expression that only chooses WHERE a tensor lives: 'cuda' / 'cpu', a name containing `device`, `torch.device(...)`, `torch.cuda.is_available()`, and conditionals over them."""
    if isinstance(node, ast.Constant):
        return isinstance(node.value, str) and bool(_DEVICE_STR.match(node.value))
    if isinstance(node, (ast.Name, ast.Attribute)):
        return "device" in _src(node).lower()
    if isinstance(node, ast.Call):
        name = _src(node.func)
        return name.endswith("device") or name.endswith("cuda.is_available") or name.endswith("cuda.device_count") or name.endswith("get_device")
    if isinstance(node, ast.IfExp):
        return _is_deviceish(node.test) and _is_deviceish(node.body) and _is_deviceish(node.orelse)
    if isinstance(node, (ast.Compare, ast.BoolOp, ast.UnaryOp)):
        return all(_is_deviceish(c) for c in ast.iter_child_nodes(node) if not isinstance(c, (ast.cmpop, ast.boolop, ast.unaryop, ast.expr_context)))
    return False


class _Canon(ast.NodeTransformer):
    """Rewrites compatibility idioms to one canonical form."""

    def visit_Call(self, node: ast.Call):
        self.generic_visit(node)
        fn = node.func
        if isinstance(fn, ast.Attribute) and fn.attr in ("cuda", "cpu") and not node.args:
            return fn.value  # `x.cuda()` / `x.cpu()` -> x
        if (isinstance(fn, ast.Attribute) and fn.attr in ("to", "type") and node.args and all(_is_deviceish(a) for a in node.args)
                and all(k.arg in COMPAT_KWARGS for k in node.keywords)):
            return fn.value  # `x.to(device)` -> x
        if _src(fn).endswith("torch.device"):
            return ast.Name(id="DEVICE", ctx=ast.Load())
        node.keywords = [k for k in node.keywords if k.arg not in COMPAT_KWARGS]
        return node

    def visit_Attribute(self, node: ast.Attribute):
        self.generic_visit(node)
        text = _src(node)
        if text in RENAMES:
            return ast.parse(RENAMES[text], mode="eval").body
        return node


def _canonical_clone(node: ast.AST) -> ast.AST:
    """A copy of a statement HEADER (the children bodies are separate items), with the compatibility idioms rewritten."""
    clone = copy.deepcopy(node)
    for attr in ("body", "orelse", "finalbody", "handlers"):
        if hasattr(clone, attr):
            setattr(clone, attr, [])
    if isinstance(clone, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.If, ast.While, ast.For, ast.AsyncFor, ast.With, ast.AsyncWith, ast.Try, ast.ExceptHandler)):
        clone.body = [ast.Pass()]
    clone = _Canon().visit(clone)
    ast.fix_missing_locations(clone)
    return clone


def canon(node: ast.AST) -> str:
    clone = _canonical_clone(node)
    if isinstance(clone, (ast.Import, ast.ImportFrom)):
        return "<import>"  # judged separately: see `_import_findings`
    return _src(clone).splitlines()[0] if isinstance(clone, ast.stmt) else _src(clone)


@dataclass
class Item:
    key: str            # context + canonical text: what the two statement lists are diffed on
    text: str           # the statement as written (header only for a compound statement)
    node: ast.AST
    line: int
    ctx: str            # enclosing function / class path
    parent: ast.AST | None = None


def _walk(body: list[ast.stmt], ctx: str, parent: ast.AST | None, out: list[Item]) -> None:
    for node in body:
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            continue  # a docstring or a bare string
        header = _src(node).splitlines()[0]
        out.append(Item(key=f"{ctx}|{canon(node)}", text=header, node=node, line=getattr(node, "lineno", 0), ctx=ctx, parent=parent))
        child_ctx = f"{ctx}/{node.name}" if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) else ctx
        for field_name in ("body", "orelse", "finalbody"):
            sub = getattr(node, field_name, None)
            if isinstance(sub, list) and sub and isinstance(sub[0], ast.stmt):
                _walk(sub, child_ctx, node, out)
        for handler in getattr(node, "handlers", None) or []:
            out.append(Item(key=f"{child_ctx}|{canon(handler)}", text=f"except {_src(handler.type) if handler.type else ''}:", node=handler, line=handler.lineno,
                            ctx=child_ctx, parent=node))
            _walk(handler.body, child_ctx, handler, out)


def _parse(source: str) -> ast.Module:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # a repository's own invalid escape sequences are not RERUN's to report
        return ast.parse(source)


def items_of(source: str) -> list[Item] | None:
    try:
        tree = _parse(source)
    except (SyntaxError, ValueError):
        return None
    out: list[Item] = []
    _walk(tree.body, "", None, out)
    return out


# ----------------------------------------------------------------------------------------------------------------------------------- allow-lists
HARMLESS_CALLS = re.compile(
    r"^(?:print|pprint(?:\.pprint)?|logging\.\w+|logger\.\w+|log\.\w+|warnings\.(?:warn|simplefilter|filterwarnings)|traceback\.print_\w+|sys\.(?:stdout|stderr)\.(?:flush|write)|"
    r"os\.(?:makedirs|mkdir)|sys\.path\.(?:insert|append)|matplotlib\.use|torch\.set_num_threads|plt\.switch_backend)$")
HARMLESS_ASSIGN_TARGET = re.compile(r"^(?:sys\.path|.*\.benchmark|.*\.enabled|.*device.*|DEVICE)$", re.IGNORECASE)
# environment variables that only tune libraries (a patch may set them; any other key could flip a code path the repository reads)
_ENV_KEY = re.compile(r"^(?:MPLBACKEND|KMP_\w+|OMP_\w+|MKL_\w+|NUMEXPR_\w+|OPENBLAS_\w+|TF_\w+|XLA_\w+|CUDA_\w+|NCCL_\w+|TORCH_\w+|PROTOCOL_BUFFERS_\w+|TOKENIZERS_\w+|PYTHONHASHSEED|WANDB_MODE)$")
_SCALE_NAME = re.compile(r"(?:epoch|iter|step|episode|n_?samples|n_?train|n_?test|n_?tasks|n_?runs|num_|max_|batch|size|limit|length|total|trials|folds|seeds?\b|reps?\b|repeat)", re.IGNORECASE)
_ENTRY_CALLS = re.compile(r"^(?:os\.(?:exec\w*|system|popen|spawn\w*|posix_spawn\w*)|subprocess\.\w+|runpy\.\w+|exec|eval|compile|importlib\.\w+|__import__)$")
# files whose change is not a judgement about the work: dependency / build metadata and documentation
_REQUIREMENTS = re.compile(r"(?:^|/)(?:requirements[\w.-]*\.txt|environment\.ya?ml|setup\.(?:py|cfg)|pyproject\.toml|package\.json|tsconfig\.json|\.gitignore|LICENSE\w*|[\w.-]*\.(?:md|rst))$", re.IGNORECASE)
# call targets that read and format but do not act (arguments of a harmless call, a guard's test, a returned value must be built from these)
_PURE_BUILTINS = frozenset({"str", "repr", "len", "int", "float", "bool", "abs", "min", "max", "round", "isinstance", "format", "tuple", "list", "dict", "set", "sorted"})
_PURE_CALL = re.compile(r"^(?:os\.path\.\w+|os\.getcwd|os\.cpu_count|os\.getenv|os\.environ\.get|platform\.\w+|torch\.cuda\.(?:is_available|device_count)|torch\.device|torch\.get_default_dtype|"
                        r"pathlib\.Path|Path|socket\.gethostname|sys\.getsizeof)$")
_PURE_METHODS = frozenset({"format", "join", "strip", "lstrip", "rstrip", "lower", "upper", "split", "startswith", "endswith", "replace", "encode", "decode", "get", "items", "keys", "values"})
# the import of one name by two modules that are the same thing (a removed location and its successor)
_IMPORT_SUCCESSORS = {frozenset({"sklearn.externals.joblib", "joblib"}), frozenset({"sklearn.cross_validation", "sklearn.model_selection"}),
                      frozenset({"sklearn.grid_search", "sklearn.model_selection"}), frozenset({"sklearn.externals.six", "six"})}


def _call_name(node: ast.AST) -> str:
    return _src(node.func) if isinstance(node, ast.Call) else ""


def _simple(node: ast.AST | None) -> bool:
    """An expression that only reads and formats: constants, names, attributes, subscripts, containers, f-strings, operators, a few pure calls. Nothing in it acts."""
    if node is None:
        return True
    if isinstance(node, (ast.Constant, ast.Name)):
        return True
    if isinstance(node, ast.Attribute):
        return _simple(node.value)
    if isinstance(node, ast.Subscript):
        return _simple(node.value) and _simple(node.slice)
    if isinstance(node, ast.Slice):
        return _simple(node.lower) and _simple(node.upper) and _simple(node.step)
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        return all(_simple(e) for e in node.elts)
    if isinstance(node, ast.Dict):
        return all(_simple(k) for k in node.keys if k is not None) and all(_simple(v) for v in node.values)
    if isinstance(node, ast.JoinedStr):
        return all(_simple(v) for v in node.values)
    if isinstance(node, ast.FormattedValue):
        return _simple(node.value) and _simple(node.format_spec)
    if isinstance(node, (ast.BinOp, ast.UnaryOp, ast.BoolOp, ast.Compare, ast.IfExp)):
        return all(_simple(c) for c in ast.iter_child_nodes(node) if not isinstance(c, (ast.operator, ast.unaryop, ast.boolop, ast.cmpop, ast.expr_context)))
    if isinstance(node, ast.Starred):
        return _simple(node.value)
    if isinstance(node, ast.Call):
        name = _call_name(node)
        pure = name in _PURE_BUILTINS or bool(_PURE_CALL.match(name)) or (isinstance(node.func, ast.Attribute) and node.func.attr in _PURE_METHODS and _simple(node.func.value))
        return pure and all(_simple(a) for a in node.args) and all(_simple(k.value) for k in node.keywords)
    return False


def _args_simple(call: ast.Call) -> bool:
    return all(_simple(a) for a in call.args) and all(_simple(k.value) for k in call.keywords)


def _harmless_call(call: ast.AST) -> bool:
    return isinstance(call, ast.Call) and bool(HARMLESS_CALLS.match(_call_name(call))) and _args_simple(call)


def _env_write(node: ast.AST) -> bool:
    """`os.environ["KEY"] = "value"` / `os.environ.setdefault("KEY", "value")` with a library-tuning key and constant arguments."""
    if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Subscript) and _src(node.targets[0].value) == "os.environ":
        key = node.targets[0].slice
        return isinstance(key, ast.Constant) and isinstance(key.value, str) and bool(_ENV_KEY.match(key.value)) and isinstance(node.value, ast.Constant)
    if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call) and _call_name(node.value) == "os.environ.setdefault" and len(node.value.args) == 2:
        key, val = node.value.args
        return isinstance(key, ast.Constant) and isinstance(key.value, str) and bool(_ENV_KEY.match(key.value)) and isinstance(val, ast.Constant)
    return False


_EXIT_NAMES = {"sys.exit", "exit", "quit", "os._exit", "SystemExit"}


def _raises_exit(n: ast.Raise) -> bool:
    exc = n.exc
    return exc is not None and _src(exc.func if isinstance(exc, ast.Call) else exc) == "SystemExit"


def _nonzero_exit(call: ast.AST | None) -> bool:
    """`sys.exit(2)`, `sys.exit("message")`, `SystemExit(1)`: an exit that can never end the run with code 0."""
    if not isinstance(call, ast.Call) or _call_name(call) not in _EXIT_NAMES or len(call.args) != 1 or call.keywords:
        return False
    arg = call.args[0]
    if not isinstance(arg, ast.Constant):
        return False
    return (isinstance(arg.value, int) and not isinstance(arg.value, bool) and arg.value != 0) or (isinstance(arg.value, str))


def _raise_ok(n: ast.Raise) -> bool:
    if _raises_exit(n):
        return _nonzero_exit(n.exc)
    if n.exc is None:
        return True  # a bare `raise` re-raises
    call_ok = _simple(n.exc.func) and _args_simple(n.exc) if isinstance(n.exc, ast.Call) else _simple(n.exc)
    return call_ok and _simple(n.cause)


def _body_only_raises_or_logs(stmts: list[ast.stmt]) -> bool:
    if not stmts:
        return False
    for s in stmts:
        if isinstance(s, ast.Assert):
            if not (_simple(s.test) and _simple(s.msg)):
                return False
            continue
        if isinstance(s, ast.Raise) and _raise_ok(s):
            continue
        if isinstance(s, ast.Expr) and (_nonzero_exit(s.value) or _harmless_call(s.value)):
            continue
        return False
    return any(isinstance(s, (ast.Raise, ast.Assert)) or (isinstance(s, ast.Expr) and _nonzero_exit(s.value)) for s in stmts)


def _handler_reraises(h: ast.ExceptHandler) -> bool:
    if not any(isinstance(n, ast.Raise) for s in h.body for n in ast.walk(s)):
        return False
    return all((isinstance(s, ast.Raise) and _raise_ok(s)) or (isinstance(s, ast.Expr) and _harmless_call(s.value)) for s in h.body)


def _exc_names(h: ast.ExceptHandler) -> set[str]:
    if h.type is None:
        return {"<bare>"}
    elts = h.type.elts if isinstance(h.type, ast.Tuple) else [h.type]
    return {_src(e).split(".")[-1] for e in elts}


def _handler_ok(h: ast.ExceptHandler) -> bool:
    """A handler that cannot swallow a failure of the work: it re-raises, the import it guards is optional, or it only answers Ctrl-C."""
    names = _exc_names(h)
    if names <= {"ImportError", "ModuleNotFoundError"} or _handler_reraises(h):
        return True
    return names == {"KeyboardInterrupt"} and all(
        (isinstance(s, ast.Expr) and (_harmless_call(s.value) or _nonzero_exit(s.value))) or isinstance(s, ast.Pass) or (isinstance(s, ast.Raise) and _raise_ok(s)) for s in h.body)


def _noop_after_normalisation(node: ast.AST) -> bool:
    """`x = x` once the compatibility idioms are rewritten (what is left of `x = x.cuda()`), or a bare name."""
    clone = _canonical_clone(node)
    if isinstance(clone, ast.Assign) and len(clone.targets) == 1:
        return _src(clone.targets[0]) == _src(clone.value)
    if isinstance(clone, ast.Expr):
        return isinstance(clone.value, (ast.Name, ast.Attribute)) and _simple(clone.value)
    return False


def _harmless_assign(n: ast.AST) -> bool:
    """An assignment to a device / benchmark / path variable of a value that only reads (or chooses a device)."""
    if isinstance(n, ast.Assign):
        targets, value = n.targets, n.value
    elif isinstance(n, ast.AnnAssign):
        targets, value = [n.target], n.value
    else:
        return False
    return all(HARMLESS_ASSIGN_TARGET.match(_src(t)) for t in targets) and value is not None and _simple(value)


def additive_ok(it: Item, fresh: frozenset[str] = frozenset()) -> bool:
    """True when ADDING this statement does no computation: an import, a harmless call, a harmless assignment, a guard that raises, a handler that re-raises. `fresh`: the context
    paths of the functions and classes this patch adds (a name the file did not define before)."""
    n = it.node
    if isinstance(n, ast.Raise):
        return _raise_ok(n)
    if isinstance(n, ast.Assert):
        return _simple(n.test) and _simple(n.msg)
    if isinstance(n, (ast.Import, ast.ImportFrom, ast.Pass, ast.Global, ast.Nonlocal)):
        return True
    if isinstance(n, (ast.Expr, ast.Assign)) and _noop_after_normalisation(n):
        return True
    if _env_write(n):
        return True
    if isinstance(n, ast.Expr):
        v = n.value
        if isinstance(v, ast.Call):
            name = _call_name(v)
            if _harmless_call(v) or (_nonzero_exit(v)):
                return True
            if name.endswith("add_argument") and _args_simple(v):
                default = next((k.value for k in v.keywords if k.arg == "default"), None)
                return default is None or (isinstance(default, ast.Constant) and (default.value is None or isinstance(default.value, str)))
        return False
    if isinstance(n, (ast.Assign, ast.AnnAssign)):
        if _harmless_assign(n):
            return True
        # `x = None` in the handler of an ImportError: an optional import that is absent
        return bool(isinstance(it.parent, ast.ExceptHandler) and "ImportError" in _exc_names(it.parent) and isinstance(n.value, ast.Constant) and n.value.value is None)
    if isinstance(n, ast.If):
        return _simple(n.test) and _body_only_raises_or_logs(n.body) and not n.orelse
    if isinstance(n, ast.Try):
        return not n.finalbody and all(_handler_ok(h) for h in n.handlers)
    if isinstance(n, ast.ExceptHandler):
        return _handler_ok(n)
    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return f"{it.ctx}/{n.name}" in fresh  # a NEW helper (its own statements are judged one by one); a def that redefines a name of the file replaces code
    if isinstance(n, ast.Return) and isinstance(it.parent, (ast.FunctionDef, ast.AsyncFunctionDef)):
        private = it.parent.name.startswith("_") and not (it.parent.name.startswith("__") and it.parent.name.endswith("__"))
        return private and it.ctx in fresh and _simple(n.value)  # a private helper's return, in a helper this patch adds
    if isinstance(n, ast.With):
        return all(_harmless_call(i.context_expr) for i in n.items)
    return False


def removal_ok(it: Item) -> bool:
    """Removing this statement drops no computation: an import, a log line, a pass, a no-op once normalised."""
    n = it.node
    if isinstance(n, (ast.Import, ast.ImportFrom, ast.Pass)):
        return True
    if isinstance(n, (ast.Expr, ast.Assign)) and _noop_after_normalisation(n):
        return True
    if _harmless_assign(n) or _env_write(n):
        return True
    return isinstance(n, ast.Expr) and _harmless_call(n.value)


# imports: a name that an old import bound and a new one binds again must still be the same thing
def _bindings(source: str) -> dict[str, str] | None:
    try:
        tree = _parse(source)
    except (SyntaxError, ValueError):
        return None
    out: dict[str, str] = {}
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            for a in n.names:
                out[a.asname or a.name.split(".")[0]] = a.name
        elif isinstance(n, ast.ImportFrom):
            for a in n.names:
                if a.name != "*":
                    out[a.asname or a.name] = f"{'.' * n.level}{n.module or ''}.{a.name}".strip(".")
    return out


def _same_thing(a: str, b: str) -> bool:
    """Two dotted import targets name the same thing when one is a prefix of the other (`tensorflow` -> `tensorflow.compat.v1`), when they sit in the same package and end in the same
    name (`collections.Mapping` -> `collections.abc.Mapping`), when they are one removed location and its successor (`sklearn.externals.joblib` -> `joblib`), or when they are equal."""
    if a == b or frozenset({a, b}) in _IMPORT_SUCCESSORS:
        return True
    pa, pb = a.split("."), b.split(".")
    return pa[:len(pb)] == pb or pb[:len(pa)] == pa or (pa[0] == pb[0] and pa[-1] == pb[-1])


def _import_findings(path: str, old_source: str, new_source: str) -> list[Finding]:
    old, new = _bindings(old_source), _bindings(new_source)
    if old is None or new is None:
        return []
    out = []
    for name, target in new.items():
        if name in old and not _same_thing(old[name], target):
            out.append(Finding(COMPUTATION_CHANGED, f"the import binding `{name}` now names `{target}`, it named `{old[name]}`", path))
    return out


# ----------------------------------------------------------------------------------------------------------------------------------- (c) workload facts
def workload_facts(source: str) -> list[tuple] | None:
    """What fixes how much work the program does, as (kind, name, value) facts: argparse defaults, `range` bounds of loops, assignments of a number to a scale-named variable or
    attribute, constant slice bounds, subset / sampling calls, `break` inside a loop. A patch that adds, removes or changes ANY such fact changes the workload."""
    try:
        tree = _parse(source)
    except (SyntaxError, ValueError):
        return None
    facts: list[tuple] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = _call_name(node)
            if name.endswith("add_argument"):
                opts = [a.value for a in node.args if isinstance(a, ast.Constant) and isinstance(a.value, str)]
                default = next((k.value for k in node.keywords if k.arg == "default"), None)
                if default is not None and not (isinstance(default, ast.Constant) and (default.value is None or isinstance(default.value, str))):
                    facts.append(("argdefault", "/".join(opts), _src(default)))
            elif name in ("Subset", "torch.utils.data.Subset", "islice", "itertools.islice") or name.endswith((".head", ".sample", ".take")):
                facts.append(("subset", name, _src(node)))
        elif isinstance(node, (ast.For, ast.AsyncFor)):
            if isinstance(node.iter, ast.Call) and _call_name(node.iter) in ("range", "xrange"):
                facts.append(("loopbound", _src(node.target), _src(node.iter)))
            breaks = sum(isinstance(inner, ast.Break) for inner in ast.walk(node))
            if breaks:
                facts.append(("loopbreak", f"for {_src(node.target)} in {_src(node.iter)}", f"{breaks} break(s)"))
        elif isinstance(node, ast.While):
            breaks = sum(isinstance(inner, ast.Break) for inner in ast.walk(node))
            if breaks:
                facts.append(("loopbreak", f"while {_src(node.test)}", f"{breaks} break(s)"))
        elif isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            value = node.value
            if value is not None and isinstance(value, (ast.Constant, ast.UnaryOp, ast.BinOp)) and all(
                    isinstance(v, (ast.Constant, ast.UnaryOp, ast.BinOp, ast.operator, ast.unaryop, ast.expr_context)) for v in ast.walk(value)):
                for t in targets:
                    tname = _src(t)
                    if tname.startswith("os.environ"):
                        continue  # a library-tuning variable is judged by `_env_write`, not as a workload scale
                    if _SCALE_NAME.search(tname.split(".")[-1]) and any(isinstance(c, ast.Constant) for c in ast.walk(value)):
                        facts.append(("scale", tname, _src(value)))
        elif isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Slice):
            bound = node.slice.upper
            if bound is not None and ((isinstance(bound, ast.Constant) and isinstance(bound.value, int) and not isinstance(node.value, ast.Constant))
                                      or _SCALE_NAME.search(_src(bound))):
                facts.append(("slice", _src(node.value), _src(node.slice)))
    return facts


def _multiset_diff(old: list[tuple], new: list[tuple]) -> tuple[list[tuple], list[tuple]]:
    from collections import Counter

    o, n = Counter(old), Counter(new)
    return list((n - o).elements()), list((o - n).elements())


# ----------------------------------------------------------------------------------------------------------------------------------- the static judgement
def static_findings(path: str, old_source: str | None, new_source: str | None) -> list[Finding]:
    """The (a) static, (c) and (d) findings of ONE touched file. `old_source` is None for a file the patch adds."""
    out: list[Finding] = []
    if new_source is None:
        return [Finding(COMPUTATION_CHANGED, "the patch deletes the file", path)]
    if _REQUIREMENTS.search(path):
        return []
    if path.endswith((".sh", ".bash")):
        if (old_source or "") != new_source:
            return [Finding(ARGV_OR_ENTRYPOINT_REWRITTEN, "a shell script the documented command may run is changed: what the command runs is not the documented content", path)]
        return []
    if path.endswith(".ipynb"):
        return [Finding(COMPUTATION_CHANGED, "a notebook is code; its change is not judged cell by cell", path)] if (old_source or "") != new_source else []
    if not path.endswith(".py"):
        if (old_source or "") != new_source:
            return [Finding(INPUT_DATA_CHANGED, "an input, configuration or data file is added or changed by the patch", path)]
        return []
    old_items = items_of(old_source or "")
    new_items = items_of(new_source)
    if new_items is None or old_items is None:
        return [Finding(COMPUTATION_CHANGED, "the file does not parse before or after the patch: its change cannot be judged", path)]
    sm = difflib.SequenceMatcher(None, [i.key for i in old_items], [i.key for i in new_items], autojunk=False)
    inserted: list[Item] = []
    deleted: list[Item] = []
    replaced: list[tuple[list[Item], list[Item]]] = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag in ("insert", "replace"):
            inserted += new_items[j1:j2]
        if tag in ("delete", "replace"):
            deleted += old_items[i1:i2]
        if tag == "replace":
            replaced.append((old_items[i1:i2], new_items[j1:j2]))
    # definitions: a name this file did not define is a new helper; a def or class that re-defines one it did define replaces code (the later definition wins)
    defs = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
    old_defs = {(i.ctx, i.node.name) for i in old_items if isinstance(i.node, defs)}
    fresh = frozenset(f"{i.ctx}/{i.node.name}" for i in inserted if isinstance(i.node, defs) and (i.ctx, i.node.name) not in old_defs)
    # (a) the entrypoint and the arguments
    for it in inserted:
        n = it.node
        targets: list[str] = []
        if isinstance(n, ast.Assign):
            targets = [_src(t) for t in n.targets]
        elif isinstance(n, (ast.AugAssign, ast.AnnAssign)):
            targets = [_src(n.target)]
        elif isinstance(n, ast.Delete):
            targets = [_src(t) for t in n.targets]
        if any(t == "sys.argv" or t.startswith("sys.argv[") for t in targets):
            out.append(Finding(ARGV_OR_ENTRYPOINT_REWRITTEN, f"the patch rewrites sys.argv: `{it.text}`", path, it.line))
        if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call) and (_ENTRY_CALLS.match(_call_name(n.value)) or _call_name(n.value).startswith("sys.argv.")):
            out.append(Finding(ARGV_OR_ENTRYPOINT_REWRITTEN, f"the patch starts another program or code path or edits the arguments: `{it.text}`", path, it.line))
        if isinstance(n, ast.If) and "__name__" in _src(n.test):
            out.append(Finding(ARGV_OR_ENTRYPOINT_REWRITTEN, f"the patch edits the __main__ guard: `{it.text}`", path, it.line))
    for old_part, new_part in replaced:
        if any(isinstance(i.node, ast.If) and "__name__" in _src(i.node.test) for i in old_part + new_part):
            out.append(Finding(ARGV_OR_ENTRYPOINT_REWRITTEN, "the patch changes the __main__ guard", path, new_part[0].line if new_part else 0))
    # (c) the workload
    of, nf = workload_facts(old_source or ""), workload_facts(new_source)
    if of is not None and nf is not None:
        added, removed = _multiset_diff(of, nf)
        for fact in added:
            out.append(Finding(WORKLOAD_PARAMETER_CHANGED, f"adds {fact[0]} `{fact[1]} = {fact[2]}`", path, 0))
        for fact in removed:
            out.append(Finding(WORKLOAD_PARAMETER_CHANGED, f"removes {fact[0]} `{fact[1]} = {fact[2]}`", path, 0))
    # (d) the computation
    for it in inserted:
        if not additive_ok(it, fresh):
            out.append(Finding(COMPUTATION_CHANGED, f"adds `{it.text[:140]}`" + (" (it re-defines a name this file already defines)" if isinstance(it.node, defs) else ""), path, it.line))
    for it in deleted:
        if not removal_ok(it):
            out.append(Finding(COMPUTATION_CHANGED, f"removes or rewrites `{it.text[:140]}`", path, it.line))
    out += _import_findings(path, old_source or "", new_source)
    seen: set[tuple[str, str]] = set()
    unique: list[Finding] = []
    for f in out:
        if (f.reason, f.detail) not in seen:
            seen.add((f.reason, f.detail))
            unique.append(f)
    return unique


def command_finding(before: str | None, after: str | None) -> Finding | None:
    """(a) The command the candidate would execute is the command the run executes now. Whitespace is ignored."""
    norm = lambda s: " ".join((s or "").split())  # noqa: E731
    if before and after and norm(before) != norm(after):
        return Finding(COMMAND_CHANGED, f"the candidate's environment change turns the command `{norm(before)[:160]}` into `{norm(after)[:160]}`")
    return None


def candidate_findings(old_sources: dict[str, str], new_sources: dict[str, str | None], *, command_before: str | None = None, command_after: str | None = None) -> list[Finding]:
    """The static findings of one candidate: every touched file (`new_sources`: post-patch text, None = deleted; `old_sources`: pre-patch text, missing = added) and the command."""
    out: list[Finding] = []
    cmd = command_finding(command_before, command_after)
    if cmd is not None:
        out.append(cmd)
    for path in sorted(new_sources):
        out += static_findings(path, old_sources.get(path), new_sources[path])
    return out


# ----------------------------------------------------------------------------------------------------------------------------------- the tracer (runs in the sandbox)
# Installed like RERUN's other runner hooks (a module in site-packages plus a .pth file that imports it) and active only when the environment variable RERUN_BEHAVIOUR is 1, which the smoke
# launcher sets for a candidate's command and for nothing else: an adopted candidate's image keeps the files but they do nothing in any later run. The spec (files to trace, failure sites, entry)
# is embedded in the source. It traces ONLY the files named in the spec: the global trace function returns None for every other frame. The report is ONE line on stderr, written at exit and
# on SIGTERM (the smoke launcher's way of stopping a run that is still alive): RERUN_BEHAVIOUR <json>. Python 3.6-compatible (sys.argv does not exist yet when .pth files run on 3.6/3.7).
TRACE_MARKER = "RERUN_BEHAVIOUR"
TRACE_ENV = {"RERUN_BEHAVIOUR": "1"}
TRACE_SOURCE = r'''
"""RERUN behavioural tracer (harness-v1.10): injected by RERUN, not part of the repository."""
import os
import sys

if os.environ.get("RERUN_BEHAVIOUR") == "1" and not getattr(sys, "rerun_behaviour_installed", False):
    sys.rerun_behaviour_installed = True

    def _install():
        import base64
        import json
        import threading
        import time

        spec = json.loads(base64.b64decode("__SPEC__").decode("utf-8"))
        cwd0 = os.getcwd()
        files = spec["files"]
        order = sorted(files, key=len, reverse=True)
        entry = spec.get("entry") or ""
        main_body = spec.get("main_body")
        site_keys = {}
        for s in spec.get("sites", []):
            for ln in s["lines"]:
                site_keys[(s["file"], ln)] = "%s:%d" % (s["file"], ln)
        added = dict((f, set(v.get("added", []))) for f, v in files.items())
        rep = {"pid": os.getpid(), "t0": time.time(), "entry_main": False, "sites": {}, "site_raised": {}, "exit": None, "main_lines": 0, "lines": 0, "argv0": None,
               "argv_changed": None, "last": None}
        cache = {}
        state = {"prev_added": False, "emitted": False}

        def classify(co_filename):
            hit = cache.get(co_filename, 0)
            if hit != 0:
                return hit
            try:
                p = os.path.normpath(os.path.join(cwd0, co_filename)).replace("\\", "/")
            except Exception:
                p = str(co_filename)
            found = None
            for rel in order:
                if p == rel or p.endswith("/" + rel):
                    found = rel
                    break
            cache[co_filename] = found
            return found

        def emit():
            if state["emitted"] or os.getpid() != rep["pid"] or not rep["lines"]:
                return
            state["emitted"] = True
            try:
                os.write(2, ("\nRERUN_BEHAVIOUR " + json.dumps(rep) + "\n").encode("utf-8"))
            except Exception:
                pass

        def origin():
            try:
                f = sys._getframe(2)
                return classify(f.f_code.co_filename) or f.f_code.co_filename, f.f_lineno
            except Exception:
                return None

        def local(frame, event, arg):
            rel = classify(frame.f_code.co_filename)
            if event == "line":
                ln = frame.f_lineno
                rep["lines"] += 1
                rep["last"] = [rel, ln]
                if rep["argv0"] is None:
                    rep["argv0"] = list(getattr(sys, "argv", []))
                elif state["prev_added"] and rep["argv_changed"] is None and list(getattr(sys, "argv", [])) != rep["argv0"]:
                    rep["argv_changed"] = list(sys.argv)[:12]
                state["prev_added"] = ln in added.get(rel, ())
                key = site_keys.get((rel, ln))
                if key:
                    rep["sites"][key] = rep["sites"].get(key, 0) + 1
                if main_body and rel == entry and frame.f_globals.get("__name__") == "__main__" and main_body[0] <= ln <= main_body[1]:
                    rep["main_lines"] += 1
            elif event == "exception":
                ln = frame.f_lineno
                key = site_keys.get((rel, ln))
                if key:
                    rep["site_raised"][key] = rep["site_raised"].get(key, 0) + 1
                if arg and arg[0] is SystemExit and rep["exit"] is None:
                    rep["exit"] = {"how": "raise SystemExit", "file": rel, "line": ln, "code": repr(getattr(arg[1], "code", None))}
            return local

        def glob(frame, event, arg):
            rel = classify(frame.f_code.co_filename)
            if rel is None:
                return None
            if rel == entry and frame.f_globals.get("__name__") == "__main__":
                rep["entry_main"] = True
            return local

        real_exit, real_os_exit = sys.exit, os._exit

        def _sys_exit(*args):
            o = origin()
            if o and rep["exit"] is None:
                rep["exit"] = {"how": "sys.exit", "file": o[0], "line": o[1], "code": repr(args[0] if args else None)}
            return real_exit(*args)

        def _os_exit(code=0):
            o = origin()
            if o and rep["exit"] is None:
                rep["exit"] = {"how": "os._exit", "file": o[0], "line": o[1], "code": repr(code)}
            emit()
            return real_os_exit(code)

        sys.exit, os._exit = _sys_exit, _os_exit
        sys.settrace(glob)
        threading.settrace(glob)
        import atexit
        atexit.register(emit)
        try:
            import signal

            def _term(signum, frame):
                emit()
                signal.signal(signal.SIGTERM, signal.SIG_DFL)
                os.kill(os.getpid(), signal.SIGTERM)

            if signal.getsignal(signal.SIGTERM) in (signal.SIG_DFL, None):
                signal.signal(signal.SIGTERM, _term)
        except Exception:
            pass

    try:
        _install()
    except Exception:
        pass
'''


def install_command(spec_b64: str, python: str = "python3") -> str:
    """The setup command that installs the tracer, with `spec_b64` embedded, into the sandbox interpreter's site-packages (the runner hooks' installer, idempotent)."""
    from app.services import runner_hooks

    source = TRACE_SOURCE.replace("__SPEC__", spec_b64)
    code = base64.b64encode(runner_hooks._INSTALLER.encode("utf-8")).decode("ascii")  # noqa: SLF001 - the one installer every hook uses
    payload = base64.b64encode(source.encode("utf-8")).decode("ascii")
    return f"{python} -c \"import base64;exec(base64.b64decode('{code}').decode('utf-8'))\" behaviour {payload}"


def split_report(stderr: str) -> tuple[str, list[dict]]:
    """(stderr without the tracer's lines, the reports found): the tracer's line is RERUN's, not the repository's, and must not reach the classifier or the adjudicator."""
    kept, reports = [], []
    for line in (stderr or "").splitlines(keepends=True):
        if line.startswith(TRACE_MARKER + " "):
            try:
                reports.append(json.loads(line[len(TRACE_MARKER) + 1:]))
            except ValueError:
                pass
            continue
        kept.append(line)
    return "".join(kept), reports


def entry_report(reports: list[dict]) -> dict | None:
    """The report of the entry process: the one that ran the entry file as __main__, else the earliest process that traced any line."""
    if not reports:
        return None
    mains = [r for r in reports if r.get("entry_main")]
    pool = mains or reports
    return sorted(pool, key=lambda r: r.get("t0", 0))[0]


@dataclass(frozen=True)
class TracePlan:
    spec_b64: str
    entry: str
    sites: tuple[dict, ...]
    added_lines: dict
    main_body: list | None

    def as_dict(self) -> dict:
        return {"entry": self.entry, "sites": list(self.sites), "added_lines": {k: list(v) for k, v in self.added_lines.items()}, "main_body": self.main_body}


# ----------------------------------------------------------------------------------------------------------------------------------- helpers for the callers
def entry_of(command: str | None, repo_files: set[str]) -> str:
    """The repo-relative path of the Python file the documented command starts (`python train.py ...`, `python -m pkg.mod ...`), or "" when it starts no repository file."""
    try:
        tokens = shlex.split(command or "")
    except ValueError:
        tokens = (command or "").split()
    for i, tok in enumerate(tokens):
        if tok == "-m" and i + 1 < len(tokens):
            mod = tokens[i + 1].replace(".", "/")
            for cand in (mod + ".py", mod + "/__main__.py"):
                if cand in repo_files:
                    return cand
            continue
        if tok.endswith(".py"):
            norm = tok[2:] if tok.startswith("./") else tok
            if norm in repo_files:
                return norm
    return ""


_FRAME = re.compile(r'^\s*File "(?P<file>[^"]+)", line (?P<line>\d+)')


def failure_site(stderr: str, repo_files: set[str]) -> tuple[str, int] | None:
    """The innermost frame of the LAST traceback in `stderr` that lies in a repository file: (repo-relative file, line), or None."""
    frames = [(m.group("file"), int(m.group("line"))) for m in (_FRAME.match(l) for l in (stderr or "").splitlines()) if m]
    for file, line in reversed(frames):
        norm = file.replace("\\", "/")
        for rel in sorted(repo_files, key=len, reverse=True):
            if norm == rel or norm.endswith("/" + rel):
                return rel, line
    return None


def added_line_numbers(old_source: str, new_source: str) -> list[int]:
    """The 1-based line numbers of `new_source` that are not matched by a line of `old_source`."""
    o, n = old_source.splitlines(), new_source.splitlines()
    out: list[int] = []
    for tag, _i1, _i2, j1, j2 in difflib.SequenceMatcher(None, o, n, autojunk=False).get_opcodes():
        if tag in ("insert", "replace"):
            out += list(range(j1 + 1, j2 + 1))
    return out


def new_lines_of(old_source: str, new_source: str, line: int) -> list[int]:
    """The line(s) of `new_source` that stand for line `line` of `old_source`: itself, moved; the lines that replaced it; or, when the patch deleted it, the first surviving line after it."""
    o, n = old_source.splitlines(), new_source.splitlines()
    ops = difflib.SequenceMatcher(None, o, n, autojunk=False).get_opcodes()
    for k, (tag, i1, i2, j1, j2) in enumerate(ops):
        if i1 < line <= i2:
            if tag == "equal":
                return [j1 + (line - i1)]
            if tag == "replace":
                return list(range(j1 + 1, j2 + 1))
            for tag2, _a, _b, k1, k2 in ops[k + 1:]:  # deleted: the next line that is still there
                if tag2 == "equal" and k2 > k1:
                    return [k1 + 1]
            return []
    return []


def main_body_range(source: str) -> list[int] | None:
    """[first, last] line of the body of the file's `if __name__ == '__main__':` block, or None when it has none."""
    try:
        tree = _parse(source)
    except (SyntaxError, ValueError):
        return None
    for n in tree.body:
        if isinstance(n, ast.If) and "__name__" in _src(n.test) and n.body:
            return [n.body[0].lineno, max(getattr(s, "end_lineno", s.lineno) for s in n.body)]
    return None


def plan_trace(*, command: str | None, failure_text: str, old_sources: dict[str, str], new_sources: dict[str, str | None], repo_files: set[str],
               entry_source: str | None = None) -> TracePlan:
    """What the tracer is told for one candidate: the entry, the failure site (mapped into the patched file), the lines the patch added and the entry's __main__ body."""
    entry = entry_of(command, repo_files)
    added = {p: added_line_numbers(old_sources.get(p, ""), src) for p, src in new_sources.items() if src is not None and p.endswith(".py")}
    sites: list[dict] = []
    found = failure_site(failure_text, repo_files)
    if found:
        rel, line = found
        if rel in new_sources and new_sources[rel] is not None:
            lines = new_lines_of(old_sources.get(rel, ""), new_sources[rel], line)
        else:
            lines = [line]
        if lines:
            sites.append({"file": rel, "lines": lines})
    entry_text = new_sources.get(entry) if entry in new_sources else None
    if entry and entry_text is None:
        entry_text = entry_source
    main_body = main_body_range(entry_text) if entry_text else None
    traced = {p: {"added": added.get(p, [])} for p in new_sources if new_sources[p] is not None and p.endswith(".py")}
    for s in sites:
        traced.setdefault(s["file"], {"added": added.get(s["file"], [])})
    if entry:
        traced.setdefault(entry, {"added": added.get(entry, [])})
    spec = {"entry": entry, "files": traced, "sites": sites, "main_body": main_body}
    return TracePlan(base64.b64encode(json.dumps(spec, sort_keys=True).encode("utf-8")).decode("ascii"), entry, tuple(sites), added, main_body)


def trace_findings(report: dict | None, plan: TracePlan) -> list[Finding]:
    """(b) and the runtime half of (a) from the tracer's report. A missing report yields no finding (the run is `trace missing`: the caller records it)."""
    if report is None:
        return []
    out: list[Finding] = []
    for s in plan.sites:
        keys = [f"{s['file']}:{ln}" for ln in s["lines"]]
        hit = sum(report.get("sites", {}).get(k, 0) for k in keys)
        raised = sum(report.get("site_raised", {}).get(k, 0) for k in keys)
        where = f"{s['file']}:{s['lines'][0]}" + (f"-{s['lines'][-1]}" if len(s["lines"]) > 1 else "")
        if not hit:
            out.append(Finding(FAILURE_SITE_NOT_EXECUTED, f"the original failure site {where} never ran in the patched run", s["file"], s["lines"][0]))
        elif raised:
            out.append(Finding(FAILURE_SITE_STILL_RAISES, f"the original failure site {where} still raises in the patched run (the patch hides it)", s["file"], s["lines"][0]))
    ex = report.get("exit")
    if ex and ex.get("line") in set(plan.added_lines.get(ex.get("file"), ())):
        out.append(Finding(EXIT_FROM_ADDED_LINE, f"the program's exit ({ex.get('how')}, code {ex.get('code')}) comes from a line the patch added: {ex.get('file')}:{ex.get('line')}",
                           ex.get("file") or "", ex.get("line") or 0))
    if plan.main_body is not None and plan.entry and not report.get("main_lines", 0):
        out.append(Finding(ENTRYPOINT_NOT_EXECUTED, f"no line of the entry file's __main__ body ran ({plan.entry}:{plan.main_body[0]}-{plan.main_body[1]})", plan.entry, plan.main_body[0]))
    if report.get("argv_changed"):
        out.append(Finding(ARGV_CHANGED_AT_RUNTIME, f"sys.argv changed under a line the patch added: now {report['argv_changed']}"))
    return out


def violations_of(findings: list[Finding]):
    """The findings as tamper-gate violations (rule = the reason name), for the attempt record."""
    from app.services.tamper_gate import Violation

    return tuple(Violation(rule=f.reason, reason=f.detail, file=f.file) for f in findings)
