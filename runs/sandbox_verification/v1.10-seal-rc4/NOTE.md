# The live seal of harness-v1.10.0-rc4 — NOT passed (archived; superseded by the seal of rc5)

Run 2026-10-08 22:36 to 2026-10-09 10:18 (Africa/Algiers) through the Task Scheduler entries `RERUN_v110_seal` and `RERUN_v110_seal_stages`, cap $1.50.
Spend $0.1404 API-reported (`SEAL_RUN.json`, the sum of the stages' operation costs).

| stage | result | what happened |
|---|---|---|
| `v140` | not passed, 10 invocations | A, B, C, D passed every time. E (corpus-v2 entry 7, `albertometelli/pfqi`, built as a checkpoint) never started: first the `git fetch` of the repository timed out 4 x 300 s (about 20 KB/s from this machine to GitHub that night; a local bare mirror read through `GIT_CONFIG_*` `insteadOf` fixed that part, see `launcher.txt`), then the upload of its 56 MB tree stopped every time with `ApiTimeoutError` on `POST /sandboxes/v1/files`: the harness sizes that timeout for at least 0.987 MB/s (`timeouts.sandbox_transport_timeout`, 87 s for 56 MB) and the upload from this machine measured about 0.4 MB/s. An infrastructure stop, not a check that failed. |
| `smoke` | **passed** | the six smoke-launcher records, Python 3.10 and 3.6 (run with `--stage smoke --stage v110` after the v140 stops; only the order changed). |
| `v110` | **NOT passed: a defect** | T1-T5 passed on `python:3.6-slim` and `python:3.7-slim`. On `python:3.10-slim` T1 (an honest run that exits 0) reported `entry_main: false` and the exit in `//train.py`: Python 3.9+ names a script run from `/` as `//train.py`, POSIX `normpath` keeps the two leading slashes, and the tracer's file mapping did not recognise the entry file, so it raised `ENTRYPOINT_NOT_EXECUTED` on an honest run (and would have missed an exit from an added line in the entry file). |

The defect is fixed in harness-v1.10.0-rc5 (`behaviour.py`, two lines in the tracer's `classify`; regression test
`test_seal_v110_a_script_run_from_the_root_on_python_39_is_its_entry_file`, which fails on rc4 with exactly this report). Its reach in the measurement of
rc4 on the independent set (`reports/v1.10/RESULT.md`): one repository runs that way (patchSmoothing, tracebacks in `//train_mnist_band.py`); none of its
traced records has a `__main__` body or a failure site in the entry file to check, and no cheat reached a run at v1.10, so no measured outcome depends on it.
