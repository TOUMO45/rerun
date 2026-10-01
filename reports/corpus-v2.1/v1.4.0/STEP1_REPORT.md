# harness-v1.4.0-rc — Step 1 report (offline; no Nebius call, no model call, no spend)

Status: **implemented and unit-tested offline; unsealed; not validated by any gate.** Nothing here claims a recovery or a measured cost of
v1.4.0. Every number carries MEASURED (a stored record field), DERIVED (parsed or computed from MEASURED values, source named) or ESTIMATED.
Ledger: $10.1349 [ESTIMATED: $9.8507 MEASURED + $0.2842 ESTIMATED], lower bound (D-27). Unchanged: nothing ran.
`harness-v1.3.4` stays at `10319b3`; the Phase D assets (passports, REPLAY, dashboard, submission texts) are untouched.

## 1. Directive items, implementation, and the test that pins each

| Directive item | Entry | Implementation | Tests |
|---|---|---|---|
| Checkpoint: keep the environment image, reopen it by UUID, never rebuild what it holds | #11, #08 | `sandbox.Checkpoint`; `run_build_and_execute(checkpoint=...)` keeps the image after the committed tree and after every setup step ("layers"), starts from a kept image and runs only the missing setup steps; orchestrator `_execute` picks the deepest kept image whose setup steps are a prefix of what the operation needs | `test_v140_checkpoint_sandbox.py::test_an_operation_following_a_checkpoint_reopens_the_image_instead_of_rebuilding`, `::test_branching_never_reinstalls_a_package_already_in_the_image` (fake client counts installs: 1 torch install across a checkpoint and nine branches); `test_v140_pipeline.py::test_entry_8_the_time_machine_branches_from_the_baseline_torch_layer_and_installs_torch_once` |
| Every change applied in a branch on top of the image; D-20 overlay out of the live flow, tests kept as legacy | all | kept images always hold the committed tree (fresh operations upload the pristine bytes of every patched path, from git); patched and deleted files travel in a branch overlay archive with a hash check, after the setup steps (or right after the tree when a setup step reads a patched file); `test_v134_overlay.py` marked `legacy` | `::test_the_overlay_writes_and_deletes_files_and_lands_after_the_setup`, `::test_an_early_overlay_is_applied_right_after_the_tree`, `::test_a_failed_overlay_check_is_a_harness_integrity_failure` |
| Entry cap never inherited from a starved gate remainder; gate cap >= 4 x entry cap | #08 | `app/services/gate_budget.py` (`check_gate_caps`, `entry_cap_for`); gate runner uses a fixed entry cap and stops instead of starting an entry with less | `test_v140_gate_budget.py::test_the_estimator_refuses_a_gate_whose_cap_is_below_four_entry_caps`, `::test_the_v134_starvation_cannot_happen_an_entry_gets_its_full_cap_or_is_not_started` |
| CPU shim, deterministic, on GPU_REQUIRED, before any model call | #11 | `app/services/runner_hooks.py` (`cpu_shim`: lazy import hook; `torch.load` -> `map_location="cpu"`, `torch.cuda.is_available()` -> False), installed as one setup step on top of the environment image; recorded as `time_machine_action` {rule `cpu_shim`, matched_error, ...} | `test_v140_pipeline.py::test_entry_11_cpu_shim_fires_on_the_recorded_torch_load_error_with_no_model_call` (entry 11's recorded error read from the committed record; the fake model raises if called); `test_v140_runner_hooks.py` runs the shim for real against a fake `torch` package |
| D-24 (already in) | #07 | unchanged rule; under checkpoints the build-essential operation branches from the kept tree image (no re-upload) | `test_d24_build_essential.py` (unchanged); `test_v140_pipeline.py::test_entry_7_d24_under_checkpoints_branches_from_the_kept_tree_and_never_reuploads` (entry 7's recorded gcc error) |
| D-25 exit-site hook, automatic on a non-zero exit with no traceback | #03 | `runner_hooks` `exit_hook`: prints the call stack at `sys.exit`, `os._exit`, `exit()`, `quit()` (and every library calling `sys.exit`) when the code is non-zero, ending in `SystemExit: <code>`; the smoke launcher's own exit is never reported. Limit, recorded with every use: a bare `raise SystemExit(n)` in the repository's code is not captured | `test_v140_runner_hooks.py::test_the_exit_hook_prints_the_stack_of_a_sys_exit_1` (a real process calling `sys.exit(1)`), `::test_the_smoke_launcher_own_exit_is_never_reported`; `test_v140_pipeline.py::test_entry_3_the_exit_hook_fires_on_the_recorded_silent_exit_and_the_model_then_sees_the_exit_site` (entry 3's recorded silent exit) |
| Parallel repair: up to 3 candidates, py_compile, branches (concurrent when funded), Ultra adjudicates the outcome-changing ones, the chosen image becomes `env_image_id`; 3 x 3 cap | all | orchestrator repair round (`candidates_per_round`, setting `repair_candidates_per_round` = 3); `tamper_gate.py_compile_violations`; `adjudicator.adjudicate_candidates` (choice checked in code; deterministic fallback recorded); losing images released, the disposal runs' cost recorded | `test_v140_pipeline.py::test_three_candidates_run_in_branches_and_the_adjudicated_one_becomes_the_environment` ($5 left: concurrent; $1.25: one after another), `::test_a_candidate_that_does_not_compile_is_rejected_before_it_runs`, `::test_no_candidate_changing_the_outcome_means_no_adjudication_call_and_no_change` |
| Citation: keep REQUIRED; snippets to the candidate generator with "cite the index" | all | `repairer.CITATION_RULE` appended after the numbered snippets; `candidate_followup` for candidates 2 and 3; the record stays honest if no candidate cites | `test_v140_pipeline.py::test_tavily_snippets_reach_the_candidate_generator_with_the_citation_rule` |
| Record fields on every operation | all | `CostGuard.operations`, written by `scripts/live_run.py` as `operations`: `sandbox_seconds`, `install_seconds` (per step), `branch_from_image`, `result_image`, `image_kept`, plus `kept_images`, `env_image_id`, `torch_installed`, `torch_in_start_image`, `torch_env_key`, cost (measured / estimated part), outcome | `test_v140_pipeline.py::test_operation_records_are_complete_and_measured` |
| Estimator uses one install per entry | — | `gate_budget.plan_entry` / `estimate_gate` (ESTIMATED; flags a plan with more than one torch install outside the baseline) | `test_v140_gate_budget.py::test_the_cost_estimator_uses_one_install_per_entry` |

