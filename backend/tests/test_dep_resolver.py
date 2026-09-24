"""Dependency resolver: Tavily finds candidates, RERUN verifies them (GitHub
commit, PyPI history) — fake Tavily client and fake HTTP, no network."""

from __future__ import annotations

import json
from datetime import date

import pytest

from app.services import dep_resolver
from app.services.classifier import TaxonomyCode
from app.services.cost_guard import CostGuard
from app.services.dep_resolver import package_from_evidence, resolve
from app.services.env_repair import EnvRule
from app.services.intake import RepoIntake
from app.services.orchestrator import PipelineDeps, run_pipeline
from app.services.passport import verify_certificate
from app.services.sandbox import SandboxRunResult, StepResult

DASSL_SHA = "c4d3e9f1a2b3c4d5e6f708192a3b4c5d6e7f8091"
REPO_DATE = date(2023, 8, 1)
NOT_ON_PYPI_LINE = "ERROR: Could not find a version that satisfies the requirement dassl (from versions: none)"


class FakeTavily:
    def __init__(self, results, github_results=None):
        self.results = results
        self.github_results = github_results
        self.queries: list[str] = []

    def search(self, query, *, max_results, search_depth, include_domains=None):
        self.queries.append(query if not include_domains else f"{query} [{','.join(include_domains)}]")
        if include_domains is not None and self.github_results is not None:
            return {"results": self.github_results}
        return {"results": self.results}


DASSL_RESULTS = [
    {
        "title": "KaiyangZhou/Dassl.pytorch: A PyTorch toolbox for domain generalization",
        "url": "https://github.com/KaiyangZhou/Dassl.pytorch",
        "content": "Install: git clone https://github.com/KaiyangZhou/Dassl.pytorch.git && pip install -r requirements.txt",
    },
    {"title": "GitHub", "url": "https://github.com/features", "content": "unrelated"},
    {"title": "fork", "url": "https://example.org/blog", "content": "see github.com/someone/unrelated-tool"},
]


class FakeHttp:
    """GitHub + PyPI JSON, recorded."""

    def __init__(self, routes):
        self.routes = routes
        self.calls: list[str] = []

    def __call__(self, url):
        self.calls.append(url)
        for prefix, response in self.routes.items():
            if url.startswith(prefix):
                return response
        return 404, None


GITHUB_DASSL = {
    "https://api.github.com/repos/KaiyangZhou/Dassl.pytorch/commits": (
        200,
        [{"sha": DASSL_SHA, "commit": {"committer": {"date": "2023-07-20T10:00:00Z"}}}],
    ),
    "https://api.github.com/repos/KaiyangZhou/Dassl.pytorch": (200, {"language": "Python"}),
}


# --- package extraction -----------------------------------------------------


@pytest.mark.parametrize(
    "evidence,package",
    [
        ("ERROR: Could not find a version that satisfies the requirement dassl (from versions: none)", "dassl"),
        ("ERROR: No matching distribution found for ancient-pkg==0.0.1", "ancient-pkg"),
        ("ModuleNotFoundError: No module named 'tensorflow.contrib'", "tensorflow"),
        ("ModuleNotFoundError: No module named 'sklearn'", "scikit-learn"),
        ("ModuleNotFoundError: No module named 'cv2'", "opencv-python"),
    ],
)
def test_package_from_evidence(evidence, package):
    assert package_from_evidence(evidence) == package


def test_package_from_evidence_negative_control():
    assert package_from_evidence("ZeroDivisionError: division by zero") is None


# --- resolve ----------------------------------------------------------------


def test_not_on_pypi_finds_and_verifies_the_real_git_source():
    tav = FakeTavily(DASSL_RESULTS)
    http = FakeHttp(GITHUB_DASSL)
    res = resolve(
        tav,
        TaxonomyCode.DEP_NOT_ON_PYPI,
        "ERROR: Could not find a version that satisfies the requirement dassl (from versions: none)",
        REPO_DATE,
        http_get=http,
    )
    assert tav.queries == ["dassl python package source code github repository pip install"]
    assert [s.url for s in res.git_sources] == ["https://github.com/KaiyangZhou/Dassl.pytorch"]
    assert res.git_sources[0].commit == DASSL_SHA
    assert res.git_sources[0].cited_by == "https://github.com/KaiyangZhou/Dassl.pytorch"
    assert res.verified_git_pairs == {("https://github.com/kaiyangzhou/dassl.pytorch", DASSL_SHA)}
    # The commit was looked up as of the repo's own date.
    assert any("until=2023-08-01T23:59:59Z" in c for c in http.calls)
    # Unrelated / non-matching GitHub links were never verified.
    assert not any("unrelated-tool" in c or "/features" in c for c in http.calls)
    assert res.pypi_status == "not on PyPI"
    ctx = res.as_prompt_context()
    assert f"git_url=https://github.com/KaiyangZhou/Dassl.pytorch commit={DASSL_SHA}" in ctx
    assert "https://github.com/KaiyangZhou/Dassl.pytorch" in ctx  # the Tavily citation


