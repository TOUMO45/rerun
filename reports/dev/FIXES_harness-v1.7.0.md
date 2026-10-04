# harness-v1.7.0 — what it adds, from which records, and what reviewed it

Protocol: METHODOLOGY "harness-v1.7 — PRE-REGISTRATION" (pushed `3bba1a7` before any v1.7 live call), its dated annotation after the review, and rule G of the v1.5 protocol. **Status: release candidate in preparation. Not sealed, not run live.** The probe (`reports/corpus-v2.1/v1.7/probe/`) and the option-B seal (`reports/corpus-v2.1/v1.7/seal/`) are written and wait for the owner. Sandbox-touching files changed: `runner_hooks.py` and `runner_env.py`.

| rule | class of failure | recorded failure it replays (DEV or gate record) | covered by the class | semantics | label |
|---|---|---|---|---|---|
| R1 c `memory_hook` + memory environment | the sandbox kills the process for memory | DEV #17 round 3 (`sh ./fs_train.sh`, `Killed process 78 (python3) ... anon-rss:3864856kB`); gate #11 v1.4.2 and v1.4.3 (`anon-rss:3895992kB`) | two entries | same samples and order; random draws move to the main process's stream; IterableDataset / `worker_init_fn` loaders are left as is | `memory hook: ...` where it changed a loader |
| R1 d `resource_adapt` | the same, after (c) | gate #11 (`--batch_size`, `--test_batch_size`, defaults 256); refuses DEV #17 (a shell script) | two entries | **not preserved** | `RESOURCE-ADAPTED: ...`; waits for the swap decision |
| R1 b `swap_file` | the same | — | — | preserved | **not built**: waits for the probe |
| R2 CPU reference LU without pivoting | GPU_REQUIRED where torch has no CPU kernel | DEV #14 rounds 3 and 4 (`linalg.lu_factor: LU without pivoting is not implemented on the CPU`) | one entry | preserved (the unique no-pivot factorisation, up to rounding) | **single-case** |
| R3 `data_prep` | DATA_MISSING with a documented preparation step | DEV #9 round 4 (`AssertionError: Download cifar10 dataset!!`; `data/cifar10/generate_data.py --n_tasks 80 ...`); negative controls gate #3 v1.4.3, DEV #4 round 4 | three entries (fires on one) | the authors' own step | firing **single-case** |
| R4 `apt_archive` | APT_MIRROR_GONE (end-of-life Debian release) | DEV #16 round 4 (python:3.6-slim), DEV #9 round 3 (python:3.7-slim), both bullseye-security 404 | two entries | the same release's packages | suites provisional (main only) until the probe |
| R5 `companion_relax` | DEP_UNPINNED_CONFLICT: framework and companion pins that cannot coexist | DEV #5 round 4 (`torch==1.2.0` with `torchvision==0.5.0`, ResolutionImpossible) | one entry | torch kept; torchvision changed | `dependency change: ...`; **single-case** |
| R6 D-44 flag | a gated model patch changes what the code computes | DEV #14 round 3 (the pivoting `lu_factor` patch) | the only flagged DEV/gate RUNS_* record | reporting only | `semantic change` |

Tests (offline unless noted): `backend/tests/test_v17_memory.py`, `test_v17_memory_hook_real_torch.py` (real torch 2.14 CPU, WSL), `test_v17_cpu_reference_lu.py` (real torch + scipy, WSL), `test_v17_data_prep.py`, `test_v17_data_prep_launcher_posix.py` (WSL), `test_v17_apt_archive.py` (the step run under `sh` against a temporary root), `test_v17_companion_relax.py`, `test_v17_semantic_change.py`; the round tooling in `reports/corpus-v2.1/v1.5/`. Suites at `4c0b742`: backend 1838 passed, 19 skipped (`test_phase_d_passports.py` excluded as before); frontend 27 passed; WSL real-torch and POSIX checks 34 passed.

Other changes in this version: the ledger reader and the round report read DEV rounds under any tag (round 4 had been left out of the ledger); the round report adds the ladder, the blocker, the v1.7 firing table and the labelled counts; the TEST runner reports the confirmed count with and without RESOURCE-ADAPTED entries; the owner's $2.50 entry cap and a `--dev-total-usd`; four Phase D README tests that the v1.6 front page had left failing.

Found while building, fixed with a test: the CPU shim's and the memory hook's import finders recursed until the interpreter crashed when both were installed (re-entrancy guard); a RESOURCE_LIMIT on the last model attempt ended BLOCKED because its deferred stop never came (`may_defer`).

## Independent review (read-only subagent; it ran the offline v1.7 tests, not the real-torch ones)

Two high, six medium, seven low; all addressed in `4c0b742`, each with a test:
1. HIGH — R5 changed a dependency with no label → `dependency change` on the verdict, ladder, blocker and build plan.
2. HIGH — R1 c can change what the code computes (an unsharded IterableDataset yields once per worker; `worker_init_fn` never runs; random draws move) → such loaders are left as is; a changed loader is labelled `memory hook`; the pre-registration's "preserved" is corrected by annotation.
3. MEDIUM — data_prep's over-cap clean-up went by mtime (extracted archives keep old mtimes; a rewritten repository file was deleted) → path snapshot; only created files deleted; changed files counted, never deleted.
4. MEDIUM — the 180 s cap did not hold for a script with children → own process group, killed on the cap; per-member time checks on extraction.
5. MEDIUM — resource_adapt mislabelled an alias (`-b 512`) and re-quoted the whole command (`$DATA_DIR` became literal) → alias groups, in-place edit of the value only, abbreviations refused.
6. MEDIUM — labels missing from the Gallery → `verdict_label` on `GET /runs`, shown in the Gallery. (The round report already carried the counts in `reports/corpus-v2.1/v1.5/dev/report_round.py`; the Phase D dashboard row comes with the Phase D update.)
7. MEDIUM — the blocker claimed a deterministic fix for #14's LU, retroactively on older records → never `deterministic`; says whether the run's shim had the reference.
8. MEDIUM — resource_adapt and the R4 suites were active before the probe → resource_adapt waits for `SWAP_FILE_DECIDED`; the suites' comment says provisional.
9–15. LOW — the apt step's variables leaked (subshell); no era lock after apt_archive (documented in the annotation); a budget stop on a deferred rule could reach the model or end BLOCKED (the stop applies); `linalg.lu(pivot=False)` raised on a zero pivot (it does not check); resource_adapt on an install-phase kill (repo_run only); R5 matched any conflict pattern (needs `ResolutionImpossible`); `../data` was read as `data` (paths outside the repository refused). The list differences R3/R5/R6 versus the pre-registration text are in the annotation.

## Waiting on the owner, in order
1. A DEV total in chat (at $2.50 per entry, the HARD check refuses round 5 at $40.00: about $45.2 is needed with the probe and the seal; $50.00 recommended).
2. The probe (`launch_probe.cmd`, about $0.10 API-reported). Then: the R4 suites and R1 b from its record, `SWAP_FILE_DECIDED`, the tag `harness-v1.7.0-rc`.
3. The seal (`launch_seal.cmd`, ESTIMATED $1.29 API-reported, cap $1.50). Then `write_seal_verification_v17.py`, the tag `harness-v1.7.0`.
4. DEV round 5 (`launch_round.cmd 5 harness-v1.7.0 <DEV total>`), and a BILLED reading after each paid phase.
