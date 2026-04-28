"""Tests for ai_trading_common.errors — exception handler shape."""

from __future__ import annotations

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from ai_trading_common.errors import register_exception_handlers


@pytest.fixture
def app() -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/raises-http")
    def raises_http():
        raise HTTPException(status_code=404, detail="not_found")

    @app.get("/raises-internal")
    def raises_internal():
        raise RuntimeError("boom")

    return app


def test_http_exception_returns_detail_key(app: FastAPI) -> None:
    """FastAPI tradition: error body has `detail`, not `error`.

    Consumer tests across the org assert `response.json()["detail"]` —
    breaking that key is a public-API regression.
    """
    client = TestClient(app)
    res = client.get("/raises-http")
    assert res.status_code == 404
    body = res.json()
    assert "detail" in body, f"expected 'detail' key, got: {body}"
    assert body["detail"] == "not_found"


def test_internal_exception_returns_detail_key(app: FastAPI) -> None:
    # raise_server_exceptions=False: get the JSON response, not a re-raise
    client = TestClient(app, raise_server_exceptions=False)
    res = client.get("/raises-internal")
    assert res.status_code == 500
    body = res.json()
    assert "detail" in body, f"expected 'detail' key, got: {body}"
    assert body["detail"] == "Internal server error"


def test_response_includes_correlation_id_when_available(app: FastAPI) -> None:
    """When CorrelationMiddleware is wired, error responses carry the id."""
    from ai_trading_common.correlation import CorrelationMiddleware, REQUEST_ID_HEADER
    app.add_middleware(CorrelationMiddleware)

    client = TestClient(app)
    incoming = "abc-123"
    res = client.get("/raises-http", headers={REQUEST_ID_HEADER: incoming})
    body = res.json()
    assert body.get("correlation_id") == incoming
