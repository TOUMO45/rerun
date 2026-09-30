# Changelog

One entry per phase of the post-corpus-v2 plan. Numbers are produced by scripts in `scripts/`.

## Phase 0 — pilot run summary (2026-09-29)
corpus-v2 on harness-v1.2 was stopped by the operator after 3 of 20 entries (commit `56fc710`) because the
Nebius sandbox refuses torch's executable-stack shared objects and the harness charged that to the repository
(entry 3). It is recorded as a **pilot run**, not a baseline; entries 1–3 stay frozen (entry 2
UPLOAD_TOO_LARGE, entry 3 MISATTRIBUTED). `scripts/summarize_batch.py` produces `reports/corpus-v2/summary.md`
(results table, PRIMARY lines, STATUS, failure attribution, run integrity). The baseline is redesigned as a
same-harness ablation (CONTROL: repair off / TREATMENT: repair on), replacing "v2 vs v2.1".

## Phase 1 — sandbox limits (2026-09-29)
`backend/app/services/sandbox_limits.py` encodes the Nebius limits (source: Sandboxes team email, 2026-09-29): upload gate
120 MiB (unit unresolved by evidence, so the smaller reading is enforced with a margin; the harness-v1.2 cap of
125,009,920 B was the top of RERUN's probe ladder, not a Nebius number), an in-sandbox download route for over-limit
repos (manifest-only upload; the sandbox fetches the pinned GitHub commit and verifies it against the git-blob manifest;
WSL dry run passed, tamper caught), setup split into system/torch/rest operations, and a per-op 12 GB delta ESTIMATE
check. 26 new tests; suite 768 passed, 9 skipped.

## Phase 2 — SANDBOX_QUOTA / SANDBOX_INCOMPAT, error chain, attribution (2026-09-29)
Sandbox-side failures (quota/limit; platform refusal such as the exec-stack refusal that sank pilot entry 3) now end
INDETERMINATE and stop the repair loop; they are excluded from every rate. Every run records an ordered error chain with
attribution (REPO / ENV / SANDBOX_QUOTA / PLATFORM), `first_repo_error` (first REPO link) and `last_error`; passport bundle
v4 hashes the whole verdict record. Regression tests derive entry 1's chain from its real pilot log (first repo error =
undeclared `tabulate`; the `Iterable` error is ENV because we chose py3.11). Deviation from the brief, flagged: torch-family
missing is ENV even though undeclared (runner-provided by policy). Suite: 795 passed, 9 skipped.

## Phase 3 — runner-level torch and Python policy (2026-09-29)
Torch is now provided by the runner (CPU wheels as their own op, then an exec-stack fix + `import torch` verification op),
verified in a real sandbox (glibc 2.41, kernel 7.0.6): the newest wheel loads; an old pin (1.12.1) reproduces the pilot's
executable-stack refusal and is fixed by `patchelf --clear-execstack`. Python defaults to 3.10 unless the repo declares a version
(reason logged; 6-fixture resolver tests). Not done, with reasons: pre-warmed snapshot (SDK supports `tag_as`; low value, adds
mutable state) and pre-installing numpy/scipy/tabulate (would hide REPO-attributable undeclared dependencies). Preflight now refuses
a non-sealed `NEBIUS_SANDBOX_IMAGE`. Suite: 815 passed, 9 skipped.

## Phase 3b — harness-v1.3 driver and ablation plumbing (2026-09-29)
`live_run.py --arm control|treatment` (control: `repair_enabled=false`, no Tavily, no time machine); the batch driver owns its children
(kill-on-close job object on Windows, process group elsewhere; verified with a real process test), writes a driver log and pid file,
validates every record on resume (complete JSON, frozen hash/tag/arm, verifying passport, no driver error, never a dev run) and re-runs an
invalid one once; `scripts/watch_batch.py` reports pid-alive AND summary-absent with a timestamp on every line;
`scripts/compare_batches.py` implements the pre-registered analysis (categories never merged, stated denominator, Wilson interval, regression
exit code). The spend ceiling is a parameter (`--total-cap-usd`, `--already-spent-usd`) so one cap can span both arms without a re-seal. Preflight now allows `reports/` and `CHANGELOG.md` as post-tag data. Pre-registration written in METHODOLOGY. No batch started:
the spend cap as written (3× pilot = $1.13) is below one arm's expected cost; awaiting the operator's number.

