# Seal of harness-v1.5.1 (2026-10-03) — PASSED

Option B over changed files (METHODOLOGY, "harness-v1.5 dev/test protocol", rule G). Release candidate tag `harness-v1.5.1-rc` (`0fa9607`); the live seal ran against it and the harness paths
were byte-identical to it when `seal_verification.json` was written.

Among the five sandbox-touching files only `runner_hooks.py` changed (F3: the CPU shim's `torch.cuda.set_device`). `sandbox.py`, `sandbox_limits.py`, `runner_env.py` and `smoke_exec.py` are byte-identical to
harness-v1.4.3, so the **15** entries of the v1.4.3 seal that do not list `runner_hooks.py` are carried over with their records (the writer refuses to carry an entry over if any code file it lists has changed).
The **4** entries that list it are re-verified by 8 live checks through the real runner (the v1.4.3 seal's `v142` stage, unchanged, against the new blob):

| check | ok | API-reported USD |
|---|---|---|
| run1_A ready image | yes | 0.012254 |
| run1_B branch run | yes | 0.000542 |
| run1_C hooks on the kept image | yes | 0.001152 |
| run1_W0 exit hook alone sees nothing | yes | 0.000887 |
| run1_W1 wrapper prints the raise site | yes | 0.000945 |
| run1_W2 wrapper on Python 3.6 | yes | 0.001320 |
| run2_E0 calm run with evidence | yes | 0.001212 |
| run2_E1a self-SIGKILL with evidence | yes | 0.001251 |

**Seal spend: $0.019562 API-reported** (cap $0.30; nothing estimated: no step was stopped). Counted in the DEV total (`reports/corpus-v2.1/v1.5/ledger_extras.json`).

The shim's new path (`torch.cuda.set_device` does nothing) is checked against REAL torch 2.14.1 (CPU wheel) offline, in WSL, by `backend/tests/test_v151_cuda_set_device.py`: not a live sandbox check, as in the v1.4.2 seal
(a torch install would cost more than this whole seal). `scripts/run_corpus_v1_batch.py check_seal_verification` accepts the written file against the working-tree blobs.
