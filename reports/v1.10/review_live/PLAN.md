# harness-v1.10.0: one live run in flag mode with Tavily on — pre-registration (committed before the run)

Owner's directive of 2026-10-10, Step 1. **Post-hoc, a single labelled run, never a measurement or part of any count or rate** (not TEST, TEST-B, TEST-C, DEV or any benchmark table).

## Why one run

The Phase A report named two gaps. (1) No live run has produced a certificate with REVIEW_REQUIRED: the flag's positive path is shown by the test suite only. (2) The flag-mode
wiring check of 2026-10-09 ran without Tavily context (its search failed on a malformed secret). This run is meant to close both if it can; whatever it produces is reported.

## The entry: `IST-DASLab__M-FAC` (corpus-v2 #14, a DEV entry, already DEV-CONTAMINATED)

Chosen from the honest repairs the recorded analysis flags (`reports/v1.10/flag/flag_table.json`): harness-v1.9.0 adopted five honest controls that the flag marks, three of them
M-FAC's (`M-FAC-control-03`, `-04`, `-05`), one FeatureScatter's and one patchSmoothing's. Why M-FAC and not the other two, decided from committed records before the run:

* The flag marks only an adopted **model** patch. The last live repairs of patchSmoothing (harness-v1.5-final) and FeatureScatter (harness-v1.6.0, v1.7.1) were deterministic
  steps with no model call (`cpu_shim`; the removed-API pin): a run of either would most likely give the flag nothing to judge.
* M-FAC's last repair that ran (harness-v1.5.2, `runs/corpus_v2_batch/harness-v1.5.2/dev/14_IST-DASLab__M-FAC.json`) was a model patch: a CPU replacement for the GPU-only
  `torch.lu(..., pivot=False)`, adopted, RUNS_AFTER_REPAIR. This is the run erratum E-3 is about (it ran on a changed algorithm).
* **Expectation, derived offline before the run:** harness-v1.10.0's static checks (`behaviour.candidate_findings`) on that recorded adopted patch give `COMPUTATION_CHANGED`
  (twice). If the model writes a patch of the same kind and it is adopted, the certificate should carry REVIEW_REQUIRED. This is an expectation, not a criterion.
* **Known risks, stated before the run:** M-FAC's run at harness-v1.7.1 ended TIMEOUT in the baseline (killed at the 600 s wall clock, no repair attempted) and at harness-v1.6.0
  BLOCKED after 10 attempts. The documented command contains the unfilled field `--dataset DATASET` and `CUDA_VISIBLE_DEVICES=0`. The run can end without any adopted model
  patch, and then it shows nothing about the flag's positive path.

## The run

| | |
|---|---|
| code | the working tree at `main`, whose harness paths (backend/app, backend/pyproject.toml, scripts, frontend/src, .gitattributes) equal the tag `harness-v1.10.0`; the launcher refuses otherwise |
| command | `scripts/live_run.py --name IST-DASLab__M-FAC --corpus backend/app/batch/corpus_v2/corpus.yaml --dev-run --cost-cap-usd 10.00`, arm `treatment` (full RERUN) |
| mode | `behaviour_mode = flag` (the shipped default; set explicitly in the launcher's environment) |
| Tavily | on: the launcher refuses unless `TAVILY_API_KEY` is set and has no whitespace or line end |
| cap | **$10.00 API-reported** (owner) |
| where | this machine (M-FAC is 20 files; the earlier uplink failures were 20 MB and 56 MB uploads), started through Task Scheduler (D-43) |
| record | `runs/v1.10/review_live/14_IST-DASLab__M-FAC_v1100.json`, its stdout and launcher lines; counted by `reports/ledger_total.py` through `runs/v1.10/**/NN_*.json` |
| secrets | after the run the launcher withholds any output file that contains a key's value, and `reports/scan_history_for_secrets.py --tracked` runs before the commit |

**One run.** There is no second attempt to obtain a flagged result. If the run ends INFRA_ERROR before any model call, that is reported and the owner decides whether it is
run again; nothing is re-run on my own decision.

## What will be reported (whatever the run gives)

1. The verdict and the taxonomy code.
2. Tavily: whether a search was made before a repair attempt, whether it returned sources (how many), and whether the model cited one.
3. Every model attempt's `behaviour` field (`mode`, `static` findings, `flagged`), and whether the adopted patch, if any, was a model patch.
4. Whether the certificate carries `review` with status REVIEW_REQUIRED, its reasons and findings, and whether `GET /runs/{id}/certificate` would show it (the same record field).
5. Whether the derived expectation above held.
6. The API-reported cost, and the owner's account-balance readings before and after (BILLED, if given).
7. What the run does **not** show: anything about a rate; whether the flagged patch is a cheat (the flag says a human should look; this patch may be an honest CPU port, as
   the three M-FAC controls were, or a changed computation, as erratum E-3 found).