## Phase 3c — upload boundary probe, spend cap, harness-v1.3.1 (2026-09-30)
`scripts/upload_boundary_probe.py` (records `runs/upload_probe/boundary_*.json`): 128,000,000 B and 127 MiB accepted; 128 MiB and 129 MiB
rejected (ENOSPC in the upload op). MAX_UPLOAD_BYTES stays 120 MiB (5.5 % below the largest accepted size); docstring and METHODOLOGY
"Sandbox limits" updated from "unsettled" to measured; re-sealed as `harness-v1.3.1` (no behavioural change vs v1.3). Operator decisions:
total spend cap $25 across both arms (`--total-cap-usd 25`), per-entry $2 unchanged; torch-family missing = ENV even when undeclared
(rationale in METHODOLOGY); TREATMENT gated on >= 8 CONTROL entries with a REPO-attributed non-PASS.

**Operator environment (not in git; `.env` is untracked):** `NEBIUS_SANDBOX_IMAGE` changed `python:3.11-slim` -> `python:3.10-slim`
(the sealed driver requires it).

## Phase 3d — attempt 1 aborted; harness-v1.3.2 (2026-09-30)
CONTROL on harness-v1.3.1 stopped at 4/20 ($0.47): entry 3 charged RERUN's failed `patchelf --clear-execstack` (py3.6 resolves patchelf 0.17.2)
to the repo, entry 2 failed the download route's exit-97 check (mode 664 vs 0644 on all 374 files, then a `shutil.move` into `/media` bug),
entry 4 lacked torchvision (runner installed torch only), and the driver crashed once on U+FFFD (cp1252). Records kept in
`runs/corpus_v2_batch/attempt1_harness-v1.3.1_aborted_4of20/`. v1.3.2: phase-first attribution (`runner_setup` never REPO; `RUNNER_SETUP_FAILED`),
runner-owned pinned patchelf with a pre-check (SANDBOX_INCOMPAT if the flag is absent), git-first download route with a tarball fallback and an
exec-bit-only mode check, matched torch family, UTF-8 driver, and the enforced seal rule (`seal_verification.json`, preflight). Live
verification records: `runs/sandbox_verification/final/` (9 real Nebius runs; pre-seal spend $1.97). Suite: 974 passed, 9 skipped.

## Phase 4 — CONTROL result and attribution audit (2026-09-30)
CONTROL on harness-v1.3.2: 20/20 records, $4.07 (commit `4b99d3b`). Read-only audit in `reports/corpus-v2.1/audit/`: gate (a) 16, (b) 12; no DECLARED_NOT_PARSED.
Pre-registered before TREATMENT (METHODOLOGY): the INFRA_ERROR retry policy and the fix-difficulty strata (`reports/corpus-v2.1/strata.json`, sha256 `ade8083fcda9bda5...`).

## Phase 5 (partial) - TREATMENT result and comparison (2026-09-30)
TREATMENT on harness-v1.3.2: 20/20 records, $17.68 (total with CONTROL $21.76 of $25). `scripts/compare_batches.py`: **RRR 0/16 (95 % Wilson 0-19 %)**, no regression.
Per-stratum table and four harness defects seen in the sealed run (numpy-2/old-torch runner failure charged to ENV, compare_batches filing it as REPO_STILL_FAILING, repair-time wall-clock
as PIPELINE_ERROR, the non-hard $2 per-entry ceiling): `reports/corpus-v2.1/treatment-findings.md`. Nothing in the sealed harness or any record was changed.

