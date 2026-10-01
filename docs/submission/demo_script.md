# RERUN — demo video script

Length: under three minutes. Everything on screen is a recorded artifact from this repository: the static dashboard, the REPLAY files,
a passport, and a committed sandbox log from the seal verification. Nothing is run live and no Nebius call is made for the video.
Whether one short screen-recorded live run is added is the owner's decision at D6.

Before recording: `python -m phase_d.build_dashboard --check` must print that the stored page is identical to a rebuild.
Open `reports/phase-d/dashboard/index.html` from disk. Record at one zoom level; do not edit numbers on screen.
The tags in square brackets are shown on screen and are not read aloud.

Track: Coding and agentic engineering. Models named on screen are read from the dashboard's "How it ran, as recorded" section.

## Timeline

| Time | Shown (file or page, and where) | On-screen text | Spoken |
|---|---|---|---|
| 0:00–0:10 | Title card, then `reports/phase-d/dashboard/index.html` at the top | RERUN: a reproducibility auditor that produces evidence | A paper is published with its code. Later, someone tries to run it, and it does not run. |
| 0:10–0:25 | `reports/phase-d/dashboard/index.html`, header and tag legend | Who needs to know: reviewers, replication teams, labs. Tags: MEASURED, ESTIMATED, DERIVED | Reviewers, replication teams and labs need to know whether it runs. Increasingly they are told an AI fixed it. A wrong "it works" costs weeks and puts an unverified result into the literature. RERUN measures what that claim is worth. |
| 0:25–0:36 | `reports/phase-d/dashboard/index.html#stack`, the sandbox line | Sandbox backend `token_factory`, as recorded | RERUN clones a repository at its pinned commit and runs its documented command inside a Nebius Token Factory sandbox. That run is the baseline. |
| 0:36–0:50 | `reports/phase-d/dashboard/index.html#stack`, the role table | Nano: recon. Super: planner and repairer. Ultra: adjudicator | Nemotron models have separate, narrow jobs. Nano finds the entrypoint or abstains. Super plans system packages and proposes repairs. Ultra writes the certificate and may only downgrade a verdict. |
| 0:50–1:05 | `reports/phase-d/dashboard/index.html#entries`, entry `07` of `harness-v1.3.4`, opened | Baseline, era lock, attempts, verdict, passport | Failures are classified by deterministic rules, not by a model. A deterministic time machine rebuilds the repository's own era. Every model proposal must pass a tamper gate. When RERUN cannot decide it says INDETERMINATE, and every run ends in a hashed passport. |
| 1:05–1:17 | Same entry, the timeline: baseline and era lock | Era lock: Python `3.8`, lock ok `true` | This is entry 7 [MEASURED] of the last gate. Numpy is missing at baseline. The time machine locks a 2020 [MEASURED] environment on Python 3.8 [MEASURED], and that error is gone. |
| 1:17–1:33 | Same entry, the attempts and the verdict | Consulted 3 MEASURED per attempt; cited: not recorded | The model then proposes changes, and each meets a new error, ending with a missing compiler that it tried to install as a Python package. Before each attempt RERUN searched Tavily and recorded 3 [MEASURED] references. The model cited none. |
| 1:33–1:41 | Same entry, the cost block and its operations list | $0.7366 MEASURED; each spend line DERIVED with its quoted source | Every number carries a tag. This spend line is DERIVED from the quoted cost-guard line beside it. The entry cost $0.7366 [MEASURED]. |
| 1:41–1:50 | `reports/phase-d/dashboard/index.html#entries`, entry `08` of `harness-v1.3.4`, the kill box and the cost line | Killed at second 55 DERIVED. $0.3939 MEASURED + $0.2842 ESTIMATED | One entry further, the cost guard stopped an operation at its funded limit of 55 [DERIVED] seconds. Its cost is shown in two parts: $0.3939 [MEASURED] and $0.2842 [ESTIMATED]. |
| 1:50–2:01 | `reports/phase-d/dashboard/index.html#scorecard`, the anchor card | Pre-registered: recovered 0 MEASURED of 16 MEASURED | Now the result. On the pre-registered run, with repair switched on, RERUN recovered 0 [MEASURED] of 16 [MEASURED] repositories. |
| 2:01–2:13 | `reports/phase-d/dashboard/index.html#scorecard`, the two EXPLORATORY cards | EXPLORATORY, did not pass its pre-registered gate | We fixed what the records showed and ran again, twice. Both runs failed their own pre-registered gate, and the page says EXPLORATORY above the numbers. |
| 2:13–2:23 | `reports/phase-d/dashboard/index.html#headline` | 0 MEASURED of 8 MEASURED | Across those gates the LLM repair loop recovered 0 [MEASURED] of 8 [MEASURED] entry-runs. The one apparent recovery was a smoke-limit artefact, produced by the time machine alone. |
| 2:23–2:30 | `reports/phase-d/dashboard/index.html#defects` | Defect register: status, rule, quoted basis | The instrument also reports on itself: 28 [MEASURED] defects, each with a status and a quoted basis. |
| 2:30–2:42 | `reports/phase-d/dashboard/index.html#ledger` | $9.8507 MEASURED + $0.2842 ESTIMATED, lower bound | Why it matters: people are starting to trust reproductions patched by an LLM. Measured, that trust bought no recovery by the repair loop, at a recorded cost of $10.1349 [ESTIMATED], a lower bound. |
| 2:42–2:50 | `docs/design/D-23.md`, then `docs/design/D-25.md` | Open defects with costed design notes | What is next is written down and costed: two open defects have design notes that say what a validating gate must measure. |
| 2:50–3:00 | `runs/sandbox_verification/final-v1.3.4/smoke_alive_py310.json`, then `README.md` | `python -m phase_d.build_dashboard` | The sandbox logs are committed, the code is under the Apache licence, and one command rebuilds this dashboard offline from the committed records. |

