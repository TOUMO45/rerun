"""harness-v1.8 (T2): a pre-release pin the index never published, at the runner's own setup step.

TEST-B #2 vlievin/ovis (now DEV-CONTAMINATED), `runs/corpus_v3_batch/harness-v1.7.2/treatment/02_vlievin__ovis.json`: the repository pins `torchvision==0.6.0a0`, a
development version of the release that went with torch 1.5.0 and that was never uploaded to PyPI or the PyTorch index. The runner's torch-family install failed
(`ERROR: Could not find a version that satisfies the requirement torchvision==0.6.0a0 (from versions: ..., 0.6.0, 0.6.0+cpu, ...)`) BEFORE the baseline ran, so the run
ended INDETERMINATE RUNNER_SETUP_FAILED with no repair attempt and no verdict on the repository.

The rule: a torch-family package pinned exactly to a pre-release (`a`, `b`, `rc` or `.dev` suffix) that the index does not serve is pinned to a final release,
the same way R5's companion rule replaces a torchvision release that cannot coexist with the pinned torch: through `state.torch_overrides` and RERUN's own copy of
the requirements, recorded as a time-machine action and labelled a DEPENDENCY CHANGE (`outcome_levels.dependency_change`). The repository's files are never edited.
Only torch, torchvision and torchaudio: they are the packages the runner installs itself, so a failure there precedes the baseline; any other package's pre-release pin
failure happens in the repository's own install step and goes through the normal repair.

WHICH final release (found on the DEV re-run of ovis, 2026-10-07): the numeric one (`0.6.0`) is the release made for torch 1.5.0, and the repository pins torch 1.5.1, so pip
answered `Cannot install torch==1.5.1, torchvision==0.6.0 and torchvision==0.6.0+cpu because these package versions have conflicting dependencies` (ResolutionImpossible) and the
run ended RUNNER_SETUP_FAILED again, one step later. For torchvision the replacement is therefore the release made for the exact torch pin the same requirements carry
(`torch_companions_data.TORCHVISION_FOR_TORCH`, the dated snapshot of PyPI's metadata R5 already uses: torch 1.5.1 -> torchvision 0.6.1); when the torch pin is not
exact or the table does not know it, the numeric final release is used as before.

PURE. No network, no model call, no filesystem. NOT sandbox-touching (the existing override path is used unchanged).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

TORCH_FAMILY = ("torch", "torchvision", "torchaudio")
_MISSING = re.compile(r"Could not find a version that satisfies the requirement (torch|torchvision|torchaudio)==(\d+(?:\.\d+)*)((?:a|b|rc|\.dev)\d*)(?:\+[\w.]+)?")
RULE = "prerelease_pin_relax"


@dataclass(frozen=True)
class PrereleaseRelax:
    package: str
    pinned: str  # as the repository wrote it, e.g. "0.6.0a0"
    replacement: str  # the final release, e.g. "0.6.0"
    # R5's block reads these two when it logs; a pre-release has no primary pin it is kept beside
    primary: str = ""
    primary_version: str = ""

    def overrides(self) -> dict[str, str]:
        return {self.package: self.replacement}

    def as_dict(self) -> dict:
        reason = (f"{self.package}=={self.pinned} is a pre-release that the index does not serve (pip lists only the final release); "
                  + (f"{self.package}=={self.replacement}, the release made for {self.primary}=={self.primary_version}, is pinned instead"
                     if self.primary else f"its final release {self.package}=={self.replacement} is pinned instead"))
        return {"package": self.package, "from": self.pinned, "to": self.replacement, "kept": f"{self.primary}=={self.primary_version}" if self.primary else "", "also": [], "reason": reason}


def relax_for(log: str, specs: Iterable[str]) -> PrereleaseRelax | None:
    """The relaxation for a runner-setup failure whose log says the index has no such pre-release, when the runner's own torch-family specs carry that exact pin."""
    m = _MISSING.search(log or "")
    if not m:
        return None
    package, final, suffix = m.group(1), m.group(2), m.group(3)
    pinned = f"{final}{suffix}"
    specs = tuple(specs)
    if not any(spec.replace(" ", "") == f"{package}=={pinned}" for spec in specs):
        return None
    if package == "torchvision":
        from app.services import torch_companions_data as data

        torch_pin = next((m.group(1) for spec in specs for m in [re.fullmatch(r"torch==(\d+(?:\.\d+)*)(?:\+[\w.]+)?", spec.replace(" ", ""))] if m), None)
        paired = data.TORCHVISION_FOR_TORCH.get(torch_pin) if torch_pin else None
        if paired:
            return PrereleaseRelax(package, pinned, paired, primary="torch", primary_version=torch_pin)
    return PrereleaseRelax(package, pinned, final)
