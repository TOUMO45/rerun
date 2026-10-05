# Out-of-sample scan of harness-v1.7.2 (2026-10-06): five new public repositories

**Label: OUT-OF-SAMPLE for harness-v1.7.2.** This is the only out-of-sample result for v1.7.2 outside TEST-B. Every run below is REAL and was run once, with no re-run and no tuning afterwards. A defect it shows is recorded as a known limit.

**How the repositories were picked.** The rule is `select_repos.py` (its docstring): five GitHub topics, and for each the first search result that passes RERUN's firewall and has Python code. It was committed before the pick ran. The pick (`selection.json`) was committed before any scan ran (3736ad5).

**How they were run.**
- At `harness-v1.7.2` (7a1e0ba, sealed), through RERUN's own web API: `reports/live_scan/run_live_scan.py`, launched by `launch_scan.cmd` from the Task Scheduler.
- One fresh backend per repository, entry cap $2.50.
- The UI passes no arguments, so neither did the scan.
- Records: `runs/live_scan/oos_v1.7.2/`. All five downloaded-format certificates pass `scripts/verify_passport.py`.
- Spend: $1.2620 from the cost guard's own totals. The ledger is $90.6829 API-REPORTED of the $300.00 ceiling.

| topic | repository | verdict as recorded | what actually happened |
|---|---|---|---|
| cli | ValvePython/steamctl | RUNS_AFTER_REPAIR | **Not real work.** The entrypoint `steamctl/__main__.py` was run as a file, so `import steamctl` failed. Over 3 repair rounds, a requirements change, `-e .` and a pip pin were rejected or did not help. The adopted patch inserts the repository root into `sys.path` in `__main__.py`. The CLI then started with no subcommand, printed its argcomplete activation notice and exited 0. Nothing was run: no command was given. The fix a human would make is a command change (`python -m steamctl`), not a code patch. |
| web-scraping | n0kovo/fb_friend_list_scraper | BLOCKED `API_REMOVED` | `AttributeError: module 'OpenSSL.SSL' has no attribute 'SSLv2_METHOD'`: the newest pyOpenSSL removed an API the dependency chain uses. Named correctly; not repaired within the cap ($0.44). Even with it fixed, the scraper needs a Facebook login the sandbox does not have. |
| game | Frimkron/mud-pi | INDETERMINATE `ENTRYPOINT_UNCLEAR` | No candidate was found. The server script runs its loop at module level and reads no arguments, so module-level discovery (which keys on `sys.argv` / argparse) did not see it. $0. |
| data-visualization | njanakiev/openstreetmap-heatmap | BLOCKED `API_REMOVED` | `module 'bpy.ops.object' has no attribute 'select_by_layer'`: the script is a Blender script and needs the Blender API of its era. Named correctly; the human must supply that Blender release. $0.35. |
| automation | awekrx/AutoDoc-ChatGPT | INDETERMINATE `ENTRYPOINT_NEEDS_ARGS` | `main.py: error: the following arguments are required: -file`. Correctly stopped, with no repair. The tool also needs an OpenAI key. $0.09. |

**Honest summary: 0 of 5 did their work.** Two were blocked on a correctly named removed API. Two stopped as INDETERMINATE: one honestly (it needs its arguments), and one because discovery missed a module-level server. The one RUNS_AFTER_REPAIR is a false success: the program started and printed its no-argument notice. The records are left as written; the corrections are stated here.

## Known limits recorded from this scan (not fixed: no tuning after an out-of-sample result)

- **D-50: a package's `__main__.py` is run as a file.** Discovery picked `steamctl/__main__.py` and ran `python steamctl/__main__.py`, where the package expects `python -m steamctl`. The repairer then made a code change (`sys.path.insert`) that a command change would avoid. The semantic-change flag does not cover it, and the patch does not change what the program computes.
- **D-51: an exit 0 after a CLI's no-argument notice counts as a run.** The D-46 check catches a traceback, a `usage:` line and missing-credential messages. It does not catch a help or notice text with no `usage:` prefix. The TEST-B audit (rule R4) has the same blind spot for such text, and the pre-registration is not changed.
- **D-52: a module-level script that reads no arguments is not a candidate** (mud-pi's server loop).
