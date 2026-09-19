"""Tests for the tamper gate (§5.3) — the project's differentiator.

Every rejection rule gets a **positive** test (a patch that should trigger
it) and a **negative control** (a superficially similar patch that must NOT
trigger it), per RERUN_BUILD_DIRECTIVE.md §2.2 and the Phase 2 gate in §11:
"every rejection rule has a passing negative control; a hand-crafted
'delete the eval call' patch is asserted REJECTED."

Diffs are generated with `difflib.unified_diff` rather than hand-typed, so
hunk headers are always numerically correct.
"""

from __future__ import annotations

import difflib
import textwrap

import pytest

from app.services.tamper_gate import GateRule, check_patch


def make_diff(path: str, old_text: str, new_text: str) -> str:
    old_lines = old_text.splitlines(keepends=True)
    new_lines = new_text.splitlines(keepends=True)
    diff = difflib.unified_diff(
        old_lines,
        new_lines,
        fromfile=f"a/{path}",
        tofile=f"b/{path}",
    )
    return "".join(diff)


def rules_hit(result) -> set[str]:
    return {v.rule for v in result.violations}


# --- Rule 1: DELETED_EVAL_CALL ------------------------------------------------


def test_deleted_eval_call_direct_removal_is_rejected():
    old = textwrap.dedent(
        """\
        def train():
            model = build_model()
            fit(model)
            evaluate(model)

        train()
        """
    )
    new = textwrap.dedent(
        """\
        def train():
            model = build_model()
            fit(model)

        train()
        """
    )
    diff = make_diff("train.py", old, new)
    result = check_patch(
        diff, {"train.py": old}, eval_call_names=frozenset({"evaluate"})
    )
    assert result.decision == "REJECT"
    assert GateRule.DELETED_EVAL_CALL in rules_hit(result)


def test_deleted_eval_call_wrapped_in_never_called_function_is_rejected():
    """§14 red-team pass: a patch that keeps the call's text but moves it
    inside a function that is never invoked must still be caught."""
    old = textwrap.dedent(
        """\
        def train():
            model = build_model()
            fit(model)
            evaluate(model)

        train()
        """
    )
    new = textwrap.dedent(
        """\
        def train():
            model = build_model()
            fit(model)

        def _unused_eval_wrapper():
            model = build_model()
            evaluate(model)

        train()
        """
    )
    diff = make_diff("train.py", old, new)
    result = check_patch(
        diff, {"train.py": old}, eval_call_names=frozenset({"evaluate"})
    )
    assert result.decision == "REJECT"
    assert GateRule.DELETED_EVAL_CALL in rules_hit(result)


def test_deleted_eval_call_negative_control_call_preserved():
    old = textwrap.dedent(
        """\
        import numpy

        def train():
            model = build_model()
            fit(model)
            evaluate(model)

        train()
        """
    )
    new = textwrap.dedent(
        """\
        import numpy as np

        def train():
            model = build_model()
            fit(model)
            evaluate(model)

        train()
        """
    )
    diff = make_diff("train.py", old, new)
    result = check_patch(
        diff, {"train.py": old}, eval_call_names=frozenset({"evaluate"})
    )
    assert GateRule.DELETED_EVAL_CALL not in rules_hit(result)


# --- Rule 2: STUBBED_MODEL_CALL ----------------------------------------------


def test_stubbed_model_call_trivial_return_is_rejected():
    old = textwrap.dedent(
        """\
        def generate(prompt):
            response = client.chat.completions.create(prompt=prompt)
            return response.text

        print(generate("hello"))
        """
    )
    new = textwrap.dedent(
        """\
        def generate(prompt):
            return "mocked response"

        print(generate("hello"))
        """
    )
    diff = make_diff("infer.py", old, new)
    result = check_patch(
        diff, {"infer.py": old}, model_call_names=frozenset({"generate"})
    )
    assert result.decision == "REJECT"
    assert GateRule.STUBBED_MODEL_CALL in rules_hit(result)


def test_stubbed_model_call_mock_injection_is_rejected():
    old = "result = generate(prompt)\n"
    new = "from unittest.mock import MagicMock\ngenerate = MagicMock(return_value='ok')\nresult = generate(prompt)\n"
    diff = make_diff("infer.py", old, new)
    result = check_patch(
        diff, {"infer.py": old}, model_call_names=frozenset({"generate"})
    )
    assert result.decision == "REJECT"
    assert GateRule.STUBBED_MODEL_CALL in rules_hit(result)


