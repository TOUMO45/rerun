"""harness-v1.7.2: D-46 (an exit code 0 read as success whatever the run printed) and D-47 (the repairer's patches to a tab-indented file do not parse).

Every case replays recorded evidence; nothing is fetched, nothing runs live. The real classifier, tamper gate, patch pipeline and orchestrator run with a fake
sandbox runner and a fake model client (test_v151_pins_and_removals._pipeline).

  D-46 (a)  TEST #18 (runs/corpus_v2_batch/harness-v1.5-final/test/18_aam-at__adversary_critic.json): `python generate_script.py --train=True | bash`, exit 0,
            stdout empty, stderr 154 bytes. The traceback text is rebuilt and checked against the stored SHA-256 of the stream before it is replayed.
  D-46 (b)  DEV #12 (`Mehran-k/SimplE` main.py, no arguments): prints `Please specify the model name using -m.` and exits 0 (from the source, not run).
  D-46 (c)  live UI scan (`faris-shi/py_weather_cli`, 2026-10-05, runs/live_scan/ in the main checkout): the adopted repair's run printed only that the
            openweathermap API key is missing and exited 0; the record's stdout is copied below.
  D-47      live UI run of DEV #15 (runs/live_ui/2026-10-05_dev15_latent_ode_api_certificate.json): the six patches the gate refused as UNPARSEABLE_PATCH.
            `run_models.py` itself is not in the repository and is not fetched: the lines the six diffs keep and remove (17 of them, at lines 90-98 and
            222-229) are rebuilt from the diff text, and the rest of the file is scaffolding written here (`# reconstructed filler`, and 5 lines that give
            the hunk at line 222 its enclosing `if/elif`). The reconstruction reproduces the gate's six recorded refusals word for word.
"""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path

import pytest
from unidiff import PatchSet

from app.services import adjudicator, exit_zero_check, indentation, outcome_levels, repairer, sustained_run, tamper_gate
from app.services.classifier import Classification
from app.services.sandbox import SandboxRunResult, StepResult
from test_v151_pins_and_removals import _fail, _ok, _pipeline

ROOT = Path(__file__).resolve().parents[2]
TEST18 = ROOT / "runs" / "corpus_v2_batch" / "harness-v1.5-final" / "test" / "18_aam-at__adversary_critic.json"
DEV15_UI = ROOT / "runs" / "live_ui" / "2026-10-05_dev15_latent_ode_api_certificate.json"

TEST18_STDERR = (
    "Traceback (most recent call last):\n"
    '  File "generate_script.py", line 8, in <module>\n'
    "    import decorator\n"
    "ModuleNotFoundError: No module named 'decorator'\n"
)
TEST18_STDERR_SHA256 = "5c4c19a43604794b1bb52f532b020f44f6a05982f8c0c45865800ffa8ecc1164"
SIMPLE_USAGE = "Please specify the model name using -m.\n"
# runs/live_scan/2026-10-05_faris-shi__py_weather_cli_api_certificate.json, diffs[9] (attempt 3, candidate 1, chosen): stdout_tail, stderr_tail ''.
WEATHER_STDOUT = "No openweathermap.org API key specified.\nYou have to register for one at https://home.openweathermap.org/users/sign_up\n"


def _run(exit_code, stdout="", stderr="", seconds=1.0, command="python train.py"):
    return SandboxRunResult(steps=(StepResult(command, exit_code, stdout, stderr, seconds, 0.01),))


# ================================================================================================================ D-46

def _test18() -> dict:
    return json.loads(TEST18.read_text(encoding="utf-8"))


