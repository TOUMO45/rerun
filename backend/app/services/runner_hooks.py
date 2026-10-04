"""Harness-injected runtime hooks (harness-v1.4.0-rc): deterministic steps RERUN takes at repair time, before any model call.

Each hook is a small Python module RERUN writes into the sandbox's site-packages together with a `.pth` file that imports it at
interpreter start-up, so the documented command runs unchanged (same program, same arguments) and the hook applies to every Python
process of the run. Installing a hook is one RERUN-owned setup command (phase `runner_setup`), appended after the build plan's own
setup commands, so it lands on top of the checkpoint image and never forces a reinstall (sandbox.setup_commands).

  - `cpu_shim` (fires on GPU_REQUIRED, corpus-v2 entry 11): `torch.load` always maps storages to the CPU and
    `torch.cuda.is_available()` returns False. Patched lazily, right after `torch` is first imported; nothing else in torch changes.
  - `exit_hook` (fires on a non-zero exit with no traceback, D-25, corpus-v2 entry 3): the call stack at `sys.exit(...)`, `os._exit(...)`,
    `exit()` / `quit()` and every library that calls `sys.exit` (argparse, click) is printed to stderr when the exit code is non-zero,
    ending in a `SystemExit: <code>` line. Limit, stated in every record that uses it: a bare `raise SystemExit(n)` in the repository's
    own code is not captured (Python offers no hook for it short of tracing every frame).
  - `exit wrapper` (harness-v1.4.1-rc, D-35; not an installed hook but a launcher for the entry script; fires when the exit hook was
    installed and printed nothing): the entry script runs through `runpy.run_path` (or `run_module` for `python -m`) inside a
    `try/except SystemExit` that prints the traceback of the raise to stderr and re-raises, so the process exits with the same code.
    This captures the bare `raise SystemExit(n)` the hook cannot see. If the wrapper also prints nothing, the process did not leave
    through a Python `SystemExit` at all, and the record says "exit outside Python".

The module sources are Python 3.6-compatible (the oldest sandbox image is python:3.6-slim) and are sent base64-encoded, like the smoke
launcher, so no shell quoting can change them.
"""

from __future__ import annotations

import base64
import re
import shlex
from dataclasses import dataclass

CPU_SHIM = "cpu_shim"
EXIT_HOOK = "exit_hook"

CPU_SHIM_MARKER = "RERUN_CPU_SHIM"
EXIT_HOOK_MARKER = "RERUN_EXIT_HOOK"
INSTALLED_MARKER = "RERUN_HOOK_INSTALLED"

