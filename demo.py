"""RERUN's keyless demo in one command, from a fresh clone. No API key, no spend: the backend runs in DEMO mode (it replays the committed run records and refuses
live execution with HTTP 409) and the built frontend is served in front of it.

    python demo.py            # install (pinned), build, start; open the printed address; Ctrl+C stops both servers
    python demo.py --check    # the same, then probe the running app and exit 0 only if every probe passes (the final gate runs this)

Needs Python 3.11+ (the pins were made on 3.14), Node 18+ with npm, git, and a network connection for the first install. Everything it creates is under `.demo/`
(git-ignored): a virtual environment, the demo database. Keys are forced empty in the backend's environment, which takes precedence over any `.env` file.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
WORK = ROOT / ".demo"
VENV = WORK / "venv"
CONSTRAINTS = ROOT / ".github" / "seal" / "constraints.txt"
KEYS = ("NEBIUS_API_KEY", "NEBIUS_PROJECT_ID", "TAVILY_API_KEY")


def say(msg: str) -> None:
    print(f"[demo] {msg}", flush=True)


def fail(msg: str) -> None:
    print(f"[demo] FAILED: {msg}", file=sys.stderr, flush=True)
    sys.exit(1)


def run(cmd: list[str], cwd: Path, env: dict | None = None) -> None:
    say("$ " + " ".join(str(c) for c in cmd))
    if subprocess.run(cmd, cwd=cwd, env=env).returncode != 0:
        fail(f"command failed: {' '.join(str(c) for c in cmd)}")


def venv_python() -> Path:
    return VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def install(skip_install: bool) -> None:
    if sys.version_info < (3, 11):
        fail(f"Python 3.11 or newer is needed, this is {sys.version.split()[0]}")
    node, npm = shutil.which("node"), shutil.which("npm")
    if not node or not npm:
        fail("Node.js 18+ with npm is needed on PATH to build the frontend")
    if not shutil.which("git"):
        fail("git is needed on PATH (the backend's intake uses it)")
    if sys.version_info[:2] != (3, 14):
        say(f"note: the pinned versions were made on Python 3.14; this is {sys.version.split()[0]}")
    if skip_install and venv_python().is_file() and (ROOT / "frontend" / "dist" / "index.html").is_file():
        say("--skip-install: using the existing .demo/venv and frontend/dist")
        return
    WORK.mkdir(exist_ok=True)
    if not venv_python().is_file():
        run([sys.executable, "-m", "venv", str(VENV)], ROOT)
    run([str(venv_python()), "-m", "pip", "install", "--disable-pip-version-check", "--quiet", "-c", str(CONSTRAINTS), str(ROOT / "backend")], ROOT)
    run([npm, "ci", "--no-audit", "--no-fund"], ROOT / "frontend")
    run([npm, "run", "build"], ROOT / "frontend")


def get(url: str, method: str = "GET", timeout: float = 10) -> tuple[int, bytes]:
    req = urllib.request.Request(url, method=method, data=b"{}" if method == "POST" else None, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()
    except (urllib.error.URLError, OSError):
        return 0, b""


def wait_for(url: str, proc: subprocess.Popen, what: str, seconds: int = 120) -> None:
    for _ in range(seconds):
        if proc.poll() is not None:
            fail(f"{what} exited with code {proc.returncode} before it answered")
        if get(url, timeout=2)[0] == 200:
            return
        time.sleep(1)
    fail(f"{what} did not answer at {url} within {seconds} s")


def start(api_port: int, web_port: int) -> list[subprocess.Popen]:
    db = WORK / "rerun_demo.db"
    db.unlink(missing_ok=True)  # a fresh database: the records are seeded at every start
    env = {**os.environ, "DEMO_MODE": "1", "DEMO_ROOT": str(ROOT), "DATABASE_URL": f"sqlite:///{db.as_posix()}", "PYTHONIOENCODING": "utf-8"}
    env.update({k: "" for k in KEYS})  # keyless: an empty environment variable takes precedence over any .env file
    say(f"starting the backend in demo mode on 127.0.0.1:{api_port}")
    api = subprocess.Popen([str(venv_python()), "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(api_port)], cwd=ROOT / "backend", env=env)
    wait_for(f"http://127.0.0.1:{api_port}/healthz", api, "the backend")
    vite = ROOT / "frontend" / "node_modules" / "vite" / "bin" / "vite.js"
    say(f"serving the built frontend on 127.0.0.1:{web_port} (it proxies /api to the backend)")
    web = subprocess.Popen([shutil.which("node"), str(vite), "preview", "--host", "127.0.0.1", "--port", str(web_port), "--strictPort"], cwd=ROOT / "frontend",
                           env={**os.environ, "RERUN_API_PROXY": f"http://127.0.0.1:{api_port}"})
    wait_for(f"http://127.0.0.1:{web_port}/", web, "the frontend server")
    return [api, web]


def probe(web_port: int) -> bool:
    base = f"http://127.0.0.1:{web_port}"
    results: list[tuple[str, bool, str]] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        results.append((name, ok, detail))

    status, body = get(base + "/")
    check("the page loads", status == 200 and b'id="root"' in body, f"HTTP {status}")
    status, body = get(base + "/api/healthz")
    check("the API answers through the frontend's proxy", status == 200, f"HTTP {status}")
    status, body = get(base + "/api/runs")
    runs = []
    if status == 200:
        doc = json.loads(body)
        runs = doc if isinstance(doc, list) else (doc.get("items") or doc.get("runs") or [])
    check("the recorded runs are seeded", status == 200 and len(runs) > 0, f"HTTP {status}, {len(runs)} run(s)")
    if runs:
        opened = next((r["id"] for r in runs[:20] if get(f"{base}/api/runs/{r['id']}/certificate")[0] == 200), None)
        check("a certificate opens", opened is not None, f"run {opened}" if opened else "none of the first 20 runs")
        status, _ = get(f"{base}/api/runs/{runs[0]['id']}/execute", method="POST")
        check("live execution is refused (keyless demo)", status == 409, f"HTTP {status}")
    status, body = get(base + "/api/batch/preregistered")
    check("the Batch Lab's figures load", status == 200 and len(body) > 100, f"HTTP {status}")
    status, _ = get(base + "/api/demo/scenes")
    check("the demo scenes load", status == 200, f"HTTP {status}")
    for name, ok, detail in results:
        say(f"{'PASS' if ok else 'FAIL'}  {name}  ({detail})")
    return all(ok for _, ok, _ in results)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="probe the running app, then stop and exit 0 only if every probe passed")
    ap.add_argument("--skip-install", action="store_true", help="reuse .demo/venv and frontend/dist if they exist")
    ap.add_argument("--api-port", type=int, default=8765)
    ap.add_argument("--port", type=int, default=4173, help="the port of the page")
    args = ap.parse_args()
    install(args.skip_install)
    procs = start(args.api_port, args.port)
    try:
        if args.check:
            ok = probe(args.port)
            say("all probes passed" if ok else "a probe failed")
            return 0 if ok else 1
        say(f"RERUN demo running: open http://127.0.0.1:{args.port}  (Ctrl+C stops it)")
        while all(p.poll() is None for p in procs):
            time.sleep(1)
        fail("a server exited")
    except KeyboardInterrupt:
        say("stopping")
    finally:
        for p in procs:
            if p.poll() is None:
                p.terminate()
        for p in procs:
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                p.kill()
    return 0


if __name__ == "__main__":
    sys.exit(main())
