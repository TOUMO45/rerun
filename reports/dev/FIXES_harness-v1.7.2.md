# harness-v1.7.2 — fixes for D-46 and D-47 (offline only)

Written 2026-10-05, after the TEST phase. Nothing here was run live: no Nebius, Tavily or model call, no tag, no push. No record under `runs/` and no
`seal_verification.json` entry was changed. **Not retroactive:** every stored record keeps its verdict (TEST #18 stays RUNS_CLEAN in its record and in
the pre-registered count). The new logic applies only to runs made from this version on, and every verdict it changes carries a label.

## Fix 1 — D-46: exit code 0 no longer counts as success whatever the run printed

New module `backend/app/services/exit_zero_check.py`. It is pure and does not touch the sandbox. The orchestrator calls it on the final step of
every operation it runs, except the evidence run. It looks only at a step of the repository's own command (`repo_run`) that exited 0, and it uses
the streams the sandbox returned. Its findings:

| finding | rule | what happens |
|---|---|---|
| (a) traceback | stderr ends with an uncaught `Traceback (most recent call last):` block and its exception line, nothing after it; not an `Exception ignored in:` shutdown report; not `SystemExit`; step under 60 s | not a pass: classified from the traceback (unchanged classifier) and handled like any failed run (deterministic steps, repair) |
| (b) usage | step under 5 s, no traceback, and the whole output is a usage/argument message: the first line matches a usage pattern (`usage:`, `please specify`, `the following arguments are required`, `--help`, …) and every other line is shaped like help text | INDETERMINATE **`ENTRYPOINT_NEEDS_ARGS`**, with the usage line quoted; no classification, no repair, no model call |
| (c) missing input / credential (added at the coordinator's request) | step under 5 s, no traceback, output of at most 6 lines and 800 characters, the first line says something is missing or required, and no line looks like work (a percentage, an epoch/step/loss figure, a number with a unit) | INDETERMINATE **`NEEDS_CREDENTIALS`** when a line names a key, token, credential or registration; otherwise `ENTRYPOINT_NEEDS_ARGS`. The first line is quoted |

The rules lean towards leaving a run alone. These are never overruled:

- a traceback followed by more stderr output (an exception that was caught and logged);
- a traceback that is the last thing on stderr when the step took 60 s or more. This is a stated limitation: a pipeline whose first command crashes
  late is not caught;
- a usage-like or "missing" word inside real output;
- a smoke run that was still alive at its limit (`RERUN_SMOKE_ALIVE`);
- any non-zero exit (the classifier handles those, as before).

**What a run's record carries.** An overruled run keeps its real exit code, 0, everywhere. Beside it, the run carries `exit_zero_check`
(`{overruled, kind, evidence, seconds, rule, code?, version}`). This sits on the baseline, on the attempt's `execution`, on the candidate's `stage`
and on the error-chain link it added. The verdict label (`outcome_levels.verdict_label`, the ladder and the blocker) adds
**`exit 0 overruled: <evidence>`**, and the frontend badge shows `EXIT 0 OVERRULED`.

**Readers that used to treat exit code 0 as "passed".** These now use `outcome_levels.attempt_passed`: the adjudicator's `stage_rank`,
`advance_key`, `partial_progress_choice` and `_deterministic_choice`; the ladder; and `sustained_run.final_run_of`. A record without the field reads
exactly as before.

**Sustained run.** `sustained_run.outcome_of` does not call an overruled exit 0 "completed".

**`set -o pipefail`: not added.** It could be added outside the sandbox-touching files, because the orchestrator builds the command. It was not
added, for three reasons:

- The documented command runs through the sandbox's own `/bin/sh`. Offline, I cannot check that this shell supports `pipefail` (dash before 0.5.12
  does not).
- The baseline must run the documented text unchanged, so CONTROL and TREATMENT stay comparable.
- Changing what runs inside the sandbox would need a live check.

Finding (a) already catches TEST #18.

**Evidence replayed:**

