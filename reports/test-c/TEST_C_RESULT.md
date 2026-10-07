# TEST-C (corpus-v4): result, harness-v1.8.0 (2026-10-07)

Pre-registered in `backend/app/batch/corpus_v4/prereg.json` (sha256 `7b135ba6...`, seed 20261007, 10 entries, committed and pushed before the tag and before the draw), drawn once at the pushed tag
`harness-v1.8.0` (`reports/test-c/DRAW_NOTE.md`), run once (`reports/test-c/run_test_c.py`; no re-run, no infra retry was needed), audited with the committed rubric and a key written from the raw logs
and committed before scoring. **Published as it came out.** Counts over ten entries, one run each: not rates.

## The two figures, beside each other, never merged

| measure | result | the pre-registered claim threshold | outcome of the claim |
|---|---|---|---|
| **RAN** (R1-R4, the D-46 audit; unchanged from TEST-B) | **1 of 10** | a claim that harness-v1.8 RAN more than v1.7.2 only if RAN is at least 3 of 10 | **not supported: no improvement in RAN is shown.** (Earlier fresh sets: TEST 1 of 8, TEST-B 1 of 8.) |
| **Actionable diagnosis** (rubric `reports/dev/v18/DIAGNOSIS_RUBRIC.md`, scorer `score_diagnosis.py`) | **7 of 9** non-running entries | the claim "the diagnosis is actionable" only if at least 50 percent of the non-running entries are | **met as scored (78 percent)**; see the caveats below, which bear on how much of it is v1.8's work |

The one that ran: **#8 optimass/Maximally_Interfered_Retrieval**, `RUNS_AFTER_REPAIR` (APT_MIRROR_GONE: the base image's Debian archive is gone; RERUN's time-machine step repaired it, no model patch): the smoke run was alive at 60 s and the
sustained run was still running at its 600 s limit without having failed (R2 (iii): "not completion"); no audit strike. Stated as the pre-registered rule states it: the documented command ran, not that the paper's result was reproduced.

## The ten entries

| # | entry | verdict | cost (API-reported, with the estimate of killed steps) | blocker family, cause (basis) | rubric | the same key applied to what harness-v1.7.2 would have reported |
|---|---|---|---|---|---|---|
| 1 | kartikgupta-at-anu__spline-calibration | BLOCKED DATA_MISSING | $0.52 | Data DATA_MISSING (class_default) | ACTIONABLE | actionable |
| 2 | stephaneckstein__minmaxot | BLOCKED DATA_MISSING | $3.98 | Data DATA_MISSING (class_default) | not actionable | not |
| 3 | ml-jku__DeepRC | TIMEOUT  | $8.70 (over the cap; estimate only) | Resources TIMEOUT (evidence) | ACTIONABLE | not |
| 4 | demonzyj56__E3Outlier | BLOCKED SYS_LIB_MISSING | $1.49 | Environment SYS_LIB_MISSING (class_default) | ACTIONABLE | actionable |
| 5 | ioanabica__SCIGAN | BLOCKED DATA_MISSING | $0.34 | Data DATA_MISSING (class_default) | ACTIONABLE | actionable |
| 6 | csm9493__UCL | INDETERMINATE DEP_MISSING | $2.90 (over the cap; estimate only) | Dependencies DEP_MISSING (class_default) | ACTIONABLE | not |
| 7 | Rose-STL-Lab__DIVE | BLOCKED DATA_MISSING | $0.52 | Data DATA_MISSING (class_default) | ACTIONABLE | actionable |
| 8 | optimass__Maximally_Interfered_Retrieval | RUNS_AFTER_REPAIR APT_MIRROR_GONE | $0.49 (+ $9.12 sustained, estimated) |   () | (ran: not scored) |  |
| 9 | aviralkumar2907__MMCE | INDETERMINATE API_REMOVED | $2.49 | Dependencies API_REMOVED (class_default) | ACTIONABLE | not |
| 10 | mims-harvard__g-meta | BLOCKED DATA_MISSING | $0.84 | Data DATA_MISSING (class_default) | not actionable | not |

