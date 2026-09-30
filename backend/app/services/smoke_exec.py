"""Smoke execution for repair re-executions (harness-v1.3.3, step 1.7).

A repair re-execution asks one question: after this change, does the repository's documented command get past installation,
imports and into its first work without an error? It must not run a whole training job (harness-v1.3.2 re-executions ran to the
600 s wall clock: entry 15 ended PIPELINE_ERROR, entry 13 cost $5.12 in one operation).

`wrap(command, seconds)` returns a shell command that runs `command` exactly as documented (same program, same arguments, same
working directory, nothing reduced or edited) under a small launcher inside the sandbox:

  - the command finishes before `seconds`: the launcher exits with ITS exit code and forwards its stdout/stderr unchanged, so
    classification, evidence and attribution behave as without the launcher;
  - the command is still running at `seconds`: if it has written output and no Python traceback, the launcher stops it and
    exits 0 after printing `RERUN_SMOKE_ALIVE ...` (the program started, did work and had not failed);
    otherwise (silent, or a traceback while still running) it exits 1 and says why.

Scope of the claim, which every record carries (`AttemptRecord.execution`): a pass this way means "the command ran for
`seconds` without failing", not "the command finished" and not that any result was reproduced. The baseline (as published)
run is NOT wrapped: CONTROL and the first TREATMENT run stay comparable.

The launcher is Python 3.6-compatible (the oldest sandbox image is python:3.6-slim), is sent base64-encoded so no shell quoting
can change it, and never reads the host's environment.
"""

from __future__ import annotations

import base64
import json

DEFAULT_SECONDS = 60
ALIVE_MARKER = "RERUN_SMOKE_ALIVE"
FAILED_MARKER = "RERUN_SMOKE_FAILED"

_LAUNCHER = r'''
import base64, json, os, signal, subprocess, sys, threading, time
spec = json.loads(base64.b64decode(sys.argv[1]).decode("utf-8"))
seconds = float(spec["seconds"])
posix = os.name == "posix"
proc = subprocess.Popen(spec["cmd"], shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=posix)
captured = {"out": [], "err": []}

def pump(stream, key, dest):
    while True:
        chunk = stream.read1(4096)
        if not chunk:
            break
        text = chunk.decode("utf-8", "replace")
        captured[key].append(text)
        dest.write(text)
        dest.flush()

threads = [threading.Thread(target=pump, args=(proc.stdout, "out", sys.stdout)),
           threading.Thread(target=pump, args=(proc.stderr, "err", sys.stderr))]
for t in threads:
    t.daemon = True
    t.start()
deadline = time.time() + seconds
while proc.poll() is None and time.time() < deadline:
    time.sleep(0.1)
if proc.poll() is not None:
    for t in threads:
        t.join(10)
    sys.exit(proc.returncode)

def stop():
    try:
        if posix:
            os.killpg(proc.pid, signal.SIGTERM)
        else:
            proc.terminate()
    except OSError:
        pass
    for _ in range(30):
        if proc.poll() is not None:
            break
        time.sleep(0.1)
    try:
        if proc.poll() is None:
            os.killpg(proc.pid, signal.SIGKILL) if posix else proc.kill()
    except OSError:
        pass

time.sleep(0.3)  # let the pump threads drain what was already written
text = "".join(captured["err"]) + "".join(captured["out"])
stop()
for t in threads:
    t.join(2)
if "Traceback (most recent call last)" in text:
    sys.stderr.write("RERUN_SMOKE_FAILED: still running after %ds but it had already printed a Python traceback\n" % seconds)
    sys.exit(1)
if not text.strip():
    sys.stderr.write("RERUN_SMOKE_FAILED: still running after %ds with no output at all; nothing shows it did any work\n" % seconds)
    sys.exit(1)
sys.stdout.write("RERUN_SMOKE_ALIVE: still running after %ds with output and no traceback; stopped by RERUN (smoke execution)\n" % seconds)
sys.exit(0)
'''


def wrap(command: str, seconds: int = DEFAULT_SECONDS, python: str = "python3") -> str:
    """The shell command that runs `command` under the launcher. `command` is passed base64-encoded, unchanged."""
    payload = base64.b64encode(json.dumps({"cmd": command, "seconds": seconds}).encode("utf-8")).decode("ascii")
    code = base64.b64encode(_LAUNCHER.encode("utf-8")).decode("ascii")
    return f"{python} -c \"import base64;exec(base64.b64decode('{code}').decode('utf-8'))\" {payload}"


def execution_record(seconds: int, exit_code: int | None, stdout: str, stderr: str) -> dict:
    """What a smoke re-execution means, for the attempt record. `alive_at_limit` = still running at the limit, with output
    and no traceback; `exited` = the command ended by itself (its own exit code applies); `failed_while_running` = see stderr."""
    if exit_code is None:
        outcome = "not_completed"
    elif ALIVE_MARKER in (stdout or ""):
        outcome = "alive_at_limit"
    elif FAILED_MARKER in (stderr or ""):
        outcome = "failed_while_running"
    else:
        outcome = "exited"
    return {"mode": "smoke", "seconds": seconds, "outcome": outcome}