def test_candidate_that_github_cannot_resolve_is_never_offered():
    res = resolve(
        FakeTavily(DASSL_RESULTS),
        TaxonomyCode.DEP_NOT_ON_PYPI,
        NOT_ON_PYPI_LINE,
        REPO_DATE,
        http_get=FakeHttp({}),  # every GitHub/PyPI call 404s
    )
    assert res.git_sources == ()
    assert res.verified_git_pairs == frozenset()
    assert "do not propose a pip_git change" in res.as_prompt_context()


def test_source_repo_newer_than_the_paper_falls_back_to_latest_and_says_so():
    http = FakeHttp(
        {
            "https://api.github.com/repos/KaiyangZhou/Dassl.pytorch/commits?per_page=1&until": (200, []),
            "https://api.github.com/repos/KaiyangZhou/Dassl.pytorch/commits?per_page=1": (
                200,
                [{"sha": DASSL_SHA, "commit": {"committer": {"date": "2024-01-01T00:00:00Z"}}}],
            ),
            "https://api.github.com/repos/KaiyangZhou/Dassl.pytorch": (200, {"language": "Python"}),
            "https://api.github.com/repos/KaiyangZhou/Dassl.pytorch/commits?per_page=1": (
                200,
                [{"sha": DASSL_SHA, "commit": {"committer": {"date": "2024-01-01T00:00:00Z"}}}],
            ),
        }
    )
    res = resolve(FakeTavily(DASSL_RESULTS), TaxonomyCode.DEP_NOT_ON_PYPI, NOT_ON_PYPI_LINE, REPO_DATE, http_get=http)
    assert res.git_sources[0].commit == DASSL_SHA
    assert "latest commit used" in res.git_sources[0].note


PYPI_TF = {
    "releases": {
        "1.13.1": [{"upload_time_iso_8601": "2019-02-26T00:00:00Z", "python_version": "cp36", "yanked": False},
                   {"upload_time_iso_8601": "2019-02-26T00:00:00Z", "python_version": "cp37", "yanked": False}],
        "1.14.0": [{"upload_time_iso_8601": "2019-06-18T00:00:00Z", "python_version": "cp37", "yanked": False}],
        "2.0.0": [{"upload_time_iso_8601": "2019-09-30T00:00:00Z", "python_version": "cp37", "yanked": False}],
        "2.16.1": [{"upload_time_iso_8601": "2024-03-08T00:00:00Z", "python_version": "cp311", "yanked": False}],
        "1.12.9": [{"upload_time_iso_8601": "2019-01-01T00:00:00Z", "python_version": "cp36", "yanked": True}],
    }
}


def test_missing_module_gets_era_versions_from_pypi_history():
    tav = FakeTavily([{"title": "TF 1.x", "url": "https://www.tensorflow.org/versions", "content": "tf.contrib removed in 2.0"}])
    http = FakeHttp({"https://pypi.org/pypi/tensorflow/json": (200, PYPI_TF)})
    res = resolve(
        tav,
        TaxonomyCode.DEP_MISSING,
        "ModuleNotFoundError: No module named 'tensorflow.contrib'",
        date(2019, 8, 1),
        http_get=http,
    )
    assert tav.queries == ["tensorflow python package version compatible 2019 release history"]
    versions = [r.version for r in res.pypi_releases]
    # Newest-first releases on/before the repo date, then the latest overall;
    # yanked releases are excluded.
    assert versions == ["1.14.0", "1.13.1", "2.16.1"]
    assert res.pypi_releases[1].cpython_tags == ("cp36", "cp37")
    assert "1.12.9" not in res.as_prompt_context()


def test_non_dependency_codes_are_not_resolved():
    assert resolve(FakeTavily([]), TaxonomyCode.RUNTIME_ERROR_OTHER, "No module named 'x'", REPO_DATE, http_get=FakeHttp({})) is None


