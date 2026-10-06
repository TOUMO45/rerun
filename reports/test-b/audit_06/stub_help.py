"""Run run.py --help exactly as the sandbox did, with its heavy third-party and local imports replaced by empty modules.
argparse's --help prints and exits before any of them is used; stdout and stderr are written as raw bytes for hashing."""
import io
import runpy
import sys
import types


class _Any(types.ModuleType):
    __path__ = []  # a package, so `from x.y import z` works

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return _Any(f"{self.__name__}.{name}")

    def __call__(self, *a, **k):
        return _Any("call")


for name in ("tqdm", "torch", "transformers", "data", "data.dataset", "utils", "utils.measure", "utils.parser", "utils.tools", "utils.yk"):
    sys.modules[name] = _Any(name)
sys.modules["transformers"].__all__ = [f"{m}{k}" for m in ("Bert", "GPT2", "Roberta", "XLNet") for k in ("Model", "Tokenizer", "Config")]

out, err = io.StringIO(), io.StringIO()
sys.stdout, sys.stderr = out, err
sys.argv = ["run.py", "--help"]
code = 0
try:
    runpy.run_path("run.py", run_name="__main__")
except SystemExit as exc:
    code = exc.code
sys.stdout, sys.stderr = sys.__stdout__, sys.__stderr__
open("_help_stdout.bin", "wb").write(out.getvalue().encode("utf-8"))
open("_help_stderr.bin", "wb").write(err.getvalue().encode("utf-8"))
print("exit", code, "stdout", len(out.getvalue().encode()), "stderr", len(err.getvalue().encode()))
