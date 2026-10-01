# harness-v1.4.2-rc — Step 1 report (offline; no Nebius call, no spend)

Status: **implemented and unit-tested offline; unsealed; not validated by any gate.** Nothing here claims a recovery. Tags: API-REPORTED (formerly MEASURED) = a stored record field, for a dollar figure the sandbox API's
reported operation cost, not account billing (D-36); DERIVED = computed from named records; ESTIMATED; BILLED = the owner's balance reading. Ledger before Step 2: **$18.5083** [ESTIMATED: $17.3366 API-REPORTED + $1.1717 ESTIMATED],
a lower bound (D-27); the owner's ceiling is $25.00 API-reported. `harness-v1.4.1` (`5ba14a2`) and `harness-v1.4.0` (`15d3cdf`) are untouched.

## 1. Owner's answers, applied

1. **BILLED, v1.4.1 gate:** the owner's reading $49.57 (screenshot, organisation "Louay-ag4", time of day not stated) after the gate; $49.61 before. At most $0.43 [BILLED] charged cumulatively; $0.04 [BILLED] between the readings against $3.8588
   recorded for the same work (about 96x), and the price-table value of the model tokens alone in it was $0.3625: the balance moved less than the model tokens would cost. Recorded in `GATE_REPORT_v1.4.1.md`, `docs/design/D-36.md` section 9, the
   register. D-36 stays open. (The Phase D REPLAY gets the lines in the Phase D update.)
2. **Estimate rate:** from now on a killed step is ESTIMATED at the API's median per billed second x 1.5 = **$0.0152/s**, the rate and its source stored on the cost event (`cost_events[].rate_usd_per_s`, `rate_source`); past estimates are not
   recomputed and carry "computed at $0.0085/s, not an upper bound (D-27)": v1.3.4 #8 $0.2842, v1.4.0 seal attempt at most $0.4998, v1.4.0 gate #8 operation 11 $0.1868, v1.4.1 seal K1 $0.2009 (annotation on D-27 in the register). Consequence, stated:
   the estimate is now ABOVE the rate operations are funded at ($0.0030 to $0.0085 per wall second), so a kill can be recorded for more than the money the operation was funded with; the old test asserting "never more than funded" now asserts
   "exactly the parts" (`test_cost_enforcement_v133.py`). `harness-v1.4.1`'s own test of the $1.25 case moves from $0.30 left to $0.05 left; the conclusion (neither rule saves #11 at $1.25) stands.
3. **Phase D waits for v1.4.2** and then covers all versions: not started.

## 2. The four items, implementation, and the test that pins each

