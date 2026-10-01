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
| 0:10–0:25 | `reports/phase-d/dashboard/index.html`, header and tag legend | Who needs to know: reviewers, replication teams, labs. Tags: API-REPORTED, ESTIMATED, DERIVED, BILLED | Reviewers and replication teams need to know whether it runs, and increasingly they are told an AI fixed it. A wrong "it works" costs weeks. RERUN measures what that claim is worth. |
| 0:25–0:36 | `reports/phase-d/dashboard/index.html#stack`, the sandbox line | Sandbox backend `token_factory`, as recorded | RERUN clones a repository at its pinned commit and runs its documented command inside a Nebius Token Factory sandbox. |
| 0:36–0:50 | `reports/phase-d/dashboard/index.html#stack`, the role table | Nano: recon. Super: planner and repairer. Ultra: adjudicator | Nemotron models have separate, narrow jobs. Nano finds the entrypoint or abstains. Super plans system packages and proposes repairs. Ultra chooses between candidate repairs and writes the certificate, and may only downgrade a verdict. |
| 0:50–1:05 | `reports/phase-d/dashboard/index.html#entries`, entry `07` of `harness-v1.4.2`, opened | Baseline, era lock, candidate attempts, verdict, passport | Failures are classified by deterministic rules. A deterministic time machine rebuilds the repository's own era. Every model proposal must pass a tamper gate, and every run ends in a hashed passport. |
| 1:05–1:17 | Same entry, the timeline: baseline and era lock | Era lock: Python `3.8`, lock ok `true` | This is entry 7 [API-REPORTED] of the latest gate. Numpy is missing at baseline. The time machine locks a 2020 [API-REPORTED] environment on Python 3.8 [API-REPORTED], and that error is gone. |
| 1:17–1:33 | Same entry, the candidate attempts and the verdict | Second round: adopted_reason `partial progress`. Third round: exit code `0`, outcome `alive_at_limit` | Then the model proposes three candidates a round. In the second round the adjudicator picks none, and RERUN adopts the one that got furthest. In the third, one added package lets the command run for the smoke limit without failing. |
| 1:33–1:41 | Same entry, the verdict and the cost block | Verdict `RUNS_AFTER_REPAIR`, annotation `SMOKE-CRITERION-RECOVERY`. $1.1809 API-REPORTED | The verdict says RUNS_AFTER_REPAIR, under a smoke criterion: the command ran for the smoke limit, not to the end. The entry cost $1.1809 [API-REPORTED]. |
| 1:41–1:50 | `reports/phase-d/dashboard/index.html#entries`, entry `11` of `harness-v1.4.2`, the rule step `resource_evidence` | Out of memory: Killed process (kernel log). Verdict `INDETERMINATE`, taxonomy `RESOURCE_LIMIT` | One entry further, the sandbox killed the process, and one evidence run read the kernel's own log from inside: out of memory, on a VM with 3.85 [DERIVED] gigabytes of it. |
| 1:50–2:01 | `reports/phase-d/dashboard/index.html#scorecard`, the anchor card | Pre-registered: recovered 0 API-REPORTED of 16 API-REPORTED | On the pre-registered run, with repair switched on, RERUN recovered 0 [API-REPORTED] of 16 [API-REPORTED] repositories. |
| 2:01–2:13 | `reports/phase-d/dashboard/index.html#scorecard`, the EXPLORATORY cards | EXPLORATORY, did not pass its pre-registered gate | We fixed what the records showed and ran again. No gate passed its own criteria, and the page says EXPLORATORY above the numbers. |
| 2:13–2:23 | `reports/phase-d/dashboard/index.html#headline` | 2 API-REPORTED of 20 API-REPORTED | Across every gate entry-run, 2 [API-REPORTED] of 20 [API-REPORTED] ended RUNS_CLEAN or RUNS_AFTER_REPAIR. One was a smoke-limit artefact, from the time machine alone. The other is the smoke-criterion pass we just saw, not a finished run. |
| 2:23–2:30 | `reports/phase-d/dashboard/index.html#defects` | Defect register: status, rule, quoted basis | The instrument also reports on itself: 41 [API-REPORTED] defects, each with a status and a quoted basis. |
| 2:30–2:42 | `reports/phase-d/dashboard/index.html#ledger` | $21.3218 API-REPORTED + $1.1717 ESTIMATED, lower bound. Account balance reading: at most $0.43 BILLED | Why it matters: people are starting to trust reproductions patched by an LLM. Measured, that trust bought no passed gate, at an API-reported cost of $22.4935 [ESTIMATED], a lower bound. The account balance showed at most $0.43 [BILLED] charged; the two are not reconciled. |
| 2:42–2:50 | `reports/corpus-v2.1/v1.4.2/gate/GATE_REPORT_v1.4.2.md`, the section on D-41 | Open, not proven: the SDK truncates output | The last gate also found a flaw in our own harness: the SDK cuts each output stream at a fixed limit, and we never looked. It may have hidden an error for several versions. Open, not proven. |
| 2:50–3:00 | `runs/sandbox_verification/v1.4.2-seal/run1_A_ready_image.json`, then `README.md` | `python -m phase_d.build_dashboard` | The sandbox logs are committed, the code is under the Apache licence, and one command rebuilds this dashboard offline from the committed records. |

