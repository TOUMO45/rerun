# harness-v1.6.0 — what it adds, from which records, and what reviewed it

Protocol: METHODOLOGY "harness-v1.6 — PRE-REGISTRATION" (written before any v1.6 live call) and rule G of the v1.5 protocol. Branch `v1.6`; the tag is cut only after DEV round 3 (harness-v1.5.2) has finished, so that round's preflight sees unchanged harness code. NOT yet run live. Sandbox-touching files (`runner_hooks.py`, `sandbox.py`, `sandbox_limits.py`, `runner_env.py`, `smoke_exec.py`) are byte-identical to harness-v1.5.2, so the harness-v1.5.1 seal carries over.

| item | class of failure | recorded failure it replays (DEV or gate record) | covered by the class | label |
|---|---|---|---|---|
| C1 `API_REMOVED` | the code uses a name a newer release of a third-party package removed | DEV #12 (`module 'tensorflow' has no attribute 'get_variable'`), gate #08 (`cannot import name 'compare_psnr' from 'skimage.measure'`), DEV #17 (`cannot import name 'zero_gradients'`) | three entries | class-level |
| C2 `DATA_MISSING` widened | the repository tells the user to download a dataset; a DataLoader worker cannot find a file | DEV #9 (`AssertionError: Download cifar10 dataset!!`), gate #03 | two entries | class-level |
| C3 `GPU_REQUIRED` widened | a CUDA-only operation or device lookup on a CPU sandbox | DEV #14 (`Cannot access accelerator device when none is available`; `LU without pivoting is not implemented on the CPU`) | one entry (the F3 class of v1.5.1 covers the `.cuda()` shape) | class-level |
| C4 `APT_MIRROR_GONE` | the base image's distribution has left the mirrors (end-of-life) | DEV #16 (`E: Failed to fetch http://security.debian.org/debian-security/... 404`) | one entry | **single-case**; attribution ENV, verdict INDETERMINATE |
| C5 `DEP_BUILD_FAILED` | a source build fails during install | gate #07 (`Encountered error while generating package metadata`) | one entry | **single-case** |
| L outcome ladder | (reporting, not a fix) `result.outcome_levels`: first error cleared (by what), environment resolved, entrypoint runs | every record; the offline table `reports/dev/levels/levels.md` is the same function | all | — |
| B blocker report | (reporting) `result.blocker`: class, phase, attribution, evidence, fixable_by, what a human must supply | every BLOCKED / INDETERMINATE record | all | — |
| S Tavily dataset source | (reporting) one runtime search for a `DATA_MISSING` blocker, stored on `blocker.sources` | DEV #9, gate #03 | two entries | — |

Replay tests: `backend/tests/test_v16_replay_records.py` classifies the stored stderr tail of the recording attempt of each of the six records with the live classifier function and asserts the v1.6 class and the blocker row (plus one negative control: DEV #4's `NameError` stays `RUNTIME_ERROR_OTHER`). `backend/tests/test_v16_harness.py` (pipeline, ladder, blocker, Tavily, review fixes) and `test_classifier.py` additions cover the rules on synthetic lines. `backend/tests/test_v16_offline_ladder.py` pins the committed ladder table to the records.

## Independent review (read-only subagent, static reading; the reviewer could not execute tests)

No finding on the hashed record format (unchanged; old certificates verify). Findings and what was done, all with a test that failed before and passes after (commit "review fixes (1-10)"):
1. HIGH — `APT_MIRROR_GONE` fired on a transient single-package 404 → patterns narrowed to Release-file loss, an index-file 404, and `security.debian.org` / `archive.debian.org` / `/debian-security/` 404s; a DEP_* failure printed after the apt line wins.
2. HIGH — the `DEP_BUILD_FAILED` wrapper masked later rules when pip recovered → masked when `Successfully installed` follows; a rule matching after the block wins; `DEP_YANKED` / `DEP_NOT_ON_PYPI` count as inner causes; evidence limited to the block.
3. MEDIUM — the tensor-type GPU patterns matched echoed source lines and deprecation warnings → an exception prefix is required on the line.
4. MEDIUM — the `AssertionError` DATA_MISSING pattern matched argument validation → guard phrasing required.
5. MEDIUM — "no CPU implementation" sentence on the plain no-accelerator line → only `is not implemented on the CPU` gets it.
6. MEDIUM — the ladder's verdict fallback could read a flaky RUNS_CLEAN as "cleared" → restricted to RUNS_AFTER_REPAIR.
7. MEDIUM — `first_error_cleared_by` named the first attempt numbered 0 → the passing one among them.
8. MEDIUM — an unknown class raised inside the API's certificate → guarded row with a warning.
9. LOW — the Tavily lookup ran on INDETERMINATE runs → BLOCKED only.
10. LOW — three table sentences overclaimed → reworded.
Not reached by the reviewer: the test files' quality (9) and the DB migration path (6), both exercised by the suite (1757 passed, 12 skipped at commit 5122856); the reviewer's probe inputs are the new `test_fix*` tests.

## Seen and deliberately not done
No new repair, shim or sandbox step (pre-registration, "Not in v1.6"). A data-preparation step run in the sandbox (the class of DEV #4, #9 and gate #03) stays a v1.7 candidate.
