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

## Amendment 1 — 2026-10-11, committed before the run (nothing above this heading is changed)

Why. Before the launch the owner asked three questions (the `--dataset DATASET` field, why this run should reach a model patch when harness-v1.7.1's ended in a baseline
timeout, and what is reported if the run ends before a model patch). No dry run had been made for this entry. The checks below were made on 2026-10-11 without any API call or
sandbox (evidence in `prerun/`). One finding changes this plan's expectation, so this amendment replaces the expectation and the risks. **The run itself is unchanged**: entry, command,
arm, mode, Tavily, cap $10.00 API-reported, one run, record paths, secret handling.

**A. `--dataset DATASET` is not an unfilled field in effect.** `main_optim.py` declares `--dataset_path` (required); argparse accepts the prefix `--dataset`, so the program gets
the relative folder name `DATASET`, and `lib/data/datasets.py` calls `torchvision.datasets.CIFAR10(root=DATASET, download=True)`: the program downloads CIFAR-10 (170,498,071 bytes)
into that folder. No harness-v1.10.0 rule ends a run on it: `R5_PLACEHOLDER` (backend/app/batch/command_rules.py) is a corpus-draw eligibility rule and needs an underscore;
`DOCUMENTED_PATH_PLACEHOLDER` (diagnosis.py, harness-v1.9, D-73) only words the diagnosis after a DATA_MISSING verdict, and its pattern does not match a bare `DATASET` (tested: no
match). In 6 of the 7 recorded M-FAC runs (harness-v1.3.2 control and treatment, v1.5.0, v1.5.1, v1.5.2, v1.6.0) the program got past argparse and the data load. On 2026-10-11 12:42 UTC the download URL answered
301 to `cave.cs.toronto.edu`, which answered 200 with the full length (torchvision follows the redirect).

**B. The model is not expected to see the LU error.** The rationale above rests on harness-v1.5.2's adopted model patch for `torch.lu(..., pivot=False)`. harness-v1.7 (R2) added a
CPU reference kernel for LU without pivoting to the `cpu_shim` hook, written for this entry (runner_hooks.py, item 7). At harness-v1.10.0 the LU failure is answered by that
deterministic step, with no model call. The local dry check (`prerun/`: WSL, torch 2.14.0+cpu, Python 3.13; the exact hook source harness-v1.10.0 installs; M-FAC at 8116367; the
corpus command verbatim; CIFAR-10 replaced by a random stand-in only, because this machine cannot fetch 170 MB and WSL has no torchvision):

* run A, as documented: `AttributeError: module 'torch._C' has no attribute '_cuda_setDevice'`, the failure of every recorded baseline. harness-v1.10.0 classifies it GPU_REQUIRED, which
  gets the `cpu_shim` step;
* run B, with the `cpu_shim`: `RERUN_CPU_SHIM_PATH: cpu_ref:torch.lu` (the LU kernel answered), training starts, and the first optimizer step ends in M-FAC's
  `nn.parallel.parallel_apply` with `RuntimeError: Cannot access accelerator device when none is available.` (the error harness-v1.6.0 recorded after its LU patch). It is
  GPU_REQUIRED with the shim already spent: no deterministic step is left, no stop rule applies (`entry_blockers`: none; not a sandbox code), and the repair layer is `code`, so
  the repair loop calls the model (Tavily search, then candidates);
* run C, B plus a sequential replacement of the three `parallel_apply` calls (`prerun/patch_c.py`, a stand-in for an honest model patch): training runs to the 75 s limit with no
  error, past the 60 s smoke window.

**Revised expectation** (replaces the one above; still an expectation, not a criterion). If the baseline completes, the first model patch targets `parallel_apply` in `optim.py`, not
the LU call. The flag's static check (`behaviour.candidate_findings`, `prerun/flag_static_check.json`) marks all three plausible honest fixes tried offline: COMPUTATION_CHANGED, plus
WORKLOAD_PARAMETER_CHANGED for one written as a `for` loop. If such a patch is adopted, the certificate should carry REVIEW_REQUIRED with COMPUTATION_CHANGED, on an honest device
fix. That would show the flag's positive path on a live run. It would not show that the flag finds cheats. The original expectation (COMPUTATION_CHANGED on an LU patch) is not
expected to be tested, and item 5 will say so.

**Revised risks.**
1. The baseline. Its first act is the 170 MB download from a third-party host. The only recorded M-FAC baseline that did not complete is harness-v1.7.1's (TIMEOUT: 21.5 s of setup,
   then no recorded progress until the 600 s limit; the killed step's measured cost was $0.0001, that is, no CPU time). The other entries of that batch ran normally that morning.
   The four completed baselines from harness-v1.5.0 to v1.6.0 took 84–95 s. A stall ends the run TIMEOUT with no model patch.
2. Adoption. The one recorded round on the accelerator error (harness-v1.5.1, repair 3) adopted none of its 3 candidates: all left the outcome unchanged. This run has up to
   3 attempts of 3 candidates on it. Proposed is likely; adopted is open.
3. The flag mode runs the static half only (no tracer).

**What is reported if the run ends before any model patch** (clarifies the plan's wording; changes nothing). Items 1–7 apply whatever the run gives. Read literally, "INFRA_ERROR
before any model call" covers only intake, because the recon and planner models are called before the baseline. A baseline TIMEOUT or a baseline INFRA_ERROR is therefore the run's
result: verdict and code (1); no Tavily search, because searches are made per repair attempt (2); no model attempt and no `behaviour` field (3); no `review` on the certificate (4);
the expectation not tested (5); the API-reported cost and the BILLED readings (6); and that the run shows nothing about the flag's positive path (7). It is not run again on my
decision. Whether anything else is done is the owner's decision.
