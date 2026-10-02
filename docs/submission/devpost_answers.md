# Devpost question drafts

Drafts for the owner. Ratings are the owner's call: each proposed number is marked PROPOSED with its evidence beside it.
Every figure is in `reports/phase-d/replay/summary.json` or in a passport, and carries its tag. Track: Coding and agentic engineering.

## Which models did you use, and why those sizes?

Three Nemotron models through Nebius Token Factory, each with one narrow job (names as stored in the run records):

- `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B` for recon: find the entrypoint or abstain. It is the most frequent call and the cheapest to get wrong safely, because an abstention ends the run as INDETERMINATE instead of guessing.
- `nvidia/nemotron-3-super-120b-a12b` for planning and repair: it proposes system packages, patches and environment changes. It is the only role that reasons over code and logs, so it gets the mid-size model.
- `nvidia/Nemotron-3-Ultra-550b-a55b` for adjudication: it chooses between the candidate repairs of a round (from harness-v1.4.0) and writes the certificate prose, and may only downgrade a verdict. A few calls per run, so the largest model is affordable there.

Recorded calls in the last gate: Nano 4 [API-REPORTED], Super 39 [API-REPORTED], Ultra 10 [API-REPORTED]. The decisions that matter (classification, the tamper gate, the env gate, the cost guard, the verdict) are deterministic code, not model calls.

## How would you rate Nemotron's output quality (1–10)?

**PROPOSED: 4/10 for the repair role, as measured here.** The owner decides.

Evidence for:
- Patches and environment changes are well-formed enough to apply: criterion (b) passed in every gate, and in the last one 15 [API-REPORTED] of the 17 [API-REPORTED] proposed patches were applied.
- The model abstains and explains itself: it recorded a reason for not citing on 17 [API-REPORTED] attempts in the last gate, and declined an attempt rather than guess once the harness told it there was no error text.
- It produced a recorded repair attempt in 17 [API-REPORTED] of 24 [API-REPORTED] gate entry-runs, and the one entry-run that ended RUNS_AFTER_REPAIR (harness-v1.4.2, a smoke-criterion pass: the command ran for the smoke limit without failing) followed environment changes it had proposed. The same entry ended BLOCKED in the last gate: the pass did not repeat.

Evidence against:
- No gate passed: 2 [API-REPORTED] of 24 [API-REPORTED] gate entry-runs ended RUNS_CLEAN or RUNS_AFTER_REPAIR, one a smoke-limit artefact and one that smoke-criterion pass, and 0 [API-REPORTED] of 16 [API-REPORTED] repositories reached RUNS_AFTER_REPAIR on the pre-registered run.
- It cited a source in some gates and not in others: 7 [API-REPORTED] citations in the last gate, and 0 [API-REPORTED] in the one before it although 51 [API-REPORTED] references were offered (D-21).
- It proposed installing a C compiler as a Python package (D-24) and, before the harness forbade it, patched with no error text to go on (D-19); that text had been cut off by the SDK (D-41), so this counts against the harness, not against the model.

This rates one repairer model on one small corpus under a strict gate. It is not a general rating of Nemotron, and the other two roles were not scored separately: not measured. If the owner counts the one smoke-criterion pass in the repairer's favour, 5/10 is as defensible from the same records.

## Prompt-engineered or fine-tuned?

Prompt-engineered. The records name hosted model endpoints only; no fine-tuned model appears in any record. The prompts carry the failure class, the error line, the file most likely at fault, numbered search references and, on a silent exit, the rule that only diagnostics may be added.

## How does it compare with other models?

Not measured. Every record uses the three Nemotron models above; there is no record with another model, so no comparison is claimed.

## Which Nebius capabilities did you use?

- **Token Factory sandboxes**: every baseline run and re-execution (recorded backend `token_factory`, default image `python:3.10-slim`).
- **Token Factory model endpoints**: the three Nemotron models, with per-call token usage stored in each record.
- **The models endpoint with pricing**: the cost guard prices every call from it and records the source and retrieval date.
- **Seal verification**: every sandbox-touching code path was executed live before a harness version was sealed; the logs are committed under `runs/sandbox_verification/`.

Recorded spend on the current ledger: $29.1704 [ESTIMATED] = $26.2069 [API-REPORTED] + $1.4761 [ESTIMATED] + $1.4874 [DERIVED], a lower bound (D-27); the DERIVED part is parsed from the logs of gate attempts that were killed before they wrote a record. That is the sandbox API's reported operation cost; the account balance page showed at most $0.43 [BILLED] charged at the time of the owner's second reading, which predates the last two gates, and the two are not reconciled (D-36, open).

## How likely are you to recommend Nebius Token Factory?

**PROPOSED: 7/10.** The owner decides.

Evidence for: the sandboxes carried the 65 [API-REPORTED] recorded entry-runs (one ended in a transport error and was retried under the registered policy) and the seal verifications; the pricing endpoint made a hard cost guard possible; the API returns peak memory per operation.
Evidence against: a step stopped by the sandbox comes back as a normal result with a flag the SDK does not surface (D-17); the spend of a killed step is not reported, so our ledger is a lower bound (D-27); the memory and CPU of a sandbox VM are not documented and the SDK has no parameter for a larger one (we read 3.85 [DERIVED] GiB from inside, D-40); and the SDK truncates each output stream at a fixed byte limit by default, which hid a CUDA error for several versions before a probe confirmed it (D-41; the limit can be raised, and the flag that says it was cut is in the result).

## How was the developer experience?

**PROPOSED: 6/10.** The owner decides.

Evidence: the sandbox SDK was usable from its source, but its behaviour at limits had to be discovered live (D-17, the upload size limit, the refusal of executable-stack libraries). Each discovery is written down with the record that showed it, in `METHODOLOGY.md` and the defect register.

## What would you improve?

In Nebius Token Factory, from what the records show:
- surface the timed-out state of a sandbox step as an error or a documented field (D-17; an issue is drafted in `reports/corpus-v2.1/sponsor-issues/`);
- report the cost of a step that was stopped, so a ledger does not need an estimate (D-27);
- document the memory and CPU of a sandbox VM and let a run choose a larger one: one entry was killed by the 3.85 [DERIVED] GiB the VM has, in two gates running (D-40);
- raise the output truncation default or make the cut impossible to miss where a result is read: it hid an error message for several versions (D-41).

In RERUN: the open defects (D-21, D-25, D-43), a gate that cannot be killed by its environment without a trace (D-43), and storing funded and wall seconds as record fields instead of deriving them from event lines. The output-truncation flag and the API's peak memory are stored on every operation from the last version.

## What is next?

All live work has stopped: the final gate has run. The next step is written down, not promised, and it is the owner's decision: a gate that exercises the sustained-run line (D-42) on an entry that ends RUNS_*, which would need a new seal and a new gate, and the room left under the spend ceiling is small. Each design note (`docs/design/D-25.md`, `docs/design/D-40-resources.md`) says what a validating gate would have to measure before the defect may be called fixed.

## Did you use Tavily?

**Yes.** Tavily is called at runtime before each repair attempt, and the references are stored on the attempt: 27 [API-REPORTED] attempts consulted and 81 [API-REPORTED] references in the last gate. The honest sentence: the model cited sources in the last gate (7 [API-REPORTED] citations) and in two before it (3 [API-REPORTED] and 6 [API-REPORTED] citations) but in none of the one between them (0 [API-REPORTED] citations); whether a citation shaped a decision is not measured, and that defect (D-21) is open.

## Is this a new project or an existing one?

<!-- OWNER TO ANSWER: left blank on purpose -->