- **TEST #18.** The 154-byte traceback is rebuilt, and its SHA-256 equals the stored `5c4c19a4…1164`. The run step took under 1 s, computed from the
  operation record. The real orchestrator, driven with a fake sandbox that returns exit 0 with that stderr, now gives `FAILS` at baseline with
  DEP_MISSING. The verdict is not RUNS_*.
- **DEV #12 (`Please specify the model name using -m.`).** Ends `ENTRYPOINT_NEEDS_ARGS`.
- **The live scan of `faris-shi/py_weather_cli`.** The stdout is copied into the test. Replayed as the run after a model repair, it ends
  `NEEDS_CREDENTIALS`.

## Fix 2 — D-47: a repair patch written with the wrong indentation for its file

New module `backend/app/services/indentation.py`, pure.

1. **Repair prompt.** `repairer.build_repair_user_prompt` adds one line naming the target `.py` file's indentation, for example
   `Indentation of run_models.py: TABS (one tab character per level; …)` or `… 4 spaces per level`. The convention is read from the file's INDENT
   tokens.
2. **Normalising before the gate.** In the orchestrator, after the patch pipeline and before `check_patch`, `normalise_patch` acts only when a
   patched `.py` file fails `ast.parse` with an `IndentationError` or `TabError`, **and** the patch's convention differs from the file's: spaces in a
   tab file, or a different readable space unit in a space file.
   - The added lines' leading whitespace is rewritten to the file's convention.
   - Each changed group is anchored at the level of the file line it replaces. The model's own relative structure is kept; continuation lines go one
     level under their statement; string contents are never touched.
   - The result must parse, must change no non-whitespace character, and must pass `git apply --check`. Otherwise the original patch goes to the gate
     unchanged and is refused as before.
   - The gate then runs **every** rule on the normalised diff, and py_compile runs after it. That diff is the one applied.
   - The attempt records `indentation_normalised: [{file, from, to, lines, parse_error}]` and a patch note. `model_patch` keeps what the model sent.

**Evidence replayed.** `run_models.py` itself is not in the repository and was not fetched. The 17 lines the six recorded diffs keep or remove
(lines 90–98 and 222–229) are rebuilt from the diff text of `runs/live_ui/2026-10-05_dev15_latent_ode_api_certificate.json`. The rest is marked
scaffolding: filler comment lines, plus five lines that give the hunk at line 222 its `if/elif`. On this reconstruction the current gate reproduces
**all six recorded refusals word for word**, including line numbers. After normalising, **all six patches parse and PASS every gate rule and
py_compile**. No fixture was skipped.

## Also added (coordinator's request): R6 "injected default"

`tamper_gate.injected_default(diff)` flags a `.py` hunk in which an added line assigns a literal (a string, number or bool) to a name, **and** one of
these holds:

- the hunk removes a `raise`;
- the assignment sits directly under an added or kept `if`/`elif` that tests that name for being empty, false or None.

The flag is stored as `semantic_change: ["injected default"]` on the attempt record (`AttemptRecord.as_dict`), so the verdict reads
`… (semantic change)`. It is **not** added to `semantic_change_calls`. That keeps it non-retroactive: the ladder recomputes an unstored flag from
`semantic_change_calls` alone, so an old record read again is never newly flagged. The weather-cli scan's chosen patch and its raise-removing
sibling are both flagged.

## Tests — `backend/tests/test_v172_exit_zero_and_indentation.py` (30 tests)

**Before the change, at base commit 016c825** (`git archive` into a scratch folder, new test file copied in):

- As is: the file does not import (`exit_zero_check` does not exist), so 30 of 30 error.
- With only the two new pure modules copied in, and none of the wiring: **9 failed, 21 passed**. The 9 that fail are every test of a changed
  behaviour:
  - TEST #18 replay;
  - overruled-then-repaired;
  - usage → ENTRYPOINT_NEEDS_ARGS;
  - weather → NEEDS_CREDENTIALS;
  - the reader of old records;
  - the sustained run;
  - the repair prompt;
  - the in-pipeline D-47 normalisation;
  - R6 injected default.
