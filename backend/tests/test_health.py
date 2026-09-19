"""§12 compliance: /healthz must be real and checkable."""

from __future__ import annotations


def test_healthz_returns_ok(client):
    response = client.get("/healthz")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "nebius_configured" in body
    assert "tavily_configured" in body
