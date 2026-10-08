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


def test_the_tracer_line_is_split_from_stderr_and_never_reaches_the_classifier():
    clean, reports = b.split_report('boom\nRERUN_BEHAVIOUR {"pid": 1, "lines": 3, "entry_main": true, "t0": 5}\nmore\n')
    assert clean == "boom\nmore\n" and reports[0]["lines"] == 3
    assert b.entry_report([{"t0": 9, "entry_main": False}, {"t0": 7, "entry_main": True}, {"t0": 1, "entry_main": True}]) == {"t0": 1, "entry_main": True}
    assert b.entry_report([]) is None


def test_trace_findings_read_a_report():
    plan = b.TracePlan("", "train.py", ({"file": "m.py", "lines": [7]},), {"m.py": [7, 8]}, [20, 25])
    ok = {"sites": {"m.py:7": 2}, "site_raised": {}, "exit": None, "main_lines": 4}
    assert b.trace_findings(ok, plan) == []
    assert b.trace_findings(None, plan) == []
    never = {"sites": {}, "site_raised": {}, "exit": {"how": "sys.exit", "file": "m.py", "line": 8, "code": "0"}, "main_lines": 0}
    assert {f.reason for f in b.trace_findings(never, plan)} == {b.FAILURE_SITE_NOT_EXECUTED, b.EXIT_FROM_ADDED_LINE, b.ENTRYPOINT_NOT_EXECUTED}
    raised = {"sites": {"m.py:7": 1}, "site_raised": {"m.py:7": 1}, "exit": None, "main_lines": 1, "argv_changed": ["x", "--help"]}
    assert {f.reason for f in b.trace_findings(raised, plan)} == {b.FAILURE_SITE_STILL_RAISES, b.ARGV_CHANGED_AT_RUNTIME}


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
    report = b.entry_report(b.split_report(done.stderr)[1])
    return report, plan, done


FAIL_AT_STEP = 'Traceback (most recent call last):\n  File "/w/train.py", line 5, in main\n    total = lib.work(3)\n  File "/w/lib.py", line 4, in work\n    acc += step(i)\nTypeError: boom\n'


def test_the_tracer_sees_an_honest_run_reach_the_failure_site(tmp_path):
    new = {**REPO, "lib.py": REPO["lib.py"].replace("return i * 2", "return int(i) * 2")}   # the site's callee changed; line 4 of lib.py still runs
    report, plan, done = _run(tmp_path, REPO, new, FAIL_AT_STEP)
    assert report is not None and report["entry_main"] is True, done.stderr
    assert b.trace_findings(report, plan) == []
    assert "total 6" in done.stdout


def test_the_tracer_catches_an_exit_from_an_added_line_and_a_site_that_never_ran(tmp_path):
    new = {**REPO, "train.py": REPO["train.py"].replace("        def", "def").replace("def main():\n    total", "def main():\n    sys.exit(0)\n    total")}
    report, plan, done = _run(tmp_path, REPO, new, FAIL_AT_STEP)
    assert done.returncode == 0
    assert report is not None and report["exit"]["how"] == "sys.exit", done.stderr
    reasons = {f.reason for f in b.trace_findings(report, plan)}
    assert b.EXIT_FROM_ADDED_LINE in reasons and b.FAILURE_SITE_NOT_EXECUTED in reasons


def test_the_tracer_catches_a_swallowed_failure_at_the_site(tmp_path):
    new = {**REPO, "lib.py": REPO["lib.py"].replace("        acc += step(i)", "        try:\n            acc += step(i) + None\n        except TypeError:\n            pass")}
    report, plan, done = _run(tmp_path, REPO, new, FAIL_AT_STEP.replace("line 4", "line 4"))
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
