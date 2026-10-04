"""Tests of the TEST-phase runner's pure parts (run_test_phase.py): the pre-registered 'confirmed' definition, the result's arithmetic, and the freeze check. Kept beside the runner (the
batch preflight refuses files outside its data allowlist that changed since a tag). Run with
`backend/.venv/Scripts/python.exe -m pytest reports/corpus-v2.1/v1.5/test/test_run_test_phase.py -q`. No Nebius call, no TEST record is opened."""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(HERE.parents[0] / "devtest"))


def _mod():
    spec = importlib.util.spec_from_file_location("run_test_phase", HERE / "run_test_phase.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _runs(entry_id=1, verdict="RUNS_AFTER_REPAIR", outcome="alive_at_limit", image="img-1"):
    """A synthetic RUNS_* record: the final attempt's smoke run `outcome` (alive_at_limit = a 60 s smoke pass nothing has confirmed)."""
    attempts = [{"chosen": True, "exit_code": 0, "execution": {"outcome": outcome, "image": image, "command": "python train.py"}}]
    return {"batch": {"entry_id": entry_id}, "corpus_entry": {"name": f"o__r{entry_id}"}, "result": {"verdict": verdict, "attempts": attempts}}


def test_selftest_and_the_entry_list_is_the_split_rules_test_list():
    m = _mod()
    assert m._selftest() == 0
    assert len(m.TEST_ENTRIES) == 8 and m.TARGET == 3


@pytest.mark.parametrize("sustained,confirmed,fragment", [
    ({"outcome": "completed", "funded_seconds": 600}, True, "(ii)"),
    ({"outcome": "running_at_limit", "funded_seconds": 600, "label": "sustained run: still running when the sandbox stopped it at its 600 s limit"}, True, "(iii)"),
    ({"outcome": "running_at_limit", "funded_seconds": 300, "label": "sustained run: still running ... (funding-limited: the gate cap left less than requested)"}, False, "funding-limited"),
    ({"outcome": "running_at_limit", "funded_seconds": 600, "label": "(funding-limited: x)"}, False, "not confirmed"),
    ({"outcome": "failed", "funded_seconds": 600, "label": "the command failed after 200 s"}, False, "failed"),
    ({"outcome": "error", "label": "did not produce a result"}, False, "error"),
    ({"outcome": "not_run", "label": "funds 40 s, below the minimum"}, False, "not_run"),
    (None, False, "no sustained run"),
])
def test_a_smoke_alive_pass_counts_only_if_the_sustained_run_confirms_it(sustained, confirmed, fragment):
    row = _mod().confirmation(_runs(), sustained)
    assert row["kind"] == "smoke_alive" and row["confirmed"] is confirmed and fragment in row["why"]


def test_a_command_that_finished_by_itself_needs_no_sustained_run():
    m = _mod()
    exited = m.confirmation(_runs(outcome="exited"), None)
    assert exited["kind"] == "smoke_exited" and exited["confirmed"] and "(i)" in exited["why"]
    clean = {"batch": {"entry_id": 2}, "corpus_entry": {"name": "o__r2"}, "result": {"verdict": "RUNS_CLEAN", "attempts": []}}
    row = m.confirmation(clean, None)
    assert row["kind"] == "baseline_complete" and row["confirmed"]


def test_a_record_with_no_smoke_run_to_sustain_is_not_confirmed():
    record = _runs()
    record["result"]["attempts"] = []
    row = _mod().confirmation({**record, "result": {"verdict": "RUNS_AFTER_REPAIR", "attempts": []}}, None)
    assert row["kind"] == "no_smoke_record" and not row["confirmed"]


def test_other_verdicts_are_never_confirmed():
    for verdict in ("BLOCKED", "INDETERMINATE", "TIMEOUT", "INFRA_ERROR"):
        row = _mod().confirmation({"batch": {"entry_id": 3}, "corpus_entry": {"name": "x"}, "result": {"verdict": verdict, "taxonomy_code": "X"}}, {"outcome": "completed"})
        assert row["confirmed"] is False and "not a RUNS_" in row["why"]


def test_the_result_counts_confirmed_entries_against_the_target_and_only_a_complete_run_can_meet_it():
    m = _mod()
    ids = list(m.TEST_ENTRIES)
    records = [_runs(i) for i in ids]
    sustained = [{"entry": i, "outcome": "completed", "funded_seconds": 600} for i in ids[:3]]
    full = m.evaluate(records, sustained, {1: 1, 2: 2})
    assert full["confirmed_count"] == 3 and full["target_met"] is True and full["runs_verdict_count_at_smoke_level"] == 8
    assert full["dev_rounds_smoke_level_counts"] == {1: 1, 2: 2} and "not a rate" in full["note"]
    partial = m.evaluate(records[:5], sustained, {})
    assert partial["confirmed_count"] == 3 and partial["target_met"] is False  # five entries ran: the target is never claimed on an incomplete phase
    none = m.evaluate(records, [], {})
    assert none["confirmed_count"] == 0 and none["target_met"] is False


def test_harness_v17_labels_a_resource_adapted_or_semantic_change_row_and_counts_without_the_adapted_ones():
    m = _mod()
    ids = list(m.TEST_ENTRIES)
    records = [_runs(i) for i in ids]
    records[0]["result"]["attempts"] = [*records[0]["result"]["attempts"],
                                        {"origin": "time_machine", "attempt_number": 0, "exit_code": 137,
                                         "time_machine_action": {"rule": "resource_adapt", "label": "RESOURCE-ADAPTED: --batch_size 256->128"}}]
    sustained = [{"entry": i, "outcome": "completed", "funded_seconds": 600} for i in ids[:3]]
    doc = m.evaluate(records, sustained, {})
    assert doc["confirmed_count"] == 3 and doc["confirmed_count_without_resource_adapted"] == 2 and doc["confirmed_with_semantic_change"] == 0
    first = next(r for r in doc["rows"] if r["entry"] == ids[0])
    assert first["resource_adapted"] == "RESOURCE-ADAPTED: --batch_size 256->128" and first["verdict_label"].endswith("(RESOURCE-ADAPTED: --batch_size 256->128)")


# --- the freeze ------------------------------------------------------------------------------------------------------------------------------

def _git(commit="a" * 40, remote_commit=None, changed="", tags=(), dev_tag_commit="b" * 40, missing=False):
    remote_commit = commit if remote_commit is None else remote_commit

    def git(*args):
        if args[0] == "rev-parse" and args[1].startswith("refs/tags/harness-v1.5-final"):
            if missing:
                raise subprocess.CalledProcessError(1, "git")
            return commit
        if args[0] == "rev-parse":
            return dev_tag_commit
        if args[0] == "ls-remote":
            return f"{remote_commit}\t{args[-1]}" if remote_commit else ""
        if args[0] == "diff":
            return changed
        if args[0] == "tag":
            return "\n".join(tags)
        raise AssertionError(args)

    return git


def test_the_freeze_check_passes_only_for_a_pushed_final_tag_with_unchanged_harness_paths():
    m = _mod()
    m.check_frozen("harness-v1.5-final", git=_git(tags=("harness-v1.5.0", "harness-v1.5.1")))
    for kwargs, fragment in (({"missing": True}, "does not exist"), ({"remote_commit": "c" * 40}, "origin does not have"), ({"remote_commit": ""}, "origin does not have"),
                             ({"changed": "backend/app/services/orchestrator.py"}, "differ"), ({"tags": ("harness-v1.5.2",), "dev_tag_commit": "a" * 40}, "DEV round tag")):
        with pytest.raises(SystemExit) as exc:
            m.check_frozen("harness-v1.5-final", git=_git(**kwargs))
        assert fragment in str(exc.value)
    with pytest.raises(SystemExit):
        m.check_frozen("harness-v1.5.1", git=_git())  # a DEV tag is never the TEST phase's tag


def test_the_firewall_is_lifted_only_after_every_check_in_the_runner():
    source = (HERE / "run_test_phase.py").read_text(encoding="utf-8")
    lift = source.index("os.environ[firewall.FROZEN_ENV]")
    for check in ("run_dev.check_pre_registration()", "check_frozen(args.tag)", "drv.preflight(\"corpus-v2\", args.tag)", "REFUSED: ledger"):
        assert source.index(check) < lift, check
    assert source.count("os.environ[firewall.FROZEN_ENV]") == 1
