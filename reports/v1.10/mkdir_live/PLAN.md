# harness-v1.10 pass, task 5: a live check of the output-directory repair (D-72) on minmaxot — plan (committed before the run)

**Labelled post-hoc and never merged into TEST-C.** TEST-C's minmaxot record (`runs/corpus_v4_batch/harness-v1.8.0/treatment/02_stephaneckstein__minmaxot.json`, BLOCKED DATA_MISSING at harness-v1.8.0) is
unchanged and stays the published figure (RAN 1 of 10). This run is one paid run of the same repository at the same commit, through the real pipeline at **harness-v1.9.0** (the tag, from a git
worktree; the repair was added in v1.9 and has run only offline), `scripts/live_run.py` with the corpus-v4 entry, `--dev-run` (the record says so), **cost cap $5.00** for the entry
(the cost guard's per-entry ceiling; a stopped step is recorded as ESTIMATED).

What the run can show, and the success criteria written before it:

1. **The repair fires:** the record has an attempt 0 / origin `time_machine` whose `time_machine_action.rule` is `output_dir` with `command` = `mkdir -p -- output || true`, directly after a failing run whose
   error is `FileNotFoundError: [Errno 2] No such file or directory: 'output/objective_values_base...'` and which classified `OUTPUT_DIR_MISSING`.
2. **What happens next is recorded as it is:** the command runs again on the image with `output/` present; the run then either exits 0 / stays alive (RUNS_AFTER_REPAIR, a smoke verdict), or fails on something
   else (the next blocker, as the record states it), or is stopped by the $5.00 cap. The recorded baseline of TEST-C spent $3.98 (an estimate) against a $2.50 cap, so the cap is a real risk; a cap stop is
   a result, not a failure of the check.
3. **What it cannot show:** that minmaxot "runs" in any sense beyond the smoke criterion; the computation had finished before the failing write in the TEST-C record, so success here would mean the same
   computation ran again and wrote its output. Nothing about TEST-C, DEV or any rate changes.

If the repair does not fire, that is reported with the record's own text (`state.output_dir` decision, the classification). Cost is reported API-reported/ESTIMATED as the records carry it and added to the ledger
(`runs/v1.10/` is read by `reports/ledger_total.py`).
