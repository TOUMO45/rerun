"""Step 1 of the 2026-09-24 build pass: era date, era Python, whole-set uv
lock (time machine), source search on PyPI 404, used-only citations, the
missing-justification re-ask, and the .env duplicate-key startup check."""

from __future__ import annotations

import json
import subprocess
from datetime import date
from pathlib import Path

import pytest

from app.config import DuplicateEnvKeyError, check_env_file_duplicates
from app.services import time_machine
from app.services.classifier import TaxonomyCode
from app.services.cost_guard import CostGuard
from app.services.dep_resolver import resolve
from app.services.intake import RepoIntake
from app.services.orchestrator import PipelineDeps, run_pipeline
from app.services.planner import BuildPlan
from app.services.sandbox import SandboxRunResult, StepResult
from app.services.time_machine import LockResult, apply_lock, compile_lock, era_date, python_for_era


class FakeHttp:
    def __init__(self, routes):
        self.routes = routes
        self.calls: list[str] = []

    def __call__(self, url):
        self.calls.append(url)
        for prefix, response in self.routes.items():
            if url.startswith(prefix):
                return response
        return 404, None


def _commit(day: str):
    return 200, [{"sha": "f" * 40, "commit": {"committer": {"date": f"{day}T12:00:00Z"}}}]


def _git_repo(tmp_path: Path, files: dict[str, str], commit_date: str = "2024-01-26T00:00:00") -> Path:
    for rel, content in files.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(content, encoding="utf-8")
    env = {"GIT_AUTHOR_DATE": commit_date, "GIT_COMMITTER_DATE": commit_date}
    import os

    run_env = {**os.environ, **env}
    for argv in (["git", "init", "-q"], ["git", "add", "-A"],
                 ["git", "-c", "user.email=t@e.st", "-c", "user.name=t", "commit", "-q", "-m", "x"]):
        subprocess.run(argv, cwd=tmp_path, check=True, capture_output=True, env=run_env)
    return tmp_path


# --- a) era date from dependency-file history --------------------------------

REPO = "https://github.com/openai/gpt-2"


def test_a_era_is_the_latest_dependency_file_change_not_the_pinned_commit(tmp_path):
    """gpt-2 live: pinned commit 2024-01-26 (README edit), requirements.txt 2019-03-04."""
    repo = _git_repo(tmp_path, {"requirements.txt": "regex==2017.4.5\n", "setup.cfg": "[x]\n", "README.md": "hi\n"})
    http = FakeHttp({
        f"https://api.github.com/repos/openai/gpt-2/commits?path=requirements.txt&sha={'a' * 40}": _commit("2019-03-04"),
        f"https://api.github.com/repos/openai/gpt-2/commits?path=setup.cfg&sha={'a' * 40}": _commit("2018-11-02"),
    })
    era = era_date(REPO, "a" * 40, repo, http)
    assert era.date == date(2019, 3, 4)
    assert era.source == "dependency-files"
    assert era.detail == {"requirements.txt": "2019-03-04", "setup.cfg": "2018-11-02"}
    assert "README" not in " ".join(http.calls)  # only dependency files are dated


def test_a_falls_back_to_the_pinned_commit_date_and_says_so(tmp_path):
    repo = _git_repo(tmp_path, {"train.py": "print(1)\n"}, commit_date="2024-01-26T00:00:00")
    era = era_date(REPO, "a" * 40, repo, FakeHttp({}))
    assert era.date == date(2024, 1, 26)
    assert era.source == "pinned-commit"
    assert era.detail["note"] == "no dependency files in the repository"


def test_a_non_github_repo_falls_back(tmp_path):
    repo = _git_repo(tmp_path, {"requirements.txt": "x\n"}, commit_date="2023-05-05T00:00:00")
    era = era_date("https://gitlab.com/o/r", "a" * 40, repo, FakeHttp({}))
    assert (era.date, era.source) == (date(2023, 5, 5), "pinned-commit")


def test_a_dependency_file_patterns():
    for name in ("requirements.txt", "requirements-dev.txt", "requirements_gpu.txt", "setup.py", "setup.cfg",
                 "pyproject.toml", "environment.yml", "environment.yaml"):
        assert time_machine.DEPENDENCY_FILE_RE.match(name), name
    for name in ("README.md", "train.py", "requirements.md", "Pipfile"):
        assert not time_machine.DEPENDENCY_FILE_RE.match(name), name


