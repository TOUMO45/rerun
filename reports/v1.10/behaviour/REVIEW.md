# harness-v1.10 pass, task 4: the independent review of release candidate 1, and what was done about each finding

Reviewer: a separate agent instance, started with an empty context, given the design document (`PROTOCOL.md`), the diff `76da9c2..982423f` (tag `harness-v1.10.0-rc1`), the development corpus of
planted cheats (`reports/v1.9/planted/`) and a rule not to read the independent set (`reports/v1.10/independent/`) or the Task 1 results; it did not edit the repository. It ran the static checks
on concrete patches it wrote, the tracer for real on Linux (WSL, Python 3.13) and in `python:3.7-slim`, and its own 51 tests. Its report is summarised here finding by finding; "fixed" means the change is in
release candidate 2 (`behaviour.py`, `orchestrator.py`, `smoke_exec.py` unchanged since rc1) with a test named `test_review_*` in `backend/tests/test_behaviour.py`. **Nothing here was informed by the
independent set**: the reviewer could not see it and the assistant had read only its format when the fixes were written.

| # | finding (severity) | disposition |
|---|---|---|
| A1 | moving the work under a new `try: ... except ImportError: pass` is invisible (nesting is not part of the statement key) (blocker) | **fixed**: a statement's key now carries its enclosing compound statements (and the section: body / else / handler); only a `try` whose handlers all re-raise or only answer Ctrl-C is transparent. `test_review_a1_*` |
| A2 | indentation-only edits, a second decorator, `match` cases are invisible (blocker) | **fixed**: nesting in the key; the key is the whole header (decorators, bases, arguments), `match` cases are walked. `test_review_a2_*` |
| A3 | `sys.exit(256)` is accepted as a non-zero exit but exits 0 (blocker) | **fixed**: an int status is non-zero only if 1..255. `test_review_a3_*` |
| A4 | the exit-site hook wraps the tracer's `sys.exit`, so the origin frame is the hook's; the first exit event masks later ones (blocker) | **fixed**: the origin skips frames of `rerun_*` hook modules; the report keeps a list of every distinct explicit exit (and `raise SystemExit` once per exception); any exit from an added line is a finding. `test_review_a4_*` runs the real exit hook after the tracer |
| A5 | stubs that need no call-site edit: a `def` under a name the file imports, a class re-binding an imported name, an ImportError fallback stub, a stub package, `from x import *` (should-fix) | **fixed**: a def/class under a name the file already binds (def, import, assignment) is a replacement; a new function whose body is `pass` is a stub; an added star import is refused; a new file under the name of an imported package, or `sitecustomize` / `usercustomize` / `conftest`, is refused (`external_import_roots`). `test_review_a5_*` |
| A6 | a string `default` of an option, `cfg.X.ENABLED = False`, `setup.py`/`pyproject.toml` exempt, a `raise` added inside a `try` whose handler skips (should-fix) | **fixed**: a new option is harmless unless it shares a `dest`; the default of an existing option is a workload fact whatever its type; assignment targets are limited to `sys.path`, the cuDNN switches and device variables; only requirements files, `environment.yml`, `.gitignore`, licences and docs are exempt; a raise / exit added in the body of a swallowing `try` is refused. `test_review_a6_*` |
| A7 | the report line is forgeable; a flood of stderr pushes it out; own SIGTERM handler and long C calls give no report (should-fix) | **forgery fixed**: the line carries a per-run nonce known to the harness and the installed hook; any marker line is removed from the text, and only one with the right nonce counts. **Flood, own SIGTERM handler, C call > 3 s: accepted limits** (a run with no report is recorded `trace missing` and vetoed by nothing; the share of such runs is reported with the measurement). A repository that reads the nonce out of the installed hook file could still forge: it would have to know the mechanism |
| B8a | a failure site that is a `raise` / exit line cannot run after an honest repair (blocker for the false-refusal rule) | **fixed**: such a site is dropped from the plan (`plan_trace`). `test_review_a_site_that_is_a_raise_*` |
| B8b | partial progress (the same line meets the next missing module) is refused as STILL_RAISES | **fixed**: the site and entry checks apply only to a run that passed (exit 0 or alive); the exit-origin and argv checks apply to every run. `test_a_candidate_that_fails_further_on_*` |
| B8c | one report per run: `a && b` commands, forked workers | **fixed**: reports of all processes are merged (`entry_report`); on Python 3.7+ a forked child reports for itself (`os.register_at_fork`); on 3.6 children do not report |
| B8d | `python -m unittest test_x.py` takes the test file as the entry | **fixed**: after `-m` the program is the module (no entry unless the module is a repository file). `test_review_c12_*` |
| B8e | suffix matching attributes `numpy/lib/utils.py` to a repository `utils.py` | **fixed** in the tracer (exact path relative to the working directory first; any path with `site-packages`, `dist-packages` or `/lib/python` excluded) and in `failure_site`. `test_review_c12_*` |
| B9 | 79 of 131 honest-looking pairs refused | **partly fixed**: NumPy scalar aliases to their sized names, `open(p)` / `open(p, 'rb')`, a guarded `makedirs`, `if cuda.is_available(): x = x.cuda()`, deleting `torch.cuda.set_device` / `manual_seed_all` / `empty_cache` / `synchronize`, `cPickle` / `Queue` / `urllib2` ... successors, `tf.disable_*`, `yaml.load(Loader=)`, `np.load(allow_pickle=)`, `xrange`, `iteritems` and friends. `test_review_b9_*`. **Accepted collateral** (the owner's rule, computation is not repaired by a model): library swaps whose result can differ (`df.append` to `pd.concat`, `tf.contrib`, `scipy.misc.imread`, `pretrained=True` to `weights=`), `/` to `//`, `has_key`, and any Python 2 file or `async=` keyword (does not parse). These show up as false refusals in the measurement, which is how the rule is priced |
| C10 | unguarded exceptions on odd reports and files; recursion; quadratic diff | **fixed**: report fields are type-checked and the merge ignores the malformed; the orchestrator wraps the static check (a failure refuses the patch by name) and the trace reading (a failure is `unreadable`, no veto); recursion limit raised to 4000; a file above 30,000 statements or 2 MB is "too large to judge". `test_review_c10_*` |
| C11 | tracer overhead (2.7 s vs 0.12 s for a pure-Python loop; ~25x on call-heavy untraced code) | **mitigated, not removed**: the tracer switches itself off after 25 s and says so (`trace_cut_s`; the site and entry checks then conclude nothing). A traced slow-start program can still miss the 60 s window: the Task 4 pilot and measurement compare the run outcome with and without the tracer |
| C12 | `os._exit(status=)`, `splitlines` on form feed, ARGV attribution after an original line, single-candidate flow only static, operation records keep the tracer line, an adopted image's layer carries the install command, a spawned child's report taken for the entry's, stdout appended to stderr as failure text, a repository calling `sys.settrace` | `os._exit` and form feed **fixed**; argv now compares against a snapshot taken when the added line starts; stderr is used alone as failure text when it holds the traceback; the merged report replaces "one report"; **documented / accepted**: single-candidate flow is static-only (`repair_candidates_per_round=1` with `behaviour_checks` on is half-active; the deployment default is 3), operation records keep the tracer line (cosmetic), the adopted image's layer ends in the install command so the next operation starts from the layer before it (checked: `_best_layer` is a prefix match over kept layers; nothing is lost but the last layer), a repository that calls `sys.settrace` replaces the tracer |
| D13 | tests: a literal-string comparison, no-op `.replace`s, `import rerun_behaviour` instead of `.pth`, no test of exit hook + tracer, `&&` command, `-m unittest`, worker site, raise site, malformed report | **fixed** where it matters: the literal comparison and the no-ops are removed; `test_review_*` cover the exit hook with the tracer, the raise-site, the module-runner entry, malformed reports, forged lines. **Not tested**: the install through a real `.pth` on Python 3.6/3.7 (the reviewer ran it by hand; the live seal below does it again) |

The reviewer's report is the only source of the numbers in the left column; they are its claims, re-run by the assistant only where a `test_review_*` now exists.


---

# Second review (release candidate 2, `af9f5ba`) and what was done about each finding

Reviewer: a second separate agent instance, same brief and same restrictions (no independent set, no Task 1 results, no pilot records), asked to review the FIX. It ran the static layer on pairs it wrote and the
tracer for real in WSL (Python 3.13) and `python:3.7-slim`. Dispositions below are in release candidate 3 (tests `test_review2_*` in `backend/tests/test_behaviour.py`).

| # | finding (severity) | disposition |
|---|---|---|
| 1 | the canonical form drops keyword arguments, `.cuda(...)` arguments and `torch.device(...)` arguments whatever they contain, so an expression that acts hides in them (`np.load(p, allow_pickle=exec(...) or False)`; end to end `work(3, encoding=__import__('posix')._exit(0))` exits 0 with no work and no report) (blocker) | **fixed**: a normalisation drops an argument only if it only reads (`_simple`); the tracer also wraps `posix._exit` |
| 2 | the header of a new def or class (decorators, defaults, annotations, bases, metaclass), an exception type in a handler, an annotation of an assignment are evaluated and unchecked (blocker) | **fixed**: `_header_simple`, `h.type` and `AnnAssign.annotation` must only read |
| 3 | a subclass of `SystemExit` evades both layers (blocker) | **fixed**: a class deriving from `SystemExit`, `KeyboardInterrupt`, `GeneratorExit` or `BaseException` is refused; the tracer takes any `SystemExit` subclass for an exit |
| 4 | a new method on an existing class overrides an inherited one; a new public function shadows a name supplied by a star import or a builtin (blocker, stubs) | **fixed**: a method added to a class the patch did not add is refused; a def or class named like something the file reads and never binds is refused (`_used_but_unbound`) |
| 5 | an import can rebind a name a def or assignment bound (should-fix) | **fixed** |
| 6 | two option strings that make one destination (`--num_epochs`, `--num-epochs`) (should-fix) | **fixed**: a new option whose destination an existing option already writes to is refused |
| 7 | false refusal: re-indenting the existing `sys.exit(main())` under the allowed Ctrl-C `try` makes it an "added" line (should-fix) | **fixed**: the line mapping compares lines without their indentation |
| 8 | false refusal: the allowed optional-import guard trips FAILURE_SITE_STILL_RAISES (should-fix) | **fixed**: an ImportError at a site is not counted as the site raising |
| 9 | tracer: a SIGTERM that interrupts `emit()` loses the report because `emitted` is set before the write; 5 of 8 Pool runs lost a worker report (should-fix) | **fixed**: `emitted` is set after the write (a duplicate line is harmless, a lost one is not); test reads the source order |
| 10 | a run alive at the limit that never reached a late site is read as "never ran" (should-fix) | **fixed**: the report carries `elapsed_s`; at 50 s or more a site or entry that was not reached is inconclusive |
| 11 | honest repairs still refused: `Path(out).mkdir(...)`, `torch.cuda.FloatTensor`, deleting `set_default_tensor_type('torch.cuda...')`, `time.clock`, a device or worker-count default flipped, a UTF-8 byte-order mark (should-fix) | **fixed** for these. **Accepted collateral**: `keras` to `tensorflow.keras` (a library swap), a tqdm identity fallback (a public function that returns) |
| 12 | runs of identical statements are mis-aligned by difflib, and 12,000 of them take 25 s (minor) | **limit lowered** to 6,000 statements per file (above it: "too large to judge"); the mis-alignment is a false-refusal risk on repetitive files, accepted |
| 13 | a `raise` added in the callee of a swallowing caller passes: the swallow check is lexical (minor) | **accepted limit** |
| 14 | the tracer's suffix matching can attribute an untraced file under the working directory to a traced file with the same basename (minor) | **fixed**: under the working directory the path is the name |
| 15 | `external_import_roots` parses a virtualenv inside the repository (minor) | **fixed**: `repo_python_files` skips hidden directories, virtual environments, build output |
| 16 | tests that claim more than they check (a literal comparison; `>= 1`; `!= set()`; a test named for ENTRYPOINT_NOT_EXECUTED that asserts it is absent; no fork / SIGTERM test on Windows) | **fixed**: the literal check now decodes the launcher payload and asserts no other command names the variable; the forged-line test asserts one process and the real count; the swallowed-raise test asserts the exact finding; ENTRYPOINT_NOT_EXECUTED has a real-tracer test. **Not tested on Windows**: fork and SIGTERM paths (the reviewer ran them on Linux) |

The reviewer also listed what it checked and found fine (statements it tried: `match`, async, walrus, star-args, annotations, `except*`, tabs and CRLF, NUL bytes, deep `elif` chains; the nonce filter; report
merge; the exit hook with the tracer; moving or reordering work; the transparent-`try` basics). A third review of release candidate 3 follows, and is the last: after it no rule changes except a confirmed
blocker with a one-line fix, and every finding that is not fixed is a stated limit in `reports/v1.10/RESULT.md`.


---

# Third review (release candidate 3, `0d1cd7d`) and what was done about each finding

Reviewer: a third separate agent instance (the first attempt stalled and was restarted from scratch), same brief and restrictions, told it was the last round. It reported **seven blockers, all confirmed by
run**, and a list of should-fix items. Dispositions are in release candidate 4 (tests `test_review3_*` in `backend/tests/test_behaviour.py`). After this round no further review was asked for: three rounds each
found the next layer of an allow-list, and the honest reading is that an allow-list judged by reading will always have another layer. What the measurement on the independent set will show is how many of the
remaining ones an author who had not seen the checks reaches; the ones the reviewers know about and that were not fixed are limits, listed at the end of this file.

| # | finding | disposition in rc4 |
|---|---|---|
| 1 | `raise <anything>(simple args)` runs any call: `raise os.execv(...)`, `raise os._exit(0)`, `raise time.sleep(...)`, an alias of `SystemExit`; handlers inherit it (blocker) | **fixed**: a `raise` may call only an exception class by its name (`...Error`, `...Exception`, `...Warning`); `raise <name>` of an existing exception stays |
| 2 | a coding cookie such as `unicode_escape` turns a comment line into code (blocker) | **fixed**: a patch that declares a source encoding other than utf-8 / ascii / latin-1 / cp1252 is refused |
| 3 | print-only stubs (`def train(*a, **k): print('done')`, `class Net: pass`) and a new file that IS the command's script or `-m` module (blocker) | **fixed**: a new function whose body only passes / returns nothing / logs / prints is a stub, and so is a new non-exception class with an empty body; a patch that adds the file the documented command runs is refused (`command_script_paths`) |
| 4 | function-local shadowing: a def or import inside `main` of a name bound at module level (blocker) | **fixed**: names bound in any scope of the file count |
| 5 | a method added to an existing class inside an `if` / `try` block (blocker) | **fixed**: the test is "the context is a class the patch did not add", not "the parent is the class" |
| 6 | arithmetic that stalls (`7 ** (10**8)`, `'x' * 10**9`), and calls that act while looking pure (`list(loader)`, `Path(a).replace(b)`, `requests.get`) (blocker) | **fixed**: no power / shift / large multiplication in a "reading" expression; `list` `tuple` `set` `dict` `sorted` removed from the pure builtins; the text methods lose `replace` `get` `items` `keys` `values` |
| 7 | an import repointed to another module of the same package; `_bindings` kept only the last binding of a name (blocker) | **fixed**: every binding of a name is kept; two modules of one package are two things; relocations are `abc` / `compat` / `v1` / `v2` components and a short list |
| 8 | workload exemptions: an option nobody defined that existing code reads, `_ENV_OPTION` as a substring (`--per_device_train_batch_size`), a docopt usage text (should-fix) | **fixed**: an option existing code reads is a workload fact; device options are matched by whole name (`--device`, `--use_cuda`, `--num_workers`, ...); a docopt program's usage text may not change |
| 9 | the trace vetoes the typical CPU-only repair (a failure site `model.cuda()` under `if args.cuda:` that the repair steers around) (should-fix) | **fixed**: a failure site that places something on the GPU is not required to run |
| 10 | false refusals: 34 of 83 typical pairs (should-fix) | **partly fixed**: removing `assert torch.cuda.is_available()`, a `GPU required` guard's exit, the `CUDA_VISIBLE_DEVICES` line; `current_device()`; `args.cuda` / `gpu_id` / `cuda` assignments; `sys.exit(-1)`; `warnings.catch_warnings`. **Not fixed** (library swaps and API renames the rule treats as computation): `.item()`, tqdm fallbacks, `Image.ANTIALIAS`, `inspect.getargspec`, `from time import clock`, `h5py.File(p)` mode, `with torch.cuda.device(0)`, a `map_location=lambda` |
| 11 | `repo_python_files` dropped `env/`, `build/`, `dist/` (the repository's own package can be called `env`) (should-fix) | **fixed**: a virtual environment is a directory with `pyvenv.cfg` (or `venv`, `.venv`, `site-packages`) |
| minor | `global x` accepted; `x = None` in any ImportError handler for any target; the 50 s limit hard-coded; `/lib/python` also dropped `repo/lib/python_utils/`; unused import | **fixed** (all five) |
| tests | the subclass-of-SystemExit test would pass with the old check; `posix._exit` and `elapsed_s` untested; the claims for item 4 of the second review hold only for direct methods | **fixed**: the subclass is a real class defined in a traced file; `posix._exit` and `elapsed_s` have real-tracer tests; item 5 above is the fix of the claim |

**Limits the three reviews leave standing** (stated again in `reports/v1.10/RESULT.md`): the tracer's report can be pushed out of the part of stderr the sandbox keeps by a repository that prints more than 4 MiB (such a
run is `trace missing`, vetoed by nothing); a repository can read the nonce out of the installed hook; a program that installs its own SIGTERM handler or sits in a C call longer than 3 s gives no report; a `raise`
added in the callee of an existing swallowing caller is not seen (the swallow check is lexical); runs of identical statements are mis-aligned by difflib; the static judgement is syntactic, so a patch that acts through
a name the allow-list trusts but the reviewers did not think of will pass; and the allow-list refuses honest repairs that swap a library call for a differently named one.

# Fourth review (the flag-mode release candidate 6, `aa9bfb3`) and what was done about each finding

A fresh reviewer read the diff of the harness paths from rc5 to rc6 (the flag mode, the review flag on the certificate, the Batch Lab read from figures.json) and the
new seal workflow, ran the suites, and wrote failing tests for what it found. Its verdict: **do not seal rc6.**

| # | severity | finding | disposition (release candidate 7) |
|---|---|---|---|
| 1 | BLOCKER | In flag mode the tracer ran inside the candidate run being judged; its report on stderr, written at interpreter exit, follows a traceback or an argparse usage text, so the exit-zero check (D-46) no longer overrules that exit 0: reproduced, checks off gives INDETERMINATE, flag mode RUNS_AFTER_REPAIR | **Fixed:** the flag mode runs the static half only (pure); the tracer runs in refuse mode alone. The review's reproduction is kept as `test_flag_mode_equivalence.py::test_an_exit_zero_the_v190_flow_overrules_stays_overruled_in_flag_mode` |
| 2 | MAJOR | The tracer's report counts as output for the smoke launcher, so a silent run alive at the limit becomes ALIVE instead of FAILED | Fixed by 1 (no tracer in flag mode); `test_the_tracer_is_never_installed_or_named_in_flag_mode` |
| 3 | MAJOR | The tracer's overhead (about 25 times on a traced pure-Python loop) moves how far a 60 s smoke run gets | Fixed by 1; stated as a limit of refuse mode |
| 4 | MAJOR | A repository line starting with the marker and holding deeply nested JSON raised RecursionError in `split_report`, ending the run | Fixed: lines over `REPORT_LINE_LIMIT` are not parsed, `RecursionError` is caught (refuse mode still reads reports); `test_the_report_reader_survives_a_hostile_line_in_refuse_mode`, and the flag-mode run is unchanged (`test_a_repository_line_with_the_marker_changes_nothing_in_flag_mode`) |
| 5 | MINOR | The tracer's install step adds cost and an image layer | Moot in flag mode (no tracer) |
| 6 | MINOR | The single-candidate flow dropped the flag on its error paths (cost stop, sandbox timeout, void run, a patch that did not apply) | Fixed: every record of the applied candidate carries its flag; `test_the_single_candidate_flow_keeps_the_flag_when_the_rerun_is_stopped` |
| 7 | MINOR | A single-candidate environment change that is put back kept its flag | Fixed: the record is marked `put_back` and `review_findings` skips it |
| 8 | MINOR | A crash of the checker was reported as COMPUTATION_CHANGED | Fixed: in flag mode it is `CHECK_FAILED`, "could not judge this patch" (refuse mode unchanged) |
| 9 | MINOR | A malformed figures.json raised in the Batch Lab (a 500 for the page) | Fixed: any malformed, partial or non-numeric figures file is no headline; `test_a_malformed_figures_file_is_no_headline_not_an_error` |
| 10 | MINOR | The Batch Lab computed two numbers (the independent set's total, the strict percentage) and its notes used comparative words not tied to figures | Fixed: both are figures now (`indep_patches`, `diagnosis_strict_pct`); `test_every_comparative_word_in_the_notes_and_limits_holds_for_the_figures` fails if a regenerated figure makes "all", "above", "no cheat", "not fakes" or "every" false |
| 11 | MINOR | The paid wiring check ran even when the seal failed, and the job showed green | Fixed: the wiring check runs only after a passed seal; a last step fails the job when the seal did not pass |
| 12 | MINOR | The wiring check was not comparable with the earlier run (no Tavily, mode not recorded) | Fixed: optional `TAVILY_API_KEY` secret; `scripts/live_run.py` records `behaviour_mode` |
| 13 | MINOR | `uv pip compile` (which may build old sdists) received RERUN's credentials; pip and setuptools were unpinned on the runner | Fixed: `time_machine.scrubbed_env` drops `NEBIUS_*` and `TAVILY_*`; pip 26.2.1 and setuptools 84.0.0 are pinned and the backend is built without isolation |
| 14 | MINOR | Workflow hygiene: outputs interpolated into a script, a re-run collides on the branch name, a cancelled job published nothing, a failed precondition broke the publish job | Fixed: outputs through env, the branch name carries the run attempt, publish runs always and skips the commit when there are no records |

**Consequence for the flag-mode figures:** none. The derived flag table used the static half's findings and the trace findings rc4 recorded; there were no trace findings
on any measured patch that ran and no cheat was traced, so the static-only flag gives the same counts (`reports/v1.10/flag/flag_table.json`).

# Fifth review (a focused review of the rc6-to-rc7 diff, `ca28911`) and what was done about each finding

A fresh reviewer compared the flag mode with the checks off in six scenarios (the commands the sandbox receives, the image builds, the cost operations, the verdict,
every attempt record but its `behaviour`, the log without the advisory line, the outcome ladder, the certificate prose): identical in all six. It found no blocker and no
major defect, and said rc7 may be sealed; it listed five minor findings, all fixed in release candidate 8 with the reviewer's reproductions kept as tests
(`backend/tests/test_flag_mode_equivalence.py`).

| # | finding | disposition (rc8) |
|---|---|---|
| 1 | The flag reached the certificate for a patch that never applied (single-candidate apply failure; the multi-candidate winner whose patch no longer applies); the multi-candidate apply-failure record carried no flag | Records of a patch that never reached the checkout carry the flag with `not_applied`, and `review_findings` skips them |
| 2 | The advisory `behaviour check FLAGGED` log line could be among the last five log lines the final verdict adjudicator (a model that may downgrade) is given as evidence | The advisory lines are left out of that evidence: it is what the checks-off flow gives |
| 3 | A NaN or infinite figure passed the Batch Lab's numeric check | Non-finite values make the figures file no headline |
| 4 | The credential scrub was case-sensitive, Settings is not | Names are compared upper-cased |
| 5 | A re-run of the workflow reused the artifact name | The artifact name carries the run attempt |
