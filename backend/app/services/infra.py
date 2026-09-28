"""Infrastructure failures (harness-v1.1, 2026-09-28).

The corpus-v1 batch on harness-v1 showed that an external outage could be
recorded as a verdict about a repository: a Nebius sandbox upload timeout
ended KernelGCN as NOT_ATTEMPTABLE. Every failure that originates outside the
repository under test — the Nebius sandbox API, the Token Factory model API,
GitHub, the package index — is an `InfraError`. It is deliberately NOT a
subclass of any error a pipeline stage falls back on (ModelCallError,
SandboxError, …): no fallback may swallow it and carry on with a degraded run.
`orchestrator.run_pipeline` ends such a run as verdict INFRA_ERROR, an
"our fault" code excluded from every reproducibility denominator.

`retry_call` is the one retry policy: bounded exponential backoff for
transient failures; a failure that persists, or a non-transient external
failure, becomes an InfraError.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")

INFRA_ERROR = "INFRA_ERROR"

# Backoff: base * 2**(n-1), capped — 2s, 4s, 8s for the default 4 attempts.
DEFAULT_ATTEMPTS = 4
DEFAULT_BASE_DELAY_S = 2.0
DEFAULT_MAX_DELAY_S = 30.0


class InfraError(RuntimeError):
    """An external service failed; nothing is known about the repository."""

    def __init__(self, source: str, message: str, *, attempts: int = 1, cause: BaseException | None = None):
        self.source = source  # "sandbox" | "model" | "github" | "package-index" | "git"
        self.attempts = attempts
        self.cause_type = type(cause).__name__ if cause is not None else ""
        detail = f" after {attempts} attempt(s)" if attempts > 1 else ""
        super().__init__(f"{source}: {message}{detail}")


def backoff_delays(attempts: int = DEFAULT_ATTEMPTS, base: float = DEFAULT_BASE_DELAY_S, cap: float = DEFAULT_MAX_DELAY_S) -> list[float]:
    """The sleeps between `attempts` tries (len = attempts - 1)."""
    return [min(cap, base * 2 ** i) for i in range(max(0, attempts - 1))]


def retry_call(
    fn: Callable[[], T],
    *,
    source: str,
    is_transient: Callable[[BaseException], bool],
    is_external: Callable[[BaseException], bool] | None = None,
    attempts: int = DEFAULT_ATTEMPTS,
    base_delay: float = DEFAULT_BASE_DELAY_S,
    max_delay: float = DEFAULT_MAX_DELAY_S,
    sleep: Callable[[float], None] = time.sleep,
    on_retry: Callable[[int, BaseException, float], None] | None = None,
) -> T:
    """Call `fn`; retry transient failures with bounded exponential backoff.

    - transient and tries left -> sleep, retry;
    - transient and out of tries -> InfraError(source);
    - `is_external` (non-transient, but still the external service's
      failure, e.g. HTTP 403 from a quota) -> InfraError immediately;
    - anything else propagates unchanged (a RERUN bug, or a genuine result).
    """
    delays = backoff_delays(attempts, base_delay, max_delay)
    for n in range(1, attempts + 1):
        try:
            return fn()
        except InfraError:
            raise
        except Exception as exc:  # noqa: BLE001 - classified below, never swallowed
            if is_transient(exc):
                if n < attempts:
                    delay = delays[n - 1]
                    if on_retry is not None:
                        on_retry(n, exc, delay)
                    sleep(delay)
                    continue
                raise InfraError(source, f"{type(exc).__name__}: {exc}"[:500], attempts=n, cause=exc) from exc
            if is_external is not None and is_external(exc):
                raise InfraError(source, f"{type(exc).__name__}: {exc}"[:500], attempts=n, cause=exc) from exc
            raise
    raise AssertionError("unreachable")  # pragma: no cover


def http_status_is_transient(status: int) -> bool:
    """429 and 5xx are retried; GitHub's rate limit answers 403 with
    `x-ratelimit-remaining: 0` — callers that can see headers treat that as
    transient too."""
    return status == 429 or 500 <= status < 600


class _TransientHTTPStatus(RuntimeError):
    def __init__(self, status: int, url: str):
        self.status = status
        super().__init__(f"HTTP {status} from {url}")


class _ExternalHTTPStatus(RuntimeError):
    def __init__(self, status: int, url: str):
        self.status = status
        super().__init__(f"HTTP {status} from {url}")


def _http_source(url: str) -> str:
    if "github.com" in url or "githubusercontent.com" in url:
        return "github"
    if "pypi.org" in url or "pythonhosted.org" in url:
        return "package-index"
    return "http"


def _is_transport_error(exc: BaseException) -> bool:
    try:
        import httpx
    except ImportError:  # pragma: no cover
        httpx = None
    return isinstance(exc, (_TransientHTTPStatus, OSError, TimeoutError)) or (
        httpx is not None and isinstance(exc, httpx.TransportError)
    )


def checked_http_get(http_get: Callable[[str], "tuple[int, object]"], *, sleep: Callable[[float], None] | None = None):
    """Wrap a `url -> (status, json)` getter: transport errors, 429 and 5xx
    are retried with backoff; 401/403 (GitHub's unauthenticated rate limit,
    revoked access) or a persistent failure -> InfraError('github' |
    'package-index'). Every other status (200, 404, …) is returned as-is —
    those are answers about the thing looked up, not outages."""

    def _get(url: str):
        def _once():
            status, body = http_get(url)
            if http_status_is_transient(status):
                raise _TransientHTTPStatus(status, url)
            if status in (401, 403):
                raise _ExternalHTTPStatus(status, url)
            return status, body

        return retry_call(
            _once,
            source=_http_source(url),
            is_transient=_is_transport_error,
            is_external=lambda exc: isinstance(exc, _ExternalHTTPStatus),
            sleep=sleep or (lambda s: _module_sleep(s)),
        )

    return _get


def _module_sleep(seconds: float) -> None:
    sleep_fn(seconds)


sleep_fn: Callable[[float], None] = time.sleep  # tests replace it