# --- b) era Python + whole-set lock --------------------------------------------


@pytest.mark.parametrize(
    "era,expected",
    [
        (date(2019, 3, 4), "3.7"),   # gpt-2: 3.7 released 2018-06-27 (>=180 days before)
        (date(2019, 11, 1), "3.7"),  # 3.8 (2019-10-14) too new by the lag rule
        (date(2024, 8, 30), "3.12"),  # TTPT
        (date(2016, 1, 1), "3.6"),   # predates everything supported -> oldest
        (date(2030, 1, 1), "3.13"),
    ],
)
def test_b_python_for_era(era, expected):
    assert python_for_era(era)[0] == expected


def test_b_declared_python_wins():
    assert python_for_era(date(2019, 3, 4), "3.6") == ("3.6", "declared by the repository")


def test_b_compile_lock_uses_exclude_newer_and_linux_target():
    seen = {}

    def runner(argv, stdin):
        seen["argv"], seen["stdin"] = argv, stdin
        return 0, "numpy==1.16.2\ntensorflow==1.13.1\n", ""

    lock = compile_lock(["regex==2017.4.5", "-e .", "git+https://x/y"], ["numpy", "tensorflow"], date(2019, 3, 4), "3.7",
                        runner=runner, uv="uv", build_python="3.8")
    assert lock.ok and lock.lock_lines == ("numpy==1.16.2", "tensorflow==1.13.1")
    argv = seen["argv"]
    assert argv[argv.index("--exclude-newer") + 1] == "2019-03-05T00:00:00Z"  # through the era day
    assert argv[argv.index("--python-version") + 1] == "3.7"
    assert argv[argv.index("--python-platform") + 1] == "x86_64-unknown-linux-gnu"
    assert seen["stdin"] == "regex==2017.4.5\nnumpy\ntensorflow\n"  # flags / URLs are not passed to uv


def test_b_packages_the_index_does_not_know_are_dropped_and_reported():
    calls = []

    def runner(argv, stdin):
        calls.append(stdin)
        if "dassl" in stdin:
            return 1, "", ("error: No solution found when resolving dependencies\n  cause: Because dassl was not found "
                           "in the package registry and you require dassl, we can conclude that your requirements are unsatisfiable.")
        return 0, "torch==2.4.0\n", ""

    lock = compile_lock(["torch"], ["dassl"], date(2024, 8, 30), "3.12", runner=runner, uv="uv", build_python="3.8")
    assert lock.ok and lock.not_on_index == ("dassl",) and lock.lock_lines == ("torch==2.4.0",)
    assert len(calls) == 2


def test_b_other_uv_errors_fail_the_lock_without_guessing():
    lock = compile_lock(["x"], [], date(2020, 1, 1), "3.8", runner=lambda a, s: (1, "", "error: Failed to build `fire`"),
                        uv="uv", build_python="3.8")
    assert not lock.ok and "Failed to build" in lock.error


def test_b_undeclared_third_party_imports(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "model.py").write_text("import numpy as np\n", encoding="utf-8")
    (tmp_path / "src" / "gen.py").write_text(
        "import os, json\nimport tensorflow as tf\nimport model\nfrom sklearn import metrics\nimport regex\n", encoding="utf-8"
    )
    assert time_machine.undeclared_third_party_imports(tmp_path, frozenset({"regex"})) == [
        "numpy", "scikit-learn", "tensorflow",
    ]


def test_b_apply_lock_builds_the_era_plan():
    plan = BuildPlan("python:3.11-slim", (), ("pip install -r requirements.txt",), "python src/gen.py")
    new = apply_lock(plan, "3.7", ["numpy==1.16.2", "tensorflow==1.13.1"], ("build-essential",))
    assert new.base_image == "python:3.7-slim"
    assert new.apt_install == ("build-essential",)
    (cmd,) = new.install_commands
    assert cmd.endswith("pip install -r .rerun-requirements.txt") and "tensorflow==1.13.1" in cmd
    pkg = apply_lock(BuildPlan("python:3.11-slim", (), ("pip install .",), "python x.py"), "3.8", ["a==1"])
    assert pkg.install_commands[-1] == "pip install --no-deps ."


