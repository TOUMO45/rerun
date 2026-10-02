# Gate v1.4.3, attempt 1: interrupted, no record (2026-10-02)

The first start of the gate (`run_gate_v143.py --gate-cap-usd 7.00 --entry-cap-usd 1.75 --go`, preflight OK at `085d12bf4acc`, tag `harness-v1.4.3`) ran as a child process of the Claude session that started it. That session ended while the gate was inside entry **#3**, and the process was killed with it. **No entry record, no gate result and no verdict exist from this attempt.** Nothing in it is a gate result and none of it is counted in the gate: the gate was started again from the beginning (attempt 2, same tag, same caps, same entries and order); the records of attempt 2 are the gate.

What is known, from the process's own stdout (`interrupted_attempt_20261002_stdout.txt`, kept unedited):

- the pre-batch upload smoke test passed (`runs/corpus_v2_batch/harness-v1.4.3/gate/upload_smoke_20261002T113722Z.json`, $0.00497 API-reported);
- entry #3 had completed 8 recorded sandbox operations, **$0.7005 API-reported** (sum of the log's `[cost_guard] recorded` lines), with $0.9712 of its $1.75 cap left, and had started its next operation (repair 2, candidate 3, launched at 453.8 s) when the process was killed; that operation's cost is **not known** (an operation the client abandons returns no cost);
- model calls of the attempt are not in the log's sandbox sum.

The ledger counts this attempt as a lower bound: **$0.7055 API-reported** (the 8 operations and the smoke test) plus an unknown amount for the abandoned operation and the model calls. It counts against the $32.00 ceiling and not against the gate cap, because it produced no record of the gate. The kept images of the attempt were not released (the SDK has no delete call).

Lesson, and the change in how the gate is run: a paid batch must not be a child of the session that starts it. Attempt 2 runs as a detached process.

## What followed (same day)

- **Attempt 2a:** started again as a detached process through WMI (`Win32_Process.Create`). It passed preflight and the first upload smoke test ($0.00081 API-reported) and then **died within about ten seconds, before the second smoke test finished and before any entry started**; no traceback was written (its stdout is kept as `runs/corpus_v2_batch/harness-v1.4.3/gate_attempt2a_died_after_upload_smoke_1.txt`). Spend: the first smoke test, plus the second smoke test's operation if it had started (at most $0.0042 API-reported by the first attempt's figure). No entry, no record.
- **Attempt 2b (the gate):** started through the Windows Task Scheduler (`schtasks`), which no tool session can kill, with the exit code written to the log. Its upload smoke tests passed and entry #3 started at 13:35 local. Entries #3 and #7 landed; **the process died again inside entry #8** (about 32 minutes after it started, no traceback, no exit-code line; the Task Scheduler recorded the exit code 0xC000013A, STATUS_CONTROL_C_EXIT: a console control event ended it; what sent it is not known). Its stdout is kept as `runs/corpus_v2_batch/harness-v1.4.3/gate_attempt2b_stdout_until_it_died.txt`. Entry #8 had completed 7 recorded operations, **$0.7861 API-reported**, with $0.9251 of its cap left, when it died: no record, not counted in the gate.
- **Attempt 2c (resume):** the records of attempt 2b for #3 (BLOCKED DATA_MISSING, $0.9435) and #7 (BLOCKED RUNTIME_ERROR_OTHER, $0.6735) are complete records of the gate; the gate runner got `--resume` (keep the complete records already written, run only the other entries, the order and the entry cap unchanged) and `--log-file` (no console: the process is `pythonw` started by the Task Scheduler, so no console control event can reach it). Entries #8 and #11 run in this invocation, then the sustained-run line. A full restart was not possible: the ledger lower bound after the interrupted attempts is **$27.09** (below), so $32.00 - $27.09 = $4.91 is what the ceiling still allows. **The gate cap of this invocation is $6.25** (the pre-registered $7.00 less the $0.75 the ceiling no longer allows), which leaves the two remaining entries their full $1.75 cap and about $1.13 for the sustained runs, and a worst case of $31.72 on the ledger.

## Ledger after the interrupted attempts (lower bound, API-reported unless marked)

| Item | USD |
|---|---|
| ledger after the v1.4.3 seal | 23.9728 |
| attempt 1: 8 operations of #3 and the upload smoke test (one abandoned operation not known) | 0.7055 |
| attempt 2a: upload smoke test 1 (and smoke test 2's operation if it had started, at most 0.0042) | 0.0050 |
| attempt 2b: the two upload smoke tests | 0.0050 |
| attempt 2b: entry #3 (record) | 0.9435 |
| attempt 2b: entry #7 (record) | 0.6735 |
| attempt 2b: entry #8 (7 recorded operations, no record) | 0.7861 |
| **total** | **27.0914** (ceiling 32.00, room 4.9086) |

The three abandoned operations (attempt 1, entry #8 of attempt 2b) and the model calls of the unrecorded entries are not in the table: the true figure is higher by an amount that is not known.