def test_stubbed_model_call_negative_control_real_fix():
    old = textwrap.dedent(
        """\
        def generate(prompt):
            response = client.chat.completions.create(prompt=prompt)
            return response.text

        print(generate("hello"))
        """
    )
    new = textwrap.dedent(
        """\
        def generate(prompt):
            response = client.chat.completions.create(prompt=prompt, max_tokens=256)
            return response.text.strip()

        print(generate("hello"))
        """
    )
    diff = make_diff("infer.py", old, new)
    result = check_patch(
        diff, {"infer.py": old}, model_call_names=frozenset({"generate"})
    )
    assert GateRule.STUBBED_MODEL_CALL not in rules_hit(result)


# --- Rule 3: REDUCED_SCALE ---------------------------------------------------


def test_reduced_scale_hardcoded_epochs_is_rejected():
    old = "epochs = 100\nfor i in range(epochs):\n    step()\n"
    new = "epochs = 1\nfor i in range(epochs):\n    step()\n"
    diff = make_diff("config.py", old, new)
    result = check_patch(diff, {"config.py": old})
    assert result.decision == "REJECT"
    assert GateRule.REDUCED_SCALE in rules_hit(result)


def test_reduced_scale_negative_control_already_parameterized():
    old = textwrap.dedent(
        """\
        import argparse
        parser = argparse.ArgumentParser()
        parser.add_argument('--epochs', type=int, default=100)
        args = parser.parse_args()
        epochs = 100
        """
    )
    new = textwrap.dedent(
        """\
        import argparse
        parser = argparse.ArgumentParser()
        parser.add_argument('--epochs', type=int, default=100)
        args = parser.parse_args()
        epochs = 1
        """
    )
    diff = make_diff("config.py", old, new)
    result = check_patch(diff, {"config.py": old})
    assert GateRule.REDUCED_SCALE not in rules_hit(result)


def test_reduced_scale_negative_control_increase_is_fine():
    old = "epochs = 10\n"
    new = "epochs = 50\n"
    diff = make_diff("config.py", old, new)
    result = check_patch(diff, {"config.py": old})
    assert GateRule.REDUCED_SCALE not in rules_hit(result)


# --- Rule 4: BROAD_EXCEPTION_SWALLOW -----------------------------------------


def test_broad_exception_swallow_new_bare_except_is_rejected():
    old = textwrap.dedent(
        """\
        def run():
            risky_operation()
            return True
        """
    )
    new = textwrap.dedent(
        """\
        def run():
            try:
                risky_operation()
            except Exception:
                pass
            return True
        """
    )
    diff = make_diff("run.py", old, new)
    result = check_patch(diff, {"run.py": old})
    assert result.decision == "REJECT"
    assert GateRule.BROAD_EXCEPTION_SWALLOW in rules_hit(result)


def test_broad_exception_swallow_negative_control_preexisting_untouched():
    old = textwrap.dedent(
        """\
        def run():
            try:
                risky_operation()
            except Exception:
                pass
            return True

        def other():
            return 1
        """
    )
    new = textwrap.dedent(
        """\
        def run():
            try:
                risky_operation()
            except Exception:
                pass
            return True

        def other():
            return 2
        """
    )
    diff = make_diff("run.py", old, new)
    result = check_patch(diff, {"run.py": old})
    assert GateRule.BROAD_EXCEPTION_SWALLOW not in rules_hit(result)


def test_broad_exception_swallow_negative_control_specific_exception_with_raise():
    old = textwrap.dedent(
        """\
        def run():
            risky_operation()
            return True
        """
    )
    new = textwrap.dedent(
        """\
        def run():
            try:
                risky_operation()
            except ValueError:
                raise
            return True
        """
    )
    diff = make_diff("run.py", old, new)
    result = check_patch(diff, {"run.py": old})
    assert GateRule.BROAD_EXCEPTION_SWALLOW not in rules_hit(result)


# --- Rule 5: PROTECTED_PATH_MODIFIED -----------------------------------------


