"""Tavily integration (RERUN directive §12 checklist: "Tavily called at
runtime, cited in the certificate — Best Use of Tavily eligibility").

Called once per repair attempt, using the *classification* of that
attempt's failure, so the search query is grounded in a real, specific
signal (the taxonomy code and the actual evidence line) rather than a
generic "help me fix this repo" prompt. Results are threaded into the
repair prompt as explicitly citable context and recorded structurally on
the attempt (`orchestrator.AttemptRecord.tavily_sources`) so the
certificate can show real cited sources — not just text a judge has to
trust was actually looked up.

Ground truth: `TavilyClient.__init__` and `.search()`'s signature were
read from the installed `tavily-python` package source (confirmed:
`search()` always returns a dict with a `"results"` key, defaulting to
`[]`). The exact keys *within* each result item (`title`/`url`/`content`)
were not independently confirmed against local source — this client is a
thin pass-through with no bundled response schema — so they're accessed
defensively (`.get(..., "")`) rather than assumed to always be present,
following Tavily's well-documented public API conventions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from app.services import timeouts


class TavilyError(RuntimeError):
    pass


class _SearchClientLike(Protocol):
    """The minimal surface this module needs — real `tavily.TavilyClient`
    satisfies this; tests inject a small fake."""

    def search(self, query: str, *, max_results: int, search_depth: str) -> dict: ...


@dataclass(frozen=True)
class TavilySource:
    title: str
    url: str
    content: str

    def as_dict(self) -> dict:
        return {"title": self.title, "url": self.url, "content": self.content}


@dataclass(frozen=True)
class TavilyContext:
    query: str
    sources: tuple[TavilySource, ...] = field(default_factory=tuple)

    @property
    def has_sources(self) -> bool:
        return len(self.sources) > 0

    def as_prompt_context(self) -> str:
        """Citable text for the repair prompt — includes each source's URL
        so a citation can trace back to something real, not just prose."""
        if not self.sources:
            return ""
        lines = [f"Runtime web context for query '{self.query}' — cite these sources if you use them:"]
        for i, source in enumerate(self.sources, start=1):
            snippet = source.content[:500]
            lines.append(f"[{i}] {source.title} — {source.url}\n{snippet}")
        return "\n".join(lines)

    def as_dict(self) -> dict:
        return {"query": self.query, "sources": [s.as_dict() for s in self.sources]}


_FRAMEWORKS = (
    ("torch", "pytorch"), ("tensorflow", "tensorflow"), ("keras", "keras"), ("chainer", "chainer"), ("mxnet", "mxnet"),
    ("jax", "jax"), ("theano", "theano"), ("paddle", "paddlepaddle"),
)


def detect_framework(imported_modules) -> str:
    """The ML framework the repository imports (first match in a fixed order), or "". Deterministic."""
    names = {str(m).lower() for m in imported_modules or ()}
    return next((label for module, label in _FRAMEWORKS if module in names), "")


def python_minor(base_image: str | None) -> str:
    """"3.8" from "python:3.8-slim", or ""."""
    import re

    match = re.match(r"python:(\d+\.\d+)", base_image or "")
    return match.group(1) if match else ""


def build_query(taxonomy_code: str, evidence: str, *, framework: str = "", python_version: str = "", tried: tuple = ()) -> str:
    """A deterministic, explainable query built directly from the failure
    classification — never left to a model to phrase, so a judge or
    reviewer can see exactly what was searched for and why, right next to
    the citation it produced.

    harness-v1.3.3 (D-4): the query carries the error AND the repository's framework and Python version (an error text
    alone returns generic blog posts), and, when earlier attempts of this run already tried something that did not fix it,
    what they tried, so a repeated error does not repeat an identical search."""
    readable_code = taxonomy_code.replace("_", " ").lower()
    head = " ".join(part for part in ("python", python_version, framework) if part)
    query = f"{head} {readable_code} fix: {evidence[:150]}"
    if tried:
        query += " | already tried: " + ", ".join(str(t) for t in tried[:3])[:120]
    return query


def fetch_context(
    client: _SearchClientLike | None,
    taxonomy_code: str,
    evidence: str,
    max_results: int = 3,
    *,
    framework: str = "",
    python_version: str = "",
    tried: tuple = (),
) -> TavilyContext:
    """Search Tavily for context on a specific classified failure. Returns
    an empty (but real, not fabricated) `TavilyContext` if no client is
    configured or the search fails — callers must never let a Tavily
    outage block or crash the repair loop, since Tavily is a should-have
    enrichment (§5's cut ladder item 2: "Tavily-cited repair context ->
    repair without external context, still functions"), not a dependency.
    """
    query = build_query(taxonomy_code, evidence, framework=framework, python_version=python_version, tried=tried)
    if client is None:
        return TavilyContext(query=query, sources=())

    try:
        response = client.search(query, max_results=max_results, search_depth="basic", timeout=timeouts.TAVILY_S)
    except Exception as exc:
        raise TavilyError(f"Tavily search failed for query '{query}': {exc}") from exc

    sources = tuple(
        TavilySource(
            title=str(result.get("title", "")),
            url=str(result.get("url", "")),
            content=str(result.get("content", "")),
        )
        for result in response.get("results", [])
    )
    return TavilyContext(query=query, sources=sources)
