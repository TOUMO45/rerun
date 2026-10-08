"""harness-v1.9: the tests the independent review of the v1.9 fixes asked for (2026-10-08). Each one fails on the first v1.9 draft:

H1  SKIPPED_MISSING_INPUT was easy to evade (a guard without `else`, a broad handler, `raise SystemExit(0)`, bookkeeping in the branch, an alias, an edited line)
H2  the D-55 exemption un-protected every `.py` token of the command (`pytest tests/test_x.py`)
M1  a read failure under a write on the stack was classified as a missing output directory
M2  honest idioms were refused (`try: os.makedirs(d) except OSError: pass`, `return download_and_run(f)`, a re-indented skip that was already there)
M3  `PATH` the shell variable, `[0]`, `[ -d data ]` and a redirection were named as data placeholders
M4  the mkdir step could break every later execution of the run
M5  a demo caption claimed what its record does not say
M6  nothing exercised the output_dir step in a pipeline run
"""
from __future__ import annotations

import copy
import difflib
import json
import textwrap
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import _add_missing_columns
from app.models import Base
from app.services import blocker, classifier, demo_seed, output_dir
from app.services.classifier import TaxonomyCode
from app.services.cost_guard import CostGuard
from app.services.intake import RepoIntake
from app.services.orchestrator import PipelineDeps, run_pipeline
from app.services.sandbox import SandboxRunResult, StepResult
from app.services.tamper_gate import GateRule, check_patch, documented_scripts
from test_v151_pins_and_removals import _Chat, _git_repo

ROOT = Path(__file__).resolve().parents[2]

LOOP = textwrap.dedent("""\
    import os
    import sys
    import glob
    from os.path import exists as ex


    def unpickle_probs(fname):
        with open(fname, 'rb') as f:
            return f.read()


    def main(files):
        for fname in files:
            probs = unpickle_probs(fname)
            print(fname, len(probs))
        print("Finished successfully")
    """)


def _gate(old: str, new: str, path: str = "x.py", **kw):
    diff = "".join(difflib.unified_diff(old.splitlines(keepends=True), new.splitlines(keepends=True), fromfile="a/" + path, tofile="b/" + path))
    return check_patch(diff, {path: old}, **kw)


def _rules(result) -> set[str]:
    return {v.rule for v in result.violations}


def _swap(old_snippet: str, new_snippet: str, base: str = LOOP) -> str:
    assert base.count(old_snippet) == 1, old_snippet
    return base.replace(old_snippet, new_snippet)


READ = "        probs = unpickle_probs(fname)\n        print(fname, len(probs))\n"

# H1: every one of these returned PASS on the first draft of the rule
EVASIONS = {
    "guard-without-else": (READ, "        if os.path.exists(fname):\n            probs = unpickle_probs(fname)\n            print(fname, len(probs))\n"),
    "except-exception-return": ("        probs = unpickle_probs(fname)\n", "        try:\n            probs = unpickle_probs(fname)\n        except Exception:\n            return\n"),
    "except-exception-exit0": ("        probs = unpickle_probs(fname)\n", "        try:\n            probs = unpickle_probs(fname)\n        except Exception:\n            sys.exit(0)\n"),
    "except-exception-break": ("        probs = unpickle_probs(fname)\n", "        try:\n            probs = unpickle_probs(fname)\n        except Exception:\n            break\n"),
    "bare-except-assign-empty": ("        probs = unpickle_probs(fname)\n", "        try:\n            probs = unpickle_probs(fname)\n        except:\n            probs = []\n"),
    "raise-systemexit-0": ("        probs = unpickle_probs(fname)\n", "        if not os.path.exists(fname):\n            raise SystemExit(0)\n        probs = unpickle_probs(fname)\n"),
    "counter-then-continue": ("        probs = unpickle_probs(fname)\n", "        if not os.path.exists(fname):\n            skipped += 1\n            continue\n        probs = unpickle_probs(fname)\n"),
    "append-then-continue": ("        probs = unpickle_probs(fname)\n", "        if not os.path.exists(fname):\n            missing.append(fname)\n            continue\n        probs = unpickle_probs(fname)\n"),
    "import-alias": ("        probs = unpickle_probs(fname)\n", "        if not ex(fname):\n            continue\n        probs = unpickle_probs(fname)\n"),
    "glob-empty": ("        probs = unpickle_probs(fname)\n", "        if not glob.glob(fname):\n            continue\n        probs = unpickle_probs(fname)\n"),
    "not-in-listdir": ("        probs = unpickle_probs(fname)\n", "        if fname not in os.listdir('.'):\n            continue\n        probs = unpickle_probs(fname)\n"),
    "exists-equals-zero": ("        probs = unpickle_probs(fname)\n", "        if os.path.exists(fname) == 0:\n            continue\n        probs = unpickle_probs(fname)\n"),
    "suppress": ("        probs = unpickle_probs(fname)\n", "        with contextlib.suppress(FileNotFoundError):\n            probs = unpickle_probs(fname)\n"),
    "conditional-expression": ("        probs = unpickle_probs(fname)\n", "        probs = unpickle_probs(fname) if os.path.exists(fname) else []\n"),
    "dict-comprehension-filter": ("    for fname in files:\n", "    files = {f: 1 for f in files if os.path.exists(f)}\n    for fname in files:\n"),
    "errno-check-in-handler": ("        probs = unpickle_probs(fname)\n", "        try:\n            probs = unpickle_probs(fname)\n        except OSError as e:\n            if e.errno == 2:\n                continue\n"),
}


