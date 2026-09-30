# Candidate harness-v1.3.3 defects (recorded, NOT fixed: harness-v1.3.2 is sealed; TREATMENT batch in progress)

Written 2026-09-30 while TREATMENT was at 9/20 records; counts in D-1 and the additions below were re-derived on the 20/20 arm (`results_tables.json`). Source: `reports/corpus-v2.1/arm_tables.{md,json}` (from
`scripts/arm_tables.py`, read-only over `runs/`) and the raw records in `runs/corpus_v2_batch/harness-v1.3.2/treatment/`.
Counts are for the records present at that time and will be re-derived when the arm finishes.

## Python-version selection rule (for repos that declare none)

Source: `backend/app/services/python_policy.py`, `METHODOLOGY.md` § "Runner environment policy". Precedence: `.python-version`,
`pyproject.toml`, `setup.py`/`setup.cfg`, `environment.yml`, `Pipfile`, README phrases; first satisfiable minor in the order
3.10, 3.9, 3.8, 3.11, 3.7, 3.12, 3.13, 3.6. A repo with no usable declaration runs on **3.10** (`[python] ... RERUN default 3.10`).
In TREATMENT only, the time machine may replace it with the era-appropriate interpreter (newest CPython released >= 180 days before
the pinned commit date, `time_machine.python_for_era`) **if the era lock succeeds**; if the lock fails the era interpreter is computed,
recorded, and not used. Both are shown in the `python_version_used` / `how chosen` columns.

## D-1  Repairer emits invalid unified diffs; 0 of 16 source patches applied (entries 1, 3, 4, 8, 10, 14, 17)

Every `source_patch` attempt in TREATMENT (16 attempts over entries 1, 3, 4, 8, 10, 14, 17; 12 gate REJECTs, 4 gate PASSes) ended without a re-execution: 0 applied (`results_tables.json` -> repair_split). Modes seen in the stored `diff_text` / events:
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

## Additions found on the full 20/20 arm

- **D-7 Per-entry $2 ceiling is not hard.** The guard checks before a step; one sandbox operation can cost far more than a typical one. Entry 13: a single 600 s re-execution recorded $5.12 (entry total $5.68); entry 16 $2.50.
- **D-8 A timed-out sandbox operation may be unrecorded spend.** Entry 15's repair-1 re-execution hit the 600 s wall clock (`PIPELINE_ERROR:sandbox:SandboxError`) and the record's `cost_guard` shows $0.36 for the whole entry; METHODOLOGY (harness-v1.2 limitations) already states TIMEOUT spend is under-reported. If billed like entry 13's 600 s operation ($5.12), true spend could exceed recorded $21.76 by about that amount. Unverified: needs the Nebius billing console.
- **D-9 Error extraction takes noise as the error.** Entry 3: terminal error recorded as `17.6` (a progress fragment); entry 12: a benign TensorFlow `W ... Could not load dynamic library libnvinfer.so.6` warning classified SYS_LIB_MISSING while the same stderr ends in `AttributeError: ... no attribute 'get_variable'`. The repairer then chased the wrong error.
- **D-10 `remove` in env_delta does not remove apt packages.** Entry 12 repair 3: logged "env delta applied" but the build plan's `apt_install` still listed both packages and the same apt error repeated.
- **D-11 The time machine overrides a repo-declared Python.** Entry 3: README declares 3.6, CONTROL ran 3.6, TREATMENT re-ran on era python 3.10 (`[python] ... (README)` then `[time-machine] ... -> python 3.10`).
- **D-12 The repairer proposes packages that do not exist for the image, and one that is a different project.** `python3-distutils` (entry 8) and `libnvinfer6` (entry 12) do not exist on the Debian 13 image; entry 19 repair 2 pip-installed `operators==1.0.0` (a real PyPI project, verified by the resolver as existing, unrelated to the repo) for the repo's own `operators._ext`. The gate does not check whether a name is the repo's own module: a dependency-confusion vector (Phase D5 test).
- **D-13 Runner-setup failures never reach the time machine.** Entries 5 and 9 (both arms): `RUNNER_SETUP_FAILED` before the repo's first command; the era lock, which chooses an older Python, is only entered after a baseline run. Whether an era interpreter would have installed the historical torch pin was not tested.
- **D-14 METHODOLOGY line 729 is inaccurate.** "the harness saw no dependency file for any of the 16 audited entries": intake shows dependency files for entries 5 (Pipfile, requirements.txt), 9 (requirements.txt) and 17 (setup.py declaring torch, torchvision). 17 of 20 have none. The pre-registered text is not edited; RESULTS.md carries the correction.

## Observation (not a defect): Tavily was queried but never cited

46 `[tavily]` searches in 16 entries; 0 cited sources; every `tavily_sources` is empty; every `[citations]` line reads "not cited". Tavily-decisive fixes: 0 (and recoveries: 0).
