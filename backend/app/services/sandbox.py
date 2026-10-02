"""Sandbox lifecycle (RERUN directive §3 must-have #3, Phase 0).

Wraps the real Nebius Token Factory Sandboxes SDK: `pip install contree-sdk`
(PyPI), importable as `contree_sdk`. Every sandbox run is wrapped in
try/finally so a failure never leaks a Nebius resource, per §2.6.

Ground truth for this module was read directly from the **installed**
`contree_sdk` v0.3.6 source (`.venv/Lib/site-packages/contree_sdk/...`),
not guessed and not taken solely from the (incomplete, beta) hosted docs —
see DECISIONS.md for exactly which source files were read. Key facts that
shape this design:

  - `image.run(..., disposable=True).wait()` is the only execution
    primitive, and `disposable=True` is the SDK's own default: the
    resulting image (and its backing compute) is discarded the moment
    that run completes. There is no separate `sandbox.destroy()` call in
    this SDK version — running the *last* step of a chain with
    `disposable=True` **is** the destroy step. §2.6 ("every sandbox
    session must be destroyed after use") is satisfied by never letting a
    `disposable=False` image survive past this module's `finally` block.
  - Chaining steps (upload files -> install deps -> run entrypoint, each
    against the *result* of the previous step) requires `disposable=False`
    on every non-final step, or the backend discards that intermediate
    image before the next step can reference it. Every such retained image
    is explicitly disposed of in `finally` via a trivial `disposable=True`
    no-op run, so a mid-chain exception can never leave a resource behind.
  - `ContreeResult.cost` (a float, USD) comes back from every completed
    step and is the real number `cost_guard.CostGuard.record_spend()`
    should be fed — not an estimate.

**Not yet live-verified.** Phase 0's actual gate (3 real sandboxes created
and destroyed, logs shown to a human) requires a real `NEBIUS_API_KEY` that
is not present in this environment. This module is written and structured
against the real SDK's real API, but has only been exercised by this
file's own unit tests against duck-typed stand-ins for `ContreeResult` —
see `test_sandbox.py`. Do not report Phase 0 as done until it has actually
run against the live API.
"""

from __future__ import annotations

import hashlib
import inspect
import io
import json
import tarfile
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable, Iterable, Protocol

from contree_sdk import ContreeSync
from contree_sdk.auth import IAMAuth
from contree_sdk.config import ContreeConfig
from contree_sdk.sdk.exceptions import ContreeError, OperationTimedOutError
from contree_sdk.sdk.exceptions.api import ApiStatusCodeError, ApiTimeoutError, ContreeTransportError

from app.services import runner_env, sandbox_limits, timeouts
from app.services.infra import InfraError, retry_call


class SandboxError(RuntimeError):
    """A sandbox run could not produce a result for a reason that is about
    the run itself (the wall-clock ceiling). External API failures are
    SandboxInfraError instead (harness-v1.1)."""


class SandboxCredentialsError(SandboxError):
    pass


class SandboxTimeoutError(SandboxError):
    """A step reached the operation's time limit (the configured wall clock, or the budget-derived limit the
    orchestrator passes as the wall clock) and the sandbox killed it (harness-v1.3.3, D-7/D-8). The API returns no
    cost for a killed step, so this carries what IS known: the cost of the steps that completed, and how long the
    killed step ran. The message always contains "wall clock" (the orchestrator's TIMEOUT mapping keys on it)."""

    def __init__(self, message: str, *, command: str = "", completed_cost_usd: float = 0.0, killed_seconds: float = 0.0,
                 completed_steps: tuple = (), via: str = "client_wait_timeout", sandbox_id: str | None = None):
        super().__init__(message)
        self.command = command
        # Everything the API reported for completed steps; when the SERVER stopped the step and returned its result
        # (via="server_result_timed_out"), the killed step's own measured cost is included and `killed_seconds` is 0 (nothing to estimate).
        self.completed_cost_usd = completed_cost_usd
        self.killed_seconds = killed_seconds
        self.completed_steps = completed_steps
        self.via = via
        self.sandbox_id = sandbox_id


class SandboxInfraError(InfraError):
    """The Nebius sandbox API failed (timeouts, transport, 5xx, 403, …)."""

    def __init__(self, message: str, **kwargs):
        super().__init__("sandbox", message, **kwargs)


class UploadTooLargeError(RuntimeError):
    """The upload archive exceeds UPLOAD_CAP_BYTES — a pre-declared harness
    limitation (harness-v1.2), checked before any network call. Mapped to
    verdict UPLOAD_TOO_LARGE, excluded from every rate, reported separately."""

    def __init__(self, archive_bytes: int, cap_bytes: int):
        self.archive_bytes = archive_bytes
        self.cap_bytes = cap_bytes
        super().__init__(f"upload archive is {archive_bytes:,} bytes; the pre-declared cap is {cap_bytes:,} bytes")


# Largest upload archive RERUN sends: 120 MiB, from the Nebius Sandboxes team's
# documented 128 MB per-file limit (email 2026-09-29) with a margin; see
# sandbox_limits.py for the unit reasoning. Harness-v1.2 used 125,009,920 B, the top
# step of RERUN's own probe ladder (not a Nebius number); superseded in harness-v1.3.
# Over the limit the repository is fetched inside the sandbox instead
# (`download_source`), and only without such a route is it UploadTooLargeError.
UPLOAD_CAP_BYTES: int | None = sandbox_limits.MAX_UPLOAD_BYTES


class UploadIntegrityError(RuntimeError):
    """The files extracted inside the sandbox are not the files uploaded
    (post-extraction check). Mapped to INVALID_HARNESS by the orchestrator."""

    def __init__(self, message: str, stderr: str = "", completed_cost_usd: float = 0.0, completed_steps: tuple = ()):
        self.stderr = stderr
        # harness-v1.4.0-rc: the overlay check runs AFTER the setup steps, so what they cost is spend and is carried here.
        self.completed_cost_usd = completed_cost_usd
        self.completed_steps = completed_steps
        super().__init__(message)


# --- One-archive upload (harness-v1.1) ----------------------------------------
# contree_sdk's apply_files uploads every file as its own POST, all at once
# (`gather(*(_upload_file(i) for i in files))`, sdk/objects/image_like/_base.py)
# — the corpus-v1 batch's upload timeouts (KernelGCN, knnlm). The repo is now
# sent as ONE tar; the first sandbox step extracts it and verifies every file
# against a manifest of (git blob SHA-1 of the exact bytes sent, file mode),
# then removes RERUN's own files. Modes come from the pinned commit's git tree
# (100755 -> 0755, 100644 -> 0644; the SDK's per-file upload made everything
# 0644, so `./run.sh` could never run); uid/gid 0.

