
"""harness-v1.7, R3 launcher on POSIX (v1.7 review, M2): the time cap kills the step's whole process group, so a script whose child keeps the
output pipe open (a shell script's wget, a multiprocessing pool) cannot outlive the cap. Imports runner_hooks only, so it runs under WSL
(`python3 -m pytest backend/tests/test_v17_data_prep_launcher_posix.py --noconftest` with PYTHONPATH=backend) as well as on a POSIX CI."""

from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import time

import pytest

from app.services import runner_hooks


@pytest.mark.skipif(os.name != "posix", reason="process groups are POSIX")
def test_the_time_cap_kills_a_grandchild_that_holds_the_pipe(tmp_path):
    (tmp_path / "data" / "x").mkdir(parents=True)
    (tmp_path / "data" / "x" / "get_data.sh").write_text("sleep 60 &\nsleep 60\n", encoding="utf-8")
    spec = {"kind": "script", "workdir": "data/x", "script": "data/x/get_data.sh", "argv": ["sh", "get_data.sh"], "url": "",
            "max_bytes": 10_000_000, "max_seconds": 2}
    arg = base64.b64encode(json.dumps(spec).encode("utf-8")).decode("ascii")
    started = time.time()
    done = subprocess.run([sys.executable, "-c", runner_hooks.data_prep_source(), arg], cwd=tmp_path, capture_output=True, text=True, timeout=50)
    assert time.time() - started < 20, "the step outlived its cap"
    record = runner_hooks.parse_data_prep(done.stdout)
    assert record["exit_code"] is None and "process group was killed" in record["error"]
