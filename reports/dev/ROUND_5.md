# DEV round 5 — harness-v1.7.1

Protocol: METHODOLOGY.md "harness-v1.5 dev/test protocol". Tag `harness-v1.7.1` (commit `164d632d8d40`), TREATMENT, the 8 DEV entries once each, entry cap $2.50. DEV entries are tuned on; this is a development signal, not a result. The TEST entries are not in this report (rule F).

- **DEV count (smoke level, D2): 3 of 8** entries with a RUNS_* verdict; kinds: {'smoke_alive': 3} (`smoke_alive` = a 60 s smoke pass that nothing has confirmed; no sustained check in DEV).
- Of those (harness-v1.7 pre-registration): **0 resource-adapted** (R1 d, the documented command ran with a smaller batch) and **0 with a semantic change** (R6, D-44).
- Adds something over earlier rounds (D4): **no** — count 3 does not exceed the best earlier count 3 and no entry reaches RUNS_* for the first time.
- Cost [API-REPORTED]: $8.8107; [ESTIMATED] (killed steps): $1.9177; round total $10.7285. BILLED: AWAITED (the owner reads the account balance and reports it in chat).
- Ledger after this round (lower bound, D-27): $65.9273 (base $29.1704 + v1.5 DEV spend $36.7569); ceiling $100.00; DEV total $36.7569 of $50.00. Guard for another round: REFUSED — HARD: DEV spent $36.7569 + a round's worst case $20.00 passes the $50.00 DEV total.

## Verdict per entry

| id | entry | verdict | code | kind of final run | attempts | model attempts | cost USD |
|---|---|---|---|---|---|---|---|
| 4 | damo-cv__img-comp-reference | BLOCKED | RUNTIME_ERROR_OTHER |  | 9 | 9 | 0.8539 |
| 5 | BorgwardtLab__topological-autoencoders | BLOCKED | DEP_BUILD_FAILED |  | 11 | 9 | 2.3701 |
| 9 | omarfoq__fedem | INDETERMINATE | DATA_MISSING |  | 5 | 3 | 3.5696 |
| 12 | Mehran-k__SimplE | RUNS_AFTER_REPAIR | API_REMOVED | smoke_alive | 2 | 0 | 0.4356 |
| 14 | IST-DASLab__M-FAC | TIMEOUT |  |  | 0 | 0 | 0.2238 |
| 15 | YuliaRubanova__latent_ode | RUNS_AFTER_REPAIR | DEP_YANKED | smoke_alive | 4 | 3 | 0.7681 |
| 16 | bckim92__sequential-knowledge-transformer | BLOCKED | DEP_MISSING |  | 12 | 9 | 1.9927 |
| 17 | Haichao-Zhang__FeatureScatter | RUNS_AFTER_REPAIR | API_REMOVED | smoke_alive | 1 | 0 | 0.5147 |

## Failure classes

Baseline class = the classifier's first reading of the as-published failure; ending = the verdict and its code.

| id | baseline class | classifier readings in order | ending |
|---|---|---|---|
| 4 | RUNTIME_ERROR_OTHER | RUNTIME_ERROR_OTHER → DATA_MISSING → RUNTIME_ERROR_OTHER | BLOCKED RUNTIME_ERROR_OTHER |
| 5 | DEP_UNPINNED_CONFLICT | DEP_UNPINNED_CONFLICT → DEP_UNPINNED_CONFLICT → DEP_UNPINNED_CONFLICT → SYS_LIB_MISSING → DEP_BUILD_FAILED | BLOCKED DEP_BUILD_FAILED |
| 9 | SYS_LIB_MISSING | SYS_LIB_MISSING → DEP_MISSING → DATA_MISSING | INDETERMINATE DATA_MISSING |
| 12 | DEP_MISSING | DEP_MISSING → API_REMOVED | RUNS_AFTER_REPAIR API_REMOVED |
| 14 | (none) | (none) | TIMEOUT  |
| 15 | DEP_MISSING | DEP_MISSING → DEP_YANKED | RUNS_AFTER_REPAIR DEP_YANKED |
| 16 | DEP_MISSING | DEP_MISSING → SYS_LIB_MISSING → APT_MIRROR_GONE → DEP_MISSING | BLOCKED DEP_MISSING |
| 17 | API_REMOVED | API_REMOVED | RUNS_AFTER_REPAIR API_REMOVED |