UPLOAD_ARCHIVE = ".rerun-upload.tar"
UPLOAD_DIR = ".rerun_upload_v1"
UPLOAD_MISMATCH_EXIT = 97
_GIT_MODE_TO_FILE_MODE = {"100755": 0o755, "100644": 0o644}
_DEFAULT_FILE_MODE = 0o644

# Python 3.6-compatible (the oldest supported sandbox image): no walrus.
# Mode check = the executable bit only, which is all git tracks (harness-v1.3.2): GitHub tarballs and any
# umask-affected extraction give 0664/0775 for git's 100644/100755, and comparing the full mode failed every
# file of the first download-route run (attempt 1, entry 2: "374 file(s) ... mode 664 != 0644", content equal).
_VERIFY_SCRIPT = f"""import hashlib, json, os, sys
m = json.load(open("{UPLOAD_DIR}/manifest.json"))
try:
    overlay = json.load(open("{UPLOAD_DIR}/overlay.json"))
except (IOError, OSError, ValueError):
    overlay = {{}}
bad = []
for p in sorted(m):
    sha, mode = m[p]
    try:
        d = open(p, "rb").read()
        st = os.stat(p).st_mode & 0o777
    except OSError:
        bad.append(p + " (missing)")
        continue
    if hashlib.sha1(b"blob " + str(len(d)).encode() + b"\\0" + d).hexdigest() != sha:
        bad.append(p + " (content)")
    elif bool(st & 0o111) != bool(int(mode, 8) & 0o111):
        bad.append(p + " (mode %o != %s)" % (st, mode))
if bad:
    sys.stderr.write("RERUN_UPLOAD_MISMATCH %d file(s): %s\\n" % (len(bad), " ".join(bad[:20])))
    sys.exit({UPLOAD_MISMATCH_EXIT})
print("RERUN_UPLOAD_VERIFIED %d file(s) (%d original against the committed blob, %d overlay against the post-patch blob)"
      % (len(m), len(m) - len(overlay), len(overlay)))
"""

# The download route's fetch step (harness-v1.3.2). Primary: `git clone --filter=blob:none` + `git checkout <sha>`
# inside the sandbox, then `git rev-parse HEAD == sha`, an empty `git status --porcelain`, and
# `git submodule update --init` if .gitmodules exists; git is installed with apt if the image lacks it.
# Fallback (git unobtainable, e.g. the archived Debian bullseye repos of python:3.6-slim, or any git failure):
# the GitHub tarball. Either way verify.py then checks every file against the git-blob manifest. Python 3.6 code.
_FETCH_SCRIPT = f"""import json, os, shutil, subprocess, sys
D = "{UPLOAD_DIR}"
src = json.load(open(D + "/source.json"))
sha = src["sha"]
url = "https://github.com/%s/%s.git" % (src["owner"], src["repo"])
work = D + "/src"


def sh(args, cwd=None):
    p = subprocess.run(args, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True,
                       env=dict(os.environ, DEBIAN_FRONTEND="noninteractive", GIT_TERMINAL_PROMPT="0"))
    if p.returncode != 0:
        raise RuntimeError("%s -> exit %d: %s" % (" ".join(args[:4]), p.returncode, p.stdout[-400:]))
    return p.stdout.strip()


def via_git():
    if not shutil.which("git"):
        sh(["apt-get", "update", "-qq"])
        sh(["apt-get", "install", "-y", "-qq", "--no-install-recommends", "git", "ca-certificates"])
    sh(["git", "clone", "-q", "--filter=blob:none", "--no-checkout", url, work])
    sh(["git", "checkout", "-q", "--detach", sha], cwd=work)
    head = sh(["git", "rev-parse", "HEAD"], cwd=work)
    if head != sha:
        raise RuntimeError("HEAD %s != pinned %s" % (head, sha))
    if os.path.exists(work + "/.gitmodules"):
        sh(["git", "submodule", "update", "--init", "--recursive"], cwd=work)
    dirty = sh(["git", "status", "--porcelain"], cwd=work)
    if dirty:
        raise RuntimeError("git status not clean: " + dirty[:400])
    shutil.rmtree(work + "/.git")
    # cp -a MERGES into directories that already exist (the sandbox cwd is "/", which has /media, /opt, ...);
    # shutil.move would nest media/ inside /media (found live 2026-09-30: media/teaser.gif "missing").
    sh(["cp", "-a", work + "/.", "."])
    shutil.rmtree(work)


def via_tarball():
    sh(["python3", "-c", "import sys, urllib.request; urllib.request.urlretrieve(sys.argv[1], sys.argv[2])",
        "https://codeload.github.com/%s/%s/tar.gz/%s" % (src["owner"], src["repo"], sha), "/tmp/rerun_source.tar.gz"])
    sh(["tar", "-xzf", "/tmp/rerun_source.tar.gz", "--strip-components=1", "--no-same-owner"])
    os.remove("/tmp/rerun_source.tar.gz")


try:
    via_git()
    route = "git"
except Exception as exc:
    sys.stderr.write("RERUN_FETCH_GIT_FAILED: %s\\n" % str(exc)[:600])
    shutil.rmtree(work, ignore_errors=True)
    via_tarball()
    route = "tarball (git failed: %s)" % str(exc)[:200].replace("\\n", " ")
# Outside the repo tree: for the live verification and debugging, invisible to the repo.
open("/tmp/rerun_fetch_route", "w").write("%s %s" % (route, sha))
print("RERUN_FETCH %s %s" % (route, sha))
"""

# harness-v1.3.4 (D-20): on the download route the sandbox fetches the ORIGINAL tree, so a file patched by a gate-approved repair
# would fail the manifest check (found live: corpus-v2 entry 8, `utils.py (content)`, exit 97, INVALID_HARNESS). The manifest-only
# archive therefore also carries an OVERLAY: every patched/added file's post-patch bytes under `<UPLOAD_DIR>/overlay/<path>`, listed in
# `overlay.json` (path -> [git blob SHA-1 of the post-patch bytes, mode]). overlay.py copies them over the fetched tree AFTER the fetch
# and BEFORE verify.py; verify.py checks originals against their committed blobs and overlay files against their post-patch blobs (the
# manifest holds the post-patch hash for them, and reports them as overlay). Python 3.6 code.
OVERLAY_DIR = f"{UPLOAD_DIR}/overlay"
_OVERLAY_SCRIPT = f"""import json, os, shutil, sys
D = "{UPLOAD_DIR}"
overlay = json.load(open(D + "/overlay.json"))
for p in sorted(overlay):
    src = D + "/overlay/" + p
    if not os.path.isfile(src):
        sys.stderr.write("RERUN_OVERLAY_MISSING %s\\n" % p)
        sys.exit({UPLOAD_MISMATCH_EXIT})
    d = os.path.dirname(p)
    if d and not os.path.isdir(d):
        os.makedirs(d)
    shutil.copyfile(src, p)
    os.chmod(p, int(overlay[p][1], 8))
print("RERUN_OVERLAY_APPLIED %d file(s)" % len(overlay))
"""