# --- time machine end to end ---------------------------------------------------

REQS = "fire>=0.1.3\nregex==2017.4.5\n"
GCC_LOG = "  error: command 'gcc' failed: No such file or directory\n"


class _Chat:
    def __init__(self, responses):
        self._responses = list(responses)
        self.prompts = []

    def chat_completion(self, **kwargs):
        self.prompts.append(kwargs)
        return self._responses.pop(0)


class _Sandbox:
    """Fails until the plan is the era plan (python 3.7 + tensorflow 1.13.1 + a compiler)."""

    def __init__(self):
        self.calls = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        steps = " ".join(kwargs["install_commands"])
        if kwargs["base_image"] == "python:3.7-slim" and "tensorflow==1.13.1" in steps and "build-essential" in steps:
            return SandboxRunResult(steps=(StepResult("python gen.py", 0, "ok", "", 1.0, 0.0),))
        return SandboxRunResult(steps=(StepResult("pip install -r requirements.txt", 1, "", GCC_LOG, 1.0, 0.0),))


def _run_tm(tmp_path, lock_compiler, repair_responses=()):
    repo = _git_repo(tmp_path, {"requirements.txt": REQS, "gen.py": "import tensorflow as tf\nimport regex\n"})
    intake = RepoIntake(repo, "a" * 40, {"requirements.txt": REQS}, frozenset({"fire", "regex"}), (), ("gen.py",), None)
    sandbox = _Sandbox()
    deps = PipelineDeps(
        recon_client=_Chat([json.dumps({"entrypoint": "gen.py", "confidence": 0.9})]),
        recon_model="r",
        repair_client=_Chat([json.dumps(r) for r in repair_responses]),
        repair_model="p",
        adjudicator_client=None,
        adjudicator_model=None,
        sandbox_api_key="k",
        sandbox_wall_clock_seconds=60,
        sandbox_runner=sandbox,
        max_attempts=max(1, len(repair_responses)),
        http_get=FakeHttp({f"https://api.github.com/repos/openai/gpt-2/commits?path=requirements.txt": _commit("2019-03-04")}),
        lock_compiler=lock_compiler,
    )
    result = run_pipeline(repo_url=REPO, commit_sha="a" * 40, workdir=repo, intake_result=intake, deps=deps,
                          cost_guard=CostGuard(daily_cost_ceiling_usd=100), run_id="tm")
    return result, sandbox


def test_time_machine_repairs_an_era_environment_as_attempt_zero(tmp_path):
    seen = {}

    def fake_lock(reqs, extra, era, py):
        seen.update(reqs=reqs, extra=extra, era=era, py=py)
        return LockResult(True, ("fire==0.1.3", "regex==2017.4.5", "tensorflow==1.13.1"), tuple(reqs) + tuple(extra))

    result, sandbox = _run_tm(tmp_path, fake_lock)
    assert result.verdict == "RUNS_AFTER_REPAIR", result.full_log
    assert seen == {"reqs": ["fire>=0.1.3", "regex==2017.4.5"], "extra": ["tensorflow"], "era": date(2019, 3, 4), "py": "3.7"}
    (tm,) = result.attempts
    assert (tm.attempt_number, tm.origin, tm.gate_decision, tm.exit_code) == (0, "time_machine", "PASS", 0)
    rec = tm.time_machine
    assert rec["era"] == {"date": "2019-03-04", "source": "dependency-files", "detail": {"requirements.txt": "2019-03-04"}}
    assert rec["python"]["version"] == "3.7" and "devguide.python.org" in rec["python"]["source"]
    assert rec["apt_added"] == ["build-essential"]
    assert "[era] 2019-03-04 from dependency-files" in result.full_log
    assert len(sandbox.calls) == 2  # baseline + era re-execution; no model repair needed


def test_time_machine_failure_to_lock_falls_through_to_model_repair(tmp_path):
    fail = lambda *a: LockResult(False, (), (), (), "uv pip compile", "error: Failed to build `fire`")
    result, _ = _run_tm(tmp_path, fail, [{"code_diff": None, "env_delta": [], "explanation": "cannot fix"}])
    assert result.attempts[0].origin == "time_machine" and result.attempts[0].gate_decision == "DECLINED"
    assert "Failed to build" in result.attempts[0].time_machine["lock"]["error"]
    assert result.verdict == "BLOCKED"


