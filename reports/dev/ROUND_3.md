# DEV round 3 — harness-v1.5.2

Protocol: METHODOLOGY.md "harness-v1.5 dev/test protocol". Tag `harness-v1.5.2` (commit `a41c56771dfc`), TREATMENT, the 8 DEV entries once each, entry cap $1.50. DEV entries are tuned on; this is a development signal, not a result. The TEST entries are not in this report (rule F).

- **DEV count (smoke level, D2): 3 of 8** entries with a RUNS_* verdict; kinds: {'smoke_alive': 3} (`smoke_alive` = a 60 s smoke pass that nothing has confirmed; no sustained check in DEV).
- Adds something over earlier rounds (D4): **yes** — count 3 exceeds the best earlier count 2.
- Cost [API-REPORTED]: $5.8532; [ESTIMATED] (killed steps): $0.0000; round total $5.8532. BILLED: AWAITED (the owner reads the account balance and reports it in chat).

> Annotation, 2026-10-04 13:50 local: the owner's reading after this round is **$47.61 [BILLED]**, $0.35 below the $47.96 reading after round 2. The reading was taken about one minute into round 4 (its first entry was building its baseline image), so at most a few cents of round 4 are inside the $0.35 (`reports/dev/BILLED_READINGS.md`).
>
> Annotation, same date, entry #14: its RUNS_AFTER_REPAIR follows a **model patch that passed the tamper gate** and changes the algorithm's numerics: `torch.lu(x, pivot=False)` became `torch.linalg.lu_factor(x)`, which pivots; the repository's code relies on no pivoting (it takes `triu` of the factor). The gate refuses a patch that makes the code do less; it does not check numerical equivalence. The verdict stands as recorded (a 60 s smoke pass after a gated repair); it is not a reproduction of the paper's computation, and the certificate's diff shows exactly what changed. Logged as candidate defect D-44 (a gate-passed patch may change what the code computes), to be registered in the Phase D update.
- Ledger after this round (lower bound, D-27): $47.5792 (base $29.1704 + v1.5 DEV spend $18.4088); ceiling $75.00; DEV total $18.4088 of $40.00. Guard for another round: REFUSED — RESERVE: ledger $47.5792 + the round's central estimate $7.39 + the TEST reserve $26.11 passes the $75.00 ledger ceiling (the TEST phase could not be paid for).

## Verdict per entry

| id | entry | verdict | code | kind of final run | attempts | model attempts | cost USD |
|---|---|---|---|---|---|---|---|
| 4 | damo-cv__img-comp-reference | BLOCKED | RUNTIME_ERROR_OTHER |  | 9 | 9 | 0.7189 |
| 5 | BorgwardtLab__topological-autoencoders | INDETERMINATE | DEP_UNPINNED_CONFLICT |  | 0 | 0 | 0.2260 |
| 9 | omarfoq__fedem | INDETERMINATE | SYS_LIB_MISSING |  | 3 | 3 | 1.1511 |
| 12 | Mehran-k__SimplE | RUNS_AFTER_REPAIR | RUNTIME_ERROR_OTHER | smoke_alive | 2 | 0 | 0.4463 |
| 14 | IST-DASLab__M-FAC | RUNS_AFTER_REPAIR | RUNTIME_ERROR_OTHER | smoke_alive | 4 | 3 | 0.5430 |
| 15 | YuliaRubanova__latent_ode | RUNS_AFTER_REPAIR | DEP_YANKED | smoke_alive | 4 | 3 | 0.8811 |
| 16 | bckim92__sequential-knowledge-transformer | BLOCKED | RUNTIME_ERROR_OTHER |  | 11 | 9 | 0.9232 |
| 17 | Haichao-Zhang__FeatureScatter | INDETERMINATE | RESOURCE_LIMIT |  | 2 | 0 | 0.9636 |

## Failure classes

Baseline class = the classifier's first reading of the as-published failure; ending = the verdict and its code.

