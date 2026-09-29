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
