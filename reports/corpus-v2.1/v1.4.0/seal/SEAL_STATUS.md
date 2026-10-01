# Seal of harness-v1.4.0 (option B): status after run 1 and the option-B checks — INCOMPLETE at first; completed by the run 2 retry (see the last section)

> **Owner decision (chat, 2026-10-01), annotated here:** option 1. Seal cap raised to $1.70 for the run 2 retry only; E restarts from the
> kept apt image `81809b90-f48d-4ba3-9ae2-51081ee3cf68` with a fixed 180 s wall clock, then F. Attempt 1 stays ESTIMATED <= $0.4998, not
> recomputed. The seal-script defect is registered as **D-29** (fixed-unvalidated; `reports/corpus-v2.1/candidate_v1.3.3_defects.md`).
> Kept-image billing is recorded as **"unbilled on available evidence (docs list only run and import_image as billable; reopen after 600 s
> cost $0.00017)"**; the owner checks the account billing page and reports back; it is not MEASURED until then. Ledger ceiling after this
> step: $16.84 (lower bound, D-27). If run 2 passes: tag harness-v1.4.0 and start the gate under the stated rule; if it fails: stop.

Caps (owner, chat 2026-10-01): seal $1.50, gate $5.00, entry $1.25. The gate has NOT started; `harness-v1.4.0` is NOT tagged.

## Seal run 1 — passed (records in `runs/sandbox_verification/v1.4.0-seal/`)

| Op | What | ok | Cost [MEASURED] | Image / run id |
|---|---|---|---|---|
| A | ready image on python:3.10-slim, tree + setup layers kept | true | $0.0120 | `a531213a-6059-49d8-b7f6-92a9e1be33b6` |
| B | ONE branch run from A's deepest layer (overlay one file, run it), no setup step re-run; result image kept | true | **$0.00054618** | `b96a5e01-99d9-44ec-93d7-4df3ba249104` |
| C | exit-site hook + CPU shim installed on A's kept image; the hook printed the exit site of `sys.exit(3)` inside `leave()` | true | $0.0012 | `456fd50a-e406-45c8-a683-4e3995782898` |
| D | B's kept result image reopened 600 s later and run again | true | $0.00017036 | reopened `b96a5e01-99d9-44ec-93d7-4df3ba249104` |

- **Measured branch-run cost: $0.00054618** (record `run1_B_branch_run.json`), against the owner's limit of $0.15.
- **Kept-image billing:** reopening the kept image after 600 s cost $0.00017036, less than the same image's first run ($0.00054618): no
  storage charge appears in any operation's cost. Nebius documents only `run` and `import_image` as billable ("VM"); image listing, tagging,
  upload and download are "Free" (Contree MCP cheatsheet); no document found gives a storage price or a retention period. So: not billed
  on the evidence available (documentation + operation costs), not a measurement of the account's bill. Kept images of run 1:
  `a531213a…`'s layers and `b96a5e01…` (listed in `run1_D_reopen_kept_image.json`).

## Option-B re-verification — passed (records in `runs/sandbox_verification/final-v1.4.0/`)

14 live runs, all `ok`: download route by git on entry 8's repository ($0.0700), archive upload + exec bit ($0.0008), torch py3.6 pin
($0.1675), matched family py3.10 ($0.2504), runner-setup phase tag ($0.0189), torch py3.9 + NumPy cap ($0.1843), six smoke-launcher runs
($0.0066), kill at the operation limit through both stop paths (client_wait_timeout, then server_result_timed_out; $0.0001). Sum $0.698525 [MEASURED].

## Seal run 2 — NOT passed: a defect of the seal script, first attempt lost its cost

