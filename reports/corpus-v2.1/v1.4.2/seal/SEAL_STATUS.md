# Seal of harness-v1.4.2 (option B over changed files only): COMPLETE — all checks passed (live, 2026-10-01)

Caps (owner, chat 2026-10-01): seal at most $1.00 (effective $0.49 by the ceiling arithmetic: $25.00 ceiling - $18.5083 ledger - $6.00 gate cap = $0.4917), gate $6.00, entry $1.50, ledger ceiling $25.00 API-reported.
Tags: API-REPORTED = a stored record field (the sandbox API's `resources.cost`, not account billing, D-36), ESTIMATED, BILLED = the owner's balance reading. Records: `runs/sandbox_verification/v1.4.2-seal/`
(`run_seal_v142.py`, run 1 with cap $0.49, inspected; then run 2 with the remainder $0.4726, inspected). Every record carries `code_blobs` (the git blob of `sandbox.py` and `runner_hooks.py` when it was
written) and `scripts/write_seal_verification_v142.py` checked them against the files now. Changed sandbox-touching file: `runner_hooks.py` only; the other four are byte-identical to harness-v1.4.1, so the 13
v1.4.1 entries that do not list `runner_hooks.py` are carried over; the three that do are re-verified (C, W0, W1, W2) and one is new (E0, E1a, E1b).

| Op | What | ok | Cost [API-REPORTED] | Run id |
|---|---|---|---|---|
| A | ready image on python:3.10-slim (one pip step), tree and setup layers kept | true | $0.012351 | `f0884780-98b1-44f1-a619-9adfb9c34d94` |
| B | ONE branch run from A's deepest layer (overlay one file, run it); no setup step ran | true | $0.000576 | `37a6de11-04ab-4235-8d50-74892ed74909` |
| C | exit-site hook and CPU shim installed on A's kept image; the hook printed the exit site of `sys.exit(3)` inside `leave()` | true | $0.001184 | `57fd4610-9fd4-4c11-9dc4-609f07d96c64` |
| W0 | bare `raise SystemExit(1)` with the hook installed: exit 1, stderr EMPTY (the gap, D-35) | true | $0.000875 | `c00f8c5d-9697-45e3-9488-a4236932451b` |
| W1 | the same script through the exit wrapper: exit 1, the traceback of the raise on stderr (`RERUN_EXIT_WRAPPER: ... SystemExit: 1`) | true | $0.000987 | `b93dd2af-8147-4451-b96e-867589c90109` |
| W2 | the wrapper on python:3.6-slim: the same raise site on Python 3.6 | true | $0.001409 | `0dc34722-9fd0-46a6-8c80-6eff57cd2139` |
| E0 | the evidence command around a calm run (`sys.exit(3)`): exit status 3 kept, stdout kept, the evidence block parsed by the harness's own parser | true | $0.001201 | `27dcff91-bd72-40d2-8769-506835306545` |
| E1a | a process that SIGKILLs itself: exit 137, the shell says `Killed`, `kill_evidenced` true (from the exit status) | true | $0.001223 | `ea85e4c3-3709-4aa6-bbf0-3d56b5cb2e42` |
| E1b | INFORMATIONAL: a process that allocates 64 MiB at a time until the kernel stops it | true (informational) | $0.025226 | `7d24dc4d-05f0-4267-9588-88fb4985f1b9` |

## Spend

Seal: **$0.045032 API-REPORTED** (run 1 $0.017381, run 2 $0.027650); no operation was stopped, so no ESTIMATED part. Planned ESTIMATED $0.2821, cap $0.49. Ledger: **$18.5533**
[ESTIMATED: $17.3816 API-REPORTED + $1.1717 ESTIMATED], a lower bound (D-27); under the owner's ceiling of $25.00; room left $6.4467, the gate cap is $6.00.

## Seal -> gate rule (owner, automatic)

Every seal check passed (9 of 9 operations `ok`; 4 paths verified for v1.4.2); the measured branch-run cost (B) is $0.000576 API-REPORTED, at most $0.15; seal spend $0.0450, at most $0.49.
**All hold: the gate starts automatically.** `seal_verification.json` was written by `scripts/write_seal_verification_v142.py` (17 paths: 13 carried over, 4 for v1.4.2, 29 live run ids); tag `harness-v1.4.2` on the seal commit.

## What the live checks showed that the fake cloud cannot

- **The first look at the sandbox's own limits (E0, E1a, E1b; [from the records], one probe on python:3.10-slim, three separate VMs):** `/proc/meminfo` MemTotal **4,034,744 kB (3.85 GiB)**, MemAvailable 3,846,816 kB, SwapTotal 0, `nproc` **4**, kernel `7.0.6`,
  `ulimit -a` unlimited for memory and virtual memory (the wording is dash's: `memory(kbytes)`, `vmemory(kbytes)`, which the evidence command now keeps whole), `/proc/self/cgroup` `0::/`, no readable cgroup memory file (no `memory.max`, no `memory.events`).
- **E1b: a process that allocated 64 MiB at a time printed `ALLOCATED_MB 3776` and was killed.** The shell printed `Killed`, the exit status was 137, and the kernel log held `python3 invoked oom-killer` and `Out of memory: Killed process 74 (python3) total-vm:3942376kB, anon-rss:3906368kB`.
  So in this sandbox **a process that holds about the VM's whole memory is killed by the kernel's OOM killer with exit 137**, with no cgroup in between. That is what a "memory limit" is here: the VM's size (3.85 GiB), not a documented figure (D-40-resources.md: none is documented). One probe: it says that
  memory exhaustion produces exactly the exit status #11 showed (137, `Killed`); it does NOT say that #11's kill was memory (that is what the evidence run of the gate reads, on #11 itself).
- The evidence command behaves under the real dash shell: the command's own exit status is kept (3, 137), stdout is untouched, the block is printed once, and the parser reads every field (the `selfcgroup` read of the process's own cgroup returned `0::/`, the same as the mount root).
- The hooks, the wrapper (python 3.10 and 3.6) and the branch run behave as in v1.4.1.

## Kept images (for the billing page; no charge observed on the account balance so far, BILLED line in the gate report)

6 distinct image ids kept by this seal (layers of A, C, W0, W1; B and E0..E1b kept none):
- `652faec4-50c6-4525-b041-4ca2bf07619a`
- `f0884780-98b1-44f1-a619-9adfb9c34d94`
- `46005807-5423-47c0-ad22-1eb9f5a3835c`
- `6a9aac8f-55f2-4506-a546-e4bf6ea87994`
- `4ddc72b7-d061-423d-83b9-fccbc807f510`
- `aebfd136-a2f5-47a0-a969-8b895a93ad75`