# The archive is deleted right after extraction, BEFORE the manifest check
# (harness-v1.2): the corpus-v1 probe ran out of sandbox storage at 150 MB with
# archive + extracted tree both on disk. The check reads only the extracted tree.
EXTRACT_COMMAND = (
    f"tar -xpf {UPLOAD_ARCHIVE} --no-same-owner && rm -f {UPLOAD_ARCHIVE} "
    f"&& python3 {UPLOAD_DIR}/verify.py && rm -rf {UPLOAD_DIR}"
)


def extract_command_for(source: "sandbox_limits.DownloadSource | None") -> str:
    """The RERUN-owned first step: unpack the tar (and, on the download route, fetch
    the pinned source with fetch.py), verify against the manifest, then remove RERUN's files."""
    if source is None:
        return EXTRACT_COMMAND
    return (
        f"tar -xpf {UPLOAD_ARCHIVE} --no-same-owner && rm -f {UPLOAD_ARCHIVE} "
        f"&& python3 {UPLOAD_DIR}/fetch.py && python3 {UPLOAD_DIR}/overlay.py && python3 {UPLOAD_DIR}/verify.py && rm -rf {UPLOAD_DIR}"
    )


def _blob_sha1(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def file_mode_for(git_mode: str | None) -> int:
    return _GIT_MODE_TO_FILE_MODE.get(git_mode or "", _DEFAULT_FILE_MODE)


def build_upload_archive(
    upload_files: dict[str, str | Path | bytes],
    modes: dict[str, str] | None = None,
    mtime: float | None = None,
    manifest_only: bool = False,
    download_source: "sandbox_limits.DownloadSource | None" = None,
    overlay_paths: frozenset[str] = frozenset(),
) -> tuple[bytes, dict[str, list[str]]]:
    """(tar bytes, manifest path -> [git blob SHA-1 of the bytes put in the
    tar, octal file mode]). `modes` maps path -> git mode ("100755"/"100644").
    `manifest_only` (download route): the tar carries only the manifest and the
    verifier; the files themselves are fetched inside the sandbox and checked
    against the same manifest. `overlay_paths` (download route, harness-v1.3.4): the
    files a gate-approved patch changed; their post-patch bytes travel in the tar
    under the overlay directory and replace the fetched originals before the check."""
    mtime = time.time() if mtime is None else mtime
    modes = modes or {}
    manifest: dict[str, list[str]] = {}
    overlay: dict[str, list[str]] = {}
    overlay_norm = {p.replace("\\", "/") for p in overlay_paths}
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w", format=tarfile.PAX_FORMAT) as tar:

        def _add(name: str, data: bytes, mode: int = _DEFAULT_FILE_MODE) -> None:
            info = tarfile.TarInfo(name)
            info.size, info.mode, info.mtime, info.uid, info.gid = len(data), mode, int(mtime), 0, 0
            tar.addfile(info, io.BytesIO(data))

        for rel in sorted(upload_files):
            source = upload_files[rel]
            data = source if isinstance(source, bytes) else Path(source).read_bytes()
            name = rel.replace("\\", "/")
            if name.startswith("/") or ".." in name.split("/") or name.split("/")[0] in (UPLOAD_DIR, UPLOAD_ARCHIVE):
                raise UploadIntegrityError(f"refusing to archive unsafe or reserved path {rel!r}")
            mode = file_mode_for(modes.get(rel))
            if not manifest_only:
                _add(name, data, mode)
            elif name in overlay_norm:
                _add(f"{OVERLAY_DIR}/{name}", data, mode)
                overlay[name] = [_blob_sha1(data), f"{mode:04o}"]
            manifest[name] = [_blob_sha1(data), f"{mode:04o}"]
        if manifest_only:
            missing_overlay = sorted(overlay_norm - set(overlay))
            if missing_overlay:
                raise UploadIntegrityError(f"overlay path(s) not among the upload files: {missing_overlay[:5]}")
        _add(f"{UPLOAD_DIR}/manifest.json", json.dumps(manifest, sort_keys=True).encode("utf-8"))
        _add(f"{UPLOAD_DIR}/verify.py", _VERIFY_SCRIPT.encode("utf-8"))
        if manifest_only:
            if download_source is None:
                raise UploadIntegrityError("a manifest-only archive needs its download source")
            _add(f"{UPLOAD_DIR}/fetch.py", _FETCH_SCRIPT.encode("utf-8"))
            _add(f"{UPLOAD_DIR}/overlay.py", _OVERLAY_SCRIPT.encode("utf-8"))
            _add(f"{UPLOAD_DIR}/overlay.json", json.dumps(overlay, sort_keys=True).encode("utf-8"))
            _add(f"{UPLOAD_DIR}/source.json", json.dumps(
                {"owner": download_source.owner, "repo": download_source.repo, "sha": download_source.sha}, sort_keys=True).encode("utf-8"))
    return buffer.getvalue(), manifest


def _is_transient_sandbox_error(exc: BaseException) -> bool:
    if isinstance(exc, (ApiTimeoutError, ContreeTransportError, TimeoutError, ConnectionError)):
        return True
    if isinstance(exc, ApiStatusCodeError):
        status = exc.status or 0
        return status == 429 or 500 <= status < 600
    return False


def _is_external_sandbox_error(exc: BaseException) -> bool:
    # Every other Contree error except our own wall-clock ceiling
    # (OperationTimedOutError -> TIMEOUT, a result about the run).
    return isinstance(exc, ContreeError) and not isinstance(exc, OperationTimedOutError)


class _ResultLike(Protocol):
    exit_code: int
    stdout: str | None
    stderr: str | None

    @property
    def elapsed_time(self): ...

    @property
    def cost(self) -> float: ...


# harness-v1.4.3-rc (D-41): the SDK cuts each output stream of a run at `ContreeConfig.default_truncate_output_at`, 65,535 bytes by default, and
# keeps the START of the stream: everything printed after that point is lost, the traceback and the evidence block included. Found by the
# probe of 2026-10-02 (corpus-v2 #3: 400,939 bytes of stderr, 65,535 returned, the raw API result's `truncated` flag set, a CUDA error behind
# the cut; runs/sandbox_verification/d41-probe). Every client that runs a command whose output is read now asks for the limit below (the cleanup and release runs
# discard theirs); the flag is read per stream
# and stored with the step; a stream that still exceeds the limit is labelled, never read as "printed no error". 4 MiB, not more: the classifier scans a
# failed run's streams several times (measured offline: 5.6 s for classify + has_actionable_error on 8 MiB of ordinary log lines, 0.3 s on 8 MiB of progress ticks).
OUTPUT_LIMIT_BYTES = 4 * 1024 * 1024


@dataclass(frozen=True)
class StepResult:
    command: str
    exit_code: int
    stdout: str
    stderr: str
    elapsed_seconds: float
    cost_usd: float
    # harness-v1.3.2: which kind of step this was. `runner_setup` = RERUN's own environment ops (the torch install
    # and the exec-stack fix), `repo_install` = the repo's install commands, `repo_run` = the repo's command. A failure
    # in `runner_setup` is never the repository's fault (error_chain.attribute keys on this first).
    phase: str = "repo_run"
    # harness-v1.3.3: the sandbox itself stopped this step at its time limit (`state.timed_out` of the API result, which the SDK does not
    # surface). Found live 2026-09-30: a 300 s step given a 25 s limit came back in ~28 s as a NORMAL result, not as an exception.
    timed_out: bool = False
    # harness-v1.4.3-rc (D-41): the API's own `truncated` flag of each stream (raw result `stdout.truncated` / `stderr.truncated`; the SDK's
    # `ContreeResult.truncated` is their OR and nothing else reads them). False for a duck-typed fake that carries no raw result.
    stdout_truncated: bool = False
    stderr_truncated: bool = False
    # harness-v1.4.3-rc (D-40): the API's own peak-memory figure for the step (`resources.max_rss` of the raw result), as returned: its unit is not documented, so it is
    # stored and never converted. None for a duck-typed fake that carries no raw result.
    max_rss: int | None = None

    @property
    def truncated(self) -> bool:
        return self.stdout_truncated or self.stderr_truncated

    def streams(self) -> dict:
        """What the record stores about this step's output: for each stream the size and sha-256 of what the SDK returned and whether the API
        said it cut the stream. A stream with `truncated` true is the START of a longer one (the tail was not returned)."""
        def one(text: str, truncated: bool) -> dict:
            data = text.encode("utf-8")
            return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(), "truncated": truncated}

        return {"limit_bytes": OUTPUT_LIMIT_BYTES, "stdout": one(self.stdout, self.stdout_truncated), "stderr": one(self.stderr, self.stderr_truncated)}


