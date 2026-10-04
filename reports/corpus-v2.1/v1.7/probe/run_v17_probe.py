"""harness-v1.7 probe (METHODOLOGY "harness-v1.7 — PRE-REGISTRATION", R1 (a) and R4): the first live call of v1.7.

    backend/.venv/Scripts/python.exe reports/corpus-v2.1/v1.7/probe/run_v17_probe.py                                   # PLAN: nothing runs, nothing is spent
    backend/.venv/Scripts/pythonw.exe reports/corpus-v2.1/v1.7/probe/run_v17_probe.py --go --max-usd 0.10 --log-file F  # live (launch_probe.cmd, Task Scheduler)

Two disposable operations, each on a public base image, nothing of any repository in them:

  1. memory (python:3.10-slim, the image most DEV entries run on): what the sandbox says about memory (/proc/meminfo, ulimit -a, overcommit, the cgroup
     memory files, /proc/swaps, the root file system), then whether a 4 GiB swap file can be created and enabled (fallocate, else dd; mkswap; swapon), and,
     only if swapon took, whether a Python process can touch 5 GiB (past the 3.85 GiB MemTotal) without being killed. Decides whether rule R1 (b) swap_file is built.
  2. apt (python:3.6-slim, Debian bullseye): /etc/os-release, which mirrors serve a Release file for bullseye / bullseye-updates / bullseye-security
     (deb.debian.org, security.debian.org, archive.debian.org), then `apt-get update` with the sources rewritten to archive.debian.org as rule R4 would write them.
     Decides whether R4 adds `<codename>-updates`. Operation 2 is not started if operation 1 already cost more than the cap.

Cost: the pre-registered figure is $0.10 API-reported (the expected cost; the recorded rate is about $0.0115 per sandbox second, D-41 probe). The hard bound is the two
operation timeouts. Never runs without --go and --max-usd; the cost is appended to reports/corpus-v2.1/v1.5/ledger_extras.json with a pointer to the record.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "backend"))
OUT = ROOT / "runs" / "sandbox_verification" / "v1.7-probes"
EXTRAS = ROOT / "reports" / "corpus-v2.1" / "v1.5" / "ledger_extras.json"
MAX_PROBE_USD = 0.10
MEMORY_TIMEOUT_S = 60
APT_TIMEOUT_S = 45

MEMORY_SCRIPT = r"""
echo "== id"; id
echo "== meminfo"; grep -E '^(MemTotal|MemFree|MemAvailable|SwapTotal|SwapFree|CommitLimit|Committed_AS):' /proc/meminfo
echo "== free"; (free -m 2>&1 || echo "free: not installed")
echo "== ulimit"; ulimit -a 2>&1
echo "== overcommit"; cat /proc/sys/vm/overcommit_memory /proc/sys/vm/overcommit_ratio /proc/sys/vm/swappiness 2>&1
echo "== cgroup"; cat /proc/self/cgroup 2>&1
for f in /sys/fs/cgroup/memory.max /sys/fs/cgroup/memory.swap.max /sys/fs/cgroup/memory.high /sys/fs/cgroup/memory.current \
         /sys/fs/cgroup/memory/memory.limit_in_bytes /sys/fs/cgroup/memory/memory.memsw.limit_in_bytes; do [ -r "$f" ] && echo "$f=$(cat "$f")"; done
echo "== swaps"; cat /proc/swaps 2>&1
echo "== block"; ls /sys/block 2>&1; grep -i -E 'zram|loop' /proc/devices /proc/modules 2>&1 | head -5
echo "== mounts"; grep -E ' / | /tmp ' /proc/mounts 2>&1; df -T / /tmp 2>&1 | head -5
echo "== kernel"; uname -r
echo "== swapfile"
if fallocate -l 4G /swapfile 2>/tmp/falloc.err; then echo "fallocate rc=0"; else echo "fallocate rc=$? $(cat /tmp/falloc.err)"; dd if=/dev/zero of=/swapfile bs=1M count=4096 2>&1 | tail -n 1; echo "dd rc=$?"; fi
ls -l /swapfile 2>&1
chmod 600 /swapfile 2>&1
mkswap /swapfile 2>&1; echo "mkswap rc=$?"
swapon /swapfile 2>&1; rc=$?; echo "swapon rc=$rc"
cat /proc/swaps; grep -E '^(SwapTotal|SwapFree):' /proc/meminfo
if [ "$rc" = "0" ]; then
  echo "== alloc"
  timeout 40 python3 -c '
import sys
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
dmesg 2>&1 | grep -iE 'swap|oom|killed process' | tail -n 5
"""

APT_URLS = [
    "http://deb.debian.org/debian/dists/bullseye/Release",
    "http://deb.debian.org/debian/dists/bullseye-updates/Release",
    "http://security.debian.org/debian-security/dists/bullseye-security/Release",
    "http://archive.debian.org/debian/dists/bullseye/Release",
    "http://archive.debian.org/debian/dists/bullseye-updates/Release",
    "http://archive.debian.org/debian-security/dists/bullseye-security/Release",
    "http://archive.debian.org/debian/dists/buster/Release",
    "http://archive.debian.org/debian/dists/buster-updates/Release",
]

APT_SCRIPT = r"""
echo "== os-release"; cat /etc/os-release
echo "== sources"; cat /etc/apt/sources.list 2>&1; ls /etc/apt/sources.list.d 2>&1
echo "== urls"
python3 -c '
import sys, urllib.request
for url in sys.argv[1:]:
    try:
        r = urllib.request.urlopen(urllib.request.Request(url, method="HEAD"), timeout=8)
        print("URL", r.status, url)
    except Exception as exc:
        print("URL", getattr(exc, "code", type(exc).__name__), url)
