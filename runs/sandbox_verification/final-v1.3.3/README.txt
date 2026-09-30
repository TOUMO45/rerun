Seal verification of harness-v1.3.3 (repeat after attempt 1; attempt 1 is archived under ../attempt1-v1.3.3/ and does not count).
18 live Nebius runs, all passed: the 17 planned runs plus one extra kill run made to catch the server-result stop path.
Measured spend of this repeat: $1.260 (sum of each record's cost; the client-wait kill run has no cost field, the server-result kill run measured $0.00006).
The run runner's own conservative total printed ~$1.56 because it charges $0.30 to a record without a cost field; that figure is an over-estimate.
Cumulative seal spend on the new ledger: attempt 1 $1.236 + repeat $1.260 = $2.496 (approved: cap $2.50 for attempt 1, $2.20 for the repeat, cumulative <= $3.75).
Note on run ids: a run whose chain retains no image (no install step: the smoke launcher runs and the kill runs) reports the BASE IMAGE's id as its sandbox id, so those records
share an id (dbfbe818... is python:3.10-slim); each record is still distinguished by its own timestamps, output and cost.
