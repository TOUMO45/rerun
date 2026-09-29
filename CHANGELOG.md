# Changelog

One entry per phase of the post-corpus-v2 plan. Numbers are produced by scripts in `scripts/`.

## Phase 0 — pilot run summary (2026-09-29)
corpus-v2 on harness-v1.2 was stopped by the operator after 3 of 20 entries (commit `56fc710`) because the
Nebius sandbox refuses torch's executable-stack shared objects and the harness charged that to the repository
(entry 3). It is recorded as a **pilot run**, not a baseline; entries 1–3 stay frozen (entry 2
UPLOAD_TOO_LARGE, entry 3 MISATTRIBUTED). `scripts/summarize_batch.py` produces `reports/corpus-v2/summary.md`
(results table, PRIMARY lines, STATUS, failure attribution, run integrity). The baseline is redesigned as a
same-harness ablation (CONTROL: repair off / TREATMENT: repair on), replacing "v2 vs v2.1".