@dataclass(frozen=True)
class SandboxRunResult:
    steps: tuple[StepResult, ...]
    # §8 S2: "Live sandbox badge (id, elapsed time, wall-clock remaining)".
    # The real contree_sdk image object carries a `.uuid` (verified against
    # installed source) once a step has actually run — captured here so the
    # frontend can show a real identifier, not a fabricated one. `None` for
    # any fake/duck-typed result that doesn't set it (all existing tests),
    # so this stays optional rather than a breaking required field.
    sandbox_id: str | None = None
    # Seconds spent uploading the archive (apply_files) and running RERUN's
    # extract+verify step; None when there was no upload (and for fakes).
    upload_seconds: float | None = None
    extract_seconds: float | None = None
    # harness-v1.4.0-rc (D-23), set only by a checkpoint operation (`checkpoint=` given); defaults keep every older caller unchanged.
    # `layers`: (setup commands contained, image id) of every image this operation KEPT after the tree and after each setup command
    # it ran, reopenable by id; `branch_from_image`: the image the operation started from (None = fresh from the base image);
    # `result_image`: the kept image the command ran on (tree + patch + environment), when asked for; `rerun_steps`: RERUN's own
    # steps (tree extract/verify, patch overlay) with their measured seconds and cost, which are NOT in `steps`;
    # `setup_commands`: every setup command of the operation's environment; `ran_setup`: the ones this operation actually ran.
    layers: tuple[tuple[tuple[str, ...], str], ...] = ()
    branch_from_image: str | None = None
    result_image: str | None = None
    rerun_steps: tuple[StepResult, ...] = ()
    setup_commands: tuple[str, ...] = ()
    ran_setup: tuple[str, ...] = ()
    # harness-v1.4.3-rc (D-42): the command the plan of this operation ran (before the smoke launcher, the exit wrapper and the evidence suffix are put around it), set by
    # the caller: a model's environment delta may change a plan's command, so what the sustained-run line re-executes is what THIS run executed, not the corpus entry's text.
    base_command: str = ""

    @property
    def final(self) -> StepResult:
        if not self.steps:
            raise SandboxError("sandbox run produced no steps")
        return self.steps[-1]

    @property
    def total_cost_usd(self) -> float:
        # The tree-extract cost is folded into steps[0] (harness-v1.1); RERUN's other own steps (the patch overlay) are added here.
        return sum(s.cost_usd for s in self.steps) + sum(s.cost_usd for s in self.rerun_steps if s.phase != "rerun_extract")

    @property
    def kept_images(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys([*(image for _, image in self.layers), *((self.result_image,) if self.result_image else ())]))

    @property
    def succeeded(self) -> bool:
        return self.final.exit_code == 0


def _text(value) -> str:
    """A returned stream as text. harness-v1.4.3-rc (D-41): the SDK decodes a stream with a strict `.decode()` when it is asked for text, which raises inside `.wait()` (the finished
    step's result and cost are lost) when the API's cut falls inside a multi-byte character; every real run is therefore asked for bytes (`_byte_streams`) and decoded here."""
    if isinstance(value, (bytes, bytearray)):
        return bytes(value).decode("utf-8", "replace")
    return value or ""


def _byte_streams(image) -> dict:
    """`stdout=bytes, stderr=bytes` for `image.run(...)` when the SDK's `run` takes them (the real one does; a test double with the older signature does not)."""
    try:
        params = inspect.signature(image.run).parameters
    except (TypeError, ValueError):
        return {}
    return {"stdout": bytes, "stderr": bytes} if "stdout" in params and "stderr" in params else {}


def step_result_from_image(image, command: str, phase: str = "repo_run") -> StepResult:
    """Map a completed contree_sdk image's `.result` onto our own
    dataclass, so the rest of the codebase never touches the SDK's types
    directly. `image.result` matches `ContreeResult` (see module
    docstring) — this function is exercised in tests against a duck-typed
    stand-in exposing the same shape, since a live image can't be
    constructed without hitting the real API.
    """
    result: _ResultLike = image.result
    return StepResult(
        command=command,
        exit_code=result.exit_code,
        stdout=_text(result.stdout),
        stderr=_text(result.stderr),
        elapsed_seconds=result.elapsed_time.total_seconds(),
        cost_usd=result.cost,
        phase=phase,
        timed_out=_server_timed_out(result),
        stdout_truncated=_stream_truncated(result, "stdout"),
        stderr_truncated=_stream_truncated(result, "stderr"),
        max_rss=_max_rss(result),
    )


