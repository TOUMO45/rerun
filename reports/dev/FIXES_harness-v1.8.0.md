# harness-v1.8.0: the fixes, one by one (Phase 2)

Written 2026-10-07. Owner's directive of the same day: ship harness v1.8 and a fresh pre-registered held-out test (TEST-C); TEST, TEST-B and the out-of-sample (OOS) scan stay frozen as published and are never re-scored under their old names. The 21 old held-out entries are re-run here as **DEV-CONTAMINATED** (`runs/dev_v18/`, `batch.dev_label` / `dev_label` on every record): they were used to write these fixes, so nothing in this file is a held-out result and no number below is attributed to TEST, TEST-B or OOS.

Status of the code: the working tree, **unsealed** (no tag, nothing committed or pushed since `1b3abcf`). Every DEV record carries `harness_tree_sha256`, the modified and the untracked harness files, and HEAD, so the code that ran is identifiable without a commit.

## 0. Rules that held (checked, not assumed)

| rule | result | evidence |
|---|---|---|
| The tamper gate's semantics are unchanged | **yes** | `tamper_gate.py` and `env_repair.py` have no diff against HEAD; the independent review confirmed it (R1). T1 changes only what the orchestrator records in `failed_moves` / `untested_moves` before the gate's repeat check; `_repeats`' own rule and the gate's `ENV_REPEATS_FAILED_CHANGE` text are untouched |
| No sandbox-touching file changed, so **no paid seal is needed** for any item below | **yes** | `sandbox.py`, `sandbox_limits.py`, `runner_env.py`, `smoke_exec.py`, `runner_hooks.py`, `exit_zero_check.py`, `api_removals.py`, `error_chain.py`, `passport.py`, `verify_passport.py` have no diff against HEAD (same precedent as v1.7.2: the seal rule is "changes no sandbox-touching file") |
| The passport hash is not changed | **yes** | `blocker` and `outcome_levels` are derived (unhashed) fields; new keys are additive; a fresh certificate passes `scripts/verify_passport.py` (review R3) |
| Full backend suite | **2135 passed, 21 skipped, 0 failed** (7 min 36 s, on the tree committed at `befa608`) | run after the last code change (the DEV-driven diagnosis corrections and the T2 pairing). The run before them had 2097 passed; the first run after them had 1 failure, a stale class-sentence expectation in `test_v16_harness.py` that the new `_pins_conflict` rule made wrong, fixed and re-run |

New tests: 223 in 14 files (`backend/tests/test_v18_*.py`). Run against a copy of HEAD, the independent review found 4 of the files cannot even import (the modules are new) and 82 of the 94 tests in the other six fail; the 11 that pass there are record-readers and "left as before" guards. (That count predates the 16 tests of `test_v18_review_gaps.py` and the extra T1 / T3 cases.)

## 1. The fixes

Each: what changed, the test evidence, what the 21 records showed. The DEV result is in section 3, from `runs/dev_v18/` only.

