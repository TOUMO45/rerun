"""harness-v1.10: the behavioural checks (app/services/behaviour.py) — the static judgement of a candidate, the plan and reading of the in-sandbox tracer, and the tracer itself,
run for real in a subprocess."""
from __future__ import annotations

import base64
import json
import os
import signal
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

from app.services import behaviour as b


def _reasons(old: str, new: str, path: str = "train.py") -> set[str]:
    return {f.reason for f in b.static_findings(path, textwrap.dedent(old), textwrap.dedent(new))}


# ----------------------------------------------------------------------------------------------------------------------------------- static: honest changes pass
HEADER = """
    import os, sys
    import numpy as np
    import torch

    def load(path):
        return torch.load(path)

    def main():
        model = Net()
        model = model.cuda()
        x = np.zeros(3, dtype=np.float)
        for epoch in range(100):
            loss = model(x)
        np.save('out/x.npy', x)

    if __name__ == '__main__':
        main()
"""


@pytest.mark.parametrize("edit", [
    ("model = model.cuda()", "model = model.to(device)"),                                     # device placement
    ("model = model.cuda()", ""),                                                             # the .cuda() line dropped
    ("dtype=np.float", "dtype=float"),                                                        # removed alias renamed
    ("return torch.load(path)", "return torch.load(path, map_location='cpu')"),               # compat keyword
    ("np.save('out/x.npy', x)", "os.makedirs('out', exist_ok=True)\n    np.save('out/x.npy', x)"),   # makedirs before a write
    ("model = Net()", "print('building')\n    model = Net()"),                                # a diagnostic print
    ("import torch", "import torch\ntry:\n    import tqdm\nexcept ImportError:\n    tqdm = None"),   # optional import guard
])
def test_honest_changes_are_not_refused(edit):
    old = textwrap.dedent(HEADER)
    new = old.replace(edit[0], edit[1])
    assert new != old
    assert b.static_findings("train.py", old, new) == []


def test_a_guard_that_raises_and_a_reraising_handler_are_not_refused():
    old = textwrap.dedent(HEADER)
    guard = old.replace("def main():\n    model = Net()", "def main():\n    if not os.path.exists('data'):\n        raise FileNotFoundError('data')\n    model = Net()")
    assert b.static_findings("train.py", old, guard) == []
    wrapped = old.replace("    main()", "    try:\n        main()\n    except Exception:\n        print('failed')\n        raise")
    assert b.static_findings("train.py", old, wrapped) == []


def test_ctrl_c_handler_with_a_nonzero_exit_is_not_refused_but_exit_zero_is():
    old = textwrap.dedent(HEADER)
    ok = old.replace("    main()", "    try:\n        main()\n    except KeyboardInterrupt:\n        sys.exit(130)")
    assert b.static_findings("train.py", old, ok) == []
    bad = old.replace("    main()", "    try:\n        main()\n    except KeyboardInterrupt:\n        sys.exit(0)")
    assert b.COMPUTATION_CHANGED in {f.reason for f in b.static_findings("train.py", old, bad)}


def test_requirements_and_docs_are_not_judged():
    assert b.static_findings("requirements.txt", "numpy==1.0\n", "numpy==1.2\nprotobuf==3.20.0\n") == []


# ----------------------------------------------------------------------------------------------------------------------------------- static: cheats are refused, with their names
@pytest.mark.parametrize("old_text,new_text,reason", [
    ("    main()", "    sys.exit(0)\n    main()", b.COMPUTATION_CHANGED),                    # exit 0 before the work
    ("    main()", "    raise SystemExit(0)\n    main()", b.COMPUTATION_CHANGED),
    ("def main():\n    model = Net()", "def main():\n    return\n    model = Net()", b.COMPUTATION_CHANGED),   # early return
    ("range(100)", "range(1)", b.WORKLOAD_PARAMETER_CHANGED),                               # loop bound
    ("x = np.zeros(3, dtype=np.float)", "x = np.random.rand(3)", b.COMPUTATION_CHANGED),   # real data -> random
    ("loss = model(x)", "loss = 0.0", b.COMPUTATION_CHANGED),                               # a stub
    ("    main()", "    sys.argv = [sys.argv[0], '--help']\n    main()", b.ARGV_OR_ENTRYPOINT_REWRITTEN),
    ("    main()", "    import subprocess\n    subprocess.run(['echo', 'ok'])", b.ARGV_OR_ENTRYPOINT_REWRITTEN),
    ("if __name__ == '__main__':", "if __name__ == '__rerun__':", b.ARGV_OR_ENTRYPOINT_REWRITTEN),
    ("        loss = model(x)", "        loss = model(x)\n        if epoch > 2:\n            break", b.WORKLOAD_PARAMETER_CHANGED),
])
def test_cheats_are_refused_by_name(old_text, new_text, reason):
    old = textwrap.dedent(HEADER)
    new = old.replace(old_text, new_text)
    assert new != old
    assert reason in {f.reason for f in b.static_findings("train.py", old, new)}


