# v1.3.4 smoke gate (Step 2, second attempt): NOT PASSED (2026-09-30)

Sealed tag `harness-v1.3.4` (`10319b3`), launcher at `424e649`, TREATMENT only, entries 11, 7, 3, 8, cap $3.50. Records: `runs/corpus_v2_batch/harness-v1.3.4/smoke/`;
mechanical result: `smoke_gate_result_harness-v1.3.4.json`. Exploratory, development set. Per the operator's stop rule this is the last Nebius spend without a new decision.

## Mechanical result

| criterion | result | evidence |
|---|---|---|
| (a) at least 2 of 4 RUNS_CLEAN / RUNS_AFTER_REPAIR | **FAIL: 0 of 4** | #11 INDETERMINATE COST_CAP; #7 BLOCKED; #3 BLOCKED; #8 INDETERMINATE COST_CAP |
| (b) at least 1 source patch applied | PASS: 2 applied of 4 proposed | #11 repairs 1 and 2 applied (repair 2's re-execution was then cost-capped); #3 repair 2 applied (diagnostics only), repair 3 rejected by the new rule [Annotation 2026-10-01, Phase D1: the mechanical result lists the 2 applied patches as #11 repair 1 and #3 repair 2; #11 repair 2 has no exit code in its record (killed before a re-execution result) and the passport shows it as `gate_passed_not_executed`.] |
| (c) at least 1 Tavily citation stored | **FAIL: 0** | 9 references consulted across 3 repairs of #11/#7/#3 (all stored as `consulted`); the model gave `reason_no_citation` every time; no `content_match` [Annotation 2026-10-01, Phase D1: records show 7 attempts consulted; the figure 9 is not reproducible from records. From the 4 gate records: 0 cited, 7 attempts with `consulted` (21 references), 6 with `reason_no_citation`; #3 repair 1 (DECLINED) has none, see D-26.] |
| (d) no entry over $2, cost guard correct | PASS | $1.2825, $0.7366, $0.6990, $0.6781; the guard fired twice (#11, #8), both correctly: the operation was killed at its funded limit and the killed step's spend was recorded (#8: $0.28 estimate flagged) |

Gate spend **$3.3962** (cap $3.50). Cumulative on the new ledger: $6.738 + $3.396 = **$10.134** (ceiling ~$11).
[Annotation 2026-10-01, Phase D1: the gate spend contains the cost guard's estimate for entry 8's killed step, so it is not a single MEASURED figure: $3.396 = $3.112 MEASURED + $0.284 ESTIMATED. The same holds for the ledger line: $10.134 = $9.850 MEASURED + $0.284 ESTIMATED. Source: `cost_guard.spent_usd` and `cost_guard.estimated_sandbox_spent_usd` of the 4 gate records; see `reports/phase-d/record_index.md`.]
[Annotation 2026-10-01, Phase D: $10.134 is a lower bound (D-27). The ledger records only completed cost; the spend of a killed step is absent from it wherever the cost guard stored no estimate. Seal-verification records with a killed step and no cost for it: `runs/sandbox_verification/final-v1.3.3/kill_at_operation_limit_py310.json` (`killed_seconds` 26.7 MEASURED, `completed_cost_usd` 0.0 MEASURED), `runs/sandbox_verification/final-v1.3.4/kill_at_operation_limit_py310_extra2.json` (`killed_seconds` 26.3 MEASURED, `completed_cost_usd` 0.0 MEASURED), and `runs/sandbox_verification/attempt1-v1.3.3/kill_at_operation_limit_py310.json` (no cost field; its error line reads "the 300 s step returned without being stopped"). No dollar amount is reconstructed: no event line states one, so no DERIVED bound is shown and nothing is added to the ledger.]

## Per entry (what changed since v1.3.3)

| # | v1.3.3 | v1.3.4 | what the record shows |
|--:|---|---|---|
| 11 | RUNS_AFTER_REPAIR (`alive_at_limit`) | INDETERMINATE COST_CAP, $1.28 | the same era environment now runs PAST the point v1.3.3 called a pass: `torch.load` without `map_location` on a CPU machine (a REPO defect, GPU_REQUIRED). Repair 1 (patch, applied) added `map_location` and introduced an `UnboundLocalError` of its own; repair 2 (patch, applied) had $0.72 left, i.e. 119 s, of which the torch install takes ~90 s: killed. **v1.3.3's "recovery" was a smoke-limit artefact.** |
| 7 | BLOCKED (2 attempts wasted on the lock) | BLOCKED, $0.74 | D-18 worked: three real env repairs (SDL/freetype/pkg-config, four more SDL dev packages, then...) `add gcc` as a PIP package. One `apt build-essential` away. |
| 3 | BLOCKED (blind patches) | BLOCKED, $0.70 | D-19 worked as specified: "NO TRACEBACK FOUND" on all three attempts, one diagnostics-only patch applied (prints in the training loop, which the program never reaches), one blind `try:` patch REJECTED. The exit is a deliberate `exit 1` after a progress stream; faulthandler cannot show it. |
| 8 | INVALID_HARNESS | INDETERMINATE COST_CAP, $0.68 | never reached the patch: with $0.78 of the gate cap left the entry was funded for 55 s of re-execution, and the runner's torch install alone needs more. The D-20 overlay was NOT exercised here (it is verified live at the seal on this very repository). |

## Root causes (nothing fixed; the harness is sealed and the stop rule applies)

- **D-23 (entries 11, 8): the per-repair funding rule starves entries whose every re-execution pays a torch install.** Funding = (entry budget left) / $0.0085 per s. A torch install costs ~90 s per operation, so the third operation of a $2 entry (or any operation of an entry that inherits a small gate remainder) is killed before the repository runs. The rule is correct as a cap and wrong as a schedule: the torch layer should be cached (a snapshot image per Python minor + pin set, which METHODOLOGY explicitly declined for v1.3.2 for reproducibility reasons) or the funding should be per entry with a floor per operation.
- **D-24 (entry 7): the deterministic gcc rule only fires on the baseline classification.** `build-essential` is added automatically when the FIRST failure is a missing compiler; a missing compiler found after a repair goes to the model, which proposed `gcc` as a pip package.
- **D-25 (entry 3): one round of model-placed diagnostics does not locate a deliberate silent exit.** The rule prevented two blind patches; RERUN itself should inject the diagnostic (an `atexit`/`sys.excepthook` trace or `python -m trace --trace` for the last N calls) instead of letting the model guess where to print.
- **D-21 (still open in practice): the repairer never cites, even with a REQUIRED field.** It fills `reason_no_citation` with a sentence each time. The mechanism is complete (numbered references, required field, consulted and cited stored and hashed, `content_match` fallback); the repairer model does not use web references for these failures, and no applied change's text matched a reference snippet. This is a finding about the model, recorded as such.
- **v1.3.3 entry 11 reclassified:** the only "recovery" of the v1.3.3 gate was a program still loading at the 60 s smoke limit; run to its first real error it is a REPO defect (`torch.load` without `map_location`). The v1.3.3 report's line "1 of 4 recovered" stands as what that harness measured, with this note beside it.

## What worked live in v1.3.4 (evidence in the records)

D-18 (no attempt targeted the lock), D-19 (silent exits detected, head+tail delivered, blind patch rejected, diagnostics patch applied), D-21 mechanics (references numbered, `consulted` stored on 9 attempts, `reason_no_citation` recorded 9 times [Annotation 2026-10-01, Phase D1: records show 7 attempts consulted; the figure 9 is not reproducible from records (`consulted` on 7 attempts, `reason_no_citation` on 6).]), D-22 (no attempt lost), D-20 (verified at the seal on entry 8's repository; not reached in the gate), cost guard (two correct kills, spend recorded, no entry over $2).

## Reading

0 of 4. The model repair loop has now recovered 0 of 7 entry-attempts across two gates; every recovery-shaped result so far came from the deterministic time machine, and the one that looked like a recovery was an artefact of the smoke limit. The failures are traceable (D-23 scheduling, D-24 a missing deterministic rule, D-25 diagnostics placement, D-21 a model that does not cite), which is the write-up's content under Option 2. This is a statement about the repair loop, not about the papers.

[Annotation 2026-10-01, Phase D1: "0 of 7 entry-attempts" is restated so that it needs no arithmetic: across two gates the LLM repair loop recovered 0 of 8 entry-runs; the one apparent recovery (v1.3.3 entry 11) was a smoke-limit artefact. The model produced a recorded repair attempt in 5 of the 8. Every recovery-shaped result came from the deterministic time machine. The original sentence above is unchanged.]
