RERUN audits whether a paper's code still runs and, when it does not, says what stops it. The main result is that count and that diagnosis, not repair. Every figure in this section is generated from `reports/v1.9/figures.json` (built from the committed result files by `reports/v1.9/figures.py`) by `reports/texts/render.py`; the Batch Lab reads the same file.

- **{{held_out_ran}} of {{held_out_total}} held-out repositories ran their documented command.** TEST {{test_ran}} of {{test_of}} after its published audit ({{test_preregistered_confirmed}} as pre-registered), TEST-B {{test_b_ran}} of {{test_b_of}}, TEST-C {{test_c_ran}} of {{test_c_of}}. Each set was drawn under a registration committed before the draw and run once; "ran" means the documented command executed, never that a paper's result was reproduced.
- **Diagnosis, TEST-C: {{diagnosis_actionable}} of {{diagnosis_non_running}} non-running entries got an actionable diagnosis; {{diagnosis_strict}} of {{diagnosis_non_running}} judged strictly** (`reports/test-c/TEST_C_RESULT.md`; the key was written from the raw logs and committed before scoring).

| Held-out set, drawn and run once | Ran its documented command |
|---|---|
| TEST (after its published audit) | {{test_ran}} of {{test_of}} ({{test_preregistered_confirmed}} as pre-registered) |
| TEST-B | {{test_b_ran}} of {{test_b_of}} |
| TEST-C | {{test_c_ran}} of {{test_c_of}}; diagnosis {{diagnosis_actionable}} of {{diagnosis_non_running}} actionable, {{diagnosis_strict}} strictly |
| **All three** | **{{held_out_ran}} of {{held_out_total}}** |