' __URLS__
echo "== archive update"
. /etc/os-release
printf 'deb http://archive.debian.org/debian %s main\n' "$VERSION_CODENAME" > /etc/apt/sources.list
echo 'Acquire::Check-Valid-Until "false";' > /etc/apt/apt.conf.d/99rerun-archive
cat /etc/apt/sources.list
timeout 30 apt-get -o Acquire::http::Timeout=10 update >/tmp/apt_update.log 2>&1; echo "apt-get update rc=$?"; tail -n 8 /tmp/apt_update.log
apt-cache policy build-essential 2>&1 | head -n 4
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _run(client, image: str, script: str, timeout: int) -> dict:
    started = _now()
    done = client.images.docker(image).run(shell=script, timeout=timeout, disposable=True, preserve_env=False).wait()
    result = done.result
    return {"image": image, "started_at": started, "finished_at": _now(), "timeout_s": timeout, "exit_code": result.exit_code,
            "cost_usd": float(result.cost), "elapsed_seconds": result.elapsed_time.total_seconds(), "truncated": bool(result.truncated),
            "stdout": result.stdout or "", "stderr": result.stderr or "", "script": script}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--go", action="store_true")
    ap.add_argument("--max-usd", type=float)
    ap.add_argument("--log-file")
    args = ap.parse_args()
    if args.log_file:
        sys.stdout = sys.stderr = open(args.log_file, "a", encoding="utf-8", buffering=1)
    apt_script = APT_SCRIPT.replace("__URLS__", " ".join(APT_URLS))
    print(f"{_now()} v1.7 probe: operation 1 memory on python:3.10-slim (timeout {MEMORY_TIMEOUT_S} s), operation 2 apt on python:3.6-slim (timeout {APT_TIMEOUT_S} s); "
          f"expected cost <= ${MAX_PROBE_USD:.2f} API-reported")
    if not args.go:
        print("PLAN ONLY: nothing was run and nothing was spent (pass --go and --max-usd to run).")
        return 0
    if args.max_usd is None or args.max_usd <= 0 or args.max_usd > MAX_PROBE_USD + 1e-9:
        print(f"REFUSED: --max-usd is required and must be at most ${MAX_PROBE_USD:.2f}")
        return 2
    from app.config import get_settings
    from contree_sdk import ContreeSync
    from contree_sdk.auth import IAMAuth
    from contree_sdk.config import ContreeConfig

    settings = get_settings()
    client = ContreeSync(config=ContreeConfig(auth=IAMAuth(token=settings.nebius_api_key, project_id=settings.nebius_project_id),
                                              transport_timeout=60, operation_timeout=MEMORY_TIMEOUT_S + 60))
    doc = {"record_kind": "harness-v1.7 probe (METHODOLOGY harness-v1.7 pre-registration, R1 (a) and R4)", "started_at": _now(), "cap_usd": args.max_usd,
           "operations": []}
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"probe_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    try:
        doc["operations"].append({"n": 1, "what": "memory and swap", **_run(client, "python:3.10-slim", MEMORY_SCRIPT, MEMORY_TIMEOUT_S)})
        spent = sum(o["cost_usd"] for o in doc["operations"])
        if spent > args.max_usd:
            doc["operation_2_skipped"] = f"operation 1 cost ${spent:.6f}, above the ${args.max_usd:.2f} cap"
        else:
            doc["operations"].append({"n": 2, "what": "apt mirrors for bullseye", **_run(client, "python:3.6-slim", apt_script, APT_TIMEOUT_S)})
    except Exception as exc:  # noqa: BLE001 - whatever was recorded is kept
        doc["error"] = f"{type(exc).__name__}: {str(exc)[:500]}"
    doc["finished_at"] = _now()
    doc["cost_usd"] = round(sum(o["cost_usd"] for o in doc["operations"]), 6)
    doc["cost_over_cap_usd"] = round(max(0.0, doc["cost_usd"] - args.max_usd), 6)
    path.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    if doc["cost_usd"] > 0:
        extras = json.loads(EXTRAS.read_text(encoding="utf-8"))
        extras["items"].append({"what": f"harness-v1.7 probe (R1 (a), R4): {len(doc['operations'])} operation(s), {path.relative_to(ROOT).as_posix()}",
                                "usd": doc["cost_usd"], "estimated": False})
        EXTRAS.write_text(json.dumps(extras, indent=2) + "\n", encoding="utf-8", newline="\n")
    for o in doc["operations"]:
        print(f"---- operation {o['n']} ({o['what']}, {o['image']}): exit {o['exit_code']}, ${o['cost_usd']:.6f}, {o['elapsed_seconds']:.1f} s ----")
        print(o["stdout"][-6000:])
        if o["stderr"].strip():
            print("[stderr]", o["stderr"][-2000:])
    print(json.dumps({k: doc.get(k) for k in ("cost_usd", "cost_over_cap_usd", "error", "operation_2_skipped")}))
    print(f"{_now()} record written: {path.relative_to(ROOT).as_posix()}")
    return 0 if "error" not in doc else 1


if __name__ == "__main__":
    raise SystemExit(main())