Behaviour preservation: a sandbox runner that does not declare `checkpoint` / `runner_extras` as named parameters (every older runner and
test double), and `candidates_per_round = 1`, keep the harness-v1.3.x flow; the whole earlier suite passes unchanged.

## 2. Criterion (e), as checked from the records

`reports/corpus-v2.1/v1.4.0/gate/run_gate_v140.py::criterion_e`: no operation installs torch on top of an image that already holds it
(`torch_installed` and `torch_in_start_image`), and no operation rebuilds an environment definition (`torch_env_key` = base image + setup steps
through the torch install) that an earlier operation of the entry already built; candidates of one round run at the same time and are not
counted against each other. The planner-image baseline's install is counted separately (`baseline_installs`) and is outside (e).
Tests: `test_v140_gate_runner.py` (a record made by the real pipeline passes; the same record with the v1.3.4 behaviour fails).

## 3. Seal design (Step 2 sets the gate cap from its measurement)

`reports/corpus-v2.1/v1.4.0/seal/run_seal_v140.py` (plan by default; `--go` needs `--max-usd`, at most $1.50). Exercised offline end to end on
the fake cloud (`test_v140_seal_runner.py`).
- Run 1: A ready image (one pip step) with every layer kept; B one branch run from it (overlay one file): **the measured branch-run cost**;
  C the two runner hooks on top of the same image and an exit probe (live check of the hook); D after a wait, reopen B's kept image.
  A kept image's storage is not in any operation's cost: the record lists every kept image id with times for the billing page.
- Run 2: entry #07's recorded chain (the record's certificate build plan: python 3.8, its era lock and the apt packages its repairs added)
  built as a checkpoint (E), then "reopen + apply + execute" from E's deepest kept image (F): a full repair operation on a real entry.
