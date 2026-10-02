"""harness-v1.4.3-rc: the independent review of the release candidate (reports/corpus-v2.1/v1.4.3/STEP1_REPORT.md, section 8) found what the author's own tests did not. Each test below pins
one finding that was fixed (the pipeline-level ones are in test_v143_pipeline.py: the last attempt's cut stream, the cut ALIVE line, the command a smoke run executed)."""

from __future__ import annotations

import time
import uuid as uuidlib
from types import SimpleNamespace

import pytest

import v140_cloud
from app.services import classifier, sandbox, sustained_run
from app.services.sandbox import StepResult
from test_v143_output_limit import _run


# --- 3. the SDK's strict decoding of a cut stream ------------------------------------------------------------------------------------

def test_a_cut_inside_a_multibyte_character_comes_back_without_an_exception_the_half_character_replaced(monkeypatch):
    monkeypatch.setattr(sandbox, "OUTPUT_LIMIT_BYTES", 4000)  # 4000 = 1 byte past a multiple of 3: the cut lands inside a three-byte character
    _, result = _run(monkeypatch, "█" * 2000)
    final = result.final
    assert final.stderr_truncated is True and final.stderr.endswith("�") and len(final.stderr) == 1334  # 1333 whole characters and the replacement
    assert final.streams()["stderr"]["bytes"] == 1333 * 3 + 3  # the replacement character is three bytes: sizes are of what the harness holds, and the flag says it was cut


def test_without_the_byte_request_the_same_stream_raises_inside_the_sdk_the_failure_the_review_reproduced(monkeypatch):
    monkeypatch.setattr(sandbox, "OUTPUT_LIMIT_BYTES", 4000)
    monkeypatch.setattr(sandbox, "_byte_streams", lambda image: {})
    with pytest.raises(UnicodeDecodeError):
        _run(monkeypatch, "█" * 2000)


def test_the_text_helper_decodes_with_replacement_and_passes_text_and_nothing_through():
    assert sandbox._text(b"ab\xe2\x96") == "ab�" and sandbox._text(bytearray(b"ok")) == "ok"
    assert sandbox._text("x") == "x" and sandbox._text(None) == "" and sandbox._text(b"") == ""


def test_bytes_are_requested_only_from_a_run_that_takes_them():
    from contree_sdk.sdk.objects.image_like._base import _ImageLikeBase

    real = SimpleNamespace(run=_ImageLikeBase.run)  # the real SDK's signature has stdout= and stderr=
    assert sandbox._byte_streams(real) == {"stdout": bytes, "stderr": bytes}

    class Older:
        def run(self, shell, timeout, disposable, preserve_env=False):
            ...

    assert sandbox._byte_streams(Older()) == {}  # a test double with the older signature keeps working
    assert sandbox._byte_streams(SimpleNamespace(run=object())) == {}


def test_every_real_run_of_the_runner_is_asked_for_bytes(monkeypatch):
    seen = []
    real_run = v140_cloud.Image.run

    def run(self, shell, timeout, disposable, preserve_env=False, stdout=None, stderr=None):
        if shell != "true":  # the cleanup runs discard their output
            seen.append((stdout, stderr))
        return real_run(self, shell, timeout, disposable, preserve_env, stdout, stderr)

    monkeypatch.setattr(v140_cloud.Image, "run", run)
    _run(monkeypatch, "oops\n")
    assert len(seen) >= 2 and all(pair == (bytes, bytes) for pair in seen)  # the extract step and the command


def test_run_on_image_is_asked_for_bytes_too_and_decodes_a_cut_character_without_raising(monkeypatch):
    monkeypatch.setattr(sandbox, "OUTPUT_LIMIT_BYTES", 4000)
    cloud = v140_cloud.install(monkeypatch, lambda shell, built, files: (1, "", "█" * 2000) if shell == "python train.py" else None)
    image = cloud.new_image(("FROM python:3.10-slim",), {"train.py": b"x"})
    seen = []
    real_run = v140_cloud.Image.run

    def run(self, shell, timeout, disposable, preserve_env=False, stdout=None, stderr=None):
        seen.append((stdout, stderr))
        return real_run(self, shell, timeout, disposable, preserve_env, stdout, stderr)

    monkeypatch.setattr(v140_cloud.Image, "run", run)
    step = sandbox.run_on_image(api_key="k", image_id=image.uuid, command="python train.py", timeout_seconds=30)
    assert seen == [(bytes, bytes)] and step.stderr_truncated is True and step.stderr.endswith("�")


# --- run_on_image: a client-side wait timeout becomes SandboxTimeoutError (tested directly, not by patching run_on_image) -------------------

def test_run_on_image_converts_the_clients_wait_timeout_into_a_sandbox_timeout_error(monkeypatch):
    from contree_sdk.sdk.exceptions import OperationTimedOutError

    cloud = v140_cloud.install(monkeypatch)
    image = cloud.new_image(("FROM python:3.10-slim",), {"main.py": b"x"})

    def run(self, shell, timeout, disposable, preserve_env=False, stdout=None, stderr=None):
        raise OperationTimedOutError(operation_uuid=uuidlib.uuid4())

    monkeypatch.setattr(v140_cloud.Image, "run", run)
    with pytest.raises(sandbox.SandboxTimeoutError) as caught:
        sandbox.run_on_image(api_key="k", image_id=image.uuid, command="sleep 20", timeout_seconds=3)
    assert caught.value.command == "sleep 20" and "wall clock" in str(caught.value) and caught.value.killed_seconds >= 0