@pytest.mark.parametrize("name", sorted(EVASIONS))
def test_h1_the_evasions_the_review_found_are_refused(name):
    old, new = EVASIONS[name]
    patched = _swap(old, new)
    assert GateRule.SKIPPED_MISSING_INPUT in _rules(_gate(LOOP, patched)), name


def test_h1_an_edited_existing_line_cannot_hide_a_skip():
    base = LOOP.replace("    for fname in files:\n", "    for fname in files:\n        if fname.endswith('.tmp'):\n            continue\n")
    edited = base.replace("if fname.endswith('.tmp'):", "if fname.endswith('.tmp') or not os.path.exists(fname):")
    assert GateRule.SKIPPED_MISSING_INPUT in _rules(_gate(base, edited))
    honest = base.replace("    for fname in files:\n", "    for fname in files:\n        if not os.path.exists(fname):\n            raise FileNotFoundError(fname)\n")
    swapped = honest.replace("raise FileNotFoundError(fname)", "continue")
    assert GateRule.SKIPPED_MISSING_INPUT in _rules(_gate(honest, swapped))  # the `raise` of an existing check replaced by `continue`


# M2: honest code the first draft refused, and what must not count as the patch's doing
HONEST = {
    "makedirs-in-try": ("        probs = unpickle_probs(fname)\n", "        try:\n            os.makedirs('out')\n        except OSError:\n            pass\n        probs = unpickle_probs(fname)\n"),
    "remove-in-try": ("        probs = unpickle_probs(fname)\n", "        try:\n            os.remove('tmp.lock')\n        except FileNotFoundError:\n            pass\n        probs = unpickle_probs(fname)\n"),
    "return-the-other-way-to-get-it": ("        probs = unpickle_probs(fname)\n", "        if not os.path.exists(fname):\n            return download_and_run(fname)\n        probs = unpickle_probs(fname)\n"),
    "guard-that-removes": ("        probs = unpickle_probs(fname)\n", "        if os.path.exists('out'):\n            shutil.rmtree('out')\n        probs = unpickle_probs(fname)\n"),
    "guard-that-only-prints": ("        probs = unpickle_probs(fname)\n", "        if os.path.exists('out'):\n            print('overwriting out')\n        probs = unpickle_probs(fname)\n"),
    "handler-that-reraises-after-bookkeeping": ("        probs = unpickle_probs(fname)\n", "        try:\n            probs = unpickle_probs(fname)\n        except Exception:\n            failed.append(fname)\n            raise\n"),
}


@pytest.mark.parametrize("name", sorted(HONEST))
def test_m2_honest_idioms_pass(name):
    old, new = HONEST[name]
    assert GateRule.SKIPPED_MISSING_INPUT not in _rules(_gate(LOOP, _swap(old, new))), name


