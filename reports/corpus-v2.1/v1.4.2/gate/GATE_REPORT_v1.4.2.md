# Gate v1.4.2 — NOT PASSED (attempted, did not pass)

Harness `harness-v1.4.2` (`64e5f0e`, sealed, option B over changed files only; Step 1 on `harness-v1.4.2-rc` = `22fcd6b`). TREATMENT only, corpus-v2 entries 3, 7, 8, 11 in that order, gate cap $6.00, fixed entry cap
$1.50, criteria (a)-(e) as pre-registered in METHODOLOGY before any v1.4.2 run (the runner loads the v1.4.0 criteria). Records: `runs/corpus_v2_batch/harness-v1.4.2/gate/`; mechanical verdict:
`gate_result_harness-v1.4.2.json` (`run_gate_v142.py`). v1.4.2 is EXPLORATORY on a disclosed development set, like v1.3.3, v1.3.4, v1.4.0 and v1.4.1; v1.3.2 (0/16) stays the pre-registered result.
Tags: API-REPORTED = a stored record field (the sandbox API's `resources.cost`, not account billing, D-36; the model share is DERIVED from the price table and is part of every `spent_usd`), ESTIMATED, DERIVED, BILLED.
This was the final gate: **all live work stops here** (owner), Phase D follows.

## Verdict per criterion

| Criterion | Result | Evidence |
|---|---|---|
| (a) >= 2 of 4 RUNS_CLEAN / RUNS_AFTER_REPAIR | **FAIL: 1 of 4** | #7 RUNS_AFTER_REPAIR; #3 INDETERMINATE EXIT_OUTSIDE_PYTHON; #8 INDETERMINATE COST_CAP; #11 INDETERMINATE RESOURCE_LIMIT |
| (b) >= 1 source patch applied | pass: 1 applied of 4 proposed | #8 round 1, candidate 1 (the `skimage` import) |
| (c) >= 1 stored Tavily citation | **FAIL: 0 attempts** | Tavily was searched on #7 and #8 (rounds 1-3), the repair model cited nothing in any of the 4 patches or any env change (v1.4.1: 6 cited attempts; the repairer module and its prompts are unchanged between the two tags, `git diff harness-v1.4.1 harness-v1.4.2 -- backend/app` lists 7 other files: a model-behaviour difference between two runs, not explained) |
| (d) no entry over $2.00, guard correct | pass | largest entry $1.3058; no operation was stopped, so no cost event |
| (e) torch at most once per environment image | pass on all four | #3: 1 install outside the baseline; #7: none; #8: none; #11: 1 |

## What the entries did (API-REPORTED unless marked)

| Entry | Verdict | Spend (model share) | What happened |
|---|---|---|---|
| #3 autumn9999/vmtl | INDETERMINATE `EXIT_OUTSIDE_PYTHON` | $0.5490 ($0.0035) | The era run exits 1 with a progress stream only. The exit hook, the exit wrapper and the evidence run each printed nothing; the entry ended INDETERMINATE with that reason, no model attempt (item 4 of the directive, live). **The reason is probably wrong: see "D-41" below** — every captured stderr of this entry ends mid-progress-bar at `17.8%`, where the sandbox SDK's 64 KiB output cap would cut it. |
| #7 albertometelli/pfqi | **RUNS_AFTER_REPAIR** | $1.1809 ($0.0713) | Round 1: no candidate moved the exit outcome (`pkg-config: not found` stayed). **Round 2: Ultra said none; RERUN adopted candidate 2 for partial progress (D-37, live):** its run got past the install step to `No module named 'Box2D'`, which no other candidate reached. Round 3 started from that candidate's image: Ultra chose candidate 1 (`Box2D==2.3.10` by pip) and its run was still alive and printing training iterations at the 60 s smoke limit. **This is "the command ran 60 s without failing", not "finished" and not "results reproduced".** No source patch, an environment change; candidate 3 also exited 0, candidate 2 exited 100. v1.4.1 ended BLOCKED on the same entry. One run: the attribution of the difference to D-37 is a reading of the records (round 2 would have been a dead end without the adoption), not a controlled comparison. |
| #8 edenton/svg | INDETERMINATE `COST_CAP` | $1.3058 ($0.0491) | The era run no longer dies at a CUDA call: it reaches the repository's own code and fails on `compare_psnr` (an `skimage` API move). Round 1: Ultra's reply was invalid JSON once and **the re-ask worked (D-32, live)**; it chose candidate 1 (import from `skimage.metrics`), whose run still failed (`compare_psnr` is not in `skimage.metrics` either). Candidate 3 had the D-33/D-34/D-35 rules fire on its branch (build-essential, exit hook, exit wrapper: $0.5079 together). Round 2 could not start: at the $1.50 entry cap $0.20 funded 29 s against a 30 s minimum. **The D-39 shim extension was not exercised: no GPU error occurred on this entry.** |
| #11 JindongGu/VoteAttack | INDETERMINATE `RESOURCE_LIMIT` | $0.8994 ($0.0042) | The CPU shim fired on the era run's recorded GPU error (`cuda.is_available`, `torch.load`) and cleared it; the run then trained (`1/40`) and was killed: exit 137, `Killed`. **One evidence run on the same environment read the sandbox itself: `MemTotal` 4,034,744 kB (3.85 GiB), 4 CPUs, no swap, and the kernel log `Out of memory: Killed process 76 (python) total-vm:5026056kB, anon-rss:3895992kB`.** So #11's process held about 3.9 GB, the whole VM, and the kernel OOM-killer ended it: a sandbox memory limit, not a property of the repository's code that RERUN can fix (it needs a bigger instance, which is not documented: D-40-resources.md). Ended INDETERMINATE, no model attempt, no BLOCKED. |

Gate spend: **$3.9350** = $3.8070 sandbox API-reported + $0.1280 model (DERIVED, price table); estimated part $0.0000 (nothing was stopped). Pre-batch upload smoke tests: both passed first time, $0.0051197 together
($0.000795 for 10 KB and $0.004325 for 124 MB at 2.29 MB/s). Entry caps: every entry ran with the $1.50 cap; #8 reached 87 % of it and ended COST_CAP, the others 37 % to 79 %. The gate stopped at $3.94, under the
$6.00 hard stop. Kept images per entry (distinct ids, `operations[].kept_images`): #3 8, #7 9, #8 7, #11 9 (no charge observed on the account balance so far).
**BILLED: not yet.** The owner reads the account balance after the gate; the ledger is the API-reported cost, not billing (D-36).

## Against the earlier gates (same entries, same criteria)

| | v1.4.0 | v1.4.1 | v1.4.2 |
|---|---|---|---|
| (a) | 0 of 4 | 0 of 4 | **1 of 4** |
| #3 | BLOCKED (silent exit) | BLOCKED (exit outside Python) | INDETERMINATE EXIT_OUTSIDE_PYTHON |
| #7 | BLOCKED | BLOCKED SYS_LIB_MISSING | **RUNS_AFTER_REPAIR** |
| #8 | COST_CAP | BLOCKED GPU_REQUIRED | COST_CAP at the $1.50 cap, past the GPU error |
| #11 | COST_CAP | BLOCKED (killed, 137) | INDETERMINATE RESOURCE_LIMIT (OOM evidenced) |
| (c) | pass (first citation) | pass (6) | **fail (0)** |
| gate spend (entries) | $3.1943 | $3.5247 | $3.9350 |

## D-41 (new, found by this gate, NOT fixed, not yet proven): the sandbox SDK truncates stdout and stderr at 65,535 bytes and `sandbox.py` never looks

- **The documented fact** (`contree_sdk/config.py`, installed version 0.3.6): `default_truncate_output_at: int = 65535` ("Default truncate output at which to truncate stdout and stderr"); the run's result carries `.truncated`
  ("Whether stdout or stderr was truncated by the output size limit"). `sandbox.py` passes no `truncate_output_at` and never reads `.truncated` (no hit for either word in `sandbox.py` or `orchestrator.py`).
- **What it would do:** keep the first 64 KiB of each stream and drop the rest. Everything the harness appends or relies on at the END of a stream is lost on a run that prints more: a Python traceback (the classifier reads stderr), the exit hook's
  stack, the exit wrapper's traceback, the evidence block, `RERUN_SMOKE_*` markers written after the child's output.
- **Why entry #3 looks like it** (the strong indication, not a proof): in all four stored stderr tails of this entry (baseline, hook run, wrapper run, evidence run) the last line is `\r17.8%` in the middle of a progress stream (about 67 writes of 6 bytes per
  0.1 %), which projects to about 72 KB of stderr at that point; the hook, the wrapper and the evidence block, each written after the program ends, are all missing. The same entry in v1.4.1 (hook and wrapper printed nothing) and v1.3.x ("NO TRACEBACK FOUND") shows the same shape.
  If the cap is the cause, "silent exit" for #3 in every version was a real error message that was cut off, and `EXIT_OUTSIDE_PYTHON` here is an artefact of the harness, not a property of the repository.