| Item | Defect | Implementation | Tests |
|---|---|---|---|
| 1. Partial progress | D-37 | `adjudicator.adjudicate_candidates(..., current_stage=)`: a "none" (the model's, or no qualifying pass) becomes `partial_progress_choice`: the candidate with the furthest `advance_key` (the repository's own command > install step k > runner setup; the key ignores seconds and ignores whether the run was still running, a longer or silent run is not progress) IF it is strictly further than the failure being repaired; a run that PASSED is never adopted this way (the adjudicator's veto of a pass stands); `adopted_reason` "partial progress" with both stages; Ultra's own pick is labelled "adjudicator", the JSON fallback "fallback: <why>". The orchestrator passes the failing run's stage. The adoption path is the existing one, so the next round starts from the candidate's kept image. | `test_v142_partial_progress.py`: #7 rounds 1-3 from the committed v1.4.1 record (round 1: Box2D is further than pkg-config; once candidate 2 is adopted, round 2's Box2D and round 3's setup failure are NOT further); a pipeline run whose round 2 branches from the adopted candidate's image |
| 2. CPU shim | D-39 | `runner_hooks` shim: `Tensor.cuda()` / `Module.cuda()` return self; `.to("cuda*")`, `.to(torch.device("cuda*"))`, `device=` on Tensor and Module go to the CPU; `torch.device("cuda*")` is the CPU device (a proxy class, `isinstance(x, torch.device)` stays true); each patch stands alone (v1.4.1's was all-or-nothing); each path that acted prints `RERUN_CPU_SHIM_PATH: <path>` once per process and the orchestrator records `time_machine_action.paths_fired`. Limit recorded: factory `device="cuda"` strings, `torch.cuda.*Tensor`, `set_default_tensor_type` are not covered. | `test_v142_cpu_shim.py`: #8's recorded `Torch not compiled with CUDA enabled` (GPU_REQUIRED) reproduced by a fake torch without the shim and gone with it, every path recorded, partial torch still patched; REAL torch: see section 5 |
| 3. RESOURCE_LIMIT | D-38, D-40 | `classifier`: exit 137 / -9 -> RESOURCE_LIMIT (taxonomy, family Platform, a sandbox code; other signals NOT: 139 and 134 are crashes, 143 may be the program's own), attributed to the sandbox (`error_chain`), "our fault" for denominators. `_note_failure` ends the entry INDETERMINATE: ONE evidence run per entry (TREATMENT only, `runner_hooks.evidence_command`: the command runs unchanged in a subshell, then `/proc/meminfo`, `nproc`, kernel, swap, overcommit, `/proc/self/cgroup`, cgroup memory files, `dmesg`, `ulimit` go to stderr and the exit status is kept), the reason quotes what the sandbox showed, else the documented limits; no model attempt. `resource_limits` stored on every operation. | `test_v142_resource_limit.py`: #11's recorded kill (classification; the pipeline: CPU shim, exit 137, evidence, INDETERMINATE RESOURCE_LIMIT, the repair model raises if called); the evidence command run for real with sh (exit status kept, a trailing `# comment` survives); the parser, kill evidence from three sources; baseline and CONTROL (no extra operation); a killed candidate gets no hook or wrapper |
| 4. "exit outside Python" | D-35 follow-up, D-40 | After the exit hook printed nothing and the wrapper printed nothing, the wrapper runs once more WITH the evidence; a kill evidenced (status 137, a cgroup `oom_kill` count > 0, a kernel-log line) -> RESOURCE_LIMIT, otherwise INDETERMINATE EXIT_OUTSIDE_PYTHON with that reason and the evidence; no model attempt. A wrapper that cannot be applied (not a plain python command) changes nothing: the model is still asked. | `test_v141_exit_wrapper.py`: the #3-shaped silent exit ends INDETERMINATE EXIT_OUTSIDE_PYTHON (reason quotes the evidence, the repair client raises if called) or RESOURCE_LIMIT when the evidence shows a kill |

Negative controls (a mechanism disabled, the tests that should notice it fail, the file restored byte for byte): no partial progress, no SIGKILL class, no resource stop, a shim without `.cuda()`, the old estimate rate: each failed the expected tests.

## 3. What the research found about resources (`docs/design/D-40-resources.md`, offline, [direct] / [fetch] / [search] marked)

No source gives a memory or CPU figure for a Sandboxes microVM; no spawn parameter, SDK field, CLI flag or MCP parameter chooses a size; the only documented cap is the 12 GiB writable layer (`resources_limits.max_layer_bytes`); the only
wording is "Automatic cleanup and resource limits help prevent abuse." A larger instance is not documented (beta, access by request, contree@nebius.com); no price page. **That #11's kill is a memory kill is NOT ESTABLISHED** (three separate VMs,
deterministic, `state.timed_out` false by inference). The API does return peak memory per operation (`resources.max_rss`, readable from the SDK object with no new call, same path as `_server_timed_out`), but storing it needs an additive change in
`sandbox.py`: **not done** (it would make every seal entry that lists `sandbox.py` stale, about $0.8 to re-verify, above the ceiling room left); proposed for a later version. The evidence run reads the guest's own view instead. The seal's E1b probe is the
first look at how much memory a process can hold in this sandbox.

## 4. Seal of harness-v1.4.2 and its estimate

Sandbox-touching file changed: `runner_hooks.py` only. The 13 v1.4.1 entries whose code files are unchanged are carried over by `scripts/write_seal_verification_v142.py` (it stops if a blob changed); the three entries that list `runner_hooks.py` are
re-verified; one is new (the evidence command after a kill). **Estimated cost $0.2821 [ESTIMATED]** from the v1.4.1 seal records (A $0.012413, B $0.000628, C $0.001165, W0 $0.000901, W1 $0.000924, W2 $0.001338, API-reported; E0 and E1a a few tenths of a
cent; E1b the 25 s clock bound at the observed $0.0103 per billed second, $0.26, less if a kill comes first). **Cap $0.49, not the owner's $1.00:** ledger $18.5083 + gate cap $6.00 + seal must stay at or under the $25.00 ceiling, which leaves $0.4917.
An operation starts only while 1.5 x its estimate is left. Seal -> gate (owner's rule, unchanged): every seal check passed, branch-run cost at most $0.15, seal spend within the cap.

## 5. Real torch

The shim's new paths touch torch internals (`Tensor.to`, `Module.to`, a `torch.device` proxy): they are checked against REAL CPU torch before sealing, offline and free, in a throwaway environment (`RERUN_REAL_TORCH_PYTHON`; the same test is skipped in an
ordinary run).

REAL-TORCH RESULT (offline, no Nebius call, torch 2.14.1+cpu, Linux in WSL, 2026-10-01): **one defect found and fixed.**
- Plain torch: `.cuda()` on Tensor and Module, `.to("cuda")`, `.to(device=torch.device("cuda"))`, `Module.to("cuda:1")`, `torch.zeros(device=torch.device("cuda"))` and `torch.load(map_location="cuda:0")` all raise (`Torch not compiled with CUDA enabled`).
  `torch.device("cuda...")` alone does not raise on plain torch (it is only a name).
- With the shim (loaded through a real site directory and its `.pth` line): the 9 CUDA calls probed all went to the CPU, `torch.load(map_location="cuda:0")` returned a CPU tensor, all seven shim paths were recorded; 19 of 20 CPU-side checks passed.
- **The defect:** `pickle.dumps(torch.device("cpu"))` raised `PicklingError: Can't pickle <class 'rerun_cpu_shim.device'>`: a real device pickles as `(torch.device, args)`, pickle looks the class up by name, and the proxy class was named after the shim module. Plain torch pickles it.
  A repository that pickles a device (a checkpoint holding one, a multiprocessing argument) would have failed with the shim and passed without it. **Fix:** the proxy class is created with `__module__ = "torch"` and `__qualname__ = "device"` (`runner_hooks.py`).
  After the fix: 20 of 20 CPU-side checks pass, 9 of 9 CUDA calls pass.
- Tests: `test_on_real_torch_cuda_calls_raise_without_the_shim_and_pass_with_it` and the new `test_on_real_torch_what_already_worked_on_the_cpu_still_works_with_the_shim` (14 checks that pass on plain torch: isinstance, `torch.device("cpu", 0)`, pickle, deepcopy, `.to(dtype)`, `.to(tensor)`, `.to("cpu", dtype=..., non_blocking=True)`, `Module.to(memory_format=...)`, DataLoader, DataParallel, forward). Run under WSL with `RERUN_REAL_TORCH_PYTHON=/usr/bin/python3`: 8 passed (the 6 fake-torch tests and both real-torch tests). Negative control: the two proxy-class attributes removed, the new test fails with the `PicklingError`; restored byte for byte, passes.
- Not covered (stated, unchanged): `torch.zeros(2, device="cuda")` with a plain string given to a factory function, `torch.cuda.*Tensor` types, `torch.set_default_tensor_type`, `torch.load(map_location=...)` of a code path that does not go through `torch.load`. The shim is a CPU-only device story, not a claim that the repository's numbers match a GPU run.
- The sandbox's torch is whatever the repository installs (often an older release), so this checks the proxy against one current release, not against every release.

## 6. Found, decisions

1. **The seal cap is $0.49** (ceiling arithmetic), under the owner's $1.00.
2. **EXIT_OUTSIDE_PYTHON is a new INDETERMINATE reason code** (not "our fault"): the harness cannot say why the process left, and does not call it the repository's fault either.
3. **RESOURCE_LIMIT covers SIGKILL only** (137, -9), by choice; the directive's "signal kills" is read as kills from outside the program.
4. **Funding and estimate now use different rates** ($0.0030 to $0.0085 per wall second versus $0.0152 per billed second): a killed operation can be recorded above the money it was funded with (item 1 of section 1).
5. **A kill now ends the entry, where v1.4.1 let nine candidates be refused**: the next version of the #11 record, if the sandbox's limit is the cause, is INDETERMINATE, not BLOCKED, whatever the model proposes.
6. The documented limits are "not documented": nothing is invented on any record.

## 8. Independent review of the Step 1 diff (read-only agent, before any seal) and what it changed

A reviewer with no part in writing the code read `git diff 5ba14a2..HEAD -- backend/app scripts`, ran probes (real torch in WSL, `sh`, `dash`) and reported 8 findings. Each is confirmed from code or by a probe,
fixed, and pinned by a test that a negative control proves (`backend/tests/test_v142_review_fixes.py`, 12 mutations, each noticed, the file restored byte for byte; plus the seal tests, 3 mutations).

| # | Finding (would change a gate result: 1, 2, 3) | Fix |
|---|---|---|
| 1 | A candidate that PASSED, vetoed by Ultra ("passes by doing less"), was adopted as "partial progress" and the entry ended RUNS_AFTER_REPAIR where v1.4.1 ended BLOCKED; a silent run still running counted as an advance over a quick exit. | `partial_progress_choice` ignores runs with exit code 0; the "still running" flag is out of `advance_key`. |
| 2 | The `torch.device` proxy broke pickling (already found and fixed in commit `55d72db`); also `torch.device.type` (class attribute) raised, and `torch.device("cuda", 0)` became `cpu:0`, which is not equal to a CPU tensor's `cpu`. | proxy named `torch.device`; class attributes forward to the real class; every converted device is `torch.device("cpu")`. Real torch: `torch.save` of a Namespace and of a module holding a device pass. Stated limits added to the hook record: `type(d) is torch.device` is False, `torch.device(...)` inside a TorchScript function is not supported. |
| 3 | A candidate that fixed the failure and was then KILLED (137), not chosen by Ultra and at the same stage, was not adopted: four more model calls and BLOCKED, against the owner's rule (INDETERMINATE whatever the model proposes). | `adjudicate_candidates`: a candidate whose run was classified RESOURCE_LIMIT is adopted over a "none" (`adopted_reason` "resource kill", lowest number); the model's own choice is respected. |
| 4 | The evidence run of a BASELINE kill was billed but dropped from `result.attempts`. | the baseline finalisation passes the attempts. |
| 5 | The evidence run: (a) was made for a kill during SETUP, where the sandbox stops before the command, so no block can print (cost, no evidence); (b) was made for a wrapped run that exited 0; (c) its budget stop left `state.cost_capped` set, so the entry ended COST_CAP, and an `InfraError` or `SandboxError` turned a decided RESOURCE_LIMIT into INFRA_ERROR or PIPELINE_ERROR; (d) the `resource_stop` paths never wrote the error chain. | (a) no evidence run outside the `repo_run` phase, the reason says so; (b) a passed wrapped run is a pass; (c) any failure of the evidence run is recorded and the kill's verdict stands, `cost_capped` restored; (d) a kill found by the evidence run is a chain link attributed to the sandbox. For EXIT_OUTSIDE_PYTHON no link is added (the last link is the silent exit attributed REPO by default; the reason code on the verdict is what says "unexplained", and the summaries read it). |
| 6 | The batch summaries (`compare_batches.py`, `run_corpus_v1_batch.py`) listed only SANDBOX_QUOTA / SANDBOX_INCOMPAT as sandbox-side: an INDETERMINATE RESOURCE_LIMIT with a failing control was categorised REPO_STILL_FAILING. The certificate prose for the two new reasons read "Recon could not establish enough confidence". | RESOURCE_LIMIT is sandbox-side; **decision, reversible: EXIT_OUTSIDE_PYTHON is NOT_MEASURED** in those summaries (the harness cannot say why the process left; it is neither the repository's column nor the sandbox's). Prose written for both. |
| 7 | The evidence's `ulimit` section grepped bash's wording and was always empty under dash (Debian slim images); the cgroup files were read only at the mount root. | `ulimit -a` (first 30 lines, no wording filter); the process's own cgroup (from `/proc/self/cgroup`) is read as well, and the larger `oom_kill` count of the files counts. |
| 8 | The seal records carried no file blob, so an edit of `runner_hooks.py` between the live seal and the writer would have been accepted (same gap as v1.4.1). | every seal record carries `code_blobs` (taken when it is written); `write_seal_verification_v142.py` stops on a missing or stale blob. |

Nothing serious was found in `evidence_command` and `parse_evidence` (16 command shapes under dash: trailing comment, quotes, `&&`, redirects, heredoc, `kill -9`, `set -e`, trailing `&`), `cost_guard` (both `record_killed_operation` call sites and
`record_spend`), the CONTROL arm (no extra operation) or the seal writer's carry-over logic (16 minus 3 gives 13, plus 4 new; a changed blob stops it).

Not fixed, stated: a documented command that ends in a backslash would break the evidence command's `)`; the shim was not run on torch 1.x with Python 3.6 (the source parses under the 3.6 grammar; the real-torch check is torch 2.14).

## 7. What remains

Step 2 (live): seal at most $0.49, tag `harness-v1.4.2` only if every check passes, gate under the stated rule (entries 3, 7, 8, 11; entry cap $1.50; gate cap $6.00; hard stop), each entry reported as it lands. Then all live work stops and the Phase D
update follows. Tag `harness-v1.4.2-rc` on the Step 1 commit (unsealed, used in no gate figure).
