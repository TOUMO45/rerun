# harness-v1.4.1-rc — Step 1 report (offline; no Nebius call, no spend)

Status: **implemented and unit-tested offline; unsealed; not validated by any gate.** Nothing here claims a recovery. Tags: API-REPORTED = a stored record field (for a dollar
figure the sandbox API's reported operation cost, not account billing, D-36; formerly MEASURED), DERIVED = computed from named records, ESTIMATED, BILLED = the owner's account-balance
reading. Ledger before Step 2: **$14.6495** [ESTIMATED: $13.6787 API-REPORTED + $0.9708 ESTIMATED], a lower bound (D-27); owner's ceiling $25.00 API-reported (headroom $10.3505).
`harness-v1.4.0` stays at `15d3cdf`: its tag is untouched and none of its files is edited in place.

## 1. The six directive items, implementation, and the test that pins each

| Item | Defect | Implementation | Tests |
|---|---|---|---|
| 1. Funding rate | D-30 | `cost_guard.CostGuard.funding_rate()`: sum of this entry's completed operations' cost over their wall time, x1.5, floor $0.0030, ceiling $0.0085 (the old fixed rate); no completed operation: the ceiling. The orchestrator funds each non-baseline operation at it and stores `operations[].funding` (`rate_used_usd_per_s`, measured rate, basis, source operations) on EVERY operation (the baseline: "not budget-limited"). | `test_v141_funding_and_resume.py`: #11's recorded stop read from its record (`::test_the_recorded_stop_of_entry_11_would_have_been_funded_for_the_full_smoke_run`), clamps and sources, the per-operation fields |
| 2. Resume after a budget-limited stop | D-31 | `orchestrator._execute` = `_execute_once` + a resume loop: after a stop at the budget-derived limit, if what is left funds one operation (smoke run + 20 s) AND a kept image holds at least one setup command, the next operation reopens the deepest kept image; at most 2 resumes per operation; otherwise INDETERMINATE COST_CAP with the reason ("not resumed: ..."). | same file: #11's sequence on the fake cloud with a scripted clock (baseline 78.52 s, era 112.56 s, as recorded): killed, then resumed from the kept era image, no third torch install; the two COST_CAP branches; the resume limit |
| 3. Adjudicator | D-32 | `adjudicator.adjudicate_candidates`: one JSON re-ask (both raw replies stored, `replies`, `reasked`); fallback = first passing run, else the furthest recorded stage (`stage_rank`: phase of the final step, setup steps completed, still running when it failed, seconds), ties to the lowest number; `fallback_basis` stores what it chose from. The orchestrator passes each qualifying candidate's `stage`. | `test_v141_adjudicator.py`: #7 round 1 read from the committed record (candidate 2 reached `No module named 'Box2D'`, candidate 1 stopped in package metadata, the recorded fallback chose 1) |
| 4. Rules on every candidate | D-33 | `_observe_candidate`: after a candidate's run fails, D-24, the CPU shim, the exit hook and the exit wrapper are matched against THAT failure and fire in the candidate's own branch; the action goes on the candidate's attempt as `time_machine_action` (`on_candidate`, `then` for a second action); the candidate's outcome is the run after the rules; what a rule added joins the run's environment only if that candidate is adopted. | `test_v141_candidate_rules.py`: #7 round 2's gcc line, adopted and not adopted (parametrized), the control without the trigger, the CPU shim on a candidate |
| 5. Layering | D-34 | A repair-time apt package is an additive layer, `export DEBIAN_FRONTEND=noninteractive && apt-get update && apt-get install -y ...`, placed (`_apt_layer_for`, `_sandbox_steps`) after the install commands the deepest kept image holds; the leading `export` keeps `split_setup_ops` from filing it with the system packages (which always run first). With no environment image kept the package joins the first apt step as before. **`sandbox.py` is not touched** (this is why the seal can be small). | `test_v141_apt_layer.py`: a fake cloud counts every command: after a run-time gcc need only the layer runs and no `pip install` follows it; after a build-time need the layer goes before the failing pip step and torch is installed twice in the whole entry (baseline + era), not three times |
| 6. D-25 extension | D-35 | `runner_hooks.wrap_entry_command` + the orchestrator's `_auto_exit_wrapper` (main flow, after the hook printed nothing) and the same rule on candidates: `python -c <wrapper> script main.py args`, the wrapper is `runpy.run_path` inside `try/except SystemExit` that prints the traceback and re-raises; "exit outside Python" if it prints nothing too; "not applicable" (recorded, nothing run) for anything but a plain `[VAR=v] python [-u] script.py args` / `python -m module args`. | `test_v141_exit_wrapper.py`: REAL subprocesses on a fixture with a bare `raise SystemExit(1)` (the hook alone prints nothing; the wrapper prints the raise site, same exit code), `sys.argv`/`__file__`/`sys.path`/`chdir(dirname(__file__))` against plain `python script.py`, `-m`, 10 not-applicable commands, the orchestration on the fake cloud |

Negative controls (a mechanism disabled, the tests that should notice it fail, the file restored byte for byte): no apt layer, no resume, fixed funding rate, no candidate rules
(`mutate.py` in the session scratchpad; each run showed the expected failure).

Old test changed on purpose: `test_v140_pipeline.py::test_entry_7_d24_under_checkpoints_...` asserted v1.4.0's behaviour (`start_setup_commands == 0`: build-essential rebuilt from
the tree image); it now asserts the v1.4.1 behaviour (the era lock's layer is reused, only the apt layer runs). Test fixed that was already failing at HEAD:
`test_seal_verification.py::test_the_committed_file_names_only_live_records_that_exist_and_passed` still expected the v1.3.4 tag in `seal_verification.json` (the v1.4.0 seal commit wrote
v1.4.0; the same kind of fix as `8af1717`).

## 2. What the records say, checked (the directive's "reading to verify")

Annotated in `reports/corpus-v2.1/v1.4.0/gate/GATE_REPORT_v1.4.0.md` (the original text is unchanged). Result: **#11 holds; #7 holds; #3 holds as "an exit the hook did not see"; #8 holds only in part.**
#8's last operation was funded 44.1 s at the fixed rate from $0.3749, but the entry had already spent $1.1422 of $1.25 (91.4 %) in two rounds of three candidates, so it was not "not by exhausted
budget". #3: the record does not show whether the exit was a bare `raise SystemExit` or a process-level exit (the wrapper will tell). Kept images: 8 / 6 / 6 / 8 (#3 / #7 / #8 / #11), now
"no charge observed on the account balance".

DERIVED counterfactual (each record's own completed operations and the money its guard had; no spend): #11 operation 2 would be funded 145.9 s at $1.25 and 185 s at $1.50 (it needed about 168 s);
#8 operation 11 would be funded 67.5 s (recorded 44.1 s); every other operation of the four entries would be funded at least as many seconds as recorded (by construction: the new rate never
exceeds the old one). **At the old $1.25 cap neither rule saves #11**: funded 145.9 s, the operation would be stopped about 38 s into its smoke run, the estimate for that killed step
($0.32 at the guard's ceiling rate) leaves $0.30, which funds 48 s, below one resumed operation (80 s): COST_CAP, later and dearer than recorded. That is why the owner's $1.50 entry cap matters;
the resume rule covers the stop as it was recorded (late in setup, $0.62 left, about 98 s fundable) and any stop that leaves an image and the money. Tests:
`test_at_the_old_1_25_entry_cap_entry_11_would_still_end_cost_cap_after_a_late_stop`, `test_the_stop_as_recorded_was_resumable_at_the_old_cap_...`.

## 3. D-36, relabel and BILLED (owner's item 1)

- `docs/design/D-36.md` (offline investigation, quotes marked [direct] / [fetch], no API call): `resources.cost` is documented only as "Operation cost" (no unit, no currency, no formula);
  "USD" is our wording. The Token Factory sandboxes page says "Free while in beta — runs don't consume your credits" (read logged out, undated). The billing docs do not mention Sandboxes and state
  no display delay. In the ledger window (2026-09-30 19:54 UTC to 2026-10-01 17:11 UTC) the model share is $0.4245 DERIVED and the sandbox share $14.2250 API-reported (incl. $0.9708 ESTIMATED); the
  $0.39 charged is not decidable from the repository. Six hypotheses, each with the one observation that settles it (Usage tab filtered by service, Transactions, re-reading the balance at +1 h / +6 h / +24 h).
  Registered as D-36, status **open**; ledger stays "a bound on API-reported cost, not on spend".
- Side finding, **decision for the owner** (annotated on D-27, nothing changed): the killed-step ESTIMATE uses $0.0085 per second, while the API's cost per BILLED second is $0.0101 at the median over 21
  steps of at least 3 s (minimum $0.01005, maximum $0.01454), so those estimates are not upper bounds (small: $0.1868 on #8 operation 11).
- Relabel (MEASURED -> API-REPORTED) in the Phase D assets: 49 passports (schema v4), REPLAY (3 versions + summary + index), dashboard, README, Devpost answers, description, criteria map, demo script, the
  budget note and their tests; ESTIMATED and DERIVED unchanged; no number changed value (1506 tagged values compared; `backend/tests/test_phase_d_relabel.py` pins it). BILLED: the account line (at most $0.39,
  the owner's source string, billing lag unknown) and one null line per REPLAY gate with the reason; the v1.4.0 gate's line is in its report, the v1.4.1 gate's line stays null until the owner reads the balance.
  Not touched, by rule: `reports/corpus-v2.1/**` pre-registered and historical reports and `scripts/` (sealed paths) keep the old word MEASURED; METHODOLOGY says to read it as API-REPORTED. JSON keys named
  `measured` are structural and unchanged.

## 4. Seal of harness-v1.4.1 (option B over changed files only) and its estimate

Sandbox-touching files changed: `runner_hooks.py` only. The v1.4.0 seal entries whose code files are all unchanged (11 of 12: download route by git, archive upload, runner torch on 3.6 / 3.10 / 3.9 with the
NumPy cap, the runner-setup phase tag, the kill path through both stop paths, the smoke launcher, checkpoint layers and branch run, kept image reopened later, the real entry-7 checkpoint) are carried over
by `scripts/write_seal_verification_v141.py`, which compares each blob with the v1.4.0 record and stops if one changed. Live (`reports/corpus-v2.1/v1.4.1/seal/run_seal_v141.py`, records in
`runs/sandbox_verification/v1.4.1-seal/`): run 1 A ready image, B one branch run, C hooks on a kept image (the one re-verified entry), W0 bare `raise SystemExit(1)` with the hook alone, W1 through the wrapper,
W2 the wrapper on python:3.6-slim; run 2 L1 / L2 the additive apt layer on a kept image; run 3 K1 / K2 an operation stopped at its limit and a new operation reopening the layer before the stopped step
(the one thing the fake cloud cannot show: that a KILLED operation's layers are reopenable on the real service).

**Estimated cost $0.3637 [ESTIMATED]**, from the v1.4.0 seal and gate records: A $0.0120 and C $0.0012 API-reported, B $0.0011 (the dearest v1.4.0 smoke run on a ready image; the measured branch run was
$0.00054618), W0 / W1 $0.0012 each, W2 $0.0030, L1 $0.0120, L2 $0.1000 (the apt step of #8 operation 11 cost $0.0775 for build-essential in 7.7 s), K1 $0.2200 (the stopped sleep runs about 20 s of its 30 s limit
at $0.0103 per billed second; a kill may bill less), K2 $0.0120. Cap **$1.00**; an operation starts only while three times its estimate is left under the cap (K1 needs $0.66), so one repeat of the dearest
check still fits. Seal -> gate (owner's rule, automatic): every seal check passed, branch-run cost (B) at most $0.15 API-reported, seal spend at most $1.00.

## 5. Gate v1.4.1, pre-registered (METHODOLOGY, before any v1.4.1 run)

Same four entries in the same order (3, 7, 8, 11), TREATMENT only, criteria (a)-(e) unchanged (`run_gate_v141.py` loads the v1.4.0 runner's criteria, test `test_v141_gate_runner.py`), fixed entry cap
$1.50, gate cap $6.00 (= 4 x entry), hard stop at the gate cap, each entry reported as it lands. Worst case seal + gate = $7.00, so the ledger stays at or under $21.6495 of the $25.00 ceiling.

## 6. Found, decisions

1. **Killed-step estimates are not upper bounds** (D-27 annotation above): open for the owner; unchanged here.
2. **D-36's most informative single fact is "Free while in beta"**: if it applies, the $0.39 is model tokens and sandbox spend is $0 on the account; the caps stay as discipline either way.
3. **The resume threshold uses a 20 s start-up margin** (twice the largest wall overhead, 10.0 s, of the 22 v1.4.0 operations that ran no setup step); v1.4.0's 45 s candidate margin is unchanged for concurrency.
4. **At the old $1.25 cap neither the rate nor the resume rule saves #11** (§2); the pre-registered $1.50 cap is what makes the counterfactual fit.
5. A resumed operation is a new operation: criterion (e) counts it like any other (it installs nothing); its record carries `resumed_after_operation`.
6. The exit wrapper is applied to the documented command only when it is a plain python invocation; #3's command (`python feature_vgg16.py #gpu_id #split`) qualifies (the shell comment is dropped as the shell drops it).

## 7. What remains

Step 2 (live, automatic under the seal -> gate rule): seal at most $1.00, tag `harness-v1.4.1` on the seal commit only if every check passes, gate under the stated rule, each entry reported as it lands.
Tag `harness-v1.4.1-rc` on the Step 1 commit (unsealed, used in no gate figure).
