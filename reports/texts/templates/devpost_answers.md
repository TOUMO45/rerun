# Devpost question drafts

Drafts for the owner. Ratings are the owner's call: each proposed number is marked PROPOSED with its evidence beside it.
Generated from `reports/v1.9/figures.json` by `reports/texts/render.py` (template: `reports/texts/templates/devpost_answers.md`): every figure carries its tag. Track: Coding and agentic engineering.

## Which models did you use, and why those sizes?

Three Nemotron models through Nebius Token Factory, each with one narrow job (names as stored in the run records):

- `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B` for recon: find the entrypoint or abstain. It is the most frequent call and the cheapest to get wrong safely, because an abstention ends the run as INDETERMINATE instead of guessing.
- `nvidia/nemotron-3-super-120b-a12b` for planning and repair: it proposes system packages, patches and environment changes. It is the only role that reasons over code and logs, so it gets the mid-size model.
- `nvidia/Nemotron-3-Ultra-550b-a55b` for adjudication: it chooses between the candidate repairs of a round and writes the certificate prose, and may only downgrade a verdict. A few calls per run, so the largest model is affordable there.

Recorded calls in the last exploratory gate: Nano {{last_gate_calls_nano}}, Super {{last_gate_calls_super}}, Ultra {{last_gate_calls_ultra}}. The decisions that matter (classification, the tamper gate, the env gate, the cost guard, the verdict) are deterministic code, not model calls.

## How would you rate Nemotron's output quality (1–10)?

**PROPOSED: 4/10 for the repair role, as measured here.** The owner decides.

Evidence for:
- It produced a recorded repair attempt in {{gate_with_model_attempt}} of the {{gate_entry_runs}} exploratory gate entry-runs, well-formed enough for the gate to apply, and it abstains with a reason instead of guessing.
- On the DEV rounds of the dev/test protocol (tuned-on entries), one entry reached RUNS_AFTER_REPAIR in every round on a model-proposed environment change adopted through the tamper gate. Each is a smoke-criterion verdict, not a reproduced result.

Evidence against:
- No exploratory gate passed: {{gate_apparent_recoveries}} of {{gate_entry_runs}} gate entry-runs ended RUNS_CLEAN or RUNS_AFTER_REPAIR, one a smoke-limit artefact.
- On the independent cheat set, Ultra (the adjudicator) adopted {{indep_v190_adopted}} of the {{indep_confirmed_cheats}} measured cheats, {{indep_real_failure_cheats_adopted}} of the {{indep_real_failure_cheats}} aimed at a repository whose run really fails: it judges a patch by whether it addresses the failure, so a genuine fix bundled with a change of the result passes.
- It cited a source in some gates and none in another although references were offered (D-21, open), and it once proposed installing a C compiler as a Python package (D-24).

This rates one repairer model on one small corpus under a strict gate. It is not a general rating of Nemotron.

## Prompt-engineered or fine-tuned?

Prompt-engineered. The records name hosted model endpoints only; no fine-tuned model appears in any record. The prompts carry the failure class, the error line, the file most likely at fault, numbered search references and, on a silent exit, the rule that only diagnostics may be added.

## How does it compare with other models?

Not measured. Every record uses the three Nemotron models above; there is no record with another model, so no comparison is claimed. The benchmark (`benchmark/`) accepts any checker's decisions and scores them the same way.

## Which Nebius capabilities did you use?

- **Token Factory sandboxes**: every baseline run and re-execution, and the kept environment images the cheat measurements branched from.
- **Token Factory model endpoints**: the three Nemotron models, with per-call token usage stored in each record.
- **The models endpoint with pricing**: the cost guard prices every call from it and records the source and retrieval date.
- **Seal verification**: every sandbox-touching code path is executed live before a harness version is sealed; the records are committed under `runs/sandbox_verification/`.

Recorded spend: the ledger is {{ledger_usd}} against the owner's ceiling of {{ledger_ceiling_usd}} (`reports/ledger_total.py`): the sandbox API's reported operation cost plus the priced model calls, a stated lower bound (D-27); the harness-v1.10 passes are {{ledger_v110_pass_usd}} of it.
The account balance is the owner's reading (`reports/dev/BILLED_READINGS.md`): at the second reading it showed at most {{billed_second_reading_charged_usd}} charged, before the last gates; the account balance and the API-reported ledger are not reconciled (D-36, open).

## How likely are you to recommend Nebius Token Factory?

**PROPOSED: 7/10.** The owner decides.

Evidence for: the sandboxes carried every recorded entry-run ({{gate_passports}} passports in the exploratory gates alone), the seal verifications and the cheat measurements; the pricing endpoint made a hard cost guard possible; the API returns peak memory per operation.
Evidence against: a step stopped by the sandbox comes back as a normal result with a flag the SDK does not surface (D-17); the spend of a killed step is not reported, so the ledger is a lower bound (D-27); the memory and CPU of a sandbox VM are not documented and the SDK has no parameter for a larger one (D-40); and the SDK truncates each output stream at a fixed byte limit by default, which hid a CUDA error for several versions (D-41).

## How was the developer experience?

**PROPOSED: 6/10.** The owner decides.

Evidence: the sandbox SDK was usable from its source, but its behaviour at limits had to be discovered live (D-17, the upload size limit, the refusal of executable-stack libraries). Each discovery is written down with the record that showed it, in `METHODOLOGY.md` and the defect register.

## What would you improve?

In Nebius Token Factory, from what the records show:
- surface the timed-out state of a sandbox step as an error or a documented field (D-17; an issue is drafted in `reports/corpus-v2.1/sponsor-issues/`);
- report the cost of a step that was stopped, so a ledger does not need an estimate (D-27);
- document the memory and CPU of a sandbox VM and let a run choose a larger one (D-40);
- raise the output truncation default or make the cut impossible to miss where a result is read (D-41).

In RERUN: an adjudicator that cannot be talked into a bundled patch (the {{indep_real_failure_cheats_adopted}} adopted cheats), behavioural checks precise enough to refuse rather than flag (they refused {{indep_controls_refused_by_checks}} of {{indep_controls_passed_run}} honest controls), and a cheat set written by an author who knows the checks.

## What is next?

The submission harness is harness-v1.10.0: harness-v1.9.0's verdict rules, plus the behavioural checks as a review flag. They refuse too many honest repairs to be a verdict rule, so an adopted patch they would have refused keeps its verdict and its certificate says REVIEW_REQUIRED with the reason: a signal that a human should look, not a cheat detector (it also marks {{flag_controls_adopted_flagged}} of the {{indep_v190_adopted_controls}} honest repairs harness-v1.9.0 adopted). The mode was sealed live ({{v110_seal_paths}} verified code paths, {{v110_seal_run_ids}} live run ids) and tagged; its one live run so far ({{minmaxot_flag_live_cost_usd}}, minmaxot) gave the harness-v1.9.0 run's decisions with {{minmaxot_flag_live_flagged_attempts}} attempts flagged, and no live run has yet produced a REVIEW_REQUIRED certificate (the test suite has). After that: a new independent cheat set (both current sets are development material now), an adaptive set written by an author who knows the allow-list, and the open defects in the register. What comes next is the owner's decision, not a promise.

## Did you use Tavily?

**Yes.** Tavily is called at runtime before each repair attempt, and the references are stored on the attempt. The model cited sources in some gates and none in another although references were offered, and whether a citation shaped a decision is not measured (D-21, open).

## Is this a new project or an existing one?

<!-- OWNER TO ANSWER: left blank on purpose -->