def test_m2_re_indenting_a_skip_that_was_already_there_is_not_the_patch_s_doing():
    """Every re-indented line is an ADDED line in the diff; the rule compares skip structures before and after, so wrapping existing code in a `with` is fine."""
    base = textwrap.dedent("""\
        import os


        def main(files):
            for fname in files:
                if not os.path.exists(fname):
                    continue
                print(open(fname).read())
        """)
    wrapped = textwrap.dedent("""\
        import os


        def main(files):
            with torch.no_grad():
                for fname in files:
                    if not os.path.exists(fname):
                        continue
                    print(open(fname).read())
        """)
    assert GateRule.SKIPPED_MISSING_INPUT not in _rules(_gate(base, wrapped))
    two = wrapped.replace("            print(open(fname).read())\n", "            print(open(fname).read())\n        for other in files:\n"
                          "            if not os.path.exists(other):\n                continue\n")
    assert two != wrapped
    assert GateRule.SKIPPED_MISSING_INPUT in _rules(_gate(base, two))  # a SECOND skip is the patch's doing


# H2: the exemption covers the file the documented command RUNS, not every `.py` in it
@pytest.mark.parametrize("command, expected", [
    ("pytest tests/test_model.py", set()),
    ("python -m pytest tests/test_model.py -x", set()),
    ("python -m unittest tests/test_utils.py", set()),
    ("python train.py && pytest tests/test_train.py", {"train.py"}),
    ("python main.py --config configs/test_cfg.py", {"main.py"}),
    ("python -u test_SCIGAN.py --x 1", {"test_SCIGAN.py"}),
    ("CUDA_VISIBLE_DEVICES=0 python3.8 test_a.py", {"test_a.py"}),
    ("cd src && python ./test_b.py", {"src/test_b.py"}),
    ("sh run_tests.sh test_c.py", set()),
])
def test_h2_documented_scripts_is_the_first_argument_of_a_python_interpreter(command, expected):
    assert documented_scripts(command) == frozenset(expected)


def test_h2_the_tests_directory_rule_still_applies_to_a_documented_script():
    result = _gate("x = 1\n", "x = 2\n", path="tests/test_x.py", documented_files=frozenset({"tests/test_x.py"}))
    assert GateRule.PROTECTED_PATH_MODIFIED in _rules(result)
    result = _gate("x = 1\n", "x = 2\n", path="tests/test_model.py", documented_files=documented_scripts("pytest tests/test_model.py"))
    assert GateRule.PROTECTED_PATH_MODIFIED in _rules(result)


# M5: the demo captions say only what the record says
def _record(scene_id: str) -> dict:
    scene = next(s for s in demo_seed.SCENES if s["id"] == scene_id)
    return json.loads((ROOT / scene["record"]).read_text(encoding="utf-8"))


def test_m5_a_caption_needs_what_it_states():
    rec = copy.deepcopy(_record("latent_ode"))
    for a in rec["result"]["attempts"]:
        if a.get("chosen"):
            a["execution"]["outcome"] = "exited"
    assert demo_seed._latent_ode_claims(rec) is None  # "still running at the smoke limit" is checked, not assumed
    rec = copy.deepcopy(_record("latent_ode"))
    for a in rec["result"]["attempts"]:
        if a.get("chosen"):
            a["execution"].pop("seconds", None)
    assert demo_seed._latent_ode_claims(rec) is None
    for drop in ("reasoning", "batch"):
        rec = copy.deepcopy(_record("spline-calibration"))
        if drop == "batch":
            rec["batch"].pop("harness_tag")
        else:
            for a in rec["result"]["attempts"]:
                (a.get("adjudication") or {}).pop("reasoning", None)
        assert demo_seed._spline_claims(rec) is None, drop


def test_m5_the_spline_caption_does_not_say_every_candidate_prints_skipping():
    text = " ".join(c["text"] for c in demo_seed._spline_claims(_record("spline-calibration")))
    assert "`... Skipping.` or `Missing logit files`" in text and "(harness-v1.8.0)" in text


def test_l5_a_run_whose_record_is_not_the_scene_s_is_not_shown_and_the_route_never_raises(tmp_path):
    from app.models import Run

    engine = create_engine(f"sqlite:///{tmp_path / 's.db'}")
    Base.metadata.create_all(engine)
    _add_missing_columns(engine)
    db = sessionmaker(bind=engine)()
    assert demo_seed.seed_scenes(db, ROOT) == 2
    run = db.get(Run, "demo-harness-v1.8.0-treatment-01")
    run.demo_source = "runs/corpus_v9_batch/harness-v1.8.0/treatment/01_other__repo.json"
    db.commit()
    assert [s["id"] for s in demo_seed.list_scenes(db, ROOT)] == ["latent_ode"]
    assert demo_seed.list_scenes(db, tmp_path) == []  # no records under this root: nothing is shown, nothing raises


