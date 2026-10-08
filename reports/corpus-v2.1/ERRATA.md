# Errata to `RESULTS.md` (written 2026-09-30, while fixing harness-v1.3.3; `RESULTS.md` itself is unchanged below its first line)

`RESULTS.md` (commit `8d47dfc`) stays authoritative for every number it reports. Two statements in it are incomplete in a way that matters; nothing
else is known to be wrong.

**E-1. "0 of 16 source patches applied ... (`git apply` failed: wrong hunk counts, zero hunks, stale context)" (§6, §1) omits a host defect.**
On the Windows host that ran the v1.3.2 batches, the apply step passed the patch to `git apply` through text-mode stdin, which turns every LF into CR LF.
`git apply` then reports `patch failed: <file>:<line> ... patch does not apply` for a patch that applies cleanly to the LF file. Reproduced on the stored
record of **entry 14, attempt 2** (a gate-approved diff): applied to the pinned file through bytes it succeeds (exit 0); through text mode it fails with exactly the
error in the record (`patch failed: main_optim.py:138`). Test with its negative control: `backend/tests/test_v133_patch_pipeline.py`
(`test_negative_control_text_mode_stdin_really_breaks_git_apply_on_windows`). The other three gate-approved diffs were header-only (entries 1 and 8) or built on
invented context (entry 3 attempt 3) and would not have applied on any host.
Consequence: the v1.3.2 figure "0 applied" is a true count of what happened, but at least one of the 16 was lost to the harness host, not to the model. Whether
entry 14 would then have run is unknown (the patch removes a `torch.cuda.set_device` call; the entry sits in the platform stratum D3). The primary rate 0/16 is a
measurement under that defect; the v1.3.3 fix is D-15 in `v1.3.3/DEFECT_FIX_MAP.md`.

**E-2. METHODOLOGY line 729 and `RESULTS.md` §3.** Already recorded in `RESULTS.md` §3 (dependency files exist for entries 5, 9, 17); listed here so the
corrections are in one place.

---

# E-3 (written 2026-10-08, harness-v1.10 pass): counts that include DEV entry 14 (IST-DASLab/M-FAC, harness-v1.5.2)

Nothing above is edited and the record `runs/corpus_v2_batch/harness-v1.5.2/dev/14_IST-DASLab__M-FAC.json` is unchanged; its erratum is the sidecar file `14_IST-DASLab__M-FAC.erratum.md` beside it
(the full statement and table), and the machine-readable entry is `reports/v1.10/errata.json`.

**E-3.** The record's `RUNS_AFTER_REPAIR` follows a gate-passed model patch that replaced LU without pivoting by a pivoting factorisation (D-44): it ran, on a different matrix. It was counted as a run
in: the DEV per-round smoke counts (round 3: 3 of 8, **2 after the erratum**), the DEV "certified" figure of the v1.9 counterfactual (12 of 40, **11 after the erratum**; the ungated figure, at least 15
of 40, is unchanged), the README and the Batch Lab headline that quote them, and the D1/D4 stop-rule inference of the DEV freeze (round 4 adds one entry over a round 3 of 2, so "two consecutive rounds
that add nothing" is not met at round 5 by the corrected counts). The fresh-set figures (3 of 26) do not include it.
