# DRAFT (Phase E, NOT FILED): `contree-sdk` does not surface `state.timed_out`; a step the sandbox kills looks like an ordinary failure

Status: draft for operator review. Nothing here has been sent. The numbers below come from `runs/sandbox_verification/attempt1-v1.3.3/` (first observation) and
`runs/sandbox_verification/final-v1.3.3/kill_at_operation_limit_py310*.json` (both behaviours, with their stored values); nothing in this draft is invented.

## Summary

With `contree-sdk` 0.3.6, `image.run(shell="sleep 300", timeout=25, disposable=True).wait()` **returns normally after about 28 s**: no exception, a result object, the step
stopped by the platform at the limit. The information that it was stopped (`state.timed_out`) is in the raw API response but is not exposed by `ContreeResult`, so a caller
cannot tell "the command exited with a non-zero code" from "the platform killed it at the time limit" without reading a private attribute. The same event can also surface as
`OperationTimedOutError` (see "Two behaviours for one event"), so callers have to handle both.

## Why it matters

We run untrusted research code in the sandbox and classify failures (missing module, missing file, GPU required, ...). A step stopped by the time limit returned a non-zero exit code
and arrived as a plain result, so our harness treated it as the repository's own failure. Automated reproducibility tooling can therefore attribute a platform kill to the project
under test. The cost of the killed step is reported by the API (`resources.cost`), which is useful, but only if the caller knows the step was killed.

## Minimal reproduction

```python
import time
from contree_sdk import ContreeSync
from contree_sdk.auth import IAMAuth
from contree_sdk.config import ContreeConfig

client = ContreeSync(config=ContreeConfig(auth=IAMAuth(token="<token>", project_id="<project id>")))
image = client.images.docker("python:3.10-slim")

t0 = time.monotonic()
done = image.run(shell="sleep 300", timeout=25, disposable=True).wait()   # returns, does not raise
print(round(time.monotonic() - t0, 1), "s")                               # about 28 s in our run
print(done.exit_code, done.result.cost)                                   # -1 and about $0.00006 in our run
print(done.result._raw.result.state.timed_out)                            # True, but only via the private `_raw`
```

What our archived first attempt (`runs/sandbox_verification/attempt1-v1.3.3/kill_at_operation_limit_py310.json`) establishes by itself: the call with a 25 s limit on a 300 s
command returned without an exception (`"error": "the 300 s step returned without being stopped"`, written by our verification script, which only expected an exception) and the
record was written about 28 s after `started_at` (file times; the script did not store a duration or the result). The exit code, cost and the `timed_out` value come from the
repeated kill run that took the same path (`final-v1.3.3/kill_at_operation_limit_py310_extra1.json`): stopped by the platform after 28.0 s, `timed_out` true, **exit code -1**, cost
**$0.00006**, no exception. In the run made just before it (`kill_at_operation_limit_py310.json`), the identical call raised `OperationTimedOutError` after 27.9 s instead.

## Where it comes from (contree-sdk 0.3.6, read from the installed source)

- `contree_sdk/_internals/models/instance.py`: `ProcessState` has `timed_out: bool`.
- `contree_sdk/sdk/objects/image_like/result.py`: `ContreeResult.from_result` copies `exit_code`, `stdout`, `stderr`, `elapsed_time` and `cost`; `timed_out` is not copied
  (the only access is `result._raw.result.state.timed_out`).

## Two behaviours for one event

`_ImageLikeBase._await` (`sdk/objects/image_like/_base.py`) sends `timeout` to the server (`InstanceSpawnRequest(timeout=round(timeout))`) **and** uses the same value for the client's
wait (`_wait_operation(operation_uuid, InstanceOperationMetadata, timeout=timeout)`). Which one fires first is a race: in the run above the server's result arrived first; in a 600 s
repair re-execution of our batch, and in one of the two identical 25 s runs below, the client's wait expired first and raised `OperationTimedOutError` ("Operation ... has timed out",
step cost not returned). Same call, same event, a result in one run and an exception in the other (both recorded, 28.0 s and 27.9 s).

## Suggested fix (any one of these)

1. Expose `timed_out: bool` on `ContreeResult` (public), so a caller can branch on it.
2. Make the client wait `timeout` plus a small grace period, so the server's result (with `timed_out` and the real cost) is always what the caller gets.
3. Document the behaviour and the race in `run()`'s docstring.

## Workaround we ship

`step_result_from_image` reads `result._raw.result.state.timed_out` (guarded, `False` when absent) and raises our own `SandboxTimeoutError` carrying the step's measured cost
(`backend/app/services/sandbox.py`, test `tests/test_cost_enforcement_v133.py`).

## Environment

`contree-sdk` 0.3.6, Python 3.14.4 on Windows 11, base image `python:3.10-slim`, Nebius Token Factory sandboxes, 2026-09-30.
