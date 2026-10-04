# DEV round 4 — harness-v1.6.0

Protocol: METHODOLOGY.md "harness-v1.5 dev/test protocol". Tag `harness-v1.6.0` (commit `b0b7d92473d0`), TREATMENT, the 8 DEV entries once each, entry cap $1.50. DEV entries are tuned on; this is a development signal, not a result. The TEST entries are not in this report (rule F).

- **DEV count (smoke level, D2): 3 of 8** entries with a RUNS_* verdict; kinds: {'smoke_alive': 3} (`smoke_alive` = a 60 s smoke pass that nothing has confirmed; no sustained check in DEV).
- Adds something over earlier rounds (D4): **no** — count 3 does not exceed the best earlier count 3 and no entry reaches RUNS_* for the first time.
- Cost [API-REPORTED]: $5.3490; [ESTIMATED] (killed steps): $0.0000; round total $5.3490. BILLED: $47.11 (the owner's reading after this round, 2026-10-04; $0.50 below the $47.61 reading taken about one minute into this round; reports/dev/BILLED_READINGS.md).
- Ledger after this round (lower bound, D-27): $52.9336 (base $29.1704 + v1.5 DEV spend $23.7632); ceiling $100.00; DEV total $23.7632 of $40.00. Guard for another round: OK.

> Notes written with this report, 2026-10-04 (after the round; nothing above is edited by them):
>
> - **Launcher.** `dev_round4_launcher.txt` records three launches. The first two (13:18 and 13:41 local) returned 3 with `PREFLIGHT REFUSED (harness-v1.6.0): working tree is dirty` (the round-3 records were not yet committed): no sandbox, no model call, no spend. The third (13:47) ran the round and returned 0 at 14:33.
> - **Ledger reader fixed before this report.** `devtest/budget.read_spend` and this script globbed `harness-v1.5*` only, so a DEV round under another tag (this one, `harness-v1.6.0/dev/`) was not counted. Round 4's own start was unaffected (its guard read $47.5792, which was the ledger then); the guard for round 5 would have under-read by this round's $5.3543. Both now read `harness-v*/dev/`, with a test; the ledger line above is the corrected one.
> - **D4.** This round adds nothing (3 of 8 again; #12, #15, #17 had RUNS_* before). Under D1 a second consecutive round that adds nothing stops the DEV loop: round 5 must add something or the loop freezes.
> - **#14.** Round 3's RUNS_AFTER_REPAIR (a gated model patch that swapped `torch.lu(x, pivot=False)` for the pivoting `torch.linalg.lu_factor`, candidate D-44) was not drawn again: this round's classifier read `RuntimeError: linalg.lu_factor: LU without pivoting is not implemented on the CPU` (GPU_REQUIRED), then the model's patches reached `AttributeError: 'HInvFastUpMulti' object has no attribute 'moddev'` and no candidate changed the exit outcome. One LLM run is one draw.
> - **#9** ended INDETERMINATE COST_CAP ($1.3466 of the $1.50 cap spent; the next operation could not be funded) with `AssertionError: Download cifar10 dataset!!` as its last classified failure, so no Tavily dataset lookup was made (item S looks up only for a BLOCKED run, v1.6 review defect 9).
> - **BILLED.** The owner's reading after this round is **$47.11 [BILLED]**, $0.50 below the $47.61 reading taken about one minute into the round: the interval holds round 4 ($5.3543 API-reported with its upload smoke test) and nothing else that spends.

## Verdict per entry

| id | entry | verdict | code | kind of final run | attempts | model attempts | cost USD |
|---|---|---|---|---|---|---|---|
| 4 | damo-cv__img-comp-reference | BLOCKED | DATA_MISSING |  | 9 | 9 | 0.6094 |
| 5 | BorgwardtLab__topological-autoencoders | INDETERMINATE | DEP_UNPINNED_CONFLICT |  | 0 | 0 | 0.2174 |
| 9 | omarfoq__fedem | INDETERMINATE | DATA_MISSING |  | 7 | 6 | 1.3466 |
| 12 | Mehran-k__SimplE | RUNS_AFTER_REPAIR | API_REMOVED | smoke_alive | 2 | 0 | 0.4376 |
| 14 | IST-DASLab__M-FAC | BLOCKED | RUNTIME_ERROR_OTHER |  | 10 | 9 | 0.9441 |
| 15 | YuliaRubanova__latent_ode | RUNS_AFTER_REPAIR | DEP_YANKED | smoke_alive | 4 | 3 | 0.4934 |
| 16 | bckim92__sequential-knowledge-transformer | INDETERMINATE | APT_MIRROR_GONE |  | 2 | 0 | 0.7919 |
| 17 | Haichao-Zhang__FeatureScatter | RUNS_AFTER_REPAIR | API_REMOVED | smoke_alive | 1 | 0 | 0.5087 |

## Failure classes

Baseline class = the classifier's first reading of the as-published failure; ending = the verdict and its code.

| id | baseline class | classifier readings in order | ending |
|---|---|---|---|
| 4 | RUNTIME_ERROR_OTHER | RUNTIME_ERROR_OTHER → DATA_MISSING → DATA_MISSING | BLOCKED DATA_MISSING |
| 5 | DEP_UNPINNED_CONFLICT | DEP_UNPINNED_CONFLICT | INDETERMINATE DEP_UNPINNED_CONFLICT |
| 9 | SYS_LIB_MISSING | SYS_LIB_MISSING → DEP_MISSING → DATA_MISSING | INDETERMINATE DATA_MISSING |
| 12 | DEP_MISSING | DEP_MISSING → API_REMOVED | RUNS_AFTER_REPAIR API_REMOVED |
| 14 | GPU_REQUIRED | GPU_REQUIRED → GPU_REQUIRED → RUNTIME_ERROR_OTHER | BLOCKED RUNTIME_ERROR_OTHER |
| 15 | DEP_MISSING | DEP_MISSING → DEP_YANKED | RUNS_AFTER_REPAIR DEP_YANKED |
| 16 | DEP_MISSING | DEP_MISSING → SYS_LIB_MISSING → APT_MIRROR_GONE | INDETERMINATE APT_MIRROR_GONE |
| 17 | API_REMOVED | API_REMOVED | RUNS_AFTER_REPAIR API_REMOVED |

Histogram, baseline class, this round: {'DEP_MISSING': 3, 'RUNTIME_ERROR_OTHER': 1, 'DEP_UNPINNED_CONFLICT': 1, 'SYS_LIB_MISSING': 1, 'GPU_REQUIRED': 1, 'API_REMOVED': 1}.

Histogram, ending (verdict code), this round: {'RUNS_AFTER_REPAIR API_REMOVED': 2, 'BLOCKED DATA_MISSING': 1, 'INDETERMINATE DEP_UNPINNED_CONFLICT': 1, 'INDETERMINATE DATA_MISSING': 1, 'BLOCKED RUNTIME_ERROR_OTHER': 1, 'RUNS_AFTER_REPAIR DEP_YANKED': 1, 'INDETERMINATE APT_MIRROR_GONE': 1}.

Histogram, ending, every earlier record of the DEV and gate entries (all versions, both arms of v1.3.2): {'BLOCKED RUNTIME_ERROR_OTHER': 20, 'BLOCKED DEP_MISSING': 8, 'INDETERMINATE RUNTIME_ERROR_OTHER': 4, 'INDETERMINATE DEP_UNPINNED_CONFLICT': 2, 'INDETERMINATE DEP_YANKED': 2, 'RUNS_AFTER_REPAIR DEP_MISSING': 2, 'INDETERMINATE DEP_MISSING': 2, 'INDETERMINATE RESOURCE_LIMIT': 2, 'INDETERMINATE PIPELINE_ERROR:sandbox:SandboxError': 1, 'INVALID_HARNESS INVALID_HARNESS': 1, 'BLOCKED DEP_NOT_ON_PYPI': 1, 'INDETERMINATE SYS_LIB_MISSING': 1, 'BLOCKED SYS_LIB_MISSING': 1, 'BLOCKED GPU_REQUIRED': 1, 'BLOCKED DATA_MISSING': 1}.

## Outcome ladder (harness-v1.6, L; stored fields)

Counts, this round: first error cleared **7 of 8** (by origin: {'time_machine': 6, 'model': 1}); environment resolved **6 of 8**; entrypoint runs (RUNS_*, smoke level) **3 of 8**.

| id | first error cleared | cleared by | env resolved | entrypoint runs |
|---|---|---|---|---|
| 4 | yes | model | yes | no |
| 5 | no |  | no | no |
| 9 | yes | time_machine | yes | no |
| 12 | yes | time_machine | yes | yes |
| 14 | yes | time_machine | yes | no |
| 15 | yes | time_machine | yes | yes |
| 16 | yes | time_machine | no | no |
| 17 | yes | time_machine | yes | yes |

## Blocker (harness-v1.6, B; stored fields; none on a RUNS_AFTER_REPAIR run)

| id | class | family | phase | attribution | fixable by | evidence | what a human must supply | sources |
|---|---|---|---|---|---|---|---|---|
| 4 | DATA_MISSING | Data | repo_run | REPO | human | `FileNotFoundError: [Errno 2] No such file or directory: 'original.png'` | the dataset the repository expects at original.png, obtained as its README describes | https://datumo.com/blog/tech/list-of-free-datasets-for-your-image-training-models; http://www.cvpapers.com/datasets.html; https://images.cv |
| 5 | DEP_UNPINNED_CONFLICT | Dependencies | runner_setup | ENV | deterministic | `ERROR: ResolutionImpossible: for help visit https://pip.pypa.io/en/latest/topics/dependency-resolution/#dealing-with-dependency-conflicts` | nothing, if the era lock resolves it; otherwise the exact release of the package the authors used | not looked up |
| 9 | DATA_MISSING | Data | repo_run | REPO | human | `AssertionError: Download cifar10 dataset!!` | the dataset the repository expects at the path the code opens, obtained as its README describes | not looked up |
| 12 | (none) | | | | | | | |
| 14 | RUNTIME_ERROR_OTHER | Code | repo_run | REPO | model | `AttributeError: 'HInvFastUpMulti' object has no attribute 'moddev'` | a code change; the repairer proposes one and the tamper gate decides | not looked up |
| 15 | (none) | | | | | | | |
| 16 | APT_MIRROR_GONE | Environment | repo_install | ENV | platform | `E: Failed to fetch http://security.debian.org/debian-security/pool/updates/main/p/perl/perl-base_5.32.1-4%2bdeb11u5_amd64.deb  404  Not Found [IP: 151.101.246.1` | a base image whose distribution is still on the mirrors | not looked up |
| 17 | (none) | | | | | | | |

## Deterministic rules that fired (no model call)

- #4: runner torch policy x9; cpu_shim x2
- #5: runner torch policy
- #9: runner torch policy x5; time machine (era 2021-08-11, python 3.7, apt ['build-essential'])
- #12: time machine (era 2020-02-11, python 3.7, apt []); time machine (era None, python None, apt [])
- #14: runner torch policy x9; cpu_shim; time machine (era None, python None, apt [])
- #15: runner torch policy x3; time machine (era 2020-12-03, python 3.8, apt [])
- #16: runner torch policy x3; apt build-essential; time machine (era 2020-06-16, python 3.6, apt []); time machine (era None, python None, apt [])
- #17: runner torch policy x2; removed_api_torch_zero_gradients; time machine (era None, python None, apt [])

## What the model contributed

| id | calls by model | model attempts | env-delta ops | patches proposed | declined | rejected | citations | origin of the passing attempt |
|---|---|---|---|---|---|---|---|---|
| 4 | {'nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B': 1, 'nvidia/nemotron-3-super-120b-a12b': 12, 'nvidia/Nemotron-3-Ultra-550b-a55b': 6} | 9 | 0 | 9 | 0 | 3 | 0 |  |
| 5 | {'nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B': 2, 'nvidia/nemotron-3-super-120b-a12b': 1, 'nvidia/Nemotron-3-Ultra-550b-a55b': 1} | 0 | 0 | 0 | 0 | 0 | 0 |  |
| 9 | {'nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B': 1, 'nvidia/nemotron-3-super-120b-a12b': 9, 'nvidia/Nemotron-3-Ultra-550b-a55b': 2} | 6 | 3 | 1 | 2 | 0 | 0 |  |
| 12 | {'nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B': 1, 'nvidia/nemotron-3-super-120b-a12b': 1, 'nvidia/Nemotron-3-Ultra-550b-a55b': 1} | 0 | 0 | 0 | 0 | 0 | 0 | time_machine |
| 14 | {'nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B': 1, 'nvidia/nemotron-3-super-120b-a12b': 11, 'nvidia/Nemotron-3-Ultra-550b-a55b': 5} | 9 | 2 | 7 | 1 | 1 | 0 |  |
| 15 | {'nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B': 1, 'nvidia/nemotron-3-super-120b-a12b': 4, 'nvidia/Nemotron-3-Ultra-550b-a55b': 2} | 3 | 1 | 0 | 2 | 0 | 0 | model |
| 16 | {'nvidia/nemotron-3-super-120b-a12b': 1, 'nvidia/Nemotron-3-Ultra-550b-a55b': 1} | 0 | 0 | 0 | 0 | 0 | 0 |  |
| 17 | {'nvidia/nemotron-3-super-120b-a12b': 1, 'nvidia/Nemotron-3-Ultra-550b-a55b': 1} | 0 | 0 | 0 | 0 | 0 | 0 | time_machine |

## Stream flags (D-41)

| id | operations | operations with a cut stream | largest stream (bytes) | OUTPUT_TRUNCATED |
|---|---|---|---|---|
| 4 | 12 | none | 5274 | no |
| 5 | 1 | none | 3965 | no |
| 9 | 5 | none | 50048 | no |
| 12 | 3 | none | 2259 | no |
| 14 | 12 | none | 33866 | no |
| 15 | 3 | none | 3461 | no |
| 16 | 3 | none | 19554 | no |
| 17 | 2 | none | 42424 | no |

## Cost per entry [API-REPORTED unless marked]

| id | sandbox | model | estimated (killed step) | total |
|---|---|---|---|---|
| 4 | 0.4984 | 0.1110 | 0.0000 [ESTIMATED] | 0.6094 |
| 5 | 0.2115 | 0.0059 | 0.0000 [ESTIMATED] | 0.2174 |
| 9 | 1.2785 | 0.0681 | 0.0000 [ESTIMATED] | 1.3466 |
| 12 | 0.4351 | 0.0025 | 0.0000 [ESTIMATED] | 0.4376 |
| 14 | 0.8383 | 0.1058 | 0.0000 [ESTIMATED] | 0.9441 |
| 15 | 0.4727 | 0.0207 | 0.0000 [ESTIMATED] | 0.4934 |
| 16 | 0.7901 | 0.0018 | 0.0000 [ESTIMATED] | 0.7919 |
| 17 | 0.5061 | 0.0026 | 0.0000 [ESTIMATED] | 0.5087 |
