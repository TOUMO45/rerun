# VOID — corpus-v1 batch records on harness-v1.1 (2026-09-28)

All records in this folder come from the corpus-v1 batch on tag `harness-v1.1`
(commit `2c8178e`), including the re-queued attempts in `void_infra/` and the second
attempts of #5 and #6 at the top level. **They are void: none is counted anywhere.**
corpus-v1 is re-run from scratch, all 20 entries, on `harness-v1.2`
(`runs/corpus_v1_batch/harness-v1.2/`). Kept unmodified as evidence.

**Reason: a deterministic harness defect.** harness-v1.1 never set the Nebius sandbox
SDK's HTTP `transport_timeout`, so its silent default of **10 s** applied: every upload
that took longer than 10 s timed out, on every attempt. #6 mlohaus/SearchFair (30.6 MB
archive) and #5 expressGNN/ExpressGNN (125.6 MB) failed identically twice
(`INFRA_ERROR:sandbox:ApiTimeoutError`) while small smoke uploads passed. The circuit
breaker stopped the batch both times. Fixed in harness-v1.2 (explicit timeouts, transport
timeout scaled to the archive size, pre-declared upload cap).

| # | Entry | Verdict on harness-v1.1 | Note |
|---|---|---|---|
| 1 | neuroailab/Neural-Alignment | BLOCKED `RUNTIME_ERROR_OTHER` | superseded by the v1.2 re-run |
| 2 | bluer555/KernelGCN | RUNS_AFTER_REPAIR (deterministic) | **valid but superseded**: 200 training epochs and test accuracy printed, tree and passport verified (13.3 MB archive, under the 10 s window). Re-run on v1.2 so all 20 come from one harness. |
| 3 | urvashik/knnlm | BLOCKED (COMMAND_NOT_A_RUN) | superseded |
| 4 | Lucas2012/ProbabilisticNeuralProgrammedNetwork | BLOCKED `DEP_YANKED` | superseded |
| 5 | expressGNN/ExpressGNN | INFRA_ERROR ×2 (`void_infra/` = attempt 1, top level = attempt 2) | the 10 s transport timeout |
| 6 | mlohaus/SearchFair | INFRA_ERROR ×2 (same) | the 10 s transport timeout |