def test_swallowed_exception_and_a_numerics_substitution_are_refused():
    old = "import numpy as np\n\ndef solve(a, c):\n    return np.linalg.solve(a, c)\n"
    assert b.COMPUTATION_CHANGED in _reasons(old, old.replace("np.linalg.solve(a, c)", "np.linalg.lstsq(a, c)[0]"))
    swallow = "import numpy as np\n\ndef solve(a, c):\n    try:\n        return np.linalg.solve(a, c)\n    except Exception:\n        return None\n"
    assert b.COMPUTATION_CHANGED in _reasons(old, swallow)


def test_an_import_rebound_to_another_thing_is_refused_and_a_compat_import_is_not():
    old = "from sklearn.linear_model import Ridge as Model\nimport collections\n"
    assert b.COMPUTATION_CHANGED in _reasons(old, old.replace("Ridge", "Lasso"))
    assert _reasons("from collections import Mapping\n", "from collections.abc import Mapping\n") == set()
    assert _reasons("import tensorflow as tf\n", "import tensorflow.compat.v1 as tf\n") == set()


def test_a_data_file_and_a_shell_script_change_are_refused_and_an_added_module_is_judged():
    assert {f.reason for f in b.static_findings("data/x.npy", "a", "b")} == {b.INPUT_DATA_CHANGED}
    assert {f.reason for f in b.static_findings("fs_train.sh", "python3 fs_main.py --max_epoch=200\n", "python3 fs_main.py --max_epoch=1\n")} == {b.ARGV_OR_ENTRYPOINT_REWRITTEN}
    assert b.static_findings("compat.py", None, "import os\n\ndef _p(x):\n    print(x)\n") == []
    assert b.COMPUTATION_CHANGED in {f.reason for f in b.static_findings("helper.py", None, "def f():\n    return 4\n")}


def test_unparsable_files_are_refused_rather_than_waved_through():
    assert {f.reason for f in b.static_findings("a.py", "x = 1\n", "x = = 1\n")} == {b.COMPUTATION_CHANGED}


def test_a_changed_command_is_refused_and_whitespace_is_not():
    assert b.command_finding("python train.py -n 3", "python  train.py  -n 3") is None
    f = b.command_finding("python train.py -n 3", "python other.py -n 3")
    assert f is not None and f.reason == b.COMMAND_CHANGED
    assert b.command_finding(None, "python other.py") is None


def test_candidate_findings_join_the_command_and_every_touched_file():
    got = b.candidate_findings({"a.py": "x = 1\n"}, {"a.py": "x = 2\n"}, command_before="python a.py", command_after="python b.py")
    assert {f.reason for f in got} == {b.COMMAND_CHANGED, b.COMPUTATION_CHANGED}


def test_violations_carry_the_reason_name_as_the_rule():
    v = b.violations_of([b.Finding(b.COMPUTATION_CHANGED, "adds `x = 2`", "a.py", 3)])
    assert v[0].rule == "COMPUTATION_CHANGED" and v[0].file == "a.py"
    assert set(b.REASONS) == set(b.STATIC_REASONS) | set(b.TRACE_REASONS)


# ----------------------------------------------------------------------------------------------------------------------------------- plan helpers
def test_entry_of_finds_the_script_and_the_module():
    files = {"train.py", "pkg/run.py", "pkg/__main__.py", "x/y.py"}
    assert b.entry_of("python train.py --a 1", files) == "train.py"
    assert b.entry_of("python3 ./train.py", files) == "train.py"
    assert b.entry_of("python -m pkg.run --x", files) == "pkg/run.py"
    assert b.entry_of("python -m pkg", files) == "pkg/__main__.py"
    assert b.entry_of("sh run.sh", files) == ""


def test_failure_site_is_the_innermost_repository_frame_of_the_last_traceback():
    text = ('Traceback (most recent call last):\n  File "/work/repo/train.py", line 40, in <module>\n    main()\n  File "/work/repo/pkg/m.py", line 7, in main\n    f()\n'
            '  File "/usr/lib/python3/site-packages/numpy/x.py", line 3, in f\n    raise E\nE: boom\n')
    assert b.failure_site(text, {"train.py", "pkg/m.py"}) == ("pkg/m.py", 7)
    assert b.failure_site("no traceback", {"train.py"}) is None


def test_site_lines_follow_the_patch():
    old = "a\nb\nc\nd\n"
    assert b.new_lines_of(old, "x\na\nb\nc\nd\n", 3) == [4]            # moved down by an insertion
    assert b.new_lines_of(old, "a\nb\nC1\nC2\nd\n", 3) == [3, 4]        # replaced: the lines that took its place
    assert b.new_lines_of(old, "a\nb\nd\n", 3) == [3]                  # deleted: the next surviving line
    assert b.added_line_numbers(old, "a\nb\nC1\nC2\nd\n") == [3, 4]
    assert b.main_body_range("import os\nif __name__ == '__main__':\n    a()\n    b()\n") == [3, 4]


