# Criteria map

For each judging criterion: the three strongest evidence items, each with a record id or a test name, then the weakest point stated
plainly and what mitigates it. Field paths are passport fields unless they start with `summary.json` (`reports/phase-d/replay/summary.json`).

## Technological Implementation

1. **The evidence chain is verifiable.** 65 [API-REPORTED] passports rebuild from the committed record blobs with zero diff, and one changed byte in any record changes its id and fails verification: `test_one_changed_byte_in_any_record_changes_its_id_and_hash_and_fails_verification`, `test_the_verifier_rebuilds_every_passport_with_zero_diff`.
2. **Nemotron and Token Factory are used in narrow, recorded roles, with a deterministic gate between the model and the code.** Model per role, calls and token usage are in `summary.json` `stack`; the adjudicator cannot upgrade a verdict (`test_adjudicator_rejects_a_model_attempted_upgrade`); a model patch refused by the gate is `attempts[3]` of `harness-v1.3.4/treatment/03@937744fe7a07e901961158d15fcb31bba204d9d214ef0ebb9624442b7fcc0544`.
3. **The cost guard stops what it cannot fund and says so, and a kill by the sandbox is named, with the sandbox's own evidence.** The operation stopped at its funded limit, with the quoted event line and the API-REPORTED / ESTIMATED split, is `harness-v1.3.4/treatment/08@cf7e86f9580bb99147920b33d6481c61f55506e979bb75ee354527a6e2610bf9`: `test_the_two_cost_cap_kills_in_v134_show_the_cap_line_crossed_at_the_recorded_second`. A kill that the evidence run traced to the sandbox's memory, ending INDETERMINATE and never BLOCKED, is `harness-v1.4.2/treatment/11@b266a0a92abce48d206fa8512843f10f9a7eb6a9a4577f6a8c21962c70feeb8e`: `test_entry_11s_kill_ends_resource_limit_with_the_limit_quoted_and_no_model_attempt`.

**Weakest point.** No gate passed. Of 24 [API-REPORTED] gate entry-runs, 2 [API-REPORTED] ended RUNS_CLEAN or RUNS_AFTER_REPAIR (`summary.json` `headline.apparent_recoveries`): one is a smoke-limit artefact, and the other, a smoke-criterion pass after model-proposed environment changes were adopted, ran for the smoke limit without failing and is one entry-run, not a rate (`summary.json` `headline.recoveries_with_applied_model_repair`). The part of the system that uses the models most did not achieve a passed gate.

**What mitigates it.** It is measured, not hidden, and it is the headline. The failures are traced to named defects (D-21, D-25, D-30 to D-43) with a status rule and the gate line behind each status. The deterministic parts work as recorded: the time machine cleared the baseline dependency error of the entry shown in the demo (`classification_chain[0]` of `harness-v1.4.2/treatment/07@4688f3c38b3f8efa48b5e3ace9f26bdc246a42e0fcf2e1fa315ca068d0fda40a`), which is not a recovery and is not presented as one.

## Design

1. **One coherent surface.** A single dashboard page carries the headline, the scorecard, the ledger, the defect register and a drill-down for every entry; every number shows its tag and links to its record: `test_every_number_on_the_page_carries_its_tag_and_links_to_a_record`.
2. **Failure is not in a footnote.** The EXPLORATORY badge is the first element of each exploratory card, above the numbers: `test_the_exploratory_badge_sits_above_the_numbers_and_is_absent_on_the_anchor`, `test_the_badge_sentence_in_the_html_equals_the_d1_text`.
3. **It works anywhere, offline.** One command builds it with nothing but Python and git, and it renders with the network blocked: `test_one_command_builds_the_page_with_the_standard_library_only`, `test_the_page_renders_fully_with_the_network_blocked`.

**Weakest point.** A static dashboard is not an interactive product. There is no filtering, no search, no way to start a run from the page, and the entry drill-down is a native disclosure element rather than an application view.

