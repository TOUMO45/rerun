"""Tests for tavily.py. No live Tavily call — fetch_context is tested
against a fake client satisfying `_SearchClientLike`'s one-method surface."""

from __future__ import annotations

import pytest

from app.services.tavily import TavilyContext, TavilyError, TavilySource, build_query, fetch_context


class _FakeTavilyClient:
    def __init__(self, response: dict | None = None, raise_error: Exception | None = None):
        self.response = response or {"results": []}
        self.raise_error = raise_error
        self.last_call: dict | None = None

    def search(self, query, *, max_results, search_depth):
        self.last_call = {"query": query, "max_results": max_results, "search_depth": search_depth}
        if self.raise_error:
            raise self.raise_error
        return self.response


def test_build_query_is_deterministic_and_explainable():
    query = build_query("DEP_MISSING", "ModuleNotFoundError: No module named 'yaml'")
    assert "dep missing" in query.lower()
    assert "ModuleNotFoundError" in query


def test_fetch_context_returns_empty_context_when_no_client_configured():
    context = fetch_context(None, "DEP_MISSING", "ModuleNotFoundError: No module named 'yaml'")
    assert context.has_sources is False
    assert context.sources == ()
    assert context.query  # still built, for transparency about what *would* have been searched


def test_fetch_context_parses_real_search_results():
    client = _FakeTavilyClient(
        response={
            "results": [
                {"title": "Fixing ModuleNotFoundError for yaml", "url": "https://example.com/a", "content": "pip install pyyaml"},
                {"title": "PyYAML docs", "url": "https://example.com/b", "content": "PyYAML is a YAML parser"},
            ]
        }
    )
    context = fetch_context(client, "DEP_MISSING", "ModuleNotFoundError: No module named 'yaml'")
    assert context.has_sources is True
    assert len(context.sources) == 2
    assert context.sources[0].url == "https://example.com/a"
    assert client.last_call["search_depth"] == "basic"


def test_fetch_context_negative_control_missing_fields_default_safely():
    # A result item missing expected keys must not crash the pipeline.
    client = _FakeTavilyClient(response={"results": [{}]})
    context = fetch_context(client, "DEP_MISSING", "evidence")
    assert context.sources[0].title == ""
    assert context.sources[0].url == ""


def test_fetch_context_negative_control_missing_results_key_defaults_to_empty():
    client = _FakeTavilyClient(response={})
    context = fetch_context(client, "DEP_MISSING", "evidence")
    assert context.sources == ()


def test_fetch_context_raises_tavily_error_on_search_failure():
    client = _FakeTavilyClient(raise_error=RuntimeError("connection refused"))
    with pytest.raises(TavilyError):
        fetch_context(client, "DEP_MISSING", "evidence")


def test_as_prompt_context_includes_urls_for_citation():
    context = TavilyContext(
        query="q",
        sources=(TavilySource(title="T", url="https://example.com/x", content="some content"),),
    )
    prompt_text = context.as_prompt_context()
    assert "https://example.com/x" in prompt_text
    assert "T" in prompt_text


def test_as_prompt_context_empty_when_no_sources():
    context = TavilyContext(query="q", sources=())
    assert context.as_prompt_context() == ""


def test_as_dict_round_trips_sources():
    context = fetch_context(
        _FakeTavilyClient(response={"results": [{"title": "T", "url": "U", "content": "C"}]}),
        "DEP_MISSING",
        "evidence",
    )
    d = context.as_dict()
    assert d["sources"] == [{"title": "T", "url": "U", "content": "C"}]