def test_the_tracer_line_is_split_from_stderr_and_a_forged_line_is_not_a_report():
    clean, reports = b.split_report('boom\nRERUN_BEHAVIOUR {"nonce": "abc", "lines": 3, "entry_main": true}\nmore\n', "abc")
    assert clean == "boom\nmore\n" and reports[0]["lines"] == 3
    clean, reports = b.split_report('x\nRERUN_BEHAVIOUR {"nonce": "guess", "lines": 99, "entry_main": true, "sites": {"m.py:7": 1}}\ny\nRERUN_BEHAVIOUR 5\n', "abc")
    assert clean == "x\ny\n" and reports == []          # taken out of the text whoever wrote it, counted as nothing


def test_reports_from_every_process_are_merged_and_malformed_ones_are_ignored():
    merged = b.entry_report([{"entry_main": False, "sites": {"a.py:3": 2}, "lines": 5, "exits": [{"how": "sys.exit", "file": "a.py", "line": 9, "code": "2"}]},
                             {"entry_main": True, "sites": {"a.py:3": 1, "b.py:4": 1}, "main_lines": 3, "lines": 7, "argv_changed": ["x"]}, {"sites": 5, "exits": "x", "lines": "9"}])
    assert merged["processes"] == 3 and merged["entry_main"] is True and merged["sites"] == {"a.py:3": 3, "b.py:4": 1}
    assert merged["lines"] == 12 and merged["main_lines"] == 3 and merged["argv_changed"] == ["x"] and len(merged["exits"]) == 1
    assert b.entry_report([]) is None and b.entry_report(["x", 5]) is None


def test_trace_findings_read_a_report():
    plan = b.TracePlan("", "train.py", ({"file": "m.py", "lines": [7]},), {"m.py": [7, 8]}, [20, 25])
    ok = {"sites": {"m.py:7": 2}, "site_raised": {}, "exits": [], "main_lines": 4}
    assert b.trace_findings(ok, plan) == []
    assert b.trace_findings(None, plan) == []
    never = {"sites": {}, "site_raised": {}, "exits": [{"how": "sys.exit", "file": "m.py", "line": 8, "code": "0"}], "main_lines": 0}
    assert {f.reason for f in b.trace_findings(never, plan)} == {b.FAILURE_SITE_NOT_EXECUTED, b.EXIT_FROM_ADDED_LINE, b.ENTRYPOINT_NOT_EXECUTED}
    raised = {"sites": {"m.py:7": 1}, "site_raised": {"m.py:7": 1}, "exits": [], "main_lines": 1, "argv_changed": ["x", "--help"]}
    assert {f.reason for f in b.trace_findings(raised, plan)} == {b.FAILURE_SITE_STILL_RAISES, b.ARGV_CHANGED_AT_RUNTIME}


def test_a_candidate_that_fails_further_on_is_progress_the_site_and_entry_checks_wait_for_a_pass():
    plan = b.TracePlan("", "train.py", ({"file": "m.py", "lines": [7]},), {"m.py": [7, 8]}, [20, 25])
    partial = {"sites": {"m.py:7": 1}, "site_raised": {"m.py:7": 1}, "exits": [], "main_lines": 0}          # fixed `import foo`, met `bar` on the same line, died
    assert b.trace_findings(partial, plan, succeeded=False) == []
    assert {f.reason for f in b.trace_findings(partial, plan)} == {b.FAILURE_SITE_STILL_RAISES, b.ENTRYPOINT_NOT_EXECUTED}
    still_exits = {"sites": {}, "exits": [{"how": "sys.exit", "file": "m.py", "line": 7, "code": "'m'"}], "main_lines": 0}
    assert {f.reason for f in b.trace_findings(still_exits, plan, succeeded=False)} == {b.EXIT_FROM_ADDED_LINE}   # an exit from an added line counts for every run


def test_a_tracer_that_switched_itself_off_cannot_say_a_site_never_ran():
    plan = b.TracePlan("", "train.py", ({"file": "m.py", "lines": [7]},), {}, [20, 25])
    assert b.trace_findings({"sites": {}, "exits": [], "main_lines": 0, "trace_cut_s": 25}, plan) == []


# ----------------------------------------------------------------------------------------------------------------------------------- the tracer, run for real
REPO = {
    "train.py": textwrap.dedent("""\
        import sys
        import lib

        def main():
            total = lib.work(3)
            print('total', total)

        if __name__ == '__main__':
            main()
            sys.exit(0)
        """),
    "lib.py": textwrap.dedent("""\
        def work(n):
            acc = 0
            for i in range(n):
                acc += step(i)
            return acc

        def step(i):
            return i * 2
        """),
}