def test_d46_the_rebuilt_traceback_is_test_18s_recorded_stderr():
    record = _test18()
    baseline = record["operations"][0]
    assert record["result"]["verdict"] == "RUNS_CLEAN" and baseline["role"] == "baseline" and baseline["exit_code"] == 0
    stream = baseline["streams"]["stderr"]
    assert stream["sha256"] == TEST18_STDERR_SHA256 == hashlib.sha256(TEST18_STDERR.encode("utf-8")).hexdigest()
    assert stream["bytes"] == len(TEST18_STDERR.encode("utf-8")) == 154
    assert baseline["streams"]["stdout"]["bytes"] == 0
    run_seconds = baseline["sandbox_seconds"] - sum(s["seconds"] for s in baseline["install_seconds"]) - sum(s["seconds"] for s in baseline["rerun_steps"])
    assert 0 <= run_seconds < 1.0  # the run step took about 0.1 s (METHODOLOGY / D-46 audit)


def test_d46_replay_test_18_the_pipe_exit_0_with_a_traceback_is_not_runs_clean(tmp_path):
    """The real orchestrator, the TEST #18 baseline replayed (exit 0, the 154-byte traceback): no longer RUNS_*. It is classified from the traceback
    (DEP_MISSING, `decorator`) and proceeds like a failed run; here the deterministic steps cannot install it offline and the model declines."""
    record = _test18()
    command = record["corpus_entry"]["command"]
    assert command == "python generate_script.py --train=True | bash"
    baseline = _run(0, "", TEST18_STDERR, seconds=0.1, command=command)
    decline = {"file_edits": None, "env_delta": [], "cited_sources": [], "reason_no_citation": "none", "explanation": "cannot fix offline"}
    result, _, _, left = _pipeline(tmp_path, [baseline] + [_run(0, "", TEST18_STDERR, seconds=0.1, command=command)] * 6,
                                   files={"generate_script.py": "import decorator\n", "train.py": "x = 1\n"}, replies=[decline] * 6, max_attempts=1)
    assert result.verdict not in ("RUNS_CLEAN", "RUNS_AFTER_REPAIR")
    assert result.baseline["result"] == "FAILS" and result.baseline["exit_code"] == 0  # the recorded exit code stays 0
    assert result.baseline["exit_zero_check"]["kind"] == "traceback"
    assert result.baseline["exit_zero_check"]["evidence"] == "ModuleNotFoundError: No module named 'decorator'"
    assert result.baseline["taxonomy_code"] == "DEP_MISSING"
    assert result.error_chain[0]["class"] == "DEP_MISSING" and result.error_chain[0]["exit_zero_check"]["overruled"]
    assert "[exit-0 check] baseline: exit code 0 overruled (traceback" in result.full_log
    assert result.outcome_levels["exit_zero_overruled"].startswith("exit 0 overruled: ModuleNotFoundError")
    assert "exit 0 overruled" in outcome_levels.verdict_label(result.certificate())


def test_d46_a_traceback_exit_0_then_a_repair_that_passes_ends_runs_after_repair(tmp_path):
    """The overruled baseline is a failure like any other: when the next run passes, the verdict is RUNS_AFTER_REPAIR (recovery), labelled."""
    fix = {"env_delta": [{"op": "add", "package": "decorator", "version": None, "justification": "missing module",
                          "evidence": "No module named 'decorator'"}], "cited_sources": [], "reason_no_citation": "none", "explanation": "add decorator"}
    result, _, _, _ = _pipeline(tmp_path, [_run(0, "", TEST18_STDERR, 0.1)] + [_ok()] * 4, files={"train.py": "import decorator\n"}, replies=[fix])
    assert result.verdict == "RUNS_AFTER_REPAIR" and result.recovery
    assert "exit 0 overruled" in outcome_levels.verdict_label(result.certificate())


def test_d46_usage_message_and_exit_0_ends_indeterminate_entrypoint_needs_args(tmp_path):
    result, repair, _, _ = _pipeline(tmp_path, [_run(0, SIMPLE_USAGE, "", 0.4, "python main.py")], files={"main.py": "print('x')\n", "train.py": "x\n"})
    assert result.verdict == "INDETERMINATE"
    assert result.indeterminate_reason.startswith("ENTRYPOINT_NEEDS_ARGS: ")
    assert "Please specify the model name using -m." in result.indeterminate_reason
    assert result.taxonomy_code is None and not repair.calls and not result.attempts  # no repair, no model call
    assert result.baseline["exit_zero_check"]["kind"] == "usage" and result.baseline["evidence"] == "Please specify the model name using -m."