_CPU_SHIM_SOURCE = r'''
"""RERUN CPU shim (harness-v1.4.2-rc): injected by RERUN, not part of the repository."""
import sys

_TARGET = "torch"
_FIRED = set()


def _fired(path):
    """Say once per process which shim path acted: `RERUN_CPU_SHIM_PATH: <path>` on stderr (the harness records it)."""
    if path in _FIRED:
        return
    _FIRED.add(path)
    try:
        sys.stderr.write("RERUN_CPU_SHIM_PATH: %s\n" % path)
        sys.stderr.flush()
    except Exception:
        pass


def _is_cuda_name(value):
    return isinstance(value, str) and (value == "cuda" or value.startswith("cuda:"))


def _patch(torch):
    applied = []

    def step(name, fn):
        """Every patch stands alone: one that cannot be applied (an attribute this torch version lacks) never disables the others."""
        try:
            fn()
            applied.append(name)
        except Exception as exc:  # the shim must never break the import it patches
            try:
                sys.stderr.write("RERUN_CPU_SHIM: %s not applied (%r)\n" % (name, exc))
            except Exception:
                pass

    orig_device = getattr(torch, "device", None)

    def to_cpu(value):
        """('cuda' / 'cuda:N' / a cuda torch.device) -> the CPU equivalent; anything else unchanged. Returns (value, changed)."""
        if _is_cuda_name(value):
            return "cpu", True
        if orig_device is not None and isinstance(value, orig_device) and getattr(value, "type", None) == "cuda":
            return orig_device("cpu"), True
        return value, False

    # 1. torch.cuda.is_available() is False.
    def is_available_patch():
        def is_available():
            _fired("cuda.is_available")
            return False

        torch.cuda.is_available = is_available

    # 2. torch.load maps every storage to the CPU.
    def load_patch():
        orig_load = torch.load

        def load(f, *args, **kwargs):
            _fired("torch.load")
            if args:
                args = ("cpu",) + tuple(args[1:])
            else:
                kwargs["map_location"] = "cpu"
            return orig_load(f, *args, **kwargs)

        load.__wrapped__ = orig_load
        torch.load = load

    # 3. Tensor.cuda() and Module.cuda() return self.
    def tensor_cuda_patch():
        def tensor_cuda(self, *args, **kwargs):
            _fired("tensor.cuda")
            return self

        torch.Tensor.cuda = tensor_cuda

    def module_cuda_patch():
        def module_cuda(self, *args, **kwargs):
            _fired("module.cuda")
            return self

        torch.nn.Module.cuda = module_cuda

    # 4. .to("cuda...") / .to(device=...) / .to(torch.device("cuda...")) on Tensor and Module go to the CPU.
    def wrap_to(owner, name):
        orig = owner.to

        def to(self, *args, **kwargs):
            changed = False
            new_args = []
            for a in args:
                a, c = to_cpu(a)
                new_args.append(a)
                changed = changed or c
            if "device" in kwargs:
                kwargs = dict(kwargs)
                kwargs["device"], c = to_cpu(kwargs["device"])
                changed = changed or c
            if changed:
                _fired(name)
            return orig(self, *new_args, **kwargs)

        to.__wrapped__ = orig
        owner.to = to

    # 5. torch.device("cuda...") is the CPU device. A proxy class keeps isinstance(x, torch.device) true for real devices.
    def device_patch():
        if orig_device is None:
            raise AttributeError("this torch has no torch.device")

        class _DeviceMeta(type):
            def __instancecheck__(cls, obj):
                return isinstance(obj, orig_device)

            def __subclasscheck__(cls, sub):
                return issubclass(sub, orig_device)

            def __getattr__(cls, name):
                # class-level reads (`torch.device.type`) see the real class, as on plain torch (found by the independent review)
                return getattr(orig_device, name)

        def device_new(cls, *args, **kwargs):
            new_args = []
            changed = False
            for a in args:
                a, c = to_cpu(a)
                new_args.append(a)
                changed = changed or c
            if "type" in kwargs:
                kwargs = dict(kwargs)
                kwargs["type"], c = to_cpu(kwargs["type"])
                changed = changed or c
            if changed:
                _fired("torch.device")
                # one CPU device, whatever index was asked for: a tensor on the CPU reports `cpu`, so `cpu:0` would not compare equal to it
                return orig_device("cpu")
            return orig_device(*new_args, **kwargs)

        # __module__/__qualname__ make the proxy importable as torch.device: a real device pickles as (torch.device, args), and
        # pickle looks that class up by name (found on REAL torch: without these, pickle.dumps(torch.device("cpu")) raised).
        torch.device = _DeviceMeta(
            "device", (object,),
            {"__new__": device_new, "__doc__": orig_device.__doc__, "__module__": "torch", "__qualname__": "device"},
        )

    # 6. torch.cuda.set_device(...) does nothing (harness-v1.5.1, F3; corpus-v2 entry 14: the CPU wheel has no torch._C._cuda_setDevice, so the call raised
    #    AttributeError before the first tensor was made).
    def set_device_patch():
        def set_device(device):
            _fired("cuda.set_device")

        torch.cuda.set_device = set_device

    # 7. CPU reference kernels (harness-v1.7, R2; DEV entry 14: `torch.lu(x, pivot=False)` raised `linalg.lu_factor: LU without pivoting is not
    #    implemented on the CPU`). Each entry point calls the ORIGINAL first; only when it raises "not implemented on the CPU" for pivot=False does
    #    the pure-torch reference below answer instead. LU without pivoting is unique (unit-diagonal L) whenever it exists, so the reference computes
    #    the factorisation the CUDA kernel computes, up to floating-point rounding; it is NOT the pivoting LU (D-44).
    def lu_reference_patch():
        linalg = getattr(torch, "linalg", None)  # torch < 1.8 has no torch.linalg: torch.lu (via torch._lu_with_info) is still covered

        def no_cpu_kernel(exc):
            return "not implemented on the CPU" in str(exc)

        def factor(A):
            """(LU packed, pivots 1..k int32, info int32) of A without pivoting, batched over the leading dimensions (Doolittle elimination)."""
            m, n = A.shape[-2], A.shape[-1]
            k = min(m, n)
            batch = tuple(A.shape[:-2])
            info = torch.zeros(batch, dtype=torch.int32, device=A.device)
            S, rows, cols = A, [], []
            for j in range(k):
                piv = S[..., 0, 0]
                info = torch.where((piv == 0) & (info == 0), torch.full_like(info, j + 1), info)  # LAPACK's info: the first zero pivot, 1-based
                u = S[..., 0, :]
                l = S[..., 1:, 0] / piv.unsqueeze(-1)
                rows.append(u)
                cols.append(l)
                S = S[..., 1:, 1:] - l.unsqueeze(-1) * u[..., 1:].unsqueeze(-2)
            LU = A.new_zeros(A.shape)
            for j in range(k):
                LU[..., j, j:] = rows[j]
                LU[..., j + 1:, j] = cols[j]
            pivots = torch.arange(1, k + 1, dtype=torch.int32, device=A.device).expand(batch + (k,)).contiguous()
            return LU, pivots, info

        def check(name, info):
            if bool((info > 0).any()):
                first = int(info[info > 0].reshape(-1)[0]) - 1
                raise RuntimeError("%s: U[%d,%d] is zero and using it on lu_solve would result in a division by zero (RERUN CPU reference, no pivoting)"
                                   % (name, first, first))

        def pivot_of(args, kwargs, position):
            return args[position] if len(args) > position else kwargs.get("pivot", True)

        def wrap(owner, attr, path, answer):
            orig = getattr(owner, attr)

            def wrapped(A, *args, **kwargs):
                try:
                    return orig(A, *args, **kwargs)
                except RuntimeError as exc:
                    if not no_cpu_kernel(exc) or kwargs.get("out") is not None:
                        raise
                    result = answer(A, args, kwargs)
                    if result is None:
                        raise
                    _fired(path)
                    return result

            wrapped.__wrapped__ = orig
            wrapped.__doc__ = getattr(orig, "__doc__", None)
            setattr(owner, attr, wrapped)

        def lu_factor(A, args, kwargs):
            if pivot_of(args, kwargs, 99) is not False:
                return None
            LU, pivots, info = factor(A)
            check("linalg.lu_factor", info)
            return LU, pivots

        def lu_factor_ex(A, args, kwargs):
            if pivot_of(args, kwargs, 99) is not False:
                return None
            LU, pivots, info = factor(A)
            if kwargs.get("check_errors", False):
                check("linalg.lu_factor_ex", info)
            return LU, pivots, info

        def lu_with_info(A, args, kwargs):  # torch._lu_with_info(A, pivot=True, check_errors=True): what torch.lu calls
            if pivot_of(args, kwargs, 0) is not False:
                return None
            LU, pivots, info = factor(A)
            if (args[1] if len(args) > 1 else kwargs.get("check_errors", True)):
                check("torch.lu", info)
            return LU, pivots, info

        def lu_plu(A, args, kwargs):  # torch.linalg.lu(A, pivot=False) -> (P empty, L m x k unit lower, U k x n upper)
            if pivot_of(args, kwargs, 99) is not False:
                return None
            LU, _pivots, info = factor(A)
            check("linalg.lu", info)
            m, n = A.shape[-2], A.shape[-1]
            k = min(m, n)
            L = torch.tril(LU[..., :, :k], -1) + torch.eye(m, k, dtype=A.dtype, device=A.device)
            U = torch.triu(LU[..., :k, :])
            return A.new_empty(0), L, U

        for owner, attr, path, answer in ((torch, "_lu_with_info", "cpu_ref:torch.lu", lu_with_info),
                                          (linalg, "lu_factor", "cpu_ref:linalg.lu_factor", lu_factor),
                                          (linalg, "lu_factor_ex", "cpu_ref:linalg.lu_factor_ex", lu_factor_ex),
                                          (linalg, "lu", "cpu_ref:linalg.lu", lu_plu)):
            if owner is not None and hasattr(owner, attr):
                wrap(owner, attr, path, answer)

    step("torch.cuda.is_available() -> False", is_available_patch)
    step("torch.cuda.set_device(...) does nothing", set_device_patch)
    step("LU without pivoting: CPU reference when torch has no CPU kernel", lu_reference_patch)
    step("torch.load(map_location='cpu')", load_patch)
    step("Tensor.cuda() returns the tensor", tensor_cuda_patch)
    step("Module.cuda() returns the module", module_cuda_patch)
    step("Tensor.to('cuda*') -> cpu", lambda: wrap_to(torch.Tensor, "tensor.to"))
    step("Module.to('cuda*') -> cpu", lambda: wrap_to(torch.nn.Module, "module.to"))
    step("torch.device('cuda*') -> cpu", device_patch)
    try:
        sys.stderr.write("RERUN_CPU_SHIM: injected by RERUN: %s\n" % ", ".join(applied))
    except Exception:
        pass


class _Loader(object):
    """Wraps the real loader of ONE spec: runs it, then patches the module. The real loader object is never modified."""

    def __init__(self, inner, finder):
        self._inner, self._finder = inner, finder

    def create_module(self, spec):
        create = getattr(self._inner, "create_module", None)
        return create(spec) if create is not None else None

    def exec_module(self, module):
        self._inner.exec_module(module)
        _patch(module)
        self._finder.done = True
        try:
            sys.meta_path.remove(self._finder)
        except ValueError:
            pass

    def __getattr__(self, name):
        return getattr(self._inner, name)


class _Finder(object):
    """Stays in sys.meta_path until torch has actually been executed and patched: a library that only LOOKS for torch first
    (importlib.util.find_spec("torch"), as transformers / accelerate / lightning do) must not use the shim up."""

    done = False

    def find_spec(self, name, path=None, target=None):
        if name != _TARGET or self.done:
            return None
        others = [f for f in sys.meta_path if f is not self]
        spec = None
        for finder in others:
            find = getattr(finder, "find_spec", None)
            if find is None:
                continue
            spec = find(name, path, target) if target is not None else find(name, path)
            if spec is not None:
                break
        loader = getattr(spec, "loader", None)
        if spec is None or loader is None or not hasattr(loader, "exec_module"):
            return spec
        spec.loader = _Loader(loader, self)
        return spec

    def find_module(self, name, path=None):  # Python < 3.4 protocol; never used here
        return None


if _TARGET in sys.modules:
    _patch(sys.modules[_TARGET])
else:
    sys.meta_path.insert(0, _Finder())
'''