Histogram, baseline class, this round: {'DEP_MISSING': 3, 'RUNTIME_ERROR_OTHER': 1, 'DEP_UNPINNED_CONFLICT': 1, 'SYS_LIB_MISSING': 1, '(none)': 1, 'API_REMOVED': 1}.

Histogram, ending (verdict code), this round: {'RUNS_AFTER_REPAIR API_REMOVED': 2, 'BLOCKED RUNTIME_ERROR_OTHER': 1, 'BLOCKED DEP_BUILD_FAILED': 1, 'INDETERMINATE DATA_MISSING': 1, 'TIMEOUT': 1, 'RUNS_AFTER_REPAIR DEP_YANKED': 1, 'BLOCKED DEP_MISSING': 1}.

Histogram, ending, every earlier record of the DEV and gate entries (all versions, both arms of v1.3.2): {'BLOCKED RUNTIME_ERROR_OTHER': 20, 'BLOCKED DEP_MISSING': 8, 'INDETERMINATE RUNTIME_ERROR_OTHER': 4, 'INDETERMINATE DEP_UNPINNED_CONFLICT': 2, 'INDETERMINATE DEP_YANKED': 2, 'RUNS_AFTER_REPAIR DEP_MISSING': 2, 'INDETERMINATE DEP_MISSING': 2, 'INDETERMINATE RESOURCE_LIMIT': 2, 'INDETERMINATE PIPELINE_ERROR:sandbox:SandboxError': 1, 'INVALID_HARNESS INVALID_HARNESS': 1, 'BLOCKED DEP_NOT_ON_PYPI': 1, 'INDETERMINATE SYS_LIB_MISSING': 1, 'BLOCKED SYS_LIB_MISSING': 1, 'BLOCKED GPU_REQUIRED': 1, 'BLOCKED DATA_MISSING': 1}.

## Outcome ladder (harness-v1.6, L; stored on 8 of 8 records, computed from the stored fields on the rest)

Counts, this round: first error cleared **7 of 8** (by origin: {'time_machine': 5, 'model': 2}); environment resolved **5 of 8**; entrypoint runs (RUNS_*, smoke level) **3 of 8**.

| id | first error cleared | cleared by | env resolved | entrypoint runs |
|---|---|---|---|---|
| 4 | yes | model | yes | no |
| 5 | yes | model | no | no |
| 9 | yes | time_machine | yes | no |
| 12 | yes | time_machine | yes | yes |
| 14 | no |  | no | no |
| 15 | yes | time_machine | yes | yes |
| 16 | yes | time_machine | no | no |
| 17 | yes | time_machine | yes | yes |

## Blocker (harness-v1.6, B; none on a RUNS_* run)

| id | class | family | phase | attribution | fixable by | evidence | what a human must supply | sources |
|---|---|---|---|---|---|---|---|---|
| 4 | RUNTIME_ERROR_OTHER | Code | repo_run | REPO | model | `SystemExit: 1` | a code change; the repairer proposes one and the tamper gate decides | not looked up |
| 5 | DEP_BUILD_FAILED | Dependencies | repo_install | REPO | deterministic | `error: subprocess-exited-with-error` | nothing, if the apt rule adds the build dependencies; otherwise a wheel of the package for this platform | not looked up |
| 9 | DATA_MISSING | Data | repo_run | REPO | human | `AssertionError: Download cifar10 dataset!!` | the dataset the repository expects at the path the code opens, obtained as its README describes | not looked up |
| 12 | (none) | | | | | | | |
| 14 | (none) | | | | | | | |
| 15 | (none) | | | | | | | |
| 16 | DEP_MISSING | Dependencies | repo_run | REPO | deterministic | `ModuleNotFoundError: No module named 'language_evaluation'` | nothing, if the era lock resolves it; otherwise the exact release of language_evaluation the authors used | not looked up |
| 17 | (none) | | | | | | | |

## harness-v1.7 rules (R1-R5): where each fired, what it recorded, how the entry ended

