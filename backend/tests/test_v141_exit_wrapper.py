"""harness-v1.4.1-rc, directive item 6 (D-35): when the exit-site hook printed nothing, the entry script runs through a harness wrapper
(`runpy.run_path` inside a try/except SystemExit that prints the traceback and re-raises with the same code). A bare `raise
SystemExit(n)` is invisible to the hook (harness-v1.4.0, corpus-v2 #3: the hook fired, printed nothing, the model never saw an exit
site). If the wrapper prints nothing either, the record says "exit outside Python".

Real subprocesses run the wrapper and the plain script side by side; the fake cloud runs the orchestration."""

from __future__ import annotations

import base64
import json
import shlex
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

import v140_cloud
from app.services import classifier, runner_hooks, smoke_exec
from test_v140_pipeline import ENTRY_03_SILENT, EXEC, SKLEARN_MISSING, _Chat, _edit, _repo, _run
from test_v140_runner_hooks import _site

BARE_EXIT = """\
import sys


def main():
    print("working on the data")
    raise SystemExit(1)


main()
"""


def _argv(command: str) -> list[str]:
    """The wrapped command as an argv list, with this interpreter in place of `python` (the command is POSIX-quoted)."""
    wrapped, why = runner_hooks.wrap_entry_command(command)
    assert wrapped is not None, why
    argv = shlex.split(wrapped)
    assert argv[0] in ("python", "python3") or argv[0].startswith("python")
    return [sys.executable, *argv[1:]]


def _execute(argv: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=60)


# --- the wrapper, run for real -----------------------------------------------------------------------------------------

def test_a_bare_raise_systemexit_is_invisible_to_the_hook_but_the_wrapper_prints_the_raise_site(tmp_path):
    (tmp_path / "main.py").write_text(BARE_EXIT, encoding="utf-8")
    site = _site(tmp_path, runner_hooks.EXIT_HOOK)
    # the exit-site hook alone (the script run the way `python main.py` runs it, with the hook's .pth processed): nothing is printed
    boot = f"import site, runpy; site.addsitedir({str(site)!r}); runpy.run_path('main.py', run_name='__main__')"
    plain = _execute([sys.executable, "-c", boot], tmp_path)
    assert plain.returncode == 1 and plain.stderr == "" and "RERUN_EXIT_HOOK" not in plain.stderr
    assert not classifier.has_actionable_error(plain.stderr, plain.stdout)  # still a silent exit: what corpus-v2 #3 recorded
    # through the wrapper: the traceback of the raise, the same exit code
    proc = _execute(_argv("python main.py --epochs 3"), tmp_path)
    assert proc.returncode == 1 and proc.stdout == "working on the data\n"
    assert "RERUN_EXIT_WRAPPER: the entry script raised SystemExit(1)" in proc.stderr
    assert "Traceback (most recent call last):" in proc.stderr
    assert 'File "main.py", line 6, in main' in proc.stderr.replace(str(tmp_path / "main.py"), "main.py") or "line 6, in main" in proc.stderr
    assert "raise SystemExit(1)" in proc.stderr and proc.stderr.rstrip().endswith("SystemExit: 1")
    assert classifier.has_actionable_error(proc.stderr, proc.stdout)


def test_the_wrapper_keeps_the_exit_code_and_stays_silent_on_a_clean_exit(tmp_path):
    (tmp_path / "ok.py").write_text("import sys\nprint('done')\nsys.exit(0)\n", encoding="utf-8")
    (tmp_path / "off.py").write_text("raise SystemExit\n", encoding="utf-8")
    (tmp_path / "three.py").write_text("raise SystemExit(3)\n", encoding="utf-8")
    (tmp_path / "msg.py").write_text("raise SystemExit('the config is missing')\n", encoding="utf-8")
    ok = _execute(_argv("python ok.py"), tmp_path)
    assert ok.returncode == 0 and ok.stdout == "done\n" and ok.stderr == ""
    assert _execute(_argv("python off.py"), tmp_path).returncode == 0 and _execute(_argv("python off.py"), tmp_path).stderr == ""
    three = _execute(_argv("python three.py"), tmp_path)
    assert three.returncode == 3 and "SystemExit(3)" in three.stderr
    msg = _execute(_argv("python msg.py"), tmp_path)
    assert msg.returncode == 1 and "SystemExit('the config is missing')" in msg.stderr and "the config is missing" in msg.stderr


