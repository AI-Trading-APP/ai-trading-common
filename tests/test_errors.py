"""Tests for ai_trading_common.errors — exception handler shape."""

from __future__ import annotations

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from ai_trading_common.errors import register_exception_handlers, _json_error_response, CauseCategory
from ai_trading_common import CauseCategory as CauseCategoryPublic


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


# ---------------------------------------------------------------------------
# COM-1 / TEST-1: CauseCategory enum tests
# ---------------------------------------------------------------------------

_EXPECTED_CAUSE_VALUES = {
    "timeout",
    "quota",
    "out-of-universe",
    "IP-block",
    "breaker-open",
    "stale-data",
    "unknown",
}


def test_cause_category_has_all_seven_values() -> None:
    """AC-9a: CauseCategory enum must expose exactly the 7 contracted values."""
    actual = {member.value for member in CauseCategory}
    assert actual == _EXPECTED_CAUSE_VALUES, (
        f"Unexpected enum values.\n  missing: {_EXPECTED_CAUSE_VALUES - actual}\n"
        f"  extra:   {actual - _EXPECTED_CAUSE_VALUES}"
    )


def test_cause_category_importable_from_package() -> None:
    """AC-9d: CauseCategory is importable from ai_trading_common top-level."""
    # CauseCategoryPublic was imported at module level; just verify it's the same class
    assert CauseCategoryPublic is CauseCategory


def test_cause_category_is_str_subclass() -> None:
    """CauseCategory members must be usable as plain strings (str, Enum)."""
    assert isinstance(CauseCategory.TIMEOUT, str)
    assert CauseCategory.TIMEOUT == "timeout"
    assert CauseCategory.UNKNOWN == "unknown"



def test_cause_category_present_in_error_body() -> None:
    """AC-9b: when cause_category is provided, it appears in the JSON body."""
    # Build a minimal FastAPI app with a route that uses _json_error_response
    # directly so we can verify the envelope shape without going through the
    # exception handler chain.
    mini = FastAPI()

    @mini.get("/err")
    async def err_route(request: Request):
        return _json_error_response(request, 503, "service unavailable", cause_category=CauseCategory.TIMEOUT)

    client = TestClient(mini)
    res = client.get("/err")
    assert res.status_code == 503
    body = res.json()
    assert body.get("cause_category") == "timeout", f"body was: {body}"
    assert body.get("detail") == "service unavailable"


def test_cause_category_absent_when_not_provided() -> None:
    """Backward-compat: cause_category key must NOT appear when omitted."""
    mini = FastAPI()

    @mini.get("/err")
    async def err_route(request: Request):
        return _json_error_response(request, 404, "not found")

    client = TestClient(mini)
    res = client.get("/err")
    assert res.status_code == 404
    body = res.json()
    assert "cause_category" not in body, (
        f"cause_category must be absent when not provided; got body: {body}"
    )


def test_cause_category_accepts_bare_string() -> None:
    """_json_error_response also accepts a plain string for cause_category."""
    mini = FastAPI()

    @mini.get("/err")
    async def err_route(request: Request):
        return _json_error_response(request, 429, "rate limited", cause_category="quota")

    client = TestClient(mini)
    res = client.get("/err")
    body = res.json()
    assert body.get("cause_category") == "quota"


def test_cause_category_ec7_unknown_value_present() -> None:
    """EC-7: 'unknown' value must exist for novel failures."""
    assert CauseCategory.UNKNOWN == "unknown"
    assert CauseCategory("unknown") is CauseCategory.UNKNOWN
