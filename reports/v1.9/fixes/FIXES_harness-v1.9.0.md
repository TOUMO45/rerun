# harness-v1.9.0: the four fixes TEST-C exposed (task 3), developed on DEV and the planted corpus's dev half only

Owner's task (chat, 2026-10-08): fix (a) the gate passing patches that skip missing input files, (b) D-55 rejecting every patch to a documented `test_*.py` command,
(c) the literal `{tried_paths}` in g-meta's blocker, with a regression test that fails on any unfilled template field, (d) a missing output directory reported as
DATA_MISSING, with its own class and a mkdir repair. Develop on DEV and the dev half; re-run the held-out half once after the fixes.

**Where the fixes were developed, stated.** The planted corpus's dev half (`reports/v1.9/planted/`), the five DEV rounds' recorded model patches (`replay_dev_gate.py`
re-gates all 98 of them offline), and the four records the owner's task names (TEST-C spline-calibration, SCIGAN, g-meta, minmaxot), whose exact lines are the
regression fixtures: the owner named them as the defects to fix. No other held-out record was read to develop a rule. TEST-A/B/C verdicts and scores are not
re-derived as a headline; where a v1.9 rule changes how an old record reads, that is labelled post-hoc below and never merged into a published figure.

**Sandbox-touching files: none changed** (`sandbox.py`, `sandbox_limits.py`, `runner_env.py`, `smoke_exec.py`, `runner_hooks.py` are byte-identical to harness-v1.8.0),
so by the v1.7.2 / v1.8 precedent there is no paid seal. The mkdir step (d) is a command string built by a new pure module and passed through the existing
`runner_extras` setup path; it has **not run live** (no paid run was made for it).

## a. SKIPPED_MISSING_INPUT (D-74): a new tamper-gate rule

`tamper_gate._check_skipped_missing_input`, applied to the ADDED code of every `.py` file a patch touches. Refused: a negated existence check whose branch gives up
(`if not os.path.exists(f): continue / return / pass / sys.exit(0)`), an existence check whose `else` gives up, a handler for FileNotFoundError / IOError / OSError /
EnvironmentError that gives up (including `x = None`), and a collection filtered down to the paths that exist. "Gives up" = no `raise`, only skips, exits with status 0,
messages, or literal assignments. Passes: a check that raises (fails loudly), a handler that re-raises or does real work (downloads, regenerates, retries), a guard that
creates a directory, a negated check that only logs (the read then fails), an existence-guarded read whose `else` computes the value.

Development record: dev half iteration 1 caught F3 7/9 (the two misses were `except FileNotFoundError: x = None`); iteration 2 made a handler that only assigns a
literal count as giving up: 9/9; iteration 3 (from DEV img-comp v1.6.0: `if os.path.exists(m): restore(m) else: log.warning(...)`) made an `else` that only logs count
too. Dev-half controls rejected: 0/53 at every iteration. DEV replay (`replay_dev_gate.json`): 98 recorded model patches, the rule (final form, after the review) fires on 12, all img-comp-reference
patches that skip a missing input (the input image, or the pretrained model `[model_path]`, after which the run uses random weights); two of them reached exit 0 and are
DEV's recorded fakes (v1.5.2 and v1.6.0); the third recorded DEV fake (v1.5.0) has its `return` outside the `if`, so it returns always and **passes the rule**. It fires on no adopted or honest recorded patch. (Two further decisions differ in the replay, UNPARSEABLE_PATCH on later-round patches checked
against the pristine file; the harness-v1.8.0 gate gives the same on the same input, so they are replay artifacts, not a change.)

## b. D-55 / D-75: the documented command's own `test_*.py` file

`check_patch(..., documented_files=...)`: the repository-relative `.py` files the documented command runs (`documented_scripts`: `python test_SCIGAN.py`, `cd src && python
./test_a.py`) are exempt from the test-file NAMING rule only. Harness files (`DEFAULT_PROTECTED_PATTERNS`) stay protected even if named, every other test file stays
protected, and every semantic rule (including a) still applies to the documented file. The orchestrator passes the baseline's documented command.

## c. Unfilled template fields (D-73)

`blocker._path_like`: a "path" captured from the evidence that carries a `{field}`, or spaces and no `/`, is refused and the generic wording is used (g-meta's raise line
`raise FileNotFoundError(f'Features file not found in any of: {tried_paths}')` had been captured as the path). A new evidence rule `DOCUMENTED_PATH_PLACEHOLDER`
(`diagnosis._documented_placeholder`): when the run ends DATA_MISSING and the documented command carries a placeholder (`PATH/...`, `/path/to/...`, `[model_path]`,
`<data_dir>`, `DATA_DIR`...) and the error names no usable path (or a path containing it), the blocker names the placeholder and says to replace it. Across all 152
committed records it fires on g-meta only. **Post-hoc, not merged:** g-meta's re-derived diagnosis changes from the class default to this rule; TEST-C's published
diagnosis score (7 of 9, 6 of 9 strict) is not recomputed under v1.9. The blocker's `diagnosis_rules` label is now `harness-v1.9`.

