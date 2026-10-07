# harness-v1.9, task 4: steamctl at harness-v1.7.2 and harness-v1.8.0 — plan (committed before the first run)

**Question (D-69).** ValvePython/steamctl (out of sample, commit `274a8db`) ended `RUNS_AFTER_REPAIR` in its one harness-v1.7.2 run (2026-10-05) and `BLOCKED DEP_MISSING` in both
harness-v1.8 working-tree runs (2026-10-07). Regression or model variance?

**Runs.** 3 at the tag `harness-v1.7.2` (7a1e0ba) and 3 at the tag `harness-v1.8.0` (b818e5b), each tag checked out as its own worktree, alternating tags
(v1.7.2, v1.8.0, v1.7.2, v1.8.0, v1.7.2, v1.8.0), one fresh backend per run, through RERUN's own API, no entrypoint arguments (as in the OOS scans), driver
`run_steamctl.py`, detached through Task Scheduler (`launch_steamctl.cmd`). Per-run cap $2.00 (the cost guard), so **$12.00 worst case**, the owner's cap.
Ledger before: $161.3095 API-reported; worst case after: $173.3095, inside this pass's $25.00 (stop at $186.31). The earlier runs cost $0.27 to $0.38 each.

**Counted.** "Runs" = the certificate's verdict is `RUNS_CLEAN` or `RUNS_AFTER_REPAIR`, raw. Beside it, not instead of it: D-51 (steamctl's exit 0 follows argcomplete's
activation notice, so even a "run" here does not exercise the tool's work) and whether the run used commit `274a8db`.

**Decision rule (the owner's, applied as written).** Bisect only if v1.7.2 runs at least 2 of 3 **and** v1.8.0 runs 0 of 3. Otherwise D-69 is recorded as variance in the defects
register with the raw counts, and nothing is bisected. The six earlier-or-later records are never pooled with the three earlier runs in the headline count; they are listed beside it.
