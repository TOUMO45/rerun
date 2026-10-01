# Changelog

One entry per phase of the post-corpus-v2 plan. Numbers are produced by scripts in `scripts/`.

## Phase D5 — submission assets (2026-10-01; documents and offline tooling only, no Nebius call)
One commit per deliverable. (1) `docs/submission/demo_script.md`: a timed script under three minutes that shows recorded artifacts only, with a side-by-side table mapping every spoken
sentence that contains a number to a passport field or record id. To let the video and the texts quote models and counts from a recorded artifact, `replay/summary.json` gained `stack`
(model per role, call and token counts, sandbox backend, search configuration, read from the run records) and `inventory`, and the dashboard gained a "How it ran, as recorded" section.
`backend/tests/test_phase_d_submission.py` checks every submission text: each number is in the REPLAY JSON, each line with a number carries a tag, and no sentence says the LLM repair
loop recovered an entry. The pre-Phase-D demo script moved to `docs/history/`. (2) `README.md` rewritten in the submission order (what it is, the measured result, how it works, where Nemotron / Token Factory / Tavily are used,
offline and live runs, evidence and integrity, defect register and status rule, cost ledger, licence, known limits); the model names are checked against the records, every number is in
the REPLAY JSON and tagged; `summary.json` `inventory` gained the defect counts by status. The build-log README moved to `docs/history/README_build_log.md`. Ledger: $10.1349 ($9.8507 MEASURED + $0.2842 ESTIMATED, lower bound D-27).

## Phase D4 — design notes for D-23 and D-25 (2026-10-01; documents only, no code)
`docs/design/D-23.md` (cached torch layer and per-operation floor, compared) and `docs/design/D-25.md` (harness-injected exit-site hook, with a `-X dev -m trace` fallback): the problem
as the records show it with record ids, the proposed mechanism, what a validating gate would have to measure, and an ESTIMATED cost of that gate. Both defects stay open.

## Phase D4 — D-24 fix: post-gate, unvalidated (2026-10-01; tag `harness-v1.3.5-unvalidated`; no Nebius call)
**post-gate, unvalidated.** The deterministic "missing C compiler -> apt build-essential" rule now also fires on a SYS_LIB_MISSING classification at repair time, before any model
proposal for that failure (deterministic first, model second). The step is recorded as an attempt of origin `time_machine` with `time_machine_action` = {rule, matched_error,
apt_added, phase}; it passes the same env gate as a model proposal and does not use up a model attempt. The baseline path is unchanged and shares the matcher. Only
`backend/app/services/orchestrator.py` changed. `harness-v1.3.4` (`10319b3`) stays byte-identical; this change is on `main` as `harness-v1.3.5-unvalidated`, which is not sealed and is
never used in a gate, seal, passport, REPLAY or dashboard figure. No gate has measured it: nothing here claims a recovery. Tests: test_d24_build_essential.py (entry 7's recorded
error string from the v1.3.4 gate record, no model call; baseline regression; an unrelated SYS_LIB_MISSING does not fire; the attempt record carries the quoted string).
Register: D-24 is now `fixed-unvalidated`, its basis the quoted test name. Dashboard wording: "harness-level, no entry passport"; the status column reads "Status (rule above)".
Ledger from here on: $10.1349 ($9.8507 MEASURED + $0.2842 ESTIMATED, lower bound D-27).

## Phase D3 — static dashboard from the REPLAY JSON (2026-10-01; offline, no Nebius call)
`python -m phase_d.build_dashboard` writes `reports/phase-d/dashboard/index.html`: headline card, gate scorecard (pre-registered anchor, CONTROL and TREATMENT separate; the two
EXPLORATORY versions with their D1 badges above the numbers), cost ledger (MEASURED + ESTIMATED, lower bound D-27, the three seal kill records), defect register D-1..D-28 with
status and passport links, and a per-entry drill-down. The build stops if the REPLAY check fails or if the rendered page has an untagged or unlinked number or an external resource
(`phase_d/check_dashboard.py` parses the HTML). REPLAY gained `summary.json` (headline counts, defect register with quoted sources, ledger recomputed from the seal and gate records)
and, per entry, the blob hash and the D-28 worktree hash. Passport annotations no longer carry a `status` (the register is the single source; still schema v3). D-24 is shown open.
Tests: test_phase_d_dashboard.py; test_phase_d_replay.py extended.

## Phase D housekeeping 2 — D-28, passport schema note, ledger rounding (2026-10-01; documentation and regenerated passports)
D-28 registered (the `record_*_sha256` values of `results_tables.json` are hashes of CRLF worktree files, not git blobs): open, documented only; `results_tables.json` is not
modified, `results_tables.md` carries the annotation beside its first hash column, and `reports/phase-d/record_index.md` maps worktree hash -> blob hash -> record id.
Passport schema: v1 at tag `phase-d1`, v2 at tag `phase-d2` (so passport hashes differ between the two tags), v3 from this commit (adds `record.results_tables_sha256`). Passports
are regenerable from the record blobs at any of these commits with `python -m phase_d.build_passports`. Ledger: the report's $10.134 is a sum of rounded components; the
full-precision record sum is annotated beside it. REPLAY regenerated (passport hashes changed).

