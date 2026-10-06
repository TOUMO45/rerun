# TEST-B: corpus-v3, harness-v1.7.2 (run 2026-10-06, once, as pre-registered)

**Pre-registration:**
- `backend/app/batch/corpus_v3/prereg.json`, sha256 7b2f53f9…, committed in the harness-v1.7.2 release candidate (f401eda) before any candidate was screened.
- Drawn once afterwards (d6e99a3; firewall self-check passed; corpus_hash 99b52da7…).
- Run once at the sealed tag `harness-v1.7.2` (7a1e0ba) by `reports/test-b/run_test_b.py` from the Task Scheduler. Nothing was re-run and nothing was tuned.
- Records: `runs/corpus_v3_batch/harness-v1.7.2/treatment/`; result: `test_b_result.json` (written by the script, not edited).

## The primary measure, as pre-registered

**RAN: 1 of 8** (1 without a semantic change; 0 resource-adapted; 0 sole-candidate).
- It is a count over 8 entries, one run each: not a rate.
- RAN says the documented command ran. It does not say the paper's result was reproduced.
- 2 of 8 had a RUNS_* verdict at smoke level, and both were "confirmed" under the TEST phase's rule. The stricter RAN rule keeps 1.
- The TEST phase's numbers (2 of 8 confirmed, 1 of 8 ran) belong to harness-v1.7.1 code and are not pooled with these.

| id | entry | verdict | what happened | RAN |
|---|---|---|---|---|
| 1 | yikangshen/Ordered-Neurons | BLOCKED `RUNTIME_ERROR_OTHER` | NLTK's `ptb` corpus (the Penn Treebank sample) is not installed: a missing dataset, classified as a generic runtime error (see below) | no |
| 2 | vlievin/ovis | INDETERMINATE `DEP_YANKED` | pins `torchvision==0.6.0a0`, a pre-release that pip does not serve | no |
| 3 | alexlee-gk/video_prediction | BLOCKED `DEP_BUILD_FAILED` | a dependency failed to build under Python 3.10 (TensorFlow-era stack). The recon model also used its whole output budget without answering; RERUN fell back to the documented command, as designed | no |
| 4 | zcajiayin/L2D | RUNS_AFTER_REPAIR `GPU_REQUIRED` | **ran.** The as-published run needed CUDA. The deterministic CPU shim (no model call, no code patch) let `python3 test_learned.py` run to completion inside the smoke window: it scheduled 100 job-shop instances, printed each makespan and its total time (19.39 s), and exited 0. No traceback; the D-46 audit strikes nothing | **yes** |
| 5 | twitter-research/cwn | BLOCKED `DEP_NOT_ON_PYPI` | the documented command is the README's `sh graph-tool_install.sh`; `graph_tool` is not on PyPI (conda only). E5_v2's install rule (stem `^(setup\|install)`) does not catch a stem that only ends in `_install`, and the registration is not changed | no |
| 6 | galsang/trees_from_transformers | RUNS_CLEAN | the documented command is `python run.py --help`: it printed argparse's help and exited 0. Struck under R4 (b), a usage message (see the correction below) | no |
| 7 | Stilwell-Git/Hindsight-Goal-Generation | BLOCKED `DEP_MISSING` | `mujoco_py` (MuJoCo, a licensed simulator binary) is not installable | no |
| 8 | CSAILVision/gandissect | BLOCKED `SYS_LIB_MISSING` | `ft2build.h`: FreeType headers are missing for a source build | no |

## A correction, stated beside the result (the script's output is not edited)

- **What the script wrote.** `run_test_b.py` struck #6 under R3 ("an exit 0 that printed nothing").
- **Why that reason is wrong.** The record of an as-published (baseline) run keeps only each stream's length and SHA-256, not its text. The script's `final_output` read the missing text as empty.
- **What the record shows.** The run printed 1,209 bytes on stdout (sha256 `c879491a…`) and 96 on stderr. R3 therefore does not apply.
- **What does apply.** Reproduced locally in `python:3.7-slim` (the sandbox's interpreter), with the script's imports stubbed, `python run.py --help` at the pinned commit prints exactly 1,209 bytes with SHA-256 `c879491a1f75a415ef9bc3d0baefb00551fb2520561f591ca5ce6705e99d9723`, identical to the recorded stream. Evidence: `reports/test-b/audit_06/` (the stub runner and the reproduced text). The text begins `usage: run.py [-h] …`, so the pre-registered R4 (b) strike applies.
- **The count does not change:** RAN 1 of 8.
- **D-53** (open, a defect of the TEST-B evaluator, not of the harness): R3 and R4 cannot read a baseline run's text from the record. Such a strike must come from the stream hashes, as here.

## What TEST-B shows

- **The working path.** The one entry that ran did so through a deterministic rule (the CPU shim, R2-era code), not through a model repair.
- **The model repairs.** Across the 8 entries, no model patch led to a run.
- **The blockers.** Six of 8 ended on a blocker named in the record's own words: a yanked pin, a build failure, a conda-only package, a licensed simulator, missing system headers, and a missing NLTK corpus.
- **Misclassification (D-54, open).** #1's missing NLTK resource (`Resource ptb not found`) was classified `RUNTIME_ERROR_OTHER` and not `DATA_MISSING`.
- **Corpus definition.** Two of the 8 documented commands are not runs of the paper's code (#5 is an install script; #6 prints help). That is a limit of the corpus-v2 command rule this registration reused unchanged.

## Cost

- Entries: $7.5546 (cost guard: API-REPORTED plus the estimate of any killed step).
- Sustained runs: $0.00. No entry needed one: #4 finished inside the smoke window, and #6 finished as published.
- TEST-B cap: $95.00.
- Ledger after TEST-B: $98.2375 API-REPORTED of the $300.00 ceiling.
- A BILLED reading after TEST-B has not been given yet.