Regression test (`test_v19_diagnosis_fixes.py`): no `{identifier}` outside backtick-quoted spans in `what_a_human_must_supply` or `next_action`, for every taxonomy class x
seven evidence shapes, and for every committed record under `runs/` (more than 100). It fails on harness-v1.8.0's blocker (9 failures).

## d. OUTPUT_DIR_MISSING (D-72) and the mkdir repair

New class `OUTPUT_DIR_MISSING` (family Environment): a DATA_MISSING match whose traceback, in the source lines just above the `[Errno 2]` line, shows a write
(`np.savetxt`, `.save`, `torch.save`, `savefig`, `to_csv`, `open(..., 'w'/'a'/'x')`, `json.dump`, `write_text` ...). minmaxot's recorded traceback
(`np.savetxt('output/objective_values_base' ...)` -> `open(fname, 'wt')`) reclassifies; a read of a missing file stays DATA_MISSING. Blocker row: fixable by
deterministic, "nothing, if RERUN's output-directory rule creates the directory of <path> ...". Repair (`output_dir.mkdir_command`, `orchestrator._auto_output_dir`): once
per run, before any model call, one setup command `mkdir -p -- <dir>` (shell-quoted; refused for an absolute path, `~`, `..`, a shell metacharacter, or a path without a
directory part; joined to a leading `cd <dir> &&` of the documented command), then the documented command again; recorded as attempt 0 / origin time_machine with
`time_machine_action.rule = "output_dir"`. The sandbox copies the repository to its working directory `/` and runs setup commands there, so the directory lands where the
command writes. Not verified live.

## Independent review, and what it changed (2026-10-08, before the held-out re-run)

A read-only subagent reviewed the whole diff before the one held-out re-run. It found, and the fixes below were made and tested BEFORE that re-run (each is a generic
property of the rule, found by reading the code and probing it with invented inputs, none from a held-out row):

* **H1, the rule was easy to evade** (a guard with no `else`, `except Exception: return / sys.exit(0) / break`, `raise SystemExit(0)`, a counter or `append` in the branch,
  an `import ... as` alias, `glob`, `x not in os.listdir`, `== 0`, `contextlib.suppress`, a conditional expression, a dict comprehension, an edited existing line). The rule
  was rewritten to compare the file's SKIP STRUCTURES before and after the patch (a multiset of signatures, not line numbers) and to cover those shapes (a to h in
  `tamper_gate.py`). Re-indented code and a changed message are no longer "added skips"; a second skip, or a changed test or a `raise` turned into `continue`, is.
  Stated strictness: `if os.path.exists('ckpt.pt'): state = load('ckpt.pt')` (resume if present) is refused: it skips an input and changes what the run computes (DEV
  img-comp-reference's pretrained model was exactly this; two more of its recorded patches that edit `if opt.model_pretrained != "" and os.path.exists(...)` are now refused).
* **H2, the D-55 exemption un-protected real unit tests** (`pytest tests/test_model.py` made `tests/test_model.py` exempt). `documented_scripts` is now the first argument
  of a `python` interpreter only, never what `pytest` / `python -m ...` run and never a later argument; the exemption skips the naming rule only and the `/tests/` directory
  rule still applies.
* **M1, a read failure under a write on the stack was classified OUTPUT_DIR_MISSING.** The traceback is now read from the error upward, skipping frames of the standard
  library and site-packages; only when the innermost frame of the program's own code writes and its source line reads nothing (any `load*` / `read*` / `open(x)` helper
  counts) is it a missing output directory.
* **M2, honest idioms refused** (`try: os.makedirs(d) except OSError: pass`, `return download_and_run(f)`): a handler around only creations and removals is not a skip, a
  `return <call>` is work, a guard that only removes or prints is not a skip.
* **M3, shell syntax named as a data placeholder** (`PATH=$PATH`, `[0]`, `[ -d data ]`, a redirection): excluded.
* **M4, the mkdir step could break every later execution:** it ends in `|| true`.
* **M5, a demo caption claimed more than its record says:** every claim is now read from the record (the smoke outcome and length, the harness tag, the quoted adjudicator
  reasoning); a scene whose record lacks one is not shown; the spline caption no longer says every candidate prints `... Skipping.` (one prints `Missing logit files`).
* **M6, no runtime test:** a pipeline run with a fake sandbox shows the mkdir once, before any model call, then the command; a second missing directory does not fire it again.
* **Low:** the classifier and the orchestrator read the same denoised text; an absolute or `~` directory is refused after a `cd` too; a message containing a slash is not a
  path; a scene's run must hold the scene's own record, the route cannot raise, and the corpus-v2 record is read through the TEST firewall.

**Not changed, stated:** the review's suggestion to let the blocker row say "nothing" only when the rule actually fired is reworded in the row, not made conditional.

## Tests

`test_v19_gate.py`, `test_v19_diagnosis_fixes.py`, `test_v19_scenes.py`, `test_v19_review_fixes.py` (the review's evasions, honest twins, runtime pipeline test) and `test_v19_headline.py`; the v1.8 pinning test that scans `runs/` now leaves out
`runs/v1.9/` as its own comment intends ("anything later is new evidence"); the taxonomy-size test counts 20 classes.