### D (the owner's top priority): evidence-driven diagnosis
*What:* the blocker's `what_a_human_must_supply`, `next_action`, `error_line`, `cause`, `fixable_by` and `basis` are derived from the record's own evidence (`diagnosis.py`: rules over the error chain, attempt tails, environment deltas and gate messages), not from one fixed sentence per class. A class default is kept for records no rule reads and is marked `diagnosis: "class_default"` (so a rate can never count a default as evidence). `derived_record` now passes `indeterminate_reason` and `baseline` (D-58: an INDETERMINATE stop's blocker was `null` in every record before).
*Tests:* `test_v18_diagnosis.py` (42). The answer key `reports/dev/v18/diagnosis_key.json` was **committed (`1b3abcf`) before** `diagnosis.py` existed; each of the 14 blocker records is regenerated and judged by the key's regexes; every quoted line must be a verbatim line of the record's own output. `check_diagnosis.py --write` -> `DIAGNOSIS_REGEN.md`: **9 of 9 wrong texts now right, 5 of 5 right texts still right, all error lines verbatim**. Held-out check (`test_v18_review_gaps.py`): the rules fire on exactly six other committed records, each read by hand, and on none of the other ~120 blocked records.
*Entry by entry:* `reports/dev/v18/DIAGNOSIS_REGEN.md`.

### T5: a missing C header or compiler tool maps to its apt package (deterministic, labelled)
*What:* `system_packages.py` (header and tool tables; `ft2build.h` -> `libfreetype6-dev`, `which g++` -> `build-essential`, `pkg-config` ...), applied through the same labelled mechanism as the D-24 compiler rule (`orchestrator._auto_system_packages`); the classifier reads inside pip's failed-build wrapper. D-62.
*Tests:* `test_v18_t5_system_packages.py` (11), `test_d24_build_essential.py` (updated: pkg-config is now deterministic). *Records:* TEST #13 neo_gnns (`which g++`), TEST-B #8 gandissect (`ft2build.h`).

### T3: install-line repair
*What:* `install_repair.py`: `git+git://github.com/` -> `git+https://` in RERUN's own copy of the requirements (the repository's files are never edited) and `git` installed (GitHub switched off `git://` on 2022-03-15; reproduced 2026-10-07); a Debian package renamed upstream (`libgl1-mesa-glx` -> `libgl1`) is mapped at plan time and, on `no installation candidate`, replaced; that apt failure is `SYS_LIB_MISSING` and no longer skips the time machine. Labelled dependency changes. D-63.
*Tests:* `test_v18_t3_install_repair.py` (9, including the era-lock-failing case the review said was hidden). *Record:* TEST-B #3 video_prediction.

### T2: an unserved pre-release pin becomes its final release
*What:* `prerelease_pin.py` (`torchvision==0.6.0a0` -> `0.6.0`) through R5's existing `state.torch_overrides` path; labelled. D-64.
*Tests:* `test_v18_t2_prerelease_pin.py` (3) + the diagnosis rule. *Record:* TEST-B #2 ovis.

### T11: a documented command that pipes into an interpreter runs under pipefail
*What:* `command_shell.py`: `python generate_script.py --train=True | bash` is handed to the sandbox as `bash -o pipefail -c '<command>'`; the certificate's `build_plan.execute_command` stays the documented text and the baseline says `pipefail: true`. Only a pipe whose last stage is a shell or Python interpreter is wrapped (review finding 3: `| head`, `| tee`, `| grep`, `| wc` keep their semantics, since pipefail would turn the producer's benign SIGPIPE into a failure). D-65. **Not implemented:** the second half as triaged (an exit-0 run that printed nothing in under a second is not RUNS_CLEAN): none of the 21 records would change and a silent legitimate command cannot be tested offline.
*Tests:* `test_v18_t11_pipefail.py` (18) + a real-`bash` test in `test_v18_review_gaps.py` (`false | sh`: 0 without the wrapper, 1 with it). *Record:* TEST #18 adversary_critic. *No seal:* the sandbox is handed a different command string; no sandbox file changes.

### T10 / T9: the exact line, and the stops no repair can fix
*What:* the classifier no longer records pip's wrapper line or the exit hook's `SystemExit: 2` as the evidence when a more specific line exists (`_specific_build_line`, `fallback_evidence`); NLTK's `Resource X not found` is `DATA_MISSING` (D-54) and the diagnosis says `ptb` is a stub for the licensed corpus. `docker: not found` / `conda: not found` among the **last three lines** of a failed output (and no Python failure after) stop the run INDETERMINATE before any repair (`entry_blockers.py`; the earlier version of this reader was quadratic on one long line, found by the review and fixed; timed tests in `test_v18_review_gaps.py`). An argparse rejection of the documented command is diagnosed but is **not** a stop (a patch that adds the option is a legitimate repair). D-59.
*Tests:* `test_v18_diagnosis.py`, `test_v18_review_gaps.py`. *Records:* NeuralTracking (docker), cwn (conda), video_prediction, rocgan, gandissect.

