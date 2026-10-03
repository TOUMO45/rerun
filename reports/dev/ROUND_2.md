# DEV round 2 — harness-v1.5.1

Protocol: METHODOLOGY.md "harness-v1.5 dev/test protocol". Tag `harness-v1.5.1` (commit `895fa9d4b105`), TREATMENT, the 8 DEV entries once each, entry cap $1.50. DEV entries are tuned on; this is a development signal, not a result. The TEST entries are not in this report (rule F).

- **DEV count (smoke level, D2): 2 of 8** entries with a RUNS_* verdict; kinds: {'smoke_alive': 2} (`smoke_alive` = a 60 s smoke pass that nothing has confirmed; no sustained check in DEV).
- Adds something over earlier rounds (D4): **yes** — count 2 exceeds the best earlier count 1.
- Cost [API-REPORTED]: $6.3323; [ESTIMATED] (killed steps): $0.6237; round total $6.9561. BILLED: AWAITED (the owner reads the account balance and reports it in chat; the last reading, $48.29, was taken before this round).
- Ledger after this round (lower bound, D-27): $41.7207 (base $29.1704 + v1.5 DEV spend $12.5503); ceiling $75.00; DEV total $12.5503 of $40.00. Guard for another round: REFUSED — RESERVE: ledger $41.7207 + the round's central estimate $7.39 + the TEST reserve $26.11 passes the $75.00 ledger ceiling (the TEST phase could not be paid for).

## Verdict per entry

| id | entry | verdict | code | kind of final run | attempts | model attempts | cost USD |
|---|---|---|---|---|---|---|---|
| 4 | damo-cv__img-comp-reference | BLOCKED | RUNTIME_ERROR_OTHER |  | 9 | 9 | 0.6879 |
| 5 | BorgwardtLab__topological-autoencoders | INDETERMINATE | DEP_UNPINNED_CONFLICT |  | 0 | 0 | 0.2478 |
| 9 | omarfoq__fedem | INDETERMINATE | RUNTIME_ERROR_OTHER |  | 10 | 9 | 1.3971 |
| 12 | Mehran-k__SimplE | BLOCKED | RUNTIME_ERROR_OTHER |  | 11 | 9 | 0.7278 |
| 14 | IST-DASLab__M-FAC | BLOCKED | RUNTIME_ERROR_OTHER |  | 10 | 9 | 1.0450 |
| 15 | YuliaRubanova__latent_ode | RUNS_AFTER_REPAIR | DEP_YANKED | smoke_alive | 4 | 3 | 1.3999 |
| 16 | bckim92__sequential-knowledge-transformer | BLOCKED | RUNTIME_ERROR_OTHER |  | 11 | 9 | 0.9352 |
| 17 | Haichao-Zhang__FeatureScatter | RUNS_AFTER_REPAIR | RUNTIME_ERROR_OTHER | smoke_alive | 1 | 0 | 0.5153 |

## Failure classes

Baseline class = the classifier's first reading of the as-published failure; ending = the verdict and its code.

| id | baseline class | classifier readings in order | ending |
|---|---|---|---|
| 4 | RUNTIME_ERROR_OTHER | RUNTIME_ERROR_OTHER → DATA_MISSING → RUNTIME_ERROR_OTHER | BLOCKED RUNTIME_ERROR_OTHER |
| 5 | DEP_UNPINNED_CONFLICT | DEP_UNPINNED_CONFLICT | INDETERMINATE DEP_UNPINNED_CONFLICT |
| 9 | SYS_LIB_MISSING | SYS_LIB_MISSING → DEP_MISSING → RUNTIME_ERROR_OTHER | INDETERMINATE RUNTIME_ERROR_OTHER |
| 12 | DEP_MISSING | DEP_MISSING → RUNTIME_ERROR_OTHER → DEP_UNPINNED_CONFLICT → RUNTIME_ERROR_OTHER | BLOCKED RUNTIME_ERROR_OTHER |
| 14 | GPU_REQUIRED | GPU_REQUIRED → RUNTIME_ERROR_OTHER → RUNTIME_ERROR_OTHER | BLOCKED RUNTIME_ERROR_OTHER |
| 15 | DEP_MISSING | DEP_MISSING → DEP_YANKED | RUNS_AFTER_REPAIR DEP_YANKED |
| 16 | DEP_MISSING | DEP_MISSING → SYS_LIB_MISSING → RUNTIME_ERROR_OTHER | BLOCKED RUNTIME_ERROR_OTHER |
| 17 | RUNTIME_ERROR_OTHER | RUNTIME_ERROR_OTHER | RUNS_AFTER_REPAIR RUNTIME_ERROR_OTHER |

Histogram, baseline class, this round: {'DEP_MISSING': 3, 'RUNTIME_ERROR_OTHER': 2, 'DEP_UNPINNED_CONFLICT': 1, 'SYS_LIB_MISSING': 1, 'GPU_REQUIRED': 1}.

Histogram, ending (verdict code), this round: {'BLOCKED RUNTIME_ERROR_OTHER': 4, 'INDETERMINATE DEP_UNPINNED_CONFLICT': 1, 'INDETERMINATE RUNTIME_ERROR_OTHER': 1, 'RUNS_AFTER_REPAIR DEP_YANKED': 1, 'RUNS_AFTER_REPAIR RUNTIME_ERROR_OTHER': 1}.

