# Gate v1.4.1 — NOT PASSED (attempted, did not pass)

Harness `harness-v1.4.1` (`5ba14a2`, sealed, option B over changed files only). TREATMENT only, corpus-v2 entries 3, 7, 8, 11 in that order, gate cap $6.00, fixed entry cap $1.50, criteria (a)-(e)
as pre-registered in METHODOLOGY before any v1.4.1 run (the runner loads the v1.4.0 criteria). Records: `runs/corpus_v2_batch/harness-v1.4.1/gate/`; mechanical verdict:
`gate_result_harness-v1.4.1.json` (`run_gate_v141.py::evaluate_gate`). v1.4.1 is EXPLORATORY on a disclosed development set, like v1.3.3, v1.3.4 and v1.4.0; v1.3.2 (0/16) stays the
pre-registered result. Tags: API-REPORTED = a stored record field (the sandbox API's `resources.cost`, not account billing, D-36; the model share is DERIVED from the price table and is part of
every `spent_usd`), ESTIMATED, DERIVED, BILLED.

## Verdict per criterion

| Criterion | Result | Evidence |
|---|---|---|
| (a) >= 2 of 4 RUNS_CLEAN / RUNS_AFTER_REPAIR | **FAIL: 0 of 4** | #3 BLOCKED RUNTIME_ERROR_OTHER, #7 BLOCKED SYS_LIB_MISSING, #8 BLOCKED GPU_REQUIRED, #11 BLOCKED RUNTIME_ERROR_OTHER |
| (b) >= 1 source patch applied | pass: 8 applied of 26 proposed | all 8 on #8 (rounds 1-3, in their own branches) |
| (c) >= 1 stored Tavily citation | pass: 6 attempts | #7 rounds 1 and 2; #8 round 2 (three candidates) and round 3 |
| (d) no entry over $2.00, guard correct | pass | largest entry $1.1140; no operation was stopped, so no cost event |
| (e) torch at most once per environment image | pass on all four | #3: 1 install outside the baseline; #7: none; #8: none; #11: 1 |

## What the entries did (API-REPORTED unless marked)

| Entry | Verdict | Spend (model share) | What happened |
|---|---|---|---|
| #3 autumn9999/vmtl | BLOCKED RUNTIME_ERROR_OTHER | $0.6229 ($0.1166) | Era re-execution exits 1, progress bars only. The exit hook was installed automatically and printed nothing; the exit wrapper then ran the entry script and printed nothing either: the record says **"exit outside Python"** (`time_machine_action.result`). Of the 9 model candidates (3 rounds), 8 were refused by the gates (BLIND_PATCH_ON_SILENT_EXIT, DIFF_TOO_LARGE, UNPARSEABLE_PATCH) and 1 declined: no patch ran. |
| #7 albertometelli/pfqi | BLOCKED SYS_LIB_MISSING | $0.7220 ($0.0703) | The original `pkg-config: not found` stayed the last error. Every round had one qualifying candidate that moved the failure on (pygame pinned, then `No module named 'Box2D'`; apt packages, then pygame's missing-library list) and the adjudicator chose none each time because the run still failed. Round 3's first adjudicator reply was prose: the one re-ask produced valid JSON and both replies are stored (`reasked: true`). Two attempts stored Tavily citations. |
| #8 edenton/svg | BLOCKED GPU_REQUIRED | $1.0658 ($0.0560) | The adjudicator adopted a candidate in all three rounds: round 1 candidate 2 (the `skimage` import), round 2 candidate 1 (the failure moved to `_pickle.UnpicklingError`), round 3 candidate 1 (`weights_only=False`), whose run then hit `torch.load` on a CUDA tensor: the CPU shim handled that **inside that candidate's branch** (D-33, `time_machine_action` `cpu_shim`, `on_candidate` 1). The run then reached an explicit `.cuda()` (`AssertionError: Torch not compiled with CUDA enabled`) and the three model attempts were used up. No torch install after the baseline; no operation stopped. |
| #11 JindongGu/VoteAttack | BLOCKED RUNTIME_ERROR_OTHER | $1.1140 ($0.1197) | The CPU shim fired on the era run's recorded GPU error and **cleared it** (v1.4.0 never reached it: its era operation was stopped first). The era run then loads CIFAR-10, enters the training loop and is **killed at iteration 1 of 40** (`1/40 [00:01<00:53, 1.37s/it]Killed`, exit 137). The hook and the wrapper both printed nothing ("exit outside Python": a signal, not a SystemExit); all 9 candidates were refused by the silent-exit rule. |

Gate spend: **$3.5247** = $3.1622 sandbox API-reported + $0.3625 model (DERIVED, price table); estimated part $0.0000 (nothing was stopped). Pre-batch upload smoke tests: the failed first attempt
$0.0007892 (its 124 MB upload timed out, no operation completed, so no cost is recorded: D-27) and the passing one $0.0052415, plus a diagnostic 10 MB upload $0.0017281 to measure the link
(`upload_probe_10mb_20261001T200229Z.json`): $0.0077588 together. Entry caps: every entry ran with its full $1.50 cap; none got near it (largest 74 %); the gate stopped at $3.52, under the $6.00 hard stop.
Kept images per entry (distinct ids, `operations[].kept_images`): #3 8, #7 6, #8 10, #11 10 (no charge observed on the account balance so far).

