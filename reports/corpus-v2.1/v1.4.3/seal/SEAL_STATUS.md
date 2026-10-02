# Seal of harness-v1.4.3 — result (2026-10-02, live)

**Passed.** Five stages, every check ok, `seal_verification.json` 19 paths (17 re-verified by re-running their live checks against the new `sandbox.py`, 2 new), 34 live run ids; tag `harness-v1.4.3` on the commit that adds the records. Tags: API-REPORTED = the sandbox API's reported operation cost (not billing, D-36), ESTIMATED = the killed-step estimate at $0.0152/s (D-27).

| Stage | Checks | Spend (recorded) |
|---|---|---|
| new | S1 200,075 bytes of stderr come back whole, flag false; S2 a 5 MiB stream returns exactly 4,194,304 bytes with the flag set and the last line not returned, the harness labels it OUTPUT_TRUNCATED; S2b a 4.5 MB stream of three-byte characters is cut inside a character (returned 1,398,102 characters, the last the replacement character) with no exception; S3 `run_on_image` reopens a kept image by its id; S4 the same stopped at 3 s (the server's result with `timed_out`, $0.00006) | $0.00468 |
| v141 | K1 a step stopped at its operation limit keeps the layer before it, K2 resume from it, L1/L2 the additive apt layer | $0.411419 (K1: $0.011842 API-REPORTED completed steps + $0.304452 ESTIMATED for the stopped step, 20.03 s, client wait path) |
| v142 | A, B, C, W0, W1, W2 hooks and the exit wrapper (3.10 and 3.6), E0 and E1a the evidence command after a calm run and a self-SIGKILL | $0.019551 |
| v140 | A, B, C, D (a kept image reopened after a 600 s wait), E, F entry 7's recorded environment as a checkpoint | $0.290733 |
| final | download route, archive upload, three torch installs, the runner-setup tag, the kill through both stop paths, the smoke launcher on 3.10 and 3.6 | $0.704296 |

**Seal spend: $1.4307 recorded = $1.1262 API-reported + $0.3045 ESTIMATED**, cap $1.50 (the plan's pessimistic estimate was $1.4765). Branch-run cost (the seal -> gate rule's figure): $0.000529 (v1.4.0 stage) and $0.000551 (v1.4.2 stage), limit $0.15: **seal -> gate rule satisfied** (`check_seal_to_gate.py --cap 1.50`).
Ledger after the seal: **$23.9728** [ESTIMATED: $22.4966 API-REPORTED + $1.4762 ESTIMATED], a lower bound (D-27); ceiling $32.00; with the gate cap $7.00 the worst case is $30.9728, $1.0272 below the ceiling.

What the live checks showed that no offline test could: the API honours a 4 MiB `truncate_output_at` (S1, S2) and cuts exactly there with `truncated` set; a cut inside a multi-byte character is returned as bytes and decoded with replacement without an exception (S2b); `run_on_image` reopens a kept image and both of its stop paths exist (S4 took the server's path). The API's peak-memory figure per step was stored as returned: 7,824 (S1), 17,448 (S2), 14,484 (S2b); its unit is not documented and is not converted.
