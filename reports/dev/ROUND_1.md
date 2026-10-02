# DEV round 1 — harness-v1.5.0

Protocol: METHODOLOGY.md "harness-v1.5 dev/test protocol". Tag `harness-v1.5.0` (commit `a6cdb42a6c70`), TREATMENT, the 8 DEV entries once each, entry cap $1.50. DEV entries are tuned on; this is a development signal, not a result. The TEST entries are not in this report (rule F).

- **DEV count (smoke level, D2): 1 of 8** entries with a RUNS_* verdict; kinds: {'smoke_alive': 1} (`smoke_alive` = a 60 s smoke pass that nothing has confirmed; no sustained check in DEV).
- Adds something over earlier rounds (D4): **yes** — count 1 exceeds the best earlier count 0.
- Cost [API-REPORTED]: $5.4316; [ESTIMATED] (killed steps): $0.1327; round total $5.5643. BILLED: AWAITED (the owner reads the account balance and reports it in chat).
- Ledger after this round (lower bound, D-27): $34.7400 (base $29.1704 + v1.5 DEV spend $5.5696); ceiling $75.00; DEV total $5.5696 of $40.00. Guard for another round: OK.

## Verdict per entry

| id | entry | verdict | code | kind of final run | attempts | model attempts | cost USD |
|---|---|---|---|---|---|---|---|
| 4 | damo-cv__img-comp-reference | BLOCKED | RUNTIME_ERROR_OTHER |  | 9 | 9 | 0.7195 |
| 5 | BorgwardtLab__topological-autoencoders | INDETERMINATE | DEP_UNPINNED_CONFLICT |  | 0 | 0 | 0.2331 |
| 9 | omarfoq__fedem | INDETERMINATE | DEP_YANKED |  | 0 | 0 | 0.0230 |
| 12 | Mehran-k__SimplE | BLOCKED | RUNTIME_ERROR_OTHER |  | 10 | 9 | 0.3528 |
| 14 | IST-DASLab__M-FAC | BLOCKED | RUNTIME_ERROR_OTHER |  | 9 | 9 | 1.0825 |
| 15 | YuliaRubanova__latent_ode | RUNS_AFTER_REPAIR | DEP_YANKED | smoke_alive | 4 | 3 | 0.7284 |
| 16 | bckim92__sequential-knowledge-transformer | BLOCKED | RUNTIME_ERROR_OTHER |  | 11 | 9 | 0.9165 |
| 17 | Haichao-Zhang__FeatureScatter | INDETERMINATE | RUNTIME_ERROR_OTHER |  | 6 | 6 | 1.5084 |

## Failure classes

Baseline class = the classifier's first reading of the as-published failure; ending = the verdict and its code.

| id | baseline class | classifier readings in order | ending |
|---|---|---|---|
| 4 | RUNTIME_ERROR_OTHER | RUNTIME_ERROR_OTHER → DATA_MISSING → DATA_MISSING → RUNTIME_ERROR_OTHER | BLOCKED RUNTIME_ERROR_OTHER |
| 5 | DEP_UNPINNED_CONFLICT | DEP_UNPINNED_CONFLICT | INDETERMINATE DEP_UNPINNED_CONFLICT |
| 9 | DEP_YANKED | DEP_YANKED | INDETERMINATE DEP_YANKED |
| 12 | DEP_MISSING | DEP_MISSING → RUNTIME_ERROR_OTHER | BLOCKED RUNTIME_ERROR_OTHER |
| 14 | RUNTIME_ERROR_OTHER | RUNTIME_ERROR_OTHER → RUNTIME_ERROR_OTHER | BLOCKED RUNTIME_ERROR_OTHER |
| 15 | DEP_MISSING | DEP_MISSING → DEP_YANKED | RUNS_AFTER_REPAIR DEP_YANKED |
| 16 | DEP_MISSING | DEP_MISSING → SYS_LIB_MISSING → RUNTIME_ERROR_OTHER | BLOCKED RUNTIME_ERROR_OTHER |
| 17 | RUNTIME_ERROR_OTHER | RUNTIME_ERROR_OTHER | INDETERMINATE RUNTIME_ERROR_OTHER |

Histogram, baseline class, this round: {'RUNTIME_ERROR_OTHER': 3, 'DEP_MISSING': 3, 'DEP_UNPINNED_CONFLICT': 1, 'DEP_YANKED': 1}.

Histogram, ending (verdict code), this round: {'BLOCKED RUNTIME_ERROR_OTHER': 4, 'INDETERMINATE DEP_UNPINNED_CONFLICT': 1, 'INDETERMINATE DEP_YANKED': 1, 'RUNS_AFTER_REPAIR DEP_YANKED': 1, 'INDETERMINATE RUNTIME_ERROR_OTHER': 1}.