def test_tavily_outage_degrades_without_crashing():
    class Down:
        def search(self, *a, **k):
            raise RuntimeError("503")

    res = resolve(Down(), TaxonomyCode.DEP_NOT_ON_PYPI, NOT_ON_PYPI_LINE, REPO_DATE, http_get=FakeHttp({}))
    assert res.git_sources == () and any("Tavily search failed" in n for n in res.notes)


def test_real_http_is_blocked_in_the_unit_suite():
    with pytest.raises(RuntimeError, match="disabled in tests"):
        dep_resolver._default_http_get("https://pypi.org/pypi/x/json")


# --- end to end: the TTPT scenario ------------------------------------------

NOT_ON_PYPI_LOG = "ERROR: Could not find a version that satisfies the requirement dassl (from versions: none)\nERROR: No matching distribution found for dassl\n"


class _Chat:
    def __init__(self, responses):
        self._responses = list(responses)
        self.prompts = []

    def chat_completion(self, **kwargs):
        self.prompts.append(kwargs)
        return self._responses.pop(0)


class _Sandbox:
    """Install fails until the plan installs Dassl from the verified commit."""

    def __init__(self):
        self.calls = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        if any(f"Dassl.pytorch@{DASSL_SHA}" in c for c in kwargs["install_commands"]):
            return SandboxRunResult(steps=(StepResult("python train.py", 0, "ok", "", 1.0, 0.0),))
        return SandboxRunResult(steps=(StepResult("pip install -r requirements.txt", 1, "", NOT_ON_PYPI_LOG, 1.0, 0.0),))


def _pip_git(commit):
    return {
        "code_diff": None,
        "env_delta": [
            {
                "op": "pip_git",
                "package": "dassl",
                "git_url": "https://github.com/KaiyangZhou/Dassl.pytorch",
                "commit": commit,
                "justification": "Dassl is GitHub-only; install the verified commit",
                "evidence": "requirement dassl (from versions: none)",
            }
        ],
        "explanation": "install dassl from its verified source",
    }


def _run(tmp_path, repair_responses):
    (tmp_path / "requirements.txt").write_text("ftfy==6.1.1\nregex\ntqdm\ndassl\n", encoding="utf-8")
    (tmp_path / "train.py").write_text("import dassl\n", encoding="utf-8")
    intake = RepoIntake(
        tmp_path, "a" * 40, {"requirements.txt": "ftfy==6.1.1\nregex\ntqdm\ndassl\n"},
        frozenset({"ftfy", "regex", "tqdm", "dassl"}), (), ("train.py",), None,
    )
    sandbox = _Sandbox()
    repair = _Chat([json.dumps(r) for r in repair_responses])
    deps = PipelineDeps(
        recon_client=_Chat([json.dumps({"entrypoint": "train.py", "confidence": 0.9})]),
        recon_model="r",
        repair_client=repair,
        repair_model="p",
        adjudicator_client=None,
        adjudicator_model=None,
        sandbox_api_key="k",
        sandbox_wall_clock_seconds=60,
        sandbox_runner=sandbox,
        max_attempts=len(repair_responses),
        tavily_client=FakeTavily(DASSL_RESULTS),
        http_get=FakeHttp(GITHUB_DASSL),
    )
    result = run_pipeline(
        repo_url="https://example.com/ttpt", commit_sha="a" * 40, workdir=tmp_path, intake_result=intake,
        deps=deps, cost_guard=CostGuard(daily_cost_ceiling_usd=100), run_id="resolver",
    )
    return result, sandbox, repair


