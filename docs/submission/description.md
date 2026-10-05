# Devpost project description and tagline

Same evidence rule as everywhere else: every number is in the REPLAY JSON and carries its tag.

## Tagline

RERUN is a reproducibility auditor that runs a paper's code in a Nebius Token Factory sandbox and signs what actually happened. Its headline is a measured negative: across every exploratory gate entry-run, 2 [API-REPORTED] of 24 [API-REPORTED] reached a RUNS_* verdict, none to completion and no gate passed, and every number traces to a record.

## Description

**The problem.** Research code rots, and the tempting fix is to let an LLM patch it until it runs. But a patched run that "works" may have deleted the evaluation, swallowed the error or shrunk the data, and nobody measures how often the repair is real.

**What RERUN does.** It runs a repository's documented command at its pinned commit in a Nebius Token Factory sandbox. Deterministic rules classify failures and rebuild the repository's era. NVIDIA Nemotron models work in narrow roles: Nano finds the entrypoint or abstains, Super proposes repairs, Ultra chooses between candidates and may only downgrade a verdict. A tamper gate vets every proposal and a cost guard stops what it cannot fund. Each run becomes a hashed passport anyone can rebuild.

**What we measured.** Pre-registered: 0 [API-REPORTED] of 16 [API-REPORTED] repositories reached RUNS_AFTER_REPAIR with repair on. Every later gate is labelled EXPLORATORY; none passed. Across their entry-runs, 2 [API-REPORTED] of 24 [API-REPORTED] ended RUNS_*: a smoke-limit artefact, and a smoke-criterion pass that did not repeat: one entry-run, not a rate.

**What the gates found about us.** The SDK cut each output stream at a fixed limit we never checked; a probe showed it hid a CUDA error for several versions (D-41, fixed).

**Why that is the product.** RERUN shows what trust in LLM-patched reproductions was worth here: 65 [API-REPORTED] passports, 43 [API-REPORTED] defects in our own harness, each called fixed or open by rule, and a ledger that is a stated lower bound: the sandbox API's reported operation cost, while the account balance showed at most $0.43 [BILLED] charged at the owner's second reading (before the last gates), and the two are not reconciled (D-36, open). Every number carries a tag and links to its record.

**The DEV rounds.** A pre-registered dev/test protocol followed. Over five rounds on the eight tuned-on entries, RUNS_* verdicts went 1 [DERIVED], 2 [DERIVED], 3 [DERIVED], 3 [DERIVED], 3 [DERIVED] of 8 [DERIVED]; the loop stopped by its own rule. Of the last three, two passed on deterministic steps, one on a model-proposed change the tamper gate admitted: 60 s smoke verdicts, not reproduced results. Every rule that changes what runs is labelled on the certificate (`dependency change: torchvision 0.5.0->0.4.0, Pillow 9.0.0->6.2.2`).

**What is next.** The primary measure, a TEST phase on eight untouched entries with sustained-run confirmation (D-42), has not run.