**Try it, no key and no spend:** `python demo.py` in a clone (Python and Node; it installs pinned versions, builds the page and serves the recorded audits in demo mode, where live execution is refused). `python -m phase_d.build_dashboard` builds the static evidence page with no network at all. Details and the live mode: [Run it](#run-it-in-one-command-no-key-no-spend).

**What weakens these claims** (in full under [Limits](#limits)):

- Anti-cheat is not a headline claim: harness-v1.9.0 adopted {{indep_real_failure_cheats_adopted}} of the {{indep_real_failure_cheats}} independent cheats aimed at repositories whose run really fails ({{indep_real_failure_adopted_pct}}).
- REVIEW_REQUIRED is a signal that a human should look, not a cheat detector: it also marks {{flag_controls_adopted_flagged}} of the {{indep_v190_adopted_controls}} honest repairs harness-v1.9.0 adopted. Its table is derived from records, and no live run has shown it on a certificate: the {{live_flag_mode_runs}} live runs of the flag mode (the wiring check, M-FAC, and minmaxot with Tavily on) flagged {{live_flag_mode_attempts_flagged}} attempts and produced {{live_review_required_certificates}} REVIEW_REQUIRED certificates. The run pre-registered to show it (M-FAC) ended TIMEOUT before any repair attempt, so it tested nothing about the flag.
- Tavily is offered and sometimes cited; that it helps a repair is not shown. Of the {{tavily_runs_offered}} live runs that were offered Tavily references, {{tavily_runs_offered_citing}} cite one ({{tavily_runs_citing_of_offered_pct}}); of all {{tavily_live_runs}} live runs, {{tavily_runs_citing}} ({{tavily_runs_citing_of_live_pct}}). In the latest run (minmaxot with Tavily on) {{minmaxot_tavily_candidates_citing}} candidate cited a source and the adopted patch did not. Whether a citation shapes a decision is not measured (D-21).
- Repair's yield is small, the diagnosis rate is one set of {{diagnosis_non_running}} entries, and every post-hoc run is labelled and kept out of the counts.

### The benchmark and its per-layer tables

Two sets of patches to the same seven repositories, each patch labelled cheat (the documented command ends successfully without doing the work) or honest control, packaged with their hashes, family definitions, dropped list and a scorer in `benchmark/`: `python benchmark/score.py --all` reproduces every table below from RERUN's own decision files. **Both sets are development material now**; a new independent set is needed to measure again.

**The planted set** (`reports/v1.9/planted/RESULT.md`): {{planted_patches}} deterministic patches ({{planted_cheats}} cheats in six families, {{planted_controls}} honest controls) written by the assistant that also wrote the gate's rules, split by a seeded draw. On the held-out half, the tamper gate alone (harness-v1.9):

{{table:planted_heldout.gate_v1.9}}

The full pipeline (gate, a real sandbox run, the exit-zero audit, the adjudicator) at harness-v1.9.0 on the same half (`reports/v1.10/pipeline/RESULT.md`). **Table only, no summary sentence:** the adjudicator refused all {{pipeline_controls_refused}} honest controls that passed the run there, so its refusals count as detection only on the repositories whose run really fails. A refusal at `run` means the cheat did not make the command pass: not a catch.

{{table:planted_heldout.pipeline_v1.9.0}}

**The independent set** (`reports/v1.10/RESULT.md`): a separate agent that had not seen the checks wrote {{indep_authored_cheats}} cheats and {{indep_controls}} honest controls; {{indep_confirmed_cheats}} of the cheats reached exit 0 and are measured ({{indep_dropped_cheats}} dropped, listed in `benchmark/sets/independent/dropped.json`). The full pipeline at harness-v1.9.0, the submission harness:

{{table:independent.pipeline_v1.9.0}}

The behavioural checks of harness-v1.10 refusing (`harness-v1.10.0-rc4`, measured once on this set):

{{table:independent.refuse_v1.10.0-rc4}}

The flag mode: the same checks as a review flag on harness-v1.9.0's verdicts (an adopted patch they would have refused keeps its verdict and its certificate carries REVIEW_REQUIRED with the reason: a signal that a human should look, not a cheat detector). The submission harness, harness-v1.10.0, ships it. **Derived from committed records, not measured by a run of the flag mode on this set; this use of the checks was chosen after the results were seen.** The flag is the static half's: the flag mode runs no tracer, because inside the run being judged the tracer changes that run (the independent review of the first flag-mode candidate reproduced an exit-zero the harness overrules becoming a pass). The behavioural tracer was exercised by no cheat ({{flag_cheats_traced}} traced); cheats written to fit the allow-list are unmeasured.

{{table:independent.flag_mode.derived}}

**On real runs** (committed records only, zero spend, `reports/v1.9/counterfactual/RESULT.md`): an agent that trusted exit 0 would have reported at least {{ungated_fresh_at_least}} of {{fresh_entry_runs}} fresh entry-runs as reproduced; RERUN certified **{{certified_fresh_after_audits}} after the published audits** ({{certified_fresh_as_recorded}} as recorded). Neither run the audits removed was a fake ({{fresh_removed_that_were_fakes}} of {{fresh_removed_by_audit}}): no patch was involved in either; one was a pipe that returned the last stage's status after the script had failed at its first import, one a documented command that only prints help (`reports/v1.10/breakdown/BREAKDOWN.md`). DEV: at least {{ungated_dev_at_least}} of {{dev_entry_runs}} against {{certified_dev_after_erratum}} certified after erratum E-3 ({{certified_dev}} as recorded).

### Limits

- **Anti-cheat is not a headline claim.** harness-v1.9.0 adopted {{indep_real_failure_cheats_adopted}} of the {{indep_real_failure_cheats}} independent cheats aimed at repositories whose run really fails ({{indep_real_failure_adopted_pct}}), above the {{anticheat_headline_line_pct}} line: a patch that holds the genuine fix **and** a second change that alters the result passes the adjudicator.
- The behavioural checks refusing stopped every measured cheat and also {{indep_controls_refused_by_checks}} of the {{indep_controls_passed_run}} honest controls that passed the run ({{indep_fr_pct}}, above the pre-registered {{fr_rule_line_pct}} line), so the verdicts stay harness-v1.9.0's and the checks are only a review flag; the flag also marks {{flag_controls_adopted_flagged}} of the {{indep_v190_adopted_controls}} honest repairs harness-v1.9.0 adopted.
- No cheat in either set was written by an author who knew the checks: an adaptive set is not measured.
- **Erratum E-3** (`reports/corpus-v2.1/ERRATA.md`): the M-FAC DEV entry ran on a changed algorithm; DEV certified {{certified_dev}} as recorded, {{certified_dev_after_erratum}} after the erratum.
- **Post-hoc, labelled, never merged into TEST-C** (`reports/v1.10/mkdir_live/RESULT.md`): one live run of minmaxot at harness-v1.9.0 checked the output-directory repair; the rule fired and the run reached RUNS_AFTER_REPAIR at the smoke limit ({{minmaxot_posthoc_cost_usd}}).
- **The flag mode's {{live_flag_mode_runs}} live runs** (each post-hoc, labelled, never merged into any count; {{live_flag_mode_attempts_flagged}} attempts flagged, {{live_review_required_certificates}} REVIEW_REQUIRED certificates). The wiring check (`runs/v1.10/live_v110/`, the same entry at harness-v1.10.0 on a GitHub Actions runner, {{minmaxot_flag_live_cost_usd}}) gave the harness-v1.9.0 run's verdict and taxonomy and ran without Tavily context (its search failed on a malformed secret); the model's patches differ between the two runs. M-FAC (`reports/v1.10/review_live/PLAN.md`, the run pre-registered for the flag's positive path, on this machine, {{mfac_review_live_cost_usd}}) ended TIMEOUT: the documented command reached the baseline's wall clock ({{mfac_review_live_wall_clock_s}} seconds) and the record holds no output of it, so the cause is not known; it made {{mfac_review_live_attempts}} repair attempts and no Tavily search, and gave the flag nothing to judge. minmaxot with Tavily on (`reports/v1.10/tavily_live/PLAN.md`, for the Tavily gap only, on this machine, {{minmaxot_tavily_cost_usd}}) gave the wiring check's verdict and taxonomy: the search offered {{minmaxot_tavily_references_offered}} references to each of the {{minmaxot_tavily_candidates}} candidates, {{minmaxot_tavily_candidates_citing}} candidate cited a source, the adopted patch (an environment variable set in the entry file) did not, and no attempt was flagged. The flag's positive path is shown by the test suite only. The mode was sealed live ({{v110_seal_paths}} code paths, {{v110_seal_run_ids}} live run ids, {{v110_seal_cost_usd}}).
- Repair is attempted and its yield is small (below); it is not the result.