def _server_timed_out(result) -> bool:
    """`state.timed_out` of the raw API result behind a ContreeResult (False for duck-typed fakes that have none)."""
    state = getattr(getattr(getattr(result, "_raw", None), "result", None), "state", None)
    return getattr(state, "timed_out", False) is True


def _max_rss(result) -> int | None:
    """`resources.max_rss` of the raw API result behind a ContreeResult, as returned (None when the result carries none). harness-v1.4.3-rc (D-40)."""
    value = getattr(getattr(getattr(getattr(result, "_raw", None), "result", None), "resources", None), "max_rss", None)
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _stream_truncated(result, stream: str) -> bool:
    """`truncated` of one stream of the raw API result behind a ContreeResult (False for duck-typed fakes that have none). harness-v1.4.3-rc (D-41)."""
    description = getattr(getattr(getattr(result, "_raw", None), "result", None), stream, None)
    return getattr(description, "truncated", False) is True




# --- Checkpoint operations (harness-v1.4.0-rc, D-23) ----------------------------------------------------------
# Until harness-v1.3.4 every operation rebuilt the environment from the base image (upload, extract, apt, torch, pip, ...) and
# disposed of every image at its end, so each re-execution paid the torch install again (corpus-v2 entries 8 and 11 ended COST_CAP
# inside or after a repeated install). Token Factory Sandboxes snapshot the filesystem after every non-disposable run and an image
# can be reopened by its UUID (contree_sdk `images.use(uuid)`). A checkpoint operation therefore:
#   - KEEPS the image after the pristine tree and after each setup command it runs ("layers"; the caller records their ids);
#   - starts, when the caller names one, from such a layer and runs only the setup commands the layer does not already contain;
#   - applies the repository changes (gate-approved patches) as a small overlay archive on top, after the setup commands, or right
#     after the tree when a setup command reads a patched file (the caller decides: `branch_before_setup`);
#   - can keep the image the command runs on (`keep_result`): the adjudicated winner's image becomes the next environment image.
# The command itself always runs disposable: its own side effects never enter an environment image.
# The overlay replaces the harness-v1.3.4 D-20 path in the live flow: the tree in a layer is always the committed one (the caller
# uploads the pristine files, or the download route fetches them), and every patched file travels in the overlay, whatever the repo size.

BRANCH_ARCHIVE = ".rerun-branch.tar"
BRANCH_DIR = ".rerun_branch_v1"

# Python 3.6-compatible: writes every patched file, removes every deleted one, then checks each written file's git blob SHA-1.
_BRANCH_SCRIPT = f"""import hashlib, json, os, shutil, sys
D = "{BRANCH_DIR}"
spec = json.load(open(D + "/branch.json"))
bad = []
for p in sorted(spec["files"]):
    sha, mode = spec["files"][p]
    d = os.path.dirname(p)
    if d and not os.path.isdir(d):
        os.makedirs(d)
    shutil.copyfile(D + "/files/" + p, p)
    os.chmod(p, int(mode, 8))
    data = open(p, "rb").read()
    if hashlib.sha1(b"blob " + str(len(data)).encode() + b"\\0" + data).hexdigest() != sha:
        bad.append(p)
for p in spec["deleted"]:
    if os.path.lexists(p):
        os.remove(p)
    if os.path.lexists(p):
        bad.append(p + " (not deleted)")
if bad:
    sys.stderr.write("RERUN_BRANCH_MISMATCH %d file(s): %s\\n" % (len(bad), " ".join(bad[:20])))
    sys.exit({UPLOAD_MISMATCH_EXIT})
print("RERUN_BRANCH_APPLIED %d file(s) written, %d deleted" % (len(spec["files"]), len(spec["deleted"])))
"""

BRANCH_COMMAND = (
    f"tar -xpf {BRANCH_ARCHIVE} --no-same-owner && rm -f {BRANCH_ARCHIVE} "
    f"&& python3 {BRANCH_DIR}/apply.py && rm -rf {BRANCH_DIR}"
)


@dataclass(frozen=True)
class Checkpoint:
    """How one operation uses and produces reusable images (harness-v1.4.0-rc)."""

    # The layer to start from (an image id a previous operation kept) and the setup commands it already contains, which must be a
    # prefix of this operation's setup commands. None = start fresh from the base image (upload or fetch the pristine tree).
    start_image: str | None = None
    start_ops: tuple[str, ...] = ()
    # Keep the image after the tree (fresh operations) and after every setup command this operation runs.
    keep_layers: bool = True
    # The repository changes to put on top: path -> (bytes, octal mode int); and the paths a patch deleted.
    branch_files: tuple[tuple[str, bytes, int], ...] = ()
    branch_deleted: tuple[str, ...] = ()
    # Apply the changes right after the tree instead of after the setup commands (a setup command reads a patched file). The caller
    # must then not ask to keep layers: they would contain a patched tree.
    branch_before_setup: bool = False
    # Keep the image the command runs on (tree + changes + environment).
    keep_result: bool = False

    @property
    def has_branch(self) -> bool:
        return bool(self.branch_files or self.branch_deleted)


def build_branch_archive(files: Iterable[tuple[str, bytes, int]], deleted: Iterable[str] = ()) -> bytes:
    """The overlay tar: every changed file under BRANCH_DIR/files/<path>, branch.json (path -> [git blob SHA-1, mode]) and apply.py."""
    spec: dict = {"files": {}, "deleted": []}
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w", format=tarfile.PAX_FORMAT) as tar:

        def _add(name: str, data: bytes, mode: int = _DEFAULT_FILE_MODE) -> None:
            info = tarfile.TarInfo(name)
            info.size, info.mode, info.mtime, info.uid, info.gid = len(data), mode, 0, 0, 0
            tar.addfile(info, io.BytesIO(data))

        for path, data, mode in sorted(files):
            name = path.replace("\\", "/")
            if name.startswith("/") or ".." in name.split("/") or name.split("/")[0] in (UPLOAD_DIR, BRANCH_DIR):
                raise UploadIntegrityError(f"refusing to put unsafe or reserved path {path!r} in the overlay")
            _add(f"{BRANCH_DIR}/files/{name}", data, mode)
            spec["files"][name] = [_blob_sha1(data), f"{mode:04o}"]
        for path in sorted(set(deleted)):
            name = path.replace("\\", "/")
            if name.startswith("/") or ".." in name.split("/"):
                raise UploadIntegrityError(f"refusing to delete unsafe path {path!r}")
            spec["deleted"].append(name)
        _add(f"{BRANCH_DIR}/branch.json", json.dumps(spec, sort_keys=True).encode("utf-8"))
        _add(f"{BRANCH_DIR}/apply.py", _BRANCH_SCRIPT.encode("utf-8"))
    return buffer.getvalue()


