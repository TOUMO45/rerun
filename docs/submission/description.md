# Devpost project description and tagline

Same evidence rule as everywhere else: every number is in the REPLAY JSON and carries its tag.

## Tagline

RERUN is a reproducibility auditor that runs a paper's code in a Nebius Token Factory sandbox and signs what actually happened. Its headline is a measured negative: across every exploratory gate entry-run, 2 [API-REPORTED] of 20 [API-REPORTED] ended RUNS_CLEAN or RUNS_AFTER_REPAIR, none to completion and no gate passed, and every number traces to a record.

## Description

**The problem.** Research code rots. A reviewer or lab that picks up a paper's repository often finds it no longer runs. The tempting answer is to let an LLM patch it until it does. But a patched run that "works" may have deleted the evaluation, swallowed the error or shrunk the data, and nobody measures how often the repair is real.

**What RERUN does.** It runs a repository's documented command at its pinned commit in a Nebius Token Factory sandbox. Deterministic rules classify failures and rebuild the repository's era. NVIDIA Nemotron models then work in narrow roles: Nano finds the entrypoint or abstains, Super proposes repairs, Ultra chooses between candidates and writes the certificate, and may only downgrade a verdict. A tamper gate vets every proposal, and a cost guard stops what it cannot fund: the run ends INDETERMINATE, an abstention. Each run becomes a hashed passport anyone can rebuild.

**What we measured.** We pre-registered the test: 0 [API-REPORTED] of 16 [API-REPORTED] repositories recovered with repair on. We fixed what the records showed and ran more gates, all labelled EXPLORATORY because none passed its own criteria. Across every gate entry-run, 2 [API-REPORTED] of 20 [API-REPORTED] ended RUNS_CLEAN or RUNS_AFTER_REPAIR: one a smoke-limit artefact from the time machine alone, the other a smoke-criterion pass after model-proposed environment changes were adopted. It ran for the smoke limit without failing; it is one entry-run, not a rate.

**What the last gate found about us.** The sandbox VM has 3.85 [DERIVED] GiB of memory and killed one entry; the harness read the kernel's own log. And the SDK cuts each output stream at a fixed limit that we never checked, which may have hidden an error for several versions (D-41, not proven).

**Why that is the product.** Researchers are starting to trust LLM-patched reproductions. RERUN shows what that trust was worth here: 61 [API-REPORTED] passports, 41 [API-REPORTED] defects in our own harness with the rule that calls each fixed or open, and a ledger of $22.4935 [ESTIMATED], a lower bound. That ledger is the sandbox API's reported operation cost; the account balance showed at most $0.43 [BILLED] charged, and the two are not reconciled (D-36, open). Every number carries a tag and links to its record; a static dashboard shows all of it offline.

**What is next.** Fixing D-41 changes sealed code and needs a new seal and gate. Nothing is called fixed without a gate line that shows it.
