# Candidate harness-v1.3.3 defects (recorded, NOT fixed: harness-v1.3.2 is sealed; TREATMENT batch in progress)

Written 2026-09-30 while TREATMENT was at 9/20 records; counts in D-1 and the additions below were re-derived on the 20/20 arm (`results_tables.json`). Source: `reports/corpus-v2.1/arm_tables.{md,json}` (from
`scripts/arm_tables.py`, read-only over `runs/`) and the raw records in `runs/corpus_v2_batch/harness-v1.3.2/treatment/`.
Counts are for the records present at that time and will be re-derived when the arm finishes.

## Python-version selection rule (for repos that declare none)

Source: `backend/app/services/python_policy.py`, `METHODOLOGY.md` § "Runner environment policy". Precedence: `.python-version`,
`pyproject.toml`, `setup.py`/`setup.cfg`, `environment.yml`, `Pipfile`, README phrases; first satisfiable minor in the order
3.10, 3.9, 3.8, 3.11, 3.7, 3.12, 3.13, 3.6. A repo with no usable declaration runs on **3.10** (`[python] ... RERUN default 3.10`).
In TREATMENT only, the time machine may replace it with the era-appropriate interpreter (newest CPython released >= 180 days before
the pinned commit date, `time_machine.python_for_era`) **if the era lock succeeds**; if the lock fails the era interpreter is computed,
recorded, and not used. Both are shown in the `python_version_used` / `how chosen` columns.

## D-1  Repairer emits invalid unified diffs; 0 of 16 source patches applied (entries 1, 3, 4, 8, 10, 14, 17)

