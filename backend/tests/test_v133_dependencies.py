"""harness-v1.3.3: batch dependency resolution, era lock and Python rule, dependency-confusion guard, apt `remove`.

Offline only. The uv errors in fixtures/v133/uv_lock_errors.json are the real ones recorded by the v1.3.2 TREATMENT arm
(entries 1, 8, 13, 19, 20); the README excerpt is entry 3's own ("- Python 3.6.9")."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from app.services import dep_scan, env_repair, python_policy, time_machine
from app.services.planner import BuildPlan
from app.services.time_machine import compile_lock

FIXTURES = json.loads((Path(__file__).parent / "fixtures" / "v133" / "uv_lock_errors.json").read_text(encoding="utf-8"))


def _tree(tmp_path: Path, files: dict[str, str]) -> Path:
    for rel, text in files.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(text, encoding="utf-8")
    return tmp_path


# --- the scan ---------------------------------------------------------------------------------------------------------


def test_scan_builds_one_batch_from_the_whole_tree_and_excludes_the_repos_own_modules(tmp_path):
    root = _tree(tmp_path, {
        "train.py": "import os, sys\nimport numpy as np\nimport yaml\nimport utils\nfrom models.vgg import VGG\nimport sklearn.metrics\n",
        "models/__init__.py": "",
        "models/vgg.py": "import torch\nimport curves\nfrom .helpers import h\n",
        "models/helpers.py": "import tabulate\n",
        "utils.py": "import six\n",
        "deep/nested/tool.py": "import h5py\nimport skimage.io\n",
        "notes.ipynb": "{}",
    })
    batch = dep_scan.batch_install_set(dep_scan.scan_repo(root), declared=frozenset())
    assert set(batch.names) == {"numpy", "pyyaml", "scikit-learn", "torch", "curves", "tabulate", "six", "h5py", "scikit-image"}
    assert set(batch.internal) == {"utils", "models"}  # resolvable inside the tree: never PyPI packages
    assert batch.names == tuple(sorted(batch.names, key=str.lower))  # deterministic order
    assert {m.module for _, m in batch.distributions if m is not None} >= {"yaml", "sklearn", "skimage"}


def test_the_declared_set_is_not_reinstalled_and_optional_guarded_imports_are_skipped(tmp_path):
    root = _tree(tmp_path, {
        "a.py": "import numpy\nimport scipy\ntry:\n    import apex\nexcept ImportError:\n    apex = None\n",
        "b.py": "try:\n    import ujson as json\nexcept (ImportError, ModuleNotFoundError):\n    import json\nimport ujson2\n",
        "c.py": "try:\n    import tqdm\nexcept ImportError:\n    pass\n\ndef f():\n    import tqdm\n",  # also imported unguarded, in a function
    })
    batch = dep_scan.batch_install_set(dep_scan.scan_repo(root), declared=frozenset({"numpy"}))
    assert "numpy" in batch.declared and "numpy" not in batch.names
    assert "apex" in batch.optional and "ujson" in batch.optional and "apex" not in batch.names
    assert "tqdm" in batch.names  # unguarded somewhere: required
    assert {"scipy", "ujson2"} <= set(batch.names)


def test_a_compiled_extension_the_repo_declares_makes_its_package_internal_entry_19(tmp_path):
    root = _tree(tmp_path, {
        "operators/__init__.py": "",
        "operators/functions/unsorted_segment_sum.py": "from operators._ext import segment_reduction\n",
        "operators/build.py": "import torch.utils.ffi\nffi = create_extension('operators._ext', headers=[], sources=[])\n",
        "main.py": "from operators.functions.unsorted_segment_sum import UnsortedSegmentSumFunction\nimport operators\nimport yaml\n",
    })
    batch = dep_scan.batch_install_set(dep_scan.scan_repo(root), declared=frozenset())
    assert "operators" in batch.internal and "operators" not in batch.names
    assert batch.names == ("pyyaml", "torch") or set(batch.names) == {"pyyaml", "torch"}


def test_extension_declared_in_setup_py_and_prebuilt_so_files_are_internal(tmp_path):
    root = _tree(tmp_path, {
        "setup.py": "from setuptools import setup, Extension\nsetup(ext_modules=[Extension('fastops._core', ['a.c'])])\n",
        "run.py": "import fastops\nimport prebuilt\nimport cv2\n",
        "libs/prebuilt.cpython-38-x86_64-linux-gnu.so": "",
    })
    batch = dep_scan.batch_install_set(dep_scan.scan_repo(root), declared=frozenset())
    assert set(batch.internal) == {"fastops", "prebuilt"}
    assert batch.names == ("opencv-python",)


def test_python2_standard_library_names_are_not_pypi_packages(tmp_path):
    root = _tree(tmp_path, {"x.py": "import urllib2\nimport cPickle\nimport numpy\n"})
    batch = dep_scan.batch_install_set(dep_scan.scan_repo(root), declared=frozenset())
    assert set(batch.python2_only) == {"urllib2", "cPickle"} and batch.names == ("numpy",)


def test_a_file_that_does_not_parse_does_not_stop_the_scan(tmp_path):
    root = _tree(tmp_path, {"py2.py": "print 'hello'\nimport numpy\n", "ok.py": "import scipy\n"})
    batch = dep_scan.batch_install_set(dep_scan.scan_repo(root), declared=frozenset())
    assert batch.names == ("scipy",)


# --- dependency-confusion guard (D-12) ---------------------------------------------------------------------------------


def test_a_package_named_like_a_repo_module_is_refused_entry_19_operators():
    internal = frozenset({"operators", "models", "yaml"})
    assert dep_scan.shadows_repo_module("operators", internal) == "operators"
    assert dep_scan.shadows_repo_module("pyyaml", internal) == "yaml"  # the dist->import map closes the alias route
    assert dep_scan.shadows_repo_module("numpy", internal) is None


def _change(op, package, version=None, evidence="ModuleNotFoundError: No module named 'operators._ext'"):
    return env_repair.EnvChange(op=op, package=package, version=version, justification="missing module", evidence=evidence)


def test_the_env_gate_rejects_the_exact_entry_19_repair():
    violations = env_repair.check_env_delta(
        (_change("add", "operators", "1.0.0"),),
        log_text="ModuleNotFoundError: No module named 'operators._ext'",
        imported_modules=frozenset({"operators"}), has_requirements_txt=False,
        repo_internal_modules=frozenset({"operators"}),
    )
    assert [v.rule for v in violations] == [env_repair.EnvRule.ENV_SHADOWS_REPO_MODULE]
    assert "operators" in violations[0].reason


def test_the_gate_still_allows_a_real_third_party_add():
    violations = env_repair.check_env_delta(
        (_change("add", "tabulate", "0.8.7", "ModuleNotFoundError: No module named 'operators._ext'"),),
        log_text="ModuleNotFoundError: No module named 'operators._ext'", imported_modules=frozenset(),
        has_requirements_txt=False, repo_internal_modules=frozenset({"operators"}),
    )
    assert violations == ()


# --- apt `remove` (D-10) -------------------------------------------------------------------------------------------------


def test_remove_of_an_apt_package_edits_the_apt_list_entry_12():
    plan = BuildPlan("python:3.7-slim", ("libnvinfer-plugin6", "libnvinfer6"), ("pip install -r requirements.txt",), "python main.py")
    log = "E: Unable to locate package libnvinfer6"
    changes = (env_repair.EnvChange(op="remove", package="libnvinfer6", justification="not in the repos", evidence=log),
               env_repair.EnvChange(op="remove", package="libnvinfer-plugin6", justification="not in the repos", evidence=log))
    assert env_repair.check_env_delta(changes, log_text=log, imported_modules=frozenset(), has_requirements_txt=False,
                                      apt_packages=frozenset(plan.apt_install)) == ()
    new_plan, _ = env_repair.apply_env_delta(plan, changes, "tensorflow==1.15.0\n")
    assert new_plan.apt_install == ()  # before: both stayed and the same apt error repeated


def test_remove_of_an_unknown_name_without_requirements_is_still_unsupported():
    v = env_repair.check_env_delta(
        (env_repair.EnvChange(op="remove", package="nosuchthing", justification="x", evidence="E: Unable to locate package nosuch"),),
        log_text="E: Unable to locate package nosuch", imported_modules=frozenset(), has_requirements_txt=False)
    assert [x.rule for x in v] == [env_repair.EnvRule.ENV_UNSUPPORTED]


# --- era lock against the real uv failures of v1.3.2 (D-1, D-5) ------------------------------------------------------------


def _runner_from_real_errors(fixture: dict, *, fails_for: dict[str, str], seen: list, relax_fixes: frozenset = frozenset()):
    """Emulates uv: a name in `fails_for` fails with the REAL recorded message, unless it is in `relax_fixes` (its first
    release falls inside the relaxation window) AND was relaxed via --exclude-newer-package; anything else locks."""

    def runner(argv, stdin):
        seen.append((list(argv), stdin))
        relaxed = {argv[i + 1].split("=")[0] for i, a in enumerate(argv) if a == "--exclude-newer-package"}
        for name, error in fails_for.items():
            if name in stdin.split() and not (name in relaxed and name in relax_fixes):
                return 1, "", error
        return 0, "\n".join(f"{line.strip()}==1.0" for line in stdin.split() if line.strip()) + "\n", ""

    return runner


def test_entry_1_curves_has_no_release_before_the_era_so_it_is_dropped_and_the_lock_proceeds():
    f = FIXTURES["1"]
    seen = []
    lock = compile_lock([], [i for i in f["inputs"]], date.fromisoformat(f["era"]), f["python"],
                        runner=_runner_from_real_errors(f, fails_for={"curves": f["error"]}, seen=seen), uv="uv", build_python="3.8")
    assert lock.ok
    assert "curves" not in " ".join(lock.lock_lines) and lock.not_on_index == ("curves",)
    assert dict(lock.relaxed) == {}  # curves was tried with a relaxed cutoff first, then dropped
    assert any("--exclude-newer-package" in argv for argv, _ in seen)  # the relaxation WAS attempted for it


def test_entry_8_a_name_with_nothing_inside_the_relaxation_window_is_dropped_not_fatal():
    f = FIXTURES["8"]
    lock = compile_lock([], f["inputs"], date.fromisoformat(f["era"]), f["python"],
                        runner=_runner_from_real_errors(f, fails_for={"torch": f["error"], "torchvision": f["error"].replace("torch", "torchvision")}, seen=[]),
                        uv="uv", build_python="3.8")
    assert lock.ok and "numpy==1.0" in lock.lock_lines
    assert set(lock.not_on_index) >= {"torch"}  # (the runner provides torch; the lock no longer dies for it)


def test_entry_20_a_package_released_shortly_after_the_era_is_relaxed_not_dropped():
    f = FIXTURES["20"]
    seen = []
    # the real error says pycocoevalcap was filtered by exclude-newer (v1.2 was published 6 weeks after the era estimate)
    lock = compile_lock([], f["inputs"], date.fromisoformat(f["era"]), f["python"],
                        runner=_runner_from_real_errors(f, fails_for={"pycocoevalcap": f["error"]}, seen=seen,
                                                        relax_fixes=frozenset({"pycocoevalcap"})), uv="uv", build_python="3.8")
    assert lock.ok and "pycocoevalcap==1.0" in lock.lock_lines  # kept
    assert dict(lock.relaxed) == {"pycocoevalcap": "2021-10-04T00:00:00Z"}  # era 2020-10-03 + 1 day + 365 days
    assert lock.as_dict()["relaxed"] == [{"package": "pycocoevalcap", "cutoff": "2021-10-04T00:00:00Z"}]


# --- Python: a README-declared version wins over the era inference (D-11) -----------------------------------------------------


def test_entry_3_readme_declares_python_36():
    readme = "# vmtl\n\n## Requirements\n - Python 3.6.9\n - PyTorch\n"
    choice = python_policy.resolve({}, readme)
    assert (choice.version, choice.source, choice.is_declared) == ("3.6", "README", True)


def test_python_for_era_uses_the_declared_version_over_the_era_default():
    assert time_machine.python_for_era(date(2022, 9, 15), None)[0] == "3.10"
    assert time_machine.python_for_era(date(2022, 9, 15), "3.6") == ("3.6", "declared by the repository")


def test_the_orchestrator_passes_the_readme_python_to_the_era_lock(tmp_path):
    """End to end through run_pipeline (fakes): README says Python 3.6.9, the era is 2022 (which alone would give 3.10)."""
    import json as _json
    import subprocess

    from app.services.cost_guard import CostGuard
    from app.services.intake import RepoIntake
    from app.services.orchestrator import PipelineDeps, run_pipeline
    from app.services.sandbox import SandboxRunResult, StepResult
    from app.services.time_machine import LockResult

    (tmp_path / "README.md").write_text("Requirements:\n - Python 3.6.9\n", encoding="utf-8")
    (tmp_path / "train.py").write_text("import sklearn\n", encoding="utf-8")
    for argv in (["git", "init", "-q"], ["git", "add", "-A"], ["git", "-c", "user.email=t@e.st", "-c", "user.name=t", "commit", "-q", "-m", "x"]):
        subprocess.run(argv, cwd=tmp_path, check=True, capture_output=True, env={**__import__("os").environ, "GIT_COMMITTER_DATE": "2022-09-15T00:00:00"})
    seen = {}

    def lock_compiler(reqs, extra, era, py):
        seen["py"] = py
        return LockResult(True, ("scikit-learn==1.0",), tuple(extra))

    class _Chat:
        def __init__(self, r):
            self.r = list(r)

        def chat_completion(self, **kw):
            return self.r.pop(0)

    bases = []

    def sandbox(**kw):
        bases.append(kw["base_image"])
        if len(bases) == 1:
            return SandboxRunResult(steps=(StepResult("python train.py", 1, "", "ModuleNotFoundError: No module named 'sklearn'", 1.0, 0.0),))
        return SandboxRunResult(steps=(StepResult("python train.py", 0, "ok", "", 1.0, 0.0),))

    intake = RepoIntake(tmp_path, "a" * 40, {}, frozenset(), (), ("train.py",), None)
    deps = PipelineDeps(
        recon_client=_Chat([_json.dumps({"entrypoint": "train.py", "confidence": 0.9})]), recon_model="r",
        repair_client=_Chat([]), repair_model="p", adjudicator_client=None, adjudicator_model=None,
        sandbox_api_key="k", sandbox_wall_clock_seconds=100, sandbox_runner=sandbox, lock_compiler=lock_compiler,
        http_get=lambda url: (404, None),
    )
    result = run_pipeline(repo_url="https://github.com/o/r", commit_sha="a" * 40, workdir=tmp_path, intake_result=intake,
                          deps=deps, cost_guard=CostGuard(daily_cost_ceiling_usd=100), run_id="py")
    assert result.verdict == "RUNS_AFTER_REPAIR", result.full_log
    assert seen["py"] == "3.6" and bases == ["python:3.6-slim", "python:3.6-slim"]
    tm = result.attempts[0].time_machine
    assert tm["python"]["version"] == "3.6" and "README" in tm["python"]["reason"]
    assert tm["batch_scan"]["install"] == ["scikit-learn"]


# --- the D1 entries of corpus-v2: the recorded output of scripts/dep_scan_check.py --------------------------------------------

D1_EVIDENCE = Path(__file__).resolve().parents[2] / "reports" / "corpus-v2.1" / "v1.3.3" / "dep_scan_d1.json"


def test_batch_covers_every_module_one_at_a_time_repair_met_on_the_d1_entries():
    """scripts/dep_scan_check.py cloned the pinned commits and scanned the real trees (no sandbox, no model). Every
    `No module named X` in the v1.3.2 CONTROL and TREATMENT error chains of the D1 entries is in the batch or internal to
    the repo; the only exception is `distutils` (entry 8): stdlib in the repo's era, removed in 3.12, not a package."""
    rows = json.loads(D1_EVIDENCE.read_text(encoding="utf-8"))
    d1 = [r for r in rows if r["stratum"] == "D1"]
    assert {r["id"] for r in d1} == {1, 3, 7, 8, 10, 11, 15, 16, 20}
    assert {r["id"]: r["missed"] for r in d1 if r["missed"]} == {8: ["distutils"]}
    # one batch replaces up to three attempts: e.g. entry 16 met sklearn, ruamel, language_evaluation one by one
    entry16 = next(r for r in d1 if r["id"] == 16)
    assert {"scikit-learn", "ruamel.yaml", "language_evaluation"} <= set(entry16["batch_install"])
    entry20 = next(r for r in d1 if r["id"] == 20)
    assert {"six", "h5py", "scikit-image"} <= set(entry20["batch_install"])


def test_entry_19_operators_is_internal_not_a_dependency():
    rows = json.loads(D1_EVIDENCE.read_text(encoding="utf-8"))
    entry19 = next(r for r in rows if r["id"] == 19)
    assert "operators" in entry19["internal_excluded"] and "operators" not in entry19["batch_install"]
