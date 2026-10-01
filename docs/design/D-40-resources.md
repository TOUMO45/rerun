# D-40 (resources): memory and CPU limits of one Sandboxes microVM, and what RERUN can record about them

Status: research note, 2026-10-01, offline. No Nebius / Token Factory / ConTree API call, no key, no spend, no sandbox call; nothing committed.
Trigger: corpus-v2 #11 (JindongGu/VoteAttack) is "Killed" (exit 137) at iteration 1 of 40 in three separate operations (gate v1.4.1 ledger operations 3, 4, 5, each
about 9.2-9.5 sandbox seconds, outcome `completed`).
**Headline: no source gives a memory or CPU figure for a Sandboxes microVM, and none documents a way to choose a size. That the #11 kill is a memory kill is
NOT ESTABLISHED.** The API does return peak memory per operation, and the SDK already holds it in an object sandbox.py reads, but RERUN stores none of it (Q1, Q4).

Tags: [direct] = text read in the page or file itself (public docs pages downloaded as `.md` from docs.tokenfactory.nebius.com with curl, no credentials; contree.dev
HTML; local files). [fetch] = a WebFetch summary. [search] = a WebSearch snippet (weakest). I did not fetch the API host (`eu-north.nebius.computer/static/api.yaml`);
the docs pages embed the same OpenAPI text. All 128 pages of llms.txt for the Sandboxes docs (guides, CLI, MCP, SDK, API reference), billing and rate-limits were
grepped for memory, RAM, vCPU, cores, GPU, OOM, cgroup, swap, signal, limit, price (the rate-limits page is the inference service; it was not used).

## Q1. Memory and CPU limits of one operation; do `run(...)` and the specs accept resource parameters; which result fields exist

What the sources say
- Docs give no figure. The only wording: "Automatic cleanup and resource limits help prevent abuse." (sandboxes/overview.md:83) and "Built-in tracking of CPU time, memory
  usage, and I/O operations for every execution." (overview.md:35) [direct]. Beta limitations (overview.md:94-95): "Number of simultaneously running operations is limited to 50."
  and "Checkpoint images retention is set to 180 days." [direct]. contree.dev lists "MicroVM per execution", "Dedicated kernel, hardware boundary", "Timeout kills runaway code",
  "Output capped", "Startup takes 0.4-2 seconds per microVM" and nothing on RAM or vCPU [direct]. MCP docs: "Spins up an isolated microVM (~2-5 seconds)", "Default timeout: 30 seconds"
  (sandboxes/mcp/concepts/core.md) [direct]. The one "memory" number in the docs is an illustrative output sample, `"resources": {"cpu_time_ms": 150, "memory_mb": 64}`
  (sandboxes/mcp/resources.md:139); it is not a limit.
- API spawn request (api-reference/sandboxes/instances "Spawn a new container instance", schema InstanceSpawnRequest) [direct]: `command`, `image`, `args`, `shell` (default false),
  `env`, `preserve_env`, `cwd`, `uid`, `gid`, `disposable` (default false), `hostname` (default `linuxkit`), `stdin`, `files`, `timeout` ("Maximum execution time in seconds"),
  `truncate_output_at` (default 1048576, max 10485760), `networking.enabled` (default true) and `resources_limits.max_layer_bytes` ("Maximum writable layer size in bytes.",
  default 12884901888). That is the only key under `resources_limits`: a disk-layer cap, no memory, no CPU. 12884901888 is exactly 12 GiB (12 x 1024^3); sandbox_limits.py
  encodes the Nebius email of 2026-09-29 ("12 GB of filesystem changes per single operation", "128 MB per uploaded file") and reads 12 GB as decimal, the smaller reading.
  That email, as encoded in sandbox_limits.py:1-5, has no memory or CPU figure [direct, local].
- CLI `contree run` flags: -t/--timeout, -C, -e, -H, -D, -I, -s, -F, --file-excludes, -T/--truncate, --preserve-env, -d, --use; MCP `run` parameters: command, image, shell, disposable,
  directory_state_id, files, wait, timeout, env, cwd, stdin, truncate_output_at. None sets memory or CPU [direct].
