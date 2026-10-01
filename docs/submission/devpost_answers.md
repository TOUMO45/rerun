# Devpost question drafts

Drafts for the owner. Ratings are the owner's call: each proposed number is marked PROPOSED with its evidence beside it.
Every figure is in `reports/phase-d/replay/summary.json` or in a passport, and carries its tag. Track: Coding and agentic engineering.

## Which models did you use, and why those sizes?

Three Nemotron models through Nebius Token Factory, each with one narrow job (names as stored in the run records):

- `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B` for recon: find the entrypoint or abstain. It is the most frequent call and the cheapest to get wrong safely, because an abstention ends the run as INDETERMINATE instead of guessing.
- `nvidia/nemotron-3-super-120b-a12b` for planning and repair: it proposes system packages, patches and environment changes. It is the only role that reasons over code and logs, so it gets the mid-size model.
- `nvidia/Nemotron-3-Ultra-550b-a55b` for adjudication: it writes the certificate prose and may only downgrade a verdict. One call per run, so the largest model is affordable there.

Recorded calls in the last gate: Nano 4 [API-REPORTED], Super 16 [API-REPORTED], Ultra 4 [API-REPORTED]. The decisions that matter (classification, the tamper gate, the env gate, the cost guard, the verdict) are deterministic code, not model calls.

## How would you rate Nemotron's output quality (1–10)?

**PROPOSED: 4/10 for the repair role, as measured here.** The owner decides.

Evidence for:
- Patches are well-formed enough to apply: 2 [API-REPORTED] applied of 4 [API-REPORTED] proposed in each gate (criterion b passed in both).
- The model abstains and explains itself: it recorded a reason for not citing on 6 [API-REPORTED] attempts, and declined an attempt rather than guess once the harness told it there was no error text.
- It produced a recorded repair attempt in 5 [API-REPORTED] of 8 [API-REPORTED] gate entry-runs.

Evidence against:
- The repair loop recovered 0 [API-REPORTED] of 8 [API-REPORTED] gate entry-runs, and 0 [API-REPORTED] of 16 [API-REPORTED] on the pre-registered run.
- It never cited a search result: 0 [API-REPORTED] citations with 21 [API-REPORTED] references offered in the last gate (D-21).
- It proposed installing a C compiler as a Python package (D-24) and, before the harness forbade it, patched blindly on a silent exit (D-19).

This rates one repairer model on one small corpus under a strict gate. It is not a general rating of Nemotron, and the other two roles were not scored separately: not measured.

## Prompt-engineered or fine-tuned?

Prompt-engineered. The records name hosted model endpoints only; no fine-tuned model appears in any record. The prompts carry the failure class, the error line, the file most likely at fault, numbered search references and, on a silent exit, the rule that only diagnostics may be added.

## How does it compare with other models?

Not measured. Every record uses the three Nemotron models above; there is no record with another model, so no comparison is claimed.

## Which Nebius capabilities did you use?

- **Token Factory sandboxes**: every baseline run and re-execution (recorded backend `token_factory`, default image `python:3.10-slim`).
- **Token Factory model endpoints**: the three Nemotron models, with per-call token usage stored in each record.
- **The models endpoint with pricing**: the cost guard prices every call from it and records the source and retrieval date.
- **Seal verification**: every sandbox-touching code path was executed live before a harness version was sealed; the logs are committed under `runs/sandbox_verification/`.

Recorded spend on the current ledger: $10.1349 [ESTIMATED] = $9.8507 [API-REPORTED] + $0.2842 [ESTIMATED], a lower bound (D-27). That is the sandbox API's reported operation cost; the account balance page showed at most $0.39 [BILLED] charged at the time of the owner's reading, and the two are not reconciled (D-36, open).

## How likely are you to recommend Nebius Token Factory?

**PROPOSED: 7/10.** The owner decides.

Evidence for: the sandboxes carried the 49 [API-REPORTED] recorded entry-runs (one ended in a transport error and was retried under the registered policy) and the seal verifications; the pricing endpoint made a hard cost guard possible.
Evidence against: a step stopped by the sandbox comes back as a normal result with a flag the SDK does not surface (D-17), and the spend of a killed step is not reported, so our ledger is a lower bound (D-27).

## How was the developer experience?

**PROPOSED: 6/10.** The owner decides.

Evidence: the sandbox SDK was usable from its source, but its behaviour at limits had to be discovered live (D-17, the upload size limit, the refusal of executable-stack libraries). Each discovery is written down with the record that showed it, in `METHODOLOGY.md` and the defect register.

## What would you improve?

In Nebius Token Factory, from what the records show:
- surface the timed-out state of a sandbox step as an error or a documented field (D-17; an issue is drafted in `reports/corpus-v2.1/sponsor-issues/`);
- report the cost of a step that was stopped, so a ledger does not need an estimate (D-27);
- allow a cached image layer per environment, so a re-execution does not pay the same install again (D-23).

In RERUN: the three open defects with design notes or register rows (D-21, D-23, D-25), and storing funded and wall seconds as record fields instead of deriving them from event lines.

## What is next?

Nothing is scheduled to spend money: the stop rule is in force. The next steps are written and costed, not promised: a cached torch layer or a per-operation floor (`docs/design/D-23.md`), and a harness-injected exit-site hook (`docs/design/D-25.md`). Each note says what a validating gate would have to measure before the defect may be called fixed.

## Did you use Tavily?

**Yes.** Tavily is called at runtime before each repair attempt, and the references are stored on the attempt: 7 [API-REPORTED] attempts consulted and 21 [API-REPORTED] references in the last gate. The honest sentence: the model never cited any of them (0 [API-REPORTED] citations), the record says so on every attempt, and that defect (D-21) is open.

## Is this a new project or an existing one?

<!-- OWNER TO ANSWER: left blank on purpose -->