_EXIT_HOOK_SOURCE = r'''
"""RERUN exit-site hook (harness-v1.4.0-rc, D-25): injected by RERUN, not part of the repository."""
import os
import sys
import traceback


def _code_of(arg):
    if arg is None:
        return 0
    if isinstance(arg, bool):
        return int(arg)
    if isinstance(arg, int):
        return arg
    return 1  # a message: Python prints it and exits with 1


def _report(how, code, stack):
    if code == 0 or getattr(sys, "rerun_exit_hook_silent", False):
        return
    try:
        sys.stderr.write("RERUN_EXIT_HOOK: %s was called; the exit site (most recent call last):\n" % how)
        sys.stderr.write("".join(stack))
        sys.stderr.write("SystemExit: %s\n" % (code,))
        sys.stderr.flush()
    except Exception:
        pass


_real_sys_exit = sys.exit


def _sys_exit(*args):
    arg = args[0] if args else None
    _report("sys.exit(%r)" % (arg,), _code_of(arg), traceback.format_stack()[:-1])
    return _real_sys_exit(*args)


sys.exit = _sys_exit

_real_os_exit = os._exit


def _os_exit(code):
    _report("os._exit(%r)" % (code,), _code_of(code), traceback.format_stack()[:-1])
    return _real_os_exit(code)


os._exit = _os_exit

def _wrap_quitters():
    try:
        import builtins
        for name in ("exit", "quit"):
            quitter = getattr(builtins, name, None)
            if quitter is None or getattr(quitter, "_rerun_wrapped", False):
                continue

            def _make(real, label):
                def _call(code=None):
                    _report("%s(%r)" % (label, code), _code_of(code), traceback.format_stack()[:-1])
                    return real(code)
                _call._rerun_wrapped = True
                return _call
            setattr(builtins, name, _make(quitter, name))
    except Exception:
        pass


# site.main() processes the .pth files BEFORE it defines exit() / quit() (site.setquit): wrap them right after setquit runs.
# main() looks setquit up by its global name in the site module, so replacing the attribute is enough.
try:
    import site as _site
    _real_setquit = getattr(_site, "setquit", None)
    if _real_setquit is not None and not getattr(_real_setquit, "_rerun_wrapped", False):
        def _setquit():
            _real_setquit()
            _wrap_quitters()
        _setquit._rerun_wrapped = True
        _site.setquit = _setquit
except Exception:
    pass
_wrap_quitters()  # if they already exist (the hook imported after start-up)
'''