Operation E (entry 7's recorded environment as a checkpoint) was funded for 58.8 s: the $0.50 run cap at the guard's bound of $0.0085/s.
That is too short for entry 7's apt step plus its pip install of the era lock; the client stopped the pip step (operation
`01a0f82a-ee6d-76bc-a8f0-f74e11c7246f`, CANCELLED, read back from the API). The script did not catch the timeout, so the measured cost of
the completed steps (upload/extract, apt) was lost; no API call lists past operations. Recorded in `run2_E_attempt1_killed.json` with an
ESTIMATED upper bound of $0.4998 (58.8 s at $0.0085/s). The image after the apt step was kept: `81809b90-f48d-4ba3-9ae2-51081ee3cf68`.
Fixed in the script (every operation's timeout is now recorded with its cost; E can start from a kept image; a fixed wall clock per
operation), with tests (`test_v140_seal_runner.py`).

## Spend

Seal: $0.712373 [MEASURED] + at most $0.4998 [ESTIMATED, run 2 attempt 1] = at most $1.2122. Left under the $1.50 seal cap on that strict
count: $0.2878. Ledger: $11.3471 [ESTIMATED: $10.5631 MEASURED + $0.7840 ESTIMATED], lower bound (D-27).

## Why stopped

The seal is not complete without run 2, and the retry does not fit the strict count. Entry 7's v1.3.4 repair-3 operation, the same build
plan, cost $0.2338 [DERIVED, events[54]] in 136 s. E restarted from the kept apt image runs only the pip step. F branches from E's deepest
image; if the pip step fails again, as it did in v1.3.4, F runs it again. E + F is therefore about $0.30-$0.40 [ESTIMATED] at observed rates,
above the $0.2878 left, and the guard's own bound would fund only 34 s.

## Run 2 retry (owner's option 1) — passed; the seal is COMPLETE

| Op | What | ok | Cost [MEASURED] | Record / image |
|---|---|---|---|---|
| E | entry 7's recorded environment as a checkpoint, started from the kept apt image `81809b90-f48d-4ba3-9ae2-51081ee3cf68`: only the pip step of the era lock ran; it failed in 5.0 s, `No matching distribution found for gcc` (the same failure v1.3.4 ended on, DEP_NOT_ON_PYPI) | true | $0.05123476 | `run2_E_entry07_checkpoint.json`, run id `feb3c11f-5906-41ea-8efb-3f7b4e6069d5` |
| F | reopen + apply + execute: reopened the same kept image, applied a one-file overlay, ran only the missing pip step: same outcome as E | true | $0.05192514 | `run2_F_reopen_apply_execute.json`, run id `9de6fe80-0d35-4a7f-af19-75cf3e9f79e8` |

Seal spend: $0.815528 [MEASURED: run 1 $0.013848 + option-B checks $0.698525 + run 2 retry $0.103160] + at most $0.4998 [ESTIMATED,
run 2 attempt 1, not recomputed] = at most $1.3153, under the $1.70 cap. Ledger: $11.4502 [ESTIMATED: $10.6662 MEASURED + $0.7840
ESTIMATED], lower bound (D-27).

Seal -> gate rule (owner): every seal check passed (the killed attempt 1 is superseded by the authorised retry and stays on record);
measured branch-run cost $0.00054618 <= $0.15; kept images unbilled on available evidence; seal spend <= $1.70. **All hold: the gate
starts automatically.** `seal_verification.json` written by `scripts/write_seal_verification_v140.py` (12 paths); tag `harness-v1.4.0`.


## Annotation (2026-10-01, v1.4.1 Step 1; the text above is unchanged)

Kept-image billing: where this file says "unbilled on available evidence" it now reads **no charge observed on the account balance** (owner's reading at 19:37 local,
2026-10-01: $49.61 of $50.00, at most $0.39 charged cumulative for the whole account; BILLED, not per gate). Tag: MEASURED in this file reads API-REPORTED (D-36, open:
`docs/design/D-36.md`; the Token Factory sandboxes page says "Free while in beta", the docs list no storage price). The "docs list only run and import_image as billable"
sentence is the MCP cheatsheet's Cost column (VM versus Free); the word "billable" is our reading of it (D-36, section 4).