def test_d46_an_argparse_help_block_with_exit_0_is_a_usage_message():
    help_text = "usage: main.py [-h] [-m MODEL] [-d DATASET]\n\noptional arguments:\n  -h, --help  show this help message and exit\n  -m MODEL\n"
    found = exit_zero_check.check(0, help_text, "", 0.5)
    assert found is not None and found.kind == "usage" and found.evidence.startswith("usage: main.py")


def test_d46_c_replay_the_weather_cli_run_missing_api_key_ends_needs_credentials(tmp_path):
    """The live scan's adopted repair: the run printed only that the API key is missing and exited 0 (~2 s of sandbox time for the whole operation).
    Replayed as the run after a model repair: INDETERMINATE NEEDS_CREDENTIALS, the message quoted; the model's injected default is labelled."""
    found = exit_zero_check.check(0, WEATHER_STDOUT, "", 2.0)
    assert found is not None and found.kind == "missing" and found.code == "NEEDS_CREDENTIALS"
    assert found.evidence == "No openweathermap.org API key specified."
    main = ("def cli(city):\n    name = city\n    if not name:\n        raise ValueError('please enter the city name')\n    print(name)\n\ncli(None)\n")
    baseline = _fail("Traceback (most recent call last):\n  File \"main.py\", line 7, in <module>\n    cli(None)\n"
                     "  File \"main.py\", line 4, in cli\n    raise ValueError('please enter the city name')\nValueError: please enter the city name\n")
    fix = {"file_edits": [{"path": "main.py", "old": "        raise ValueError('please enter the city name')", "new": "        name = 'Toronto'"}],
           "env_delta": [], "cited_sources": [], "reason_no_citation": "none", "explanation": "default city"}
    result, _, _, _ = _pipeline(tmp_path, [baseline, _run(0, WEATHER_STDOUT, "", 2.0, "python main.py")], files={"main.py": main, "train.py": "x\n"},
                                replies=[fix])
    assert result.verdict == "INDETERMINATE" and result.verdict != "RUNS_AFTER_REPAIR"
    assert result.indeterminate_reason.startswith("NEEDS_CREDENTIALS: ") and "No openweathermap.org API key specified." in result.indeterminate_reason
    model = [a for a in result.attempts if a.origin == "model"][-1]
    assert model.exit_code == 0 and model.execution["exit_zero_check"]["kind"] == "missing"
    assert model.as_dict()["semantic_change"] == ["injected default"]
    assert not outcome_levels.attempt_passed(model.as_dict())


def test_d46_c_a_missing_message_without_a_credential_word_is_entrypoint_needs_args():
    found = exit_zero_check.check(0, "Error: config file not specified.\n", "", 0.3)
    assert found is not None and found.kind == "missing" and found.code == "ENTRYPOINT_NEEDS_ARGS"
    assert exit_zero_check.stop_reason(found.as_dict()).startswith("ENTRYPOINT_NEEDS_ARGS: ")


# ---------------------------------------------------------------------------------------------------- D-46 negative controls

def test_d46_control_a_normal_exit_0_run_stays_runs_clean(tmp_path):
    result, _, _, _ = _pipeline(tmp_path, [_run(0, "loaded 5000 samples\nepoch 1 loss 0.42\ndone\n", "", 12.0)], files={"train.py": "x = 1\n"})
    assert result.verdict == "RUNS_CLEAN" and "exit_zero_check" not in result.baseline
    assert "exit 0 overruled" not in result.full_log


def test_d46_control_a_long_run_with_a_usage_like_word_in_its_output_stays_runs(tmp_path):
    out = "epoch 1 loss 0.9\nwarning: please specify --seed for reproducibility\nusage: 3.1 GB\nepoch 2 loss 0.5\ndone\n"
    result, _, _, _ = _pipeline(tmp_path, [_run(0, out, "", 240.0)], files={"train.py": "x = 1\n"})
    assert result.verdict == "RUNS_CLEAN"
    assert exit_zero_check.check(0, out, "", 1.0) is None  # not usage-only even when short: real output around it


