"""Dependency resolver: Tavily finds a package's real source and the versions
that fit the repo's era; RERUN verifies what it found before the repairer may
use it.

Runs for dependency-family failures (DEP_NOT_ON_PYPI, DEP_YANKED,
DEP_UNPINNED_CONFLICT, DEP_MISSING). The 2026-09-24 live runs showed what
the env layer lacked: TTPT needs Dassl, which is GitHub-only, and gpt-2 needs
TensorFlow 1.x, not whatever `pip install tensorflow` resolves to today.

Three sources, kept separate on purpose:
  1. Tavily search (cited on the certificate) — finds candidate source repos
     and version/compatibility discussion around the repo's commit date.
  2. GitHub API — a candidate repo named in the Tavily results is only
     offered to the repairer after RERUN resolves it to a real commit on or
     before the repo's own commit date. The env gate accepts a `pip_git`
     change ONLY for a (url, commit) pair verified here, so the model can
     never pin an invented URL or sha.
  3. PyPI JSON API — the package's real release history (upload dates,
     yanked flags, CPython wheel tags), so a version "around the paper's
     date" is a checked fact, not a guess.

Every network failure degrades to "no verified source" — never a crash and
never a fabricated one.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Callable

from app.services import tavily
from app.services.classifier import TaxonomyCode

RESOLVER_CODES = frozenset(
    {
        TaxonomyCode.DEP_NOT_ON_PYPI,
        TaxonomyCode.DEP_YANKED,
        TaxonomyCode.DEP_UNPINNED_CONFLICT,
        TaxonomyCode.DEP_MISSING,
    }
)

# Import name -> distribution name, where they differ.
_IMPORT_TO_DIST = {
    "sklearn": "scikit-learn",
    "cv2": "opencv-python",
    "yaml": "pyyaml",
    "PIL": "pillow",
    "bs4": "beautifulsoup4",
}

_PKG_PATTERNS = (
    re.compile(r"No module named '([A-Za-z0-9_.]+)'"),
    re.compile(r"satisfies the requirement ([A-Za-z0-9][A-Za-z0-9._-]*)"),
    re.compile(r"No matching distribution found for ([A-Za-z0-9][A-Za-z0-9._-]*)"),
    re.compile(r"yanked version: '?([A-Za-z0-9][A-Za-z0-9._-]*)"),
    re.compile(r"Cannot install ([A-Za-z0-9][A-Za-z0-9._-]*)"),
)
_GITHUB_REPO_RE = re.compile(r"github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)", re.IGNORECASE)
_NOT_REPO_OWNERS = {"orgs", "topics", "features", "about", "marketplace", "sponsors", "settings", "login", "search"}

_PRERELEASE_RE = re.compile(r"(a|b|rc|dev)\d*$|\.dev", re.IGNORECASE)

HttpGet = Callable[[str], "tuple[int, object]"]


def package_from_evidence(evidence: str) -> str | None:
    """The package/module a dependency failure is about, from the evidence
    line (full lines since 2026-09-24). Version specifiers are stripped."""
    for pattern in _PKG_PATTERNS:
        match = pattern.search(evidence or "")
        if match:
            name = re.split(r"[<>=!~;\[ ]", match.group(1), maxsplit=1)[0].rstrip(".")
            top = name.split(".")[0] if "No module named" in pattern.pattern else name
            return _IMPORT_TO_DIST.get(top, top)
    return None


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def repo_commit_date(workdir: Path) -> date | None:
    """Committer date of the checked-out commit (the repo's own era)."""
    try:
        out = subprocess.run(
            ["git", "-C", str(workdir), "log", "-1", "--format=%cs"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        return date.fromisoformat(out.stdout.strip()) if out.returncode == 0 and out.stdout.strip() else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def _default_http_get(url: str) -> tuple[int, object]:
    import httpx

    response = httpx.get(url, timeout=15, headers={"Accept": "application/json", "User-Agent": "rerun-dep-resolver"})
    try:
        return response.status_code, response.json()
    except ValueError:
        return response.status_code, None


@dataclass(frozen=True)
class VerifiedGitSource:
    url: str  # https://github.com/<owner>/<repo>
    commit: str  # full 40-hex sha
    committed_at: str
    cited_by: str  # the Tavily result URL it was found in
    note: str = ""

    def as_dict(self) -> dict:
        return {
            "kind": "git",
            "url": self.url,
            "commit": self.commit,
            "committed_at": self.committed_at,
            "cited_by": self.cited_by,
            "note": self.note,
            "commit_url": f"{self.url}/commit/{self.commit}",
        }


@dataclass(frozen=True)
class PypiRelease:
    version: str
    uploaded: str
    cpython_tags: tuple[str, ...]

    def as_dict(self, package: str) -> dict:
        return {
            "kind": "pypi",
            "package": package,
            "version": self.version,
            "uploaded": self.uploaded,
            "cpython_tags": list(self.cpython_tags),
            "url": f"https://pypi.org/project/{package}/{self.version}/",
        }


@dataclass(frozen=True)
class Resolution:
    package: str | None
    repo_date: date | None
    context: tavily.TavilyContext
    git_sources: tuple[VerifiedGitSource, ...] = ()
    pypi_package: str | None = None
    pypi_releases: tuple[PypiRelease, ...] = ()
    pypi_status: str = ""  # "found", "not on PyPI", "lookup failed"
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def verified_git_pairs(self) -> frozenset[tuple[str, str]]:
        return frozenset((s.url.lower(), s.commit) for s in self.git_sources)

    def resolved_sources(self) -> tuple[dict, ...]:
        return tuple(s.as_dict() for s in self.git_sources) + tuple(
            r.as_dict(self.pypi_package or self.package or "") for r in self.pypi_releases
        )

    def as_prompt_context(self) -> str:
        parts = []
        era = self.repo_date.isoformat() if self.repo_date else "unknown"
        parts.append(f"Dependency resolution for '{self.package}' (repository commit date: {era}).")
        if self.git_sources:
            parts.append(
                "RERUN-VERIFIED git sources — the ONLY url+commit pairs a pip_git change may use "
                "(each resolved by RERUN to a real commit on or before the repository's date):"
            )
            for s in self.git_sources:
                parts.append(f"- git_url={s.url} commit={s.commit} (committed {s.committed_at}; cited by {s.cited_by}) {s.note}")
        else:
            parts.append("No verified git source was found — do not propose a pip_git change.")
        if self.pypi_releases:
            parts.append(
                f"PyPI release history for '{self.pypi_package}' (verified from pypi.org; newest first, "
                "releases on/before the repository date, then the latest overall). Prefer a version from "
                "the repository's era; if its wheels only cover older CPython (cpython_tags), also change "
                "the python version:"
            )
            for r in self.pypi_releases:
                parts.append(f"- {r.version} uploaded {r.uploaded} cpython={','.join(r.cpython_tags) or 'sdist/any'}")
        elif self.pypi_status:
            parts.append(f"PyPI lookup for '{self.pypi_package or self.package}': {self.pypi_status}.")
        tavily_text = self.context.as_prompt_context()
        if tavily_text:
            parts.append(tavily_text)
        return "\n".join(parts)


def build_query(code: str, package: str, repo_date: date | None) -> str:
    """Deterministic, explainable query (shown next to its citations)."""
    year = f" {repo_date.year}" if repo_date else ""
    if code == TaxonomyCode.DEP_NOT_ON_PYPI:
        return f"{package} python package source code github repository pip install"
    return f"{package} python package version compatible{year} release history"


def _verify_github(owner: str, repo: str, repo_date: date | None, cited_by: str, http_get: HttpGet) -> VerifiedGitSource | None:
    base = f"https://api.github.com/repos/{owner}/{repo}"
    # Found live: "dassl" also matched SciML/DASSL.jl, a Julia package. Only
    # a repo GitHub reports as Python can be a pip source.
    status, meta = http_get(base)
    if status != 200 or not isinstance(meta, dict) or (meta.get("language") or "") != "Python":
        return None
    until = f"&until={repo_date.isoformat()}T23:59:59Z" if repo_date else ""
    status, body = http_get(f"{base}/commits?per_page=1{until}")
    note = ""
    if status == 200 and isinstance(body, list) and not body and repo_date:
        # The source repo has no commit before the paper repo's date (it
        # was created later): fall back to its latest commit, and say so.
        status, body = http_get(f"{base}/commits?per_page=1")
        note = "(no commit before the repository date existed; latest commit used)"
    if status != 200 or not isinstance(body, list) or not body:
        return None
    sha = str(body[0].get("sha", ""))
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        return None
    committed = str(((body[0].get("commit") or {}).get("committer") or {}).get("date", ""))[:10]
    return VerifiedGitSource(url=f"https://github.com/{owner}/{repo}", commit=sha, committed_at=committed, cited_by=cited_by, note=note)


def _pypi_releases(package: str, repo_date: date | None, http_get: HttpGet) -> tuple[str, tuple[PypiRelease, ...]]:
    status, body = http_get(f"https://pypi.org/pypi/{package}/json")
    if status == 404:
        return "not on PyPI", ()
    if status != 200 or not isinstance(body, dict):
        return "lookup failed", ()
    releases = []
    for version, files in (body.get("releases") or {}).items():
        live = [f for f in files or [] if not f.get("yanked")]
        if not live:
            continue
        uploaded = min(str(f.get("upload_time_iso_8601") or f.get("upload_time") or "")[:10] for f in live)
        tags = sorted({m.group(0) for f in live for m in [re.search(r"cp3\d+", str(f.get("python_version", "")))] if m})
        releases.append(PypiRelease(version=version, uploaded=uploaded, cpython_tags=tuple(tags)))
    releases.sort(key=lambda r: r.uploaded, reverse=True)
    stable = [r for r in releases if not _PRERELEASE_RE.search(r.version)]
    chosen: list[PypiRelease] = []
    if repo_date:
        chosen.extend([r for r in stable if r.uploaded and r.uploaded <= repo_date.isoformat()][:5])
    # Latest STABLE overall (found live: the newest tensorflow upload was 2.22.0rc0).
    if stable and stable[0] not in chosen:
        chosen.append(stable[0])
    return "found", tuple(chosen)


def _search(client, query: str, **extra) -> tavily.TavilyContext:
    response = client.search(query, max_results=5, search_depth="basic", **extra)
    return tavily.TavilyContext(
        query=query,
        sources=tuple(
            tavily.TavilySource(title=str(r.get("title", "")), url=str(r.get("url", "")), content=str(r.get("content", "")))
            for r in response.get("results", [])
        ),
    )


def _github_candidates(context: tavily.TavilyContext, package: str) -> list[tuple[str, str, str]]:
    """(owner, repo, cited_by) for GitHub repos named in the cited results
    whose name matches the package (e.g. dassl -> KaiyangZhou/Dassl.pytorch)."""
    candidates: list[tuple[str, str, str]] = []
    key = _norm(package)
    for source in context.sources:
        for text in (source.url, source.content):
            for owner, repo in _GITHUB_REPO_RE.findall(text or ""):
                repo = re.sub(r"\.git$", "", repo)
                if owner.lower() in _NOT_REPO_OWNERS or key not in _norm(repo):
                    continue
                if (owner.lower(), repo.lower()) not in {(o.lower(), r.lower()) for o, r, _ in candidates}:
                    candidates.append((owner, repo, source.url))
    return candidates


def resolve(
    tavily_client,
    code: str,
    evidence: str,
    repo_date: date | None,
    *,
    http_get: HttpGet | None = None,
    max_git_candidates: int = 3,
) -> Resolution | None:
    """None if this failure isn't a dependency failure RERUN can name."""
    if code not in RESOLVER_CODES:
        return None
    package = package_from_evidence(evidence)
    if not package:
        return None
    http_get = http_get or _default_http_get
    query = build_query(code, package, repo_date)
    notes: list[str] = []

    context = tavily.TavilyContext(query=query, sources=())
    if tavily_client is not None:
        try:
            context = _search(tavily_client, query)
        except Exception as exc:  # a Tavily outage must never block repair
            notes.append(f"Tavily search failed: {exc}")
        # Found live (dassl, 2026-09-24): a general query returned blog posts
        # and a Hugging Face mirror but never the GitHub repo itself. For a
        # package that is not on PyPI, the source repo is the whole point,
        # so if no matching GitHub repo was cited, ask once more restricted
        # to github.com. Both queries are recorded and cited.
        if code == TaxonomyCode.DEP_NOT_ON_PYPI and not _github_candidates(context, package):
            github_query = f"{package} github repository"
            try:
                extra = _search(tavily_client, github_query, include_domains=["github.com"])
                context = tavily.TavilyContext(
                    query=f"{context.query} | {github_query} (github.com only)",
                    sources=context.sources + extra.sources,
                )
            except Exception as exc:
                notes.append(f"Tavily github.com search failed: {exc}")

    candidates = _github_candidates(context, package)
    git_sources = []
    for owner, repo, cited_by in candidates[:max_git_candidates]:
        try:
            verified = _verify_github(owner, repo, repo_date, cited_by, http_get)
        except Exception as exc:
            notes.append(f"GitHub verification failed for {owner}/{repo}: {exc}")
            verified = None
        if verified:
            git_sources.append(verified)

    try:
        pypi_status, releases = _pypi_releases(package, repo_date, http_get)
    except Exception as exc:
        pypi_status, releases = f"lookup failed ({type(exc).__name__})", ()
    return Resolution(
        package=package,
        repo_date=repo_date,
        context=context,
        git_sources=tuple(git_sources),
        pypi_package=package,
        pypi_releases=releases,
        pypi_status=pypi_status,
        notes=tuple(notes),
    )