def setup_commands(install_commands: Iterable[str], torch_setup: "runner_env.TorchSetup | None" = None,
                   runner_extras: Iterable[str] = ()) -> tuple[str, ...]:
    """Every setup command of an environment, in the order the sandbox runs them: the build plan's steps split into system packages,
    the runner's torch install, the rest (sandbox_limits.split_setup_ops), then RERUN's own runner hooks (runner_hooks). Two
    operations with the same base image whose lists share a prefix can share the layer that prefix produced."""
    runner_torch = (torch_setup.install_command, torch_setup.fix_command) if torch_setup else ()
    return (*(op.command for op in sandbox_limits.split_setup_ops(install_commands, runner_torch)), *runner_extras)


def run_build_and_execute(
    *,
    api_key: str,
    project_id: str = "",
    base_image: str,
    install_commands: Iterable[str],
    execute_command: str,
    wall_clock_seconds: float,
    upload_files: dict[str, str | Path | bytes] | None = None,
    file_modes: dict[str, str] | None = None,
    download_source: "sandbox_limits.DownloadSource | None" = None,
    torch_setup: "runner_env.TorchSetup | None" = None,
    overlay_paths: frozenset[str] = frozenset(),
    checkpoint: Checkpoint | None = None,
    runner_extras: tuple[str, ...] = (),
) -> SandboxRunResult:
    """Run the full build-plan pipeline in an isolated Token Factory
    Sandbox: reference/import the base image, upload the repo, run each
    install command, then the execute command — stopping at the first
    non-zero exit code. Always tears down sandbox resources, success or
    failure (§2.6): every intermediate retained (`disposable=False`) image
    is disposed of in `finally`, and the final step always runs with
    `disposable=True`. harness-v1.4.0-rc: with `checkpoint`, the images it
    names as kept are NOT disposed of (they are reused by later operations
    of the same entry and recorded), see `Checkpoint`.

    `project_id` is passed explicitly into `IAMAuth` rather than left to
    `ContreeSync(token=api_key)`'s shorthand. Found live during this
    session's Nebius integration audit: that shorthand only overrides
    `token`, leaving `IAMAuth.project_id` at its dataclass default — the
    literal string `"NEBIUS_PROJECT_ID"` (an env-var *name*, not a value).
    `Auth.resolve()` (contree_sdk/auth.py) only turns that into a real
    project id if an OS environment variable literally named
    NEBIUS_PROJECT_ID exists — true under docker-compose's `env_file:`
    (which does inject real OS env vars), false when running via bare
    uvicorn/pytest, since this codebase loads `.env` through
    pydantic-settings only and never calls `os.environ`/`load_dotenv`.
    Passing project_id explicitly makes the sandbox's `Project` auth header
    correct regardless of how the process was started.
    """
    if not api_key:
        raise SandboxCredentialsError(
            "NEBIUS_API_KEY is not set — cannot open a Token Factory Sandbox. "
            "Populate .env from .env.example before running a real sandbox."
        )

    # Setup is split into separate operations (system packages, torch, the rest),
    # each checked against the per-operation filesystem-delta limit.
    runner_torch = (torch_setup.install_command, torch_setup.fix_command) if torch_setup else ()
    setup = sandbox_limits.check_ops(sandbox_limits.split_setup_ops(install_commands, runner_torch))
    all_setup = (*(op.command for op in setup), *runner_extras)
    if checkpoint is not None and checkpoint.start_image is not None:
        if tuple(all_setup[: len(checkpoint.start_ops)]) != tuple(checkpoint.start_ops):
            raise SandboxError("checkpoint start image does not contain a prefix of this operation's setup commands")
        to_run = all_setup[len(checkpoint.start_ops):]
    else:
        to_run = all_setup
    commands = [*to_run, execute_command]
    if not [c for c in commands if c]:
        raise SandboxError("no commands to run: install_commands and execute_command are both empty")
    archive, extract_command = None, EXTRACT_COMMAND
    if upload_files and not (checkpoint is not None and checkpoint.start_image is not None):
        archive = build_upload_archive(upload_files, file_modes)[0]
        limit = UPLOAD_CAP_BYTES if UPLOAD_CAP_BYTES is not None else 1 << 62
        decision = sandbox_limits.decide_upload(len(archive), download_source, limit)
        if decision.mode == "refuse":
            raise UploadTooLargeError(len(archive), limit)
        if decision.mode == "download":
            # Never a local upload of an over-limit repo: send the manifest only. A checkpoint operation never uses the D-20
            # overlay (its changes travel in the branch archive), so `overlay_paths` only applies to the legacy path.
            archive = build_upload_archive(upload_files, file_modes, manifest_only=True, download_source=download_source,
                                           overlay_paths=frozenset(overlay_paths) if checkpoint is None else frozenset())[0]
            extract_command = extract_command_for(download_source)
    branch_archive = None
    if checkpoint is not None and checkpoint.has_branch:
        branch_archive = build_branch_archive(checkpoint.branch_files, checkpoint.branch_deleted)
        limit = UPLOAD_CAP_BYTES if UPLOAD_CAP_BYTES is not None else 1 << 62
        if len(branch_archive) > limit:
            raise UploadTooLargeError(len(branch_archive), limit)

    # harness-v1.1: transient API failures (timeouts, transport errors, 429,
    # 5xx) re-run the whole chain from a fresh image with bounded exponential
    # backoff; persistent or other external failures -> SandboxInfraError.
    # The wall-clock ceiling (OperationTimedOutError) is never retried.
    try:
        result = retry_call(
            lambda: _run_once(
                api_key=api_key,
                project_id=project_id,
                base_image=base_image,
                commands=commands,
                runner_commands=frozenset((*runner_torch, *runner_extras)),
                wall_clock_seconds=wall_clock_seconds,
                archive=archive,
                extract_command=extract_command,
                checkpoint=checkpoint,
                start_ops=tuple(checkpoint.start_ops) if checkpoint is not None and checkpoint.start_image else (),
                branch_archive=branch_archive,
            ),
            source="sandbox",
            is_transient=_is_transient_sandbox_error,
            is_external=_is_external_sandbox_error,
            sleep=_sleep,
        )
    except InfraError as exc:
        if isinstance(exc, SandboxInfraError):
            raise
        raise SandboxInfraError(str(exc).removeprefix("sandbox: "), attempts=exc.attempts, cause=exc.__cause__) from exc
    if checkpoint is None:
        return result
    from dataclasses import replace as _replace

    return _replace(result, setup_commands=tuple(all_setup), ran_setup=tuple(to_run))


_sleep: Callable[[float], None] = time.sleep  # tests replace it


