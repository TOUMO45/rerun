"""harness-v1.8 (T19, D-53): the record keeps what an audit needs.

  - A step that exited 0 keeps the last 2,000 characters of each stream in `operations[].streams.tail`. TEST-B's audit of #6 (`python run.py --help`) could not read what the
    command printed (the record kept only sizes and SHA-256 hashes), took the missing text for empty, and struck the entry under the wrong rule; the right rule was
    proven by reproducing the stream byte for byte (reports/test-b/audit_06/).
  - A model's file_edits / file_replacements are stored whole, as valid JSON, up to 200,000 characters; a larger patch is stored as valid JSON that says it was cut, with
    its size, hash and first 6,000 characters. Until v1.7.2 the string was cut at 6,000 characters in the middle of the JSON (TEST #6 rocgan's record), so no replay could
    parse it.
Offline: a scripted sandbox; the real classifier, patch pipeline, gate and orchestrator run."""

from __future__ import annotations

import json
import subprocess

from app.services import orchestrator
from app.services.cost_guard import CostGuard
from app.services.intake import RepoIntake
from app.services.orchestrator import PipelineDeps, run_pipeline
from app.services.sandbox import SandboxRunResult, StepResult
from app.services.time_machine import LockResult
from test_d24_build_essential import _Chat


def _run(tmp_path, files, results, replies=(), max_attempts=1):
    for name, text in files.items():
        (tmp_path / name).write_text(text, encoding="utf-8", newline="\n")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True, capture_output=True)
    for k, v in (("core.autocrlf", "false"), ("user.email", "t@e.st"), ("user.name", "t")):
        subprocess.run(["git", "config", k, v], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-q", "-m", "x"], cwd=tmp_path, check=True, capture_output=True)
    results = list(results)
    deps = PipelineDeps(
        recon_client=_Chat([{"entrypoint": "main.py", "confidence": 0.9}]), recon_model="r", repair_client=_Chat(replies), repair_model="p",
        adjudicator_client=None, adjudicator_model=None, sandbox_api_key="k", sandbox_wall_clock_seconds=100, sandbox_runner=lambda **kw: results.pop(0),
        tavily_client=None, smoke_seconds=0, max_attempts=max_attempts, lock_compiler=lambda *a: LockResult(True, ("numpy==1.19.1",), ("numpy",)),
    )
    guard = CostGuard(daily_cost_ceiling_usd=100)
    intake = RepoIntake(tmp_path, "a" * 40, {}, frozenset(), (), ("main.py",), None)
    result = run_pipeline(repo_url="https://example.com/r", commit_sha="a" * 40, workdir=tmp_path, intake_result=intake, deps=deps, cost_guard=guard, run_id="t19")
    return result, guard


def _step(code, stdout="", stderr=""):
    return SandboxRunResult(steps=(StepResult("python main.py", code, stdout, stderr, 1.0, 0.01),))


def test_a_clean_run_keeps_the_end_of_its_output_beside_the_hashes(tmp_path):
    out = "usage: run.py [-h] [--model MODEL]\n" + "x" * 3000 + "\nlast line\n"
    result, guard = _run(tmp_path, {"main.py": "print(1)\n"}, [_step(0, out, "a warning\n")])
    assert result.verdict == "RUNS_CLEAN" or result.verdict == "INDETERMINATE"  # a usage message is the D-46 audit's business, not this test's
    streams = guard.operations[0]["streams"]
    assert streams["tail"]["stdout"] == out[-2000:] and streams["tail"]["stderr"] == "a warning\n" and streams["tail"]["cap_chars"] == 2000
    assert streams["stdout"]["bytes"] == len(out.encode()) and len(streams["stdout"]["sha256"]) == 64  # the hashes are still there


def test_a_failed_run_keeps_no_tail_in_the_stream_record(tmp_path):
    """Its tails are already in the attempt records; the stream record stays as it was."""
    result, guard = _run(tmp_path, {"main.py": "print(1)\n"}, [_step(1, "", "ValueError: no\n")] * 4)
    assert "tail" not in guard.operations[0]["streams"]


def test_a_model_patch_longer_than_6000_characters_is_stored_whole_and_parses(tmp_path):
    old, new = "x = '" + "a" * 3500 + "'", "x = '" + "b" * 3500 + "'"
    fix = {"file_edits": [{"path": "main.py", "old": old, "new": new}], "env_delta": [], "cited_sources": [], "reason_no_citation": "none", "explanation": "e"}
    result, _ = _run(tmp_path, {"main.py": old + "\nraise ValueError('boom')\n"}, [_step(1, "", "ValueError: boom\n")] * 4, replies=[fix])
    patch = next(a.model_patch for a in result.attempts if a.model_patch)
    assert len(patch) > 6000
    parsed = json.loads(patch)  # valid JSON: until v1.7.2 this string was cut at 6000 characters
    assert parsed["file_edits"][0]["old"] == old and parsed["file_edits"][0]["new"] == new


def test_a_patch_too_large_to_store_is_valid_json_that_says_so(tmp_path, monkeypatch):
    monkeypatch.setattr(orchestrator, "RAW_PATCH_MAX_CHARS", 500)
    old, new = "x = '" + "a" * 700 + "'", "x = '" + "b" * 700 + "'"
    fix = {"file_edits": [{"path": "main.py", "old": old, "new": new}], "env_delta": [], "cited_sources": [], "reason_no_citation": "none", "explanation": "e"}
    result, _ = _run(tmp_path, {"main.py": old + "\nraise ValueError('boom')\n"}, [_step(1, "", "ValueError: boom\n")] * 4, replies=[fix])
    patch = json.loads(next(a.model_patch for a in result.attempts if a.model_patch))
    assert patch["truncated"] is True and patch["chars"] > 500 and len(patch["sha256"]) == 64
    assert len(patch["head"]) == min(6000, patch["chars"])


# ------------------------------------------------------------------------------------------------------------ T17 (cost guard record)

def test_t17_an_estimate_that_pushes_an_entry_over_its_cap_is_labelled_as_one():
    """TEST #13 neo_gnns: $4.18 recorded against a $2.50 cap = $0.5 measured + a $3.66 ESTIMATE for a killed step."""
    guard = CostGuard(daily_cost_ceiling_usd=2.5)
    guard.record_spend(0.52)
    guard.record_killed_operation(0.0, 241.0, note="killed after 241s")
    status = guard.cap_status()
    assert round(guard.spent_today_usd, 2) == 4.18 and status["cap_usd"] == 2.5
    assert round(status["over_cap_usd"], 2) == 1.68 and status["over_cap_estimated_only"] is True and round(status["estimated_usd"], 2) == 3.66


def test_t17_a_measured_overrun_is_not_called_an_estimate():
    guard = CostGuard(daily_cost_ceiling_usd=2.5)
    guard.record_spend(3.0)
    assert guard.cap_status()["over_cap_usd"] == 0.5 and guard.cap_status()["over_cap_estimated_only"] is False
    under = CostGuard(daily_cost_ceiling_usd=2.5)
    under.record_spend(1.0)
    assert under.cap_status() == {"cap_usd": 2.5, "over_cap_usd": 0.0, "estimated_usd": 0.0, "over_cap_estimated_only": False}
