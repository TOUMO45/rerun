# corpus-v2.1: TREATMENT findings that the pre-registered analysis does not show by itself

Sealed harness `harness-v1.3.2`, corpus hash `7df090be…`. CONTROL 20/20 ($4.08), TREATMENT 20/20 ($17.68), total **$21.76 of the $25 cap**.
Primary result (pre-registered, `comparison-control-vs-treatment.md`): **Reproducibility Recovery Rate 0/16 = 0 %, 95 % Wilson 0 %–19 %.** No regression
(entry 18 is RUNS_CLEAN in both arms, no repair needed). Numbers are computed from the raw records; nothing below changes them.

## Per-stratum table (strata frozen before TREATMENT: `strata.json`, sha256 in METHODOLOGY's amendment)

| stratum | entries | REPO-failing in CONTROL | recovered | Wilson 95 % | not measurable in TREATMENT (INDETERMINATE) |
|---|---|--:|--:|---|---|
| D1 name-only | 1, 3, 7, 8, 10, 11, 15, 16, 20 | 9 | 0 | 0–30 % | 11 (runner setup), 15 (pipeline error) |
| D2 version / API drift | 5, 6, 9, 12, 13, 17 | 4 (5 and 9 are ENV in CONTROL, excluded) | 0 | 0–49 % | none |
| D3 platform (GPU / Docker) | 2, 4, 14 | 3 | 0 | 0–56 % | none |
| D4 build step / own module | 19 | 1 | 0 | 0–79 % | none |

Zero recoveries in every stratum, including D1, the stratum where a name-only fix was the expected easy win. n is at most 16: every interval is wide.

## What the records show (descriptive; none of it is in the rate)

- **Repairs moved failures forward but did not finish them.** In several D1/D2 entries the loop cleared the first error and reached a new one: entry 16 (sklearn, then ruamel.yaml, then
  language_evaluation), entry 20 (six, h5py, skimage, then a missing pretrained checkpoint `caption_models/infos_best.pkl`, i.e. DATA_MISSING), entry 13 (torch_sparse, a missing g++,
  then torch_scatter), entry 1 (tabulate, `collections.Iterable`, then `curves`). Three attempts is too few for a chain of undeclared packages; the attempt limit is a
  design parameter of the harness, not a finding about the repositories.
- **Tavily contributed nothing measurable:** searches ran, but every attempt's `tavily_sources` is empty and the citation log says "not cited (not used in a decision)".
- **Some D1 entries are not D1 underneath:** entry 10 (scipy, then `GPU_REQUIRED`), entry 20 (data file), so the audit's first-error label understates the depth.
- **Entry 6 (rocgan):** three env repairs passed the tamper gate but `numpy` stayed missing under the time machine's 2020-era lock (chainer 7.4.0, py3.8): most likely a build-order problem
  (a package needing numpy at build time), which "add numpy" cannot fix.

## Harness defects seen in the sealed run (reported, nothing changed; a fix needs a new seal and a re-run)

1. **A runner-setup failure caused by the repair's environment, charged to ENV (entry 11).** The time machine locked the 2021 era (py3.9, old pinned torch); the runner's torch op pulled the newest
   numpy (2.x) and its own `import torch` check failed (`_ARRAY_API not found`). It ended INDETERMINATE `RUNNER_SETUP_FAILED`, which hides whether TREATMENT could have recovered the entry.
2. **`compare_batches.py` files that case as REPO_STILL_FAILING**, because only SANDBOX_QUOTA/SANDBOX_INCOMPAT count as sandbox-side. So the 0/16 denominator includes entry 11, a run in which the repo was never
   executed in TREATMENT. Entry 15 (below) is filed NOT_MEASURED. Sensitivity: excluding entry 11 the rate is 0/15 (0 %–20 %).
3. **A repair re-execution that exceeds the 600 s wall clock becomes `PIPELINE_ERROR:sandbox` (entry 15)**, not a TIMEOUT verdict; only the baseline run maps to TIMEOUT. It is NOT_MEASURED in the comparison.
4. **The per-entry $2 ceiling is not hard.** Entry 13 recorded $5.68 and entry 16 $2.50. The guard checks before a step starts; entry 13's third step started with $1.44 remaining and one sandbox operation
   (a long compile) recorded $5.12. The total $25 cap was never at risk ($21.76), but the per-entry ceiling was exceeded twice.
