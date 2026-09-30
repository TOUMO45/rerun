Seal verification attempt 1 (2026-09-30, harness-v1.3.3 code at dc7b503): 10 paths passed, kill_at_operation_limit FAILED and the sequence stopped (as instructed).
The failure was a finding, not noise: a step stopped by the sandbox returns a normal result with state.timed_out (D-17). sandbox.py changed in response,
so these records were made against a stale blob and do NOT count for the seal; the seal uses runs/sandbox_verification/final-v1.3.3/ after a full repeat.
Measured spend of the 10 passing runs: $1.236 (sum of the cost_usd recorded in each); the failed kill run recorded no cost (~28 s).
