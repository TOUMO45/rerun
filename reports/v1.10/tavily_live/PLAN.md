# harness-v1.10.0: one live run of minmaxot in flag mode with Tavily on — pre-registration (committed before the run)

Owner's directive of 2026-10-11/12. **Post-hoc, a single labelled run, never a measurement or part of any count or rate** (not TEST, TEST-B, TEST-C, DEV or any benchmark table).

## Purpose: the Tavily gap only

The flag-mode wiring check of 2026-10-09 (`runs/v1.10/live_v110/02_stephaneckstein__minmaxot_rc8.json`, GitHub Actions run 37958950100) ran without Tavily context: its
`TAVILY_API_KEY` secret ended with two newlines, the search failed on the header (`[tavily] search failed, continuing without cited context`), and no attempt was offered a
reference. That defect is fixed (the keys were rotated; the launcher refuses a key with whitespace or a line end). This run repeats that entry in the same mode with Tavily
working, to show what the records hold when the search works.

**This is not a second attempt at a flagged result and must not be described as one.** The M-FAC run (`reports/v1.10/review_live/PLAN.md`) was the one run for the flag's
positive path; it ended TIMEOUT and is not repeated. **Expectation about the flag: none.**

## The run

| | |
|---|---|
| entry | `stephaneckstein__minmaxot` (corpus-v4 #2, the wiring check's entry), command `python dcot/base_case.py` |
| code | the working tree at `main`, whose harness paths (backend/app, backend/pyproject.toml, scripts, frontend/src, .gitattributes) equal the tag `harness-v1.10.0`, which equal `harness-v1.10.0-rc8`, the code the wiring check ran; the launcher refuses otherwise |
| command | `scripts/live_run.py --name stephaneckstein__minmaxot --corpus backend/app/batch/corpus_v4/corpus.yaml --dev-run --cost-cap-usd 10.00`, arm `treatment` |
| mode | `BEHAVIOUR_MODE=flag`, as in the wiring check |
| Tavily | on: the launcher refuses unless `TAVILY_API_KEY` is set, has no whitespace or line end, and authenticates. On 2026-10-12 the account had used 246 of its 1000 plan credits; this key, none |
| cap | **$10.00 API-reported** (owner). The wiring check's cap was $5.00 and it spent $3.90; the cap decides nothing unless spend comes near it |
| where | this machine, started through Task Scheduler (D-43). The wiring check ran on a GitHub Actions runner; that route now needs the owner to re-set three repository secrets and dispatch it. The local attempt of 2026-10-09 failed on the upload (`ApiTimeoutError` on `POST /sandboxes/v1/files`, `runs/v1.10/live_v110/attempt2_rc5_infra_error_upload_timeout.json`); on 2026-10-12 this machine uploaded 5 MB at 2.1 MB/s, above the 0.987 MB/s the harness sizes its upload timeout for |
| git source | the local bare mirror of the repository (`%TEMP%\minmaxot_mirror.git`, read through `url.<mirror>.insteadOf`, as the 2026-10-09 local attempt did): the same commit; the harness checks the commit and the tree (`[integrity]`). This machine's link to GitHub is about 30 KB/s |
| record | `runs/v1.10/tavily_live/02_stephaneckstein__minmaxot_v1100.json`, its stdout and launcher lines; counted by `reports/ledger_total.py` through `runs/v1.10/**/NN_*.json` |
| secrets | after the run the launcher withholds any output file that contains a key's value; `reports/scan_history_for_secrets.py --tracked` runs before the commit |

**One run, no retry.** Whatever happens is the result, including an infrastructure failure.

## Why it can show Tavily context (checked before the run, from committed records)

In the wiring check, the baseline failed on `TypeError: Descriptors cannot not be created directly.` (RUNTIME_ERROR_OTHER), no deterministic step matched, and the harness made
its Tavily search before the first model round (the line that failed). The code is the same, so a search is expected at the same point. The same entry at harness-v1.9.0
(`runs/v1.10/mkdir_live/02_stephaneckstein__minmaxot_v190.json`), with Tavily working, made the same search (3 results), offered them to each of its 3 candidates, and the record cites sources on all three. If this run's baseline fails differently, or a
deterministic step clears the failure first, there may be no search: that is reported as it is.

## What will be reported (whatever the run gives)

1. The verdict and the taxonomy code.
2. Tavily: the query; whether the search returned sources and how many (`consulted`); whether the record cites one (`tavily_sources[].cited_via`, `resolved_sources[].cited_by`)
   or gives a reason for not citing (`reason_no_citation`).
3. The candidates proposed, and each attempt's `behaviour` block (static findings, flagged or not).
4. Whether a patch was adopted, and what the certificate says (`review` field included).
5. Beside the wiring check: whether the path and the verdict were the same (descriptive; the model is not deterministic).
6. The API-reported cost and the owner's BILLED readings: $41.96 before (2026-10-11, after the M-FAC run), the after-reading when the owner sends it.
7. What it does not show: anything about a rate, about the flag finding cheats, or about whether a citation shaped a decision (not measured, D-21).