_INSTALLER = r'''
import base64, os, site, sys
name, source = sys.argv[1], base64.b64decode(sys.argv[2]).decode("utf-8")
candidates = []
try:
    candidates = list(site.getsitepackages())
except Exception:
    pass
import sysconfig
candidates.append(sysconfig.get_paths()["purelib"])
target = next(p for p in candidates if os.path.isdir(p))
with open(os.path.join(target, "rerun_%s.py" % name), "w") as f:
    f.write(source)
with open(os.path.join(target, "rerun_%s.pth" % name), "w") as f:
    f.write("import rerun_%s\n" % name)
print("RERUN_HOOK_INSTALLED %s %s" % (name, target))
'''

_SOURCES = {CPU_SHIM: _CPU_SHIM_SOURCE, EXIT_HOOK: _EXIT_HOOK_SOURCE}


@dataclass(frozen=True)
class Hook:
    name: str
    rule: str  # the time_machine_action rule recorded when RERUN installs it
    fires_on: str
    limit: str = ""


HOOKS = {
    CPU_SHIM: Hook(
        CPU_SHIM, "cpu_shim", "GPU_REQUIRED at repair time",
        "covers torch.load (map_location), torch.cuda.is_available(), torch.cuda.set_device() (does nothing: harness-v1.5.1), Tensor.cuda() and Module.cuda() "
        "(return self), a CPU reference for LU without pivoting when torch has no CPU kernel for it (torch.lu / torch._lu_with_info / "
        "torch.linalg.lu_factor / lu_factor_ex / lu with pivot=False; harness-v1.7, R2), .to('cuda*') on Tensor and "
        "Module and torch.device('cuda*') (-> cpu); does NOT cover device='cuda' strings given to factory functions (torch.zeros(device='cuda')), "
        "the other torch.cuda.* functions (current_device, synchronize, ...), "
        "torch.cuda.*Tensor types or torch.set_default_tensor_type('torch.cuda.FloatTensor'); torch.device is a proxy class, so "
        "`type(d) is torch.device` is False for a real device and a `torch.device(...)` call inside a TorchScript function is not supported",
    ),
    EXIT_HOOK: Hook(
        EXIT_HOOK, "exit_site_hook", "a non-zero exit with no traceback (silent exit, D-25)",
        "a bare `raise SystemExit(n)` in the repository's own code is not captured; sys.exit, os._exit, exit(), quit() and "
        "libraries that call sys.exit are",
    ),
}