Histogram, ending, every earlier record of the DEV and gate entries (all versions, both arms of v1.3.2): {'BLOCKED RUNTIME_ERROR_OTHER': 20, 'BLOCKED DEP_MISSING': 8, 'INDETERMINATE RUNTIME_ERROR_OTHER': 4, 'INDETERMINATE DEP_UNPINNED_CONFLICT': 2, 'INDETERMINATE DEP_YANKED': 2, 'RUNS_AFTER_REPAIR DEP_MISSING': 2, 'INDETERMINATE DEP_MISSING': 2, 'INDETERMINATE RESOURCE_LIMIT': 2, 'INDETERMINATE PIPELINE_ERROR:sandbox:SandboxError': 1, 'INVALID_HARNESS INVALID_HARNESS': 1, 'BLOCKED DEP_NOT_ON_PYPI': 1, 'INDETERMINATE SYS_LIB_MISSING': 1, 'BLOCKED SYS_LIB_MISSING': 1, 'BLOCKED GPU_REQUIRED': 1, 'BLOCKED DATA_MISSING': 1}.

## Deterministic rules that fired (no model call)

- #4: runner torch policy x13; cpu_shim x3; exit_site_hook
- #5: runner torch policy
- #9: runner torch policy
- #12: time machine (era 2020-02-11, python 3.7, apt [])
- #14: runner torch policy x13; cpu_shim x4
- #15: runner torch policy x5; time machine (era 2020-12-03, python 3.8, apt [])
- #16: runner torch policy x5; apt build-essential; time machine (era 2020-06-16, python 3.6, apt []); time machine (era None, python None, apt [])
- #17: runner torch policy x5

## What the model contributed

| id | calls by model | model attempts | env-delta ops | patches proposed | declined | rejected | citations | origin of the passing attempt |
|---|---|---|---|---|---|---|---|---|
| 4 | {'nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B': 1, 'nvidia/nemotron-3-super-120b-a12b': 11, 'nvidia/Nemotron-3-Ultra-550b-a55b': 6} | 9 | 0 | 9 | 0 | 1 | 0 |  |
| 5 | {'nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B': 1, 'nvidia/nemotron-3-super-120b-a12b': 1, 'nvidia/Nemotron-3-Ultra-550b-a55b': 1} | 0 | 0 | 0 | 0 | 0 | 0 |  |
| 9 | {'nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B': 1, 'nvidia/nemotron-3-super-120b-a12b': 1, 'nvidia/Nemotron-3-Ultra-550b-a55b': 1} | 0 | 0 | 0 | 0 | 0 | 0 |  |
| 12 | {'nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B': 1, 'nvidia/nemotron-3-super-120b-a12b': 11, 'nvidia/Nemotron-3-Ultra-550b-a55b': 2} | 9 | 0 | 8 | 1 | 6 | 1 |  |
| 14 | {'nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B': 1, 'nvidia/nemotron-3-super-120b-a12b': 13, 'nvidia/Nemotron-3-Ultra-550b-a55b': 5} | 9 | 0 | 8 | 1 | 0 | 0 |  |
| 15 | {'nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B': 1, 'nvidia/nemotron-3-super-120b-a12b': 4, 'nvidia/Nemotron-3-Ultra-550b-a55b': 2} | 3 | 3 | 0 | 0 | 0 | 0 | model |
| 16 | {'nvidia/nemotron-3-super-120b-a12b': 13, 'nvidia/Nemotron-3-Ultra-550b-a55b': 2} | 9 | 6 | 0 | 6 | 1 | 0 |  |
| 17 | {'nvidia/nemotron-3-super-120b-a12b': 7, 'nvidia/Nemotron-3-Ultra-550b-a55b': 1} | 6 | 0 | 6 | 0 | 0 | 9 |  |

## Stream flags (D-41)

| id | operations | operations with a cut stream | largest stream (bytes) | OUTPUT_TRUNCATED |
|---|---|---|---|---|
| 4 | 16 | none | 5233 | no |
| 5 | 1 | none | 3895 | no |
| 9 | 1 | none | 1720 | no |
| 12 | 6 | none | 2324 | no |
| 14 | 16 | none | 32587 | no |
| 15 | 5 | none | 3168 | no |
| 16 | 5 | none | 19554 | no |
| 17 | 6 | none | 517 | no |

## Cost per entry [API-REPORTED unless marked]

| id | sandbox | model | estimated (killed step) | total |
|---|---|---|---|---|
| 4 | 0.6050 | 0.1145 | 0.0000 [ESTIMATED] | 0.7195 |
| 5 | 0.2290 | 0.0041 | 0.0000 [ESTIMATED] | 0.2331 |
| 9 | 0.0189 | 0.0041 | 0.0000 [ESTIMATED] | 0.0230 |
| 12 | 0.3039 | 0.0489 | 0.0000 [ESTIMATED] | 0.3528 |
| 14 | 0.9981 | 0.0845 | 0.0000 [ESTIMATED] | 1.0825 |
| 15 | 0.7062 | 0.0222 | 0.0000 [ESTIMATED] | 0.7284 |
| 16 | 0.8175 | 0.0991 | 0.0000 [ESTIMATED] | 0.9165 |
| 17 | 1.3520 | 0.0237 | 0.1327 [ESTIMATED] | 1.5084 |
