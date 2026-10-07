# harness-v1.9, task 4: steamctl at harness-v1.7.2 and harness-v1.8.0 — result (2026-10-08, as it came out)

Plan committed before the first run (`PLAN.md`, 5f7d372). Six runs, alternating tags, each from its own worktree at the tag's commit (preflight: HEAD = tag, harness paths
clean, `app` imported from the worktree), one fresh backend per run, commit `274a8db` every time, detached through Task Scheduler (launch 00:13, done 00:36 local).

| tag | run | verdict | class | attempts | API-reported (cost guard) |
|---|---|---|---|---|---|
| harness-v1.7.2 | 1 | BLOCKED | DEP_MISSING | 10 | $0.3011 |
| harness-v1.8.0 | 1 | BLOCKED | DEP_MISSING | 10 | $0.4155 |
| harness-v1.7.2 | 2 | INDETERMINATE | `ENTRYPOINT_UNCLEAR: model could not identify a confident entrypoint among the candidates` (recon, before any sandbox operation) | 0 | $0.0000 (no guard line; one recon model call, its cost not recorded by the guard) |
| harness-v1.8.0 | 2 | BLOCKED | DEP_MISSING | 10 | $0.3753 |
| harness-v1.7.2 | 3 | BLOCKED | DEP_MISSING | 10 | $0.1501 |
| harness-v1.8.0 | 3 | BLOCKED | DEP_MISSING | 10 | $0.1431 |

**Raw counts: harness-v1.7.2 ran 0 of 3; harness-v1.8.0 ran 0 of 3.** Spend $1.3851 API-reported of the $12.00 cap.

**Decision (the owner's rule, applied as written):** bisect only if v1.7.2 runs at least 2 of 3 and v1.8.0 runs 0 of 3. v1.7.2 ran 0 of 3, so **no bisect**; D-69 is recorded
as variance in the defects register. Beside it, not pooled into the counts above: the one earlier v1.7.2 run (2026-10-05) was RUNS_AFTER_REPAIR and the two earlier v1.8 runs
(2026-10-07) were BLOCKED, so over every steamctl run on record v1.7.2 is 1 of 4 and v1.8 is 0 of 5. The one success needed the repairer to propose the `sys.path` patch to
`steamctl/__main__.py` in its third round; nothing in these six runs shows a code difference between the tags deciding it. A seventh behaviour appeared: at v1.7.2 run 2,
recon (a model call) could not pick an entrypoint, which is model variance before any execution. D-51 stands beside all of it: even the earlier "run" was an exit 0 after
argcomplete's activation notice, not the tool's work.

Records: `runs/v1.9/steamctl/<tag>/run<k>_certificate.json` (the UI's download form) and `run<k>_api_certificate.json`, `summary.json`, `run_stdout.log`, `launcher.txt`.
