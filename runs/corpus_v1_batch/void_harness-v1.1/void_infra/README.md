# Re-queued INFRA_ERROR records — corpus-v1 on harness-v1.1

Operational rule (METHODOLOGY.md, "Re-queue rule for INFRA_ERROR"): an entry that
ended INFRA_ERROR **with no baseline execution** is re-queued, at most 2 times; after
that it stays INFRA_ERROR permanently and is excluded from the denominator.

| # | Entry | Result | Baseline | Re-queue |
|---|---|---|---|---|
| 5 | expressGNN/ExpressGNN | INFRA_ERROR:sandbox:ApiTimeoutError (upload read timeout, 4 attempts) | NOT_RUN | **attempt 1 of 2** |
| 6 | mlohaus/SearchFair | INFRA_ERROR:sandbox:ApiTimeoutError (upload read timeout, 4 attempts) | NOT_RUN | **attempt 1 of 2** |

Nothing of either repository ran (the Nebius sandbox upload endpoint timed out; the
circuit breaker then stopped the batch, 2026-09-28). A live smoke upload succeeded
minutes later. These records are kept unmodified as evidence; the resumed batch runs
both entries again on the same tag (harness-v1.1). They are not counted anywhere.