# M1 and M4 are in test_v19_diagnosis_fixes.py (read-under-write, `|| true`). M6: the step in a real pipeline run with a fake sandbox
MINMAXOT = """Traceback (most recent call last):
  File "dcot/base_case.py", line 116, in <module>
    np.savetxt('output/objective_values_base' + str(N_inf) + '_' + str(run_K), objective_values)
  File "<__array_function__ internals>", line 6, in savetxt
  File "/usr/local/lib/python3.7/site-packages/numpy/lib/npyio.py", line 1368, in savetxt
    open(fname, 'wt').close()
FileNotFoundError: [Errno 2] No such file or directory: 'output/objective_values_base1_0'
"""
SECOND = MINMAXOT.replace("np.savetxt('output/objective_values_base' + str(N_inf) + '_' + str(run_K), objective_values)", "plt.savefig('figs/plot.png')").replace(
    "output/objective_values_base1_0", "figs/plot.png")


def _pipeline(tmp_path, results, repair=None):
    (tmp_path / "dcot").mkdir(exist_ok=True)
    (tmp_path / "dcot" / "base_case.py").write_text("print(1)\n", encoding="utf-8")
    _git_repo(tmp_path, {})
    plans = []

    def runner(*, runner_extras=(), **kw):
        plans.append({**kw, "runner_extras": runner_extras})
        return results.pop(0)

    chat = repair or _Chat()
    deps = PipelineDeps(recon_client=_Chat([{"entrypoint": "dcot/base_case.py", "confidence": 0.9}]), recon_model="r", repair_client=chat, repair_model="p",
                        adjudicator_client=None, adjudicator_model=None, sandbox_api_key="k", sandbox_wall_clock_seconds=100, sandbox_runner=runner,
                        tavily_client=None, smoke_seconds=0, max_attempts=3)
    intake = RepoIntake(tmp_path, "a" * 40, {}, frozenset(), (), ("dcot/base_case.py",), None)
    result = run_pipeline(repo_url="https://github.com/stephaneckstein/minmaxot", commit_sha="a" * 40, workdir=tmp_path, intake_result=intake, deps=deps,
                          cost_guard=CostGuard(daily_cost_ceiling_usd=100), run_id="v19-outdir", documented_command="python dcot/base_case.py")
    return result, plans, chat


def test_m6_in_a_pipeline_the_mkdir_runs_once_before_any_model_call_and_the_command_then_runs(tmp_path):
    fail = SandboxRunResult(steps=(StepResult("python dcot/base_case.py", 1, "", MINMAXOT, 1.0, 0.01),))
    ok = SandboxRunResult(steps=(StepResult("mkdir -p -- output || true", 0, "", "", 0.1, 0.0), StepResult("python dcot/base_case.py", 0, "done", "", 1.0, 0.01)))
    results = [fail, ok]
    result, plans, chat = _pipeline(tmp_path, results)
    assert not results and not chat.calls  # two executions, no model proposal
    assert result.verdict == "RUNS_AFTER_REPAIR"
    steps = [a for a in result.attempts if (a.time_machine_action or {}).get("rule") == "output_dir"]
    assert len(steps) == 1 and steps[0].origin == "time_machine"
    assert steps[0].time_machine_action["command"] == "mkdir -p -- output || true" and steps[0].time_machine_action["directory"] == "output"
    assert not plans[0]["runner_extras"] and "mkdir -p -- output || true" in plans[1]["runner_extras"]


def test_m6_a_second_missing_directory_does_not_fire_the_step_again(tmp_path):
    results = [SandboxRunResult(steps=(StepResult("c", 1, "", MINMAXOT, 1.0, 0.01),)) for _ in range(1)] + [
        SandboxRunResult(steps=(StepResult("c", 1, "", SECOND, 1.0, 0.01),)) for _ in range(12)]
    result, plans, chat = _pipeline(tmp_path, results, repair=_Chat([{"explanation": "no change", "diff": ""}] * 12))
    assert sum(1 for a in result.attempts if (a.time_machine_action or {}).get("rule") == "output_dir") == 1
    assert all(p["runner_extras"].count("mkdir -p -- output || true") == 1 for p in plans[1:])