# --- c) source search whenever PyPI says the package does not exist ---------------


class FakeTavily:
    def __init__(self, results, github_results=None):
        self.results, self.github_results, self.queries = results, github_results, []

    def search(self, query, *, max_results, search_depth, include_domains=None):
        self.queries.append(query + (" [github]" if include_domains else ""))
        if include_domains is not None and self.github_results is not None:
            return {"results": self.github_results}
        return {"results": self.results}


DASSL_REPO = [{"title": "Dassl", "url": "https://github.com/KaiyangZhou/Dassl.pytorch", "content": ""}]
GH = {
    "https://api.github.com/repos/KaiyangZhou/Dassl.pytorch/commits": (
        200, [{"sha": "c61a1b570ac6333bd50fb5ae06aea59002fb20bb", "commit": {"committer": {"date": "2022-10-06T00:00:00Z"}}}]
    ),
    "https://api.github.com/repos/KaiyangZhou/Dassl.pytorch": (200, {"language": "Python"}),
}


def test_c_missing_import_of_a_non_pypi_package_triggers_source_search():
    """TTPT v3: `dassl` surfaced as ModuleNotFoundError (DEP_MISSING)."""
    tav = FakeTavily([{"title": "blog", "url": "https://blog.example/x", "content": ""}], github_results=DASSL_REPO)
    res = resolve(tav, TaxonomyCode.DEP_MISSING, "ModuleNotFoundError: No module named 'dassl'", date(2024, 8, 30),
                  http_get=FakeHttp(GH))  # pypi.org/pypi/dassl/json -> 404
    assert res.pypi_status == "not on PyPI"
    assert tav.queries == ["dassl python package source code github repository pip install", "dassl github repository [github]"]
    assert [s.url for s in res.git_sources] == ["https://github.com/KaiyangZhou/Dassl.pytorch"]


def test_c_negative_control_a_package_on_pypi_gets_the_version_query():
    tav = FakeTavily([])
    pypi = {"https://pypi.org/pypi/numpy/json": (200, {"releases": {"1.16.2": [{"upload_time_iso_8601": "2019-02-26", "python_version": "cp37"}]}})}
    res = resolve(tav, TaxonomyCode.DEP_MISSING, "ModuleNotFoundError: No module named 'numpy'", date(2019, 3, 4), http_get=FakeHttp(pypi))
    assert tav.queries == ["numpy python package version compatible 2019 release history"]
    assert res.git_sources == ()


# --- d) only sources used in a decision are cited -------------------------------

SHA = "c61a1b570ac6333bd50fb5ae06aea59002fb20bb"
NOT_ON_PYPI = "ERROR: Could not find a version that satisfies the requirement dassl (from versions: none)\n"


class _DasslSandbox:
    def __init__(self):
        self.calls = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        if any(f"Dassl.pytorch@{SHA}" in c for c in kwargs["install_commands"]):
            return SandboxRunResult(steps=(StepResult("python train.py", 0, "ok", "", 1.0, 0.0),))
        return SandboxRunResult(steps=(StepResult("pip install", 1, "", NOT_ON_PYPI, 1.0, 0.0),))


def _run_cite(tmp_path, responses):
    (tmp_path / "requirements.txt").write_text("dassl\n", encoding="utf-8")
    (tmp_path / "train.py").write_text("import dassl\n", encoding="utf-8")
    intake = RepoIntake(tmp_path, "a" * 40, {"requirements.txt": "dassl\n"}, frozenset({"dassl"}), (), ("train.py",), None)
    tav = FakeTavily(DASSL_REPO + [{"title": "unused blog", "url": "https://blog.example/unused", "content": ""}])
    deps = PipelineDeps(
        recon_client=_Chat([json.dumps({"entrypoint": "train.py", "confidence": 0.9})]), recon_model="r",
        repair_client=_Chat([json.dumps(r) for r in responses]), repair_model="p",
        adjudicator_client=None, adjudicator_model=None, sandbox_api_key="k", sandbox_wall_clock_seconds=60,
        sandbox_runner=_DasslSandbox(), max_attempts=1, tavily_client=tav, http_get=FakeHttp(GH),
        lock_compiler=lambda *a: LockResult(False, (), (), (), "", "skipped in test"),
    )
    return run_pipeline(repo_url="https://example.com/ttpt", commit_sha="a" * 40, workdir=tmp_path, intake_result=intake,
                        deps=deps, cost_guard=CostGuard(daily_cost_ceiling_usd=100), run_id="cite")


