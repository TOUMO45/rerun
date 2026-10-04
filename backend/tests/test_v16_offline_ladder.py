"""harness-v1.6, item L: the offline ladder (reports/dev/levels/compute_levels.py) and the harness's outcome_levels.compute are one function, and the
committed table matches what the script computes from the committed DEV and gate records (TEST records never opened: the firewall)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "reports" / "dev" / "levels" / "compute_levels.py"
LEVELS = ROOT / "reports" / "dev" / "levels" / "levels.json"


@pytest.mark.skipif(not SCRIPT.is_file() or not LEVELS.is_file(), reason="the levels report is not in this checkout")
def test_the_committed_levels_table_is_what_the_script_computes_from_the_records(tmp_path):
    committed = json.loads(LEVELS.read_text(encoding="utf-8"))["rows"]
    out = subprocess.run([sys.executable, str(SCRIPT)], cwd=ROOT, capture_output=True, text=True, check=True)
    assert "harness-v1" in out.stdout
    recomputed = json.loads(LEVELS.read_text(encoding="utf-8"))["rows"]
    assert recomputed == committed
    # the firewall held: no TEST entry in the table
    sys.path.insert(0, str(ROOT / "reports" / "corpus-v2.1" / "v1.5" / "devtest"))
    import split
    assert not {r["entry"] for r in committed} & set(split.split()["test"])


def test_the_offline_rows_carry_the_same_rungs_as_outcome_levels_compute():
    from app.services import outcome_levels
    sys.path.insert(0, str(ROOT / "reports" / "corpus-v2.1" / "v1.5" / "devtest"))
    import firewall
    rows = {r["record"]: r for r in json.loads(LEVELS.read_text(encoding="utf-8"))["rows"]}
    checked = 0
    for rel, row in rows.items():
        res = json.loads(firewall.read_record_text(ROOT / rel))["result"]
        levels = outcome_levels.compute({"verdict": res["verdict"], "error_chain": res.get("error_chain") or [], "attempts": res.get("attempts") or []})
        assert (row["first_cleared"], row["env_resolved"], row["entrypoint_runs"]) == (
            levels["first_error_cleared"], levels["env_resolved"], levels["entrypoint_runs"]), rel
        checked += 1
    assert checked >= 40
