"""harness-v1.10 pass, task 7: `reports/v1.9/figures.json` (the source the README guard allows its numbers from) is regenerated from the committed result files, and the test fails on any
difference, so a figure cannot be edited by hand or left stale when a result file changes."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _figures_module():
    spec = importlib.util.spec_from_file_location("rerun_figures", ROOT / "reports" / "v1.9" / "figures.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_figures_json_equals_a_fresh_build_from_the_committed_result_files():
    committed = json.loads((ROOT / "reports" / "v1.9" / "figures.json").read_text(encoding="utf-8"))
    rebuilt = _figures_module().build()
    assert rebuilt == committed, "figures.json is stale or was edited: run `python reports/v1.9/figures.py --write` and commit the result"


def test_every_figure_carries_a_tag_a_source_and_an_integer_value():
    for name, fig in _figures_module().build()["figures"].items():
        assert fig["tag"] in ("DERIVED", "API-REPORTED", "ESTIMATED", "BILLED"), name
        assert fig["source"] and isinstance(fig["value"], int) and not isinstance(fig["value"], bool), name


def test_the_erratum_figures_are_the_recorded_ones_minus_the_withdrawn_run():
    figs = _figures_module().build()["figures"]
    assert figs["certified_dev"]["value"] - figs["certified_dev_after_erratum"]["value"] == 1  # E-3, DEV entry 14 (M-FAC)
    assert [figs[f"dev_round{n}_smoke_after_erratum"]["value"] for n in range(1, 6)] == [1, 2, 2, 3, 3]
    assert [figs[f"dev_round{n}_smoke_as_recorded"]["value"] for n in range(1, 6)] == [1, 2, 3, 3, 3]
    assert figs["fresh_removed_by_audit"]["value"] == 2 and figs["fresh_removed_that_were_fakes"]["value"] == 0


def test_the_task_6_breakdown_is_a_fresh_build_and_says_the_two_removed_were_not_fakes():
    spec = importlib.util.spec_from_file_location("rerun_breakdown", ROOT / "reports" / "v1.10" / "breakdown" / "breakdown.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    built = module.build()
    assert built == json.loads((ROOT / "reports" / "v1.10" / "breakdown" / "breakdown.json").read_text(encoding="utf-8"))
    assert (built["ungated_at_least"], built["certified_as_recorded"], built["certified_after_audits"], built["removed_by_audit"]) == (6, 5, 3, 2)
    removed = [r for r in built["rows"] if r["removed_by_audit"]]
    assert [(r["set"], r["entry"]) for r in removed] == [("TEST-A", "18"), ("TEST-B", "06")]
    assert all(not r["model_patch_involved"] and r["exit_zero_came_from"] == "the as-published command" for r in removed)
    assert built["ungated_but_not_certified"] == ["kartikgupta-at-anu__spline-calibration"]  # the one fake of the fresh sets, refused
