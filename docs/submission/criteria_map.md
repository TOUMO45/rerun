# Criteria map

For each judging criterion: the three strongest evidence items, each with a record id or a test name, then the weakest point stated
plainly and what mitigates it. Field paths are passport fields unless they start with `summary.json` (`reports/phase-d/replay/summary.json`).

## Technological Implementation

1. **The evidence chain is verifiable.** 49 [MEASURED] passports rebuild from the committed record blobs with zero diff, and one changed byte in any record changes its id and fails verification: `test_one_changed_byte_in_any_record_changes_its_id_and_hash_and_fails_verification`, `test_the_verifier_rebuilds_every_passport_with_zero_diff`.
2. **Nemotron and Token Factory are used in narrow, recorded roles, with a deterministic gate between the model and the code.** Model per role, calls and token usage are in `summary.json` `stack`; the adjudicator cannot upgrade a verdict (`test_adjudicator_rejects_a_model_attempted_upgrade`); a model patch refused by the gate is `attempts[3]` of `harness-v1.3.4/treatment/03@937744fe7a07e901961158d15fcb31bba204d9d214ef0ebb9624442b7fcc0544`.
3. **The cost guard stops what it cannot fund and says so.** The operation stopped at its funded limit, with the quoted event line and the MEASURED / ESTIMATED split, is `harness-v1.3.4/treatment/08@cf7e86f9580bb99147920b33d6481c61f55506e979bb75ee354527a6e2610bf9`: `test_the_two_cost_cap_kills_in_v134_show_the_cap_line_crossed_at_the_recorded_second`.

**Weakest point.** The LLM repair loop did not recover a single entry: 0 [MEASURED] of 8 [MEASURED] gate entry-runs (`summary.json` `headline.recovered_by_llm_loop`). The part of the system that uses the models most did not achieve its purpose.

**What mitigates it.** It is measured, not hidden, and it is the headline. The failures are traced to named defects (D-21, D-23, D-24, D-25) with a status rule and, for two of them, costed design notes. The deterministic parts work as recorded: the time machine cleared the baseline dependency error of the entry shown in the demo (`classification_chain[0]` of `harness-v1.3.4/treatment/07@6bd614a2a0447ead7e9dc6007b6fe868a29af9660ed175ddf667e08f74673a98`), which is not a recovery and is not presented as one.

## Design

1. **One coherent surface.** A single dashboard page carries the headline, the scorecard, the ledger, the defect register and a drill-down for every entry; every number shows its tag and links to its record: `test_every_number_on_the_page_carries_its_tag_and_links_to_a_record`.
2. **Failure is not in a footnote.** The EXPLORATORY badge is the first element of each exploratory card, above the numbers: `test_the_exploratory_badge_sits_above_the_numbers_and_is_absent_on_the_anchor`, `test_the_badge_sentence_in_the_html_equals_the_d1_text`.
3. **It works anywhere, offline.** One command builds it with nothing but Python and git, and it renders with the network blocked: `test_one_command_builds_the_page_with_the_standard_library_only`, `test_the_page_renders_fully_with_the_network_blocked`.

**Weakest point.** A static dashboard is not an interactive product. There is no filtering, no search, no way to start a run from the page, and the entry drill-down is a native disclosure element rather than an application view.

**What mitigates it.** The choice is deliberate: no script and no network means the evidence cannot change under the reader and opens from a file. The whole chain is navigable by links (number to record, record to passport, defect to passport). An interactive backend and frontend exist in the repository (`backend/`, `frontend/`) but are not what the submission demonstrates.

## Potential Impact

1. **A specific, measured answer to a real question.** "What is a reproduction patched by an LLM worth?" Here: the repair loop recovered 0 [MEASURED] of 8 [MEASURED] gate entry-runs (`summary.json` `headline`), and 0 [MEASURED] of 16 [MEASURED] on the pre-registered run (`badge.figures[0]` of `harness-v1.3.2/treatment/01@fecb8efd3d440fdedb29aae428abced2e511480ac673405aa55f8a5d7f5ffaf6`).
2. **It catches a false positive that would otherwise be reported as success.** The one apparent recovery is kept with its measured verdict and annotated as a smoke-limit artefact: `harness-v1.3.3/treatment/11@619a97784e6abc3f29fedf36a7c4723c65232111233a34e3299a1ed3eee034a2`, `test_entry_11_v133_shows_runs_after_repair_unchanged_with_the_artefact_annotation_beside_it`.
3. **It refuses fixes that make code do less.** The tamper gate rejects a patch that deletes the evaluation call: `test_deleted_eval_call_direct_removal_is_rejected`; an abstention is recorded as INDETERMINATE instead of a guess: `test_parse_recon_response_negative_control_low_confidence_is_indeterminate`.

**Weakest point.** The evidence base is small and nobody outside the project has used it: one corpus, one repairer model, exploratory gates of a few entries each, and no study of whether a reviewer or a replication team decides differently with a passport in hand.

**What mitigates it.** The scope is stated wherever the result is stated, and the result is claimed for this harness only. The instrument is reusable as it is: a new corpus needs records, not new tooling, and the replay and dashboard rebuild from them with one command.

## Quality of the Idea

1. **Model sizes are matched to what an error costs.** The smallest model does the job where abstaining is safe, the largest only writes prose under a rule that it may only downgrade: `summary.json` `stack.versions[].roles`, `test_adjudicator_allows_a_genuine_downgrade`.
2. **Every number says how it is known.** MEASURED, ESTIMATED or DERIVED, and a derived value quotes its source line with the record id: `test_every_derived_value_carries_its_quoted_source_line_and_record_id`, `test_every_number_in_the_html_exists_in_the_replay_json`.
3. **The instrument reports on itself.** 28 [MEASURED] defects with a printed status rule, where a partial fix stays open and a post-gate fix is labelled unvalidated: `test_the_defect_register_is_d1_to_d28_with_quoted_sources`, `test_at_repair_time_the_recorded_gcc_error_adds_build_essential_with_no_model_call`.

**Weakest point.** The non-obvious part is the audit, and it is built around a repair loop that did not work. The time machine was not compared with any other way of rebuilding an old environment: not measured. Search is called at runtime but its use by the model is not demonstrated (D-21).

**What mitigates it.** The audit does not depend on the repair working: it is what made the null result visible and attributable. The open questions are written as design notes with what a validating gate must measure (`docs/design/D-23.md`, `docs/design/D-25.md`), not as promises.
