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
| after DEV round 4 | **2026-10-04, after DEV round 4** (owner's figure, chat) | **$47.11** | **$0.50** | at most **$2.89 cumulative** if the account started at $50.00; the interval holds round 4 ($5.3490 API-reported entries + $0.0053 upload smoke test) less its first minute |
| before the v1.7 probe | **2026-10-05** (owner's screenshot, chat: "Account balance $47.11") | **$47.11** | **$0.00** | confirms the round-4 reading by screenshot; nothing paid ran in between (the v1.7 work was offline; the probe has not run). Above the $20.00 floor |
| after DEV round 5 | **2026-10-05, after DEV round 5** (owner's screenshot, pasted in chat: "Account balance $46.90"; the screenshot shows no time) | **$46.90** | **$0.21** | at most **$3.10 cumulative** if the account started at $50.00; the interval holds the two v1.7 probes ($0.0205), the two seal attempts ($2.2393) and DEV round 5 ($8.8107 API-reported + $1.9177 estimated + $0.0053 upload smoke test): $11.0759 API-reported against $0.21 billed (D-36, not reconciled). Above the $20.00 floor |
| after the TEST phase and the live UI run | **2026-10-05, after the TEST phase and the live UI run** (owner's figure, typed in chat) | **$46.37** | **$0.53** | at most **$3.63 cumulative** if the account started at $50.00; the interval holds the TEST phase ($18.4401 recorded: $5.6540 API-reported entries, $3.6610 estimated killed steps, $9.12 estimated sustained run, $0.0051 upload smoke tests) and the live UI run ($1.0670): $19.5071 recorded against $0.53 billed (D-36, not reconciled). Above the $20.00 floor |
| after the exploratory v1.7.2 scans | **2026-10-05, after the three exploratory 5-repo live scans of harness-v1.7.2 work** (owner's figure, typed in chat: "$45.81 BILLED") | **$45.81** | **$0.56** | at most **$4.19 cumulative** if the account started at $50.00; the interval holds the three exploratory live scans (runs/live_scan/, runs/live_scan/v1.7.2/, runs/live_scan/v1.7.2b/: $0.2971 + $0.4080 + $2.1638 = $2.8689 from the cost guard's own totals) against $0.56 billed (D-36, not reconciled). These scans were never added to the ledger reader; ledger API-reported with TEST and the scans: $88.3032. Floor: the owner set a BILLED floor of **$10.00** and an API-reported ledger ceiling of **$300.00** on 2026-10-05 (chat); above the floor |
| after the v1.7.2 seal, the out-of-sample scan and TEST-B | **2026-10-06, after the harness-v1.7.2 seal, the out-of-sample scan and TEST-B** (owner's screenshot, chat: "Account balance $45.14") | **$45.14** | **$0.67** | at most **$4.86 cumulative** if the account started at $50.00; the interval holds the harness-v1.7.2 seal ($1.1228 API-reported), the out-of-sample scan ($1.2620) and TEST-B ($7.5598 with its upload smoke test): $9.9446 API-reported against $0.67 billed (D-36, not reconciled). Ledger $98.2478 API-reported of the $300.00 ceiling; above the $10.00 BILLED floor |

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

> 2026-10-04: the round-4 reading ($47.11) is in the table above; the row labelled "this reading" is the round-3 one. Round 4 ($5.3543 API-reported) was billed $0.50: the third one-round interval, in line with rounds 2 and 3. Next reading wanted: after the v1.7 seal and DEV round 5.