## Evidence for every spoken sentence that contains a number

Field paths are passport fields unless they start with `summary.json`, which is `reports/phase-d/replay/summary.json`.

| # | Spoken sentence | Number and tag | Passport or record |
|---|---|---|---|
| C1 | This is entry 7 [API-REPORTED] of the latest gate. | 7 API-REPORTED (`entry.id` is `07`) | `harness-v1.4.2/treatment/07@4688f3c38b3f8efa48b5e3ace9f26bdc246a42e0fcf2e1fa315ca068d0fda40a` |
| C2 | The time machine locks a 2020 [API-REPORTED] environment on Python 3.8 [API-REPORTED], and that error is gone. | 2020 API-REPORTED (`time_machine_actions[0].era.date`), 3.8 API-REPORTED (`time_machine_actions[0].python.version`); the first link of `classification_chain` is cleared by `attempt-0` | `harness-v1.4.2/treatment/07@4688f3c38b3f8efa48b5e3ace9f26bdc246a42e0fcf2e1fa315ca068d0fda40a` |
| C3 | The entry cost $1.1809 [API-REPORTED]. | 1.1809 API-REPORTED (`cost`, shown with four decimals) | `harness-v1.4.2/treatment/07@4688f3c38b3f8efa48b5e3ace9f26bdc246a42e0fcf2e1fa315ca068d0fda40a` |
| C4 | One entry further, the sandbox killed the process, and one evidence run read the kernel's own log from inside: out of memory, on a VM with 3.85 [DERIVED] gigabytes of it. | 3.85 DERIVED (`attempts[2].rule_step.limit_quote`, the harness's own quote of `rule_step.evidence.mem_total_kb`; the kernel line is in `rule_step.evidence.dmesg`) | `harness-v1.4.2/treatment/11@b266a0a92abce48d206fa8512843f10f9a7eb6a9a4577f6a8c21962c70feeb8e` |
| C5 | On the pre-registered run, with repair switched on, RERUN recovered 0 [API-REPORTED] of 16 [API-REPORTED] repositories. | 0 API-REPORTED (`badge.figures[0].recovered`), 16 API-REPORTED (`badge.figures[0].denominator`) | `harness-v1.3.2/treatment/01@fecb8efd3d440fdedb29aae428abced2e511480ac673405aa55f8a5d7f5ffaf6` |
| C6 | Across every gate entry-run, 2 [API-REPORTED] of 20 [API-REPORTED] ended RUNS_CLEAN or RUNS_AFTER_REPAIR. | 2 API-REPORTED (`summary.json` `headline.apparent_recoveries`), 20 API-REPORTED (`summary.json` `headline.gate_entry_runs`) | `summary.json`; the artefact is `harness-v1.3.3/treatment/11@619a97784e6abc3f29fedf36a7c4723c65232111233a34e3299a1ed3eee034a2` (annotation `ENTRY-11-SMOKE-LIMIT-ARTEFACT`), the smoke-criterion pass is `harness-v1.4.2/treatment/07@4688f3c38b3f8efa48b5e3ace9f26bdc246a42e0fcf2e1fa315ca068d0fda40a` (annotation `SMOKE-CRITERION-RECOVERY`) |
| C7 | The instrument also reports on itself: 41 [API-REPORTED] defects, each with a status and a quoted basis. | 41 API-REPORTED (`summary.json` `inventory.defects`) | `summary.json` `defects.rows` |
| C8 | Measured, that trust bought no passed gate, at an API-reported cost of $22.4935 [ESTIMATED], a lower bound. | 22.4935 ESTIMATED (`summary.json` `ledger.total`) = 21.3218 API-REPORTED (`ledger.measured`) + 1.1717 ESTIMATED (`ledger.estimated`); lower bound per D-27 | `summary.json` `ledger`; the estimates are from the killed-step records listed in `ledger.kill_records` |
| C9 | The account balance showed at most $0.43 [BILLED] charged; the two are not reconciled. | 0.43 BILLED (`summary.json` `ledger.billed.account`): the owner's second reading of the Nebius account balance page, not an API cost; the API-reported ledger is `summary.json` `ledger`, and the two are not reconciled (D-36, open) | `summary.json` `ledger.billed`; the first reading and the one gate interval that holds both are in `ledger.billed.readings` and `ledger.billed.gates` |

