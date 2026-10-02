# Gate v1.4.3, attempt 1: interrupted, no record (2026-10-02)

The first start of the gate (`run_gate_v143.py --gate-cap-usd 7.00 --entry-cap-usd 1.75 --go`, preflight OK at `085d12bf4acc`, tag `harness-v1.4.3`) ran as a child process of the Claude session that started it. That session ended while the gate was inside entry **#3**, and the process was killed with it. **No entry record, no gate result and no verdict exist from this attempt.** Nothing in it is a gate result and none of it is counted in the gate: the gate was started again from the beginning (attempt 2, same tag, same caps, same entries and order); the records of attempt 2 are the gate.

What is known, from the process's own stdout (`interrupted_attempt_20261002_stdout.txt`, kept unedited):

- the pre-batch upload smoke test passed (`runs/corpus_v2_batch/harness-v1.4.3/gate/upload_smoke_20261002T113722Z.json`, $0.00497 API-reported);
- entry #3 had completed 8 recorded sandbox operations, **$0.7005 API-reported** (sum of the log's `[cost_guard] recorded` lines), with $0.9712 of its $1.75 cap left, and had started its next operation (repair 2, candidate 3, launched at 453.8 s) when the process was killed; that operation's cost is **not known** (an operation the client abandons returns no cost);
- model calls of the attempt are not in the log's sandbox sum.

The ledger counts this attempt as a lower bound: **$0.7055 API-reported** (the 8 operations and the smoke test) plus an unknown amount for the abandoned operation and the model calls. It counts against the $32.00 ceiling and not against the gate cap, because it produced no record of the gate. The kept images of the attempt were not released (the SDK has no delete call).

Lesson, and the change in how the gate is run: a paid batch must not be a child of the session that starts it. Attempt 2 runs as a detached process.