Every `source_patch` attempt in TREATMENT (16 attempts over entries 1, 3, 4, 8, 10, 14, 17; 12 gate REJECTs, 4 gate PASSes) ended without a re-execution: 0 applied (`results_tables.json` -> repair_split). Modes seen in the stored `diff_text` / events:
- wrong hunk line counts: `diff could not be parsed: Hunk is shorter than expected` (entry 3 #1, entry 4 #3);
- header-only diff with no hunk that the gate **passes** and `git apply` rejects: `No valid patches in input` (entry 1 #2, entry 8 #3);
- stale or misquoted context: `patch does not apply` (entry 3 #3);
- JSON-escaped literal `\n` inside the diff: `diff contains no file changes` (entry 4 #1, #2).
Consequence: source-patch repairs cannot currently be a source of recoveries; any recovery so far is env-only.
Candidate fix: ask for structured edits (file, exact old text, new text) and let the harness build the diff; reject a diff with zero hunks in the gate.

## D-2  Tamper gate PASSes a diff with zero hunks (entry 1 #2, entry 8 #3)

The gate's own AST reconstruction trusts the diff structure (see the comment in `orchestrator.py` near "gate-approved patch failed to apply").
A header-only diff is "approved", consumes a repair attempt and, for entry 1, fed the same failing state into the next search.

## D-3  Entry 1: root cause of "repair 2 did not clear `collections.Iterable`" and of the identical second search

What the record shows (`01_nadiinchi__power_laws_deep_ensembles.json`, events 152-173 s):
1. Repair 2 was **not** a Tavily-derived patch. It was a model-written diff, `origin=model`, `tavily_sources=[]`, and the diff text is only
   `--- a/train.py` / `+++ b/train.py` (0 hunks). The gate passed it; `git apply` failed (`No valid patches in input`); nothing was executed.
   So the `Iterable` error could not have cleared: no code or environment change was made in repair 2 (D-1, D-2).
2. The second search is identical because `tavily.build_query(code, evidence)` is `f"python {code} fix: {evidence[:150]}"`: a pure function of the
   failure class and error string. The error was unchanged after the failed apply, so the query and its results were the same
   (`[tavily] 3 result(s) for 'python runtime error other fix: ImportError: cannot import name ...'`, logged twice). No history of earlier attempts enters the query (D-4).
3. Why `Iterable` appeared at all: the time-machine era lock failed (attempt 0, `DECLINED`): `curves` is a module the repo imports but does
   not contain, and the lock treated it as a PyPI distribution (`no versions of curves ... before 2020-10-23`). One unlockable name aborted the whole
   era lock, so the era interpreter (3.8) was computed but not used and the run stayed on 3.10. Repair 1 then pinned `tabulate==0.8.7` (2020), which
   does `from collections import Iterable`, on 3.10: an era-old package on a non-era interpreter (D-5). The final error, `No module named 'curves'`, is REPO (module absent from the repo).

## D-4  Search query does not vary with attempt history (same class + same error string = same query)

## D-5  An era lock that fails for one name discards the whole era environment, including the interpreter (entries 1, 8)

Entry 8: era python 3.6 computed, lock failed, run stayed on 3.10; repair 1 then pinned `scikit-learn==1.0.1`. Classification of these as
HARNESS_INDUCED is decided in Phase B3 with the definition written there; this file only records the mechanism.

## D-6  Entry 19 planning gap (from the pre-registered audit)

`operators._ext` is the repo's own compiled module and its README documents a build step; not a dependency. See METHODOLOGY.md CONTROL amendment.

## Additions found on the full 20/20 arm

- **D-7 Per-entry $2 ceiling is not hard.** The guard checks before a step; one sandbox operation can cost far more than a typical one. Entry 13: a single 600 s re-execution recorded $5.12 (entry total $5.68); entry 16 $2.50.
- **D-8 A timed-out sandbox operation may be unrecorded spend.** Entry 15's repair-1 re-execution hit the 600 s wall clock (`PIPELINE_ERROR:sandbox:SandboxError`) and the record's `cost_guard` shows $0.36 for the whole entry; METHODOLOGY (harness-v1.2 limitations) already states TIMEOUT spend is under-reported. If billed like entry 13's 600 s operation ($5.12), true spend could exceed recorded $21.76 by about that amount. Unverified: needs the Nebius billing console.
- **D-9 Error extraction takes noise as the error.** Entry 3: terminal error recorded as `17.6` (a progress fragment); entry 12: a benign TensorFlow `W ... Could not load dynamic library libnvinfer.so.6` warning classified SYS_LIB_MISSING while the same stderr ends in `AttributeError: ... no attribute 'get_variable'`. The repairer then chased the wrong error.
- **D-10 `remove` in env_delta does not remove apt packages.** Entry 12 repair 3: logged "env delta applied" but the build plan's `apt_install` still listed both packages and the same apt error repeated.
- **D-11 The time machine overrides a repo-declared Python.** Entry 3: README declares 3.6, CONTROL ran 3.6, TREATMENT re-ran on era python 3.10 (`[python] ... (README)` then `[time-machine] ... -> python 3.10`).
- **D-12 The repairer proposes packages that do not exist for the image, and one that is a different project.** `python3-distutils` (entry 8) and `libnvinfer6` (entry 12) do not exist on the Debian 13 image; entry 19 repair 2 pip-installed `operators==1.0.0` (a real PyPI project, verified by the resolver as existing, unrelated to the repo) for the repo's own `operators._ext`. The gate does not check whether a name is the repo's own module: a dependency-confusion vector (Phase D5 test).
- **D-13 Runner-setup failures never reach the time machine.** Entries 5 and 9 (both arms): `RUNNER_SETUP_FAILED` before the repo's first command; the era lock, which chooses an older Python, is only entered after a baseline run. Whether an era interpreter would have installed the historical torch pin was not tested.
- **D-14 METHODOLOGY line 729 is inaccurate.** "the harness saw no dependency file for any of the 16 audited entries": intake shows dependency files for entries 5 (Pipfile, requirements.txt), 9 (requirements.txt) and 17 (setup.py declaring torch, torchvision). 17 of 20 have none. The pre-registered text is not edited; RESULTS.md carries the correction.

## Observation (not a defect): Tavily was queried but never cited

46 `[tavily]` searches in 16 entries; 0 cited sources; every `tavily_sources` is empty; every `[citations]` line reads "not cited". Tavily-decisive fixes: 0 (and recoveries: 0).

## Found by the v1.3.3 smoke gate (2026-09-30; see `v1.3.3/smoke_gate/SMOKE_GATE_REPORT.md`; none fixed, the harness is sealed)

- **D-18** The repairer prompt shows RERUN's resolved lock as `requirements.txt`; edits to it are refused (entry 7, repairs 2-3 wasted).
- **D-19** A silent exit 1 after a progress stream leaves the repairer no error text (entry 3: evidence `1`, two applied patches changed nothing, the third broke the syntax).
- **D-20** The download route (repositories over 125.8 MB: entries 2, 8, 10, 11) cannot carry a patched file: manifest from the patched bytes, sandbox fetches the original, exit 97, INVALID_HARNESS (entry 8).
- **D-21** The repairer declared no `cited_sources` in 7 searches (0 citations), including when the top result was the API documentation for the moved function (entry 8).
- **D-22** An attempt that ends in INVALID_HARNESS is not recorded (entry 8, repair 1).

## Found by the v1.3.4 smoke gate (2026-09-30; `v1.3.3/smoke_gate/SMOKE_GATE_REPORT_v1.3.4.md`; not fixed: stop rule)

- **D-23** The per-repair funding rule starves entries whose re-executions each pay a ~90 s torch install (entries 11, 8: COST_CAP before the repository ran).
- **D-24** The deterministic "missing gcc -> build-essential" rule fires only on the baseline classification, not after a repair (entry 7: the model proposed `gcc` as a pip package). [Annotation 2026-10-01, Phase D4: fixed post-gate, unvalidated. The rule now fires on any SYS_LIB_MISSING classification at repair time, before the model, and records `time_machine_action` with the matched error string (`backend/tests/test_d24_build_essential.py`). The change is on `main` as `harness-v1.3.5-unvalidated`: not sealed, run in no gate, used in no record, passport, REPLAY or dashboard figure. `harness-v1.3.4` is unchanged.]
- **D-25** One round of model-placed diagnostics does not locate a deliberate silent `exit 1` (entry 3); RERUN should inject the diagnostic itself.
- **D-21 (open in practice)** With a REQUIRED `cited_sources`, the repairer filled `reason_no_citation` 9 times out of 9; no `content_match` either. The mechanism is complete; the model does not cite. [Annotation 2026-10-01, Phase D1: records show 7 attempts consulted; the figure 9 is not reproducible from records (`consulted` on 7 attempts, 21 references; `reason_no_citation` on 6).]
- **v1.3.3 entry 11** was a smoke-limit artefact, not a recovery (run further, a REPO `torch.load` defect).

## Found by the Phase D record inventory (2026-10-01; offline, from the committed records; documented only, not fixed)

- **D-26** `reason_no_citation` is not recorded on a DECLINED attempt (harness-v1.3.4, entry 3, repair 1: `consulted` holds 3 references, the attempt was DECLINED, and the record has no `reason_no_citation` and no citation). Status: open.
- **D-27** The ledger records only completed cost; the spend of a killed step is absent (seal-verification kill runs stopped through `client_wait_timeout` store `completed_cost_usd` 0.0 and no cost for the killed step; the first v1.3.3 seal attempt's kill record has no cost field). The ledger total is therefore a lower bound. Related: D-8 (harness-v1.3.2, entry 15). Status: open, documented only; the missing amounts are not reconstructed.
- **D-28** `record_*_sha256` in `reports/corpus-v2.1/results_tables.json` are hashes of CRLF worktree files, not git blobs; they do not match passport record ids (confirmed on control entry 1, then on all 40 listed records: each listed hash equals the SHA-256 of the blob with LF written as CRLF). `results_tables.json` is not modified; the mapping worktree hash -> blob hash -> record id is in `reports/phase-d/record_index.md`. Status: open, documented only.


## Found by the harness-v1.4.0 seal (2026-10-01, live; registered by owner decision)

- **D-29** The v1.4.0 seal script (`reports/corpus-v2.1/v1.4.0/seal/run_seal_v140.py`) derived each operation's timeout from the cost guard's worst-case rate ($0.50 run cap / $0.0085 per s = 58.8 s for seal run 2, operation E, too short for entry 7's apt + pip setup) and did not record cost when an operation timed out: the measured cost of the completed steps was lost with the exception (operation `01a0f82a-ee6d-76bc-a8f0-f74e11c7246f`, CANCELLED). Recorded as ESTIMATED <= $0.4998 in `runs/sandbox_verification/v1.4.0-seal/run2_E_attempt1_killed.json`, not recomputed. Fix: every seal operation's timeout is recorded with its measured completed cost plus the killed-step estimate; a fixed wall clock per operation (`--op-seconds`); E can start from a kept image (`--e-start-image`). Tests: `backend/tests/test_v140_seal_runner.py::test_a_killed_seal_operation_is_recorded_with_its_cost_not_lost`, `::test_run_2_can_start_from_a_kept_image_without_uploading_or_rerunning_apt`. Status: fixed-unvalidated (tests exist; not gate-validated). Not in the Phase D register snapshot (D-1..D-28), which stays untouched.


## Found by the harness-v1.4.0 gate (2026-10-01; `v1.4.0/gate/GATE_REPORT_v1.4.0.md`) and by the v1.4.1 Step 1 reading of its records; registered 2026-10-01

All of D-30 to D-35 are fixed in `harness-v1.4.1-rc` (unsealed until its seal; no gate has validated any of them): status **fixed-unvalidated**, basis = the named test. Ledger tags in this section: API-REPORTED = a stored record field (the sandbox API's `resources.cost`; not account billing, D-36), ESTIMATED, DERIVED = computed here from the named records. None of D-30 to D-36 is in the Phase D register snapshot (D-1..D-28), which stays untouched.

- **D-30** The guard funded every operation at a fixed $0.0085 per second of WALL clock, while the API bills sandbox time and an operation's wall time is several times its billed time. Corpus-v2 #11, harness-v1.4.0, operation 2 (`operations[1]`): $0.2975 API-reported for 29.2 s of billed time in 108.2 s of wall time (about $0.0028 per wall second; its baseline $0.3299 over 78.5 s, $0.0042). Funded 108.2 s from $0.92, it built the whole era environment, was stopped as the smoke launcher was about to start, and the entry ended COST_CAP with $0.62 of its $1.25 unspent. Fix: the rate is the rolling rate of this entry's completed operations (sum of cost over sum of wall time) x 1.5, between a floor of $0.0030 and the old ceiling $0.0085; `rate_used` and its source operations are recorded on every operation (`operations[].funding`). DERIVED from the same records: at $1.50 the new rule funds #11's operation 2 for 185 s, above the 168 s it needed (108.2 s to reach the smoke run + 60 s); at the old $1.25 cap it funds 146 s, not enough: the operation would be stopped about 38 s into its smoke run, the guard's estimate for that killed step leaves $0.30, which funds 48 s, below one resumed operation (80 s), so at $1.25 the entry would still end COST_CAP (neither D-30 nor D-31 saves it); at the pre-registered $1.50 the rate alone funds it. Tests: `backend/tests/test_v141_funding_and_resume.py::test_the_recorded_stop_of_entry_11_would_have_been_funded_for_the_full_smoke_run`, `::test_at_the_old_1_25_entry_cap_entry_11_would_still_end_cost_cap_after_a_late_stop`, `::test_the_rate_is_clamped_between_the_floor_and_the_ceiling_and_a_killed_operation_is_not_a_source`. Status: fixed-unvalidated. The killed-step ESTIMATE stays at the ceiling rate; see the D-27 annotation below.
- **D-31** A budget-limited stop ended the entry even when the stopped operation had kept every layer it built and the entry could fund another operation (#11, v1.4.0: the era environment complete in kept images, $0.62 left). The v1.3.3 rule (a kill at the budget limit ends the run COST_CAP, D-7) predates kept images. Fix: such a stop is followed by the next operation, which reopens the deepest kept image and runs what it lacks; the entry ends COST_CAP only when what is left cannot fund one operation (the smoke run plus a 20 s start-up margin, 80 s at the 60 s smoke limit; the margin is twice the largest wall overhead, 10.0 s, of a v1.4.0 gate operation that ran no setup step) or no environment image (one holding at least one setup command) is kept; at most two resumes per operation. Read as: the stop does not end the entry while both hold; the directive's "only when neither holds" is taken to mean "when that pair does not hold". Tests: `test_v141_funding_and_resume.py::test_entry_11s_recorded_stop_is_followed_by_a_resumed_operation_from_the_kept_era_image`, `::test_the_entry_ends_cost_cap_when_what_is_left_cannot_fund_one_operation`, `::test_nothing_kept_means_nothing_to_resume_and_the_entry_ends_cost_cap`, `::test_a_resume_that_is_stopped_again_is_resumed_at_most_twice_per_operation`. Status: fixed-unvalidated.
- **D-32** The candidate adjudicator had no JSON re-ask (the repairer has one) and its fallback chose the FIRST qualifying candidate. #7 round 1: Ultra's reply was not valid JSON, RERUN chose candidate 1 (stopped in package metadata) although candidate 2 had finished the install and reached `No module named 'Box2D'`; #8 round 2: invalid JSON again (2 of the 4 adjudications the gate asked for). Fix: one re-ask on an invalid reply, both raw replies recorded (`adjudication.replies`, `reasked`); the fallback picks the first passing run, else the candidate with the furthest recorded stage (phase of the final step, setup steps completed, whether it was still running when it failed, seconds), ties to the lowest number, and records what it chose from (`fallback_basis`). Tests: `backend/tests/test_v141_adjudicator.py` (the #7 round-1 candidates are read from the committed record). Status: fixed-unvalidated.
- **D-33** The deterministic rules (D-24, the CPU shim, the exit-site hook) only saw the adopted failure. #7 round 2: a candidate's run reached `unable to execute 'gcc'`, was not adopted, and D-24 never saw it. Fix: the rules observe every candidate's failure and fire in that candidate's own branch; the action is recorded as `time_machine_action` on the candidate's attempt (with `on_candidate`), and what a rule added joins the run's environment only if that candidate is adopted. Tests: `backend/tests/test_v141_candidate_rules.py` (the gcc text is the one the v1.3.4 gate recorded for #7; the v1.4.0 record's round-2 adjudication quotes it). Status: fixed-unvalidated.
- **D-34** An apt package added at repair time changed the plan's FIRST setup step, so no setup layer could be reused and the operation rebuilt from the tree image: #8, v1.4.0, operation 11 (build-essential for the gcc error of an adopted environment change) started a second torch install and was stopped. Fix: a repair-time apt package is an additive layer, `export DEBIAN_FRONTEND=noninteractive && apt-get update && apt-get install -y ...`, placed after the setup steps the deepest kept image holds (the leading `export` keeps `sandbox_limits.split_setup_ops` from filing it with the system packages, which always run first); when no environment image is kept the package joins the first apt step as before. No change to `sandbox.py`. Tests: `backend/tests/test_v141_apt_layer.py` (a run-time gcc need: only the layer runs and no `pip install` follows it; a build-time need: the layer goes before the failing pip step and torch is installed no more than in the baseline and the era environment). Status: fixed-unvalidated.
- **D-35** The exit-site hook cannot see a bare `raise SystemExit(n)`: on #3 the hook was installed automatically, printed nothing, and the model never saw an exit site (D-25 remains open in practice). Fix: when the hook was installed and printed nothing, the entry script runs through a harness wrapper (`runpy.run_path` inside `try/except SystemExit`, printing the traceback and re-raising with the same code); if the wrapper prints nothing either, the record says "exit outside Python". Applies to a plain `[VAR=v] python [-u] script.py args` or `python -m module args`; anything else is recorded as not applicable. Limit, stated in every use: only a Python SystemExit reaches it; on Python 3.9+ the script sees `sys.argv[0]` as an absolute path. Tests: `backend/tests/test_v141_exit_wrapper.py` (real subprocesses on a fixture with a bare `raise SystemExit(1)`: the hook alone prints nothing, the wrapper prints the raise site). Status: fixed-unvalidated.
- **D-36** Ledger figures are the sandbox API's reported operation cost (`resources.cost`, unit undocumented), not account billing. For the window 2026-09-30 19:54 UTC to 2026-10-01 17:11 UTC the ledger is $14.6495 and the account balance fell $0.39 (owner's reading, $49.61 of $50.00 at 19:37 local, 2026-10-01): a factor of about 37. Cause not established: billing lag, free beta ("Free while in beta — runs don't consume your credits", Token Factory sandboxes page), list price versus charge, page coverage and project mismatch are all open. Investigation, quotes and the single observation that settles each hypothesis: `docs/design/D-36.md`. Until it is resolved the tag MEASURED is renamed API-REPORTED in the Phase D assets, the one BILLED line per gate comes from the owner's balance readings, and the ledger stays a bound on API-reported cost, not on spend. Status: **open**.

Annotation on **D-27** (2026-10-01, from `docs/design/D-36.md`): the killed-step ESTIMATE is `killed_seconds x $0.0085` (`cost_guard.SANDBOX_COST_RATE_USD_PER_S`, derived over wall seconds of whole operations); the API's own cost per BILLED second of a step is $0.0101 at the median (21 steps of at least 3 s: minimum $0.01005, maximum $0.01454), so that estimate is not an upper bound for a killed step. harness-v1.4.1-rc keeps the estimate unchanged (no recorded number moves; the amounts are small: $0.1868 on #8 operation 11). Open for the owner's decision.

## Found by the harness-v1.4.1 gate (2026-10-01; `v1.4.1/gate/GATE_REPORT_v1.4.1.md`; not fixed: the harness is sealed and the gate failed)

- **D-37** The candidate adjudicator adopts nothing unless the run passes. #7, all three rounds: the one qualifying candidate each round had moved the failure to a later stage (`pkg-config: not found` -> `No module named 'Box2D'`; apt packages -> pygame's missing-library list) and was refused because the run still failed; the same pattern in v1.4.0 #7 round 2. An entry therefore cannot accumulate progress and ends on its original error. Status: open (a prompt/rule question: reward a later recorded stage, D-32's `stage_rank` already orders it).
- **D-38** A kill by signal is classified as a silent exit. #11: after the CPU shim cleared the GPU error, the era run loads CIFAR-10, enters the training loop and is killed at iteration 1 of 40 (`Killed`, exit 137); the classifier reports RUNTIME_ERROR_OTHER with no actionable error, the hook and the wrapper print nothing ("exit outside Python", correct), and the model is asked for nine patches the silent-exit rule must refuse. Probable cause: a sandbox memory limit (not established: `consumed_memory` is returned by the API and not stored). Status: open (name exit 137 / "Killed" as a resource kill and stop asking the model; store `consumed_memory`).
- **D-39** The CPU shim covers `torch.load` and `torch.cuda.is_available()` only. #8, round 3: after the shim handled the CUDA `torch.load`, the run reached an explicit `.cuda()` (`AssertionError: Torch not compiled with CUDA enabled`) and the model attempts were used up. Status: open.
- **Observation (not a defect of the harness)** The pre-batch upload smoke test passes only when the line sustains about 0.85 MB/s (124 MB against a 155.6 s transport timeout): at 0.16 MB/s it timed out four times in 760 s and the gate refused to start, with no entry run and no spend beyond $0.0008; at 0.71 to 0.88 MB/s it passed once (141 s upload, 14 s of margin). No gate entry uploads more than a few MB (#8 uses the download route), so the check guards a path these four do not use.

Annotation on **D-36** (2026-10-01, the owner's second balance reading): $49.57 after the v1.4.1 seal and gate; cumulative charged at most $0.43 against a ledger of $18.5083; $0.04 between the two readings against $3.8588 recorded for the same work (and $0.3625 of price-table model tokens in it). Still open; `docs/design/D-36.md` section 9.

Annotation on **D-27** (2026-10-01, owner decision): from harness-v1.4.2 on, a killed step is ESTIMATED at the API's median cost per billed second x 1.5 = $0.0152/s (the rate and its source are recorded with each estimate); past estimates are not recomputed. Each past estimate carries: **computed at $0.0085/s, not an upper bound (D-27)**:
v1.3.4 gate #8 $0.2842 (`runs/corpus_v2_batch/harness-v1.3.4/smoke/08_edenton__svg.json`), v1.4.0 seal run 2 attempt 1 at most $0.4998 (`runs/sandbox_verification/v1.4.0-seal/run2_E_attempt1_killed.json`), v1.4.0 gate #8 operation 11 $0.1868, v1.4.1 seal K1 $0.2009 (`runs/sandbox_verification/v1.4.1-seal/run3_K1_operation_stopped_at_its_limit.json`); the v1.3.3 and v1.4.1 gates stored no estimate. They sum to $1.1717 in the ledger (the ESTIMATED part), a lower bound.

## harness-v1.4.2-rc: D-37 to D-40 fixed-unvalidated (2026-10-01; offline; the owner's v1.4.2 directive)

No gate has validated any of these: status **fixed-unvalidated**, basis = the named test. Tags as in the section above. D-37, D-38 and D-39 were registered as open by the harness-v1.4.1 gate (above); this section is
their annotation, not a rewrite.

- **D-37 [annotation: fixed-unvalidated]** When no candidate passes, the adjudicator adopts the candidate whose run got furthest by the recorded stage order (runner setup < install step k < the repository's own command < passed),
  PROVIDED it strictly advances past the failure being repaired (a coarse key: phase, setup steps completed, still running when it failed; seconds are ignored, a longer run is not progress); `adopted_reason` = "partial progress"
  with the two stages recorded; Ultra's own choice is labelled "adjudicator", RERUN's JSON fallback "fallback: <why>". The adopted candidate's change is applied and its kept image is the next round's environment (the existing
  adoption path). Tests: `backend/tests/test_v142_partial_progress.py` (corpus-v2 #7, harness-v1.4.1 gate rounds 1-3 read from the committed record: Box2D is further than pkg-config; and a pipeline run whose round 2 branches from the
  adopted candidate's image).
- **D-38 [annotation: fixed-unvalidated; see D-40]** An exit by SIGKILL (137, -9) is classified RESOURCE_LIMIT before any text rule (the shell's `Killed` was lost with the progress bar it sat on, so the kill read as a silent exit);
  it is attributed to the sandbox, never to the repository.
- **D-39 [annotation: fixed-unvalidated]** The CPU shim now also returns self from `Tensor.cuda()` and `Module.cuda()`, maps `.to("cuda*")` / `.to(torch.device("cuda*"))` / `device=` on Tensor and Module to the CPU, and makes
  `torch.device("cuda*")` the CPU device (a proxy class that keeps `isinstance(x, torch.device)` true); every patch stands alone (one that cannot be applied is reported and never disables the others), and each path that acted prints
  `RERUN_CPU_SHIM_PATH: <path>` once per process, which the harness records as `time_machine_action.paths_fired`. Limit, recorded with every use: device strings given to factory functions (`torch.zeros(device="cuda")`),
  `torch.cuda.*Tensor` types and `torch.set_default_tensor_type("torch.cuda.FloatTensor")` are NOT covered. Tests: `backend/tests/test_v142_cpu_shim.py` (a fake torch that raises #8's recorded `Torch not compiled with CUDA enabled`;
  the same checks against real CPU torch when RERUN_REAL_TORCH_PYTHON names an interpreter that has it).
- **D-40** Resource classification and evidence. (1) RESOURCE_LIMIT (taxonomy, family Platform, a sandbox code like SANDBOX_QUOTA) ends the entry INDETERMINATE with the limit quoted, never BLOCKED, and no model attempt is spent
  (corpus-v2 #11, v1.4.1: nine candidates were refused by the silent-exit rule after the kill). (2) ONE evidence run per entry (TREATMENT only): the command (through the exit wrapper if it is on) runs unchanged in a subshell and the
  sandbox's own limits and kill traces are read after it (`/proc/meminfo`, `nproc`, cgroup memory files, kernel version, `dmesg`, `ulimit`), parsed by the harness; the reason quotes them, or the documented limits when none could be read.
  (3) The unexplained silent exit of #3: after the exit hook printed nothing and the exit wrapper printed nothing, the wrapper runs once more WITH the evidence; a kill evidenced (status 137, a cgroup `oom_kill` count above zero, or a kernel
  log line) is RESOURCE_LIMIT, otherwise the record keeps "exit outside Python" and the entry ends INDETERMINATE EXIT_OUTSIDE_PYTHON with that reason and the evidence; no model attempt is spent. (4) The sandbox's resource limits are stored on every
  operation (`operations[].resource_limits`): `docs/design/D-40-resources.md` (offline research) found NO documented memory or CPU figure for a Sandboxes microVM, no parameter to choose a size and no larger instance (beta, access by request,
  contree@nebius.com); the only documented cap is the 12 GiB writable layer. The record says "not documented"; nothing is invented. **Not done, on purpose:** storing the API's per-step `max_rss` (reachable through the SDK object
  `result._raw.result.resources.max_rss` with no new call) needs an additive change to `sandbox.py`, which would make every seal entry that lists it stale (about $0.8 to re-verify, above the ceiling room left); proposed for a later
  version. Tests: `backend/tests/test_v142_resource_limit.py` (#11's recorded kill; the evidence command run for real with sh; baseline and CONTROL; a killed candidate gets no hook or wrapper), `backend/tests/test_v141_exit_wrapper.py`
  (the #3-shaped silent exit ends INDETERMINATE EXIT_OUTSIDE_PYTHON, or RESOURCE_LIMIT when the evidence shows a kill). Status: fixed-unvalidated.
