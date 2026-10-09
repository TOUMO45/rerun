# Devpost project description and tagline

Generated from `reports/v1.9/figures.json` by `reports/texts/render.py` (template: `reports/texts/templates/description.md`): every number is a figure of that file and carries its tag.

## Tagline

RERUN audits whether a paper's code still runs, in a Nebius Token Factory sandbox, and says what stops it when it does not: {{held_out_ran}} of {{held_out_total}} held-out repositories ran their documented command, and {{diagnosis_actionable}} of the {{diagnosis_non_running}} that did not on TEST-C got an actionable diagnosis. Every number traces to a committed record.

## Description

**The problem.** Research code rots; the tempting fix is to let an LLM patch it until it runs. A patched run that "works" may have swallowed the error, faked the data or changed the computation.

**What RERUN does.** It runs a repository's documented command at its pinned commit in a Nebius Token Factory sandbox, rebuilds the paper's era deterministically, classifies what stopped it and says who can remove it. NVIDIA Nemotron models work in narrow roles: Nano finds the entrypoint or abstains, Super proposes repairs, Ultra chooses between candidates and may only downgrade a verdict. A deterministic tamper gate vets every proposal, a cost guard stops what it cannot fund, and each run becomes a hashed passport anyone can verify offline.

**What we measured.** Three held-out sets, each registered before its draw and run once: {{held_out_ran}} of {{held_out_total}} repositories ran their documented command (TEST {{test_ran}} of {{test_of}} after its published audit, TEST-B {{test_b_ran}} of {{test_b_of}}, TEST-C {{test_c_ran}} of {{test_c_of}}); ran, never reproduced. On TEST-C, {{diagnosis_actionable}} of {{diagnosis_non_running}} non-running entries got an actionable diagnosis ({{diagnosis_strict}} judged strictly).

**The benchmark.** Two cheat sets ship in `benchmark/` with hashes and a scorer that reproduces every published table: {{planted_patches}} planted patches, and {{indep_authored_cheats}} cheats with {{indep_controls}} honest controls by a separate agent that had not seen the checks ({{indep_confirmed_cheats}} cheats measured). On the planted held-out half the full pipeline adopted {{pipeline_cheats_adopted}} cheats but refused all {{pipeline_controls_refused}} honest controls that passed the run, so that table has no summary sentence.

**Limits.** Repair's yield is small: {{gate_apparent_recoveries}} of {{gate_entry_runs}} exploratory gate entry-runs reached a RUNS_* verdict. Anti-cheat is not a headline claim: the shipped harness adopted {{indep_real_failure_cheats_adopted}} of the {{indep_real_failure_cheats}} independent cheats aimed at repositories whose run really fails ({{indep_real_failure_adopted_pct}}). Behavioural checks that refuse such patches also refused {{indep_controls_refused_by_checks}} of {{indep_controls_passed_run}} honest controls, so they ship as a review flag (REVIEW_REQUIRED, the verdict unchanged); its figures are derived from committed records, the use was chosen after the results were seen, no cheat was run with the tracer, and cheats written to fit the checks are unmeasured. Erratum E-3 and one post-hoc run are reported under their labels.

**Why that is the product.** Every number traces to its record. The ledger, {{ledger_usd}} of the owner's {{ledger_ceiling_usd}}, is the sandbox API's reported operation cost, a lower bound; the account balance showed at most {{billed_second_reading_charged_usd}} charged at the owner's second reading, not reconciled (D-36, open).