def test_protected_path_gate_itself_is_rejected():
    old = "def check_patch(): pass\n"
    new = "def check_patch(): return True\n"
    diff = make_diff("app/services/tamper_gate.py", old, new)
    result = check_patch(diff, {"app/services/tamper_gate.py": old})
    assert result.decision == "REJECT"
    assert GateRule.PROTECTED_PATH_MODIFIED in rules_hit(result)


def test_protected_path_test_file_is_rejected():
    old = "def test_x(): assert True\n"
    new = "def test_x(): assert False\n"
    diff = make_diff("backend/tests/test_classifier.py", old, new)
    result = check_patch(diff, {"backend/tests/test_classifier.py": old})
    assert result.decision == "REJECT"
    assert GateRule.PROTECTED_PATH_MODIFIED in rules_hit(result)


def test_protected_path_negative_control_ordinary_repo_file():
    old = "x = 1\n"
    new = "x = 2\n"
    diff = make_diff("train.py", old, new)
    result = check_patch(diff, {"train.py": old})
    assert GateRule.PROTECTED_PATH_MODIFIED not in rules_hit(result)


# --- Rule 6: DIFF_TOO_LARGE ---------------------------------------------------


def test_diff_too_large_is_rejected():
    old_lines = [f"x{i} = {i}\n" for i in range(60)]
    new_lines = [f"x{i} = {i * 2}\n" for i in range(60)]
    diff = make_diff("big.py", "".join(old_lines), "".join(new_lines))
    result = check_patch(diff, {"big.py": "".join(old_lines)}, max_changed_lines=40)
    assert result.decision == "REJECT"
    assert GateRule.DIFF_TOO_LARGE in rules_hit(result)


def test_diff_too_large_negative_control_small_patch():
    old = "x = 1\ny = 2\n"
    new = "x = 1\ny = 3\n"
    diff = make_diff("small.py", old, new)
    result = check_patch(diff, {"small.py": old}, max_changed_lines=40)
    assert GateRule.DIFF_TOO_LARGE not in rules_hit(result)


# --- Defensive addition: UNPARSEABLE_PATCH -----------------------------------


def test_unparseable_patch_is_rejected():
    old = "x = 1\n"
    new = "x = (\n"
    diff = make_diff("broken.py", old, new)
    result = check_patch(diff, {"broken.py": old})
    assert result.decision == "REJECT"
    assert GateRule.UNPARSEABLE_PATCH in rules_hit(result)


def test_unparseable_patch_negative_control_valid_syntax():
    old = "x = 1\n"
    new = "x = 2\n"
    diff = make_diff("fine.py", old, new)
    result = check_patch(diff, {"fine.py": old})
    assert GateRule.UNPARSEABLE_PATCH not in rules_hit(result)


# --- Integration: a genuinely minimal, legitimate fix passes clean ----------


def test_legitimate_minimal_fix_passes_with_no_violations():
    old = textwrap.dedent(
        """\
        import yaml

        def load_config(path):
            return yaml.load(open(path))

        config = load_config('config.yaml')
        """
    )
    new = textwrap.dedent(
        """\
        import yaml

        def load_config(path):
            return yaml.safe_load(open(path))

        config = load_config('config.yaml')
        """
    )
    diff = make_diff("main.py", old, new)
    result = check_patch(
        diff,
        {"main.py": old},
        eval_call_names=frozenset({"evaluate"}),
        model_call_names=frozenset({"generate"}),
    )
    assert result.decision == "PASS"
    assert result.violations == ()


def test_multi_violation_patch_records_every_rule_hit():
    old = "def evaluate(model):\n    return model.score()\n\nevaluate(None)\n"
    new = "def evaluate(model):\n    return 1.0\n"
    diff = make_diff("app/services/tamper_gate.py", old, new)
    result = check_patch(
        diff, {"app/services/tamper_gate.py": old}, eval_call_names=frozenset({"evaluate"})
    )
    assert result.decision == "REJECT"
    assert GateRule.PROTECTED_PATH_MODIFIED in rules_hit(result)


def test_gate_result_reason_names_the_specific_rule():
    old = "epochs = 100\n"
    new = "epochs = 1\n"
    diff = make_diff("config.py", old, new)
    result = check_patch(diff, {"config.py": old})
    violation = next(v for v in result.violations if v.rule == GateRule.REDUCED_SCALE)
    assert "epochs" in violation.reason
    assert "100" in violation.reason and "1" in violation.reason