| rule | entry | recorded | entry's ending |
|---|---|---|---|
| data_prep | 9 | script data/cifar10/README.md:47 `python generate_data.py --n_tasks 80 --n_components 3 --alpha 0.4 --s_frac 1.0 -`; result null | INDETERMINATE DATA_MISSING (exit None) |
| apt_archive | 16 | rewrote [] | BLOCKED DEP_MISSING (exit 1) |
| companion_relax | 5 | torchvision 0.5.0 requires torch==1.4.0; the repository pins torch==1.2.0, whose torchvision is 0.4.0; Pillow==6.2.2 beside it (torchvision 0.4.0 imports PIL.PI | BLOCKED DEP_BUILD_FAILED (exit 1) |

## Deterministic rules that fired (no model call)

- #4: runner torch policy x17; cpu_shim x3; exit_site_hook x4
- #5: runner torch policy x9; companion_relax; time machine (era None, python None, apt []); time machine (era 2022-01-18, python 3.7, apt [])
- #9: runner torch policy x6; data_prep; time machine (era 2021-08-11, python 3.7, apt ['build-essential']); time machine (era None, python None, apt [])
- #12: removed_api_tensorflow_v1_graph_api; time machine (era 2020-02-11, python 3.7, apt []); time machine (era None, python None, apt [])
- #14: runner torch policy
- #15: runner torch policy x4; time machine (era 2020-12-03, python 3.8, apt [])
- #16: runner torch policy x6; apt build-essential; missing_compiler_build_essential; apt_archive; time machine (era 2020-06-16, python 3.6, apt []); time machine (era None, python None, apt []) x2
- #17: runner torch policy x2; removed_api_torch_zero_gradients; time machine (era None, python None, apt [])

## What the model contributed

| id | calls by model | model attempts | env-delta ops | patches proposed | declined | rejected | citations | origin of the passing attempt |
|---|---|---|---|---|---|---|---|---|
| 4 | {'nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B': 1, 'nvidia/nemotron-3-super-120b-a12b': 11, 'nvidia/Nemotron-3-Ultra-550b-a55b': 6} | 9 | 0 | 9 | 0 | 0 | 0 |  |
| 5 | {'nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B': 2, 'nvidia/nemotron-3-super-120b-a12b': 14, 'nvidia/Nemotron-3-Ultra-550b-a55b': 4} | 9 | 4 | 3 | 2 | 1 | 2 |  |
| 9 | {'nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B': 2, 'nvidia/nemotron-3-super-120b-a12b': 4, 'nvidia/Nemotron-3-Ultra-550b-a55b': 2} | 3 | 3 | 0 | 0 | 0 | 0 |  |
| 12 | {'nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B': 1, 'nvidia/nemotron-3-super-120b-a12b': 1, 'nvidia/Nemotron-3-Ultra-550b-a55b': 1} | 0 | 0 | 0 | 0 | 0 | 0 | time_machine |
| 14 | {'nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B': 1, 'nvidia/nemotron-3-super-120b-a12b': 1, 'nvidia/Nemotron-3-Ultra-550b-a55b': 1} | 0 | 0 | 0 | 0 | 0 | 0 |  |
| 15 | {'nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B': 1, 'nvidia/nemotron-3-super-120b-a12b': 4, 'nvidia/Nemotron-3-Ultra-550b-a55b': 2} | 3 | 2 | 0 | 1 | 0 | 0 | model |
| 16 | {'nvidia/nemotron-3-super-120b-a12b': 12, 'nvidia/Nemotron-3-Ultra-550b-a55b': 2} | 9 | 1 | 1 | 7 | 0 | 2 |  |
| 17 | {'nvidia/nemotron-3-super-120b-a12b': 1, 'nvidia/Nemotron-3-Ultra-550b-a55b': 1} | 0 | 0 | 0 | 0 | 0 | 0 | time_machine |

## Stream flags (D-41)

| id | operations | operations with a cut stream | largest stream (bytes) | OUTPUT_TRUNCATED |
|---|---|---|---|---|
| 4 | 20 | none | 5339 | no |
| 5 | 9 | none | 20237 | no |
| 9 | 6 | none | 50048 | no |
| 12 | 3 | none | 2259 | no |
| 14 | 1 | none | 0 | no |
| 15 | 4 | none | 3461 | no |
| 16 | 7 | none | 19554 | no |
| 17 | 2 | none | 28547 | no |

## Cost per entry [API-REPORTED unless marked]

| id | sandbox | model | estimated (killed step) | total |
|---|---|---|---|---|
| 4 | 0.7495 | 0.1045 | 0.0000 [ESTIMATED] | 0.8539 |
| 5 | 2.2730 | 0.0972 | 0.0000 [ESTIMATED] | 2.3701 |
| 9 | 1.6245 | 0.0273 | 1.9177 [ESTIMATED] | 3.5696 |
| 12 | 0.4327 | 0.0028 | 0.0000 [ESTIMATED] | 0.4356 |
| 14 | 0.2215 | 0.0023 | 0.0000 [ESTIMATED] | 0.2238 |
| 15 | 0.7438 | 0.0243 | 0.0000 [ESTIMATED] | 0.7681 |
| 16 | 1.9188 | 0.0738 | 0.0000 [ESTIMATED] | 1.9927 |
| 17 | 0.5126 | 0.0021 | 0.0000 [ESTIMATED] | 0.5147 |

## Notes from the records (written 2026-10-05 after the round; the tables above are generated and unedited)

- **D4: round 5 adds nothing** (3 of 8, as in round 4; #12, #15, #17 again). Under D1 the DEV loop stops: two consecutive rounds that add nothing. No round 6.
- **#5, R5 (harness-v1.7.1):** the swap cleared the runner-setup conflict that had ended #5 in every earlier record. The next failure was the one stated before the round (METHODOLOGY, 2026-10-05): the repository's own requirements are unsatisfiable on urllib3. pip named `botocore==1.12.225` (`urllib3>=1.20,<1.26`) against `urllib3==1.26.5`; the annotation had named `requests==2.22.0`, which constrains it the same way. The repair loop then: the tamper gate REJECTED one candidate (its evidence was not verbatim in the log, and it repeated a failed change); the adjudicator chose a candidate that unpinned urllib3 (cleared); `cmake: not found` (SYS_LIB_MISSING; the model added cmake); then `MulticoreTSNE`'s build failed (DEP_BUILD_FAILED). Ending: BLOCKED DEP_BUILD_FAILED. The ladder: first error cleared, environment not resolved. The certificate carries `dependency change: torchvision 0.5.0->0.4.0, Pillow 9.0.0->6.2.2`.
- **#16, R4:** the apt-archive step ran in the install phase and exited 0 (11.4 s), where the operation before it had failed on `security.debian.org ... 404`; the run went on to `ModuleNotFoundError: No module named 'language_evaluation'`. This is the first record in which #16 passed APT_MIRROR_GONE. **Recording defect (D-45, open):** the action's `rewrote` field is read from the final step's output only (`orchestrator.py`, `runner_env.apt_archive_rewrote(result.final.stderr, result.final.stdout)`), so it says `[]` although the step ran; the printed marker is in an install step's output, which the record does not keep. harness-v1.7.1 is sealed and is not changed; the report table's `rewrote []` is wrong in what it implies, and is annotated here, not edited.
- **#9, R3:** data_prep fired on the README's documented command, but the entry had $0.86 left; the step was funded for 124 s and stopped at that limit with 0.0 s of sandbox time measured. Ending: INDETERMINATE COST_CAP (not a verdict on the repository). The recorded total $3.5696 passes the $2.50 entry cap only through the killed-step estimate ($1.9177 ESTIMATED at $0.0152/s for 126 s, the D-27 rule); the API-reported spend is $1.6518. The ledger counts the estimate, so the DEV total is overstated rather than understated.
- **#14, TIMEOUT (not a verdict on the repository):** the baseline's install steps took the same time as in round 4 (20.0 s, 1.4 s), but the documented command, which in round 4 exited within about 70 s, wrote nothing to stdout or stderr for about 580 s and was stopped at the 600 s wall clock (21.5 s of sandbox time billed). Cause not determined; a platform stall is suspected, not shown. The round-4 record of #14 (BLOCKED RUNTIME_ERROR_OTHER) stays as written.
- **R1 and R2 did not fire:** no entry was killed for memory (#17 reached its 60 s smoke pass, as in round 4) and #14 never reached its LU call. R6 flagged nothing.
