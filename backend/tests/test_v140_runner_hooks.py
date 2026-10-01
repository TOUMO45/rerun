"""harness-v1.4.0-rc: the CPU shim and the exit-site hook, run for real in a local Python process (no sandbox, no network)."""

from __future__ import annotations

import base64
import os
import re
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from app.services import classifier, runner_hooks, smoke_exec


def _site(tmp_path: Path, *hooks: str) -> Path:
    """A directory standing in for site-packages: the hook modules and their .pth files, exactly as the installer writes them."""
    site = tmp_path / "site"
    site.mkdir()
    for name in hooks:
        (site / f"rerun_{name}.py").write_text(runner_hooks.source_of(name), encoding="utf-8")
        (site / f"rerun_{name}.pth").write_text(f"import rerun_{name}\n", encoding="utf-8")
    return site


def _run(site: Path, code: str, *extra_paths: Path) -> subprocess.CompletedProcess:
    # site.addsitedir processes the .pth files the same way interpreter start-up does for site-packages.
    boot = f"import site, sys; [sys.path.insert(0, p) for p in {[str(p) for p in extra_paths]!r}]; site.addsitedir({str(site)!r})\n"
    return subprocess.run([sys.executable, "-c", boot + textwrap.dedent(code)], capture_output=True, text=True, timeout=60)


# --- exit-site hook (D-25) ------------------------------------------------------------------------------------

def test_the_exit_hook_prints_the_stack_of_a_sys_exit_1(tmp_path):
    proc = _run(_site(tmp_path, runner_hooks.EXIT_HOOK), """
        import sys
        def load_config():
            sys.exit(1)
        def main():
            load_config()
        main()
    """)
    assert proc.returncode == 1
    assert "RERUN_EXIT_HOOK: sys.exit(1) was called" in proc.stderr
    assert re.search(r"line \d+, in load_config", proc.stderr) and re.search(r"line \d+, in main", proc.stderr)
    assert proc.stderr.rstrip().endswith("SystemExit: 1")
    # the classifier now has error text to work with: the run is no longer a silent exit
    assert classifier.has_actionable_error(proc.stderr, proc.stdout)


def test_the_exit_hook_covers_os_exit_and_exit(tmp_path):
    site = _site(tmp_path, runner_hooks.EXIT_HOOK)
    proc = _run(site, "import os\ndef f():\n    os._exit(3)\nf()\n")
    assert proc.returncode == 3 and "os._exit(3) was called" in proc.stderr and re.search(r"in f", proc.stderr)
    proc = _run(site, "exit(2)\n")
    assert proc.returncode == 2 and "exit(2) was called" in proc.stderr


def test_the_exit_hook_is_silent_on_a_clean_exit_and_does_not_change_semantics(tmp_path):
    site = _site(tmp_path, runner_hooks.EXIT_HOOK)
    proc = _run(site, "import sys\nsys.exit(0)\n")
    assert proc.returncode == 0 and "RERUN_EXIT_HOOK" not in proc.stderr
    # code that catches SystemExit still catches it (the hook raises the real exception class)
    proc = _run(site, """
        import sys
        try:
            sys.exit(4)
        except SystemExit as exc:
            print("caught", exc.code, type(exc) is SystemExit)
    """)
    assert proc.returncode == 0 and "caught 4 True" in proc.stdout


def test_the_smoke_launcher_own_exit_is_never_reported(tmp_path):
    site = _site(tmp_path, runner_hooks.EXIT_HOOK)
    # Both processes load the hook (in the sandbox the .pth does it for every interpreter; here an explicit import does).
    command = smoke_exec.wrap(f'"{sys.executable}" -c "import rerun_exit_hook, sys; sys.exit(5)"', seconds=30, python=f'"{sys.executable}"')
    launcher = command.replace("import base64;", "import rerun_exit_hook, base64;", 1)
    proc = subprocess.run(launcher, shell=True, capture_output=True, text=True, timeout=60, env=dict(os.environ, PYTHONPATH=str(site)))
    assert proc.returncode == 5
    # exactly one report: the repository command's sys.exit(5); the launcher's own sys.exit(5) is not reported
    assert proc.stderr.count("RERUN_EXIT_HOOK") == 1 and "sys.exit(5) was called" in proc.stderr


# --- CPU shim (GPU_REQUIRED) --------------------------------------------------------------------------------

FAKE_TORCH = '''
class _Cuda(object):
    @staticmethod
    def is_available():
        return True
cuda = _Cuda()
def load(f, map_location=None, **kwargs):
    if map_location != "cpu":
        raise RuntimeError("Attempting to deserialize object on a CUDA device but torch.cuda.is_available() is False. "
                           "If you are running on a CPU-only machine, please use torch.load with map_location=torch.device('cpu')")
    return {"loaded_from": f, "map_location": map_location}
'''