def test_d46_control_a_long_run_whose_only_output_is_missing_like_stays_runs():
    assert exit_zero_check.check(0, WEATHER_STDOUT, "", 300.0) is None  # same text, but the run worked for minutes
    assert exit_zero_check.check(0, "API key not specified, using the public endpoint\nepoch 1 loss 0.4\n", "", 1.0) is None  # work after it


def test_d46_control_a_caught_traceback_logged_as_a_warning_then_a_long_run_stays_runs(tmp_path):
    """Rule, stated: a traceback FOLLOWED by more stderr output is never overruled; a traceback that is the last thing on stderr of a run that took
    TRACEBACK_MAX_SECONDS or longer is not overruled either (the program may have logged a caught exception, then worked, printing to stdout)."""
    logged = TEST18_STDERR + "WARNING: optional plugin unavailable, continuing without it\n"
    result, _, _, _ = _pipeline(tmp_path, [_run(0, "epoch 1\nepoch 2\ndone\n", logged, 5.0)], files={"train.py": "x = 1\n"})
    assert result.verdict == "RUNS_CLEAN"
    assert exit_zero_check.check(0, "epoch 1\n" * 50, TEST18_STDERR, 900.0) is None
    assert exit_zero_check.check(0, "", TEST18_STDERR, 0.1) is not None  # the same text in a short run IS overruled


def test_d46_control_an_interpreter_shutdown_report_is_not_overruled():
    shutdown = "Exception ignored in: <function Pool.__del__ at 0x7f>\n" + TEST18_STDERR
    assert exit_zero_check.check(0, "done\n", shutdown, 2.0) is None
    chained = TEST18_STDERR + "\nDuring handling of the above exception, another exception occurred:\n\n" + TEST18_STDERR
    assert exit_zero_check.check(0, "", chained, 0.2).kind == "traceback"


def test_d46_control_a_smoke_run_alive_at_its_limit_and_a_failed_exit_are_never_findings():
    assert exit_zero_check.check(0, "step 1\nRERUN_SMOKE_ALIVE after 60 s\n", "", 60.5) is None
    assert exit_zero_check.check(1, "", TEST18_STDERR, 0.1) is None  # a non-zero exit is the classifier's, as before
    assert exit_zero_check.check(0, "", TEST18_STDERR, 0.1, phase="repo_install") is None


def test_d46_not_retroactive_old_records_read_as_before():
    """A stored attempt / stage with exit code 0 and no `exit_zero_check` (every record before v1.7.2) still reads as passed; TEST #18 keeps its verdict."""
    assert outcome_levels.attempt_passed({"exit_code": 0, "execution": {"mode": "smoke", "outcome": "exited"}})
    assert adjudicator.stage_rank({"exit_code": 0, "phase": "repo_run"}) == (1, 3, 0, 0, 0.0)
    overruled = {"exit_code": 0, "phase": "repo_run", "exit_zero_check": {"overruled": True, "kind": "traceback"}}
    assert adjudicator.stage_rank(overruled)[0] == 0 and adjudicator.advance_key(overruled)[0] == 0
    assert _test18()["result"]["verdict"] == "RUNS_CLEAN"  # the record is never rewritten
    assert outcome_levels.exit_zero_overruled(_test18()["result"]) == ""


def test_d46_the_sustained_run_does_not_call_an_overruled_exit_0_completion():
    step = StepResult("python x.py", 0, "", TEST18_STDERR, 0.2, 0.0)
    outcome, label = sustained_run.outcome_of(step, funded=600)
    assert outcome == "failed" and "overruled" in label
    assert sustained_run.outcome_of(StepResult("python x.py", 0, "done\n", "", 200.0, 0.0), funded=600)[0] == "completed"