# harness-v1.7 (R2): the CPU reference kernels the CPU shim carries, keyed by name. `matches` is what the error torch raises says; the reference answers
# only when the original raises "not implemented on the CPU" for the case named in `case`. One row so far (DEV entry 14); a kernel is added only with a
# recorded failure and a test against real torch.
CPU_REFERENCE_KERNELS = {
    "lu_nopivot": {
        "label": "LU without pivoting",
        "case": "pivot=False",
        "entry_points": ("torch.lu", "torch._lu_with_info", "torch.linalg.lu_factor", "torch.linalg.lu_factor_ex", "torch.linalg.lu"),
        "paths": ("cpu_ref:torch.lu", "cpu_ref:linalg.lu_factor", "cpu_ref:linalg.lu_factor_ex", "cpu_ref:linalg.lu"),
        "matches": re.compile(r"\blu(?:_factor(?:_ex)?)?\b.*\bLU without pivoting is not implemented on the CPU|lu without pivoting is not implemented on the CPU",
                              re.IGNORECASE),
        "semantics": "LU without pivoting is unique (unit-diagonal L) whenever it exists: the reference computes the factorisation the CUDA kernel computes, "
                     "up to floating-point rounding (Doolittle elimination in the input's dtype)",
    },
}


def reference_kernel_for(evidence: str) -> str | None:
    """The CPU reference kernel (CPU_REFERENCE_KERNELS key) that answers the 'not implemented on the CPU' error in `evidence`, or None."""
    for name, row in CPU_REFERENCE_KERNELS.items():
        if row["matches"].search(evidence or ""):
            return name
    return None


_SHIM_PATH_RE = re.compile(r"^RERUN_CPU_SHIM_PATH: (\S+)", re.MULTILINE)


def shim_paths_fired(*texts: str) -> list[str]:
    """The CPU shim paths that acted, in order of first appearance, from a run's output (`RERUN_CPU_SHIM_PATH: <path>`, one line per path per
    process): cuda.is_available, cuda.set_device (harness-v1.5.1), torch.load, tensor.cuda, module.cuda, tensor.to, module.to, torch.device (harness-v1.4.2-rc, D-39)."""
    seen: list[str] = []
    for text in texts:
        for path in _SHIM_PATH_RE.findall(text or ""):
            if path not in seen:
                seen.append(path)
    return seen


def source_of(name: str) -> str:
    return _SOURCES[name]


def install_command(name: str, python: str = "python3") -> str:
    """The setup command that installs hook `name` into the sandbox interpreter's site-packages (idempotent)."""
    if name not in _SOURCES:
        raise ValueError(f"unknown runner hook {name!r}")
    code = base64.b64encode(_INSTALLER.encode("utf-8")).decode("ascii")
    payload = base64.b64encode(_SOURCES[name].encode("utf-8")).decode("ascii")
    return f"{python} -c \"import base64;exec(base64.b64decode('{code}').decode('utf-8'))\" {name} {payload}"


def hook_of_command(command: str) -> str | None:
    """The hook name a setup command installs, or None if it is not a runner-hook install."""
    for name in _SOURCES:
        if command == install_command(name):
            return name
    return None


# --- the exit wrapper (harness-v1.4.1-rc, D-35) -----------------------------------------------------------------------------------

EXIT_WRAPPER = "exit_wrapper"
EXIT_WRAPPER_RULE = "exit_wrapper"
EXIT_WRAPPER_MARKER = "RERUN_EXIT_WRAPPER"
EXIT_WRAPPER_FIRES_ON = "a non-zero exit with no traceback after the exit-site hook was installed and printed nothing (D-35)"
EXIT_WRAPPER_LIMIT = (
    "only a Python SystemExit reaches the wrapper; a signal, a C library's exit() or a shell `exit` does not. On Python 3.9+ the script "
    "sees sys.argv[0] as an absolute path (runpy.run_path sets it from the path it was given; `__file__` is absolute there, as with "
    "`python script.py`)"
)
OUTSIDE_PYTHON = "exit outside Python"

_EXIT_WRAPPER_SOURCE = r'''
import os, runpy, sys, traceback
mode, target = sys.argv[1], sys.argv[2]
sys.argv = [target] + sys.argv[3:]
sys.path[:] = [p for p in sys.path if p != ""]  # `python -c` puts the working directory first; `python script.py` puts the script's own
if mode == "script":
    sys.path.insert(0, os.path.dirname(os.path.abspath(target)))
else:
    sys.path.insert(0, os.getcwd())
try:
    if mode == "script":
        # Python 3.9+ gives the main script an absolute __file__ (`python script.py`); older interpreters keep it as typed. A relative
        # __file__ would break `os.chdir(os.path.dirname(__file__))` (dirname is ""), which research scripts do.
        runpy.run_path(os.path.abspath(target) if sys.version_info >= (3, 9) else target, run_name="__main__")
    else:
        runpy.run_module(target, run_name="__main__", alter_sys=True)
except SystemExit as exc:
    code = exc.code
    if code not in (None, 0) and not getattr(sys, "rerun_exit_hook_silent", False):
        sys.stderr.write("RERUN_EXIT_WRAPPER: the entry %s raised SystemExit(%r); the traceback of the raise (most recent call last):\n" % (mode, code))
        traceback.print_exc()
        sys.stderr.flush()
    raise
'''