- **What it does not touch:** #11's kill (its stderr ends in `Killed`, inside the cap) and the seal's evidence checks (small outputs). #8 and #7 print less.
- **What would settle it:** the stored records do not keep `.truncated` (nothing stored it). One live probe of about $0.002 (a script that writes 100 KB to stderr, then a marker line, then exits) shows what the API returns. **Not run: all live work stopped when the gate ended.**
- **The fix would be small and would touch the sealed code:** pass a large `truncate_output_at` (the SDK takes it per run) or write the child's streams to files and read their ends, and store `.truncated` on every operation. `sandbox.py` is listed by almost every seal entry, so under option B a re-seal
  costs about $0.8 to $1.2 (ESTIMATED from the v1.4.1 and v1.4.2 seals), and a new gate $3.5 to $6.00: more than the room left under the $25.00 ceiling (**$2.5065**). That is the owner's decision (raise the ceiling, or document D-41 as open).

## Findings and decisions

1. D-37 partial progress worked as designed on #7 round 2 (the live record shows the adoption and its reasons); D-32's re-ask worked on #8 round 1.
2. D-38 / D-40: #11 is a MEMORY kill, evidenced from inside the sandbox (OOM-killer line, 3.85 GiB VM). The seal's allocation probe and the gate's evidence run agree (one VM size, 4,034,744 kB). **That an entry needs more memory than a sandbox VM has is now a recorded finding, not a guess.**
3. D-39 was not exercised live (no `.cuda()`/`.to`/`torch.device` call was reached; #11 used `cuda.is_available` and `torch.load` only). It stays fixed-unvalidated; its real-torch check is offline (STEP1_REPORT section 5).
4. Criterion (c) failed on model behaviour, not on harness behaviour: the same Tavily results were offered and the repair model offered no citation (`reason_no_citation` is recorded on the patches that were proposed).
5. The `EXIT_OUTSIDE_PYTHON` reason code from item 4 of the directive did what it was built to do (ended INDETERMINATE, no model attempt, evidence run attempted) and D-41 shows its premise ("the wrapper would have printed the raise") can fail silently when the stream is cut.
6. The headline is unchanged in kind and changes in count: over the four gate entries of this version, 1 of 4 reached RUNS_AFTER_REPAIR under a 60 s smoke criterion; Phase D recomputes the program headline over all gate entry-runs of all versions.

## Ledger

Gate $3.9350 + smoke $0.0051 = $3.9401. Ledger: **$22.4935** [ESTIMATED: $21.3218 API-REPORTED + $1.1717 ESTIMATED], a lower bound (D-27); ceiling $25.00; room left **$2.5065**.