# ================================================================================================================ D-47

_SCAFFOLD = {218: 'if __name__ == "__main__":', 219: "\tif args.classic_rnn:", 220: "\t\tpass", 221: "\telif args.latent_ode:", 230: "\tprint(model)"}


def _dev15() -> dict:
    return json.loads(DEV15_UI.read_text(encoding="utf-8"))


def _rejected() -> list[dict]:
    return [a for a in _dev15()["diffs"] if a["gate_decision"] == "REJECT"]


def _reconstructed_run_models() -> str:
    """The lines the six recorded diffs keep or remove, at their recorded line numbers, read from the diffs; everything else is scaffolding."""
    known: dict[int, str] = {}
    for attempt in _rejected():
        for patched in PatchSet(attempt["diff_text"]):
            for hunk in patched:
                n = hunk.source_start
                for line in hunk:
                    if line.is_context or line.is_removed:
                        text = line.value.rstrip("\n")
                        assert known.setdefault(n, text) == text  # the six diffs agree on every line they share
                        n += 1
    assert sorted(known) == [*range(90, 99), *range(222, 230)]
    lines = [known.get(n, _SCAFFOLD.get(n, "# reconstructed filler (not the file)")) for n in range(1, 231)]
    source = "\n".join(lines) + "\n"
    ast.parse(source)
    return source


def test_d47_the_record_holds_six_patches_refused_for_indentation_and_the_file_is_tab_indented():
    rejected = _rejected()
    assert len(rejected) == 6
    assert all(v["rule"] == "UNPARSEABLE_PATCH" for a in rejected for v in a["gate_violations"])
    source = _reconstructed_run_models()
    assert indentation.detect(source) == indentation.Indentation("tabs")
    for attempt in rejected:  # every added line of every patch is indented with spaces
        added = [line[1:] for line in attempt["diff_text"].splitlines() if line.startswith("+") and not line.startswith("+++") and line[1:].strip()]
        assert added and not any(line.startswith("\t") for line in added)


def test_d47_the_reconstruction_reproduces_the_gates_six_recorded_refusals_word_for_word():
    source = _reconstructed_run_models()
    for attempt in _rejected():
        before = tamper_gate.check_patch(attempt["diff_text"], {"run_models.py": source})
        assert [v.reason for v in before.violations] == [v["reason"] for v in attempt["gate_violations"]]


@pytest.mark.parametrize("index", range(6))
def test_d47_each_recorded_patch_is_normalised_to_tabs_and_then_passes_every_gate_rule(index):
    source = _reconstructed_run_models()
    attempt = _rejected()[index]
    done = indentation.normalise_patch(attempt["diff_text"], {"run_models.py": source})
    assert done is not None
    diff, records = done
    assert [(r["file"], r["to"]) for r in records] == [("run_models.py", "tabs")] and records[0]["from"].startswith("spaces")
    assert records[0]["parse_error"].split(":")[0] in ("IndentationError", "TabError")
    gate = tamper_gate.check_patch(diff, {"run_models.py": source})
    assert gate.decision == "PASS", [v.reason for v in gate.violations]
    assert not tamper_gate.py_compile_violations(diff, {"run_models.py": source})
    # only leading whitespace changed: the added code is the model's, character for character
    def added(text):
        return sorted(line[1:].strip() for line in text.splitlines() if line.startswith("+") and not line.startswith("+++") and line[1:].strip())
    model_added = added(attempt["diff_text"])
    assert set(added(diff)) <= set(model_added)
    new_lines = [line[1:] for line in diff.splitlines() if line.startswith("+") and not line.startswith("+++") and line[1:].strip()]
    assert all(not line.startswith(" ") for line in new_lines)


