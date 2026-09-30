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
import io
import json
import tarfile
import time
from dataclasses import dataclass
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
                 completed_steps: tuple = ()):
        super().__init__(message)
        self.command = command
        self.completed_cost_usd = completed_cost_usd
        self.killed_seconds = killed_seconds
        self.completed_steps = completed_steps


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

    def __init__(self, message: str, stderr: str = ""):
        self.stderr = stderr
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
print("RERUN_UPLOAD_VERIFIED %d file(s)" % len(m))
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
        f"&& python3 {UPLOAD_DIR}/fetch.py && python3 {UPLOAD_DIR}/verify.py && rm -rf {UPLOAD_DIR}"
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
) -> tuple[bytes, dict[str, list[str]]]:
    """(tar bytes, manifest path -> [git blob SHA-1 of the bytes put in the
    tar, octal file mode]). `modes` maps path -> git mode ("100755"/"100644").
    `manifest_only` (download route): the tar carries only the manifest and the
    verifier; the files themselves are fetched inside the sandbox and checked
    against the same manifest."""
    mtime = time.time() if mtime is None else mtime
    modes = modes or {}
    manifest: dict[str, list[str]] = {}
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
            manifest[name] = [_blob_sha1(data), f"{mode:04o}"]
        _add(f"{UPLOAD_DIR}/manifest.json", json.dumps(manifest, sort_keys=True).encode("utf-8"))
        _add(f"{UPLOAD_DIR}/verify.py", _VERIFY_SCRIPT.encode("utf-8"))
        if manifest_only:
            if download_source is None:
                raise UploadIntegrityError("a manifest-only archive needs its download source")
            _add(f"{UPLOAD_DIR}/fetch.py", _FETCH_SCRIPT.encode("utf-8"))
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

    @property
    def final(self) -> StepResult:
        if not self.steps:
            raise SandboxError("sandbox run produced no steps")
        return self.steps[-1]

    @property
    def total_cost_usd(self) -> float:
        return sum(s.cost_usd for s in self.steps)

    @property
    def succeeded(self) -> bool:
        return self.final.exit_code == 0


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
        stdout=result.stdout or "",
        stderr=result.stderr or "",
        elapsed_seconds=result.elapsed_time.total_seconds(),
        cost_usd=result.cost,
        phase=phase,
    )


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
) -> SandboxRunResult:
    """Run the full build-plan pipeline in an isolated Token Factory
    Sandbox: reference/import the base image, upload the repo, run each
    install command, then the execute command — stopping at the first
    non-zero exit code. Always tears down sandbox resources, success or
    failure (§2.6): every intermediate retained (`disposable=False`) image
    is disposed of in `finally`, and the final step always runs with
    `disposable=True`.

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
    commands = [*(op.command for op in setup), execute_command]
    if not [c for c in commands if c]:
        raise SandboxError("no commands to run: install_commands and execute_command are both empty")
    archive, extract_command = None, EXTRACT_COMMAND
    if upload_files:
        archive = build_upload_archive(upload_files, file_modes)[0]
        limit = UPLOAD_CAP_BYTES if UPLOAD_CAP_BYTES is not None else 1 << 62
        decision = sandbox_limits.decide_upload(len(archive), download_source, limit)
        if decision.mode == "refuse":
            raise UploadTooLargeError(len(archive), limit)
        if decision.mode == "download":
            # Never a local upload of an over-limit repo: send the manifest only.
            archive = build_upload_archive(upload_files, file_modes, manifest_only=True, download_source=download_source)[0]
            extract_command = extract_command_for(download_source)

    # harness-v1.1: transient API failures (timeouts, transport errors, 429,
    # 5xx) re-run the whole chain from a fresh image with bounded exponential
    # backoff; persistent or other external failures -> SandboxInfraError.
    # The wall-clock ceiling (OperationTimedOutError) is never retried.
    try:
        return retry_call(
            lambda: _run_once(
                api_key=api_key,
                project_id=project_id,
                base_image=base_image,
                commands=commands,
                runner_commands=frozenset(runner_torch),
                wall_clock_seconds=wall_clock_seconds,
                archive=archive,
                extract_command=extract_command,
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


_sleep: Callable[[float], None] = time.sleep  # tests replace it


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
) -> SandboxRunResult:
    """One attempt of the whole chain. Raises the SDK's own errors (the
    caller classifies them), SandboxError for the wall clock, and
    UploadIntegrityError if the post-extraction check fails."""
    # harness-v1.2: no silent SDK default. The SDK's transport_timeout (10 s)
    # made every upload that took longer than 10 s time out, deterministically.
    client = ContreeSync(
        config=ContreeConfig(
            auth=IAMAuth(token=api_key, project_id=project_id),
            transport_timeout=timeouts.sandbox_transport_timeout(len(archive) if archive is not None else 0),
            operation_timeout=timeouts.SANDBOX_OPERATION_S,
        )
    )
    image = client.images.docker(base_image)

    steps: list[StepResult] = []
    current = image
    retained_images = []  # every disposable=False image, for guaranteed cleanup

    # The id reported as sandbox_id: the last image in the chain that has
    # one. The final step always runs disposable=True, and contree_sdk only
    # assigns a uuid to a run that produced an image (image_like/_base.py:
    # `new_self.uuid = new_uuid and UUID(new_uuid)`), so taking the final
    # image's uuid gave None whenever the execute step actually ran — the
    # `id=None` seen in the 2026-09-24 TTPT live run. This is the id of the
    # environment image the final step ran on.
    last_image_uuid = getattr(current, "uuid", None)

    upload_seconds = None
    # Bookkeeping for SandboxTimeoutError: the step being run and how long it has run.
    extract_cost = 0.0
    current_cmd = ""
    step_started = time.monotonic()
    try:
        if archive is not None:
            upload_started = time.monotonic()
            current = current.apply_files(files={UPLOAD_ARCHIVE: archive})
            upload_seconds = round(time.monotonic() - upload_started, 2)
            retained_images.append(current)
            last_image_uuid = getattr(current, "uuid", None) or last_image_uuid
            commands = [extract_command, *commands]

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
        deadline = time.monotonic() + wall_clock_seconds
        extract_seconds = None
        for i, cmd in enumerate(commands):
            is_last = i == len(commands) - 1
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise SandboxTimeoutError(
                    f"sandbox execution exceeded {wall_clock_seconds}s wall clock "
                    f"for the whole attempt (stopped before running '{cmd}')",
                    command=cmd, completed_cost_usd=extract_cost + sum(st.cost_usd for st in steps),
                    killed_seconds=0.0, completed_steps=tuple(steps),
                )
            step_started = time.monotonic()
            current_cmd = cmd
            executed = current.run(
                shell=cmd,
                timeout=remaining,
                disposable=is_last,
                preserve_env=not is_last,
            ).wait()
            phase = "runner_setup" if cmd in runner_commands else ("repo_run" if is_last else "repo_install")
            step = step_result_from_image(executed, cmd, phase)
            current = executed
            last_image_uuid = getattr(executed, "uuid", None) or last_image_uuid
            if not is_last:
                retained_images.append(executed)
            if cmd == extract_command:
                # RERUN's own step: never part of the repo's result.
                if step.exit_code != 0:
                    raise UploadIntegrityError(
                        f"post-extraction check failed (exit code {step.exit_code})", stderr=step.stderr[-2000:]
                    )
                extract_cost = step.cost_usd
                extract_seconds = step.elapsed_seconds
                continue
            steps.append(step)
            if executed.exit_code != 0:
                break

        if extract_cost and steps:
            first = steps[0]
            steps[0] = StepResult(first.command, first.exit_code, first.stdout, first.stderr,
                                  first.elapsed_seconds, first.cost_usd + extract_cost, first.phase)
        sandbox_id = str(last_image_uuid) if last_image_uuid is not None else None
        return SandboxRunResult(
            steps=tuple(steps), sandbox_id=sandbox_id, upload_seconds=upload_seconds, extract_seconds=extract_seconds
        )

    except OperationTimedOutError as exc:
        raise SandboxTimeoutError(
            f"sandbox execution exceeded {wall_clock_seconds}s wall clock: {exc}",
            command=current_cmd,
            completed_cost_usd=extract_cost + sum(st.cost_usd for st in steps),
            killed_seconds=time.monotonic() - step_started,
            completed_steps=tuple(steps),
        ) from exc
    finally:
        for retained in retained_images:
            try:
                retained.run(shell="true", disposable=True, timeout=timeouts.SANDBOX_CLEANUP_S).wait()
            except ContreeError:
                pass  # best-effort cleanup; nothing more actionable from here