## Phase D2 — REPLAY from committed records, cross-checked against the passports (2026-10-01; offline, no Nebius call)
`python -m phase_d.build_replay` writes `reports/phase-d/replay/<version>.json`, `<version>.md` and `index.md` for harness-v1.3.2 (the pre-registered anchor, CONTROL and
TREATMENT separate), v1.3.3 and v1.3.4 (EXPLORATORY badges from D1, verbatim). Per entry: baseline, era lock, each attempt (gate decision, outcome, consulted, cited, reason,
silent exit), execution and kills with the quoted source line, verdict with its annotations, and cost against the entry cap and the batch cap, split MEASURED / ESTIMATED.
Every value shown is cross-checked against its passport field (a mismatch stops the build); every number carries a tag and a pointer to the passport field; the output has no
build timestamp. Passport schema v2 adds the tagged fields REPLAY displays (consulted count, batch cap, per-operation cost lines, gate criteria b and d, the v1.3.2 primary
line); all 49 passports were regenerated and still verify. Tests: test_phase_d_replay.py.

## Phase D housekeeping — D-27, ledger lower bound, tag-check scope (2026-10-01; documentation only)
D-27 registered (the ledger records only completed cost; the spend of a killed step is absent): open, documented only. The ledger line in `SMOKE_GATE_REPORT_v1.3.4.md` is annotated
"$10.134 is a lower bound (D-27)"; no amount is reconstructed and no DERIVED bound exists (no event line states one). `reports/phase-d/README.md` states that the tag check is
JSON-only and that REPLAY and the dashboard may display only numbers read from tagged passport fields.

## Phase D1 — passports from committed records (2026-10-01; offline, no Nebius call; the sealed harness is untouched)
`phase_d/` (outside the sealed harness paths) builds one passport per committed run record of harness-v1.3.2 / v1.3.3 / v1.3.4 into `reports/phase-d/passports/`, with
`reports/phase-d/record_index.md`. Record id = `<harness_tag>/<arm>/<entry>@<sha256 of the committed blob>`; every number is tagged MEASURED, ESTIMATED or DERIVED; a field a
harness version did not store is null with that reason. `python -m phase_d.verify_passports` rebuilds from the blobs and diffs to zero; `python -m phase_d.check_tags` fails on an
untagged number. harness-v1.3.3 and v1.3.4 passports carry the EXPLORATORY badge with each version's own measured gate line. Annotations added beside (never in place of) the
original lines of `SMOKE_GATE_REPORT_v1.3.4.md` and `candidate_v1.3.3_defects.md`: the figure 9 for consulted attempts is not reproducible from records (records: `consulted` on 7
attempts, `reason_no_citation` on 6), the gate and ledger totals contain the entry-8 estimate, and the headline is restated as 0 of 8 entry-runs. New defect D-26
(`reason_no_citation` not recorded on a DECLINED attempt): open, documented only. Tests: test_phase_d_passports.py.

## harness-v1.3.4 — the five defects the v1.3.3 smoke gate found (2026-09-30; exploratory; v1.3.2 stays the pre-registered result)
Smoke gate v1.3.3 (entries 11, 7, 3, 8): 1/4 recovered, 2 patches applied, 0 citations, no cost event; NOT PASSED. Fixes: D-20 the download route carries patched files as an
overlay applied before the integrity check (entry 8's INVALID_HARNESS); D-22 a voided attempt is still recorded; D-18 the RERUN-managed lock is never shown as `requirements.txt`
and cannot be a patch target; D-19 silent failures (no error text) give the repairer head+tail of both streams and the exit code, a blind code patch is rejected unless it only adds
diagnostics, and re-executions run unbuffered with faulthandler; D-21 numbered references with a REQUIRED `cited_sources` field, `consulted` and cited stored and hashed, a
deterministic `content_match` citation when the applied change's text appears in a reference. New tests: test_v134_overlay.py, test_v134_repair_loop.py.

## harness-v1.3.3 — exploratory repair-loop fixes (2026-09-30; v1.3.2 stays the pre-registered result)
Fixes for the defects the v1.3.2 records showed (`reports/corpus-v2.1/v1.3.3/DEFECT_FIX_MAP.md`): hard per-entry / per-operation spend enforcement during a sandbox operation
with killed-operation spend recorded and TIMEOUT instead of PIPELINE_ERROR; one static whole-tree dependency batch with the repo's own modules excluded and a dependency-confusion
guard; era-lock robustness (relax, drop, or one fallback pip step) and a README-declared Python that wins; a patch pipeline that rebuilds the model's diff and checks it with
`git apply --check` before the gate (offline: 11 of the 16 stored v1.3.2 patches recovered, 68.75 %, target 80 % not met offline); Tavily citations carried into the record and the passport;
classifier denoising; apt `remove`; smoke execution for re-executions; a Windows-host bug in the apply step (text-mode stdin turned LF into CRLF); NumPy<2 beside torch<2.3.
Suite: see the commit. Nothing was run on Nebius before the seal verification.

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

