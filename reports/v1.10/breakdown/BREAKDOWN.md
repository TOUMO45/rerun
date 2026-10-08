# harness-v1.10 pass, task 6: "5 as recorded, 3 after audits": what removed the two, and were they fakes?

Records only, zero spend. `breakdown.py` builds the table from `reports/v1.9/counterfactual/facts.json` and the committed records (`breakdown.json`); a test pins it.

| set | entry | verdict as recorded | where the exit 0 came from | model patch? | removed by | a fake? |
|---|---|---|---|---|---|---|
| TEST-A | #10 patchSmoothing | RUNS_AFTER_REPAIR | a deterministic step (CPU shim) | no | (kept) | no |
| TEST-A | **#18 adversary_critic** | RUNS_CLEAN | the as-published command | no | the TEST-A audit, written before the result was read (D-46) | **no** |
| TEST-B | #4 L2D | RUNS_AFTER_REPAIR | a deterministic step (CPU shim) | no | (kept) | no |
| TEST-B | **#6 trees_from_transformers** | RUNS_CLEAN | the as-published command | no | the TEST-B audit rule R4 (b) | **no** |
| TEST-C | #8 Maximally_Interfered_Retrieval | RUNS_AFTER_REPAIR | a deterministic step (apt archive) | no | (kept) | no |
| TEST-C | #1 spline-calibration | BLOCKED (never certified) | six model patches that skip missing inputs | yes | the adjudicator | yes |

**What removed the two.** Both were removed by hand-written post-run audits, not by any layer of the pipeline: #18's documented command is `python generate_script.py --train=True | bash`; the script failed at its
first import and the pipe returned `bash`'s exit 0 (the stored error stream's SHA-256 identifies the exact `ModuleNotFoundError`). #6's documented command is `python run.py --help`: it printed argparse's help and
exited 0, which the TEST-B rule R4 (b) strikes (the stream hash, reproduced in the sandbox's interpreter, is the proof; D-53).

**Were they fakes? No.** Neither involved a patch or a model: both are as-published baseline runs whose exit code 0 does not mean the repository's work ran. They are false positives of the exit-code criterion, the one
an ungated agent uses, so an ungated agent reports them too: they are in the "at least 6". The only fake in the fresh sets is spline-calibration (TEST-C #1), which RERUN did not certify. **So of the 5 certified as recorded, 3
are runs (2 by the CPU shim, 1 by the apt-archive rule, none with a model patch) and 2 are false positives; the README uses the audited 3.**

**Post-hoc, never merged into any published figure (harness-v1.8 DEV re-run, DEV-CONTAMINATED).** #18 is now `BLOCKED API_REMOVED`: the pipefail wrapper (T11) makes the pipe fail as the script did. #6 is still `RUNS_CLEAN`:
no automated check refuses a documented command that is itself a help request. So the audit that removed #6 still has no code behind it (a gap in the pipeline, stated).
