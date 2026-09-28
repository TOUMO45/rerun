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

from app.services import timeouts
from app.services.infra import InfraError, retry_call


class SandboxError(RuntimeError):
    """A sandbox run could not produce a result for a reason that is about
    the run itself (the wall-clock ceiling). External API failures are
    SandboxInfraError instead (harness-v1.1)."""


class SandboxCredentialsError(SandboxError):
    pass


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


# Largest upload archive RERUN sends, fixed BEFORE any harness-v1.2 run by the
# pre-registered live probe (METHODOLOGY, "Upload cap"). Nebius documents no
# upload limit. None = not yet decided (only the probe itself runs then).
UPLOAD_CAP_BYTES: int | None = None


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
    elif st != int(mode, 8):
        bad.append(p + " (mode %o != %s)" % (st, mode))
if bad:
    sys.stderr.write("RERUN_UPLOAD_MISMATCH %d file(s): %s\\n" % (len(bad), " ".join(bad[:20])))
    sys.exit({UPLOAD_MISMATCH_EXIT})
print("RERUN_UPLOAD_VERIFIED %d file(s)" % len(m))
"""

EXTRACT_COMMAND = (
    f"tar -xpf {UPLOAD_ARCHIVE} --no-same-owner && python3 {UPLOAD_DIR}/verify.py "
    f"&& rm -rf {UPLOAD_DIR} {UPLOAD_ARCHIVE}"
)


def _blob_sha1(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def file_mode_for(git_mode: str | None) -> int:
    return _GIT_MODE_TO_FILE_MODE.get(git_mode or "", _DEFAULT_FILE_MODE)


def build_upload_archive(
    upload_files: dict[str, str | Path | bytes],
    modes: dict[str, str] | None = None,
    mtime: float | None = None,
) -> tuple[bytes, dict[str, list[str]]]:
    """(tar bytes, manifest path -> [git blob SHA-1 of the bytes put in the
    tar, octal file mode]). `modes` maps path -> git mode ("100755"/"100644")."""
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
            _add(name, data, mode)
            manifest[name] = [_blob_sha1(data), f"{mode:04o}"]
        _add(f"{UPLOAD_DIR}/manifest.json", json.dumps(manifest, sort_keys=True).encode("utf-8"))
        _add(f"{UPLOAD_DIR}/verify.py", _VERIFY_SCRIPT.encode("utf-8"))
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


def step_result_from_image(image, command: str) -> StepResult:
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

    commands = [*install_commands, execute_command]
    if not [c for c in commands if c]:
        raise SandboxError("no commands to run: install_commands and execute_command are both empty")
    archive = build_upload_archive(upload_files, file_modes)[0] if upload_files else None
    if archive is not None and UPLOAD_CAP_BYTES is not None and len(archive) > UPLOAD_CAP_BYTES:
        raise UploadTooLargeError(len(archive), UPLOAD_CAP_BYTES)

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
                wall_clock_seconds=wall_clock_seconds,
                archive=archive,
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

    try:
        if archive is not None:
            current = current.apply_files(files={UPLOAD_ARCHIVE: archive})
            retained_images.append(current)
            last_image_uuid = getattr(current, "uuid", None) or last_image_uuid
            commands = [EXTRACT_COMMAND, *commands]

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
        extract_cost = 0.0
        for i, cmd in enumerate(commands):
            is_last = i == len(commands) - 1
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise SandboxError(
                    f"sandbox execution exceeded {wall_clock_seconds}s wall clock "
                    f"for the whole attempt (stopped before running '{cmd}')"
                )
            executed = current.run(
                shell=cmd,
                timeout=remaining,
                disposable=is_last,
                preserve_env=not is_last,
            ).wait()
            step = step_result_from_image(executed, cmd)
            current = executed
            last_image_uuid = getattr(executed, "uuid", None) or last_image_uuid
            if not is_last:
                retained_images.append(executed)
            if cmd == EXTRACT_COMMAND:
                # RERUN's own step: never part of the repo's result.
                if step.exit_code != 0:
                    raise UploadIntegrityError(
                        f"post-extraction check failed (exit code {step.exit_code})", stderr=step.stderr[-2000:]
                    )
                extract_cost = step.cost_usd
                continue
            steps.append(step)
            if executed.exit_code != 0:
                break

        if extract_cost and steps:
            first = steps[0]
            steps[0] = StepResult(first.command, first.exit_code, first.stdout, first.stderr,
                                  first.elapsed_seconds, first.cost_usd + extract_cost)
        sandbox_id = str(last_image_uuid) if last_image_uuid is not None else None
        return SandboxRunResult(steps=tuple(steps), sandbox_id=sandbox_id)

    except OperationTimedOutError as exc:
        raise SandboxError(f"sandbox execution exceeded {wall_clock_seconds}s wall clock: {exc}") from exc
    finally:
        for retained in retained_images:
            try:
                retained.run(shell="true", disposable=True, timeout=timeouts.SANDBOX_CLEANUP_S).wait()
            except ContreeError:
                pass  # best-effort cleanup; nothing more actionable from here
