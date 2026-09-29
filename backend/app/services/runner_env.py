"""Runner-level environment policy for torch (Phase 3).

Torch is provided by the RUNNER, not left to each repo, because two facts found live (2026-09-29, real
Nebius sandbox, glibc 2.41 / kernel 7.0.6, record: runs/torch_check/) make the naive path measure the
platform instead of the paper:

  * the sandbox refuses shared objects that require an executable stack. The newest torch wheel
    (2.14.0+cpu) loads; an old pin (1.12.1+cpu) is refused with
    `libtorch_cpu.so: cannot enable executable stack as shared object requires: Invalid argument`
    — the error that sank pilot entry 3;
  * `patchelf --clear-execstack` on the offending libraries fixes it (verified: `import torch` -> 1.12.1+cpu).

Policy:
  1. torch is installed from the CPU wheels (`--index-url https://download.pytorch.org/whl/cpu`, with PyPI as
     an extra index because the CPU index alone cannot supply torch's own dependencies), as its own sandbox
     operation, pinned exactly as the repo pins it (a `+cuXXX` local suffix is dropped);
  2. a second operation clears the exec-stack flag on any torch shared object that has it and verifies
     `import torch`; a refusal that survives this is SANDBOX_INCOMPAT (INDETERMINATE), never the repo's fault;
  3. CUDA wheels only if the repo pins a CUDA build AND the sandbox exposes a GPU. It does not
     (SANDBOX_HAS_GPU = False), so CPU always.

Torch is set up only for repos that use it (a pin in the plan/requirements, or an import in the code):
a torch-free repo pays nothing. Only torch/torchvision/torchaudio are provided; numpy, scipy, tabulate and
every other package stay the repo's job — an undeclared one is a repository defect (attribution REPO), and
pre-installing them would hide it.
"""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

CPU_INDEX = "https://download.pytorch.org/whl/cpu"
PYPI_INDEX = "https://pypi.org/simple"
SANDBOX_HAS_GPU = False  # Nebius Token Factory Sandboxes expose no GPU

TORCH_FAMILY = ("torch", "torchvision", "torchaudio")

_SPEC = re.compile(
    r"(?<![\w.-])(?P<name>torch|torchvision|torchaudio)\s*(?P<spec>(?:[<>=!~]=?\s*[\w.*]+(?:\+[\w.]+)?"
    r"(?:\s*,\s*[<>=!~]=?\s*[\w.*]+(?:\+[\w.]+)?)*)?)(?![\w.-])"
)
_IMPORT = re.compile(r"^\s*(?:import|from)\s+torch(?:vision|audio)?\b", re.M)
_MAX_PY_FILES = 3000
_MAX_PY_BYTES = 400_000


def torch_specs(texts: Iterable[str]) -> dict[str, str]:
    """torch-family requirement specs found in requirement-like text (requirements files, `pip install`
    commands, printf'd lists), keyed by package. `+cu113`-style local suffixes are dropped (the sandbox has no
    GPU). The first spec seen for a package wins."""
    found: dict[str, str] = {}
    for text in texts:
        for m in _SPEC.finditer(text or ""):
            name = m.group("name")
            spec = re.sub(r"\+[\w.]+", "", m.group("spec")).replace(" ", "")
            if name not in found or (spec and not found[name]):
                found[name] = spec
    return found


def imports_torch(workdir: Path) -> bool:
    """Does any (size-capped) .py file in the repo import torch/torchvision/torchaudio?"""
    seen = 0
    for path in workdir.rglob("*.py"):
        if ".git" in path.parts:
            continue
        seen += 1
        if seen > _MAX_PY_FILES:
            break
        try:
            if path.stat().st_size > _MAX_PY_BYTES:
                continue
            if _IMPORT.search(path.read_text(encoding="utf-8", errors="ignore")):
                return True
        except OSError:
            continue
    return False


@dataclass(frozen=True)
class TorchSetup:
    specs: tuple[str, ...]  # pip requirement strings, e.g. ("torch==1.12.1", "torchvision==0.13.1")
    reason: str

    @property
    def install_command(self) -> str:
        quoted = " ".join(shlex.quote(s) for s in self.specs)
        return f"pip install {quoted} --index-url {CPU_INDEX} --extra-index-url {PYPI_INDEX}"

    @property
    def fix_command(self) -> str:
        return f"python -c {shlex.quote(FIX_AND_VERIFY)}"


def plan_torch_setup(texts: Iterable[str], workdir: Path | None) -> TorchSetup | None:
    """None if the repo does not use torch. `texts` = the plan's install commands + the repo's requirement
    files (current copy)."""
    texts = list(texts)
    pins = torch_specs(texts)
    if pins:
        # A torchvision/torchaudio pin without a torch pin: leave torch to the resolver (it will take the
        # torch that matches the pinned companion).
        companion_pinned = any(spec for name, spec in pins.items() if name != "torch")
        specs = tuple(f"{name}{spec}" for name, spec in pins.items() if not (name == "torch" and not spec and companion_pinned))
        return TorchSetup(specs, f"repo pins {', '.join(pins)}; installed CPU wheels with the same pins")
    if workdir is not None and imports_torch(workdir):
        return TorchSetup(("torch",), "repo imports torch without declaring it; runner provides the newest CPU wheel")
    return None


# One python program: find torch shared objects whose PT_GNU_STACK is executable (parsed from the ELF program
# headers, no binutils in a slim image), clear the flag with patchelf, then verify `import torch`.
FIX_AND_VERIFY = r"""
import glob, importlib.util, os, struct, subprocess, sys
spec = importlib.util.find_spec("torch")
root = os.path.join(os.path.dirname(spec.origin), "lib")
PT_GNU_STACK = 0x6474e551
bad = []
for path in sorted(glob.glob(os.path.join(root, "*.so*"))):
    with open(path, "rb") as f:
        head = f.read(64)
        if head[:4] != b"\x7fELF" or head[4] != 2:
            continue
        phoff, = struct.unpack_from("<Q", head, 32)
        phentsize, phnum = struct.unpack_from("<HH", head, 54)
        f.seek(phoff)
        for _ in range(phnum):
            ph = f.read(phentsize)
            p_type, p_flags = struct.unpack_from("<II", ph, 0)
            if p_type == PT_GNU_STACK and p_flags & 1:
                bad.append(path)
if bad:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "patchelf"])
    for path in bad:
        subprocess.check_call(["patchelf", "--clear-execstack", path])
    print("RERUN_EXECSTACK_CLEARED", len(bad))
subprocess.check_call([sys.executable, "-c", "import torch; print('RERUN_TORCH_OK', torch.__version__)"])
"""
