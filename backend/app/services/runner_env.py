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
    # torch older than 2.3 is compiled against NumPy 1.x: with NumPy 2 installed `import torch` fails (`_ARRAY_API not found`,
    # corpus-v2 entry 11: the runner's own setup check failed, INDETERMINATE RUNNER_SETUP_FAILED). The runner installs NumPy<2
    # in the same pip command whenever the torch pin is older than 2.3 (harness-v1.3.3).
    cap_numpy: bool = False

    def _pip(self, specs: tuple[str, ...]) -> str:
        quoted = " ".join(shlex.quote(s) for s in (*specs, *(("numpy<2",) if self.cap_numpy else ())))
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


def torch_older_than_2_3(spec: str) -> bool:
    """True if a torch requirement spec pins or upper-bounds a release below 2.3 (`==1.8.1`, `<2`, `~=1.12`, `<=1.13.1`).
    A bare name or a lower bound (`>=1.0`) selects the newest wheel, which is >= 2.3, so it is False."""
    for op, version in re.findall(r"(==|<=|<|~=)\s*(\d+(?:\.\d+)*)", spec or ""):
        parts = [int(p) for p in version.split(".")]
        parts += [0] * (2 - len(parts))
        if tuple(parts[:2]) < (2, 3) or (op == "<" and tuple(parts[:2]) <= (2, 3)):
            return True
    return False


# --- harness-v1.7 (R1, memory): the re-execution after the sandbox killed a process for memory ----------------------------------------------------
# MALLOC_ARENA_MAX=2 caps glibc's per-thread malloc arenas (each can hold freed memory the process never returns); OMP_NUM_THREADS=4 is the
# sandbox's CPU count (nproc 4 in every evidence block), so no OpenMP pool is sized past it. Set in the shell before the documented command, so
# every process of the run (DataLoader workers, a shell script's python) inherits them; a value the documented command sets itself wins.
MEMORY_ENV: tuple[tuple[str, str], ...] = (("MALLOC_ARENA_MAX", "2"), ("OMP_NUM_THREADS", "4"))

# R1 (b) swap_file: built only if the v1.7 probe shows the sandbox can enable a swap file and a process then survives past 3.85 GiB.
# The probe (runs/sandbox_verification/v1.7-probes/probe_20261005T064245Z.json, 2026-10-05) did not show it: on the virtiofs root, fallocate and
# mkswap returned 0, swapon returned 255 `Invalid argument` (kernel: `swapon: swapfile has holes`), and the allocation was skipped. So (b) is not
# built. The follow-up probe (probe_dd_20261005T080007Z.json; not pre-registered) wrote a 2 GiB file with dd (every block allocated: 2097152 KiB
# on disk), mkswap returned 0, and swapon again returned 255 `Invalid argument` (kernel: `swapon: swapfile has holes`). The sandbox's virtiofs root
# cannot back a swap file, written either way: (b) is not buildable on this sandbox.
SWAP_FILE_ENABLED = False
SWAP_FILE_MARKER = "RERUN_SWAP_FILE"
# The pre-registration allows R1 (d) resource_adapt only once (b) is decided: built, or shown by the probe not to be buildable. While False,
# resource_adapt never fires (v1.7 review, M6). True from the follow-up probe's record (above): (b) not buildable. resource_adapt is NOT
# semantics-preserving and every verdict it touches carries RESOURCE-ADAPTED (outcome_levels.verdict_label).
SWAP_FILE_DECIDED = True


def with_memory_env(command: str) -> str:
    return "export " + " ".join(f"{k}={v}" for k, v in MEMORY_ENV) + "\n" + command


# --- harness-v1.7 (R4, apt_archive): an end-of-life Debian release on the base image ------------------------------------------------------------
# DEV #16 (python:3.6-slim) and DEV #9 round 3 (python:3.7-slim) are Debian 11 "bullseye" images: their apt sources still name security.debian.org,
# which no longer serves bullseye's files (`E: Failed to fetch http://security.debian.org/debian-security/pool/... 404`, APT_MIRROR_GONE). At
# repair time, once, every apt command of the run is preceded by one RERUN-owned shell step that reads VERSION_CODENAME from /etc/os-release and,
# ONLY for a codename in EOL_APT_SOURCES, rewrites /etc/apt/sources.list to that release's suites on its official archive, drops every other
# source file, and turns off the Release-file expiry check (archived Release files are past their Valid-Until date). A live release is left alone.
# The same Debian release's packages: no version changes. The suites follow the v1.7 probe (runs/sandbox_verification/v1.7-probes/
# probe_20261005T064245Z.json): archive.debian.org answered 200 for the Release file of bullseye, bullseye-updates, buster and buster-updates, so those
# two releases get main and <codename>-updates; stretch was not probed and stays main only. For buster that is the Release files' status only: no
# apt-get update has run against the buster lines, and the seal's live check (bullseye) does not cover them. The security suite is dropped as pre-registered (the archive
# answered 200 for bullseye-security too; it is not used). The live check in the v1.7 seal (N3) tests the bullseye rewrite. The step runs in a subshell, so the
# variables /etc/os-release defines do not leak into the apt command after it (v1.7 review, L1). Because it is prefixed to the apt command, the runner's
# setup splitter (sandbox_limits.split_setup_ops) files that command with the requirements steps, after the torch step, not before it: the order changes,
# nothing else (accepted; sandbox_limits.py is not changed).
EOL_APT_SOURCES: dict[str, tuple[str, ...]] = {
    "stretch": ("deb http://archive.debian.org/debian stretch main",),
    "buster": ("deb http://archive.debian.org/debian buster main", "deb http://archive.debian.org/debian buster-updates main"),
    "bullseye": ("deb http://archive.debian.org/debian bullseye main", "deb http://archive.debian.org/debian bullseye-updates main"),
}
APT_ARCHIVE_MARKER = "RERUN_APT_ARCHIVE"
_APT_COMMAND = re.compile(r"(?<![\w-])apt(?:-get)?\s[^\n;&|]*?\b(?:update|install)\b")


