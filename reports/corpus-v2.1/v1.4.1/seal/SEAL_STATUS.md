# Seal of harness-v1.4.1 (option B over changed files only): COMPLETE — all checks passed (live, 2026-10-01)

Caps (owner, chat 2026-10-01): seal at most $1.00, gate $6.00, entry $1.50, ledger ceiling $25.00 API-reported. Tags: API-REPORTED = a stored record field (the sandbox API's `resources.cost`,
not account billing, D-36), ESTIMATED, BILLED = the owner's balance reading. Records: `runs/sandbox_verification/v1.4.1-seal/` (`run_seal_v141.py`, run 1, then run 2, then run 3; each inspected
before the next started). Changed sandbox-touching file: `runner_hooks.py` only; the other four are byte-identical to harness-v1.4.0, so 11 of the 12 v1.4.0 entries are carried over
(`scripts/write_seal_verification_v141.py`) and `runner_hooks_on_a_kept_image` is re-verified (check C).

| Op | What | ok | Cost | Run id |
|---|---|---|---|---|
| A | ready image on python:3.10-slim (one pip step), tree and setup layers kept | true | $0.012413 | `e3becb83-213b-4fd8-b760-f2271771523a` |
| B | ONE branch run from A's deepest layer (overlay one file, run it); no setup step ran | true | $0.000628 | `6be8598e-720e-404b-8638-37db5a904f33` |
| C | exit-site hook and CPU shim installed on A's kept image; the hook printed the exit site of `sys.exit(3)` inside `leave()` | true | $0.001165 | `db8b613b-513f-4ac8-8c1b-e728e2af5fa6` |
| W0 | bare `raise SystemExit(1)` with the hook installed: exit 1, stderr EMPTY (the gap, D-35) | true | $0.000901 | `12d1ee01-9ff7-4890-94ae-db041686d571` |
| W1 | the same script through the exit wrapper: exit 1, the traceback of the raise on stderr (`File "/bare.py", line 6, in main`, `raise SystemExit(1)`, `SystemExit: 1`) | true | $0.000924 | `426eba31-6374-4b37-9e7c-1868f5d27955` |
| W2 | the wrapper on python:3.6-slim: the same raise site on Python 3.6 | true | $0.001338 | `d5d46b4b-d4bc-40d2-9f74-d392bea34fae` |
| L1 | python:3.10-slim, pip step kept; `shutil.which('gcc')` is None | true | $0.012159 | `ec037001-f757-4b38-95d4-44f1b530c8a7` |
| L2 | the apt layer on L1's deepest layer: only the layer ran (8.27 s billed), `gcc --version` works; the pip step was not run again | true | $0.083358 | `64e98434-bcc9-4558-82f0-7ca73151793c` |
| K1 | second setup step (`sleep 120`) stopped at the 30 s operation limit (client wait timeout, 23.6 s into it); layers kept: the tree and the pip layer | true | $0.011948 API-REPORTED + $0.200893 ESTIMATED (the killed step, 23.6 s at $0.0085/s) | `ca36a746-7351-47ec-9350-3a6b8f24f749` |
| K2 | a new operation reopened K1's pip layer by id and ran only `true` and the command | true | $0.000601 | `79e41928-3727-43b0-a910-b59ea1e287ed` |

## Spend

Seal: **$0.326329** = $0.125435 API-REPORTED + $0.200893 ESTIMATED (K1's stopped step). Planned ESTIMATED $0.3637, cap $1.00. Ledger: **$14.9758**
[ESTIMATED: $13.8041 API-REPORTED + $1.1717 ESTIMATED], a lower bound (D-27); under the owner's ceiling of $25.00.

## Seal -> gate rule (owner, automatic)

Every seal check passed (10 of 10 operations `ok`, 5 new or re-verified paths); the measured branch-run cost (B) is $0.00062790 API-REPORTED, at most $0.15;
seal spend $0.3263, at most $1.00. **All hold: the gate starts automatically.** `seal_verification.json` was written by `scripts/write_seal_verification_v141.py`
(16 paths: 11 carried over, 5 for v1.4.1); tag `harness-v1.4.1` on the seal commit.

## What the live checks showed that the fake cloud cannot

- The real shell runs `export DEBIAN_FRONTEND=noninteractive && apt-get update && apt-get install -y build-essential` as a layer on a kept image (8.27 s of billed time, exit 0) and `gcc` is there afterwards (L2).
- The real service lets a new operation reopen the layer that a KILLED operation had kept (K1 -> K2, by image id): the premise of D-31's resume.
- A bare `raise SystemExit(1)` leaves nothing on stderr with the hook installed (W0) and is printed by the wrapper on Python 3.10 and 3.6 (W1, W2).

## Kept images (for the billing page; no charge observed on the account balance so far, BILLED line in the gate report)

12 distinct image ids kept by this seal (layers of A, L1, L2, K1 and the operations that kept results):
- `42c44994-ac6f-46dd-b60c-91c40c006c60`
- `e3becb83-213b-4fd8-b760-f2271771523a`
- `7936a221-1ee3-4959-8bc0-12a7ed83a941`
- `19bcff19-f813-4309-b73d-e6a226806348`
- `20255f68-fc5d-4177-aba6-10add69b0994`
- `20821bb3-71dc-41bc-8287-a4bf9eb93315`
- `655930ea-b54e-4117-8664-00596df8c877`
- `ec037001-f757-4b38-95d4-44f1b530c8a7`
- `64e98434-bcc9-4558-82f0-7ca73151793c`
- `1ab12c73-2258-4a39-bd17-e6d0fccdece2`
- `ca36a746-7351-47ec-9350-3a6b8f24f749`
- `91d91dbf-febb-49a0-89ff-ba20e3161ecf`
