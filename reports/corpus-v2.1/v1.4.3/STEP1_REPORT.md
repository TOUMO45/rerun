# harness-v1.4.3-rc — Step 1 report (offline except the D-41 probe)

Status: **implemented and unit-tested offline; unsealed; not validated by any gate.** Nothing here claims a recovery. Tags: API-REPORTED (formerly MEASURED) = a stored record field, for a dollar figure the sandbox API's reported operation cost, not account billing (D-36);
DERIVED = computed from named records; ESTIMATED; BILLED = the owner's balance reading. Ledger before the seal: **$22.5421** [ESTIMATED: $21.3704 API-REPORTED + $1.1717 ESTIMATED], a lower bound (D-27); the owner's ceiling is **$32.00** API-reported.
`harness-v1.4.2` (`64e5f0e`), `harness-v1.4.1` (`5ba14a2`) and `harness-v1.4.0` (`15d3cdf`) are untouched.

## 1. Owner's answers, applied

1. **Headline and rule:** the wording and the replacement rule are in `METHODOLOGY.md` ("The D-41 probe and harness-v1.4.3-rc") and are applied in the Phase D update after the gate; nothing on a product surface changes before it.
2. **Ceiling $32.00**; probe cap $0.05; seal cap $1.50; gate cap $7.00, entry cap $1.75. Arithmetic: $22.5421 + $1.50 + $7.00 = $31.0421, **$0.9579 below the ceiling**.
3. **D-41 annotation of every EXIT_OUTSIDE_PYTHON and silent-exit record** ("stderr truncated at 65,535 bytes, D-41", verdicts unchanged): Phase D, after the gate. What it can honestly say per record is in section 6.
4. **Reclassifications** (D-23/D-24 fixed-and-gated, EXIT_OUTSIDE_PYTHON as not measured): in force; OUTPUT_TRUNCATED joins EXIT_OUTSIDE_PYTHON as NOT_MEASURED.

## 2. The probe

`D41_PROBE.md`; record `d41-probe/probe_03_vmtl_op5@51727e649a26a37f0646ec1e0107bf1708cd175c086b75a13c09b0f8b48bc7f2`. **D-41 confirmed:** #3's real stderr is 400,939 bytes; the SDK returned 65,535; the raw API result's stderr `truncated` flag was true; the tail is a CUDA `AssertionError` at `.cuda()`.
Cost $0.048615 API-reported (the recorded operation cost $0.047575; the "about $0.002" of the v1.4.2 report was an estimate for a smaller read and was wrong for the full command).

## 3. The four items, implementation, and the test that pins each

