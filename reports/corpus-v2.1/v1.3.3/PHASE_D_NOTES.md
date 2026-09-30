# Notes carried to Phase D (product surface)

- **Passports carry `image_id` separately from `record_id`.** A sandbox run whose chain retains no image (no install step: the smoke-launcher runs and the kill runs of the seal verification) reports the
  BASE IMAGE's id as its sandbox id, so several records share one id (`dbfbe818...` is `python:3.10-slim`). The passport therefore must not treat the sandbox/image id as the identity of a run: it carries
  `image_id` (what the sandbox ran on) and `record_id` (a unique id of the stored record, e.g. its `entry_id` + arm + harness tag + the record's SHA-256) as two fields, and the verify script keys on `record_id` and the SHA-256.
  Source: `runs/sandbox_verification/final-v1.3.3/README.txt`.
- Passports must also carry, per repair attempt, the new v1.3.3 evidence fields when present: `execution` (smoke mode, seconds, outcome: a pass means "ran for that long without failing", never "completed"), `patch_notes`,
  `model_patch`, and `tavily_sources[].cited_via` (`model_declared` or `git_source`).
- REPLAY must label v1.3.2 (pre-registered) and v1.3.3 (exploratory, development set) records as different runs everywhere they appear.