Histogram, ending, every earlier record of the DEV and gate entries (all versions, both arms of v1.3.2): {'BLOCKED RUNTIME_ERROR_OTHER': 20, 'BLOCKED DEP_MISSING': 8, 'INDETERMINATE RUNTIME_ERROR_OTHER': 4, 'INDETERMINATE DEP_UNPINNED_CONFLICT': 2, 'INDETERMINATE DEP_YANKED': 2, 'RUNS_AFTER_REPAIR DEP_MISSING': 2, 'INDETERMINATE DEP_MISSING': 2, 'INDETERMINATE RESOURCE_LIMIT': 2, 'INDETERMINATE PIPELINE_ERROR:sandbox:SandboxError': 1, 'INVALID_HARNESS INVALID_HARNESS': 1, 'BLOCKED DEP_NOT_ON_PYPI': 1, 'INDETERMINATE SYS_LIB_MISSING': 1, 'BLOCKED SYS_LIB_MISSING': 1, 'BLOCKED GPU_REQUIRED': 1, 'BLOCKED DATA_MISSING': 1}.

## Deterministic rules that fired (no model call)

- #4: runner torch policy x11; cpu_shim x2
- #5: runner torch policy
- #9: runner torch policy x6; time machine (era 2021-08-11, python 3.7, apt ['build-essential'])
- #12: time machine (era 2020-02-11, python 3.7, apt []); time machine (era None, python None, apt [])
- #14: runner torch policy x10; cpu_shim; time machine (era None, python None, apt [])
- #15: runner torch policy x4; time machine (era 2020-12-03, python 3.8, apt [])
- #16: runner torch policy x5; apt build-essential; time machine (era 2020-06-16, python 3.6, apt []); time machine (era None, python None, apt [])
- #17: runner torch policy x2; removed_api_torch_zero_gradients; time machine (era None, python None, apt [])

## What the model contributed

| id | calls by model | model attempts | env-delta ops | patches proposed | declined | rejected | citations | origin of the passing attempt |
|---|---|---|---|---|---|---|---|---|
| 4 | {'nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B': 1, 'nvidia/nemotron-3-super-120b-a12b': 14, 'nvidia/Nemotron-3-Ultra-550b-a55b': 7} | 9 | 0 | 9 | 0 | 1 | 0 |  |
| 5 | {'nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B': 1, 'nvidia/nemotron-3-super-120b-a12b': 1, 'nvidia/Nemotron-3-Ultra-550b-a55b': 1} | 0 | 0 | 0 | 0 | 0 | 0 |  |
| 9 | {'nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B': 1, 'nvidia/nemotron-3-super-120b-a12b': 15, 'nvidia/Nemotron-3-Ultra-550b-a55b': 3} | 9 | 2 | 5 | 2 | 1 | 1 |  |
| 12 | {'nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B': 1, 'nvidia/nemotron-3-super-120b-a12b': 16, 'nvidia/Nemotron-3-Ultra-550b-a55b': 3} | 9 | 7 | 2 | 0 | 4 | 0 |  |
| 14 | {'nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B': 1, 'nvidia/nemotron-3-super-120b-a12b': 11, 'nvidia/Nemotron-3-Ultra-550b-a55b': 4} | 9 | 0 | 9 | 0 | 1 | 0 |  |
| 15 | {'nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B': 1, 'nvidia/nemotron-3-super-120b-a12b': 4, 'nvidia/Nemotron-3-Ultra-550b-a55b': 2} | 3 | 2 | 0 | 1 | 0 | 0 | model |
| 16 | {'nvidia/nemotron-3-super-120b-a12b': 15, 'nvidia/Nemotron-3-Ultra-550b-a55b': 3} | 9 | 2 | 0 | 7 | 0 | 0 |  |
| 17 | {'nvidia/nemotron-3-super-120b-a12b': 1, 'nvidia/Nemotron-3-Ultra-550b-a55b': 1} | 0 | 0 | 0 | 0 | 0 | 0 | time_machine |

## Stream flags (D-41)

| id | operations | operations with a cut stream | largest stream (bytes) | OUTPUT_TRUNCATED |
|---|---|---|---|---|
| 4 | 14 | none | 5352 | no |
| 5 | 1 | none | 3895 | no |
| 9 | 8 | none | 50048 | no |
| 12 | 8 | none | 12066 | no |
| 14 | 13 | none | 34527 | no |
| 15 | 4 | none | 3168 | no |
| 16 | 5 | none | 19554 | no |
| 17 | 2 | none | 38985 | no |

## Cost per entry [API-REPORTED unless marked]

| id | sandbox | model | estimated (killed step) | total |
|---|---|---|---|---|
| 4 | 0.5584 | 0.1295 | 0.0000 [ESTIMATED] | 0.6879 |
| 5 | 0.2440 | 0.0038 | 0.0000 [ESTIMATED] | 0.2478 |
| 9 | 1.2768 | 0.1203 | 0.0000 [ESTIMATED] | 1.3971 |
| 12 | 0.6542 | 0.0736 | 0.0000 [ESTIMATED] | 0.7278 |
| 14 | 0.9680 | 0.0770 | 0.0000 [ESTIMATED] | 1.0450 |
| 15 | 0.7562 | 0.0200 | 0.6237 [ESTIMATED] | 1.3999 |
| 16 | 0.8177 | 0.1175 | 0.0000 [ESTIMATED] | 0.9352 |
| 17 | 0.5126 | 0.0027 | 0.0000 [ESTIMATED] | 0.5153 |