| Item | Implementation | Tests |
|---|---|---|
| 1. D-41 | `sandbox.py`: the clients of `_run_once` and `run_on_image` ask for `default_truncate_output_at = 4 MiB` (`OUTPUT_LIMIT_BYTES`); every `StepResult` carries `stdout_truncated`/`stderr_truncated` (the raw API result's flags), `streams()` = size and sha-256 of what came back per stream, and `max_rss` as returned (D-40); the extract-cost fold keeps every field (`dataclasses.replace`; the positional rebuild had dropped them). `orchestrator.py`: `operations[].streams` and `max_rss` on every operation; `output_cut_without_error` (a failed command whose cut stream holds no error text) ends INDETERMINATE `OUTPUT_TRUNCATED` at the top of the repair loop and after the exit wrapper's run (no hook, wrapper, evidence run or model attempt); the evidence run says "cut by the API" instead of "printed no evidence block"; a candidate whose stream was cut is not a "silent exit" (no hook is installed on it). | `test_v143_output_limit.py` (200 KB stderr keeps #3's real traceback, recovered from the probe record; the same run with the old limit loses it; the flag is read from the raw result; sizes are bytes; the fold keeps the fields; `run_on_image`; the SDK has no memory/instance parameter), `test_v143_pipeline.py` (the #3 chain reaches the CPU shim with no hook and no model call; with the old limit it ends OUTPUT_TRUNCATED; an error in the cut start keeps its classification; a cut candidate gets no hook, an uncut one still does; the wrapper's and the evidence run's cut streams), `test_v143_summaries.py` |
| 2. Entry cap $1.75, gate cap $7.00 | `reports/corpus-v2.1/v1.4.3/gate/run_gate_v143.py`: no defaults, both on the command line; `gate_budget.check_gate_caps(7.00, 1.75, 4)` passes exactly | `test_v143_gate_runner.py` |
| 3. Larger instance for #11 | **No parameter exists** (SDK 0.3.6: no memory, CPU, size, flavor or instance field on `run()`, `RunRequest` or `InstanceSpawnRequest`); no rule; #11 stays INDETERMINATE RESOURCE_LIMIT with the kernel line quoted. The API returns peak memory per step: stored (`max_rss`). | `test_contree_sdk_0_3_6_has_no_memory_cpu_size_or_instance_parameter` |
| 4. Sustained-run line (D-42) | `app/services/sustained_run.py` + `sandbox.run_on_image` + the smoke attempt's `execution.image` (`orchestrator.command_image`) + `run_gate_v143.sustained_phase`: after the four entries each RUNS_* entry whose smoke run was alive at its limit is re-executed once from its final image for up to 600 s, funded with its share of what the gate cap has left; the outcome is `sustained_<NN>_<name>.json` beside the record; non-gating | `test_v143_sustained_run.py`, `test_v143_pipeline.py` (image recorded), `test_v143_gate_runner.py` |

Negative controls (a mechanism disabled, the new tests that should notice it fail, the file restored byte for byte): 28 mutations (the client without the raised limit, `run_on_image` without it, the flag never read, the extract fold dropping the fields, the OUTPUT_TRUNCATED check disabled at each of
its four places, a cut candidate given the hook, the image not recorded, `command_image` ignoring a patch overlay, no stream record, the funding reserve, the chosen-attempt selection, every smoke pass sustained, the minimum funded time, the client-side stop's estimated cost, the share and the carry-over of
what the earlier sustained run used, the summaries and prose without the new code, the seal precondition, a foreign SEAL_RUN.json, the final-stage cost check, the writer's stale-blob, failed-record and missing-stage checks, and S1's whole-stream check): **27 caught; 1 equivalent** (S1 without its exact-content test still fails on the byte count when the stream is cut: the two checks overlap).

## 4. The D-41 deviation from the directive's wording

The directive asked to tee stdout/stderr to files on every run and, when `truncated` is set, re-fetch the full stream from a file in the kept image. **Not implemented, deliberately:** (a) the command's own run is disposable, so a file it writes is never in any kept image; (b) a tee changes the executed command of every run, the
baseline included (CONTROL comparability; `sh` is dash on the Debian slim images); (c) the SDK's own per-run limit returns up to 4 MiB whole (#3's stream is 0.4 MiB), and a stream beyond it is labelled instead of guessed. The directive's own test (200 KB on stderr keeps the last traceback) passes, and its negative control fails as it should.
What remains lost: the end of a stream over 4 MiB (labelled OUTPUT_TRUNCATED when it matters); the SDK itself decodes a returned stream with a strict `.decode()`, so a cut that splits a multi-byte character would raise inside the SDK (pre-existing; not changed; found by reading `contree_sdk/sdk/objects/image_like/result.py`).
If the owner wants the file-based mechanism anyway it is a v1.4.4, not an edit of this version.

## 5. Cost of the sustained-run line, stated

A sandbox second costs about $0.0104 [API-REPORTED records], so 600 s is about $6.2 (the owner's $0.0152/s rate: $9.12). v1.4.2's gate left $3.065 of a $7.00 cap after its entries. Funded from what is left, shared equally, at $0.0152/s with a $0.05 reserve: **198 s for one run, 97 s each for two**; below 90 s nothing is run and the record says so.
So "600 s or to completion" will usually be a shorter window, said in the label ("funding-limited"). A command that sleeps or waits costs far less per second than a CPU-bound one (a killed `sleep 300` was reported at $0.00005), so a window can end at its time limit having cost little; the funding rule does not rely on that.

## 6. What the probe changes for the records already committed

Only entry #3 is confirmed by the probe. For every other EXIT_OUTSIDE_PYTHON or silent-exit record, the stored tails (2,000 characters) cannot show whether the stream was cut: before v1.4.3 no record stored the flag. The annotation in the Phase D update is therefore worded per record: "stderr truncated at 65,535 bytes, D-41" for #3 in every version (identical stored
tails ending at the same progress value, and the probe), and "not checked: the flag was not stored before harness-v1.4.3" for the other silent-exit records. Verdicts are unchanged.

## 7. Seal of harness-v1.4.3 and its estimate

`sandbox.py` changed and every entry of the v1.4.2 seal lists it, so all 17 are re-verified by re-running their live checks unchanged, plus two new entries. **ESTIMATED $1.2945** (the earlier records' own API-reported costs; K1's stopped step at $0.0152/s for a 15 s operation limit), cap **$1.50**; an operation starts only while its earlier cost is left under the cap.
Stages in order: new S1-S4, v1.4.1 checks, v1.4.2 checks (the informational allocation probe is not repeated), v1.4.0 checks (a kept image reopened after a 600 s wait), the 14 verifier-script checks (three torch installs are $0.60 of the total). The driver refuses to start unless HEAD's harness paths equal the tag `harness-v1.4.3-rc` and are clean; `SEAL_RUN.json` carries the blobs; the writer refuses a stale one.
Seal -> gate (owner's rule, unchanged, automatic): every seal check passed, branch-run cost at most $0.15 API-reported, seal spend within its cap; otherwise stop and report.

## 8. Independent review of the diff

(filled in below)
