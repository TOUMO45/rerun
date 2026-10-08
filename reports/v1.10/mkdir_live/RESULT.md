# harness-v1.10 pass, task 5 — the live check of the output-directory repair on minmaxot: result

**Labelled post-hoc. Never merged into TEST-C.** TEST-C's minmaxot record (`runs/corpus_v4_batch/harness-v1.8.0/treatment/02_stephaneckstein__minmaxot.json`: BLOCKED, DATA_MISSING, $3.98) is unchanged and stays the
published figure (RAN 1 of 10). This is one paid run of the same repository at the same commit (3f88502) through the real pipeline at **harness-v1.9.0** (the tag, from a git worktree), `scripts/live_run.py`
`--dev-run`, entry cap **$5.00**. Plan and success criteria: `PLAN.md` (committed 96a26b8, before the run). Record: `runs/v1.10/mkdir_live/02_stephaneckstein__minmaxot_v190.json`.

## What happened

| step | record |
|---|---|
| baseline (as published, `python dcot/base_case.py`, python:3.7-slim) | fails: `TypeError: Descriptors cannot not be created directly.` (protobuf) |
| attempt 1, three candidates, all exit 1 on the next error | cand. 1 and 2 set `PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python` in `dcot/base_case.py` (before / after the `numpy` import), cand. 3 pins `protobuf==3.20.0`; the adjudicator chose **candidate 2** |
| the run after it | `FileNotFoundError: [Errno 2] No such file or directory: 'output/objective_values_base1_0'` at `np.savetxt('output/objective_values_base' + ...)`; classified `OUTPUT_DIR_MISSING` |
| **attempt 0, origin `time_machine`, rule `output_dir`** | `mkdir -p -- output || true` on the image, then the documented command again: **exit 0, `alive_at_limit`** (still running at 60 s with output and no traceback) |
| verdict | **RUNS_AFTER_REPAIR** (smoke level); labels: first error cleared by the model, environment resolved, entrypoint runs; error chain: protobuf TypeError cleared by attempt 1, `OUTPUT_DIR_MISSING` cleared by attempt 0 |

Cost: **$3.73 API-reported** ($3.695 sandbox + $0.036 model; no estimated part) against the $5.00 cap, 399 s of pipeline time.

## Against the success criteria written before the run

1. *The repair fires* — **yes**: attempt 0 / origin `time_machine`, `rule` = `output_dir`, `command` = `mkdir -p -- output || true`, directly after the failing run classified `OUTPUT_DIR_MISSING` with the quoted error.
2. *What happens next is recorded as it is* — the command ran again with `output/` present and stayed alive past the smoke limit (RUNS_AFTER_REPAIR). It did not meet a next blocker inside the 60 s window and the cap was not hit.
3. *What it cannot show* — that minmaxot "runs" beyond the smoke criterion: the run was stopped by RERUN at 60 s, not finished, and nothing here says the computation's outputs match the paper's.
   The two records have the same shape up to the second error: TEST-C's v1.8.0 record has the same protobuf `TypeError` first (cleared by a model candidate in attempt 1) and then the same
   `FileNotFoundError: ... 'output/objective_values_base1_0'`, which v1.8.0 classified `DATA_MISSING` (BLOCKED, human must supply a dataset); at v1.9.0 the same error is classified `OUTPUT_DIR_MISSING`
   and repaired by the rule. The model candidates differ between the two runs (a model is sampled), so this is one live run, not a controlled comparison.

Nothing about TEST-C, DEV or any rate changes.