# --- 6. the classifier is linear on a long run of digits ----------------------------------------------------------------------------------

@pytest.mark.parametrize("digits", [32_000, 400_000])
def test_a_long_run_of_digits_does_not_make_classification_quadratic(digits):
    """Measured on the unbounded `\\d+` pattern: 8,000 digits 1.2 s, 16,000 4.8 s, 32,000 19.5 s, 64,000 more than a minute. Bounded, it is linear."""
    text = "x" * 10 + "1" * digits + "\nTraceback (most recent call last):\n  File \"a.py\", line 1\nNameError: name 'q' is not defined\n"
    started = time.monotonic()
    result = classifier.classify(1, text, "")
    assert classifier.has_actionable_error(text, "") and result.code != "GPU_REQUIRED"
    assert time.monotonic() - started < 3.0


@pytest.mark.parametrize("line,dropped", [("100.0%", True), ("12.5% done, 99.9% of the rest", True), ("Epoch 3: 100%|███| 10/10", True), ("  7%  ", True),
                                          ("accuracy 0.93", False), ("loss 12345678901234567890", False), ("NameError: name 'x' is not defined", False)])
def test_the_bounded_progress_pattern_still_drops_progress_lines_and_keeps_the_rest(line, dropped):
    assert (classifier.denoise(line) == "") is dropped


# --- 10. the sustained line: labels and funding -------------------------------------------------------------------------------------------

def _record(verdict="RUNS_AFTER_REPAIR", attempts=None):
    return {"batch": {"entry_id": 7}, "corpus_entry": {"name": "x__y", "command": "python main.py"}, "result": {"verdict": verdict, "attempts": attempts or []}}


def test_a_runs_after_repair_record_without_a_passing_smoke_attempt_is_not_called_a_complete_baseline():
    record = _record()
    assert sustained_run.final_run_of(record)["kind"] == "no_smoke_record"
    doc = sustained_run.run_sustained(record, api_key="k", remaining_usd=5.0, runner=lambda **kw: pytest.fail("nothing to run"))
    assert doc["outcome"] == "not_run" and "no passing attempt with a smoke record" in doc["reason"]
    assert sustained_run.final_run_of(_record("RUNS_CLEAN"))["kind"] == "baseline_complete"  # only a RUNS_CLEAN record is the complete baseline


def test_a_run_stopped_at_its_limit_has_no_classification_and_says_when_it_had_printed_an_error():
    alive = [{"attempt_number": 3, "chosen": True, "exit_code": 0, "execution": {"mode": "smoke", "seconds": 60, "outcome": "alive_at_limit", "image": "img", "command": "python main.py"}}]
    stopped = StepResult("python main.py", 137, "", "", 198.1, 2.05, timed_out=True)
    doc = sustained_run.run_sustained(_record(attempts=alive), api_key="k", remaining_usd=3.0, runner=lambda **kw: stopped)
    assert doc["classification"] is None and "it had not failed by then" in doc["label"]
    noisy = StepResult("python main.py", 137, "", "Traceback (most recent call last):\n  File \"a.py\", line 1\nValueError: x\n", 198.1, 2.05, timed_out=True)
    doc = sustained_run.run_sustained(_record(attempts=alive), api_key="k", remaining_usd=3.0, runner=lambda **kw: noisy)
    assert doc["classification"] is None and "it had printed an error text and was still running" in doc["label"] and "had not failed" not in doc["label"]


def test_the_share_of_the_gate_cap_is_among_the_runs_that_spend_not_among_the_ones_that_need_nothing(tmp_path):
    import importlib.util
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location("g143x", root / "reports" / "corpus-v2.1" / "v1.4.3" / "gate" / "run_gate_v143.py")
    gate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gate)
    alive = lambda image: [{"attempt_number": 3, "chosen": True, "exit_code": 0,  # noqa: E731
                            "execution": {"mode": "smoke", "seconds": 60, "outcome": "alive_at_limit", "image": image, "command": "python main.py"}}]
    finished = [{"attempt_number": 3, "chosen": True, "exit_code": 0, "execution": {"mode": "smoke", "seconds": 60, "outcome": "exited", "command": "python main.py"}}]
    records = [{"batch": {"entry_id": 3}, "corpus_entry": {"name": "a__a", "command": "c"}, "result": {"verdict": "RUNS_AFTER_REPAIR", "attempts": finished}},
               {"batch": {"entry_id": 7}, "corpus_entry": {"name": "b__b", "command": "c"}, "result": {"verdict": "RUNS_AFTER_REPAIR", "attempts": alive("img-b")}},
               {"batch": {"entry_id": 11}, "corpus_entry": {"name": "d__d", "command": "c"}, "result": {"verdict": "RUNS_AFTER_REPAIR", "attempts": alive("img-d")}}]
    paths = {r["corpus_entry"]["name"]: tmp_path / f"{r['batch']['entry_id']:02d}_{r['corpus_entry']['name']}.json" for r in records}
    calls = []

    def fake(record, **kw):
        calls.append((record["batch"]["entry_id"], kw["entries_left"]))
        return {"entry": record["batch"]["entry_id"], "name": record["corpus_entry"]["name"], "outcome": "completed", "ran": True, "cost_usd": 0.0, "cost_estimated_usd": 0.0, "label": "x"}

    gate.sustained_phase(records, paths, gate_cap_usd=7.0, spent_usd=3.5, odir=tmp_path, run=fake)
    assert calls == [(3, 2), (7, 2), (11, 1)]  # entry 3 needs nothing and takes no share: the two runs that spend split what is left in two
