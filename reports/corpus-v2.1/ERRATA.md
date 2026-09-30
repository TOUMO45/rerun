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