- SDK contree-sdk 0.3.6 (installed): `run(command|shell, args, env, cwd, hostname, stdin, stdout, stderr, tag, files, timeout, disposable, truncate_output_at, preserve_env)`
  (sdk/objects/image_like/_base.py:126-143). The request it sends, `InstanceSpawnRequest` (_internals/models/instance.py:78-92), has command, image, hostname, args, shell,
  env, cwd, disposable, stdin, timeout (default 60), truncate_output_at, files, preserve_env. It has no memory, CPU, uid, gid, resources_limits or networking field, so the SDK
  cannot ask for a size. Client defaults: `operation_timeout` 1000.0, `default_truncate_output_at` 65535 (config.py:35, 46) [direct].
- Token limits: API "Get current token information" (`GET /v1/whoami`) returns `limits`: "Map of resource limit names to their values for the current token." with the example
  keys `instance_max_timeout` 3600, `instance_max_concurrency` 10, `images_import_max_concurrency` 5, `images_import_max_timeout` 3600 (an example, not live values; no memory key
  shown) [direct]. SDK: `WhoAmI.limits` (utils/models/auth.py:9); public `get_token_info()` (sdk/client/_sync.py:21, _async.py:20); the SDK reads only `instance_max_timeout` and
  `images_import_max_timeout`, and only warns (sdk/client/_base.py:117-122). A grep of backend/app, scripts and phase_d finds no `get_token_info`/`whoami` call: RERUN never loads limits.
  Not called now (it is an API call).
- D-36 already states "The sandbox VM size is undocumented"; nothing found here changes that.

