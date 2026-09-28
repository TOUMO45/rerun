# VOID — corpus-v1 batch records on harness-v1 (2026-09-28)

These three records are the first entries of the corpus-v1 batch started on tag
`harness-v1` (commit `f339077`). The batch was stopped by hand after entry #3 and
**all three are void. None is a measurement of its repository, and none is counted
anywhere.** They are kept, unmodified, as evidence for the harness fixes they exposed.

| # | Entry | Recorded verdict | Why it is void |
|---|---|---|---|
| 1 | neuroailab/Neural-Alignment | BLOCKED `RUNTIME_ERROR_OTHER` | Two harness defects shaped the run: the time machine asked the resolver for the import name `absl` instead of the distribution `absl-py` (the era lock failed), and the classifier's fallback evidence was pip's `[notice] To update, run: pip install --upgrade pip` instead of the real error (`RuntimeError: Python version 2.7 or 3.4+ is required.`). |
| 2 | bluer555/KernelGCN | NOT_ATTEMPTABLE | The Nebius sandbox API timed out uploading the repository (`ApiTimeoutError … /sandboxes/v1/files`, read). Nothing ran. An infrastructure failure recorded as a verdict. |
| 3 | urvashik/knnlm | INDETERMINATE `PIPELINE_ERROR:adjudicator` | Same upload timeout (pool), then the model API timed out. Nothing ran. |

Fixed in `harness-v1.1` (see METHODOLOGY.md, "Harness changes discovered during the
corpus-v1 batch"). corpus-v1 is re-run from scratch, all 20 entries, on `harness-v1.1`;
those records are in `runs/corpus_v1_batch/harness-v1.1/`.
