# BILLED readings (the owner's account balance), kept beside the API-reported ledger

The ledger of every v1.x report is the sandbox API's own reported cost (API-REPORTED, with ESTIMATED parts for stopped steps; D-27, D-36). It is not what the account is billed. The only
source of BILLED figures is a balance the owner reads off the account page and reports in chat. A reading is a point in time: it cannot be split between runs that happened between two
readings.

| reading | when | balance | billed since the previous reading | note |
|---|---|---|---|---|
| (earlier) | 2026-10-01 19:37 local | account at most $0.39 cumulative | | before the v1.4.1 gate |
| after the v1.4.1 gate | 2026-10-01 | $49.57 | $0.04 | at most $0.43 cumulative: a $50.00 start is inferred from these readings, not stated |
| after DEV round 1 | **2026-10-03, after DEV round 1 and before round 2** (owner's screenshot, chat) | **$48.29** | **$1.28** | at most **$1.71 cumulative** if the account started at $50.00 |
| after DEV round 2 | **2026-10-03 19:07 local, after DEV round 2 and before round 3** (owner's screenshot, chat) | **$47.96** | **$0.33** | at most **$2.04 cumulative** if the account started at $50.00; the interval holds round 2 only ($6.9561 API-reported + estimates) |
| **this reading** | **2026-10-04 13:50 local, after DEV round 3, about one minute into round 4** (owner's screenshot, chat) | **$47.61** | **$0.35** | at most **$2.39 cumulative**; the interval holds round 3 ($5.8532 API-reported) and the first minute of round 4 |

## What the $48.29 covers, and what it does not say

Everything run since the $49.57 reading: the v1.4.2 gate and seal, the D-41 probe, the v1.4.3 seal, the v1.4.3 gate with its two killed attempts, and DEV round 1 at harness-v1.5.0. **DEV round 1
cannot be separated** from the rest: no reading was taken just before it.

For scale only (DERIVED, not a measurement of billing): the API-reported ledger grew from $18.5083 (after the v1.4.1 gate) to $34.7400 (after round 1), $16.23 as a lower bound, over the same
interval in which the account balance fell $1.28. The API-reported ceilings of the protocol ($40.00 DEV, $75.00 ledger) are therefore far above what the account was billed; they stay the
binding limits because they are the owner's. Sandboxes are described as free while in beta (D-36), which fits a billed figure that is a small fraction of the reported one but proves nothing
about what will be billed later.

## The round-2 interval, the only one so far that holds exactly one paid activity

Round 2 ($6.9561 API-reported + estimates, of which model calls $0.5444 API-reported) was billed $0.33. The ratio is DERIVED and for scale only; it is consistent with sandboxes being free in beta and model calls being billed (D-36).

## Budget re-anchoring (owner, 2026-10-03, after this reading)

Ledger ceiling $100.00 API-reported (the figure rule B4 names), and a BILLED floor of $20.00: no live work starts when the latest reading is below it. METHODOLOGY, "DEV round 2, BILLED reading, and the budget re-anchoring".

Round 3 ($5.8532 API-reported, model calls included) was billed $0.35: the second interval that holds one round, consistent with the first (round 2: $6.9561 → $0.33).

Next reading wanted: after DEV round 4 (and at the freeze, and after the TEST phase).