def run_on_image(*, api_key: str, project_id: str = "", image_id: str, command: str, timeout_seconds: float) -> StepResult:
    """harness-v1.4.3-rc (D-42, the sustained-run line): ONE disposable run of `command` on a kept image, reopened by its id (strict: the API
    confirms the image exists), for at most `timeout_seconds`. Nothing is built, uploaded or kept; nothing is retried (a long run is not repeated
    behind the caller's back). Returns the StepResult, whose `timed_out` is set when the SANDBOX stopped the step at the limit (the API returns the
    killed step's output and real cost as a normal result, D-17); a client-side wait timeout raises SandboxTimeoutError, like any other step."""
    if not api_key:
        raise SandboxCredentialsError("NEBIUS_API_KEY is not set — cannot open a Token Factory Sandbox.")
    client = ContreeSync(
        config=ContreeConfig(auth=IAMAuth(token=api_key, project_id=project_id), transport_timeout=timeouts.sandbox_transport_timeout(0),
                             operation_timeout=timeouts.SANDBOX_OPERATION_S, default_truncate_output_at=OUTPUT_LIMIT_BYTES)
    )
    started = time.monotonic()
    try:
        image = client.images.use(image_id, strict=True)
        executed = image.run(shell=command, timeout=timeout_seconds, disposable=True, preserve_env=False, **_byte_streams(image)).wait()
    except OperationTimedOutError as exc:
        raise SandboxTimeoutError(f"sandbox execution exceeded {timeout_seconds}s wall clock: {exc}", command=command, completed_cost_usd=0.0,
                                  killed_seconds=time.monotonic() - started) from exc
    return step_result_from_image(executed, command, "repo_run")


def release_images(*, api_key: str, project_id: str = "", image_ids: Iterable[str]) -> dict:
    """harness-v1.4.0-rc: the same best-effort disposal `_run_once` applies to every image it does not keep (a trivial disposable run on
    it), for kept images a later decision no longer needs (the losing candidates' result images). The SDK has no delete call, so whether
    this frees anything on the platform is NOT known; what is known is that each disposal is a sandbox run with its own cost, returned for
    the caller to record: {"released": n (disposal runs completed), "cost_usd": total, "seconds": total}."""
    ids = [i for i in image_ids if i]
    if not ids or not api_key:
        return {"released": 0, "cost_usd": 0.0, "seconds": 0.0}
    client = ContreeSync(
        config=ContreeConfig(auth=IAMAuth(token=api_key, project_id=project_id), transport_timeout=timeouts.SANDBOX_CLEANUP_S,
                             operation_timeout=timeouts.SANDBOX_OPERATION_S)
    )
    released, cost, seconds = 0, 0.0, 0.0
    for image_id in ids:
        try:
            done = client.images.use(image_id).run(shell="true", disposable=True, timeout=timeouts.SANDBOX_CLEANUP_S).wait()
            released += 1
            result = getattr(done, "result", None)
            cost += float(getattr(result, "cost", 0.0) or 0.0)
            elapsed = getattr(result, "elapsed_time", None)
            seconds += elapsed.total_seconds() if elapsed is not None else 0.0
        except ContreeError:
            pass  # best-effort, like the cleanup in _run_once
    return {"released": released, "cost_usd": cost, "seconds": seconds}


