# Gate v1.4.3 — NOT PASSED (attempted, did not pass)

Harness `harness-v1.4.3` (`085d12b`, sealed, all 17 earlier seal entries re-verified plus two new ones; Step 1 on `harness-v1.4.3-rc` = `aba2391`). TREATMENT only, corpus-v2 entries 3, 7, 8, 11 in that order, fixed entry cap $1.75, criteria (a)-(e) as pre-registered in METHODOLOGY before any v1.4.3 run (the runner loads the v1.4.0 criteria down the chain). Records: `runs/corpus_v2_batch/harness-v1.4.3/gate/`; mechanical verdict: `gate_result_harness-v1.4.3.json` (`run_gate_v143.py`). v1.4.3 is EXPLORATORY on a disclosed development set, like v1.3.3 to v1.4.2; v1.3.2 (0/16) stays the pre-registered result.
Tags: API-REPORTED = a stored record field (the sandbox API's `resources.cost`, not account billing, D-36; the model share is DERIVED from the price table and is part of every `spent_usd`), ESTIMATED, DERIVED, BILLED.
This was the final gate: **all live work stops here** (owner). **How it ran:** the gate was started three times; two attempts were killed by their environment and only the third finished (section "Interrupted attempts"): #3 and #7 are records of the second attempt, #8 and #11 of the third, resumed with `--resume` under the same tag, caps and order; the gate cap of the resumed invocation was $6.25 (the pre-registered $7.00 less what the $32.00 ledger ceiling no longer allowed after the interrupted attempts).

## Verdict per criterion

| Criterion | Result | Evidence |
|---|---|---|
| (a) >= 2 of 4 RUNS_CLEAN / RUNS_AFTER_REPAIR | **FAIL: 0 of 4** | #3 BLOCKED DATA_MISSING; #7 BLOCKED RUNTIME_ERROR_OTHER; #8 BLOCKED RUNTIME_ERROR_OTHER; #11 INDETERMINATE RESOURCE_LIMIT |
| (b) >= 1 source patch applied | pass: 15 applied of 17 proposed | #3 8 (all three rounds), #8 7 |
| (c) >= 1 stored Tavily citation | pass: 7 attempts | #3 2 attempts, #8 5 attempts (v1.4.2: 0; v1.4.1: 6; v1.4.0: 3) |
| (d) no entry over $2.00, guard correct | pass | largest entry $1.1742; no operation was stopped, so no cost event |
| (e) torch at most once per environment image | pass on all four | #3: 1 install outside the baseline; #7: none; #8: none; #11: 1 |

No entry ended RUNS_*: **the sustained-run line (D-42) had nothing to label and made no live run** (its primitive was verified live in the seal, S3 and S4).

## What the entries did (API-REPORTED unless marked)

| Entry | Verdict | Spend (model share) | What happened |
|---|---|---|---|
| #3 autumn9999/vmtl | BLOCKED `DATA_MISSING` | $0.9435 ($0.0901) | **D-41 fixed, live.** The era run's stderr, 399,981 bytes of download progress and then a traceback, came back whole (`truncated` false); the CUDA error that had been cut off in every earlier version was seen, classified GPU_REQUIRED, and the **CPU shim fired as a deterministic rule with no model call** (`paths_fired`: `torch.load`, `module.cuda`: the first live exercise of the `.cuda()` path, D-39). The run then reached the repository's own data loading: `FileNotFoundError: '/Dataset/office-home/images/Art/Drill/00014.jpg'` in a DataLoader worker. Three rounds of three candidates (8 patches applied) could not supply that path (a dataset outside the checkout; whether the repository documents how to obtain it was not examined); BLOCKED, with that cause. [Phase D red team D6: reworded; the first draft said the repository does not contain the dataset, which no record shows.] |
| #7 albertometelli/pfqi | BLOCKED `RUNTIME_ERROR_OTHER` | $0.6735 ($0.0861) | numpy, then `pkg-config: not found` (SYS_LIB_MISSING), then `Encountered error while generating package metadata` on an install step. Seven environment changes were proposed and run; the adjudicator's first reply was invalid JSON once and the re-ask worked (D-32, live again); none passed. v1.4.2's pass on this entry did not repeat: the proposals differ between runs. |
| #8 edenton/svg | BLOCKED `RUNTIME_ERROR_OTHER` | $1.1742 ($0.0702) | `sklearn`, then the repository's own `from skimage.measure import compare_psnr` (removed from scikit-image). 7 patches applied, 5 attempts cited a stored source (`scikit-image` issue 3567 among them); the compiler rule fired on a candidate's own branch with no model call (D-24, live again). The import stayed unresolved: BLOCKED, under the $1.75 cap. v1.4.2 ended COST_CAP here. |
| #11 JindongGu/VoteAttack | INDETERMINATE `RESOURCE_LIMIT` | $0.9032 ($0.0031) | The CPU shim cleared the GPU error (`cuda.is_available`, `torch.load`); the run trained and was killed: exit 137, `Killed`; one evidence run read the kernel's own line: `Out of memory: Killed process 74 (python) ... anon-rss:3897356kB` on a VM with `MemTotal` 4,034,744 kB (3.85 GiB). **The API's peak-memory figure for the step (`max_rss`, stored for the first time in this version) is 3,898,376 as returned**, within 1,020 of the kernel's `anon-rss` in kB, so its unit is consistent with kilobytes (not converted, not documented). No larger-instance rule exists (no SDK parameter). Not a verdict on the repository. |

Gate spend (the four records): **$3.69455** = $3.4451 sandbox API-reported + $0.2495 model (DERIVED, price table); estimated part $0.0000 (nothing was stopped). Pre-batch upload smoke tests: passed each time ($0.00498, $0.005282 and $0.005362 for the three starts). Entry caps: every entry ran with the $1.75 cap; the largest used 67 % of it. Kept images per entry (distinct ids, `operations[].kept_images`): #3 8, #7 7, #8 6, #11 9.
**BILLED: not yet** (neither for the v1.4.2 gate nor for this one): the owner reads the account balance; the ledger is the API-reported cost, not billing (D-36).

## What the D-41 fix showed live

- **No stream of the four records was cut**: every `operations[].streams.*.truncated` is false, the largest stderr was 400,941 bytes (#3, whole), so no entry ended OUTPUT_TRUNCATED and no classification rested on a cut stream in this gate.
- **#3 ends with a different, real verdict.** In v1.4.2 it was INDETERMINATE `EXIT_OUTSIDE_PYTHON` ("printed no error"), in v1.3.x to v1.4.1 a silent exit: all produced by the cut. The probe (`d41-probe/probe_03_vmtl_op5@51727e64...`) found the error behind it; this gate shows the harness acting on it.
- The 4 MiB output limit, the byte request, the stream records and `max_rss` all appear in the records as designed; the live seal had already shown that the API honours the limit.

## Against the earlier gates (same entries, same criteria)

| | v1.4.0 | v1.4.1 | v1.4.2 | v1.4.3 |
|---|---|---|---|---|
| (a) | 0 of 4 | 0 of 4 | 1 of 4 | **0 of 4** |
| #3 | BLOCKED (silent exit) | BLOCKED (exit outside Python) | INDETERMINATE EXIT_OUTSIDE_PYTHON | **BLOCKED DATA_MISSING** (the cut error seen) |
| #7 | BLOCKED | BLOCKED SYS_LIB_MISSING | RUNS_AFTER_REPAIR | BLOCKED RUNTIME_ERROR_OTHER |
| #8 | COST_CAP | BLOCKED GPU_REQUIRED | COST_CAP | BLOCKED RUNTIME_ERROR_OTHER |
| #11 | COST_CAP | BLOCKED (killed, 137) | INDETERMINATE RESOURCE_LIMIT | INDETERMINATE RESOURCE_LIMIT |
| (c) | pass (3) | pass (6) | fail (0) | pass (7) |
| gate spend (entries) | $3.1943 | $3.5247 | $3.9350 | $3.69455 |

Across the six exploratory gates since v1.3.3 (v1.3.3, v1.3.4, v1.4.0, v1.4.1, v1.4.2, v1.4.3; the first draft of this line said five, a miscount corrected in the Phase D update) the count of gate entry-runs that ended RUNS_CLEAN or RUNS_AFTER_REPAIR is 2 of 24, one a smoke-limit artefact and one a 60 s smoke-criterion pass (the Phase D update restates the headline from the records).

## Interrupted attempts (operational finding, D-43)

`INTERRUPTED_ATTEMPT.md` has the details and the ledger. In short: attempt 1 ran as a child of the session that started it and was killed with it inside #3 (8 recorded operations, $0.7005, no record); attempt 2a, started through WMI, died ten seconds in; attempt 2b, started through the Task Scheduler with `python.exe`, landed #3 and #7 and died inside #8 (exit code 0xC000013A, STATUS_CONTROL_C_EXIT, 7 recorded operations, $0.7861, no record; what sent the console control event is not known); attempt 2c, `pythonw` (no console) from the Task Scheduler with the new `--resume` and `--log-file`, ran #8 and #11 and finished. None of the interrupted work is in the gate; its spend is in the ledger. A full restart was impossible: after the interrupted attempts the ledger lower bound was $27.0914, and a new gate cap of $7.00 would have passed the $32.00 ceiling.

## Ledger (lower bound, D-27)

| Item | USD |
|---|---|
| after the v1.4.2 gate | 22.4935 (21.3218 API-reported + 1.1717 estimated) |
| D-41 probe | 0.048615 |
| v1.4.3 seal | 1.430679 (1.126227 API-reported + 0.304452 estimated) |
| interrupted attempts (no record of the gate): attempt 1 $0.70548, attempt 2a $0.000814, attempt 2b smoke $0.005282, #8 of attempt 2b $0.7861, attempt 2c smoke $0.005362 | 1.503038 |
| gate v1.4.3 (four records) | 3.69455 |
| **total** | **29.1704** (of which ESTIMATED 1.4762; the rest API-reported, apart from the model share inside every `spent_usd`, which is DERIVED from the price table) |

Ceiling $32.00: **room $2.8296**. The rows are shown rounded as their sources state them; the total is the sum of the unrounded record values (the Phase D ledger, `reports/phase-d/replay/summary.json`, builds it from the records and gets 29.17038). BILLED: awaited. All live work is stopped.