def test_the_wrapped_script_sees_what_python_script_py_shows_it(tmp_path):
    """Same working directory, same sys.argv, __name__ == '__main__', __file__ as given, and the script's own directory (not the working
    directory) on sys.path."""
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "helper.py").write_text("VALUE = 41\n", encoding="utf-8")
    (tmp_path / "pkg" / "run.py").write_text(textwrap.dedent("""\
        import os, sys
        import helper
        print(__name__, os.path.isabs(__file__), os.path.abspath(__file__) == os.path.abspath('pkg/run.py'), sys.argv[1:],
              os.path.basename(sys.argv[0]), os.getcwd() == os.path.abspath('.'), helper.VALUE + 1)
        print(os.path.abspath(sys.path[0]) == os.path.abspath('pkg'), '' in sys.path)
        os.chdir(os.path.dirname(__file__))  # research scripts do this: with a relative __file__ the dirname is '' and it raises
    """), encoding="utf-8")
    plain = _execute([sys.executable, "pkg/run.py", "--a", "b c", "-x"], tmp_path)
    wrapped = _execute(_argv("python pkg/run.py --a 'b c' -x # a trailing comment, as in corpus-v2 #3's '#gpu_id #split'"), tmp_path)
    assert plain.returncode == wrapped.returncode == 0 and plain.stdout == wrapped.stdout and wrapped.stderr == ""
    assert "__main__ " in wrapped.stdout and "['--a', 'b c', '-x'] run.py True 42" in wrapped.stdout
    # a script placed in the working directory: `os.chdir(os.path.dirname(__file__))` must work exactly as under plain `python main.py`
    (tmp_path / "main.py").write_text("import os\nos.chdir(os.path.dirname(__file__))\nprint('chdir ok')\n", encoding="utf-8")
    assert _execute([sys.executable, "main.py"], tmp_path).stdout == _execute(_argv("python main.py"), tmp_path).stdout == "chdir ok\n"


def test_python_dash_m_runs_through_the_wrapper_too(tmp_path):
    (tmp_path / "tool").mkdir()
    (tmp_path / "tool" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "tool" / "__main__.py").write_text("import sys\nprint(sys.argv[1:])\nraise SystemExit(2)\n", encoding="utf-8")
    proc = _execute(_argv("python -m tool --x 1"), tmp_path)
    assert proc.returncode == 2 and proc.stdout == "['--x', '1']\n" and "SystemExit(2)" in proc.stderr and "RERUN_EXIT_WRAPPER" in proc.stderr


@pytest.mark.parametrize("command, reason", [
    ("bash run.sh", "does not start with python"),
    ("cd src && python train.py", "shell operators"),
    ("python train.py | tee out.log", "shell operators"),
    ("python train.py > out.log", "shell operators"),
    ("python -c 'print(1)'", "python -c program"),
    ("python -X dev train.py", "not supported"),
    ("python", "names no script"),
    ("python train.sh", "does not run a .py script"),
    ("", "empty"),
    ("python 'unterminated", "cannot be parsed"),
])
def test_a_command_that_is_not_a_plain_python_script_is_left_alone_and_the_reason_is_returned(command, reason):
    wrapped, why = runner_hooks.wrap_entry_command(command)
    assert wrapped is None and reason in why


def test_environment_variables_flags_and_quoted_arguments_survive_the_wrapping():
    wrapped, _ = runner_hooks.wrap_entry_command("CUDA_VISIBLE_DEVICES=0 PYTHONPATH='a b' python3 -u main.py --name 'x y' 1e-3 #gpu_id #split")
    parts = shlex.split(wrapped)
    assert parts[:2] == ["CUDA_VISIBLE_DEVICES=0", "PYTHONPATH=a b"] and parts[2:4] == ["python3", "-u"] and parts[4] == "-c"
    assert parts[6:] == ["script", "main.py", "--name", "x y", "1e-3"]  # the shell's comment is gone, as it is for the shell
    assert base64.b64decode(parts[5].split("'")[1]).decode() == runner_hooks.exit_wrapper_source()
    assert "#gpu_id" not in wrapped