| id | baseline class | classifier readings in order | ending |
|---|---|---|---|
| 4 | RUNTIME_ERROR_OTHER | RUNTIME_ERROR_OTHER → DATA_MISSING → DATA_MISSING → RUNTIME_ERROR_OTHER | BLOCKED RUNTIME_ERROR_OTHER |
| 5 | DEP_UNPINNED_CONFLICT | DEP_UNPINNED_CONFLICT | INDETERMINATE DEP_UNPINNED_CONFLICT |
| 9 | RUNTIME_ERROR_OTHER | RUNTIME_ERROR_OTHER → SYS_LIB_MISSING | INDETERMINATE SYS_LIB_MISSING |
| 12 | DEP_MISSING | DEP_MISSING → RUNTIME_ERROR_OTHER | RUNS_AFTER_REPAIR RUNTIME_ERROR_OTHER |
| 14 | GPU_REQUIRED | GPU_REQUIRED → RUNTIME_ERROR_OTHER | RUNS_AFTER_REPAIR RUNTIME_ERROR_OTHER |
| 15 | DEP_MISSING | DEP_MISSING → DEP_YANKED | RUNS_AFTER_REPAIR DEP_YANKED |
| 16 | DEP_MISSING | DEP_MISSING → SYS_LIB_MISSING → RUNTIME_ERROR_OTHER | BLOCKED RUNTIME_ERROR_OTHER |
| 17 | RUNTIME_ERROR_OTHER | RUNTIME_ERROR_OTHER → RESOURCE_LIMIT | INDETERMINATE RESOURCE_LIMIT |

Histogram, baseline class, this round: {'RUNTIME_ERROR_OTHER': 3, 'DEP_MISSING': 3, 'DEP_UNPINNED_CONFLICT': 1, 'GPU_REQUIRED': 1}.

Histogram, ending (verdict code), this round: {'BLOCKED RUNTIME_ERROR_OTHER': 2, 'RUNS_AFTER_REPAIR RUNTIME_ERROR_OTHER': 2, 'INDETERMINATE DEP_UNPINNED_CONFLICT': 1, 'INDETERMINATE SYS_LIB_MISSING': 1, 'RUNS_AFTER_REPAIR DEP_YANKED': 1, 'INDETERMINATE RESOURCE_LIMIT': 1}.

Histogram, ending, every earlier record of the DEV and gate entries (all versions, both arms of v1.3.2): {'BLOCKED RUNTIME_ERROR_OTHER': 20, 'BLOCKED DEP_MISSING': 8, 'INDETERMINATE RUNTIME_ERROR_OTHER': 4, 'INDETERMINATE DEP_UNPINNED_CONFLICT': 2, 'INDETERMINATE DEP_YANKED': 2, 'RUNS_AFTER_REPAIR DEP_MISSING': 2, 'INDETERMINATE DEP_MISSING': 2, 'INDETERMINATE RESOURCE_LIMIT': 2, 'INDETERMINATE PIPELINE_ERROR:sandbox:SandboxError': 1, 'INVALID_HARNESS INVALID_HARNESS': 1, 'BLOCKED DEP_NOT_ON_PYPI': 1, 'INDETERMINATE SYS_LIB_MISSING': 1, 'BLOCKED SYS_LIB_MISSING': 1, 'BLOCKED GPU_REQUIRED': 1, 'BLOCKED DATA_MISSING': 1}.

## Deterministic rules that fired (no model call)

- #4: runner torch policy x12; cpu_shim x3; exit_site_hook
- #5: runner torch policy
- #9: runner torch policy x4; missing_compiler_build_essential
- #12: time machine (era 2020-02-11, python 3.7, apt []); time machine (era None, python None, apt [])
- #14: runner torch policy x5; cpu_shim; time machine (era None, python None, apt [])
- #15: runner torch policy x5; time machine (era 2020-12-03, python 3.8, apt [])
- #16: runner torch policy x5; apt build-essential; time machine (era 2020-06-16, python 3.6, apt []); time machine (era None, python None, apt [])
- #17: runner torch policy x3; removed_api_torch_zero_gradients; time machine (era None, python None, apt []) x2