### T19: records an audit can read
*What:* a step that exited 0 keeps the last 2,000 characters of each stream in `operations[].streams.tail` (`cap_chars` says the cap); `model_patch` is stored whole as valid JSON up to 200,000 characters (it was cut at 6,000, mid-JSON). D-53. The TEST-B result file is not edited.
*Tests:* `test_v18_t19_records.py` (6).

### T17: the cost guard's estimate is labelled, not changed
*What:* `cost_guard.cap_status()` -> `cost_guard.over_cap_estimated_only` / `over_cap_usd` in each record. **Not changed:** funding at the killed-step estimate rate ($0.0152/s) would cut every repair operation's funded seconds 2 to 5 times; that is an owner decision (D-60). Consequence for this run: the DEV driver holds back the highest single-entry reading on record, $4.18, before each start, not $2.50.

### T1 (narrowed as the owner wrote it): "failed" only if the error it targeted is still there
*What:* for the env changes of a candidate that was **not adopted** and whose run did not succeed: the cited line still in the new output, or the change's **own** install failing (a pin that does not exist, an apt name Debian does not know; review finding 7) -> `failed`, barred as before; anything else -> `untested`, allowed once more, and the second untested outcome bars it (`MAX_UNTESTED_ATTEMPTS = 2`). Recorded per attempt in `env_outcome`. The gate's rules are untouched: only the orchestrator's `failed_moves` bookkeeping changed (`move_status`, `move_barred`, `_settle_moves`). D-57.
*Tests:* `test_v18_t1_untested_moves.py` (7): a scenario with the real classifier, gate, adjudicator and orchestrator on the fake cloud (on the v1.7.2 code the run ends BLOCKED, refused as a repeat), the failed case, and pure tests for the twice-untested bar and the own-install-failed case. *Record:* TEST-B #8 gandissect.

### T6 (the minimum): "era lock unavailable" names its cause
*What:* `time_machine.lock_failure_cause` reads uv's own message (`BUILD_NEEDS_BUILD_DEPENDENCY`, `CUTOFF_BELOW_BUILD_TOOL`, `SDIST_METADATA_BUILD_FAILED_ON_HOST`, `REQUIREMENTS_UNSATISFIABLE`; the dependency is read from uv's hint, never assumed to be torch). **Naming only; no lock behaviour changed.** D-61.
*Tests:* `test_v18_t6_lock_cause.py` (7), on the recorded uv messages.

### T7: the rest of D-47 (indentation)
*What:* `indentation.rebase_edit` re-bases an edit whose `old` starts without its indentation (or carries the wrong absolute indentation) onto the matched lines before the gate; every other edit is byte-identical to before; `patch_pipeline._apply_file_edits` decides per file. D-56. *Tests:* `test_v18_patch_rebase.py` (46), from the replay scripts of the 5 recorded patches.

