# Candidate harness-v1.3.3 defects (recorded, NOT fixed: harness-v1.3.2 is sealed; TREATMENT batch in progress)

Written 2026-09-30 while TREATMENT was at 9/20 records. Source: `reports/corpus-v2.1/arm_tables.{md,json}` (from
`scripts/arm_tables.py`, read-only over `runs/`) and the raw records in `runs/corpus_v2_batch/harness-v1.3.2/treatment/`.
Counts are for the records present at that time and will be re-derived when the arm finishes.

## Python-version selection rule (for repos that declare none)

Source: `backend/app/services/python_policy.py`, `METHODOLOGY.md` § "Runner environment policy". Precedence: `.python-version`,
`pyproject.toml`, `setup.py`/`setup.cfg`, `environment.yml`, `Pipfile`, README phrases; first satisfiable minor in the order
3.10, 3.9, 3.8, 3.11, 3.7, 3.12, 3.13, 3.6. A repo with no usable declaration runs on **3.10** (`[python] ... RERUN default 3.10`).
In TREATMENT only, the time machine may replace it with the era-appropriate interpreter (newest CPython released >= 180 days before
the pinned commit date, `time_machine.python_for_era`) **if the era lock succeeds**; if the lock fails the era interpreter is computed,
recorded, and not used. Both are shown in the `python_version_used` / `how chosen` columns.

## D-1  Repairer emits invalid unified diffs; 0 of 8 source patches applied so far (entries 1, 3, 4, 8)

Every `source_patch` attempt in TREATMENT so far (8 attempts: entry 1 #2, entry 3 #1-3, entry 4 #1-3, entry 8 #3) ended without a re-execution. Modes seen in the stored `diff_text` / events:
- wrong hunk line counts: `diff could not be parsed: Hunk is shorter than expected` (entry 3 #1, entry 4 #3);
- header-only diff with no hunk that the gate **passes** and `git apply` rejects: `No valid patches in input` (entry 1 #2, entry 8 #3);
- stale or misquoted context: `patch does not apply` (entry 3 #3);
- JSON-escaped literal `\n` inside the diff: `diff contains no file changes` (entry 4 #1, #2).
Consequence: source-patch repairs cannot currently be a source of recoveries; any recovery so far is env-only.
Candidate fix: ask for structured edits (file, exact old text, new text) and let the harness build the diff; reject a diff with zero hunks in the gate.

## D-2  Tamper gate PASSes a diff with zero hunks (entry 1 #2, entry 8 #3)

The gate's own AST reconstruction trusts the diff structure (see the comment in `orchestrator.py` near "gate-approved patch failed to apply").
A header-only diff is "approved", consumes a repair attempt and, for entry 1, fed the same failing state into the next search.

## D-3  Entry 1: root cause of "repair 2 did not clear `collections.Iterable`" and of the identical second search

What the record shows (`01_nadiinchi__power_laws_deep_ensembles.json`, events 152-173 s):
1. Repair 2 was **not** a Tavily-derived patch. It was a model-written diff, `origin=model`, `tavily_sources=[]`, and the diff text is only
   `--- a/train.py` / `+++ b/train.py` (0 hunks). The gate passed it; `git apply` failed (`No valid patches in input`); nothing was executed.
   So the `Iterable` error could not have cleared: no code or environment change was made in repair 2 (D-1, D-2).
2. The second search is identical because `tavily.build_query(code, evidence)` is `f"python {code} fix: {evidence[:150]}"`: a pure function of the
   failure class and error string. The error was unchanged after the failed apply, so the query and its results were the same
   (`[tavily] 3 result(s) for 'python runtime error other fix: ImportError: cannot import name ...'`, logged twice). No history of earlier attempts enters the query (D-4).
3. Why `Iterable` appeared at all: the time-machine era lock failed (attempt 0, `DECLINED`): `curves` is a module the repo imports but does
   not contain, and the lock treated it as a PyPI distribution (`no versions of curves ... before 2020-10-23`). One unlockable name aborted the whole
   era lock, so the era interpreter (3.8) was computed but not used and the run stayed on 3.10. Repair 1 then pinned `tabulate==0.8.7` (2020), which
   does `from collections import Iterable`, on 3.10: an era-old package on a non-era interpreter (D-5). The final error, `No module named 'curves'`, is REPO (module absent from the repo).

## D-4  Search query does not vary with attempt history (same class + same error string = same query)

## D-5  An era lock that fails for one name discards the whole era environment, including the interpreter (entries 1, 8)

Entry 8: era python 3.6 computed, lock failed, run stayed on 3.10; repair 1 then pinned `scikit-learn==1.0.1`. Classification of these as
HARNESS_INDUCED is decided in Phase B3 with the definition written there; this file only records the mechanism.

## D-6  Entry 19 planning gap (from the pre-registered audit)

`operators._ext` is the repo's own compiled module and its README documents a build step; not a dependency. See METHODOLOGY.md CONTROL amendment.

## Observation (not a defect): Tavily was queried but never cited so far

`[tavily] N result(s)` appears in the events of every repaired entry, but every `[citations]` line is "not cited" and `tavily_sources` is empty in all
attempts of entries 1-9. So far the number of repairs whose decisive context came from Tavily is 0 of the repairs that ran. Phase B2 recomputes this on the full arm.