@pytest.fixture
def fake_torch(tmp_path):
    pkg = tmp_path / "pkgs" / "torch"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text(FAKE_TORCH, encoding="utf-8")
    return tmp_path / "pkgs"


def test_without_the_shim_the_recorded_error_reproduces(tmp_path, fake_torch):
    proc = _run(_site(tmp_path), "import torch\ntorch.load('model.pt')\n", fake_torch)
    assert proc.returncode == 1 and classifier.classify(1, proc.stderr).code == "GPU_REQUIRED"


def test_the_shim_maps_every_load_to_the_cpu_and_hides_cuda(tmp_path, fake_torch):
    proc = _run(_site(tmp_path, runner_hooks.CPU_SHIM), """
        import torch
        print(torch.load("model.pt"))
        print(torch.load("model.pt", "cuda:0"))
        print(torch.load("model.pt", map_location=lambda s, l: s))
        print("cuda", torch.cuda.is_available())
    """, fake_torch)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.count("'map_location': 'cpu'") == 3 and "cuda False" in proc.stdout
    assert "RERUN_CPU_SHIM: injected by RERUN" in proc.stderr
    assert not classifier.has_actionable_error(proc.stderr)  # the shim's own line is not an error


def test_the_shim_does_not_import_torch_by_itself(tmp_path, fake_torch):
    proc = _run(_site(tmp_path, runner_hooks.CPU_SHIM), "import sys\nprint('torch' in sys.modules)\n", fake_torch)
    assert proc.returncode == 0 and proc.stdout.strip() == "False"


# --- the install command ------------------------------------------------------------------------------------

def test_the_install_command_writes_module_and_pth_into_site_packages(tmp_path):
    command = runner_hooks.install_command(runner_hooks.EXIT_HOOK, python=f'"{sys.executable}"')
    # run the installer against a throw-away site directory: patch site.getsitepackages via a sitecustomize-free shim
    target = tmp_path / "target"
    target.mkdir()
    code = re.search(r"b64decode\('([A-Za-z0-9+/=]+)'\)", command).group(1)
    installer = base64.b64decode(code).decode("utf-8").replace("list(site.getsitepackages())", repr([str(target)]))
    payload = command.rsplit(" ", 1)[1]
    proc = subprocess.run([sys.executable, "-c", installer, runner_hooks.EXIT_HOOK, payload], capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    assert (target / "rerun_exit_hook.py").read_text(encoding="utf-8") == runner_hooks.source_of(runner_hooks.EXIT_HOOK)
    assert (target / "rerun_exit_hook.pth").read_text(encoding="utf-8") == "import rerun_exit_hook\n"
    assert runner_hooks.hook_of_command(runner_hooks.install_command(runner_hooks.CPU_SHIM)) == runner_hooks.CPU_SHIM


@pytest.mark.parametrize("name", [runner_hooks.CPU_SHIM, runner_hooks.EXIT_HOOK])
def test_hook_sources_are_python36_syntax(name):
    source = runner_hooks.source_of(name)
    compile(source, name, "exec", dont_inherit=True)
    assert "f\"" not in source and "f'" not in source and ":=" not in source  # no f-strings, no walrus (3.6 image)


# --- regressions found by the independent review ----------------------------------------------------------------------

def test_the_shim_survives_a_library_that_looks_for_torch_before_importing_it(tmp_path, fake_torch):
    """transformers / accelerate / lightning call importlib.util.find_spec("torch") first: that must not use the shim up."""
    proc = _run(_site(tmp_path, runner_hooks.CPU_SHIM), """
        import importlib.util
        assert importlib.util.find_spec("torch") is not None
        assert importlib.util.find_spec("torch") is not None
        import torch
        print(torch.load("model.pt"), "cuda", torch.cuda.is_available())
    """, fake_torch)
    assert proc.returncode == 0, proc.stderr
    assert "'map_location': 'cpu'" in proc.stdout and "cuda False" in proc.stdout
    assert proc.stderr.count("RERUN_CPU_SHIM: injected") == 1


def test_the_exit_hook_wraps_exit_and_quit_even_though_site_defines_them_after_the_pth_files(tmp_path):
    """site.main() processes .pth files BEFORE setquit() defines exit()/quit(): reproduce that order with `python -S`, then run the
    same steps site.main() runs (addsitedir, then setquit)."""
    site_dir = _site(tmp_path, runner_hooks.EXIT_HOOK)
    code = (f"import site, builtins\nassert not hasattr(builtins, 'exit')\nsite.addsitedir({str(site_dir)!r})\n"
            "site.setquit()\ndef leave():\n    exit(4)\nleave()\n")
    proc = subprocess.run([sys.executable, "-S", "-c", code], capture_output=True, text=True, timeout=60)
    assert proc.returncode == 4
    assert "RERUN_EXIT_HOOK: exit(4) was called" in proc.stderr and re.search(r"in leave", proc.stderr)