## What the model contributed

| id | calls by model | model attempts | env-delta ops | patches proposed | declined | rejected | citations | origin of the passing attempt |
|---|---|---|---|---|---|---|---|---|
| 4 | {'nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B': 1, 'nvidia/nemotron-3-super-120b-a12b': 13, 'nvidia/Nemotron-3-Ultra-550b-a55b': 6} | 9 | 0 | 8 | 1 | 1 | 0 |  |
| 5 | {'nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B': 1, 'nvidia/nemotron-3-super-120b-a12b': 1, 'nvidia/Nemotron-3-Ultra-550b-a55b': 1} | 0 | 0 | 0 | 0 | 0 | 0 |  |
| 9 | {'nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B': 2, 'nvidia/nemotron-3-super-120b-a12b': 5, 'nvidia/Nemotron-3-Ultra-550b-a55b': 2} | 3 | 3 | 0 | 1 | 0 | 0 |  |
| 12 | {'nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B': 1, 'nvidia/nemotron-3-super-120b-a12b': 1, 'nvidia/Nemotron-3-Ultra-550b-a55b': 1} | 0 | 0 | 0 | 0 | 0 | 0 | time_machine |
| 14 | {'nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B': 1, 'nvidia/nemotron-3-super-120b-a12b': 4, 'nvidia/Nemotron-3-Ultra-550b-a55b': 2} | 3 | 0 | 3 | 0 | 0 | 0 | model |
| 15 | {'nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B': 1, 'nvidia/nemotron-3-super-120b-a12b': 4, 'nvidia/Nemotron-3-Ultra-550b-a55b': 2} | 3 | 3 | 0 | 0 | 0 | 0 | model |
| 16 | {'nvidia/nemotron-3-super-120b-a12b': 13, 'nvidia/Nemotron-3-Ultra-550b-a55b': 2} | 9 | 2 | 1 | 6 | 1 | 0 |  |
| 17 | {'nvidia/nemotron-3-super-120b-a12b': 1, 'nvidia/Nemotron-3-Ultra-550b-a55b': 1} | 0 | 0 | 0 | 0 | 0 | 0 |  |

## Stream flags (D-41)

| id | operations | operations with a cut stream | largest stream (bytes) | OUTPUT_TRUNCATED |
|---|---|---|---|---|
| 4 | 15 | none | 5274 | no |
| 5 | 1 | none | 3965 | no |
| 9 | 4 | none | 50268 | no |
| 12 | 3 | none | 2259 | no |
| 14 | 6 | none | 34527 | no |
| 15 | 5 | none | 3461 | no |
| 16 | 5 | none | 19554 | no |
| 17 | 3 | none | 19982 | no |

## Cost per entry [API-REPORTED unless marked]

| id | sandbox | model | estimated (killed step) | total |
|---|---|---|---|---|
| 4 | 0.5856 | 0.1332 | 0.0000 [ESTIMATED] | 0.7189 |
| 5 | 0.2221 | 0.0039 | 0.0000 [ESTIMATED] | 0.2260 |
| 9 | 1.1119 | 0.0392 | 0.0000 [ESTIMATED] | 1.1511 |
| 12 | 0.4432 | 0.0031 | 0.0000 [ESTIMATED] | 0.4463 |
| 14 | 0.5227 | 0.0202 | 0.0000 [ESTIMATED] | 0.5430 |
| 15 | 0.8595 | 0.0216 | 0.0000 [ESTIMATED] | 0.8811 |
| 16 | 0.8255 | 0.0978 | 0.0000 [ESTIMATED] | 0.9232 |
| 17 | 0.9614 | 0.0022 | 0.0000 [ESTIMATED] | 0.9636 |
