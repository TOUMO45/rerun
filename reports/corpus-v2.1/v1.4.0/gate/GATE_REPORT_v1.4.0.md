# Gate v1.4.0 — NOT PASSED (attempted, did not pass)

Harness `harness-v1.4.0` (`15d3cdf`, sealed, option B). TREATMENT only, corpus-v2 entries 3, 7, 8, 11 in that order (owner's order), gate cap
$5.00, fixed entry cap $1.25, criteria (a)-(e) as pre-registered in METHODOLOGY before any v1.4.0 run. Records:
`runs/corpus_v2_batch/harness-v1.4.0/gate/`; mechanical verdict: `gate_result_harness-v1.4.0.json` (`run_gate_v140.py::evaluate_gate`).
v1.4.0 is EXPLORATORY on a disclosed development set, like v1.3.3 and v1.3.4; v1.3.2 (0/16) stays the pre-registered result. The Phase D
assets (passports, REPLAY, dashboard, submission texts) are untouched.

## Verdict per criterion

| Criterion | Result | Evidence |
|---|---|---|
| (a) >= 2 of 4 RUNS_CLEAN / RUNS_AFTER_REPAIR | **FAIL: 0 of 4** | #3 BLOCKED, #7 BLOCKED, #8 INDETERMINATE COST_CAP, #11 INDETERMINATE COST_CAP |
| (b) >= 1 source patch applied | pass: 6 applied of 11 proposed | attempts with a diff that reached a re-execution (in their own branches) |
| (c) >= 1 stored Tavily citation | **pass: 3 attempts, the first citations in any RERUN gate** | #8, repair round 2, candidates 1-3 |
| (d) no entry over $2.00, guard correct | pass | spend per entry below; cost events listed in the records |
| (e) torch at most once per environment image | **pass on all four** | #3: 1 install outside the baseline; #7: no torch; #8: 0 outside the baseline (the era fallback reused the baseline's torch layer); #11: 1 |

## Per entry (spend MEASURED unless marked)

| Entry | Verdict | Spend | What happened |
|---|---|---|---|
| #3 autumn9999/vmtl | BLOCKED RUNTIME_ERROR_OTHER | $0.6100 | Era re-execution exits 1 with no error text (as in v1.3.4). The exit-site hook fired automatically, before any model call, on the kept environment image (no reinstall, $0.049) and printed nothing: the exit does not go through sys.exit / os._exit / exit() / quit() (its recorded limit: a bare `raise SystemExit`, or a process-level exit). 3 rounds: diagnostics-only candidates ran in branches without changing the outcome; code changes were refused by the silent-exit rule (D-19). |
| #7 albertometelli/pfqi | BLOCKED RUNTIME_ERROR_OTHER | $0.8113 | numpy missing -> era env -> `pkg-config: not found`. Round 1: candidates 1 and 2 changed the outcome; the adjudicator's reply was not valid JSON, RERUN's fallback chose candidate 1 (metadata error) although candidate 2 had got further (install done, `No module named 'Box2D'`). Round 2: a candidate's run reached `unable to execute 'gcc'`; it was not adopted, so D-24 never saw it. Round 3: repeats refused, declines. |
| #8 edenton/svg | INDETERMINATE COST_CAP | $1.1422 ($0.9554 MEASURED + $0.1868 ESTIMATED) | The checkpoint fix worked as designed: the era fallback branched from the baseline's torch layer (in v1.3.4 it was killed 33 s into a second torch install) and reached the `compare_psnr` ImportError. Round 1: Ultra chose none (correctly: none of the three imports exists). Round 2: three candidates, all citing a Tavily reference; Ultra's reply was not valid JSON; the fallback adopted candidate 1 (an environment change), whose run hit `No such file or directory: 'gcc'`. D-24 added build-essential; an apt change alters the FIRST setup step, so the rebuild could not reuse the torch layer, was funded 44 s at the guard's $0.0085/s bound, and was stopped. |
| #11 JindongGu/VoteAttack | INDETERMINATE COST_CAP | $0.6309 | Baseline: tqdm missing. The era environment (python 3.9, torch 1.8.1, lock) was built completely and every layer kept, but the operation was funded 108 s (the $0.92 left at the guard's bound) and the server stopped it during the smoke run of the command itself; the run then ended COST_CAP with $0.6219 of the entry cap unspent. The GPU_REQUIRED failure was never reached, so the CPU shim never fired. |

Gate spend: $3.194323 [ESTIMATED: $3.007567 MEASURED + $0.186755 ESTIMATED] + the pre-gate upload smoke test $0.004937 [MEASURED]. Model share:
$0.254982 [MEASURED]. Every entry ran with its full $1.25 cap (no starved entry); the gate stopped at $3.19, under the $5.00 hard stop.

Kept images per entry (for bounding a storage charge, D-27 style; billing recorded as "unbilled on available evidence" until the owner's
check of the billing page): #3 8, #7 6, #8 6, #11 8 (`operations[].kept_images`, distinct ids).

## Findings (exploratory; each with its record)

1. **The cost guard's funding rule, not the install, now decides the COST_CAP endings.** Both COST_CAPs were operations funded from what was
   left at the guard's worst-case $0.0085/s. Measured on #11's killed operation: $0.2975 for 29.2 s of sandbox time but 108 s of wall time
   (the guard funds wall-clock seconds; the API bills sandbox time). With the $1.25 entry cap (v1.3.4 used $2.00) a fresh era build plus a
   60 s smoke run does not fit.
2. **A budget-limited kill still ends the entry, even when the environment survived.** #11's complete era environment was kept as an image
   and $0.62 was left; re-running the command from it would have cost a branch run (seal: $0.00054618 MEASURED on a small image,
   $0.05 on entry 7's). The D-7 rule (harness-v1.3.3: a kill at the budget limit ends the run COST_CAP) predates kept images.
3. **The adjudicator's reply was invalid JSON in 2 of the 4 adjudications it was called for** (#7 round 1, #8 round 2; one more round, #3
   round 1, had no qualifying candidate and made no call); the deterministic fallback (first qualifying candidate) picked the less advanced
   candidate on #7. The candidate adjudicator has no JSON re-ask, unlike the repairer.
4. **An apt change forces a full rebuild** (setup order: system packages, torch, the rest), as stated in the Step 1 report: #8's
   build-essential step could not reuse the torch layer.
5. **D-24 only sees the adopted failure**: a gcc error in a candidate that was not chosen (#7 round 2) never triggered the deterministic rule.
6. **The exit-site hook found no exit site on #3**: the silent exit is not a sys.exit / os._exit / exit() / quit() call.

## Ledger

$14.6495 [ESTIMATED: $13.6787 MEASURED + $0.9708 ESTIMATED], lower bound (D-27): before Step 2 $10.1349; seal $0.815528 MEASURED + at most
$0.4998 ESTIMATED; gate $3.194323 (incl. $0.186755 ESTIMATED); upload smoke $0.004937. Under the owner's ceiling of $16.84.


## Annotations (2026-10-01, v1.4.1 Step 1; the text above is unchanged)

Tags: in this report MEASURED reads API-REPORTED (D-36); DERIVED = computed here from the named records; BILLED = the owner's balance reading.

**1. The reading of the records, checked.** The owner's reading was that #8 and #11 ended by the guard's funding rule and not by exhausted budget, #7 by the
adjudicator's parse failure plus the first-candidate fallback plus D-24's scope, and #3 by an exit the hook cannot see. Against the records:
- **#11 holds.** Operation 2 was funded 108.2 s (`operations[1].funded_seconds`) from $0.92 left at the guard's $0.0085/s, built the whole era environment (4 kept
  images, 3 setup commands), was stopped as the smoke launcher was about to start (`killed_step` is the launcher, `killed_seconds` 0.0), and the entry ended with $0.6191
  of its $1.25 unspent (`cost_guard.remaining_usd`, 49.5 %).
- **#8 holds in part.** The last operation (11) was funded 44.1 s at the fixed rate from $0.3749 [DERIVED: 44.1 x 0.0085], and the guard's rule is what stopped it.
  But the budget was mostly spent by then: $1.1422 of the $1.25 cap (91.4 %), $0.1078 left at the end, after two rounds of three candidates. It is therefore not
  "not by exhausted budget": the funding rule decided the last 44 s of an entry that had used nine tenths of its cap. DERIVED: the v1.4.1 rule would have funded
  that operation 67.5 s (rolling rate $0.00555/s from the entry's eight completed operations), and with D-34 the operation would have run the apt layer and the failing
  pip step, not a second torch install.
- **#7 holds.** Round 1: Ultra's reply was not valid JSON and the fallback chose candidate 1 (package metadata error) although candidate 2 had reached
  `No module named 'Box2D'` (D-32). Round 2: a candidate's run reached `unable to execute gcc` (quoted in the adjudication's own reasoning), the adjudicator
  adopted none, D-24 never saw it (D-33). The entry ended BLOCKED with $0.8113 of $1.25 spent: it ended by using its three model attempts, not by its budget.
- **#3 holds as "an exit the hook did not see".** The record shows the hook installed automatically and printing nothing. It does not show whether the exit was a
  bare `raise SystemExit` or a process-level exit: D-35's wrapper separates the two (it prints the raise site, or the record says "exit outside Python").

**2. Kept images and billing.** Kept images per entry: #3 8, #7 6, #8 6, #11 8 (`operations[].kept_images`, distinct ids). Where this report says "unbilled on available
evidence" it now reads **no charge observed on the account balance** (the owner's reading below; the documents list no storage price, D-36).

**3. BILLED line (the gate's own).** Account balance, owner's reading at 19:37 local, 2026-10-01: $49.61 of $50.00, i.e. **at most $0.39 [BILLED] charged,
cumulative for the whole account, not per gate** (the last operation of this gate ended at 17:11 UTC, about 1 h 26 min before the reading if local time is UTC+1, as the machine reports; the time zone of the reading is an assumption, D-36). The ledger figure above,
$14.6495, is the sandbox API's reported operation cost, not account billing; the two differ by about 37x and the cause is not established (D-36, open).

**4. What the v1.4.1 funding rule would have done on this gate's operations (DERIVED, counterfactual; from each record's own completed operations and the money the
recorded guard had, no new spend).** Operations that ended the entries' COST_CAP: #11 operation 2, funded 108.2 s, would be funded 145.9 s at its $1.25 cap
(185 s at the v1.4.1 cap of $1.50; it needed about 168 s: 108.2 s to reach the smoke run plus its 60 s); #8 operation 11, funded 44.1 s, would be funded 67.5 s.
Every other operation of the four entries would have been funded more seconds than recorded (the rate is at or near the $0.0030 floor on #3 and #7, whose operations were
cheap per wall second), so the new rule starves none of them. `reports/corpus-v2.1/v1.4.1/STEP1_REPORT.md` carries the table.