def test_verified_git_source_repairs_a_not_on_pypi_failure_end_to_end(tmp_path):
    result, sandbox, repair = _run(tmp_path, [_pip_git(DASSL_SHA)])
    assert result.verdict == "RUNS_AFTER_REPAIR", result.full_log
    attempt = result.attempts[0]
    assert attempt.gate_decision == "PASS"
    # The certificate lists the Tavily citation and the verified source.
    assert "https://github.com/KaiyangZhou/Dassl.pytorch" in {s["url"] for s in attempt.tavily_sources}
    git = [s for s in attempt.resolved_sources if s["kind"] == "git"]
    assert git == [
        {
            "kind": "git",
            "url": "https://github.com/KaiyangZhou/Dassl.pytorch",
            "commit": DASSL_SHA,
            "committed_at": "2023-07-20",
            "cited_by": "https://github.com/KaiyangZhou/Dassl.pytorch",
            "note": "",
            "commit_url": f"https://github.com/KaiyangZhou/Dassl.pytorch/commit/{DASSL_SHA}",
        }
    ]
    assert "RERUN-VERIFIED git sources" in repair.prompts[0]["user_prompt"]
    cert = {
        "repo_url": result.repo_url, "commit_sha": result.commit_sha, "build_plan": result.build_plan or {},
        "full_log": result.full_log, "diffs": [a.as_dict() for a in result.attempts], "verdict": result.verdict,
        "timestamp": result.timestamp, "reproduction_passport_hash": result.reproduction_passport_hash,
    }
    assert verify_certificate(cert)
    cert["diffs"][0]["resolved_sources"][0]["commit"] = "0" * 40
    assert not verify_certificate(cert)


def test_invented_commit_for_the_right_repo_is_rejected_end_to_end(tmp_path):
    result, sandbox, _ = _run(tmp_path, [_pip_git("d" * 40)])
    assert result.verdict == "BLOCKED"
    assert result.attempts[0].gate_decision == "REJECT"
    assert EnvRule.ENV_GIT_UNVERIFIED in {v["rule"] for v in result.attempts[0].gate_violations}
    assert len(sandbox.calls) == 1


def test_not_on_pypi_retries_restricted_to_github_when_no_repo_was_cited():
    """Live finding (dassl): the general query cited a Hugging Face mirror and
    blogs, never the GitHub repo. A github.com-only query finds it."""
    general = [{"title": "mirror", "url": "https://huggingface.co/x/blame/main/Dassl.pytorch/README.md", "content": "Dassl"}]
    tav = FakeTavily(general, github_results=DASSL_RESULTS[:1])
    res = resolve(tav, TaxonomyCode.DEP_NOT_ON_PYPI, NOT_ON_PYPI_LINE, REPO_DATE, http_get=FakeHttp(GITHUB_DASSL))
    assert tav.queries == [
        "dassl python package source code github repository pip install",
        "dassl github repository [github.com]",
    ]
    assert [s.url for s in res.git_sources] == ["https://github.com/KaiyangZhou/Dassl.pytorch"]
    assert "(github.com only)" in res.context.query
    assert {s.url for s in res.context.sources} >= {general[0]["url"], DASSL_RESULTS[0]["url"]}


def test_negative_control_no_github_retry_when_the_first_query_already_cited_the_repo():
    tav = FakeTavily(DASSL_RESULTS, github_results=[])
    resolve(tav, TaxonomyCode.DEP_NOT_ON_PYPI, NOT_ON_PYPI_LINE, REPO_DATE, http_get=FakeHttp(GITHUB_DASSL))
    assert len(tav.queries) == 1


def test_latest_overall_is_the_latest_stable_not_a_prerelease():
    rel = dict(PYPI_TF["releases"])
    rel["2.22.0rc0"] = [{"upload_time_iso_8601": "2026-09-22T00:00:00Z", "python_version": "cp313"}]
    res = resolve(FakeTavily([]), TaxonomyCode.DEP_MISSING, "No module named 'tensorflow'", date(2019, 8, 1),
                  http_get=FakeHttp({"https://pypi.org/pypi/tensorflow/json": (200, {"releases": rel})}))
    assert [r.version for r in res.pypi_releases] == ["1.14.0", "1.13.1", "2.16.1"]


def test_non_python_repo_matching_the_name_is_not_offered():
    """Live finding: 'dassl' also matched SciML/DASSL.jl (Julia)."""
    results = DASSL_RESULTS[:1] + [{"title": "DASSL.jl", "url": "https://github.com/SciML/DASSL.jl", "content": ""}]
    http = FakeHttp(dict(GITHUB_DASSL, **{
        "https://api.github.com/repos/SciML/DASSL.jl/commits": (200, [{"sha": "e" * 40, "commit": {"committer": {"date": "2024-07-29"}}}]),
        "https://api.github.com/repos/SciML/DASSL.jl": (200, {"language": "Julia"}),
    }))
    res = resolve(FakeTavily(results), TaxonomyCode.DEP_NOT_ON_PYPI, NOT_ON_PYPI_LINE, REPO_DATE, http_get=http)
    assert [s.url for s in res.git_sources] == ["https://github.com/KaiyangZhou/Dassl.pytorch"]
