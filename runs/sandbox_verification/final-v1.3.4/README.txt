Seal verification of harness-v1.3.4: 20 live Nebius runs (18 planned incl. the D-20 overlay case + kill runs until both stop paths were seen), all passed.
Overlay case: entry 8's repository (edenton/svg, 143 MB, download route) with utils.py patched locally; the sandbox fetched the original, applied the overlay, passed the
manifest check and showed the patched content (OVERLAY_OK; run id 5e30468e-1ade-465a-a9dc-99957ffac64f, cost $0.0717).
Measured spend of this seal: $1.312 (sum of each record's measured cost; the runner's conservative print of ~$1.61 charges $0.30 to a record without a cost field).
Cumulative on the new ledger: $5.426 before + $1.312 = $6.738.
Note on run ids: a run whose chain retains no image reports the base image's id; records are distinguished by timestamps, output and cost.