def _run_once(
    *,
    api_key: str,
    project_id: str,
    base_image: str,
    commands: list[str],
    wall_clock_seconds: float,
    archive: bytes | None,
    runner_commands: frozenset[str] = frozenset(),
    extract_command: str = EXTRACT_COMMAND,
    checkpoint: Checkpoint | None = None,
    start_ops: tuple[str, ...] = (),
    branch_archive: bytes | None = None,
) -> SandboxRunResult:
    """One attempt of the whole chain. Raises the SDK's own errors (the
    caller classifies them), SandboxError for the wall clock, and
    UploadIntegrityError if the post-extraction check fails."""
    # harness-v1.2: no silent SDK default. The SDK's transport_timeout (10 s)
    # made every upload that took longer than 10 s time out, deterministically.
    client = ContreeSync(
        config=ContreeConfig(
            auth=IAMAuth(token=api_key, project_id=project_id),
            transport_timeout=timeouts.sandbox_transport_timeout(
                (len(archive) if archive is not None else 0) + (len(branch_archive) if branch_archive is not None else 0)),
            operation_timeout=timeouts.SANDBOX_OPERATION_S,
            default_truncate_output_at=OUTPUT_LIMIT_BYTES,  # harness-v1.4.3-rc (D-41): the SDK default of 65,535 bytes cut #3's traceback
        )
    )
    start_image = checkpoint.start_image if checkpoint is not None else None
    # harness-v1.4.0-rc: an operation can start from a kept image, reopened by its id (strict: the API confirms it exists).
    image = client.images.use(start_image, strict=True) if start_image else client.images.docker(base_image)
    keep_layers = checkpoint is not None and checkpoint.keep_layers
    branch_first = checkpoint is not None and checkpoint.branch_before_setup

    steps: list[StepResult] = []
    rerun_steps: list[StepResult] = []
    current = image
    retained_images = []  # every disposable=False image, for guaranteed cleanup
    kept: list = []  # the retained images this operation keeps (checkpoint only): never cleaned up
    layers: list[tuple[tuple[str, ...], str]] = []
    result_image: str | None = None
    keep_on_exit = False  # kept images survive only a normal return or a timeout (their layers are then recorded)

    # The id reported as sandbox_id: the last image in the chain that has
    # one. The final step always runs disposable=True, and contree_sdk only
    # assigns a uuid to a run that produced an image (image_like/_base.py:
    # `new_self.uuid = new_uuid and UUID(new_uuid)`), so taking the final
    # image's uuid gave None whenever the execute step actually ran — the
    # `id=None` seen in the 2026-09-24 TTPT live run. This is the id of the
    # environment image the final step ran on.
    last_image_uuid = getattr(current, "uuid", None)

    def _keep(img, ops: tuple[str, ...] | None) -> None:
        uuid = getattr(img, "uuid", None)
        if uuid is None:
            return
        if img not in kept:
            kept.append(img)
        if ops is not None:
            layers.append((ops, str(uuid)))

    upload_seconds = None
    # Bookkeeping for SandboxTimeoutError: the step being run and how long it has run.
    extract_cost = 0.0
    current_cmd = ""
    step_started = time.monotonic()
    ran_setup: list[str] = []
    try:
        # The chain: [upload + extract] [overlay, early] setup... [overlay, late] command. Each item: (kind, command, archive name, bytes).
        chain: list[tuple[str, str, str | None, bytes | None]] = []
        if archive is not None:
            chain.append(("extract", extract_command, UPLOAD_ARCHIVE, archive))
        if branch_archive is not None and branch_first:
            chain.append(("branch", BRANCH_COMMAND, BRANCH_ARCHIVE, branch_archive))
        for cmd in commands[:-1]:
            chain.append(("setup", cmd, None, None))
        if branch_archive is not None and not branch_first:
            chain.append(("branch", BRANCH_COMMAND, BRANCH_ARCHIVE, branch_archive))
        chain.append(("execute", commands[-1], None, None))

        # `wall_clock_seconds` is meant to be a single hard ceiling for the
        # WHOLE attempt (§4: "hard limits (wall clock...)"; the TIMEOUT
        # verdict means "exceeded wall-clock ceiling", singular). Found
        # live: passing the full `wall_clock_seconds` unchanged to every
        # step's own `timeout=` would let a multi-step build (each install
        # command plus the execute command) consume up to
        # len(commands) * wall_clock_seconds in aggregate — e.g. a
        # configured 60s ceiling silently allowing 180s for a 2-install
        # build. Tracking one shared deadline across all steps makes the
        # configured value an actual ceiling on the whole attempt,
        # matching §9's cost-predictability goal, rather than a per-step
        # allowance that scales with how many install commands a given
        # repo happens to need.
        deadline = None
        extract_seconds = None
        for kind, cmd, archive_name, archive_bytes in chain:
            if archive_bytes is not None:
                upload_started = time.monotonic()
                current = current.apply_files(files={archive_name: archive_bytes})
                if kind == "extract":
                    upload_seconds = round(time.monotonic() - upload_started, 2)
                retained_images.append(current)
                last_image_uuid = getattr(current, "uuid", None) or last_image_uuid
            if deadline is None:
                # The ceiling starts after the (first) upload, as before harness-v1.4.0-rc.
                deadline = time.monotonic() + wall_clock_seconds
            is_last = kind == "execute"
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise SandboxTimeoutError(
                    f"sandbox execution exceeded {wall_clock_seconds}s wall clock "
                    f"for the whole attempt (stopped before running '{cmd}')",
                    command=cmd, completed_cost_usd=extract_cost + sum(st.cost_usd for st in steps) + _branch_cost(rerun_steps),
                    killed_seconds=0.0, completed_steps=tuple(steps),
                )
            step_started = time.monotonic()
            current_cmd = cmd
            executed = current.run(
                shell=cmd,
                timeout=remaining,
                disposable=is_last,
                preserve_env=not is_last,
                **_byte_streams(current),
            ).wait()
            if kind == "extract":
                phase = "rerun_extract"
            elif kind == "branch":
                phase = "rerun_branch"
            else:
                phase = "runner_setup" if cmd in runner_commands else ("repo_run" if is_last else "repo_install")
            step = step_result_from_image(executed, cmd, phase)
            previous = current  # for the command: the image it ran on, kept when asked for (the adjudicated winner's environment)
            current = executed
            last_image_uuid = getattr(executed, "uuid", None) or last_image_uuid
            if step.timed_out:
                # The server stopped the step at the limit we gave it and returned its result WITH its real cost. It must never be read
                # as the repository's own failure (an exit code 124/137 classified as a runtime error).
                exc = SandboxTimeoutError(
                    f"sandbox execution exceeded {wall_clock_seconds}s wall clock: the sandbox stopped '{cmd[:80]}' at its time limit "
                    f"(server-reported timed_out, exit code {step.exit_code}, cost measured ${step.cost_usd:.4f})",
                    command=cmd, completed_cost_usd=extract_cost + sum(st.cost_usd for st in steps) + _branch_cost(rerun_steps) + step.cost_usd,
                    killed_seconds=0.0, completed_steps=(*steps, step), via="server_result_timed_out",
                    sandbox_id=str(last_image_uuid) if last_image_uuid is not None else None,
                )
                exc.layers = tuple(layers)
                exc.rerun_steps = tuple(rerun_steps)
                keep_on_exit = True
                raise exc
            if not is_last:
                retained_images.append(executed)
            if kind in ("extract", "branch"):
                # RERUN's own step: never part of the repo's result.
                rerun_steps.append(step)
                if step.exit_code != 0:
                    what = "post-extraction check" if kind == "extract" else "patch overlay check"
                    integrity = UploadIntegrityError(
                        f"{what} failed (exit code {step.exit_code})", stderr=step.stderr[-2000:],
                        completed_cost_usd=extract_cost + sum(st.cost_usd for st in steps) + _branch_cost(rerun_steps)
                        + (step.cost_usd if kind == "extract" else 0.0),
                        completed_steps=tuple(steps))
                    integrity.rerun_steps = tuple(rerun_steps)
                    raise integrity
                if kind == "extract":
                    extract_cost = step.cost_usd
                    extract_seconds = step.elapsed_seconds
                    if keep_layers:
                        _keep(executed, ())
                continue
            steps.append(step)
            if kind == "setup":
                if executed.exit_code != 0:
                    break
                ran_setup.append(cmd)
                if keep_layers:
                    _keep(executed, (*start_ops, *ran_setup))
                continue
            # kind == "execute": `previous` is the image the command ran on.
            if checkpoint is not None and checkpoint.keep_result:
                _keep(previous, None)
                result_image = str(getattr(previous, "uuid", None)) if getattr(previous, "uuid", None) is not None else None

        if extract_cost and steps:
            first = steps[0]
            steps[0] = replace(first, cost_usd=first.cost_usd + extract_cost)
        sandbox_id = str(last_image_uuid) if last_image_uuid is not None else None
        keep_on_exit = True
        return SandboxRunResult(
            steps=tuple(steps), sandbox_id=sandbox_id, upload_seconds=upload_seconds, extract_seconds=extract_seconds,
            layers=tuple(layers), branch_from_image=start_image, result_image=result_image, rerun_steps=tuple(rerun_steps),
        )

    except OperationTimedOutError as exc:
        keep_on_exit = True
        timeout_exc = SandboxTimeoutError(
            f"sandbox execution exceeded {wall_clock_seconds}s wall clock: {exc}",
            command=current_cmd,
            completed_cost_usd=extract_cost + sum(st.cost_usd for st in steps) + _branch_cost(rerun_steps),
            killed_seconds=time.monotonic() - step_started,
            completed_steps=tuple(steps),
        )
        timeout_exc.layers = tuple(layers)
        timeout_exc.rerun_steps = tuple(rerun_steps)
        raise timeout_exc from exc
    finally:
        for retained in retained_images:
            if keep_on_exit and retained in kept:
                continue
            try:
                retained.run(shell="true", disposable=True, timeout=timeouts.SANDBOX_CLEANUP_S).wait()
            except ContreeError:
                pass  # best-effort cleanup; nothing more actionable from here


def _branch_cost(rerun_steps) -> float:
    return sum(s.cost_usd for s in rerun_steps if s.phase == "rerun_branch")
