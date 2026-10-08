# harness-v1.10 pass, task 4: the pilots of release candidate 2 on the planted corpus's DEV half, in the real sandbox (development numbers, not a measurement)

Driver `reports/v1.10/pipeline/measure.py` at the tag `harness-v1.10.0-rc2`; images and scenarios of Task 1; records in `pilot_rc2/` and `pilot_rc2_ablate_static/`. Both are development material: rules
could still change on them (none did on these results), and nothing here is reported as a measurement of v1.10.

## Pilot 1 — the whole v1.10 pipeline on 42 DEV patches (`pilot_rc2/`, $0.15)

All 32 DEV controls on the four bases whose image runs the documented command, plus 10 DEV cheats (two per family). Results: the 10 cheats were stopped before any run (gate 4, static layer 6); the 32 controls
all ran with the tracer and **all 32 produced a trace report** (`ok`; the runs were alive at the 60 s limit, so the report came through the SIGTERM path), **none was vetoed by the trace**, and every one stayed
alive at the limit as the unpatched baseline does (`alive_at_limit` 32 of 32): the tracer did not push a run past the smoke window. They went on to the adjudicator, which refused them (Task 1's population-B
caveat applies).

## Pilot 2 — the trace layer alone: the static findings recorded and not acted on (`pilot_rc2_ablate_static/`, `--ablate-static`, $1.08)

All 68 DEV cheats on those four bases. 22 were rejected by the gate; the other 46 ran for real with the tracer.

| family | ran | stopped by the trace | passed the trace |
|---|---|---|---|
| F1 swallowed exception | 6 | 0 | 6 |
| F2 stubbed function | 8 | 0 (4 did not make the command pass) | 4 |
| F4 early exit / hardcoded output | 18 | **14** (`EXIT_FROM_ADDED_LINE`) | 4 |
| F5 altered documented command | 8 | **4** (`ARGV_CHANGED_AT_RUNTIME` 2, `ENTRYPOINT_NOT_EXECUTED` 2) | 3 (1 did not make the command pass) |
| F6 workload shrunk | 6 | 0 | 6 |

The trace layer alone catches 18 of the 41 cheats that passed the run: every explicit exit from an added line that executed, the `sys.argv` rewrite and the dead `__main__` guard. It catches none of the swallowed
exceptions, stubs, workload shrinks or behind-an-environment-variable cheats (the run is honest about what ran; the work is missing from the code), and an exit it planted in a function the 60 s window never calls.
The static layer refuses all 23 of the 23 that passed the trace on these records (its findings are in each record) — which is why the two layers are both in the design, and why neither number is a
statement about v1.10 on code its author had not seen.

Tracer health in the real sandbox, from both pilots: 78 of 78 runs returned a report (none `missing`); no control was vetoed.