_SAFE_PYTHON_FLAGS = frozenset({"-u", "-B", "-O", "-OO", "-s", "-S", "-E", "-I", "-q"})
_SHELL_OPERATORS = frozenset({"&&", "||", ";", "|", "&", ">", ">>", "<", "<<", "2>&1", "&>", "(", ")"})
_PYTHON_EXE = re.compile(r"^(.*/)?python(3(\.\d+)?)?$")
_ASSIGNMENT = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$", re.DOTALL)


def exit_wrapper_source() -> str:
    return _EXIT_WRAPPER_SOURCE


def wrap_entry_command(command: str, python: str | None = None) -> tuple[str | None, str]:
    """The documented command with its entry script run through the exit wrapper, or (None, why) when the command is not a plain
    `[VAR=value ...] python [-u ...] script.py [args]` / `python -m module [args]` (any shell operator, a `-c` program or another
    interpreter is left alone: nothing is wrapped and the record says so). Same interpreter, same arguments, same working directory;
    `python` replaces the interpreter (tests run the wrapper with sys.executable). Arguments are re-quoted exactly as the shell
    would have split them (a trailing `# comment` is dropped, as the shell drops it)."""
    try:
        tokens = shlex.split(command, comments=True)
    except ValueError as exc:
        return None, f"the command cannot be parsed ({exc})"
    if not tokens:
        return None, "the command is empty"
    if any(t in _SHELL_OPERATORS or "$(" in t or "`" in t for t in tokens):
        return None, "the command uses shell operators"
    i, env = 0, []
    while i < len(tokens) and _ASSIGNMENT.match(tokens[i]):
        name, value = _ASSIGNMENT.match(tokens[i]).groups()
        env.append(f"{name}={shlex.quote(value)}")
        i += 1
    if i >= len(tokens) or not _PYTHON_EXE.match(tokens[i]):
        return None, "the command does not start with python"
    exe, i, flags = python or tokens[i], i + 1, []
    while i < len(tokens) and tokens[i].startswith("-") and tokens[i] not in ("-m", "-c"):
        if tokens[i] not in _SAFE_PYTHON_FLAGS:
            return None, f"the python option {tokens[i]} is not supported"
        flags.append(tokens[i])
        i += 1
    if i >= len(tokens):
        return None, "the command names no script"
    if tokens[i] == "-c":
        return None, "the command is a python -c program"
    if tokens[i] == "-m":
        if i + 1 >= len(tokens):
            return None, "python -m without a module"
        mode, target, args = "module", tokens[i + 1], tokens[i + 2:]
    elif tokens[i].endswith(".py"):
        mode, target, args = "script", tokens[i], tokens[i + 1:]
    else:
        return None, "the command does not run a .py script or a module"
    code = base64.b64encode(_EXIT_WRAPPER_SOURCE.encode("utf-8")).decode("ascii")
    launcher = f"{exe} " + "".join(f"{flag} " for flag in flags) + f"-c \"import base64;exec(base64.b64decode('{code}').decode('utf-8'))\""
    return " ".join([*env, launcher, mode, shlex.quote(target), *(shlex.quote(a) for a in args)]).strip(), "wrapped"


# --- data preparation (harness-v1.7, R3) ------------------------------------------------------------------------------------------
# The step data_prep.decide() found (a documented script or a documented archive) runs inside the sandbox as one RERUN-owned setup command, after the
# environment is built and before the documented command, so what it writes is in the environment image the re-execution starts from. Caps: the
# step's wall clock (180 s) and the bytes it adds to the tree (500 MB; over the cap every file the step created or changed is deleted and the record
# says so). It always exits 0 (a failed preparation is recorded, and the documented command then shows what is still missing). One line on stdout:
# `RERUN_DATA_PREP {json}` (kind, exit code, bytes written, sha256 of the script or the archive, seconds, url, any error).

DATA_PREP_RULE = "data_prep"
DATA_PREP_MARKER = "RERUN_DATA_PREP"
DATA_PREP_MAX_SECONDS = 180
DATA_PREP_MAX_BYTES = 500 * 1000 * 1000