**The pre-batch upload smoke test failed once.** At the first attempt its 124 MB upload timed out four times (760 s; the link measured 0.16 MB/s, below the 0.44 MB/s the transport timeout assumes) and the gate
refused to start: no entry ran. The second attempt, after a 10 MB probe showed 0.71 MB/s, passed (141 s of upload against a 155.6 s timeout: 14 s of margin, as in the v1.4.0 gate's 140 s). The check is
sensitive to the line's bandwidth, not to the harness. Both smoke records are kept.

## Against harness-v1.4.0 (same entries, same criteria)

| | v1.4.0 | v1.4.1 |
|---|---|---|
| Entries ending COST_CAP | 2 of 4 (#8, #11) | **0 of 4** |
| Entries BLOCKED | 2 (#3, #7) | 4 |
| Operations stopped at their funded limit | 2 (#8 op 11, #11 op 2) | 0 of 28 compute operations |
| (b) patches applied | 6 of 11 | 8 of 26 |
| (c) stored citations | 3 attempts | 6 attempts |
| Spend per entry (#3 / #7 / #8 / #11) | $0.6100 / $0.8113 / $1.1422 / $0.6309 | $0.6229 / $0.7220 / $1.0658 / $1.1140 |

The six fixes, as seen live: **D-30** funded every operation between $0.0030 and $0.0052 per wall second (recorded on each) and never starved one (100 to 499 s funded). **D-31** was not exercised (no operation
was stopped); it rests on seal checks K1/K2 on the real service and on its unit tests. **D-32** re-asked live once (#7 round 3). **D-33** fired live once, adopted (#8 round 3, the CPU shim on the candidate's own failure); the main-flow CPU shim fired once (#11, before any model call). **D-34**'s apt layer was not needed (no compiler error occurred; #7's era operation failed in its first setup step, so only the tree layer was kept and the apt candidates' packages joined the first apt step, as designed: operation 8 shows `start_setup_commands` 0 and the apt step first). **D-35** fired twice (#3, #11) and both times reported "exit outside Python": in #11 the cause is visible (`Killed`, exit 137); in #3 (exit 1 with only progress output) it is not established.

## Findings (exploratory; each with its record)

1. **The adjudicator adopts nothing unless the run passes** (#7, all three rounds; the same pattern in v1.4.0 #7 round 2). Its instruction is to choose null if no candidate is acceptable and to prefer the
   one that fixes the failure; every round's single qualifying candidate had moved the failure to a later stage (pkg-config -> Box2D) and was refused for that reason, so an entry could not accumulate progress and
   ended on its original error. Proposed D-37 (not fixed; the harness is sealed).
2. **A kill by signal is classified as a silent exit** (#11: `Killed`, exit 137 after iteration 1 of 40, reported RUNTIME_ERROR_OTHER). No code patch can be justified by it, and the silent-exit rule correctly refused all
   9 candidates, but the harness neither names it (a resource kill, probably the sandbox's memory limit; not established: the records do not store `consumed_memory`, a field the API returns) nor stops asking the model. Proposed D-38.
3. **The CPU shim does not cover an explicit `.cuda()`** (#8: `Torch not compiled with CUDA enabled` after `torch.load` and `is_available` were handled). Proposed D-39.
4. **#3's silent exit is still unexplained**: exit 1, only a progress stream, hook and wrapper silent. The wrapper separates it from a Python SystemExit; it does not say what it is.
5. **The first-attempt smoke refusal** (above): the pre-batch check needs about 0.85 MB/s to pass at its 155.6 s timeout.

## Ledger

**$18.5083** [ESTIMATED: $17.3366 API-reported (including model $ from the price table) + $1.1717 ESTIMATED], a lower bound (D-27): before Step 2 $14.6495; seal $0.326329 ($0.125435 API-reported +
$0.200893 ESTIMATED); gate $3.524718; smoke tests and the link probe $0.0077588. Under the owner's ceiling of $25.00 (headroom $6.4917).

**BILLED line (this gate's own).** The owner reads the account balance after the gate; the figure is not known yet and this report states none. The only reading on record is the account-level one from before
this step: at most $0.39 [BILLED] cumulative at 19:37 local on 2026-10-01 (before the v1.4.1 seal and gate). Ledger figures are the sandbox API's reported cost, not account billing (D-36, open).

## Annotation: BILLED line for this gate (owner's reading, 2026-10-01; the text above is unchanged)

Account balance after the seal and the gate (a screenshot of the Nebius console, organisation "Louay-ag4", time of day not stated; the table rows visible beside it are dated 2026-10-01 21:xx):
**$49.57 [BILLED]**. The earlier reading was $49.61 at 19:37 local, before the v1.4.1 seal and gate. So, for the whole account:
- cumulative charged: **at most $0.43 [BILLED]** ($50.00 - $49.57), against a ledger of $18.5083 API-reported (a factor of about 43);
- charged between the two readings, which span this seal, this gate, the smoke tests and the link probe: **$0.04 [BILLED]** (rounded to cents: $0.03 to $0.05), against **$3.8588 [API-REPORTED + ESTIMATED]** the ledger
  recorded for the same work (a factor of about 96) [DERIVED: $18.5083 - $14.6495];
- the model share of that work alone is $0.3625 [DERIVED from the price table] (gate records; the seal made no model call), more than the whole $0.04 charged.
So the charged amount is below even the price-table value of the model tokens, which D-36's reading as "sandboxes are free in beta and the balance is the model tokens" would have to explain by a billing lag, a different
model price or a credit that the balance page does not show. Not established; D-36 stays open (`docs/design/D-36.md`, section "Second reading"). Ledger figures remain the sandbox API's reported cost, not account billing.
