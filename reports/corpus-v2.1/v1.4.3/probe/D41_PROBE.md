# D-41 probe: the SDK truncated #3's stderr and the error was behind the cut

Date: 2026-10-02. Owner's instruction: rerun #3's recorded failing operation from its kept image with the stream sent to a file and fetched, and read the SDK `truncated` flag; cap $0.05 [API-REPORTED].

**Record id: `d41-probe/probe_03_vmtl_op5@51727e649a26a37f0646ec1e0107bf1708cd175c086b75a13c09b0f8b48bc7f2`** (`runs/sandbox_verification/d41-probe/probe_03_vmtl_op5.json`, sha-256 of the committed blob). Script: `reports/corpus-v2.1/v1.4.3/probe/run_d41_probe.py`.

## What ran

One operation, on the kept image `31ff7d2a-841d-45fb-8f1f-2dc3ee8961fa`, the image that operation 5 of `harness-v1.4.2/gate/03_autumn9999__vmtl` ran on. The command is the recorded one, rebuilt by the functions the orchestrator used (`runner_hooks.wrap_entry_command`, `runner_hooks.evidence_command`, `smoke_exec.wrap`): `python feature_vgg16.py #gpu_id #split` through the exit wrapper, the evidence suffix and the 60 s smoke launcher. Inside the run its stdout and stderr went to files; the run printed their sizes and hashes, every line that is not a bare progress line, and the tails; the stderr file was then replayed on the run's own stderr so the SDK returned what it returns for an unredirected operation.

## Result (all API-REPORTED by the run itself unless marked)

| Observation | Value |
|---|---|
| Size of the real stderr (file written by the command) | 400,939 bytes |
| Size the SDK returned for the replayed stream | 65,535 bytes |
| `truncated` flag of the raw API result, stderr | **true** |
| `truncated` flag of the raw API result, stdout | false (nothing written to stdout) |
| `ContreeResult.truncated` | true |
| Bare progress lines in the real stderr | 67,558, the last one `100.0%` |
| Other lines | 58, from line 67,561 on (byte offset far beyond 65,535) |
| Exit code | 1 |
| Cost of the probe | $0.048615 (the recorded operation cost $0.047575) |

The real stderr ends with a Python traceback that the SDK never returned:

```
  File "feature_vgg16.py", line 38, in experiment
    model = network_dict["vgg16"]().cuda() # base model
  ...
  File "/usr/local/lib/python3.6/site-packages/torch/cuda/__init__.py", line 47, in _check_driver
    raise AssertionError("Torch not compiled with CUDA enabled")
AssertionError: Torch not compiled with CUDA enabled
```

followed by the evidence block (`RERUN_EVIDENCE_BEGIN ... RERUN_EVIDENCE_END`) that the harness looked for and, finding none, wrote "the run printed no evidence block".

## What it means

- D-41 is confirmed, not only suspected: the SDK cuts each stream at 65,535 bytes and keeps the head; everything printed after that point is lost. `sandbox.py` never read the flag.
- #3's "silent exit" in every version was a CUDA error (`.cuda()` on a CPU-only torch) behind 65,535 bytes of download progress. The CPU shim, which handles exactly `.cuda()` (D-39), never ran on #3 because the harness did not know the error. The verdict `EXIT_OUTSIDE_PYTHON` ("printed no error", "no evidence block") was produced by the cut, not by the program.
- The evidence run could not have found anything on any entry whose command writes more than 65,535 bytes to a stream before it fails: the evidence block is printed last.
- The VM figures in the evidence block match the earlier ones: 4,034,744 kB, 4 CPUs, no swap, kernel 7.0.6. The cgroup and `dmesg` reads printed nothing here.

## Cost against the cap

The recorded operation cost $0.047575, so a faithful rerun costs about $0.048: the cap of $0.05 left room for one run only. The "about $0.002" I wrote earlier was an estimate for a smaller read and was wrong for the full command. The probe cost $0.048615, under the cap.