def test_d47_the_gates_other_rules_still_run_on_a_normalised_patch():
    """A space-indented patch to the tab file that ALSO deletes an evaluation call: normalised (it parses), then refused for the deleted call."""
    source = "def evaluate(m):\n\treturn m\n\ndef main():\n\tm = 1\n\tevaluate(m)\n\tprint(m)\n\nmain()\n"
    diff = "--- a/run.py\n+++ b/run.py\n@@ -4,4 +4,4 @@\n def main():\n \tm = 1\n-\tevaluate(m)\n+    m = 2\n \tprint(m)\n"
    done = indentation.normalise_patch(diff, {"run.py": source})
    assert done is not None
    gate = tamper_gate.check_patch(done[0], {"run.py": source}, eval_call_names=frozenset({"evaluate"}))
    assert gate.decision == "REJECT" and [v.rule for v in gate.violations] == ["DELETED_EVAL_CALL"]


def test_d47_control_a_space_indented_file_and_a_correct_patch_are_untouched():
    source = "def main():\n    if True:\n        x = 1\n    print(x)\n\nmain()\n"
    good = "--- a/run.py\n+++ b/run.py\n@@ -2,4 +2,4 @@\n     if True:\n-        x = 1\n+        x = 2\n     print(x)\n \n"
    assert indentation.normalise_patch(good, {"run.py": source}) is None  # it parses: nothing to do
    wrong_level = "--- a/run.py\n+++ b/run.py\n@@ -2,4 +2,4 @@\n     if True:\n-        x = 1\n+          x = 2\n     print(x)\n \n"
    assert indentation.normalise_patch(wrong_level, {"run.py": source}) is None  # same convention: the patch's own error, not normalised
    assert tamper_gate.check_patch(wrong_level, {"run.py": source}).decision == "PASS"  # (10 spaces under `if`: still valid Python)
    bad = "--- a/run.py\n+++ b/run.py\n@@ -2,4 +2,4 @@\n     if True:\n-        x = 1\n+  x = 2\n     print(x)\n \n"
    assert indentation.normalise_patch(bad, {"run.py": source}) is None
    assert tamper_gate.check_patch(bad, {"run.py": source}).violations[0].rule == "UNPARSEABLE_PATCH"


def test_d47_a_two_space_file_and_a_four_space_patch_is_normalised_to_two_spaces():
    source = "def main(m):\n  if m:\n    x = 1\n  else:\n    raise SystemExit('no model')\n  print(x)\n\nmain(1)\n"
    diff = ("--- a/run.py\n+++ b/run.py\n@@ -4,3 +4,4 @@\n   else:\n-    raise SystemExit('no model')\n+            x = 2\n+        print(x)\n"
            "   print(x)\n")
    assert tamper_gate.check_patch(diff, {"run.py": source}).violations[0].rule == "UNPARSEABLE_PATCH"  # unindent does not match
    done = indentation.normalise_patch(diff, {"run.py": source})
    assert done is not None and done[1][0]["to"] == "2 spaces" and done[1][0]["from"] == "spaces (unit 4)"
    assert "+    x = 2\n+  print(x)\n" in done[0]
    assert tamper_gate.check_patch(done[0], {"run.py": source}).decision == "PASS"


def test_d47_control_a_patch_with_a_real_syntax_error_is_still_refused():
    source = _reconstructed_run_models()
    broken = (_rejected()[0]["diff_text"]).replace("n_labels = n_labels)\n \n", "n_labels = n_labels\n \n", 1)  # an unclosed parenthesis
    assert broken != _rejected()[0]["diff_text"]
    assert indentation.normalise_patch(broken, {"run_models.py": source}) is None
    gate = tamper_gate.check_patch(broken, {"run_models.py": source})
    assert gate.decision == "REJECT" and gate.violations[0].rule == "UNPARSEABLE_PATCH"


def test_d47_the_repair_prompt_names_the_files_indentation():
    cls = Classification(code="RUNTIME_ERROR_OTHER", family="code", evidence="Exception: Model not specified", matched_pattern="x")
    tabs = repairer.build_repair_user_prompt(cls, "run_models.py", _reconstructed_run_models())
    assert "Indentation of run_models.py: TABS" in tabs
    spaces = repairer.build_repair_user_prompt(cls, "train.py", "def f():\n    return 1\n")
    assert "Indentation of train.py: 4 spaces per level" in spaces


