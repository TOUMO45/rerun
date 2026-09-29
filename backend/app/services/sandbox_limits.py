"""Nebius Token Factory Sandbox limits, encoded (source: Nebius Sandboxes team
email, 2026-09-29):

  * 128 MB per uploaded file;
  * 12 GB of filesystem changes per single operation.

The email gives no unit for "MB"/"GB". This module therefore enforces the
*smaller* reading with a margin, and says so:

  MAX_UPLOAD_BYTES = 120 MiB = 125,829,120 B
      128 MB decimal = 128,000,000 B is the smaller reading of the email;
      120 MiB leaves 2,170,880 B (1.7 %) of headroom below it. The archive
      size is measured exactly (len of the tar bytes), so the margin only has
      to cover unknowns in the server's accounting, not our own arithmetic.

What the repo's own evidence says about the unit (nothing new was probed):
  * `125,009,920` (the harness-v1.2 UPLOAD_CAP_BYTES) is NOT a Nebius number.
    It is the largest step (125 MB decimal + tar overhead) of RERUN's own
    pre-registered probe ladder 25/50/75/100/125 MB, which stopped there. It is
    119.2 MiB and was never a discovered ceiling.
  * The first probe uploaded a 150 MB (143 MiB) archive successfully (the failure
    came afterwards, inside the sandbox operation: ENOSPC). That is above both
    readings of "128 MB", so the endpoint did not reject it; it cannot settle the
    unit. Settling it needs a boundary probe (e.g. 128,000,000 / 134,217,728 B),
    which has not been run.

MAX_FS_DELTA_PER_OP_BYTES = 12 GB, read as decimal (the smaller reading). RERUN
cannot measure a per-operation filesystem delta from the SDK (it exposes no layer
size), so ops are checked against a conservative ESTIMATE (see `estimate_op_delta`)
before they run, and an actual quota failure is classified after the fact
(SANDBOX_QUOTA, phase 2). The estimates are labelled ESTIMATE wherever reported.

Routing rule (never a local upload of an over-limit repo): a repository whose
upload archive exceeds MAX_UPLOAD_BYTES is not sent. Only the small integrity
manifest is uploaded, and the sandbox downloads the pinned commit itself
(codeload.github.com tarball, no git needed in the image) and verifies every file
against the same git-blob manifest. If the source is not a GitHub repo at a full
commit SHA there is no download route and the run ends UPLOAD_TOO_LARGE.

Environment setup is split into separate sandbox operations so each is checked
against the delta limit on its own: (a) system packages, (b) torch, (c) the rest.
"""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass
from typing import Iterable, Literal

MIB = 1024 * 1024

MAX_UPLOAD_BYTES = 120 * MIB  # 125,829,120
MAX_FS_DELTA_PER_OP_BYTES = 12 * 10**9
# Estimates are coarse; an op is only allowed to run if its estimate is under this
# fraction of the limit.
FS_DELTA_SAFETY = 0.8

OpKind = Literal["system", "torch", "requirements"]
UploadMode = Literal["archive", "download", "refuse"]


# --- upload gate ------------------------------------------------------------------

@dataclass(frozen=True)
class DownloadSource:
    """A GitHub repository at a full commit SHA the sandbox can fetch itself."""

    owner: str
    repo: str
    sha: str

    _NAME = re.compile(r"^[A-Za-z0-9_.-]+$")
    _SHA = re.compile(r"^[0-9a-f]{40}$")

    def __post_init__(self) -> None:
        if not (self._NAME.match(self.owner) and self._NAME.match(self.repo) and self._SHA.match(self.sha)):
            raise ValueError(f"not a fetchable GitHub source: {self.owner!r}/{self.repo!r}@{self.sha!r}")

    @classmethod
    def from_repo_url(cls, repo_url: str, sha: str) -> "DownloadSource | None":
        m = re.match(r"^https://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?/?$", (repo_url or "").strip())
        if not m or not cls._SHA.match(sha or ""):
            return None
        return cls(m.group(1), m.group(2), sha)

    @property
    def tarball_url(self) -> str:
        return f"https://codeload.github.com/{self.owner}/{self.repo}/tar.gz/{self.sha}"

    def fetch_command(self) -> str:
        """Shell text for the sandbox. Every interpolated value was validated against
        a strict pattern in __post_init__ and is quoted regardless."""
        tmp = "/tmp/rerun_source.tar.gz"
        return (
            "python3 -c 'import sys, urllib.request; urllib.request.urlretrieve(sys.argv[1], sys.argv[2])' "
            f"{shlex.quote(self.tarball_url)} {tmp} "
            f"&& tar -xzf {tmp} --strip-components=1 --no-same-owner && rm -f {tmp}"
        )