# --- the orchestration (fake cloud) ------------------------------------------------------------------------------------

def _is_wrapped(shell: str) -> bool:
    """Is the smoke-wrapped command the exit-wrapper launcher's? (the smoke launcher's payload carries the command it runs)"""
    try:
        return "script main.py" in json.loads(base64.b64decode(shell.split()[-1]))["cmd"]
    except Exception:  # noqa: BLE001 - not a smoke command
        return False


WRAPPER_TRACE = ("RERUN_EXIT_WRAPPER: the entry script raised SystemExit(1); the traceback of the raise (most recent call last):\n"
                 "Traceback (most recent call last):\n  File \"main.py\", line 6, in main\n    raise SystemExit(1)\nSystemExit: 1\n")


def _decoded(shell: str) -> str:
    try:
        return json.loads(base64.b64decode(shell.split()[-1]))["cmd"]
    except Exception:  # noqa: BLE001 - not a smoke command
        return ""


NO_KILL_EVIDENCE = ("RERUN_EVIDENCE_BEGIN exit_status=1\n--meminfo\nMemTotal:        2048000 kB\n--nproc\n2\n--cgroup\n"
                    "/sys/fs/cgroup/memory.events=low 0 high 0 max 0 oom 0 oom_kill 0 \n--dmesg\nRERUN_EVIDENCE_END\n")


def _silent_cloud(monkeypatch, *, wrapper_prints: bool, evidence: str = NO_KILL_EVIDENCE):
    def behaviour(shell, built, files):
        if shell in EXEC or _is_wrapped(shell):
            if not any("numpy==1.19.5" in b for b in built):
                return 1, "", SKLEARN_MISSING
            if _is_wrapped(shell) and wrapper_prints:
                return 1, "", ENTRY_03_SILENT["stderr_tail"][-200:] + "\n" + WRAPPER_TRACE
            extra = evidence if "RERUN_EVIDENCE_BEGIN" in _decoded(shell) else ""  # the evidence run prints the block after the command
            return 1, ENTRY_03_SILENT["stdout_tail"], ENTRY_03_SILENT["stderr_tail"] + extra  # the recorded silent exit (the hook prints nothing)
        return None

    return v140_cloud.install(monkeypatch, behaviour)


def test_entry_3s_recorded_silent_exit_gets_the_wrapper_after_the_hook_printed_nothing(tmp_path, monkeypatch):
    _repo(tmp_path, {"main.py": BARE_EXIT})
    assert not classifier.has_actionable_error(ENTRY_03_SILENT["stderr_tail"], ENTRY_03_SILENT["stdout_tail"])
    cloud = _silent_cloud(monkeypatch, wrapper_prints=True)
    decline = {"file_edits": None, "env_delta": [], "explanation": "the repository raises SystemExit(1) at main.py line 6 on its own"}
    repair = _Chat([decline] * 3, "repair model")
    result, _, guard = _run(tmp_path, cloud, repair=repair)
    rules = [a.time_machine_action["rule"] for a in result.attempts if a.time_machine_action]
    assert rules[:2] == ["exit_site_hook", "exit_wrapper"], result.full_log[-2500:]  # the hook first; the wrapper only because it printed nothing
    wrapper = next(a for a in result.attempts if a.time_machine_action and a.time_machine_action["rule"] == "exit_wrapper")
    action = wrapper.time_machine_action
    assert action["applied"] is True and action["result"] == "the wrapper printed the traceback of the raise"
    assert "printed nothing" in action["matched_error"] and "SystemExit" in action["limit"].replace("Python SystemExit", "SystemExit")
    wrap_op = next(op for op in guard.operations if op["role"] == "time machine: exit_wrapper")
    assert wrap_op["exit_wrapper"] == "applied" and wrap_op["branch_from_image"] is not None and not wrap_op["torch_installed"]
    # the model now sees the raise site, not the "NO TRACEBACK FOUND" rule
    prompt = repair.calls[0]["user_prompt"]
    assert "RERUN_EXIT_WRAPPER" in prompt and "NO TRACEBACK FOUND" not in prompt
    # it runs once per run, and the wrapper stays on for the later operations (candidate re-executions run through it too)
    assert sum(1 for r in rules if r == "exit_wrapper") == 1
    assert all(op.get("exit_wrapper") == "applied" for op in guard.operations if op["role"].startswith("repair"))