- Run 3: only as a repeat of an ambiguous run.
- ESTIMATED cost: run 1 $0.0272, run 2 $0.4676, together $0.4948 (sources printed by the plan: v1.3.4 seal record
  `smoke_exits_ok_py310.json` $0.0011 MEASURED; entry 7's v1.3.4 repair-3 operation with the same build plan $0.2338 DERIVED, `events[54]`).

## 4. Found, decision needed

1. **The seal rule asks for more than three runs.** `scripts/run_corpus_v1_batch.py::check_seal_verification` refuses a batch unless every
   sandbox-touching file (`sandbox.py`, `sandbox_limits.py`, `runner_env.py`, `smoke_exec.py`, and now `runner_hooks.py`) is covered by live
   verifications made against its CURRENT blob. `sandbox.py` and `smoke_exec.py` changed, so all eleven harness-v1.3.4 verification entries are
   stale, and "seal first with at most three live runs" cannot satisfy the rule as written. Options:
   - (A) repeat the whole v1.3.4 seal suite plus runs 1-2: $1.2407 [DERIVED: the v1.3.4 seal's 20 records, $1.3125 MEASURED, minus the
     legacy overlay case $0.0717] + $0.4948 [ESTIMATED] = about $1.74 [ESTIMATED], above the proposed $1.50;
   - (B) runs 1-2 plus only the v1.3.4 paths the four gate entries use (download route by git: #08's 143 MB repo; torch on 3.10 newest, 3.9 pin
     with the NumPy cap, 3.6 pin; the kill path; the smoke launcher; the runner-setup phase; the upload exec bit): $0.7051 [DERIVED from those
     records' MEASURED costs] + $0.4948 [ESTIMATED] = about $1.20 [ESTIMATED], with the rule amended to "paths used by the gate entries" and the
     unused paths (tarball fallback, 3.8 / 3.10-pin torch, patchelf flag) listed as not re-verified for v1.4.0;
   - (C) keep "three runs" by folding: run 1 on python:3.9 with the #11 era torch pin (covers the torch 3.9 check), run 2 on #08's repository
     by the download route (covers the git download path) instead of #07. Fewer checks; not recommended.
   Recommendation: (B), written into METHODOLOGY before the seal runs.
2. **Images RERUN keeps are not deleted.** The SDK offers no delete; the existing cleanup (a disposable no-op run on the image) is what
   `release_images` applies to losing candidates, and its measured cost is now recorded. Whether kept images are billed while kept is unknown
   until run 1 of the seal; if they are, the gate cap must include it.
3. **An apt change still rebuilds torch.** Setup steps run in a fixed order (system packages, torch, the rest), so a candidate that adds an apt
   package cannot reuse the torch layer and installs torch again in a new environment image (allowed by (e), but it costs an install).
   Entries 8 and 11 have not needed apt so far; #07 has no torch.
4. **The exit hook does not see a bare `raise SystemExit(n)`.** Recorded as the hook's `limit` in every attempt that uses it.
5. **At the proposed $1.25 entry cap the three candidates run one after another, not concurrently.** The cost guard funds an operation for
   (money left) / $0.0085 per second [MEASURED bound, `cost_guard.SANDBOX_COST_RATE_USD_PER_S`]; a third of about $0.93 left after a $0.32
   baseline funds about 36 s [DERIVED], below the 60 s smoke run plus a 45 s start-up margin. Concurrency would only kill healthy candidates, so
   the round runs them in sequence, each funded from what is left. They still branch from one environment image and install nothing again;
   only wall-clock time is lost. The rate is an observed upper bound (median $0.0026/s over 168 operations), so the seal's measured branch cost
   is the evidence for revisiting it, not this note.

## 5. Independent review before tagging, and what changed

A separate reviewer read the diff (code, not this report) and reported four defects and several record problems; all were verified against
the code and fixed, each with a test:
1. Splitting the budget across concurrent candidates could fund each for less than the 60 s smoke run, and one killed candidate ended the
   entry as COST_CAP with money left. Fixed: only the money left is shared (`CostGuard.operation_seconds_budget(share=)`), candidates run
   concurrently only when each share funds the smoke run plus 45 s, and a candidate stopped at its share does not end the entry while the
   entry can still fund an operation. Test: the parametrized candidate test ($5.00 concurrent, $1.25 sequential, no candidate killed).
2. With a non-editable `pip install .` (or `setup.py install`), a patch put on top after the setup steps left the command running the
   unpatched installed package. Fixed: such a setup step makes every patch go in right after the tree (`_installs_project_copy`).
   Test: `test_a_non_editable_project_install_gets_the_patch_before_the_setup_steps`.
3. The CPU shim was used up by a library that only looked for torch first (`importlib.util.find_spec("torch")`). Fixed: the finder stays
   until torch has actually been executed and patched, and wraps the loader of each spec instead of changing the shared loader.
   Test: `test_the_shim_survives_a_library_that_looks_for_torch_before_importing_it`.
4. The exit hook never wrapped `exit()` / `quit()`: site.py defines them after it processes .pth files. Fixed: the hook wraps them right after
   `site.setquit` runs. Test (with `python -S` to reproduce the start-up order):
   `test_the_exit_hook_wraps_exit_and_quit_even_though_site_defines_them_after_the_pth_files`.
5. A failed overlay check dropped the cost of the steps already run. Fixed: the error carries the completed cost, which is recorded spend.
   Test: `test_a_failed_overlay_check_records_what_the_completed_steps_cost`.
6. Record details: layers are registered with their own operation number (no race between concurrent candidates) and their lineage
   (`patched`); losing candidates' result images are released before any error is raised, never when they are also a reusable layer, and
   their operation records then stop listing them as kept (`result_image_released`); the release record says that the SDK has no delete call,
   so whether the disposal step frees anything is not known. Test: `test_released_losing_images_are_no_longer_reported_as_kept`.
Not changed, stated here: `sandbox_seconds` sums the API's per-step times, so for an operation the CLIENT stopped it excludes the killed
step (its client-measured duration is `killed_seconds`); a requirements file that lists `.` is not detected as a project install.

## 6. What remains

Step 2 (seal, then gate v1.4.0) starts only when the owner writes the caps in chat, and the seal-rule decision above is taken.
Tag: `harness-v1.4.0-rc` on the Step 1 commit (unsealed, never used in a gate figure).
