# harness-v1.9: result (2026-10-08)

Owner's goal: turn RERUN's anti-cheat claim into measured evidence, fix the four defects TEST-C exposed, settle steamctl; do not try to raise the run rate; draw no new fresh
set. TEST-A/B/C are frozen (3 of 26 ran; TEST-C 1 of 10, 7 of 9 actionable, 6 of 9 strict) and are reported as they are; nothing here re-scores them as a headline.

## What weakens the anti-cheat claim (first, as asked)

1. **The gate catches almost none of the cheat families it was not written for.** Planted-cheat benchmark, held-out half, harness-v1.9 gate: **0 of 50** cheats that end the
   program early (0 of 29), change the documented command (0 of 13) or shrink the workload (0 of 8); **3 of 23** stubbed functions; 21 of 31 swallowed exceptions; 11 of 11 skipped
   inputs (a rule added in this version). 35 of 115 overall (30%). The gate alone, not the pipeline: whether the adjudicator and the audits stop an early `sys.exit(0)` is not measured.
2. **On real runs the gate caught no fake and refused honest patches.** Of 9 fakes that reached exit 0, all 9 passed the gate and the adjudicator stopped them; of 24 gate
   rejections under a faking rule, all 24 were honest patches (23 for a file name, D-55). One adopted DEV patch (M-FAC) changed the algorithm (a different matrix), which neither
   the gate nor the adjudicator flagged at the time.
3. **The "before" planted figure was flattered by a defect:** 13 of the 37 cheats the harness-v1.8.0 gate caught were refused only for a `test_*.py` file name (D-55); by a
   semantic rule it caught 24 before and 35 after.
4. The one fix to the gate in this version came from a review that found the first draft of the new rule easy to evade; the second draft passes the review's cases but was written
   by the same author as the cheats: an independent set of cheats is still to be written.

## Task 1: ungated counterfactual (zero spend)

`reports/v1.9/counterfactual/` (rubric committed first, then `facts.json`, hand judgements, a blind second rater: 43 of 43 agree). **An ungated agent would have reported at least 6
of 26 fresh entry-runs as reproduced; RERUN certified 5 (3 after the published audits).** DEV: at least 15 of 40; RERUN certified 12. "At least": a gate-rejected patch was never
executed. Of the 13 DEV and 6 TEST-C patches that exited 0: 9 genuine fakes (all refused by the adjudicator, all passed by the gate), 5 adopted honest environment changes (latent_ode),
4 honest alternatives not chosen, 1 adopted patch outside both classes (M-FAC). Gate rejections under a faking rule: 24, all honest. Cost $0.

## Task 2: planted-cheat benchmark (zero Nebius spend)

`reports/v1.9/planted/`: 337 deterministic patches (231 cheats in six families, 106 honest controls) planted into the 7 repositories with a committed run record (latent_ode first),
corpus and seeded split committed before any gate run (dev 169 / held-out 168). Held-out, gate before (harness-v1.8.0) and after (harness-v1.9, run once):

| family | n | before | after |
|---|---|---|---|
| swallowed exception | 31 | 21 | 21 |
| stubbed function | 23 | 3 | 3 |
| skipped missing input | 11 | 7 (all by a file name) | 11 |
| early exit / hardcoded output | 29 | 2 (file name) | 0 |
| altered documented command | 13 | 2 (file name) | 0 |
| workload shrunk to nothing | 8 | 2 (file name) | 0 |
| **all cheats** | 115 | 37 | 35 |
| **honest controls rejected** | 53 | 6 (11%) | 0 |

Limits: labels by construction, patches not executed, gate alone, recon names absent. Cost $0.

## Task 3: harness-v1.9 fixes (`reports/v1.9/fixes/FIXES_harness-v1.9.0.md`)

| fix | result |
|---|---|
| a. skipped missing input (D-74) | new rule `SKIPPED_MISSING_INPUT`: held-out F3 4 of 11 passed the gate before (7 caught only by a file name), 11 of 11 caught after; dev half 9 of 9; DEV replay: refused 12 recorded img-comp-reference patches that skip an input, no adopted or honest recorded patch changed |
| b. D-55 (SCIGAN nine rejected) | the documented command's own `python test_*.py` file is exempt from the naming rule only; L2D controls 6 of 6 false rejects gone |
| c. `{tried_paths}` (D-73) | no `{field}` outside quotes in any blocker sentence: regression test over every class x 7 evidence shapes and all committed records (fails on v1.8.0: 9 failures); g-meta now names the placeholder `PATH/G-Meta_Data/arxiv/` |
| d. missing output directory (D-72) | class `OUTPUT_DIR_MISSING` + `mkdir -p -- <dir> || true` before any model call; minmaxot's recorded traceback reclassifies; **not verified live** (no paid run) |

An independent review of the diff (before the held-out re-run) found 2 high and 4 medium problems (an evadable rule, an exemption that un-protected `pytest tests/test_x.py`, a
read-under-write misclassification, shell syntax read as a data placeholder, a mkdir that could break later runs, a caption claiming more than its record); all were fixed and
tested first. No sandbox-touching file changed, so no paid seal. Held-out re-run: once (above). Cost $0.

## Task 4: steamctl (`reports/v1.9/steamctl/RESULT.md`)

3 runs at harness-v1.7.2 and 3 at harness-v1.8.0, alternating, commit `274a8db`: **v1.7.2 ran 0 of 3, v1.8.0 ran 0 of 3**. The bisect condition (v1.7.2 at least 2 of 3 and v1.8.0 0 of 3)
is not met: D-69 recorded as variance. **$1.3851 API-reported** of the $12.00 cap.

## Task 5: demo scenes

latent_ode stays the primary scene; spline-calibration is the second, shown because its committed record supports every step: **six** candidates (not seven) passed the gate and reached
exit 0 by skipping the missing logit files, none was adopted, the verdict is BLOCKED. Each scene is marked REPLAY on screen (and every certificate REPLAY or REAL); every caption claim
is computed from its record and a scene whose record lacks one is not shown. Verified in the browser at the Gallery and the certificate. The hosted demo is **not redeployed** (a deploy).

## Task 6: README and Batch Lab

Both lead with 3 of 26 ran, the diagnosis rate with its strict figure (7 of 9, 6 of 9), the counterfactual and the planted numbers, each read from committed files
(`reports/v1.9/figures.json`); wording that made repair the main result was reworded. The README guard tests were extended to accept that one generated source and the new first section.

## Cost and ledger

This pass: **$1.3851 API-reported** (steamctl) of the $25.00 ledger cap; nothing else was billed to the Nebius sandbox or the models (tasks 1, 2, 3, 5, 6 are offline). Ledger now
**$162.6946 API-reported** of the $300.00 ceiling (was $161.3095). BILLED: reading after TEST-C **$43.70** (2026-10-08 00:03 Africa/Algiers, owner; recorded); **no reading after this pass**.
The reviewer and second-rater model instances are Claude Code usage, not on the Nebius ledger.

## What was not achieved

* No paid live run of the output-directory repair, so D-72's fix is tested offline only.
* No independent set of cheats; no measurement of the whole pipeline (adjudicator + audits) against the planted cheats.
* The gate still has no rule for early exits, altered commands or shrunk workloads, and catches 3 of 23 stubs: those are findings, not fixed (no change was made in response to a held-out row).
* The hosted demo and the Devpost texts were not redeployed or refreshed.
* The M-FAC-style algorithm-changing patch has no gate rule (only the harness-v1.7 label).