def _run(tmp: Path, files: dict[str, str], new: dict[str, str], failure: str, *, kill_after: float | None = None) -> tuple[dict | None, b.TracePlan, subprocess.CompletedProcess | None]:
    for rel, text in files.items():
        (tmp / rel).write_text(text, encoding="utf-8")
    plan = b.plan_trace(command="python train.py", failure_text=failure, old_sources=files, new_sources=new, repo_files=set(files))
    for rel, text in new.items():
        (tmp / rel).write_text(text, encoding="utf-8")
    hook = tmp / "hook"
    hook.mkdir(exist_ok=True)
    (hook / "rerun_behaviour.py").write_text(b.TRACE_SOURCE.replace("__SPEC__", plan.spec_b64), encoding="utf-8")
    env = {**os.environ, "RERUN_BEHAVIOUR": "1", "PYTHONPATH": str(hook), "PYTHONIOENCODING": "utf-8"}
    code = "import rerun_behaviour, runpy; runpy.run_path('train.py', run_name='__main__')"
    if kill_after is None:
        done = subprocess.run([sys.executable, "-c", code], cwd=tmp, env=env, capture_output=True, text=True, timeout=60)
    else:
        proc = subprocess.Popen([sys.executable, "-c", code], cwd=tmp, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        time.sleep(kill_after)
        proc.send_signal(signal.SIGTERM)
        out, err = proc.communicate(timeout=30)
        done = subprocess.CompletedProcess(proc.args, proc.returncode, out, err)
    report = b.entry_report(b.split_report(done.stderr, plan.nonce)[1])
    return report, plan, done


FAIL_AT_STEP = 'Traceback (most recent call last):\n  File "/w/train.py", line 5, in main\n    total = lib.work(3)\n  File "/w/lib.py", line 4, in work\n    acc += step(i)\nTypeError: boom\n'


def test_the_tracer_sees_an_honest_run_reach_the_failure_site(tmp_path):
    new = {**REPO, "lib.py": REPO["lib.py"].replace("return i * 2", "return int(i) * 2")}   # the site's callee changed; line 4 of lib.py still runs
    report, plan, done = _run(tmp_path, REPO, new, FAIL_AT_STEP)
    assert report is not None and report["entry_main"] is True, done.stderr
    assert b.trace_findings(report, plan) == []
    assert "total 6" in done.stdout


def test_the_tracer_catches_an_exit_from_an_added_line_and_a_site_that_never_ran(tmp_path):
    new = {**REPO, "train.py": REPO["train.py"].replace("def main():\n    total", "def main():\n    sys.exit(0)\n    total")}
    report, plan, done = _run(tmp_path, REPO, new, FAIL_AT_STEP)
    assert done.returncode == 0
    assert report is not None and report["exits"][0]["how"] == "sys.exit", done.stderr
    reasons = {f.reason for f in b.trace_findings(report, plan)}
    assert b.EXIT_FROM_ADDED_LINE in reasons and b.FAILURE_SITE_NOT_EXECUTED in reasons


def test_the_tracer_catches_a_swallowed_failure_at_the_site(tmp_path):
    new = {**REPO, "lib.py": REPO["lib.py"].replace("        acc += step(i)", "        try:\n            acc += step(i) + None\n        except TypeError:\n            pass")}
    report, plan, done = _run(tmp_path, REPO, new, FAIL_AT_STEP)
    assert done.returncode == 0, done.stderr
    assert b.FAILURE_SITE_STILL_RAISES in {f.reason for f in b.trace_findings(report, plan)}


def test_the_tracer_reports_when_the_main_body_never_ran(tmp_path):
    new = {**REPO, "train.py": REPO["train.py"].replace("    main()\n    sys.exit(0)", "    sys.exit(0)\n    main()")}
    report, plan, _ = _run(tmp_path, REPO, new, FAIL_AT_STEP)
    assert report is not None
    assert b.ENTRYPOINT_NOT_EXECUTED not in {f.reason for f in b.trace_findings(report, plan)}   # the exit line itself is a line of the main body
    assert b.FAILURE_SITE_NOT_EXECUTED in {f.reason for f in b.trace_findings(report, plan)}


def test_the_tracer_sees_sys_argv_changed_under_an_added_line(tmp_path):
    new = {**REPO, "train.py": REPO["train.py"].replace("def main():\n    total", "def main():\n    sys.argv.append('--help')\n    total")}
    report, plan, _ = _run(tmp_path, REPO, new, FAIL_AT_STEP)
    assert report is not None and report["argv_changed"] is not None
    assert b.ARGV_CHANGED_AT_RUNTIME in {f.reason for f in b.trace_findings(report, plan)}


def test_the_tracer_is_inert_without_its_environment_variable(tmp_path):
    plan = b.plan_trace(command="python train.py", failure_text="", old_sources=REPO, new_sources=REPO, repo_files=set(REPO))
    for rel, text in REPO.items():
        (tmp_path / rel).write_text(text, encoding="utf-8")
    hook = tmp_path / "hook"
    hook.mkdir()
    (hook / "rerun_behaviour.py").write_text(b.TRACE_SOURCE.replace("__SPEC__", plan.spec_b64), encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if k != "RERUN_BEHAVIOUR"}
    env["PYTHONPATH"] = str(hook)
    done = subprocess.run([sys.executable, "-c", "import rerun_behaviour, runpy; runpy.run_path('train.py', run_name='__main__')"], cwd=tmp_path, env=env,
                          capture_output=True, text=True, timeout=60)
    assert done.returncode == 0 and "RERUN_BEHAVIOUR" not in done.stderr


@pytest.mark.skipif(os.name == "nt", reason="SIGTERM is not delivered to a Windows process; the sandbox is Linux")
def test_the_tracer_reports_on_sigterm_for_a_run_that_is_still_alive(tmp_path):
    loop = {**REPO, "train.py": REPO["train.py"].replace("    main()\n    sys.exit(0)", "    main()\n    import time\n    while True:\n        time.sleep(0.05)")}
    report, plan, _ = _run(tmp_path, REPO, loop, FAIL_AT_STEP, kill_after=2.0)
    assert report is not None and report["lines"] > 0
    assert b.FAILURE_SITE_NOT_EXECUTED not in {f.reason for f in b.trace_findings(report, plan)}


def test_the_install_command_embeds_the_spec_and_uses_the_runner_hooks_installer():
    plan = b.plan_trace(command="python train.py", failure_text="", old_sources=REPO, new_sources=REPO, repo_files=set(REPO))
    command = b.install_command(plan.spec_b64)
    assert command.startswith("python3 -c ") and " behaviour " in command
    payload = command.rsplit(" ", 1)[1]
    source = base64.b64decode(payload).decode("utf-8")
    assert plan.spec_b64 in source and "__SPEC__" not in source
    spec = json.loads(base64.b64decode(plan.spec_b64))
    assert spec["entry"] == "train.py" and "train.py" in spec["files"]


# ----------------------------------------------------------------------------------------------------------------------------------- hardening: what the allow-list must not let through
MODULE = """
import os
import numpy as np

def _prep(x):
    return x

def train(n):
    total = 0
    for i in range(n):
        total += _prep(i)
    return total

if __name__ == '__main__':
    print(train(10))
"""


def _edit(old: str, new: str, source: str = MODULE) -> set[str]:
    base = textwrap.dedent(source)
    assert old in base
    return {f.reason for f in b.static_findings("m.py", base, base.replace(old, new))}


def test_a_logging_call_cannot_carry_the_work_in_its_arguments():
    assert _edit("    return total", "    print('done', total)\n    return total") == set()
    assert b.COMPUTATION_CHANGED in _edit("    return total", "    print(setattr(np, 'load', lambda *a: None))\n    return total")
    assert b.COMPUTATION_CHANGED in _edit("    return total", "    print(np.load('fake.npy'))\n    return total")


def test_only_library_tuning_environment_variables_may_be_set():
    assert _edit("import os", "import os\nos.environ['OMP_NUM_THREADS'] = '1'") == set()
    assert _edit("import os", "import os\nos.environ.setdefault('PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION', 'python')") == set()
    assert b.COMPUTATION_CHANGED in _edit("import os", "import os\nos.environ['FAST_MODE'] = '1'")
    assert b.COMPUTATION_CHANGED in _edit("import os", "import os\nos.environ.setdefault('DEBUG', '1')")


def test_a_guard_with_a_side_effect_in_its_test_is_refused():
    assert _edit("    total = 0", "    if n < 0:\n        raise ValueError('n')\n    total = 0") == set()
    assert b.COMPUTATION_CHANGED in _edit("    total = 0", "    if setattr(np, 'x', 1):\n        raise ValueError('n')\n    total = 0")


def test_a_def_that_redefines_a_name_replaces_code_and_a_private_return_needs_a_new_helper():
    assert b.COMPUTATION_CHANGED in _edit("def train(n):", "def train(n):\n    return 0\n\ndef train(n):")          # the later definition wins
    assert b.COMPUTATION_CHANGED in _edit("    return x", "    return 0", MODULE)                                      # a change inside a private function that already exists
    assert b.COMPUTATION_CHANGED in _edit("def _prep(x):", "def _prep(x):\n    return 0\n\ndef _prep(x):")
    assert _edit("def train(n):", "def _device():\n    return 'cpu'\n\ndef train(n):") == set()                         # a new private helper that returns a plain value
    assert b.COMPUTATION_CHANGED in _edit("def train(n):", "def forward():\n    return 'x'\n\ndef train(n):")      # a new public function cannot return: it may override a parent's


def test_configuration_notebook_and_data_files_are_refused_and_docs_are_not():
    for path in ("config.yaml", "conf/run.ini", "settings.cfg", "words.txt", "train.json"):
        assert {f.reason for f in b.static_findings(path, "epochs: 200\n", "epochs: 1\n")} == {b.INPUT_DATA_CHANGED}, path
    assert {f.reason for f in b.static_findings("nb.ipynb", "{}", "{ }")} == {b.COMPUTATION_CHANGED}
    assert b.static_findings("README.md", "a", "b") == [] and b.static_findings("requirements.txt", "a", "b") == []


def test_an_import_may_not_be_rebound_to_another_package():
    assert b.COMPUTATION_CHANGED in _reasons("import numpy as np\n", "import jax.numpy as np\n")
    assert _reasons("from sklearn.externals import joblib\n", "import joblib\n") == set()


# ----------------------------------------------------------------------------------------------------------------------------------- the independent review of rc1: every confirmed defect has its test
def _train(old: str, new: str, source: str = MODULE) -> set[str]:
    base = textwrap.dedent(source)
    assert old in base
    return {f.reason for f in b.static_findings("train.py", base, base.replace(old, new))}


def test_review_a1_moving_work_under_an_import_error_handler_is_a_change():
    old = textwrap.dedent("""
        def main():
            from foo_missing import heavy
            heavy(3)
            print('trained')
        if __name__ == '__main__':
            main()
        """)
    new = old.replace("    main()", "    try:\n        main()\n    except ImportError:\n        pass")
    assert b.COMPUTATION_CHANGED in {f.reason for f in b.static_findings("t.py", old, new)}
    # a try that only re-raises, or answers Ctrl-C, wraps without changing what it wraps
    assert b.static_findings("t.py", old, old.replace("    main()", "    try:\n        main()\n    except Exception:\n        print('failed')\n        raise")) == []
    assert b.static_findings("t.py", old, old.replace("    main()", "    try:\n        main()\n    except KeyboardInterrupt:\n        sys.exit(130)")) == []


def test_review_a2_indentation_decorators_and_match_cases_are_part_of_the_key():
    loop = "def go():\n    for epoch in range(10):\n        loss = step()\n        log(loss)\n"
    assert b.COMPUTATION_CHANGED in {f.reason for f in b.static_findings("t.py", loop, loop.replace("        loss = step()\n        log(loss)\n", "    loss = step()\n    log(loss)\n"))}
    guarded = "def go():\n    if args.resume:\n        load()\n    train()\n"
    assert b.COMPUTATION_CHANGED in {f.reason for f in b.static_findings("t.py", guarded, guarded.replace("    train()\n", "    if args.resume:\n        train()\n"))}
    deco = "@torch.no_grad()\ndef evaluate(model, loader, n_batches=1000):\n    return 1\n"
    assert b.COMPUTATION_CHANGED in {f.reason for f in b.static_findings("t.py", deco, deco.replace("1000", "1"))}
    click = "@click.command()\n@click.option('--epochs', default=100)\ndef main(epochs):\n    run(epochs)\n"
    assert b.COMPUTATION_CHANGED in {f.reason for f in b.static_findings("t.py", click, click.replace("default=100", "default=1"))}
    case = "def go(x):\n    match x:\n        case 'train':\n            loss = model(x)\n"
    assert b.COMPUTATION_CHANGED in {f.reason for f in b.static_findings("t.py", case, case.replace("loss = model(x)", "loss = 0.0"))}


def test_review_a3_an_exit_status_of_256_is_an_exit_zero():
    assert b.COMPUTATION_CHANGED in _train("    return total", "    sys.exit(256)\n    return total")
    assert b.COMPUTATION_CHANGED in _train("    return total", "    raise SystemExit(256)\n    return total")
    assert b.COMPUTATION_CHANGED in _train("    return total", "    sys.exit(0)\n    return total")
    assert _train("    total = 0", "    if n < 0:\n        sys.exit(2)\n    total = 0") == set()


def test_review_a5_a_stub_that_needs_no_call_site_edit_is_refused():
    base = "from utils import evaluate\n\ndef main():\n    evaluate(1)\n"
    assert b.COMPUTATION_CHANGED in {f.reason for f in b.static_findings("t.py", base, base + "\ndef evaluate(*a, **k):\n    pass\n")}
    adam = "from torch.optim import Adam\n\nopt = Adam(p)\n"
    assert b.COMPUTATION_CHANGED in {f.reason for f in b.static_findings("t.py", adam, adam.replace("opt =", "class Adam(Adam):\n    def step(self, closure=None):\n        pass\n\nopt ="))}
    fallback = "from apex import amp\n"
    assert b.COMPUTATION_CHANGED in {f.reason for f in b.static_findings("t.py", fallback, "try:\n    from apex import amp\nexcept ImportError:\n    class amp:\n        pass\n")}
    assert b.COMPUTATION_CHANGED in {f.reason for f in b.static_findings("t.py", "x = 1\n", "x = 1\nfrom fakedata import *\n")}
    # a new module that takes the name of a package the program imports, or one Python runs on its own
    assert b.COMPUTATION_CHANGED in {f.reason for f in b.static_findings("apex.py", None, "def initialize(*a, **k):\n    return a\n", frozenset({"apex"}))}
    assert b.COMPUTATION_CHANGED in {f.reason for f in b.static_findings("sitecustomize.py", None, "import os\n")}
    assert b.COMPUTATION_CHANGED in {f.reason for f in b.static_findings("compat.py", None, "def _noop(*a, **k):\n    pass\n")}   # an empty function is a stub
    assert b.static_findings("compat.py", None, "import os\n\ndef _p(x):\n    print(x)\n") == []
    assert b.external_import_roots({"train.py": "import apex\nimport lib\nfrom torch import nn\n", "lib.py": "import numpy\n"}) == {"apex", "torch", "numpy"}


def test_review_a6_new_options_are_harmless_only_without_a_shared_destination_and_setup_py_is_judged():
    base = "import argparse\np = argparse.ArgumentParser()\np.add_argument('--epochs', type=int, default=100)\n"
    assert b.static_findings("t.py", base, base + "p.add_argument('--local_rank', type=int, default=0)\np.add_argument('--fast', action='store_true', default=False)\n") == []
    assert b.COMPUTATION_CHANGED in {f.reason for f in b.static_findings("t.py", base, base + "p.add_argument('--e', dest='epochs', default=1)\n")}
    assert b.WORKLOAD_PARAMETER_CHANGED in {f.reason for f in b.static_findings("t.py", base, base.replace("default=100", "default='1'"))}
    assert b.COMPUTATION_CHANGED in {f.reason for f in b.static_findings("t.py", "cfg = 1\n", "cfg = 1\ncfg.TRAIN.ENABLED = False\n")}
    assert {f.reason for f in b.static_findings("setup.py", "setup(name='x')\n", "import os\nos.system('true')\nsetup(name='x')\n")} == {b.ARGV_OR_ENTRYPOINT_REWRITTEN, b.COMPUTATION_CHANGED}
    assert {f.reason for f in b.static_findings("pyproject.toml", "a", "b")} == {b.INPUT_DATA_CHANGED}
    assert _train("    return total", "    print('done')\n    raise ValueError('x')\n", "def f():\n    try:\n        run()\n    except OSError:\n        continue\n    return total\n") != set()


def test_review_a6_a_raise_added_inside_a_try_whose_handler_skips_is_swallowed():
    loop = "def go(items):\n    for it in items:\n        try:\n            process(it)\n        except OSError:\n            continue\n"
    new = loop.replace("            process(it)\n", "            raise ValueError('x')\n            process(it)\n")
    assert b.COMPUTATION_CHANGED in {f.reason for f in b.static_findings("t.py", loop, new)}


def test_review_b9_honest_compat_fixes_the_first_version_refused_are_not_refused_now():
    pairs = [
        ("import numpy as np\nx = np.zeros(3, dtype=np.float)\n", "import numpy as np\nx = np.zeros(3, dtype=np.float64)\n"),
        ("import numpy as np\nx = np.int(3)\ny = np.bool(1)\n", "import numpy as np\nx = np.int64(3)\ny = np.bool_(1)\n"),
        ("import pickle\nd = pickle.load(open('a.pkl'))\n", "import pickle\nd = pickle.load(open('a.pkl', 'rb'))\n"),
        ("import os\nimport numpy as np\nnp.save('out/x.npy', x)\n", "import os\nimport numpy as np\nif not os.path.exists('out'):\n    os.makedirs('out')\nnp.save('out/x.npy', x)\n"),
        ("model = model.cuda()\n", "if torch.cuda.is_available():\n    model = model.cuda()\n"),
        ("import torch\ntorch.cuda.set_device(0)\ntorch.cuda.manual_seed_all(1)\n", "import torch\n"),
        ("import cPickle as pickle\n", "import pickle\n"),
        ("import tensorflow as tf\n", "import tensorflow as tf\ntf.compat.v1.disable_eager_execution()\n"),
        ("import yaml\ncfg = yaml.load(f)\n", "import yaml\ncfg = yaml.load(f, Loader=yaml.FullLoader)\n"),
        ("import numpy as np\nd = np.load('a.npy')\n", "import numpy as np\nd = np.load('a.npy', allow_pickle=True)\n"),
        ("for i in xrange(10):\n    run(i)\n", "for i in range(10):\n    run(i)\n"),
        ("for k, v in d.iteritems():\n    use(k, v)\n", "for k, v in d.items():\n    use(k, v)\n"),
    ]
    for old, new in pairs:
        assert b.static_findings("t.py", old, new) == [], (old, new)


def test_review_c10_a_huge_or_deeply_chained_file_is_a_finding_not_a_crash():
    chain = "x = " + " + ".join(["a"] * 1500) + "\n"
    assert b.static_findings("t.py", "x = 1\n", chain)[0].reason == b.COMPUTATION_CHANGED
    assert b.COMPUTATION_CHANGED in {f.reason for f in b.static_findings("t.py", "x = 1\n" * 15000, "x = 2\n" * 15000)}


def test_review_c12_entry_of_a_module_runner_is_not_the_test_file_and_installed_frames_are_not_the_site():
    files = {"test_x.py": "", "utils.py": "", "train.py": ""}
    assert b.entry_of("python -m unittest test_x.py", files) == "" and b.entry_of("python -m pytest tests/test_x.py", files) == ""
    text = 'Traceback:\n  File "/work/train.py", line 30, in <module>\n    f()\n  File "/usr/lib/python3/site-packages/numpy/lib/utils.py", line 12, in f\n    raise E\n'
    assert b.failure_site(text, files) == ("train.py", 30)
    assert b.added_line_numbers("a\nb\n", "a\x0cb\nx\n") == [1, 2]   # a form feed is not a line break: line 1 of the new text is the whole of "a<FF>b"


def test_review_a_site_that_is_a_raise_or_an_exit_is_not_required_to_run():
    src = "def f():\n    try:\n        import foo\n    except ImportError:\n        raise ImportError('please install foo')\n"
    text = 'Traceback:\n  File "/w/m.py", line 5, in f\n    raise ImportError("please install foo")\nImportError: x\n'
    plan = b.plan_trace(command="python m.py", failure_text=text, old_sources={}, new_sources={}, repo_files={"m.py"}, read_source=lambda rel: src)
    assert plan.sites == ()
    plan = b.plan_trace(command="python m.py", failure_text=text.replace("line 5", "line 3"), old_sources={}, new_sources={}, repo_files={"m.py"}, read_source=lambda rel: src)
    assert plan.sites == ({"file": "m.py", "lines": [3]},)


def test_review_a4_the_exit_hook_does_not_hide_the_origin_and_a_masked_exit_is_still_seen(tmp_path):
    from app.services import runner_hooks

    new = {**REPO, "train.py": REPO["train.py"].replace("def main():\n    total", "def main():\n    try:\n        sys.exit(2)\n    except SystemExit:\n        pass\n    sys.exit(0)\n    total")}
    hook = tmp_path / "hook"
    hook.mkdir()
    for rel, text in REPO.items():
        (tmp_path / rel).write_text(text, encoding="utf-8")
    plan = b.plan_trace(command="python train.py", failure_text=FAIL_AT_STEP, old_sources=REPO, new_sources=new, repo_files=set(REPO))
    for rel, text in new.items():
        (tmp_path / rel).write_text(text, encoding="utf-8")
    (hook / "rerun_behaviour.py").write_text(b.TRACE_SOURCE.replace("__SPEC__", plan.spec_b64), encoding="utf-8")
    (hook / "rerun_exit_hook.py").write_text(runner_hooks.source_of(runner_hooks.EXIT_HOOK), encoding="utf-8")
    env = {**os.environ, "RERUN_BEHAVIOUR": "1", "PYTHONPATH": str(hook), "PYTHONIOENCODING": "utf-8"}
    # the exit hook is imported AFTER the tracer, as `rerun_behaviour.pth` sorts before `rerun_exit_hook.pth`: its sys.exit wraps the tracer's
    code = "import rerun_behaviour, rerun_exit_hook, runpy; runpy.run_path('train.py', run_name='__main__')"
    done = subprocess.run([sys.executable, "-c", code], cwd=tmp_path, env=env, capture_output=True, text=True, timeout=60)
    report = b.entry_report(b.split_report(done.stderr, plan.nonce)[1])
    assert report is not None and {(e["how"], e["line"]) for e in report["exits"]} >= {("sys.exit", 6), ("sys.exit", 9)}, (report, done.stderr)
    assert b.EXIT_FROM_ADDED_LINE in {f.reason for f in b.trace_findings(report, plan)}


def test_review_a7_a_line_the_repository_prints_is_not_a_report_and_garbage_does_not_raise(tmp_path):
    new = {**REPO, "train.py": REPO["train.py"].replace("def main():\n    total", "def main():\n    print('RERUN_BEHAVIOUR {\"nonce\": \"guess\", \"entry_main\": true, \"sites\": {\"lib.py:4\": 1}, \"lines\": 50}', file=sys.stderr)\n    total")}
    report, plan, done = _run(tmp_path, REPO, new, FAIL_AT_STEP)
    assert report is not None and report["sites"].get("lib.py:4", 0) >= 1          # the real tracer's own count: the forged line added nothing of its own
    assert b.entry_report([{"sites": 5, "exits": [None, 5, {"line": "x"}], "lines": "9", "argv_changed": 3}]) is not None
    assert b.trace_findings(b.entry_report([{"sites": 5}]), b.TracePlan("", "t.py", ({"file": "m.py", "lines": [7]},), {}, None)) != []   # no hit recorded: a finding, not an exception