### T15: README-named scripts are entrypoint candidates (product path)
*What:* `intake.find_readme_entrypoints`, a note in the recon prompt. Counts for the UI and the demo, **not for TEST-C** (which runs each repository's documented command). No seal. D-52. *Tests:* `test_v18_readme_entrypoints.py` (20).

## 2. Not done, and why

T13 (MuJoCo provisioning) and T14 (PyG wheels): L-sized, would touch the sandbox (seal). T6 beyond the naming, T8, T16 (D-50, D-51), T12: out by the owner's cut line. D-55 (the gate protects any `test_*` file, so a patch to a documented entrypoint named `test_*.py` is refused): gate semantics, not changed; the diagnosis names it.

## 3. DEV results (runs/dev_v18/, DEV-CONTAMINATED)

**What ran.** Round 1 (2026-10-07, detached through Task Scheduler, never a child of a session): the 16 corpus entries (TEST-B #1-8, TEST #1, 2, 6, 10, 13, 18, 19, 20) through `scripts/live_run.py`, and the 5 out-of-sample repositories through RERUN's own API (`reports/live_scan/run_live_scan.py`), on the working tree, **unsealed**, entry cap $2.50. Every corpus record carries `batch.dev_label = "DEV-CONTAMINATED (was <set>)"` and `harness_tree_sha256 = 16f146627253...`: all 16 are the same code, and the tree was not edited while they ran (checked afterwards: the hash is unchanged). Then three small follow-ups, each labelled: the OOS fb-scraper and steamctl repeated once (variance), and round 2 = TEST-B #2 ovis alone, after T2 was changed (below), on the tree as it then stood. Driver, table and per-record provenance: `reports/dev/v18/run_dev_v18.py`, `dev_results.py`, `dev_results.json`.

**Spend (API-reported plus the estimate of any killed step, as the ledger counts it).** Corpus round 1 $18.90; OOS $0.66 + $9.10 (one killed baseline, mud-pi: $0.0009 measured, the rest the $0.0152/s estimate, D-60); OOS repeats $0.76; round 2 $2.24; smoke tests about $0.01. DEV bucket $31.66; ledger **$129.91 of the $300.00 ceiling**. These are API-reported figures with estimates. **BILLED (owner's balance reading, 2026-10-07): $44.37, i.e. $0.77 billed since the $45.14 reading** (`reports/dev/BILLED_READINGS.md`; $31.66 recorded against $0.77 billed, D-36, not reconciled).

### 3.1 The 21 beside the verdicts they had under harness-v1.5 / v1.7.2

| set | # | entry | before | DEV v1.8 | cost | diagnosis cause (basis) |
|---|---|---|---|---|---|---|
| TEST-B | 1 | yikangshen__Ordered-Neurons | BLOCKED RUNTIME_ERROR_OTHER | BLOCKED DATA_MISSING | $0.46 | NLTK_RESOURCE_LICENSED (evidence) |
| TEST-B | 2 | vlievin__ovis | INDETERMINATE DEP_YANKED | INDETERMINATE DEP_UNPINNED_CONFLICT | $0.20 | PINS_CONFLICT (evidence) |
| TEST-B | 3 | alexlee-gk__video_prediction | BLOCKED DEP_BUILD_FAILED | BLOCKED DEP_BUILD_FAILED | $0.97 | REQUIREMENT_STRING_INVALID (evidence) |
| TEST-B | 4 | zcajiayin__L2D | RUNS_AFTER_REPAIR GPU_REQUIRED | RUNS_AFTER_REPAIR GPU_REQUIRED | $1.33 |  (none) |
| TEST-B | 5 | twitter-research__cwn | BLOCKED DEP_NOT_ON_PYPI | INDETERMINATE CONDA_REQUIRED | $0.62 | CONDA_REQUIRED (evidence) |
| TEST-B | 6 | galsang__trees_from_transformers | RUNS_CLEAN | RUNS_CLEAN | $0.31 |  (none) |
| TEST-B | 7 | Stilwell-Git__Hindsight-Goal-Generation | BLOCKED DEP_MISSING | BLOCKED DEP_MISSING | $1.33 | MUJOCO_LIBRARY_MISSING (evidence) |
| TEST-B | 8 | CSAILVision__gandissect | BLOCKED SYS_LIB_MISSING | BLOCKED DEP_BUILD_FAILED | $1.98 | BUILD_FAILS_AFTER_APT_STEP (evidence) |
| TEST | 1 | nadiinchi__power_laws_deep_ensembles | BLOCKED DEP_MISSING | BLOCKED DEP_MISSING | $0.66 | VENDORED_MODULE_MISSING (evidence) |
| TEST | 2 | DeformableFriends__NeuralTracking | BLOCKED RUNTIME_ERROR_OTHER | INDETERMINATE DOCKER_REQUIRED | $0.30 | DOCKER_REQUIRED (evidence) |
| TEST | 6 | grigorisg9gr__rocgan | BLOCKED RUNTIME_ERROR_OTHER | BLOCKED DEP_MISSING | $1.39 | DEP_MISSING (class_default) |
| TEST | 10 | alevine0__patchSmoothing | RUNS_AFTER_REPAIR GPU_REQUIRED | RUNS_AFTER_REPAIR GPU_REQUIRED | $0.62 |  (none) |
| TEST | 13 | seongjunyun__neo_gnns | INDETERMINATE DEP_BUILD_FAILED | INDETERMINATE DEP_BUILD_FAILED | $4.00 (over cap: estimate only) | SYSTEM_PACKAGE_ADDED_UNTESTED (evidence) |
| TEST | 18 | aam-at__adversary_critic | RUNS_CLEAN | BLOCKED API_REMOVED | $1.05 | API_REMOVED (class_default) |
| TEST | 19 | lrjconan__RBP | BLOCKED DEP_MISSING | INDETERMINATE DEP_BUILD_FAILED | $2.82 (over cap: estimate only) | SYSTEM_PACKAGE_ADDED_UNTESTED (evidence) |
| TEST | 20 | XiaoxiaoGuo__fashion-retrieval | BLOCKED DATA_MISSING | BLOCKED DATA_MISSING | $0.86 | DATA_MISSING (class_default) |
| TEST-B round 2 | 2 | vlievin__ovis | INDETERMINATE DEP_YANKED | INDETERMINATE DEP_YANKED | $2.23 | DEP_YANKED (class_default) |
| OOS |  | ValvePython__steamctl | RUNS_AFTER_REPAIR DEP_MISSING | BLOCKED DEP_MISSING | $0.27 | DEP_MISSING (class_default) |
| OOS |  | n0kovo__fb_friend_list_scraper | BLOCKED API_REMOVED | INDETERMINATE | $0.00 | ENTRYPOINT_UNCLEAR (evidence) |
| OOS |  | Frimkron__mud-pi | INDETERMINATE | TIMEOUT | $9.10 |  (none) |
| OOS |  | njanakiev__openstreetmap-heatmap | BLOCKED API_REMOVED | BLOCKED RUNTIME_ERROR_OTHER | $0.29 | RUNTIME_ERROR_OTHER (class_default) |
| OOS |  | awekrx__AutoDoc-ChatGPT | INDETERMINATE | INDETERMINATE | $0.09 | ENTRYPOINT_NEEDS_ARGS (evidence) |
| OOS-repeat |  | ValvePython__steamctl | RUNS_AFTER_REPAIR DEP_MISSING | BLOCKED DEP_MISSING | $0.32 | DEP_MISSING (class_default) |
| OOS-repeat |  | n0kovo__fb_friend_list_scraper | BLOCKED API_REMOVED | BLOCKED API_REMOVED | $0.43 | ERA_PAIR_MISMATCH (evidence) |

The diagnosis column is the blocker re-derived from each record's own fields with the rules as they now stand (a derived, unhashed field); the blocker each run **stored** is in `dev_results.json` beside it (`stored_blocker`), unedited. They differ on 5 records, the ones in section 3.4.

**Headline, stated as it is.** RAN (the verdict as published) 3 of 16 corpus entries: TEST-B #4 L2D and TEST #10 patchSmoothing (`RUNS_AFTER_REPAIR`, GPU_REQUIRED) and TEST-B #6 trees_from_transformers (`RUNS_CLEAN`, documented command `--help`, an R4 (b) strike under the TEST-B protocol, so not a run of the repository's code). Under v1.5 / v1.7.2 the same three ran. **No entry moved from not-running to running.** One moved the other way for the right reason: TEST #18 adversary_critic was recorded `RUNS_CLEAN` for a run that did nothing (the pipe's last status); it is now `BLOCKED API_REMOVED`. Out of sample, none of the 5 ran (v1.7.2: steamctl did). This is a DEV result on entries the fixes were written from; it says nothing about TEST-C.

### 3.2 Per fix: what the DEV records show

| fix | entries it touches | DEV result |
|---|---|---|
| D diagnosis | the 13 non-running corpus records | text from evidence on 9 as stored, **10 after the section 3.4 corrections** (3 stay on a labelled class default: rocgan, adversary_critic, fashion-retrieval); the pre-committed key is still 9 of 9 wrong->right and 5 of 5 right->right (`DIAGNOSIS_REGEN.md`) |
| T5 / D-24 apt step | gandissect, neo_gnns, RBP, rocgan, fashion-retrieval (`missing_compiler_build_essential` fired in all five) | **no entry reached a run because of it.** gandissect moved past `g++` and met matplotlib's bundled-freetype `./configure` failure (exit 2); neo_gnns and RBP: the next operation (a torch-extension build) was stopped by the spend cap; rocgan and fashion-retrieval ended on other errors. The `ft2build.h` header rule did not fire: the header was not in any final error |
| T3 install repair | video_prediction | `git_protocol_rewrite` fired and the clone **worked**; the build then failed on a different error (a dependency's setup.py lists `python_version>"3.7"`, which current setuptools rejects). `libgl1-mesa-glx` was mapped to `libgl1` at plan time. Did not reach a run |
| T2 pre-release pin | ovis | round 1: relaxed to `torchvision==0.6.0`, which needs torch 1.5.0 while the repository pins 1.5.1: `ResolutionImpossible`, INDETERMINATE again, one step later. **Changed** (the release made for the pinned torch, from R5's table: 0.6.1) and re-run in round 2: the runner's setup now passes and the run reaches the repair loop; it ended `COST_CAP` at $2.23 on a requirements file full of yanked conda-export pins (`mkl-fft==1.1.0`, `mkl-random==1.1.1`, ...), which the repairer fixed one pin per round |
| T11 pipefail | adversary_critic | baseline now fails as the script does (`pipefail: true`); the `RUNS_CLEAN` for a run that did nothing is gone |
| T9 docker / conda stops | NeuralTracking, cwn | both stop INDETERMINATE (`DOCKER_REQUIRED`, `CONDA_REQUIRED`) at $0.30 and $0.62, with no repair; before: nine and ten repair attempts |
| T10 exact line | video_prediction, rocgan, gandissect | the error lines quoted are the specific ones, not pip's wrapper or `SystemExit: 2` |
| T19 records | the three RUNS_* entries | `operations[].streams.tail` present on all three (an audit no longer has to infer from hashes) |
| T1 narrowed | video_prediction, Hindsight, power_laws, adversary_critic | `env_outcome` recorded on 4 records (untested 3 / 10 / 4 / 4, failed 3 / 7 / 1 / 0). No entry changed verdict because of it |
| T6 naming | neo_gnns, RBP, fashion-retrieval | named: `BUILD_NEEDS_BUILD_DEPENDENCY`, `CUTOFF_BELOW_BUILD_TOOL`, `SDIST_METADATA_BUILD_FAILED_ON_HOST` |
| T7 indentation | fashion-retrieval | fired 5 times (4-column re-bases); **one patch was still rejected** (`unexpected indent`): its own `old` and `new` carry the wrong RELATIVE indentation (a 4-space line above an 8-space line where the file has both at 8), which a uniform shift cannot repair; a limit, recorded as D-67 |
| T15 README entrypoints | mud-pi (OOS) | recon now picks `simplemud.py` (0.90). It is a server loop: the baseline ran the full 600 s and ended `TIMEOUT`; see D-66 |
| T17 label | neo_gnns, RBP | `over_cap_estimated_only: true` on both (the records say $4.00 and $2.82 against the $2.50 cap; $3.45 and $1.88 of those are the killed-step estimate, so the measured part of each is under the cap) |

### 3.3 Out of sample: what differs from the v1.7.2 scan, and what I could and could not establish

* **steamctl: `BLOCKED DEP_MISSING`, twice** (the repeat gave the same, 4 operations, $0.32 each time), where v1.7.2 got `RUNS_AFTER_REPAIR`. In v1.7.2 the winning patch to `steamctl/__main__.py` arrived in round 3; in both v1.8 runs the repairer did not propose it (gate-rejected env changes, a decline, a patch to requirements.txt that changed nothing). `repairer.py`, which builds the repairer's prompt, is unchanged in the diff, and the classifier's evidence line for this error (a plain `ModuleNotFoundError`) is unchanged, so nothing I changed alters what the repairer was shown for this record. Two v1.8 samples against one v1.7.2 sample **cannot** separate a regression from model variance, and I cannot re-run v1.7.2 code. Open.
* **fb_friend_list_scraper:** first run `INDETERMINATE ENTRYPOINT_UNCLEAR` (the recon model returned no entrypoint; v1.7.2's recon answered at confidence 0.60, exactly the threshold); the repeat reached recon with a confident entrypoint and ended `BLOCKED API_REMOVED`, as v1.7.2 did. Run-to-run variance in the recon model, established by the repeat.
* **mud-pi:** `TIMEOUT` (above). **openstreetmap-heatmap:** `BLOCKED RUNTIME_ERROR_OTHER` (`AttributeError: 'NoneType' object has no attribute 'objects'`; v1.7.2 ended on a different Blender error): a different repair path, a labelled class default. **AutoDoc-ChatGPT:** unchanged, `INDETERMINATE ENTRYPOINT_NEEDS_ARGS`.

### 3.4 Defects the DEV run found in what I had just written, and what was done

One defect in several forms, found by reading the five records whose stored diagnosis disagreed with the run: **a rule that says "RERUN already fixed X" read an OLD line of the record and claimed the run still ended on it.** video_prediction (the diagnosis still said "change git:// to https://" after RERUN's rewrite had made the clone work), neo_gnns and RBP (it said RERUN's apt step "did not help" when the operation after the step was stopped by the spend cap and nothing was observed), ovis (it said "pin torchvision==0.6.0", the pin RERUN had just made), plus gandissect, whose class default said "nothing, if the apt rule adds the build dependencies" after the apt step had added them. Fixes (all in the DERIVED blocker; no run behaviour changed; the pre-committed key is unchanged and still passes): rules for an applied step now say what the run after the step showed (nothing: stopped; a different error: the step worked; the same error: it did not help); a spend-cap stop is added to the last known blocker instead of replacing it (`stopped_by`); a TIMEOUT verdict gets a diagnosis that does not claim the program started; three evidence rules (`PINS_CONFLICT`, `BUILD_FAILS_AFTER_APT_STEP`, `REQUIREMENT_STRING_INVALID`). Two more were added while the DEV key was written, because the key's author could state the cause from the raw log and the rules could not: `EMBEDDED_RUNTIME_REQUIRED` now also fires when the run ends on a NoneType error whose traceback line reaches `bpy` (osm-heatmap: the stand-in `bpy.data` is None) and `PACKAGE_MAIN_RUN_AS_FILE` names the module form for `python steamctl/__main__.py` (D-50, diagnosis only: the command is not changed). Tests: `test_v18_dev_findings.py` (16). The stored blocker of each affected DEV record is left as the run wrote it; the corrected one is in `dev_results.json` and the table above. The T2 change is the one change that altered run behaviour after round 1, and it was re-run (ovis, round 2).

**What did not work (stated plainly).** (1) No blocked entry became a run: the fixes moved four entries past their recorded blocker (gandissect, video_prediction, ovis, neo_gnns until the cap), and each met the next one. (2) Two entries (neo_gnns, RBP) are stopped by the per-entry cap in a long install, not by the repository. (3) steamctl lost its v1.7.2 `RUNS_AFTER_REPAIR` in two of two re-runs, unexplained. (4) mud-pi, a server, is judged TIMEOUT.

### 3.5 Seal cost

**None required.** No sandbox-touching file changed (R2 above), so by the v1.7.2 precedent nothing needs a paid seal; the tag for TEST-C will be created from a clean tree (Phase 4), and the preflight of the sealed batch driver will check it. An optional bundled seal (a probe of the pipefail command wrapper, the only change that alters what the sandbox is handed) would cost about one probe run, a few dollars; **I do not think it is needed** and would not do it without your yes.

## 4. Phase 3: the diagnosis as a first-class result (2026-10-07)

**What exists now** (all committed except where stated): `reports/dev/v18/DIAGNOSIS_RUBRIC.md` (the written rubric, four criteria A1 verbatim, A2 right cause, A3 concrete next action, A4 anchored
in the final state; two waivers for a TIMEOUT; a procedure that keeps the scorer from being the author grading his own text), `score_diagnosis.py` (the mechanical scorer), `diagnosis_dev_key.json`
(the DEV key, written from the raw logs, every proof line checked to be in its record, committed BEFORE the scorer was run on it: commit `5664e00`), `set_metrics.py` + `set_metrics.json`
(per-set measurements from committed records), the measurements served by `GET /batch/preregistered` (`metrics` on each held-out set), and `test_v18_phase3.py` (19 tests).

### 4.1 The DEV score, with its limits stated

18 non-running DEV records (13 corpus, 5 OOS; `diagnosis_dev_score.json`):

| the blocker that is scored | actionable | what it measures |
|---|---|---|
| **as the DEV runs stored it** (the rules as they stood when the run was made) | **9 of 18** | new runs of repositories the rules had been written from: the nearest thing to an out-of-fit figure this set has |
| **as the current rules derive it** from the same records | **16 of 18** | a FIT: the rules were corrected from these very records, and the key's author had read the diagnoses. It is not a prediction |

The two that stay not actionable are scored honestly: rocgan (the record does not establish the cause, so a diagnosis cannot be right about it) and RBP (A4: the quoted line is the last one the run
showed before an apt step whose own run was stopped by the spend cap; the strict final-state test rejects it). The seven stored diagnoses the DEV run got wrong or stale (ovis, video_prediction, gandissect,
neo_gnns, RBP, steamctl, osm-heatmap) are exactly the ones A2 / A4 reject. **The expected TEST-C rate is therefore below the 16 of 18**; the committed threshold (Phase 4) is set from the 9 of 18.

### 4.2 The per-set measurements (from committed records only; the "hours" tile is gone)

| set | N | RAN (audited) | non-running | with a diagnosis | median wall-clock to a diagnosis | median API-reported cost to a diagnosis | recovery (as-published failed -> RUNS_AFTER_REPAIR) |
|---|---|---|---|---|---|---|---|
| TEST (harness-v1.5-final) | 8 | 1 | 6 | 6 | 399 s | $0.92 | 1 of 7 |
| TEST-B (harness-v1.7.2) | 8 | 1 | 6 | 6 | 785 s | $1.02 | 1 of 7 |
| Out-of-sample scan (harness-v1.7.2) | 5 | 0 | 4 | 2 | 391 s | $0.39 | 0 of 4 |
| harness-v1.8 DEV re-run of the 16 corpus entries (DEV-CONTAMINATED: the fixes were written from these) | 16 | 2 | 13 | 13 | 513 s | $0.97 | 2 of 15 |
| harness-v1.8 DEV re-run of the 5 out-of-sample repositories (DEV-CONTAMINATED) | 5 | 0 | 5 | 4 | 158 s | $0.18 | 0 of 3 |

Cost is API-REPORTED with the estimate of killed steps, not billed (the owner's balance moved $0.77 over the whole DEV interval that recorded $31.66). TEST, TEST-B and the OOS scan are read as they are
(time and cost are measurements); they are **not** scored by the rubric, which would re-score them under their old names. Of the OOS scan only two of five records carried a diagnosis (D-58), so its medians
are over two entries.

### 4.3 What is not done in Phase 3

* **The UI tiles.** The backend serves the numbers; the frontend does not show them yet, and the Certificate page does not yet show `cause`, `error_line`, `next_action`, `stopped_by` and the
  `class_default` label. I could not read the frontend sources in this session (the permission check refused a search of them), so no frontend file was touched. It is a presentation change on top of finished backend fields.
* **The demo image** pins `REF` to `a7f5c4c`; it serves these numbers only after `REF` moves to a pushed commit (Phase 5).
