# Devpost project description and tagline

Generated from `reports/v1.9/figures.json` by `reports/texts/render.py` (template: `reports/texts/templates/description.md`): every number is a figure of that file and carries its tag.

## Tagline

RERUN audits whether a paper's code still runs, in a Nebius Token Factory sandbox, and says what stops it when it does not: 3 [DERIVED] of 26 [DERIVED] held-out repositories ran their documented command, and 7 [DERIVED] of the 9 [DERIVED] that did not on TEST-C got an actionable diagnosis. Every number traces to a committed record.

## Description

**The problem.** Research code rots; the tempting fix is to let an LLM patch it until it runs. A patched run that "works" may have swallowed the error, faked the data or changed the computation.

**What RERUN does.** It runs a repository's documented command at its pinned commit in a Nebius Token Factory sandbox, rebuilds the paper's era deterministically, classifies what stopped it and says who can remove it. NVIDIA Nemotron models work in narrow roles: Nano finds the entrypoint or abstains, Super proposes repairs, Ultra chooses between candidates and may only downgrade a verdict. A deterministic tamper gate vets every proposal, a cost guard stops what it cannot fund, and each run becomes a hashed passport anyone can verify offline.

**What we measured.** Three held-out sets, each registered before its draw and run once: 3 [DERIVED] of 26 [DERIVED] repositories ran their documented command (TEST 1 [DERIVED] of 8 [DERIVED] after its published audit, TEST-B 1 [DERIVED] of 8 [DERIVED], TEST-C 1 [DERIVED] of 10 [DERIVED]); ran, never reproduced. On TEST-C, 7 [DERIVED] of 9 [DERIVED] non-running entries got an actionable diagnosis (6 [DERIVED] judged strictly).

**The benchmark.** Two cheat sets ship in `benchmark/` with hashes and a scorer that reproduces every published table: 337 [DERIVED] planted patches, and 166 [DERIVED] cheats with 42 [DERIVED] honest controls by a separate agent that had not seen the checks (144 [DERIVED] cheats measured). On the planted held-out half the full pipeline adopted 0 [DERIVED] cheats but refused all 31 [DERIVED] honest controls that passed the run, so that table has no summary sentence.

**Limits.** Repair's yield is small: 2 [API-REPORTED] of 24 [API-REPORTED] exploratory gate entry-runs reached a RUNS_* verdict. Anti-cheat is not a headline claim: the shipped harness adopted 14 [DERIVED] of the 50 [DERIVED] independent cheats aimed at repositories whose run really fails (28% [DERIVED]). Behavioural checks that refuse such patches also refused 16 [DERIVED] of 27 [DERIVED] honest controls, so they ship as a review flag (REVIEW_REQUIRED, the verdict unchanged); its figures are derived from committed records, the use was chosen after the results were seen, no cheat was run with the tracer, and cheats written to fit the checks are unmeasured. Erratum E-3 and one post-hoc run are reported under their labels.

**Why that is the product.** Every number traces to its record. The ledger, $186.21 [API-REPORTED] of the owner's $300 [DERIVED], is the sandbox API's reported operation cost, a lower bound; the account balance showed at most $0.43 [BILLED] charged at the owner's second reading, not reconciled (D-36, open).