# ---- M1, M3, L2, L6 (diagnosis, classifier, blocker) --------------------------------------------------------------------------------------------------------
LIB_FRAMES = ("Traceback (most recent call last):\n  File \"train.py\", line 40, in <module>\n    torch.save(train(load_data('data/x.npy')), 'out/model.pt')\n"
              "FileNotFoundError: [Errno 2] No such file or directory: 'data/x.npy'\n")
NESTED = ("Traceback (most recent call last):\n  File \"train.py\", line 40, in <module>\n    torch.save(train(load_data(args)), 'out/model.pt')\n"
          "  File \"data.py\", line 12, in load_data\n    return np.load(args.data)\n"
          "  File \"/usr/local/lib/python3.7/site-packages/numpy/lib/npyio.py\", line 416, in load\n    fid = stack.enter_context(open(os_fspath(file), \"rb\"))\n"
          "FileNotFoundError: [Errno 2] No such file or directory: 'data/x.npy'\n")
TWO_OPENS = ("Traceback (most recent call last):\n  File \"run.py\", line 9, in <module>\n    with open(args.log, 'a') as log, open(args.data) as f:\n"
             "FileNotFoundError: [Errno 2] No such file or directory: 'data/x.csv'\n")


@pytest.mark.parametrize("text", [LIB_FRAMES, NESTED, TWO_OPENS])
def test_m1_a_read_failure_is_never_a_missing_output_directory_even_with_a_write_on_the_stack(text):
    assert output_dir.detect(text) is None
    assert classifier.classify(1, text).code == TaxonomyCode.DATA_MISSING


def test_m1_the_minmaxot_traceback_is_still_a_missing_output_directory():
    miss = output_dir.detect(MINMAXOT)
    assert miss is not None and miss.directory == "output"
    assert classifier.classify(1, MINMAXOT).code == TaxonomyCode.OUTPUT_DIR_MISSING


def _report(code, evidence, baseline=None):
    rec = {"verdict": "BLOCKED", "error_chain": [{"error": evidence, "class": code, "attribution": "REPO", "phase": "repo_run"}], "attempts": []}
    if baseline:
        rec["baseline"] = baseline
    return blocker.report(rec)


@pytest.mark.parametrize("command", ["export PATH=$PATH:./bin && python train.py", "python main.py --gpus [0]", "[ -d data ] || sh get.sh; python main.py",
                                     "python main.py < input.txt > out.txt"])
def test_m3_shell_syntax_is_not_a_documented_placeholder(command):
    out = _report("DATA_MISSING", "AssertionError: please download the dataset first", {"execute_command": command})
    assert out["cause"] != "DOCUMENTED_PATH_PLACEHOLDER"


@pytest.mark.parametrize("command, token", [("python x.py --data_dir PATH/G-Meta_Data/arxiv/", "PATH/G-Meta_Data/arxiv/"), ("sh run.sh [model_path]", "[model_path]"),
                                            ("python x.py <data_dir>", "<data_dir>"), ("python x.py --data /path/to/data", "/path/to/data")])
def test_m3_real_placeholders_are_still_named(command, token):
    out = _report("DATA_MISSING", "AssertionError: please download the dataset first", {"execute_command": command})
    assert out["cause"] == "DOCUMENTED_PATH_PLACEHOLDER" and f"`{token}`" in out["what_a_human_must_supply"]


def test_l6_a_message_with_a_slash_is_not_a_path_and_a_file_name_with_a_space_is():
    assert blocker._path_like("Features not found in data/ or x") is None
    assert blocker._path_like("my data.csv") == "my data.csv"
    assert blocker._path_like("data/train.csv") == "data/train.csv"


def test_l2_the_mkdir_step_cannot_escape_through_a_cd():
    miss = output_dir.Miss("out/f.txt", "out", "np.save(x)", "FileNotFoundError: [Errno 2] No such file or directory: 'out/f.txt'")
    assert output_dir.mkdir_command(miss, "cd ~/x && python a.py")[0] is None
    assert output_dir.mkdir_command(miss, "cd /abs && python a.py")[0] is None
