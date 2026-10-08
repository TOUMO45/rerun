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
