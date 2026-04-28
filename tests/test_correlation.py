"""Tests for ai_trading_common.correlation — CorrelationMiddleware contract."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ai_trading_common.correlation import (
    REQUEST_ID_HEADER,
    CorrelationMiddleware,
    get_correlation_headers,
    get_correlation_id,
)


@pytest.fixture
def app_with_correlation() -> FastAPI:
    app = FastAPI()
    app.add_middleware(CorrelationMiddleware)

    @app.get("/echo")
    def echo() -> dict:
        return {
            "correlation_id": get_correlation_id(),
            "headers": get_correlation_headers(),
        }

    return app


def test_generates_correlation_id_when_header_absent(app_with_correlation: FastAPI) -> None:
    client = TestClient(app_with_correlation)
    res = client.get("/echo")
    assert res.status_code == 200
    body = res.json()
    assert body["correlation_id"], "expected a generated correlation id"
    assert body["headers"][REQUEST_ID_HEADER] == body["correlation_id"]
    assert res.headers[REQUEST_ID_HEADER] == body["correlation_id"]


def test_propagates_inbound_correlation_id(app_with_correlation: FastAPI) -> None:
    client = TestClient(app_with_correlation)
    inbound = "11111111-2222-3333-4444-555555555555"
    res = client.get("/echo", headers={REQUEST_ID_HEADER: inbound})
    assert res.status_code == 200
    assert res.json()["correlation_id"] == inbound
    assert res.headers[REQUEST_ID_HEADER] == inbound


def test_get_correlation_id_returns_none_outside_request_context() -> None:
    # No middleware has run → no correlation id bound.
    assert get_correlation_id() is None
    assert get_correlation_headers() == {}


def test_each_request_gets_a_unique_id(app_with_correlation: FastAPI) -> None:
    client = TestClient(app_with_correlation)
    ids = {client.get("/echo").json()["correlation_id"] for _ in range(5)}
    assert len(ids) == 5, "each request should generate a fresh id"