def apt_archive_step() -> str:
    """The POSIX-sh step (Debian images run it as root). Prints `RERUN_APT_ARCHIVE <codename>` to stderr when it rewrote, nothing otherwise; never fails."""
    cases = []
    for codename, lines in sorted(EOL_APT_SOURCES.items()):
        body = "".join(f"{line}\\n" for line in lines)
        cases.append(f"{codename}) printf '{body}' > /etc/apt/sources.list; rm -f /etc/apt/sources.list.d/*.list /etc/apt/sources.list.d/*.sources; "
                     f"echo 'Acquire::Check-Valid-Until \"false\";' > /etc/apt/apt.conf.d/99rerun-archive; echo \"{APT_ARCHIVE_MARKER} $VERSION_CODENAME\" >&2;;")
    return ("(if [ -r /etc/os-release ]; then . /etc/os-release; case \"$VERSION_CODENAME\" in " + " ".join(cases) + " *) ;; esac; fi)")


def apt_archive_rewrote(*texts: str) -> list[str]:
    """The codenames the apt-archive step rewrote, from a run's output (`RERUN_APT_ARCHIVE <codename>` lines), sorted, each once."""
    return sorted({m for text in texts for m in re.findall(APT_ARCHIVE_MARKER + r" (\w+)", text or "")})


def with_apt_archive(command: str) -> str:
    """`command` preceded by the apt-archive step when it runs apt (update or install), else unchanged."""
    return f"{apt_archive_step()}\n{command}" if _APT_COMMAND.search(command or "") else command


@dataclass(frozen=True)
class CompanionSwap:
    """harness-v1.7 (R5, companion_relax): the repository pins torch and torchvision exactly, to releases that cannot be installed together (the
    torchvision release requires another torch). The torch pin is kept (it decides the numerics); the torchvision pin becomes the release made for
    that torch (torch_companions_data, a dated snapshot of PyPI's metadata, never read at run time)."""
    package: str
    pinned: str
    replacement: str
    primary: str
    primary_version: str
    pinned_requires: str

    def as_dict(self) -> dict:
        from app.services import torch_companions_data as data

        return {"package": self.package, "from": self.pinned, "to": self.replacement, "kept": f"{self.primary}=={self.primary_version}",
                "reason": f"{self.package} {self.pinned} requires {self.primary}=={self.pinned_requires}; the repository pins "
                          f"{self.primary}=={self.primary_version}, whose {self.package} is {self.replacement}",
                "table": {"source": data.SOURCE, "retrieved": data.RETRIEVED}}


_EXACT = re.compile(r"^==\s*(\d+(?:\.\d+)*)$")


def companion_swap(specs: Iterable[str]) -> CompanionSwap | None:
    """The swap for a torch-family requirement set whose exact torch and torchvision pins cannot coexist, else None. Only exact pins (`==X`) are
    read: a range is the resolver's to settle. None when the table does not know either release, or when the pins already agree."""
    from app.services import torch_companions_data as data

    pins = {}
    for spec in specs:
        name = _spec_base(spec)
        m = _EXACT.match(spec[len(name):].strip())
        if m:
            pins[name] = m.group(1)
    torch_v, vision_v = pins.get("torch"), pins.get("torchvision")
    if not torch_v or not vision_v:
        return None
    requires = data.TORCHVISION_REQUIRES_TORCH.get(vision_v)
    replacement = data.TORCHVISION_FOR_TORCH.get(torch_v)
    if requires is None or replacement is None or requires == torch_v or replacement == vision_v:
        return None
    return CompanionSwap("torchvision", vision_v, replacement, "torch", torch_v, requires)


def plan_torch_setup(texts: Iterable[str], workdir: Path | None, overrides: dict[str, str] | None = None) -> TorchSetup | None:
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
    for name, version in (overrides or {}).items():  # harness-v1.7 (R5): a companion pin relaxed at repair time (CompanionSwap)
        if name in pins:
            pins[name] = f"=={version}"
    specs = tuple(f"{name}{pins.get(name, '')}" for name in TORCH_FAMILY)
    needed = tuple(name for name in TORCH_FAMILY if name in used or name == "torch")
    if overrides:
        reason = (f"repo pins {', '.join(pins)}; installed the CPU wheels as a matched set with the same pins except "
                  + ", ".join(f"{n}=={v} (companion relaxed)" for n, v in overrides.items()))
    elif pins:
        reason = f"repo pins {', '.join(pins)}; installed the CPU wheels as a matched set with the same pins"
    else:
        reason = f"repo imports {', '.join(sorted(imported))} without declaring it; runner provides the newest matched CPU wheels"
    return TorchSetup(specs, reason, needed, cap_numpy=torch_older_than_2_3(pins.get("torch", "")))


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