- The 21 that pass are of three kinds: unit tests of the two new modules, checks of the recorded evidence (the SHA-256, and the gate's six refusals
  on the reconstruction), and the negative controls, which by design hold on the old code too.

**After the change:** 30 of 30 pass. Full suite (`backend/tests`, offline): **1866 passed, 19 skipped**, 0 failed (383 s).

## Files changed

- New: `backend/app/services/exit_zero_check.py`, `backend/app/services/indentation.py`, `backend/tests/test_v172_exit_zero_and_indentation.py`, this
  report.
- Changed:
  - `backend/app/services/orchestrator.py`
  - `backend/app/services/tamper_gate.py` (added `injected_default` only; no rule changed)
  - `backend/app/services/adjudicator.py`
  - `backend/app/services/outcome_levels.py`
  - `backend/app/services/blocker.py`
  - `backend/app/services/repairer.py`
  - `backend/app/services/sustained_run.py`
  - `frontend/src/components/VerdictBadge.tsx`

**Sandbox-touching files (`scripts/run_corpus_v1_batch.py` SANDBOX_TOUCHING_FILES): none changed.** `sandbox.py`, `sandbox_limits.py`,
`runner_env.py`, `smoke_exec.py` and `runner_hooks.py` are byte-identical, so the v1.7.1 seal's `code_files` hashes still hold and **no new seal is
required by these changes**. `backend/app` and `frontend/src` are HARNESS_PATHS, however, so a batch run on this code needs its own harness version
tag (harness-v1.7.2), which the owner decides.

## Open, stated

- **New reason codes.** `ENTRYPOINT_NEEDS_ARGS` and `NEEDS_CREDENTIALS` are not in `scripts/compare_batches.py` NOT_MEASURED_REASONS or in
  `run_corpus_v1_batch.py`'s summaries. Those scripts are unchanged. A batch summary would currently count such an entry in the repository's
  INDETERMINATE column. Whether either code is "RERUN's fault" (`OUR_FAULT_CODES`) is also left to the owner.
- **Limits of findings (b) and (c).** Both are text heuristics. They can miss a message worded otherwise, and they could flip a 1-second run whose only
  output really is "missing X" while it did its job.

## Added after the live scan of 2026-10-05 (`reports/live_scan/SCAN_2026-10-05.md`)

- **Entrypoint discovery sees module-level scripts** (`intake.find_entrypoint_candidates`, `_is_module_level_script`). Three of the five scanned repositories were scripts that run at import with no `__main__` guard (pdf-to-powerpoint `convert.py`, pyqver `pyqver2.py`/`pyqver3.py`, insta-dl `insta-dl.py`), so recon stopped ENTRYPOINT_UNCLEAR before running anything. A file is now also a candidate when an unindented line reads `sys.argv`, parses arguments, calls `getopt.getopt` or enters a GUI `mainloop()`. A text rule, not an AST one, because Python 2 scripts do not parse under Python 3. Package, setup, test and docs files are excluded; a library that reads `sys.argv` only inside a function is not a candidate. Checked against the four real files at their scanned commits: all four found, each on the expected line.
- **A failed run that lacks its arguments or a display stops INDETERMINATE** (`entry_blockers.py`, called in the orchestrator right after the exit-0 stop): an `IndexError` raised on a line that reads `sys.argv`, or argparse's "the following arguments are required" with exit status 2, ends `ENTRYPOINT_NEEDS_ARGS`; tkinter's "no display name and no $DISPLAY environment variable" (or "cannot connect to X server") ends `DISPLAY_REQUIRED`. The evidence line is quoted; no classification, repair or model call follows (a model could only invent the input, which is the injected-default pattern, or cannot supply a display at all).
- Tests: `backend/tests/test_v172_entry_discovery_and_blockers.py`, 6 tests, all pass; with the two wiring changes removed, 4 fail (both discovery tests and both replays). Full suite with everything in v1.7.2: 1872 passed, 19 skipped, 0 failed.
- Sandbox-touching files: still none changed (`intake.py`, `orchestrator.py` and the new `entry_blockers.py` are not in `SANDBOX_TOUCHING_FILES`).