## Statements without a number, and where they are shown

| Statement | Where it is shown |
|---|---|
| The documented command runs in a Nebius Token Factory sandbox | `reports/phase-d/replay/summary.json`, `stack.versions[].sandbox.backend` |
| Which Nemotron model has which job | `reports/phase-d/replay/summary.json`, `stack.versions[].roles` (model names as the records store them); the adjudicator's candidate choice is `attempts[].adjudication` of the entry shown |
| Classification is deterministic | `backend/app/services/classifier.py` (no model call in the module) |
| Every model proposal passes a gate before it is applied | the `gate_decision` and `outcome` of each attempt in every passport; a rejected one is `attempts[3]` of `harness-v1.3.4/treatment/03@937744fe7a07e901961158d15fcb31bba204d9d214ef0ebb9624442b7fcc0544` |
| In the second round the adjudicator picks none and RERUN adopts the candidate that got furthest; in the third one added package lets the command run for the smoke limit | `attempts[]` of the entry shown: the first round has no qualifying candidate and the failure does not move; `attempt-2-candidate-2` has `adjudication.adopted_reason` `partial progress`; `attempt-3-candidate-1` has `chosen` true, exit code zero and `execution.outcome` `alive_at_limit`, and its `change.env_delta` adds one package |
| The verdict is RUNS_AFTER_REPAIR under a smoke criterion | `verdict.verdict` and the annotation `SMOKE-CRITERION-RECOVERY` of the entry shown; the badge figure `a` carries the same note |
| The sandbox killed the process and the harness read the kernel's log | `verdict.taxonomy_code` `RESOURCE_LIMIT`, `attempts[].rule_step.evidence.dmesg` and `kill_evidenced` of `harness-v1.4.2/treatment/11@b266a0a92abce48d206fa8512843f10f9a7eb6a9a4577f6a8c21962c70feeb8e` |
| No gate passed | `badge.gate_passed` is `false` on every passport of every exploratory version |
| One apparent recovery was a smoke-limit artefact from the time machine alone | `summary.json` `headline.recoveries_by_time_machine_alone` and `headline.apparent_recoveries_annotated_as_artefact`; that record has no model attempt |
| The SDK cuts each output stream at a fixed limit, we never looked, and it may have hidden an error for several versions; open, not proven | register row D-41 (`summary.json` `defects.rows`), the D-41 annotation on the silent-exit entry's passport of each version, and `reports/corpus-v2.1/v1.4.2/gate/GATE_REPORT_v1.4.2.md` |

## What the script must not say

- Never say that the repair loop, a model or Nemotron "recovered" an entry as a finding. The one RUNS_AFTER_REPAIR of the root-cause gates is a smoke-criterion pass after model-proposed environment changes were adopted: say exactly that, once, as one entry-run and not a rate.
- Never say that the time machine recovered an entry: it rebuilds environments and clears dependency errors, and the one run it left looking recovered earlier was a smoke-limit artefact.
- Never call the smoke-criterion pass a completed run, a success of the repair loop, or a reproduction of a paper's result.
- Never state D-41 as established: it is indicated by the records and not proven.
- Never say a number that is not in the evidence table above.
