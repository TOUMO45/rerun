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
  1. torch, torchvision and torchaudio are installed TOGETHER as one matched set when ANY of them is imported or
     declared (harness-v1.3.2; attempt 1's entry 4 imported torchvision and got torch alone), from the CPU wheels
     (`--index-url https://download.pytorch.org/whl/cpu`, with PyPI as an extra index because the CPU index alone
     cannot supply torch's own dependencies), as its own sandbox operation, pinned exactly as the repo pins them
     (a `+cuXXX` local suffix is dropped). If the whole set cannot be resolved for this Python, only the members the
     repo uses are installed;
  2. a second operation clears the exec-stack flag on any torch shared object that has it, with a patchelf that
     the runner installs into its OWN prefix (/opt/rerun_tools, pinned 0.19.1.0, flag verified from `--help` first),
     and verifies `import torch`; a refusal that survives this, or a patchelf without the flag, is SANDBOX_INCOMPAT
     (INDETERMINATE), never the repo's fault. Any failure of these ops is phase `runner_setup` (error_chain);
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


def imported_torch_names(workdir: Path) -> set[str]:
    """Which of torch/torchvision/torchaudio any (size-capped) .py file in the repo imports."""
    names: set[str] = set()
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
            for m in _IMPORT.finditer(path.read_text(encoding="utf-8", errors="ignore")):
                names.add(re.sub(r"[^a-z]", "", m.group(0).split()[-1].split(".")[0]))
        except OSError:
            continue
    return names & set(TORCH_FAMILY)


def imports_torch(workdir: Path) -> bool:
    return bool(imported_torch_names(workdir))


@dataclass(frozen=True)
class TorchSetup:
    specs: tuple[str, ...]  # pip requirement strings, the whole family: ("torch==1.12.1", "torchvision", "torchaudio")
    reason: str
    # Names that are actually imported/declared. If the full matched set cannot be resolved for this Python
    # (an old torch pin with no matching torchaudio wheel), the install falls back to these alone.
    needed: tuple[str, ...] = ()

    @staticmethod
    def _pip(specs: tuple[str, ...]) -> str:
        quoted = " ".join(shlex.quote(s) for s in specs)
        return f"pip install {quoted} --index-url {CPU_INDEX} --extra-index-url {PYPI_INDEX}"

    @property
    def install_command(self) -> str:
        full = self._pip(self.specs)
        needed = tuple(s for s in self.specs if _spec_base(s) in self.needed)
        if not needed or set(needed) == set(self.specs):
            return full
        return f"{full} || {self._pip(needed)}"

    @property
    def fix_command(self) -> str:
        return f"python -c {shlex.quote(FIX_AND_VERIFY)}"


def _spec_base(spec: str) -> str:
    return re.split(r"[<>=!~ ]", spec, maxsplit=1)[0]


def plan_torch_setup(texts: Iterable[str], workdir: Path | None) -> TorchSetup | None:
    """None if the repo does not use torch. `texts` = the plan's install commands + the repo's requirement
    files (current copy). If ANY of torch/torchvision/torchaudio is imported or declared, the whole family is
    installed as one matched set (attempt 1, entry 4: the repo imported torchvision, the runner installed only
    torch, and torchvision was missing). Pins the repo declares are kept; the rest is left to the resolver, which
    picks the companion versions that match the torch in the set."""
    texts = list(texts)
    pins = torch_specs(texts)
    imported = imported_torch_names(workdir) if workdir is not None else set()
    used = set(pins) | imported
    if not used:
        return None
    specs = tuple(f"{name}{pins.get(name, '')}" for name in TORCH_FAMILY)
    needed = tuple(name for name in TORCH_FAMILY if name in used or name == "torch")
    if pins:
        reason = f"repo pins {', '.join(pins)}; installed the CPU wheels as a matched set with the same pins"
    else:
        reason = f"repo imports {', '.join(sorted(imported))} without declaring it; runner provides the newest matched CPU wheels"
    return TorchSetup(specs, reason, needed)


# One python program: find torch shared objects whose PT_GNU_STACK is executable (parsed from the ELF program
# headers, no binutils in a slim image), clear the flag with patchelf, then verify `import torch`.
# patchelf comes from a RUNNER-OWNED prefix (`pip install --target`, never the repo's site-packages) pinned to a
# release that has --clear-execstack (>= 0.18). pip on python:3.6-slim resolves an unpinned `patchelf` to 0.17.2, which
# lacks the flag: attempt 1, entry 3 ("patchelf: getting info about '--clear-execstack'"). The flag is verified from
# `--help` BEFORE use; if it is absent the platform cannot host this torch build: exit 98 with
# RERUN_SANDBOX_INCOMPAT (classified SANDBOX_INCOMPAT, INDETERMINATE), never the repository's fault.
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
    tools = "/opt/rerun_tools"
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "--target", tools,
                           "--ignore-requires-python", "patchelf==0.19.1.0"])
    patchelf = tools + "/bin/patchelf"
    out = subprocess.run([patchelf, "--help"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True)
    version = subprocess.run([patchelf, "--version"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             universal_newlines=True).stdout.strip()
    if "clear-execstack" not in out.stdout:
        sys.stderr.write("RERUN_SANDBOX_INCOMPAT: %s has no --clear-execstack; cannot make this torch build loadable here\n" % version)
        sys.exit(98)
    for path in bad:
        subprocess.check_call([patchelf, "--clear-execstack", path])
    print("RERUN_EXECSTACK_CLEARED", len(bad), version)
subprocess.check_call([sys.executable, "-c", "import torch; print('RERUN_TORCH_OK', torch.__version__)"])
"""