## Evidence for every spoken sentence that contains a number

Field paths are passport fields unless they start with `summary.json`, which is `reports/phase-d/replay/summary.json`.

| # | Spoken sentence | Number and tag | Passport or record |
|---|---|---|---|
| C1 | This is entry 7 [MEASURED] of the last gate. | 7 MEASURED (`entry.id` is `07`) | `harness-v1.3.4/treatment/07@6bd614a2a0447ead7e9dc6007b6fe868a29af9660ed175ddf667e08f74673a98` |
| C2 | The time machine locks a 2020 [MEASURED] environment on Python 3.8 [MEASURED], and that error is gone. | 2020 MEASURED (`time_machine_actions[0].era.date`), 3.8 MEASURED (`time_machine_actions[0].python.version`); the first link of `classification_chain` is cleared by `attempt-0` | `harness-v1.3.4/treatment/07@6bd614a2a0447ead7e9dc6007b6fe868a29af9660ed175ddf667e08f74673a98` |
| C3 | Before each attempt RERUN searched Tavily and recorded 3 [MEASURED] references. | 3 MEASURED (`attempts[1].consulted_count`, and the same on `attempts[2]`, `attempts[3]`); `cited` is null on every attempt | `harness-v1.3.4/treatment/07@6bd614a2a0447ead7e9dc6007b6fe868a29af9660ed175ddf667e08f74673a98` |
| C4 | The entry cost $0.7366 [MEASURED]. | 0.7366 MEASURED (`cost`, shown with four decimals) | `harness-v1.3.4/treatment/07@6bd614a2a0447ead7e9dc6007b6fe868a29af9660ed175ddf667e08f74673a98` |
| C5 | One entry further, the cost guard stopped an operation at its funded limit of 55 [DERIVED] seconds. | 55 DERIVED (`attempts[0].execution.funded_seconds`, with its quoted event line) | `harness-v1.3.4/treatment/08@cf7e86f9580bb99147920b33d6481c61f55506e979bb75ee354527a6e2610bf9` |
| C6 | Its cost is shown in two parts: $0.3939 [MEASURED] and $0.2842 [ESTIMATED]. | 0.3939 MEASURED (`cost.measured`), 0.2842 ESTIMATED (`cost.estimated`) | `harness-v1.3.4/treatment/08@cf7e86f9580bb99147920b33d6481c61f55506e979bb75ee354527a6e2610bf9` |
| C7 | On the pre-registered run, with repair switched on, RERUN recovered 0 [MEASURED] of 16 [MEASURED] repositories. | 0 MEASURED (`badge.figures[0].recovered`), 16 MEASURED (`badge.figures[0].denominator`) | `harness-v1.3.2/treatment/01@fecb8efd3d440fdedb29aae428abced2e511480ac673405aa55f8a5d7f5ffaf6` |
| C8 | Across those gates the LLM repair loop recovered 0 [MEASURED] of 8 [MEASURED] entry-runs. | 0 MEASURED (`summary.json` `headline.recovered_by_llm_loop`), 8 MEASURED (`summary.json` `headline.gate_entry_runs`) | `summary.json`; the apparent recovery is `harness-v1.3.3/treatment/11@619a97784e6abc3f29fedf36a7c4723c65232111233a34e3299a1ed3eee034a2` with annotation `ENTRY-11-SMOKE-LIMIT-ARTEFACT` |
| C9 | The instrument also reports on itself: 28 [MEASURED] defects, each with a status and a quoted basis. | 28 MEASURED (`summary.json` `inventory.defects`) | `summary.json` `defects.rows` |
| C10 | Measured, that trust bought no recovery by the repair loop, at a recorded cost of $10.1349 [ESTIMATED], a lower bound. | 10.1349 ESTIMATED (`summary.json` `ledger.total`) = 9.8507 MEASURED (`ledger.measured`) + 0.2842 ESTIMATED (`ledger.estimated`); lower bound per D-27 | `summary.json` `ledger`; the estimate is from `harness-v1.3.4/treatment/08@cf7e86f9580bb99147920b33d6481c61f55506e979bb75ee354527a6e2610bf9` |

