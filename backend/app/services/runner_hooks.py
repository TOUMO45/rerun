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

The module sources are Python 3.6-compatible (the oldest sandbox image is python:3.6-slim) and are sent base64-encoded, like the smoke
launcher, so no shell quoting can change them.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass

CPU_SHIM = "cpu_shim"
EXIT_HOOK = "exit_hook"

CPU_SHIM_MARKER = "RERUN_CPU_SHIM"
EXIT_HOOK_MARKER = "RERUN_EXIT_HOOK"
INSTALLED_MARKER = "RERUN_HOOK_INSTALLED"

_CPU_SHIM_SOURCE = r'''
"""RERUN CPU shim (harness-v1.4.0-rc): injected by RERUN, not part of the repository."""
import sys

_TARGET = "torch"


def _patch(torch):
    try:
        torch.cuda.is_available = lambda: False
        _orig_load = torch.load

        def load(f, *args, **kwargs):
            if args:
                args = ("cpu",) + tuple(args[1:])
            else:
                kwargs["map_location"] = "cpu"
            return _orig_load(f, *args, **kwargs)

        load.__wrapped__ = _orig_load
        torch.load = load
        sys.stderr.write("RERUN_CPU_SHIM: injected by RERUN: torch.load(map_location='cpu'), torch.cuda.is_available() -> False\n")
    except Exception as exc:  # the shim must never break the import it patches
        sys.stderr.write("RERUN_CPU_SHIM: not applied (%r)\n" % (exc,))


class _Finder(object):
    def find_spec(self, name, path=None, target=None):
        if name != _TARGET:
            return None
        try:
            sys.meta_path.remove(self)
        except ValueError:
            pass
        import importlib.util
        spec = importlib.util.find_spec(name)
        loader = getattr(spec, "loader", None)
        if loader is None or not hasattr(loader, "exec_module"):
            return spec
        original = loader.exec_module

        def exec_module(module):
            original(module)
            _patch(module)

        loader.exec_module = exec_module
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

try:
    import builtins
    for _name in ("exit", "quit"):
        _quitter = getattr(builtins, _name, None)
        if _quitter is not None:
            def _make(real, label):
                def _call(code=None):
                    _report("%s(%r)" % (label, code), _code_of(code), traceback.format_stack()[:-1])
                    return real(code)
                return _call
            setattr(builtins, _name, _make(_quitter, _name))
except Exception:
    pass
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
    CPU_SHIM: Hook(CPU_SHIM, "cpu_shim", "GPU_REQUIRED at repair time"),
    EXIT_HOOK: Hook(
        EXIT_HOOK, "exit_site_hook", "a non-zero exit with no traceback (silent exit, D-25)",
        "a bare `raise SystemExit(n)` in the repository's own code is not captured; sys.exit, os._exit, exit(), quit() and "
        "libraries that call sys.exit are",
    ),
}


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