_DATA_PREP_SOURCE = r'''
import base64, hashlib, json, os, subprocess, sys, tarfile, time, zipfile
spec = json.loads(base64.b64decode(sys.argv[1]).decode("utf-8"))
max_bytes, max_seconds = int(spec["max_bytes"]), float(spec["max_seconds"])
root = os.getcwd()
target = os.path.join(root, spec["workdir"]) if spec["workdir"] else root


def tree_bytes(path):
    total = 0
    for d, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.lstat(os.path.join(d, name)).st_size
            except OSError:
                pass
    return total


def unsafe(name):
    return name.startswith("/") or ".." in name.replace("\\", "/").split("/")


start = time.time()
before = tree_bytes(root)
out = {"kind": spec["kind"], "workdir": spec["workdir"]}
try:
    if spec["kind"] == "script":
        with open(os.path.join(root, spec["script"]), "rb") as f:
            out["sha256"] = hashlib.sha256(f.read()).hexdigest()
        out["command"] = " ".join(spec["argv"])
        proc = subprocess.run(spec["argv"], cwd=target, timeout=max_seconds, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        out["exit_code"] = proc.returncode
        out["output_tail"] = proc.stdout.decode("utf-8", "replace")[-1500:]
    else:
        import urllib.request
        url = spec["url"]
        name = url.rsplit("/", 1)[-1].split("?", 1)[0]
        if not os.path.isdir(target):
            os.makedirs(target)
        dest = os.path.join(target, name)
        digest, size = hashlib.sha256(), 0
        response = urllib.request.urlopen(url, timeout=30)
        with open(dest, "wb") as f:
            while True:
                if time.time() - start > max_seconds:
                    raise RuntimeError("the download passed %d s" % max_seconds)
                chunk = response.read(1 << 20)
                if not chunk:
                    break
                size += len(chunk)
                if size > max_bytes:
                    raise RuntimeError("the download passed %d bytes" % max_bytes)
                digest.update(chunk)
                f.write(chunk)
        out.update(url=url, sha256=digest.hexdigest(), downloaded_bytes=size)
        if name.endswith((".tar.gz", ".tgz")):
            with tarfile.open(dest) as archive:
                for member in archive.getmembers():
                    if unsafe(member.name) or member.issym() or member.islnk():
                        raise RuntimeError("refused archive member %r" % member.name)
                archive.extractall(target)
            out["extracted"] = True
        elif name.endswith(".zip"):
            with zipfile.ZipFile(dest) as archive:
                for member in archive.namelist():
                    if unsafe(member):
                        raise RuntimeError("refused archive member %r" % member)
                archive.extractall(target)
            out["extracted"] = True
        out["exit_code"] = 0
except subprocess.TimeoutExpired:
    out["exit_code"] = None
    out["error"] = "the step passed %d s and was stopped" % max_seconds
except Exception as exc:
    out["exit_code"] = None
    out["error"] = "%s: %s" % (type(exc).__name__, str(exc)[:300])
out["seconds"] = round(time.time() - start, 1)
out["bytes_written"] = tree_bytes(root) - before
if out["bytes_written"] > max_bytes:
    removed = 0
    for d, _dirs, files in os.walk(root):
        for name in files:
            path = os.path.join(d, name)
            try:
                if os.lstat(path).st_mtime >= start - 1:
                    os.remove(path)
                    removed += 1
            except OSError:
                pass
    out["over_cap"] = True
    out["removed_files"] = removed
sys.stdout.write("RERUN_DATA_PREP " + json.dumps(out, sort_keys=True) + "\n")
sys.stdout.flush()
'''


def data_prep_source() -> str:
    return _DATA_PREP_SOURCE


def data_prep_command(prep, python: str = "python3") -> str:
    """The setup command that runs the documented step `prep` (data_prep.DataPrep) under the caps; always exits 0."""
    import json

    spec = {"kind": prep.kind, "workdir": prep.workdir, "script": prep.script, "argv": list(prep.command), "url": prep.url,
            "max_bytes": DATA_PREP_MAX_BYTES, "max_seconds": DATA_PREP_MAX_SECONDS}
    code = base64.b64encode(_DATA_PREP_SOURCE.encode("utf-8")).decode("ascii")
    arg = base64.b64encode(json.dumps(spec, sort_keys=True).encode("utf-8")).decode("ascii")
    return f"{python} -c \"import base64;exec(base64.b64decode('{code}').decode('utf-8'))\" {arg} || true"


def parse_data_prep(*texts: str) -> dict | None:
    """The `RERUN_DATA_PREP {json}` record in a run's output, or None."""
    import json

    for text in texts:
        for line in (text or "").splitlines():
            if line.startswith(DATA_PREP_MARKER + " "):
                try:
                    return json.loads(line[len(DATA_PREP_MARKER) + 1:])
                except ValueError:
                    return {"error": "unreadable RERUN_DATA_PREP line"}
    return None


# --- resource evidence (harness-v1.4.2-rc, D-38 / D-40) --------------------------------------------------------------------------

EVIDENCE_BEGIN = "RERUN_EVIDENCE_BEGIN"
EVIDENCE_END = "RERUN_EVIDENCE_END"
OUTSIDE_PYTHON_REASON_CODE = "EXIT_OUTSIDE_PYTHON"