def test_d47_in_the_pipeline_a_space_indented_edit_to_a_tab_file_is_normalised_gated_applied_and_recorded(tmp_path):
    """DEV #15's first patch, as the model sent it (file_edits, spaces), against a small tab-indented file with the same branch."""
    main = ("import sys\n\ndef main(model):\n\tif model == 'a':\n\t\tm = 1\n\telse:\n\t\traise Exception(\"Model not specified\")\n\tprint(m)\n\n"
            "main(None)\n")
    fix = {"file_edits": [{"path": "train.py", "old": "    else:\n        raise Exception(\"Model not specified\")",
                           "new": "    else:\n        m = 1"}], "env_delta": [], "cited_sources": [], "reason_no_citation": "none", "explanation": "default"}
    failing = _fail("Traceback (most recent call last):\n  File \"train.py\", line 10, in <module>\n    main(None)\n"
                    "  File \"train.py\", line 7, in main\n    raise Exception(\"Model not specified\")\nException: Model not specified\n")
    result, repair, _, _ = _pipeline(tmp_path, [failing, _ok()], files={"train.py": main}, replies=[fix])
    assert "Indentation of train.py: TABS" in json.dumps(repair.calls[0], default=str)
    assert result.verdict == "RUNS_AFTER_REPAIR", result.full_log[-1500:]
    attempt = [a for a in result.attempts if a.origin == "model"][-1]
    assert attempt.gate_decision == "PASS"
    assert attempt.as_dict()["indentation_normalised"][0]["to"] == "tabs"
    assert "\t\tm = 1" in attempt.diff_text and "+        m = 1" not in attempt.diff_text
    assert any("indentation normalised" in note for note in attempt.patch_notes)
    assert attempt.model_patch  # what the model sent is kept beside the applied diff
    assert (tmp_path / "train.py").read_text(encoding="utf-8").count("\t\tm = 1") == 2


# ================================================================================================================ R6: an injected default input

def test_r6_injected_default_flags_the_weather_cli_patches_and_nothing_older_is_reflagged():
    chosen = ("--- a/py_weather_cli/main.py\n+++ b/py_weather_cli/main.py\n@@ -61,7 +61,12 @@\n def cli(city, unit):\n     check_config()\n"
              "     weather_config = load_config()\n-    weather_config.city_name = city\n"
              "+    # If the city name from config is empty, set it to a default (Toronto)\n"
              "+    if not weather_config.city_name or len(weather_config.city_name) == 0:\n+        weather_config.city_name = 'Toronto'\n"
              "+    # Override with command line argument if provided (non-empty)\n+    if city:\n+        weather_config.city_name = city\n"
              "     weather_config.unit = unit\n \n     if not weather_config.city_name or len(weather_config.city_name) == 0:\n")
    removes_raise = ("--- a/py_weather_cli/main.py\n+++ b/py_weather_cli/main.py\n@@ -66,6 +66,6 @@\n"
                     "     if not weather_config.city_name or len(weather_config.city_name) == 0:\n"
                     "-        raise ValueError('please enter the city name')\n+        weather_config.city_name = 'Toronto'\n \n")
    assert tamper_gate.injected_default(chosen) == ("injected default",)
    assert tamper_gate.injected_default(removes_raise) == ("injected default",)
    assert tamper_gate.semantic_change_calls(chosen) == ()  # R6's v1.7 list is unchanged: a stored record re-read is never newly flagged
    plain = "--- a/x.py\n+++ b/x.py\n@@ -1,2 +1,2 @@\n x = load()\n-y = 1\n+y = 2\n"
    assert tamper_gate.injected_default(plain) == ()
    old = {"verdict": "RUNS_AFTER_REPAIR", "attempts": [{"origin": "model", "gate_decision": "PASS", "diff_text": chosen, "exit_code": 0}]}
    assert outcome_levels.semantic_change(old) == ()