def test_if_the_wrapper_prints_nothing_either_the_record_says_exit_outside_python_and_the_entry_ends_indeterminate(tmp_path, monkeypatch):
    """harness-v1.4.1 went on to ask the model (BLOCKED after nine refused patches). harness-v1.4.2-rc (item 4): one evidence run, then INDETERMINATE
    EXIT_OUTSIDE_PYTHON with that reason; no model attempt (the repair client raises if called)."""
    _repo(tmp_path, {"main.py": BARE_EXIT})
    cloud = _silent_cloud(monkeypatch, wrapper_prints=False)
    repair = _Chat([], "repair model")  # raises if called
    result, _, guard = _run(tmp_path, cloud, repair=repair)
    action = next(a.time_machine_action for a in result.attempts if a.time_machine_action and a.time_machine_action["rule"] == "exit_wrapper")
    assert action["applied"] is True and action["result"] == "exit outside Python" == runner_hooks.OUTSIDE_PYTHON
    assert result.verdict == "INDETERMINATE" and result.indeterminate_reason.startswith("EXIT_OUTSIDE_PYTHON: exit outside Python")
    assert "no kill" in result.indeterminate_reason and "MemTotal 2048000 kB" in result.indeterminate_reason and "no model attempt was spent" in result.indeterminate_reason
    assert repair.calls == [] and not [a for a in result.attempts if a.origin == "model"]
    evidence = next(a.time_machine_action for a in result.attempts if a.time_machine_action and a.time_machine_action["rule"] == "resource_evidence")
    assert evidence["kill_evidenced"] is False and evidence["evidence"]["oom_kill"] == 0 and evidence["evidence"]["mem_total_kb"] == 2048000
    assert sum(1 for op in guard.operations if op["role"] == "exit wrapper with evidence") == 1  # once, with the wrapper in place


def test_if_the_evidence_shows_a_kill_the_entry_ends_resource_limit(tmp_path, monkeypatch):
    killed = NO_KILL_EVIDENCE.replace("oom_kill 0", "oom_kill 1").replace("--dmesg\n", "--dmesg\nOut of memory: Killed process 4242 (python)\n")
    _repo(tmp_path, {"main.py": BARE_EXIT})
    cloud = _silent_cloud(monkeypatch, wrapper_prints=False, evidence=killed)
    repair = _Chat([], "repair model")
    result, _, _ = _run(tmp_path, cloud, repair=repair)
    assert result.verdict == "INDETERMINATE" and result.indeterminate_reason.startswith("RESOURCE_LIMIT: the command exited with code 1")
    assert "oom_kill 1" in result.indeterminate_reason and "Killed process 4242" in result.indeterminate_reason
    assert result.taxonomy_code == "RESOURCE_LIMIT" and repair.calls == []


def test_a_command_the_wrapper_cannot_wrap_is_recorded_and_not_run_again(tmp_path, monkeypatch):
    command = "python main.py | tee out.log"
    _repo(tmp_path, {"main.py": BARE_EXIT})
    plain = {command, smoke_exec.wrap(command, 60)}

    def behaviour(shell, built, files):
        if shell not in plain:
            return None
        return (1, "", SKLEARN_MISSING) if not any("numpy==1.19.5" in b for b in built) else (1, "", "")

    cloud = v140_cloud.install(monkeypatch, behaviour)
    decline = {"file_edits": None, "env_delta": [], "explanation": "silent"}
    result, _, guard = _run(tmp_path, cloud, repair=_Chat([decline] * 3, "repair model"), command=command)
    action = next(a.time_machine_action for a in result.attempts if a.time_machine_action and a.time_machine_action["rule"] == "exit_wrapper")
    assert action["applied"] is False and "shell operators" in action["reason"] and "result" not in action
    assert not [op for op in guard.operations if op["role"] == "time machine: exit_wrapper"]  # nothing was executed for it
    assert not any(op.get("exit_wrapper") for op in guard.operations)