PIP_GIT = {"code_diff": None, "env_delta": [{"op": "pip_git", "package": "dassl", "git_url": "https://github.com/KaiyangZhou/Dassl.pytorch",
           "commit": SHA, "justification": "Dassl is GitHub-only", "evidence": "requirement dassl (from versions: none)"}],
           "explanation": "install from verified source"}


def test_d_only_the_sources_used_are_cited_the_rest_is_logged(tmp_path):
    result = _run_cite(tmp_path, [PIP_GIT])
    assert result.verdict == "RUNS_AFTER_REPAIR", result.full_log
    attempt = [a for a in result.attempts if a.origin == "model"][0]
    assert [t["url"] for t in attempt.tavily_sources] == ["https://github.com/KaiyangZhou/Dassl.pytorch"]
    assert [(s["kind"], s["commit"]) for s in attempt.resolved_sources] == [("git", SHA)]
    assert "[citations] not cited (not used in a decision): https://blog.example/unused" in result.full_log


def test_d_a_declined_attempt_cites_nothing(tmp_path):
    result = _run_cite(tmp_path, [{"code_diff": None, "env_delta": [], "explanation": "no"}])
    attempt = [a for a in result.attempts if a.origin == "model"][0]
    assert attempt.tavily_sources == () and attempt.resolved_sources == ()
    assert "not cited (not used in a decision): https://github.com/KaiyangZhou/Dassl.pytorch" in result.full_log


# --- e) missing justification: one re-ask, no attempt consumed -----------------


def test_e_missing_justification_is_re_asked_within_the_same_attempt(tmp_path):
    unjustified = json.loads(json.dumps(PIP_GIT))
    unjustified["env_delta"][0]["justification"] = ""
    unjustified["env_delta"][0]["evidence"] = ""
    result = _run_cite(tmp_path, [unjustified, PIP_GIT])  # max_attempts=1
    assert result.verdict == "RUNS_AFTER_REPAIR", result.full_log
    assert len([a for a in result.attempts if a.origin == "model"]) == 1
    assert "re-asked once (same attempt)" in result.full_log


# --- f) .env duplicate keys differing only by case ------------------------------


def test_f_duplicate_env_key_by_case_refuses_to_start(tmp_path):
    env = tmp_path / ".env"
    env.write_text("A=1\nTavily_API_Key= tvly-SECRETVALUE\nB=2\nTAVILY_API_KEY=\n", encoding="utf-8")
    with pytest.raises(DuplicateEnvKeyError) as excinfo:
        check_env_file_duplicates(env)
    message = str(excinfo.value)
    assert "'TAVILY_API_KEY' on line 4" in message and "'Tavily_API_Key' on line 2" in message
    assert "SECRETVALUE" not in message and "tvly" not in message


def test_f_negative_control_distinct_keys_and_comments_are_fine(tmp_path):
    env = tmp_path / ".env"
    env.write_text("# TAVILY_API_KEY=old\nTAVILY_API_KEY=x\nNEBIUS_API_KEY=y\n\nexport OTHER=1\n", encoding="utf-8")
    check_env_file_duplicates(env)
    check_env_file_duplicates(tmp_path / "missing.env")


def test_f_get_settings_runs_the_check(monkeypatch, tmp_path):
    from app import config

    env = tmp_path / ".env"
    env.write_text("X=1\nx=2\n", encoding="utf-8")
    monkeypatch.setattr(config, "_REPO_ROOT_ENV_FILE", env)
    config._checked_env_file.cache_clear()
    config.get_settings.cache_clear()
    try:
        with pytest.raises(DuplicateEnvKeyError):
            config.get_settings()
    finally:
        config._checked_env_file.cache_clear()
        config.get_settings.cache_clear()