Spend (API-REPORTED, not billed): entries $22.28 + the sustained run $9.12 (an ESTIMATE: the client's wait ended before the API returned a result) = **$31.40** of the
$100.00 TEST-C cap. Ledger now $161.31 API-reported of the $300.00 ceiling. The BILLED balance after TEST-C is **not yet read** (owner's account page): it is requested in the report.

## By blocker family (pre-registered stratification)

The runner's strata (`by_blocker_family` in `test_c_result.json`): **Data 5** (spline-calibration, minmaxot, SCIGAN, DIVE, g-meta), **COST_CAP 2** (UCL, MMCE: stopped by the $2.50 entry cap during an install; not a verdict on the repository), **Environment 1**
(E3Outlier), **Resources 1** (DeepRC TIMEOUT). By the report's own family field (the scorer's view) the two cap-stopped entries sit under Dependencies. Actionable per family as scored: Data 3 of 5, Dependencies (the two cap stops) 2 of 2, Environment 1 of 1, Resources 1 of 1.

## What the 7 of 9 does and does not say (the caveats are part of the result)

1. **Six of the seven are class defaults, not the new evidence-driven rules.** Only the TIMEOUT diagnosis (#3) and the two spend-cap statements (#6, #9) are v1.8 additions; the other four actionable diagnoses are the per-class sentences
   harness-v1.6 introduced, filled with the path or package of the evidence line. **None of the evidence-driven rules of `diagnosis.py` fired on any of the ten entries** (they were written from the 21 DEV records and none of TEST-C's causes matches one).
2. **The counterfactual, DERIVED and labelled: the same key applied to the blockers harness-v1.7.2 would have reported scores 4 of 9** (`counterfactual_v172.py`, `diagnosis_test_c_score_as_v172.json`; the v1.7.2 `blocker.report` imported from a checkout of its tag).
   The three it loses are exactly the v1.8 additions (the TIMEOUT diagnosis, and the two cap statements the key asks for: a diagnosis that does not say the spend cap stopped the run misses a fact the record shows). So **the measurable v1.8 gain on a fresh set is 3 entries of 9, and it comes
   from naming the TIMEOUT and the cap stop, not from the DEV-fitted rules.** The key's `spend cap` requirement is a choice of the key's author; without it C06 and C09 would pass under v1.7.2 too and the gain would be 1 entry.
3. **Two entries are not actionable, for stated reasons.** #2 minmaxot: the program finished its optimisation and failed in `np.savetxt('output/objective_values_base...')` because the directory `output/` does not exist; the report says "the dataset the repository expects
   at output/objective_values_base1_0, obtained as its README describes" (D-72: a write target classified as missing data). #10 g-meta: the sentence reads "the dataset the repository expects at Features file not found in any of: {tried_paths}" (D-73: a template filled with a line of source code,
   with a literal `{tried_paths}`), and it never names the `PATH/G-Meta_Data/arxiv/` placeholder the documented command carries.
4. **The key is lenient in one place, disclosed:** #4 E3Outlier passes because its key regex accepts the word "apt"; the report names `libGL.so.1` while the run's final error is `libgthread-2.0.so.0` (both belong to the same opencv system libraries). Judged strictly (requiring `libglib2.0-0`) it fails and the figure is 6 of 9 (67 percent), still above the 50 percent threshold.
5. **The key was not fully blind.** Before writing it the author had seen the verdict lines and the runner's family strata (the family and class of each blocker: never a sentence, an error line or a next action), never a `blocker` sentence; `raw_evidence.py` printed the raw log without the report. A3 is a lenient lexical test (rubric, "Known limits").

## What else the records show (not scored)

* **#1 spline-calibration: seven candidates exited 0 by skipping the missing inputs** ("Warning: File saved_logits/... not found. Skipping." thirteen times, then "Finished successfully"). The gate passed them (no rule covers it); the adjudicator adopted none and the verdict stayed `BLOCKED DATA_MISSING`: the guard against the false success was
  the adjudicator, not the gate (D-74). Not counted as a run.
* **#5 SCIGAN: nine of nine patches rejected `PROTECTED_PATH_MODIFIED`** because the documented command is `test_SCIGAN.py` (D-55, gate semantics deliberately unchanged); the cause was missing data (`datasets/tcga.p`), which no patch would have supplied.
* **#2 minmaxot recorded $3.98 and #3 DeepRC $8.70 (the killed 600 s baseline, an estimate)** against the $2.50 entry cap; both are labelled (`over_cap_estimated_only`). #6 UCL ($2.90) and #9 MMCE ($2.49) were stopped by the cap during an install (D-71, D-60).
* **Median wall-clock and cost to a diagnosis (non-running entries):** 575 s and $1.49 (`reports/dev/v18/set_metrics.json`, key `test_c`); recovery 1 of 9 entries whose as-published run failed.

## Defects recorded (known limits, none fixed: harness-v1.8.0 is frozen for TEST-C)

D-72 a write target classified DATA_MISSING (minmaxot); D-73 the DATA_MISSING sentence built from a source line when the error names no path (g-meta); D-74 candidates that exit 0 by skipping missing inputs pass the gate (spline-calibration); D-75 TEST-C draw picked a documented
command that is a `test_*` file (SCIGAN, D-55 again); registered in `reports/corpus-v2.1/candidate_v1.3.3_defects.md`.