Result model, every field (OpenAPI text [direct]; SDK file:line [direct])
- API OperationResponse: uuid, kind, status (PENDING, ASSIGNED, EXECUTING, SUCCESS, FAILED, CANCELLED), error, created_at, duration, image_size, **consumed_cpu** ("CPU seconds
  (user_cpu_time + system_cpu_time) reported by the in-VM init"), **consumed_memory** ("Peak memory (max_rss) reported by the in-VM init; units preserved as reported by getrusage"),
  image_uuid, result_image_uuid, metadata, result{image, tag}. `metadata` = the spawn request plus `result` = InstanceResult{resources, state, stdout, stderr}.
- `resources` (API text; SDK `ProcessResources`, instance.py:9-24): block_input, block_output, cost, elapsed_time, involuntary_switches, **max_rss** (API: "Maximum resident set
  size in KB"), monotonic_time, page_faults, page_faults_io, shared_memory, signals, swaps, system_cpu_time, unshared_memory, user_cpu_time, voluntary_switches.
- `state` (API text; SDK `ProcessState`, instance.py:29-35): continued, core_dump, exit_code, pid, signal ("Signal that caused termination, if any"), stopped, timed_out ("Whether
  process had been killed because operation timeout was reached"). There is no OOM flag and no memory-limit field.
- SDK layers: `OperationModel` (_internals/models/operation.py:18-23: kind, status, duration, error, metadata, result); `InstanceOperationMetadata` (instance.py:48-61: args, command,
  cwd, disposable, env, files, hostname, image, result, shell, stdin, timeout, truncate_output_at, preserve_env); `ProcessExecutionResult` (instance.py:40-43: resources, state, stderr,
  stdout); `InstanceOperationResult` (instance.py:66-67: image, tag); `StreamDescription` (utils/models/stream.py: value, encoding, truncated); `ContreeResult` (sdk/objects/image_like/result.py:15-21:
  stderr, stdout, exit_code, elapsed_time, cost, `_raw`; property `truncated`). `ImageState` (PULLED ... FAILED, state.py) is the SDK object lifecycle, not the process state.
- Reachability, same way as `_server_timed_out` (sandbox.py:458-461, `result._raw.result.state.timed_out`): `image.result` is the ContreeResult (image_like/_base.py:388-398);
  `_raw` is the `InstanceOperationMetadata` that `_wait_operation` returns as `resp.metadata` (sdk/client/_base.py:207) and `from_result` stores (result.py:40; _base.py:338).
  So **`result._raw.result.resources.max_rss`** and the 15 other `resources` fields, and `result._raw.result.state.{signal, core_dump, pid, stopped, continued}`, are readable
  with no new API call. NOT reachable without a new call: `consumed_cpu`, `consumed_memory`, `image_size`, `image_uuid`, `result_image_uuid`, `created_at`, the operation `uuid`,
  `status`, `duration`, `error`: `OperationModel` has no such fields (they are dropped when the response is structured) and the operation uuid is a local variable
  of `_await` (_base.py:309-338), never kept on the image or the result; RERUN records hold image uuids only, so a past operation cannot be re-read by id.

What is not established
- RAM, vCPU count, swap, per-process or cgroup memory limits of the microVM; whether they depend on image, token or time; whether the live `limits` map has a memory key.
- That `max_rss` is populated with a real number: no stored record or test output contains a real `resources` dict beyond `cost` and `elapsed_time`. Inference only: all 16
  `ProcessResources` fields are required (no defaults), so a response without `max_rss` would fail to parse on every operation; every live operation parsed, so the key is
  present. Its value (0 or real), unit (API text says KB; getrusage on Linux is KB, general knowledge) and which process it covers (the in-VM init's getrusage; for RUSAGE_CHILDREN
  the largest single descendant, not the sum, general knowledge) are unverified.
- `_raw` is a private attribute of a pinned SDK (0.3.6); a later SDK may rename it (the draft sponsor issue already rests on the same attribute).

## Q2. Is a larger instance offered (memory, CPUs, GPU)

What the sources say
- Nothing documents one. No size, preset, flavor, tier, vCPU, memory or GPU parameter exists in the spawn schema, SDK, CLI or MCP (Q1); the string "GPU" does not occur in
  the 128 sandbox pages; contree.dev lists no GPU [direct].
- Availability: Sandboxes is "currently in Beta" (overview.md:8); access by request: "Request access to the Sandboxes beta at tokenfactory.nebius.com/sandboxes/about, or reach out at
  contree@nebius.com" (contree.dev FAQ) [direct]. "Please contact us if you need those limitations lifted for the beta period." (overview.md:97) refers only to the two listed
  limits (50 concurrent operations, 180-day retention), not to memory. Feedback channels named: contree@nebius.com and Discord [direct].
- Cost: no price page, no resource rate in the Sandboxes docs [direct]. D-36 cites the product page "Free while in beta - runs don't consume your credits"; a search snippet this
  session says the same [search]; contree.dev lists "Pay per execution, not idle" and JSON-LD `offers.price` "0" [direct]. A third-party review dated 2026-09-15 says "no sandbox-specific public
  tariff verified" and gives no memory or vCPU [fetch rywalker.com/research/ai-agent-sandboxes].
- Nebius AI Cloud Compute (VM types, GPUs, presets, docs.nebius.com/compute/...) and Nebius Serverless Jobs (`resources: {platform, preset}`, per backend/app/batch/runner.py's
  docstring, never exercised live per that docstring) are separate products; no page read here connects either to Sandboxes. Not read: [search] listing only.

What is not established: whether any larger microVM, per-token memory raise or GPU exists for Sandboxes, its availability, or its price. The only documented route is to ask
contree@nebius.com.

## Q3. How a process killed for memory shows itself inside the microVM

What the sources say
- Nothing on OOM, memory.events, dmesg or cgroups in any Sandboxes page, API schema or SDK file [direct]. The two `mount | grep cgroup` lines in cli/tutorial/shell.md:53 and
  cli/commands/shell.md:93 are example commands without output; they say nothing about the VM.
- Documented signal facts: "When the limit fires, the API returns `state.timed_out=true` (status may still be `SUCCESS` with `signal=9`)" (cli/tutorial/shell.md:308-309); kill API:
  "terminal `state` (`signal` set, `exit_code` -1 when killed)" [direct]. Our own live run (reports/corpus-v2.1/sponsor-issues/nebius-sandbox-state-timed_out.md): a platform timeout
  returned exit code -1 with `timed_out` true [local].
- Our records for #11 (gate v1.4.1): `attempts[1..3].exit_code` 137; `stderr_tail` ends "Killed"; ledger operations 3-5 `outcome: completed`, `exit_code: 137`. Because sandbox.py raises
  SandboxTimeoutError for `step.timed_out` (sandbox.py:851-864) and these operations completed, `state.timed_out` was False, so the kill was not the server's time limit (inference
  from that code path; `timed_out` itself is not stored). The same point in three separate VMs means a deterministic cause; it does not say which one.
- The repairer's text "observed OOM kill" (`reason_no_citation`, attempts 4, 6-10) is a model assertion, not a measurement.

General Linux knowledge, not Nebius facts: status 137 = 128 + SIGKILL; "Killed" is printed by the shell when a child dies of SIGKILL; the kernel OOM killer (global, or cgroup
v1/v2) uses SIGKILL, but so can any `kill -9`. Kernel evidence of an OOM kill: `dmesg` line "Out of memory: Killed process N", cgroup v2 `memory.events` counter `oom_kill`, cgroup v1
`memory.oom_control`/`memory.failcnt`. If the shell survives and reports "Killed" (as the #11 stderr suggests), the tracked top-level process exited normally with code 137, so
`state.signal` may be 0; no source read here says which `state.signal` such an operation shows (inference).

What is not established: that any memory limit exists, that it fired, what `state.signal`, `max_rss` or `swaps` held for the #11 operations, whether the guest has a cgroup or a
readable kernel log.

## Q4. Do our stored operation records contain any memory figure (runs/corpus_v2_batch/harness-v1.4.1/gate and harness-v1.4.0/gate)

Result: none. Method: every JSON key and string value of the 12 files (v1.4.1: entries 03, 07, 08, 11 and 3 upload files; v1.4.0: entries 03, 07, 08, 11 and 1 upload file).
- Key names containing memory, rss, consumed, cpu, resource, signal, timed_out, state, swap or page_fault: 0 in all 12 files.
- Value hits for memory, RSS, max_rss, consumed_memory/cpu, MemTotal, OOM, out of memory, MemoryError: 12 hits, all in v1.4.1 #11, six distinct sentences each stored twice
  (`result.attempts[].reason_no_citation`, `certificate.diffs[].reason_no_citation`): model prose such as "observed OOM kill". No number. A plain `grep -i consumed` also hits v1.4.1 #08 (3
  distinct strings, each stored twice): a Python `codecs.py` traceback, "(result, consumed)".
- Stored per operation (`operations[]`): n, role, candidate, concurrent, base_image, funded_seconds, wall_seconds, sandbox_seconds, install_seconds, rerun_steps, branch_from_image,
  start_setup_commands, setup_commands, torch_in_start_image, torch_installed, torch_env_key, result_image, image_kept, kept_images, env_image_id, cost_usd, cost_estimated_usd, outcome, exit_code,
  killed_step, killed_seconds, funding (+ exit_wrapper on one). Per attempt (#11): attempt_number, diff_text, env_delta, execution{mode, seconds, outcome}, exit_code, gate_*, origin, stderr_tail,
  stdout_tail, time_machine, time_machine_action, tavily_sources, resolved_sources.
- Repo-wide: `max_rss`, `consumed_memory`, `user_cpu_time`, `MemTotal` appear in no stored record (hits are D-36 and report text, and runner.py's unrelated `resources` job spec).
  reports/corpus-v2.1/v1.4.1/gate/GATE_REPORT_v1.4.1.md:57 says the same: "the records do not store `consumed_memory`".

## What RERUN can store on every operation today with no sandbox.py change, and what it cannot

Strictly, nothing new. The orchestrator never receives the SDK result: `step_result_from_image` (sandbox.py:437-455, the only call site, sandbox.py:847) copies `exit_code`, `stdout`,
`stderr`, `elapsed_seconds`, `cost_usd`, `phase`, `timed_out` into `StepResult` (sandbox.py:374-387) and drops `_raw`. `SandboxRunResult` adds sandbox_id, upload_seconds, extract_seconds, layers,
branch_from_image, result_image, rerun_steps, setup_commands, ran_setup (sandbox.py:391-415). `timed_out` has no key in the stored records (Q4).
- Reachable from objects that exist (the ContreeResult inside sandbox.py, same access path as `_server_timed_out`): `_raw.result.resources` (all 16 fields, notably max_rss, user_cpu_time,
  system_cpu_time, swaps, page_faults, page_faults_io, signals) and `_raw.result.state` (exit_code, signal, core_dump, pid, stopped, continued, timed_out), plus `_raw.timeout`, `_raw.image`.
  Capturing them needs an additive change in sandbox.py (new optional StepResult fields filled by `step_result_from_image` with the same guarded `getattr`), not in the orchestrator.
- Not reachable without a new API call: `consumed_cpu`, `consumed_memory`, `image_size`, operation uuid, `created_at`, `status` (only `GET /operations/{id}`, `GET /operations`, whoami).
- Nothing can be said about values until one real operation is stored; the unit and the covered process stay unverified (Q1).

## Evidence collectable inside the sandbox by a harness-injected command after a kill (candidates; NONE was run)

Each operation is a fresh microVM with its own kernel (MCP core concepts, "Every command runs in a separate kernel") and "Process memory, running services, and network state are not
preserved" (contree.dev FAQ) [direct]. A later operation therefore sees none of the earlier kernel state: the commands below must run in the same shell line as the failing program
(shape: `<cmd>; rc=$?; if [ $rc -ge 128 ]; then <diagnostics> >&2; fi; exit $rc`). The final command runs `disposable` (sandbox.py:838), so output must go to stdout/stderr, not a file.
- Size of the guest: `nproc`; `grep -E 'MemTotal|MemAvailable|SwapTotal|SwapFree' /proc/meminfo`; `cat /proc/swaps`; `cat /proc/cmdline` (a `mem=` option); `uname -r`.
- Limits on the process: `ulimit -a`; `python -c "import resource; print(resource.getrlimit(resource.RLIMIT_AS))"` (RLIMIT_AS, RLIMIT_DATA); caveat: rlimits do not show a VM or cgroup cap.
- cgroup: `cat /proc/self/cgroup`; `stat -fc %T /sys/fs/cgroup` (cgroup2fs = v2); v2: `memory.max`, `memory.current`, `memory.peak`, `memory.events` (field `oom_kill`) under that cgroup path;
  v1: `memory/memory.limit_in_bytes`, `memory.failcnt`, `memory.oom_control`. Absent files mean no cgroup memory control, which is itself evidence.
- Kernel log: `dmesg | tail -n 50`, or `dmesg | grep -i -E 'out of memory|oom|killed process'`; may be restricted (`kernel.dmesg_restrict`) or empty in a microVM.
- Overcommit and RAM-backed disk: `cat /proc/sys/vm/overcommit_memory`; `df -h / /tmp`; `mount | grep -E 'tmpfs|overlay'` (a tmpfs `/tmp` is paid out of RAM, general knowledge).
- Peak of the program itself: a sampler `while kill -0 $pid; do grep -E 'VmHWM|VmRSS' /proc/$pid/status; sleep 0.5; done >&2 &` (adds load), or in a Python wrapper
  `resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss`. The API's `max_rss` may already give this for free (Q1), which is why storing `_raw.result.resources` comes first.
- One-off size probe (a tiny disposable operation, not tied to a repository): the first four groups above in one command; its cost is whatever the ledger records, not estimated here.