# Appended after the documented command, which runs unchanged in a subshell first: the evidence goes to stderr, the command's exit status is kept.
# Every read is tolerant (a file the sandbox does not have prints nothing); nothing here changes the repository or the environment.
_EVIDENCE_SUFFIX = (
    'rc=$?; { echo "RERUN_EVIDENCE_BEGIN exit_status=$rc"; '
    'echo "--ulimit"; ulimit -a 2>&1 | head -n 30; '
    'echo "--meminfo"; grep -E "^(MemTotal|MemAvailable|SwapTotal):" /proc/meminfo 2>&1; '
    'echo "--nproc"; nproc 2>&1; '
    'echo "--kernel"; uname -r 2>&1; cat /proc/swaps 2>&1 | tail -n +2; cat /proc/sys/vm/overcommit_memory 2>&1; '
    'echo "--selfcgroup"; cat /proc/self/cgroup 2>&1; '
    'echo "--cgroup"; cg=/sys/fs/cgroup$(sed -n "s/^0:://p" /proc/self/cgroup 2>/dev/null); cg=${cg%/}; '
    'for f in "$cg/memory.max" "$cg/memory.events" "$cg/memory.peak" '
    '/sys/fs/cgroup/memory.max /sys/fs/cgroup/memory.events /sys/fs/cgroup/memory.peak /sys/fs/cgroup/cpu.max '
    '/sys/fs/cgroup/memory/memory.limit_in_bytes /sys/fs/cgroup/memory/memory.max_usage_in_bytes /sys/fs/cgroup/memory/memory.failcnt; do '
    '[ -r "$f" ] && echo "$f=$(tr "\\n" " " < "$f")"; done; '
    'echo "--dmesg"; dmesg 2>&1 | grep -iE "killed process|out of memory|oom-kill|oom_kill" | tail -n 5; '
    'echo "RERUN_EVIDENCE_END"; } >&2; exit $rc'
)


def evidence_command(command: str) -> str:
    """`command` run unchanged in a subshell, followed by the evidence block on stderr and the command's own exit status. The command sits on its own
    lines: a trailing `# comment` in a documented command (corpus-v2 #3: `python feature_vgg16.py #gpu_id #split`) would otherwise swallow the `)`."""
    return f"(\n{command}\n); {_EVIDENCE_SUFFIX}"


def parse_evidence(*texts: str) -> dict | None:
    """The evidence block in a run's output, or None if the run printed none (the shell did not get that far, or the block is cut off)."""
    blob = "\n".join(t or "" for t in texts)
    match = re.search(rf"{EVIDENCE_BEGIN} exit_status=(-?\d+)(.*?){EVIDENCE_END}", blob, re.S)
    if not match:
        return None
    body = match.group(2)

    def kb(name: str) -> int | None:
        m = re.search(rf"^{name}:\s+(\d+) kB", body, re.M)
        return int(m.group(1)) if m else None

    cgroup = dict(re.findall(r"^(/sys/fs/cgroup/\S+?)=(.*)$", body, re.M))
    # the mount root's memory.events and the process's own cgroup's: the larger count counts (the root's is 0 inside a nested cgroup)
    oom_counts = [int(m.group(1)) for k, v in cgroup.items() if k.endswith("memory.events") for m in [re.search(r"\boom_kill (\d+)", v)] if m]
    section = lambda name: body.split(f"--{name}", 1)[1].split("\n--", 1)[0] if f"--{name}" in body else ""  # noqa: E731
    nproc = re.search(r"\d+", section("nproc"))
    return {
        "exit_status": int(match.group(1)),
        "mem_total_kb": kb("MemTotal"),
        "mem_available_kb": kb("MemAvailable"),
        "swap_total_kb": kb("SwapTotal"),
        "nproc": int(nproc.group(0)) if nproc else None,
        "cgroup": {k: v.strip() for k, v in cgroup.items()},
        "oom_kill": max(oom_counts) if oom_counts else None,
        "dmesg": [line.strip() for line in section("dmesg").splitlines() if line.strip()],
        "ulimit": [line.strip() for line in section("ulimit").splitlines() if line.strip()],
        "kernel": [line.strip() for line in section("kernel").splitlines() if line.strip()],
        "self_cgroup": [line.strip() for line in section("selfcgroup").splitlines() if line.strip()],
    }


def kill_evidenced(evidence: dict | None) -> bool:
    """A kill is evidenced by the command's own status (SIGKILL: 137 or -9), a cgroup OOM-kill count above zero, or a kernel log line about a killed
    process / out of memory. No evidence at all is not evidence of a kill."""
    if not evidence:
        return False
    if evidence.get("exit_status") in (137, -9) or (evidence.get("oom_kill") or 0) > 0:
        return True
    return any(re.search(r"killed process|out of memory|oom", line, re.I) for line in evidence.get("dmesg", []))


def limit_quote(evidence: dict | None) -> str:
    """The limits as the sandbox itself showed them (one line), or an empty string when the run read none."""
    if not evidence:
        return ""
    parts = []
    if evidence.get("mem_total_kb"):
        parts.append(f"/proc/meminfo MemTotal {evidence['mem_total_kb']} kB ({evidence['mem_total_kb'] / 1048576:.2f} GiB)")
    if evidence.get("nproc"):
        parts.append(f"nproc {evidence['nproc']}")
    for path, value in evidence.get("cgroup", {}).items():
        if path.endswith(("memory.max", "memory.limit_in_bytes", "cpu.max")):
            parts.append(f"{path} {value}")
    if evidence.get("oom_kill") is not None:
        parts.append(f"memory.events oom_kill {evidence['oom_kill']}")
    if evidence.get("dmesg"):
        parts.append(f"dmesg: {evidence['dmesg'][-1][:160]}")
    return "; ".join(parts)
