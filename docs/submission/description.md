# Devpost project description and tagline

Same evidence rule as everywhere else: every number is in the REPLAY JSON and carries its tag.

## Tagline

RERUN is a reproducibility auditor that runs a paper's code in a Nebius Token Factory sandbox and signs what actually happened. Its headline is a measured negative: across every exploratory gate entry-run, 2 [API-REPORTED] of 24 [API-REPORTED] reached a RUNS_* verdict, none to completion and no gate passed, and every number traces to a record.

## Description

**The problem.** Research code rots, and the tempting fix is to let an LLM patch it until it runs. But a patched run that "works" may have deleted the evaluation, swallowed the error or shrunk the data, and nobody measures how often the repair is real.

**What RERUN does.** It runs a repository's documented command at its pinned commit in a Nebius Token Factory sandbox. Deterministic rules classify failures and rebuild the repository's era. NVIDIA Nemotron models work in narrow roles: Nano finds the entrypoint or abstains, Super proposes repairs, Ultra chooses between candidates and may only downgrade a verdict. A tamper gate vets every proposal and a cost guard stops what it cannot fund. Each run becomes a hashed passport anyone can rebuild.

**What we measured.** We pre-registered the test: 0 [API-REPORTED] of 16 [API-REPORTED] repositories reached RUNS_AFTER_REPAIR with repair on. We fixed what the records showed and ran more gates, all labelled EXPLORATORY because none passed its criteria. Across every gate entry-run, 2 [API-REPORTED] of 24 [API-REPORTED] ended RUNS_CLEAN or RUNS_AFTER_REPAIR: one a smoke-limit artefact from the time machine alone, the other a smoke-criterion pass after model-proposed environment changes were adopted. It ran for the smoke limit without failing; it is one entry-run, not a rate, and it did not repeat in the final gate.

**What the last gates found about us.** The sandbox VM has 3.85 [DERIVED] GiB of memory and killed one entry. The SDK cut each output stream at a fixed limit we never checked; a probe confirmed it hid a CUDA error for several versions, and the final gate read that stream whole (D-41, fixed). That gate's process was killed twice by its environment and resumed (D-43, open).

**Why that is the product.** RERUN shows what trust in LLM-patched reproductions was worth here: 65 [API-REPORTED] passports, 43 [API-REPORTED] defects in our own harness with the rule that calls each fixed or open, and a ledger of $29.1704 [ESTIMATED], a lower bound. That ledger is the sandbox API's reported operation cost; the account balance showed at most $0.43 [BILLED] at the owner's last reading, and the two are not reconciled (D-36, open). Every number carries a tag and links to its record.

**What is next.** All live work has stopped. Nothing is called fixed without a gate line that shows it: the sustained-run line (D-42) never ran live.