**What mitigates it.** The choice is deliberate: no script and no network means the evidence cannot change under the reader and opens from a file. The whole chain is navigable by links (number to record, record to passport, defect to passport). An interactive backend and frontend exist in the repository (`backend/`, `frontend/`) but are not what the submission demonstrates.

## Potential Impact

1. **A specific, measured answer to a real question.** "What is a reproduction patched by an LLM worth?" Here: 2 [API-REPORTED] of 24 [API-REPORTED] gate entry-runs ended RUNS_CLEAN or RUNS_AFTER_REPAIR, one an artefact and one a smoke-criterion pass, none to completion (`summary.json` `headline`), and 0 [API-REPORTED] of 16 [API-REPORTED] repositories reached RUNS_AFTER_REPAIR on the pre-registered run (`badge.figures[0]` of `harness-v1.3.2/treatment/01@fecb8efd3d440fdedb29aae428abced2e511480ac673405aa55f8a5d7f5ffaf6`).
2. **It catches a false positive that would otherwise be reported as success.** The RUNS_AFTER_REPAIR verdict of harness-v1.3.3 is kept as recorded and annotated as a smoke-limit artefact: `harness-v1.3.3/treatment/11@619a97784e6abc3f29fedf36a7c4723c65232111233a34e3299a1ed3eee034a2`, `test_entry_11_v133_shows_runs_after_repair_unchanged_with_the_artefact_annotation_beside_it`. The one of harness-v1.4.2 is annotated as a smoke-criterion verdict, not a finished run: `harness-v1.4.2/treatment/07@4688f3c38b3f8efa48b5e3ace9f26bdc246a42e0fcf2e1fa315ca068d0fda40a`.
3. **It refuses fixes that make code do less.** The tamper gate rejects a patch that deletes the evaluation call: `test_deleted_eval_call_direct_removal_is_rejected`; an abstention is recorded as INDETERMINATE instead of a guess: `test_parse_recon_response_negative_control_low_confidence_is_indeterminate`.

**Weakest point.** The evidence base is small and nobody outside the project has used it: one corpus, one repairer model, exploratory gates of a few entries each, and no study of whether a reviewer or a replication team decides differently with a passport in hand.

**What mitigates it.** The scope is stated wherever the result is stated, and the result is claimed for this harness only. The instrument is reusable as it is: a new corpus needs records, not new tooling, and the replay and dashboard rebuild from them with one command.

## Quality of the Idea

1. **Model sizes are matched to what an error costs.** The smallest model does the job where abstaining is safe, the largest only writes prose under a rule that it may only downgrade: `summary.json` `stack.versions[].roles`, `test_adjudicator_allows_a_genuine_downgrade`.
2. **Every number says how it is known.** API-REPORTED, ESTIMATED or DERIVED (BILLED for the one account-balance reading), and a derived value quotes its source line with the record id: `test_every_derived_value_carries_its_quoted_source_line_and_record_id`, `test_every_number_in_the_html_exists_in_the_replay_json`.
3. **The instrument reports on itself, including its own measurement defects.** 43 [API-REPORTED] defects with a printed status rule, where a partial fix stays open and a fix is called gated only on a quoted gate line: `test_the_defect_register_is_d1_to_d43_with_quoted_sources`, `test_at_repair_time_the_recorded_gcc_error_adds_build_essential_with_no_model_call`. The last gates' own findings about the harness are in the register: D-41 was found by one gate, confirmed by a probe and fixed and seen working in the next, and D-43 (a gate process killed by its environment) is open.

**Weakest point.** The non-obvious part is the audit, and it is built around a repair loop that did not work. The time machine was not compared with any other way of rebuilding an old environment: not measured. Search is called at runtime; the model cited a source in some gates and none in the last, and whether a citation shaped a decision is not measured (D-21).

**What mitigates it.** The audit does not depend on the repair working: it is what made the null result visible and attributable. The open questions are written down with what a validating gate must measure (`docs/design/D-25.md`, `docs/design/D-40-resources.md`), not as promises.
