# TEST phase — harness-v1.5-final (code = sealed harness-v1.7.1)

Protocol: METHODOLOGY.md "harness-v1.5 dev/test protocol", section T, and the freeze record of 2026-10-05. The 8 TEST entries were never opened, run or tuned on before this phase; each ran once, TREATMENT, entry cap $2.50, TEST cap $30.00 (owner, chat 2026-10-05). Records: `runs/corpus_v2_batch/harness-v1.5-final/test/`; the count below is computed by `reports/corpus-v2.1/v1.5/test/run_test_phase.py` from the pre-registered definition and written to `test_result.json`. Nothing was re-run.

## The primary measure, as pre-registered

**2 of 8 TEST entries confirmed. Target 3: not met.** (Confirmed without resource-adapted entries: 2; with a semantic change: 0.) A count over 8 entries, one run each: not a rate. A confirmed run says the documented command ran 600 s or exited 0 by itself; it does not say the paper's result was reproduced.

| id | entry | verdict | code | how it ended | confirmed |
|---|---|---|---|---|---|
| 1 | nadiinchi/power_laws_deep_ensembles | BLOCKED | DEP_MISSING | | no |
| 2 | DeformableFriends/NeuralTracking | BLOCKED | RUNTIME_ERROR_OTHER | | no |
| 6 | grigorisg9gr/rocgan | BLOCKED | RUNTIME_ERROR_OTHER | | no |
| 10 | alevine0/patchSmoothing | RUNS_AFTER_REPAIR | GPU_REQUIRED | smoke alive at 60 s, then the sustained run ran the full 600 s without failing | **yes**, rule (iii) |
| 13 | seongjunyun/neo_gnns | INDETERMINATE | DEP_BUILD_FAILED | | no |
| 18 | aam-at/adversary_critic | RUNS_CLEAN | | as published: exit 0 (`baseline_complete`) | **yes**, rule (i) — **a false positive, see below** |
| 19 | lrjconan/RBP | BLOCKED | DEP_MISSING | | no |
| 20 | XiaoxiaoGuo/fashion-retrieval | BLOCKED | DATA_MISSING | | no |

## Beside it: the D-46 audit, decided before the result

D-46 (written while the TEST phase was running, before any result was read; `reports/corpus-v2.1/candidate_v1.3.3_defects.md`): an exit code 0 is read as success whatever the command printed. The audit lists every entry confirmed under rule (i) with what it actually did.

**#18 did not run.** Its documented command is `python generate_script.py --train=True | bash`. The run step took about 0.1 s of sandbox time, wrote nothing to stdout and 154 bytes to stderr. The record keeps the stream's SHA-256, and it equals the SHA-256 of the 154-byte traceback `ModuleNotFoundError: No module named 'decorator'` at the script's line 8. The script failed at its first import; `bash`, at the end of the pipe, read nothing and exited 0, and that exit code is the pipeline's.

**So: 2 of 8 confirmed as pre-registered; 1 of 8 (#10) ran its documented command, for 600 s.** The pre-registered number is not changed after the fact; the correction is stated beside it.

## Cost

Entries $9.3150 (API-reported plus the estimate of any killed step), sustained runs $9.12, total $18.4350 of the $30.00 TEST cap (`test_result.json`, `spend`).

## What the TEST entries show about the harness

- #10's GPU-only code ran on the CPU sandbox through the CPU shim (a deterministic rule), and kept running for the full sustained window.
- Five of eight ended on a named blocker in the records' own words (missing dependency, build failure, missing dataset, runtime errors).
- #18 shows the harness can report a run that did nothing as RUNS_CLEAN when a pipeline hides the failure (D-46). The fix (for example `set -o pipefail` for the documented command, and requiring evidence of work for a short exit-0 run) is a new version and a new seal; it was not applied to any recorded verdict.
