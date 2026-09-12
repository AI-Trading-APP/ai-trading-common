"""Tests for Platform Reliability Block-0 taxonomy (COM-1, COM-2, TEST-1).

Covers:
  - CauseCategory enum — 7 members with exact string values.
  - _json_error_response — includes cause_category when provided; omits the
    key entirely when not (backward-compat assertion).
  - configure_health — both (app, name, ver) and (name, ver) call styles.
  - /health/ready dep-result — cause_category + last_known_good_ts threaded
    through when a dep check supplies them; absent otherwise.
"""

from __future__ import annotations

import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ai_trading_common.errors import CauseCategory, _json_error_response
from ai_trading_common.health import DependencyCheck, configure_health


# ---------------------------------------------------------------------------
# CauseCategory — COM-1
# ---------------------------------------------------------------------------

_EXPECTED_MEMBERS = {
    "TIMEOUT": "timeout",
    "QUOTA": "quota",
    "OUT_OF_UNIVERSE": "out-of-universe",
    "IP_BLOCK": "IP-block",
    "BREAKER_OPEN": "breaker-open",
    "STALE_DATA": "stale-data",
    "UNKNOWN": "unknown",
}


def test_cause_category_has_all_seven_members() -> None:
    member_names = {m.name for m in CauseCategory}
    assert member_names == set(_EXPECTED_MEMBERS.keys()), (
        f"Unexpected members: {member_names}"
    )


@pytest.mark.parametrize("name,expected_value", _EXPECTED_MEMBERS.items())
def test_cause_category_string_values(name: str, expected_value: str) -> None:
    member = CauseCategory[name]
    assert member.value == expected_value
    # Being a str subclass means str(member) and the .value both equal the
    # expected string — consumers can use the enum or the raw string safely.
    assert str(member) == expected_value


def test_cause_category_importable_from_package() -> None:
    from ai_trading_common import CauseCategory as CC  # noqa: F401

    assert CC.TIMEOUT == "timeout"


# ---------------------------------------------------------------------------
# _json_error_response — COM-1 (cause_category behaviour)
# ---------------------------------------------------------------------------

def _make_mock_request():
    """Return a minimal mock Request with no correlation-ID state."""
    from unittest.mock import MagicMock
    req = MagicMock()
    req.state = MagicMock()
    req.state.correlation_id = None
    return req


def test_json_error_response_excludes_cause_category_key_by_default() -> None:
    """Backward-compat: when cause_category is not provided the key must be
    absent from the body — not present with a None value."""
    req = _make_mock_request()
    response = _json_error_response(req, 500, "boom")
    body = response.body
    import json
    parsed = json.loads(body)
    assert "cause_category" not in parsed, (
        f"Key 'cause_category' must be absent when not provided; got: {parsed}"
    )


def test_json_error_response_includes_cause_category_when_provided_enum() -> None:
    req = _make_mock_request()
    response = _json_error_response(req, 503, "dep failed", cause_category=CauseCategory.TIMEOUT)
    import json
    parsed = json.loads(response.body)
    assert parsed["cause_category"] == "timeout"


def test_json_error_response_includes_cause_category_when_provided_str() -> None:
    req = _make_mock_request()
    response = _json_error_response(req, 503, "dep failed", cause_category="quota")
    import json
    parsed = json.loads(response.body)
    assert parsed["cause_category"] == "quota"


def test_json_error_response_detail_and_correlation_id_unchanged() -> None:
    """Existing shape must not change when cause_category is omitted."""
    req = _make_mock_request()
    response = _json_error_response(req, 404, "not_found")
    import json
    parsed = json.loads(response.body)
    assert "detail" in parsed
    assert parsed["detail"] == "not_found"
    assert "correlation_id" in parsed


# ---------------------------------------------------------------------------
# configure_health — COM-2 back-compat shim
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset_dep_checks():
    DependencyCheck.clear()
    yield
    DependencyCheck.clear()


def test_configure_health_app_first_style_succeeds() -> None:
    """Original (app, name, ver) call style must work without raising."""
    from ai_trading_common.health import health_router as _health_router
    app = FastAPI()
    configure_health(app, "my-service", "2.0.0")
    # _IncludedRouter wraps included routers; verify ours was mounted exactly once.
    mounted = [r for r in app.router.routes if getattr(r, "original_router", None) is _health_router]
    assert len(mounted) == 1


def test_configure_health_name_first_style_succeeds() -> None:
    """New (name, ver) call style — no app — must work without raising."""
    configure_health("bare-service", "1.2.3")
    # No app to inspect; just asserting no TypeError / exception raised.


def test_configure_health_name_first_does_not_mount_router() -> None:
    """When called without an app, the router must NOT be mounted anywhere."""
    app = FastAPI()
    configure_health("bare-service", "1.2.3")
    health_routes = [r for r in app.router.routes if getattr(r, "path", "").startswith("/health")]
    assert health_routes == [], "Router must not be mounted on an unrelated app"


def test_configure_health_app_first_is_idempotent() -> None:
    from ai_trading_common.health import health_router as _health_router
    app = FastAPI()
    configure_health(app, "svc", "1.0.0")
    configure_health(app, "svc", "1.0.0")
    mounted = [r for r in app.router.routes if getattr(r, "original_router", None) is _health_router]
    assert len(mounted) == 1, "Router must be mounted exactly once"


# ---------------------------------------------------------------------------
# /health/ready optional dep fields — COM-2
# ---------------------------------------------------------------------------

def test_health_ready_includes_cause_and_lkg_when_dep_provides_them() -> None:
    async def _dep_with_extras():
        return (
            False,
            42.0,
            {
                "cause_category": "timeout",
                "last_known_good_ts": "2026-07-03T12:00:00+00:00",
            },
        )

    DependencyCheck.register("redis", _dep_with_extras)
    app = FastAPI()
    configure_health(app, "svc", "1.0.0")
    client = TestClient(app)
    res = client.get("/health/ready")
    assert res.status_code == 503
    dep = res.json()["dependencies"]["redis"]
    assert dep["cause_category"] == "timeout"
    assert dep["last_known_good_ts"] == "2026-07-03T12:00:00+00:00"


def test_health_ready_omits_cause_and_lkg_for_plain_dep() -> None:
    async def _plain_dep():
        return (True, 5.0)

    DependencyCheck.register("postgres", _plain_dep)
    app = FastAPI()
    configure_health(app, "svc", "1.0.0")
    client = TestClient(app)
    res = client.get("/health/ready")
    assert res.status_code == 200
    dep = res.json()["dependencies"]["postgres"]
    assert "cause_category" not in dep
    assert "last_known_good_ts" not in dep


def test_health_ready_omits_cause_when_dep_returns_none_values() -> None:
    async def _dep_with_none_extras():
        return (True, 3.0, {"cause_category": None, "last_known_good_ts": None})

    DependencyCheck.register("cache", _dep_with_none_extras)
    results = asyncio.run(DependencyCheck.run_all(timeout=1.0))
    dep = results["cache"]
    assert "cause_category" not in dep
    assert "last_known_good_ts" not in dep


def test_health_ready_cause_category_with_enum_value() -> None:
    async def _dep():
        return (False, 1.0, {"cause_category": CauseCategory.QUOTA})

    DependencyCheck.register("external-api", _dep)
    results = asyncio.run(DependencyCheck.run_all(timeout=1.0))
    assert results["external-api"]["cause_category"] == "quota"