@dataclass(frozen=True)
class UploadDecision:
    mode: UploadMode
    archive_bytes: int
    limit_bytes: int
    reason: str


def decide_upload(archive_bytes: int, source: DownloadSource | None, limit: int | None = None) -> UploadDecision:
    """Size gate. `archive` = upload as one tar; `download` = over the limit, the
    sandbox fetches the pinned commit; `refuse` = over the limit and no download
    route exists (verdict UPLOAD_TOO_LARGE, RERUN's limitation, not the repo's)."""
    limit = MAX_UPLOAD_BYTES if limit is None else limit
    if archive_bytes <= limit:
        return UploadDecision("archive", archive_bytes, limit, "within the per-file upload limit")
    if source is not None:
        return UploadDecision(
            "download", archive_bytes, limit,
            f"archive {archive_bytes:,} B > limit {limit:,} B: fetched inside the sandbox from {source.tarball_url}",
        )
    return UploadDecision(
        "refuse", archive_bytes, limit,
        f"archive {archive_bytes:,} B > limit {limit:,} B and the repository has no in-sandbox download route",
    )


# --- setup operations ----------------------------------------------------------------

@dataclass(frozen=True)
class SetupOp:
    kind: OpKind
    command: str
    est_delta_bytes: int  # ESTIMATE, not a measurement

    @property
    def within_limit(self) -> bool:
        return self.est_delta_bytes <= MAX_FS_DELTA_PER_OP_BYTES * FS_DELTA_SAFETY


class FsDeltaExceeded(RuntimeError):
    def __init__(self, op: SetupOp):
        self.op = op
        super().__init__(
            f"setup op {op.kind!r} is estimated at {op.est_delta_bytes:,} B of filesystem changes, over the "
            f"{int(MAX_FS_DELTA_PER_OP_BYTES * FS_DELTA_SAFETY):,} B planning ceiling "
            f"(limit {MAX_FS_DELTA_PER_OP_BYTES:,} B per operation): {op.command[:120]}"
        )


# ESTIMATE constants (bytes): installed sizes, deliberately on the high side.
_EST_APT_BASE = 60 * 10**6
_EST_APT_PER_PACKAGE = 150 * 10**6
_EST_TORCH_CPU = 1_000 * 10**6
_EST_TORCH_CUDA = 7_000 * 10**6  # torch + the nvidia-* wheels a default Linux pip resolves
_EST_PIP_PER_PACKAGE = 250 * 10**6
_EST_PIP_REQUIREMENTS_FILE = 3_000 * 10**6  # unknown contents: assume a large scientific stack

_TORCH_NAMES = {"torch", "torchvision", "torchaudio"}
_CUDA_INDEX = re.compile(r"whl/cu\d+")


def _canonical(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _spec_name(spec: str) -> str:
    return _canonical(re.split(r"[\[<>=!~ ;@]", spec, maxsplit=1)[0])


def _split_and(command: str) -> list[str] | None:
    """Top-level `&&` segments, or None if the command uses any other shell feature
    (so it is left whole and classified conservatively)."""
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars="&|;<>")
        lexer.whitespace_split = True
        lexer.commenters = "#"
        tokens = list(lexer)
    except ValueError:
        return None
    segments: list[list[str]] = [[]]
    for tok in tokens:
        if tok == "&&":
            segments.append([])
        elif set(tok) <= set("&|;<>"):
            return None
        else:
            segments[-1].append(tok)
    return [shlex.join(seg) for seg in segments if seg]


def _apt_packages(tokens: list[str]) -> int:
    return len([t for t in tokens[3:] if not t.startswith("-")]) if tokens[:2] == ["apt-get", "install"] else 0


