# harness-v1.10 pass: one live run of the whole pipeline at release candidate 4, on minmaxot — plan (committed before the run)

**Post-hoc, a check of the wiring and never a measurement or a result of any set.** The behavioural checks were measured by a driver that rebuilds the candidate procedure from the harness's functions
(`reports/v1.10/pipeline/measure.py`); the orchestrator's own wiring (`_behaviour_static`, `_trace_plan`, `_candidate_run`, the veto, the record) has run only against the fake cloud of the test suite. This run puts
it through the real pipeline once: `scripts/live_run.py` at the tag `harness-v1.10.0-rc4` (a git worktree), `--dev-run`, the corpus-v4 entry `stephaneckstein__minmaxot` (the same repository and commit as the
Task 5 run), **cost cap $5.00**. The record is not merged into TEST-C or any rate.

What it can show, and the criteria written before it runs:

1. **A model candidate is judged by the checks inside the loop.** The record has at least one attempt with a `behaviour` field: a candidate refused before its run (`gate_decision` REJECT whose violations carry a
   reason name from `behaviour.STATIC_REASONS`) or a candidate with `behaviour.trace.status` `ok` or `missing`, and the log shows the `behaviour check` lines.
2. **The tracer works through the pipeline.** For each candidate that ran, `behaviour.trace.status` is `ok` (a report arrived through `_candidate_run`), the tracer's line is in no attempt's `stderr_tail`, and no
   command given to the sandbox other than the launcher payload names `RERUN_BEHAVIOUR`.
3. **What happens to the environment-variable candidate of the Task 5 run** (`os.environ['PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION'] = 'python'`, the one the adjudicator chose then) is recorded as it is: adopted, or
   refused with a named reason.
4. The verdict is whatever it is (RUNS_AFTER_REPAIR as in Task 5, or BLOCKED because the checks refused what the model proposed); it is reported, not judged.

What it cannot show: that v1.10 is better or worse on any rate (one run, a sampled model); anything about cheats.

## Deviation, written before the run that counts (2026-10-09)

* **First attempt at rc4: INFRA_ERROR, no model call.** Launched 2026-10-09 03:30; the `git fetch` of the repository timed out 4 x 300 s (about 12 KB/s from this machine to GitHub
  that night). Record kept as `runs/v1.10/live_v110/attempt1_infra_error_git_timeout.json` with its stdout and launcher lines. Nothing about the pipeline was observed.
* **The run moves to release candidate 5.** Before the second attempt the live seal of rc4 found a tracer defect on Python 3.9+ (a script run from `/` is named `//train.py`;
  `runs/sandbox_verification/v1.10-seal-rc4/NOTE.md`), fixed in `harness-v1.10.0-rc5`, which also turns the checks off by default. The wiring check is meant to show the
  orchestrator's wiring of what would be tagged, so it runs at `harness-v1.10.0-rc5` (worktree `.claude/worktrees/v110-rc5`) with `BEHAVIOUR_CHECKS=true` in the launcher's
  environment. The criteria above are unchanged. The orchestrator's wiring is the same in rc4 and rc5 (one comment differs).
* **Transport:** the repository is read from a local bare mirror of the same commit (`GIT_CONFIG_*` `insteadOf` in the launcher), built one blob at a time because the link
  dropped every long transfer. The commit, the pipeline and every harness file are unchanged by it.

## Second deviation, written before the run that counts (2026-10-09, the flag-mode pass)

* **Attempt 2 at rc5: INFRA_ERROR, no model call.** Launched 2026-10-09 10:39 from this machine with the repository read from the local mirror: the pipeline reached the sandbox
  (python:3.7-slim, 95 files verified against the tree) and the upload of the 20 MB tree timed out four times (the harness sizes that timeout for 0.987 MB/s; this machine
  uploaded at 0.16-0.4 MB/s). Record `runs/v1.10/live_v110/attempt2_rc5_infra_error_upload_timeout.json`.
* **The run that counts is at the flag-mode release candidate, on a GitHub Actions runner** (owner's decision of 2026-10-09: the workflow
  `.github/workflows/v110-seal.yml`, dispatched by hand, after the seal of the same candidate in the same job, never beside another paid run), `scripts/live_run.py` at the
  checked-out release candidate, `--dev-run`, cap $5.00, `BEHAVIOUR_MODE=flag` (the shipped mode). The record goes to `runs/v1.10/live_v110/02_stephaneckstein__minmaxot_<rc>.json`.
* **The criteria above, read for the flag mode** (the mode changed, so their wording does; nothing is added after the run):
  1. a model candidate is judged by the checks inside the loop: at least one attempt carries `behaviour.mode = "flag"`, and the log shows `behaviour check FLAGGED` lines or
     none (none is a finding too);
  2. the tracer works through the pipeline: every candidate that ran has `behaviour.trace.status` `ok`, the tracer's line is in no attempt's `stderr_tail`, and no command
     other than the launcher payload names `RERUN_BEHAVIOUR`;
  3. what happens to the environment-variable candidate of the earlier run (`PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python`) is recorded as it is: adopted clean, adopted
     with REVIEW_REQUIRED, or not proposed this time (the model is sampled);
  4. the verdict is whatever it is, and **it must not depend on the flag**: no attempt is refused by a behavioural finding (`behaviour.refused` absent everywhere), and the
     certificate carries `review` exactly when an adopted attempt is `flagged`.
