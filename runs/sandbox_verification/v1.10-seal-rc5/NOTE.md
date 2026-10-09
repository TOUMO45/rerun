# The live seal of harness-v1.10.0-rc5 — partial (archived; superseded by the seal of the flag-mode release candidate)

Run 2026-10-09 10:34-10:39 (Africa/Algiers) from this machine through the Task Scheduler entry `RERUN_v110_seal_stages`, cap $1.50, $0.0351 API-reported
(`SEAL_RUN.json`). **Stage `smoke` passed** (six records). **Stage `v110` passed**: T1-T5 on python:3.6-slim, python:3.7-slim and python:3.10-slim, including the Python 3.10
T1 that failed on rc4 (`entry_main: true`, the exit in `train.py`). **Stage `v140` was not run**: its entry-7 check uploads a 56 MB tree, and this machine's upload link
(0.16-0.4 MB/s) cannot meet the harness's upload timeout (sized for 0.987 MB/s; ten invocations of rc4's seal stopped on it).

The flag-mode release candidate changes harness paths, so its seal starts over (every stage) on a GitHub Actions runner (`.github/workflows/v110-seal.yml`); this
directory is kept as the record of what rc5 showed.
