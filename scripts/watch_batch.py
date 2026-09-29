"""An honest batch watcher: it reports what is TRUE, with a timestamp on every line.

    python scripts/watch_batch.py runs/corpus_v2_batch/harness-v1.3/control [--interval 60] [--log watch.log]

It prints (and appends to --log) one line per change: the driver's state and the records present. The driver
counts as RUNNING only if its pid (`driver.pid`, written by the driver) is alive AND `summary.json` is absent;
DONE if `summary.json` exists; GONE if the pid is dead and there is no summary (the batch died or was stopped). The
process check is a real OS query, not a pattern match on command lines, and there is no "exited" line unless the
process is really gone. The watcher exits when the driver is DONE or GONE, so a caller learns of a death immediately.
"""

from __future__ import annotations

import argparse
import ctypes
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


def pid_alive(pid: int) -> bool:
    if sys.platform == "win32":
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.restype = ctypes.c_void_p
        handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            kernel32.GetExitCodeProcess(ctypes.c_void_p(handle), ctypes.byref(code))
            return code.value == 259  # STILL_ACTIVE
        finally:
            kernel32.CloseHandle(ctypes.c_void_p(handle))
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def state_of(odir: Path) -> str:
    if (odir / "summary.json").exists():
        return "DONE"
    pid_file = odir / "driver.pid"
    if not pid_file.exists():
        return "NOT_STARTED"
    try:
        pid = int(pid_file.read_text(encoding="utf-8").strip())
    except ValueError:
        return "GONE (unreadable driver.pid)"
    return f"RUNNING pid={pid}" if pid_alive(pid) else f"GONE pid={pid} (dead, no summary.json)"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("dir", type=Path)
    ap.add_argument("--interval", type=float, default=60.0)
    ap.add_argument("--log", type=Path)
    args = ap.parse_args(argv)
    last = None
    while True:
        state = state_of(args.dir)
        records = sorted(p.name for p in args.dir.glob("[0-9][0-9]_*.json"))
        snapshot = (state, tuple(records))
        if snapshot != last:
            line = (f"{datetime.now(timezone.utc).isoformat(timespec='seconds')} {state}; "
                    f"{len(records)} record(s); latest={records[-1] if records else '-'}")
            print(line, flush=True)
            if args.log:
                with args.log.open("a", encoding="utf-8", newline="\n") as f:
                    f.write(line + "\n")
            last = snapshot
        if state == "DONE" or state.startswith("GONE"):
            return 0 if state == "DONE" else 1
        time.sleep(args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
