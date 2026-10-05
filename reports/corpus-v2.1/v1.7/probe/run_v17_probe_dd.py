"""harness-v1.7 probe, follow-up (R1 (a)): a swap file WRITTEN with dd. Not pre-registered; added 2026-10-05 after the independent review of the post-probe diff.

    backend/.venv/Scripts/python.exe reports/corpus-v2.1/v1.7/probe/run_v17_probe_dd.py                                   # PLAN: nothing runs, nothing is spent
    backend/.venv/Scripts/pythonw.exe reports/corpus-v2.1/v1.7/probe/run_v17_probe_dd.py --go --max-usd 0.10 --log-file F  # live (launch_probe_dd.cmd, Task Scheduler)

Why: the probe (runs/sandbox_verification/v1.7-probes/probe_20261005T064245Z.json) created its swap file with fallocate, and swapon refused it (`Invalid argument`,
kernel `swapon: swapfile has holes`). The pre-registered script takes dd only when fallocate fails, so a fully written file was never tried, and "swap cannot be
enabled" is not shown by that record. This follow-up settles it: one disposable operation on python:3.10-slim, nothing of any repository in it. It writes a 2 GiB file
of zeros with dd (every block written, fsync), mkswap, swapon; only if swapon took, a Python process touches 5 GiB (past the 3.85 GiB MemTotal; 2 GiB of swap carries
it), then swapoff. It also prints what would explain a refusal (file system type, `filefrag` when present, the kernel's swap lines).

Cost: same bound as the probe, $0.10 API-reported expected; the hard bound is the operation timeout (90 s). Never runs without --go and --max-usd; the cost is appended
to reports/corpus-v2.1/v1.5/ledger_extras.json with a pointer to the record. Reuses the probe's client set-up and record shape (run_v17_probe.py, unchanged).
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
_spec = importlib.util.spec_from_file_location("run_v17_probe", Path(__file__).with_name("run_v17_probe.py"))
probe = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(probe)

DD_TIMEOUT_S = 90

DD_SCRIPT = r"""
echo "== meminfo"; grep -E '^(MemTotal|MemAvailable|SwapTotal|SwapFree):' /proc/meminfo
echo "== mounts"; grep -E ' / ' /proc/mounts 2>&1
echo "== dd"
dd if=/dev/zero of=/swapfile bs=1M count=2048 conv=fsync 2>&1 | tail -n 1; echo "dd rc=$?"
ls -ls /swapfile 2>&1
(filefrag /swapfile 2>&1 || echo "filefrag: not available") | tail -n 2
chmod 600 /swapfile 2>&1
mkswap /swapfile 2>&1; echo "mkswap rc=$?"
swapon /swapfile 2>&1; rc=$?; echo "swapon rc=$rc"
cat /proc/swaps; grep -E '^(SwapTotal|SwapFree):' /proc/meminfo
if [ "$rc" = "0" ]; then
  echo "== alloc"
  timeout 50 python3 -c '
chunks = []
for i in range(20):  # 20 x 256 MiB = 5 GiB, every page written
    b = bytearray(256 * 1024 * 1024)
    for j in range(0, len(b), 4096):
        b[j] = 1
    chunks.append(b)
    print("ALLOC_MB", (i + 1) * 256, flush=True)
print("ALLOC_DONE", len(chunks) * 256, flush=True)
'
  echo "alloc rc=$?"
  grep -E '^(SwapTotal|SwapFree):' /proc/meminfo
  swapoff /swapfile 2>&1; echo "swapoff rc=$?"
else
  echo "== alloc skipped: swapon did not take"
fi
dmesg 2>&1 | grep -iE 'swap|oom|killed process' | tail -n 6
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--go", action="store_true")
    ap.add_argument("--max-usd", type=float)
    ap.add_argument("--log-file")
    args = ap.parse_args()
    if args.log_file:
        sys.stdout = sys.stderr = open(args.log_file, "a", encoding="utf-8", buffering=1)
    print(f"{probe._now()} v1.7 probe follow-up: one operation, a dd-written swap file on python:3.10-slim (timeout {DD_TIMEOUT_S} s); "
          f"expected cost <= ${probe.MAX_PROBE_USD:.2f} API-reported")
    if not args.go:
        print("PLAN ONLY: nothing was run and nothing was spent (pass --go and --max-usd to run).")
        return 0
    if args.max_usd is None or args.max_usd <= 0 or args.max_usd > probe.MAX_PROBE_USD + 1e-9:
        print(f"REFUSED: --max-usd is required and must be at most ${probe.MAX_PROBE_USD:.2f}")
        return 2
    sys.path.insert(0, str(ROOT / "backend"))
    from app.config import get_settings
    from contree_sdk import ContreeSync
    from contree_sdk.auth import IAMAuth
    from contree_sdk.config import ContreeConfig

    settings = get_settings()
    client = ContreeSync(config=ContreeConfig(auth=IAMAuth(token=settings.nebius_api_key, project_id=settings.nebius_project_id),
                                              transport_timeout=60, operation_timeout=DD_TIMEOUT_S + 60))
    doc = {"record_kind": "harness-v1.7 probe follow-up (R1 (a): a dd-written swap file; not pre-registered)", "started_at": probe._now(),
           "cap_usd": args.max_usd, "operations": []}
    probe.OUT.mkdir(parents=True, exist_ok=True)
    path = probe.OUT / f"probe_dd_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    try:
        doc["operations"].append({"n": 1, "what": "dd-written swap file", **probe._run(client, "python:3.10-slim", DD_SCRIPT, DD_TIMEOUT_S)})
    except Exception as exc:  # noqa: BLE001 - whatever was recorded is kept
        doc["error"] = f"{type(exc).__name__}: {str(exc)[:500]}"
    doc["finished_at"] = probe._now()
    doc["cost_usd"] = round(sum(o["cost_usd"] for o in doc["operations"]), 6)
    doc["cost_over_cap_usd"] = round(max(0.0, doc["cost_usd"] - args.max_usd), 6)
    path.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    if doc["cost_usd"] > 0:
        extras = json.loads(probe.EXTRAS.read_text(encoding="utf-8"))
        extras["items"].append({"what": f"harness-v1.7 probe follow-up (R1 (a), dd-written swap file): {len(doc['operations'])} operation(s), "
                                        f"{path.relative_to(ROOT).as_posix()}", "usd": doc["cost_usd"], "estimated": False})
        probe.EXTRAS.write_text(json.dumps(extras, indent=2) + "\n", encoding="utf-8", newline="\n")
    for o in doc["operations"]:
        print(f"---- operation {o['n']} ({o['what']}, {o['image']}): exit {o['exit_code']}, ${o['cost_usd']:.6f}, {o['elapsed_seconds']:.1f} s ----")
        print(o["stdout"][-6000:])
        if o["stderr"].strip():
            print("[stderr]", o["stderr"][-2000:])
    print(json.dumps({k: doc.get(k) for k in ("cost_usd", "cost_over_cap_usd", "error")}))
    print(f"{probe._now()} record written: {path.relative_to(ROOT).as_posix()}")
    return 0 if "error" not in doc else 1


if __name__ == "__main__":
    raise SystemExit(main())
