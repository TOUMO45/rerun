# The actionable-diagnosis rubric (harness-v1.8, Phase 3)

**Committed before TEST-C is drawn, run or looked at.** Written 2026-10-07. The owner's requirement: "actionable diagnosis rate" is scored by a written rubric committed BEFORE TEST-C, shown **beside** the run rate, **never merged** with it; scored by a script and a written key, not by the author reading his own output.

## What is scored

Every entry of a set whose verdict is **not** `RUNS_CLEAN` / `RUNS_AFTER_REPAIR` (BLOCKED, INDETERMINATE, TIMEOUT), after the audit's strikes: a row the audit struck (a false success) is not a run and is scored as a non-running entry with the diagnosis it would have needed; the strike is stated beside the count. The denominator is the number of those entries, stated as a count (small N: counts, not percentages, with the percentage only beside them).

## The four criteria (all four must hold: ACTIONABLE)

| id | criterion | how it is tested |
|---|---|---|
| **A1** verbatim | the `error_line` the report quotes is a line of the record's **own** output (the error chain, an attempt's output, the baseline's evidence, the stop's reason), not a paraphrase | script: the whitespace-collapsed, colour-stripped line is a substring of the record's text |
| **A2** right cause | the text (`what_a_human_must_supply` + `next_action`) names the cause the **key** proves, makes none of the claims the key forbids, and the report's `fixable_by` is one the key accepts | script, against the key's `must` / `must_not` / `fixable_by` regexes. A record whose cause the key says **cannot be established from the record** is NOT actionable (`establishable: false`): a diagnosis that guesses is not credit |
| **A3** concrete next action | the text names something the evidence names (a token of the quoted line: a package, file, command, option, path) or a backticked artifact beside the action; a sentence that only repeats the class name fails | script: token overlap (4+ letters, a stop-word list) or a backticked token in `next_action` |
| **A4** anchored in the final state | the quoted line is what the run **ended on**: the last link of the error chain, the output of the last attempt that ran something, the baseline's evidence when nothing ran, or the stop's own reason; **not** a line from an earlier attempt or step the run had moved past | script (`diagnosis._Ctx.find_final`'s definition): this is the criterion that catches the defect the DEV run found (D-68: "change git:// to https://" quoted after RERUN's rewrite had made the clone work) |

**Waivers (the only two).** A `TIMEOUT` verdict has no failing line by nature: A1 and A3 are waived for it (the key says `no_output_expected`), A2 and A4 still apply. Nothing is waived for a `class_default` diagnosis: a class sentence is scored by the same four criteria as any other (`diagnosis: "class_default"` is shown beside it, so a default is never mistaken for a specific diagnosis, and a default that happens to be right scores).

**Stratification.** The count is reported per blocker **family** (`blocker.family`: Dependencies, Environment, Resources, Inputs, Data, Documentation, Code), because a rate pooled across families hides where the diagnosis is weak. The families are those of the report, not of the key.

## Procedure (what keeps the scorer from being the author grading his own text)

For **TEST-C**: (1) after the one run, and BEFORE opening any record's `blocker`, the auditor writes the key entry for each non-running record **from its raw log**: the `proof` line (a line of the record's own output that shows the cause; `score_diagnosis.py --check-key` verifies it is there), the `must` / `must_not` regexes, `fixable_by`, `establishable`. (2) The key is **committed**. (3) Only then is `score_diagnosis.py` run on it, and the output committed unedited. (4) A disagreement found afterwards is recorded as a dated correction BESIDE the original score; the key is never edited to fit a diagnosis. The 14-record key of Phase 2 (`diagnosis_key.json`) and the DEV key (`diagnosis_dev_key.json`) follow the same shape; the DEV key was written by an author who had already read the diagnoses (the DEV-CONTAMINATED records), so its score is a self-check, not a measurement.

The scorer and the rubric are committed before TEST-C. Nothing in the scorer is tuned on a TEST-C record.

## Beside it, never merged

TEST-C reports `RAN n of N` and `actionable diagnosis m of M non-running` as two figures, each with its own definition, plus the per-set medians (wall-clock time and API-reported cost to reach a diagnosis) and the recovery rate, all from committed records (`set_metrics.py`). The frozen sets (TEST, TEST-B, the out-of-sample scan) are **not** scored by this rubric: their stored diagnoses are v1.5 / v1.7.2 text and scoring them would re-score them under their old names.

## Known limits of the rubric (stated now, not discovered later)

* A3 is a lenient lexical test: it cannot tell a useful action from one that merely repeats a token. It guards against a bare class name, not against a vague sentence that happens to name the package.
* A2 depends on the key's author. The key is only as good as the auditor's reading of the log; that is why the proof line is required and checked, and why an unestablishable cause counts against the diagnosis.
* A4 is conservative: a diagnosis that quotes the last line the run showed BEFORE a deterministic step whose own run was stopped (the spend cap) can fail A4 although the sentence is honest. It is left strict.
* Small N. A rate over about ten entries has a wide interval; the report says counts, and the thresholds committed with the TEST-C registration say what would count as a success, with this stated.
