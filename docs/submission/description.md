# Devpost project description and tagline

Same evidence rule as everywhere else: every number is in the REPLAY JSON and carries its tag.

## Tagline

RERUN is a reproducibility auditor that runs a paper's code in a Nebius Token Factory sandbox and signs what actually happened. Its headline is a measured negative: under a pre-registered gate, the Nemotron repair loop recovered 0 [API-REPORTED] of 8 [API-REPORTED] entry-runs, and every number traces to a record.

## Description

**The problem.** Research code rots. A reviewer, a replication team or a lab that picks up a paper's repository often finds it no longer runs. The tempting answer is to let an LLM patch it until it does. But a patched run that "works" may have deleted the evaluation, swallowed the error or shrunk the data, and nobody measures how often the repair is real.

**What RERUN does.** It clones a repository at its pinned commit and runs its documented command in a Nebius Token Factory sandbox. A deterministic classifier names the failure. A deterministic time machine rebuilds the environment of the repository's own era. Then NVIDIA Nemotron models work in narrow roles: Nano finds the entrypoint or abstains, Super proposes repairs, Ultra writes the certificate and may only downgrade a verdict. Every proposal must pass a deterministic tamper gate. A cost guard stops what it cannot fund, and the run then ends INDETERMINATE: an abstention, not a guess. Each run becomes a hashed passport that anyone can rebuild from the committed record.

**What we measured.** We pre-registered the test, then ran it. With repair switched on, 0 [API-REPORTED] of 16 [API-REPORTED] repositories recovered. We fixed what the records showed and ran two more gates, both labelled EXPLORATORY because both failed their own pre-registered criteria. Across them the LLM repair loop recovered 0 [API-REPORTED] of 8 [API-REPORTED] entry-runs; the one apparent recovery was a smoke-limit artefact produced by the time machine alone. Tavily was searched before repair attempts, with 21 [API-REPORTED] references recorded in the last gate, and the model cited none.

**Why that is the product.** Researchers are starting to trust reproductions patched by an LLM. RERUN shows what that trust was worth here, with the evidence attached: 49 [API-REPORTED] passports, a replay of every run, a register of 28 [API-REPORTED] defects in our own harness with the rule used to call each one fixed or open, and a cost ledger of $10.1349 [ESTIMATED], stated as a lower bound. That ledger is the sandbox API's reported operation cost; the account balance showed at most $0.39 [BILLED] charged, and the two are not reconciled (D-36, open). Every number carries a tag (API-REPORTED, ESTIMATED, DERIVED or BILLED) and links to its record. A static dashboard shows all of it offline, rebuilt by one command.

**What is next.** Two open defects have costed design notes that say what a validating gate must measure. Nothing is called fixed without one.