## Statements without a number, and where they are shown

| Statement | Where it is shown |
|---|---|
| The documented command runs in a Nebius Token Factory sandbox | `reports/phase-d/replay/summary.json`, `stack.versions[].sandbox.backend` |
| Which Nemotron model has which job | `reports/phase-d/replay/summary.json`, `stack.versions[].roles` (model names as the records store them) |
| Classification is deterministic | `backend/app/services/classifier.py` (no model call in the module) |
| Every model proposal passes a gate before it is applied | the `gate_decision` and `outcome` of each attempt in every passport; a rejected one is `attempts[3]` of `harness-v1.3.4/treatment/03@937744fe7a07e901961158d15fcb31bba204d9d214ef0ebb9624442b7fcc0544` |
| The model tried to install the compiler as a Python package | `attempts[3].change.env_delta` of the entry shown; defect D-24 |
| The model cited none of the references | `cited` is null on every attempt of every passport; defect D-21 is open |
| Both exploratory runs failed their own gate | `badge.gate_passed` is `false` on every passport of `harness-v1.3.3` and `harness-v1.3.4` |
| The apparent recovery came from the time machine alone | `summary.json` `headline.recoveries_by_time_machine_alone`; that record has no model attempt |
| Two open defects have costed design notes | `docs/design/D-23.md`, `docs/design/D-25.md` |

## What the script must not say

- Never say that the repair loop, a model or Nemotron recovered, repaired or fixed an entry: none did, in any record.
- Never say that the time machine recovered an entry: it rebuilds environments and clears dependency errors, and the one run it left looking recovered was a smoke-limit artefact.
- Never say a number that is not in the evidence table above.