def estimate_op_delta(kind: OpKind, command: str) -> int:
    """ESTIMATE of the filesystem bytes an op writes (see module docstring)."""
    tokens = shlex.split(command, comments=True)
    if kind == "system":
        n = sum(_apt_packages(shlex.split(seg)) for seg in (_split_and(command) or [command]))
        return _EST_APT_BASE + n * _EST_APT_PER_PACKAGE
    if kind == "torch":
        has_index = any(t.startswith(("--index-url", "-i")) for t in tokens)
        return _EST_TORCH_CUDA if any(_CUDA_INDEX.search(t) for t in tokens) or not has_index else _EST_TORCH_CPU
    if any(t in ("-r", "--requirement") or t.startswith("-r") and len(t) > 2 for t in tokens):
        return _EST_PIP_REQUIREMENTS_FILE
    specs = [t for t in tokens[2:] if not t.startswith("-")]
    return max(1, len(specs)) * _EST_PIP_PER_PACKAGE if tokens[:2] == ["pip", "install"] else _EST_PIP_REQUIREMENTS_FILE // 3


def _is_apt(segment: str) -> bool:
    tokens = shlex.split(segment)
    return bool(tokens) and tokens[0] in ("apt-get", "apt")


def _pip_install_tokens(command: str) -> list[str] | None:
    """Tokens of a plain `pip install ...` command, or None if the command uses any
    shell operator (an unquoted `>=` is a redirect, so it is rejected too)."""
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars="&|;<>")
        lexer.whitespace_split = True
        lexer.commenters = "#"
        tokens = list(lexer)
    except ValueError:
        return None
    if any(set(t) <= set("&|;<>") for t in tokens) or any("$(" in t or "`" in t for t in tokens):
        return None
    if tokens[:2] == ["python", "-m"] and tokens[2:4] == ["pip", "install"]:
        tokens = ["pip", "install", *tokens[4:]]
    return tokens if tokens[:2] == ["pip", "install"] else None


def split_setup_ops(steps: Iterable[str]) -> list[SetupOp]:
    """Order the planner's install steps into separate sandbox operations:
    (a) system packages, (b) torch, (c) everything else. Relative order inside a
    class is preserved. A `pip install` naming torch alongside other packages is
    split so torch is its own op; a command RERUN cannot parse safely (pipes,
    `;`, redirects) is never split and stays in (c)."""
    system: list[SetupOp] = []
    torch: list[SetupOp] = []
    rest: list[SetupOp] = []
    for step in steps:
        segments = _split_and(step)
        if segments and all(_is_apt(s) for s in segments):
            system.append(SetupOp("system", step, estimate_op_delta("system", step)))
            continue
        tokens = _pip_install_tokens(step)
        if tokens:
            options: list[str] = []
            torch_specs: list[str] = []
            other_specs: list[str] = []
            skip_value = False
            for tok in tokens[2:]:
                if skip_value:
                    options.append(tok)
                    skip_value = False
                elif tok.startswith("-"):
                    options.append(tok)
                    skip_value = tok in ("-r", "--requirement", "-c", "--constraint", "-i", "--index-url",
                                         "--extra-index-url", "-f", "--find-links", "-e", "--editable", "--target",
                                         "--prefix", "--root", "--platform", "--python-version", "--implementation")
                elif _spec_name(tok) in _TORCH_NAMES:
                    torch_specs.append(tok)
                else:
                    other_specs.append(tok)
            if torch_specs:
                torch_cmd = shlex.join(["pip", "install", *options, *torch_specs])
                torch.append(SetupOp("torch", torch_cmd, estimate_op_delta("torch", torch_cmd)))
                if other_specs or any(o in ("-r", "--requirement", "-e", "--editable") for o in options):
                    rest_cmd = shlex.join(["pip", "install", *options, *other_specs])
                    rest.append(SetupOp("requirements", rest_cmd, estimate_op_delta("requirements", rest_cmd)))
                continue
        rest.append(SetupOp("requirements", step, estimate_op_delta("requirements", step)))
    return [*system, *torch, *rest]


def check_ops(ops: Iterable[SetupOp]) -> list[SetupOp]:
    """Raise FsDeltaExceeded for the first op over the planning ceiling."""
    ops = list(ops)
    for op in ops:
        if not op.within_limit:
            raise FsDeltaExceeded(op)
    return ops
