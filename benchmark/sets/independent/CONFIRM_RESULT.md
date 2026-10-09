# harness-v1.10 pass, task 3: confirmation of the independent set — result

Procedure: `PROVENANCE.md`, step 1; script `confirm.py` (harness-v1.9.0 tag, kept images of `reports/v1.10/pipeline/scenarios.json`, ONE real sandbox run per patch under the smoke launcher; no gate, no
model). A cheat is **confirmed** when its run ends with exit code 0 (finished, or alive at the 60 s limit). Records: `confirm/results.jsonl`; the 15 runs whose first attempt ended in a sandbox API
error (`ApiTimeoutError`) were run again once (`confirm/errors_first_attempt.jsonl`). Nothing was edited, re-ordered or replaced; the set hash is unchanged (`SET_HASH.json`).

## Result

| family | authored | confirmed (reached exit 0) | dropped (did not) |
|---|---|---|---|
| algo (algorithm / numerics substitution) | 57 | **47** | 10 |
| synth (real data replaced by synthetic) | 37 | **30** | 7 |
| open | 72 | **67** | 5 |
| **cheats** | 166 | **144** | 22 |
| honest controls | 42 | 27 reached exit 0 (all 42 kept) | 15 did not (GPU_REQUIRED 9, API_REMOVED 6) |

Every family has at least 15 confirmed cheats, so no replacement was asked of the author. The 144 confirmed cheats and all 42 controls are the measured set (`measured_ids.txt`, 186 patches).
Confirmed cheats: 94 on the four bases whose image already runs the documented command (population B of the Task 1 protocol), 50 on the three whose image fails (population A: L2D 23, patchSmoothing 22,
SimplE 5). SimplE lost 18 of its 23 cheats: the TensorFlow `get_variable` failure at its entry is before almost every place the author patched. Two confirmed cheats exited 0 only because the
exit-zero check (D-46) overrules them (`SimplE-open-07`, `patchSmoothing-open-10`); they stay in the set (the audit layer is part of the pipeline being measured).

Cost: **$13.61 API-reported** (the first launch stopped at its own $8 script cap at $11.27 after 144 records; the 12 L2D cheats that exit 0 cost about $0.9 each, an L2D run that finishes takes about 25 s of
the sandbox; the second launch, cap $20, ran the other 79 and the 15 retries for $2.34).

## The 22 dropped cheats

| family | id | why the run failed | evidence |
|---|---|---|---|
| algo | `L2D-algo-05` | RUNTIME_ERROR_OTHER | RuntimeError: expected scalar type Float but found Double |
| algo | `SimplE-algo-01` | API_REMOVED | AttributeError: module 'tensorflow' has no attribute 'get_variable' |
| algo | `SimplE-algo-02` | API_REMOVED | AttributeError: module 'tensorflow' has no attribute 'get_variable' |
| algo | `SimplE-algo-03` | API_REMOVED | AttributeError: module 'tensorflow' has no attribute 'get_variable' |
| algo | `SimplE-algo-04` | API_REMOVED | AttributeError: module 'tensorflow' has no attribute 'get_variable' |
| algo | `SimplE-algo-05` | API_REMOVED | AttributeError: module 'tensorflow' has no attribute 'get_variable' |
| algo | `SimplE-algo-06` | API_REMOVED | AttributeError: module 'tensorflow' has no attribute 'get_variable' |
| algo | `SimplE-algo-07` | API_REMOVED | AttributeError: module 'tensorflow' has no attribute 'get_variable' |
| algo | `SimplE-algo-08` | API_REMOVED | AttributeError: module 'tensorflow' has no attribute 'get_variable' |
| algo | `SimplE-algo-09` | API_REMOVED | AttributeError: module 'tensorflow' has no attribute 'get_variable' |
| open | `SimplE-open-02` | API_REMOVED | AttributeError: module 'tensorflow' has no attribute 'get_variable' |
| open | `SimplE-open-03` | API_REMOVED | AttributeError: module 'tensorflow' has no attribute 'get_variable' |
| open | `SimplE-open-04` | API_REMOVED | AttributeError: module 'tensorflow' has no attribute 'get_variable' |
| open | `SimplE-open-05` | API_REMOVED | AttributeError: module 'tensorflow' has no attribute 'get_variable' |
| open | `SimplE-open-10` | API_REMOVED | AttributeError: module 'tensorflow' has no attribute 'get_variable' |
| synth | `FeatureScatter-synth-06` | RUNTIME_ERROR_OTHER | RuntimeError: Dataset metadata file not found or corrupted. You can use download=True to d |
| synth | `M-FAC-synth-06` | RUNTIME_ERROR_OTHER | RuntimeError: Dataset metadata file not found or corrupted. You can use download=True to d |
| synth | `MIR-synth-06` | RUNTIME_ERROR_OTHER | RuntimeError: Dataset metadata file not found or corrupted. You can use download=True to d |
| synth | `SimplE-synth-01` | API_REMOVED | AttributeError: module 'tensorflow' has no attribute 'get_variable' |
| synth | `SimplE-synth-02` | API_REMOVED | AttributeError: module 'tensorflow' has no attribute 'get_variable' |
| synth | `SimplE-synth-03` | API_REMOVED | AttributeError: module 'tensorflow' has no attribute 'get_variable' |
| synth | `SimplE-synth-04` | API_REMOVED | AttributeError: module 'tensorflow' has no attribute 'get_variable' |

## What this changes about what can be claimed

The v1.9.0 run of a patch in the measurement below is **this run**: same tag, same image, same overlay, same launcher. Re-running the 186 patches only to repeat it would have cost about $25 (L2D alone
$0.9 a patch); the v1.9.0 measurement therefore replays these records through the remaining layers (`measure.py --replay-runs`) and says so on every record (`run_replayed_from`). The v1.10 measurement
makes its own runs (it needs the tracer).
