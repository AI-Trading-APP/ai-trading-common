"""Tests for ai_trading_common.health — DependencyCheck registry + endpoints."""

from __future__ import annotations

import asyncio

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from ai_trading_common.health import DependencyCheck, _service_meta, configure_health


@pytest.fixture(autouse=True)
def _reset_health_state():
    DependencyCheck.clear()
    yield
    DependencyCheck.clear()


@pytest.fixture
def app() -> FastAPI:
    app = FastAPI()
    configure_health(app, "test-service", "1.0.0")
    return app


def test_configure_health_is_idempotent() -> None:
    app = FastAPI()
    configure_health(app, "svc", "1.0.0")
    configure_health(app, "svc", "1.0.0")  # second call — must not double-mount
    # Use the flattened OpenAPI path map rather than raw `app.router.routes`:
    # newer FastAPI/Starlette versions wrap `include_router` results in a
    # lazily-resolved object that doesn't eagerly expose child paths via
    # `.path` on `app.router.routes` entries, but `app.openapi()["paths"]`
    # is a stable, version-independent view of the fully-resolved route table.
    health_paths = sorted(p for p in app.openapi()["paths"] if p.startswith("/health"))
    assert health_paths == ["/health", "/health/live", "/health/ready"], (
        "expected exactly /health, /health/ready, /health/live with no duplicates"
    )


def test_shallow_health_returns_alive(app: FastAPI) -> None:
    client = TestClient(app)
    res = client.get("/health")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "healthy"
    assert body["service"] == "test-service"


def test_liveness_probe(app: FastAPI) -> None:
    client = TestClient(app)
    res = client.get("/health/live")
    assert res.status_code == 200
    assert res.json()["status"] == "alive"


def test_ready_with_no_registered_checks_is_healthy(app: FastAPI) -> None:
    client = TestClient(app)
    res = client.get("/health/ready")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "healthy"
    assert body["service"] == "test-service"
    assert body["version"] == "1.0.0"
    assert body["dependencies"] == {}


def test_ready_returns_503_when_dependency_unhealthy(app: FastAPI) -> None:
    async def _bad_dep() -> tuple[bool, float]:
        return (False, 12.3)

    DependencyCheck.register("postgres", _bad_dep)
    client = TestClient(app)
    res = client.get("/health/ready")
    assert res.status_code == 503
    body = res.json()
    assert body["status"] == "unhealthy"
    assert body["dependencies"]["postgres"]["status"] == "unhealthy"
    assert body["dependencies"]["postgres"]["latency_ms"] == 12.3


def test_ready_3tuple_soft_fail_stays_200_with_degraded_annotation(app: FastAPI) -> None:
    # v0.4.3: a 3-tuple (ok, latency, extras) with ok=True but a degraded
    # annotation must return 200 AND surface the extras in the payload —
    # the soft/optional-dependency semantics (ScreenerService yfinance
    # soft-fail). Previously run_all crashed unpacking a 3-tuple → 503.
    async def _soft_degraded() -> tuple:
        return (True, 10.0, {"degraded": True, "warning": "IP-blocked; fallback in use", "cause_category": "IP-block"})

    DependencyCheck.register("yfinance", _soft_degraded)
    client = TestClient(app)
    res = client.get("/health/ready")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "healthy"
    yf = body["dependencies"]["yfinance"]
    assert yf["status"] == "healthy"
    assert yf["degraded"] is True
    assert yf["warning"] == "IP-blocked; fallback in use"
    assert yf["cause_category"] == "IP-block"


def test_ready_3tuple_hard_fail_is_503(app: FastAPI) -> None:
    # A 3-tuple with ok=False still drives a 503 (extras don't rescue a real
    # unhealthy dependency).
    async def _hard_down() -> tuple:
        return (False, 5.0, {"detail": "connection refused"})

    DependencyCheck.register("postgres", _hard_down)
    client = TestClient(app)
    res = client.get("/health/ready")
    assert res.status_code == 503
    assert res.json()["dependencies"]["postgres"]["status"] == "unhealthy"
    assert res.json()["dependencies"]["postgres"]["detail"] == "connection refused"


def test_ready_handles_dependency_timeout(app: FastAPI) -> None:
    async def _hangs() -> tuple[bool, float]:
        await asyncio.sleep(10)  # exceeds default 5s timeout
        return (True, 0.0)

    DependencyCheck.register("slow", _hangs)
    client = TestClient(app)
    # Override timeout to make the test fast — re-register with a shorter wrapper.
    DependencyCheck.clear()

    async def _hangs_fast() -> tuple[bool, float]:
        # Use a sleep longer than the override timeout we'll pass
        await asyncio.sleep(0.5)
        return (True, 0.0)

    DependencyCheck.register("slow", _hangs_fast)

    # Run the async check directly with a short timeout to validate timeout path
    results = asyncio.run(DependencyCheck.run_all(timeout=0.1))
    assert results["slow"]["status"] == "unhealthy"
    assert results["slow"]["error"] == "timeout"


def test_ready_handles_dependency_exception() -> None:
    async def _raises() -> tuple[bool, float]:
        raise RuntimeError("boom")

    DependencyCheck.register("flaky", _raises)
    results = asyncio.run(DependencyCheck.run_all(timeout=1.0))
    assert results["flaky"]["status"] == "unhealthy"
    assert "boom" in results["flaky"]["error"]


# --- configure_health call-style / dispatch coverage (R2 F1/F2/F9) -------


def test_configure_health_keyword_args_mounts_and_sets_meta() -> None:
    # F1: old v0.4.4 keyword names (app=, service_name=, version=) must
    # keep working — and must actually mount the router + set meta, not
    # just avoid raising.
    app = FastAPI()
    configure_health(app=app, service_name="kw-service", version="9.9.9")
    assert _service_meta["name"] == "kw-service"
    assert _service_meta["version"] == "9.9.9"
    health_paths = sorted(p for p in app.openapi()["paths"] if p.startswith("/health"))
    assert health_paths == ["/health", "/health/live", "/health/ready"]


def test_configure_health_mixed_positional_app_and_keyword_name_version() -> None:
    # configure_health(app, service_name=..., version=...) — app positional,
    # name/version as keywords.
    app = FastAPI()
    configure_health(app, service_name="mixed-service", version="2.0.0")
    assert _service_meta["name"] == "mixed-service"
    assert _service_meta["version"] == "2.0.0"
    health_paths = sorted(p for p in app.openapi()["paths"] if p.startswith("/health"))
    assert health_paths == ["/health", "/health/live", "/health/ready"]


def test_configure_health_name_first_sets_meta_and_mounts_nothing() -> None:
    # F9: the ported test only inspected a fresh app that was never passed
    # to configure_health, so it could never fail. Assert the route table
    # of an unrelated, never-passed app is unchanged (nothing mounted
    # anywhere) AND that _service_meta was actually updated.
    app = FastAPI()
    before_paths = sorted(app.openapi()["paths"])
    configure_health("name-only-service", "3.3.3")
    assert _service_meta["name"] == "name-only-service"
    assert _service_meta["version"] == "3.3.3"
    after_paths = sorted(app.openapi()["paths"])
    assert after_paths == before_paths


def test_configure_health_name_first_then_app_first_mounts_on_app() -> None:
    # F9: ordering — name-first (no-op mount) followed later by app-first
    # for the SAME service must still mount correctly on the app.
    app = FastAPI()
    configure_health("later-mounted-service", "1.2.3")
    assert [p for p in app.openapi()["paths"] if p.startswith("/health")] == []

    configure_health(app, "later-mounted-service", "1.2.3")
    health_paths = sorted(p for p in app.openapi()["paths"] if p.startswith("/health"))
    assert health_paths == ["/health", "/health/live", "/health/ready"]
    assert _service_meta["name"] == "later-mounted-service"
    assert _service_meta["version"] == "1.2.3"


def test_configure_health_rejects_non_app_non_str_first_arg() -> None:
    # F2: a bad first argument (neither app nor str) must raise TypeError,
    # not silently take the name-first branch.
    with pytest.raises(TypeError):
        configure_health(object(), "x")


def test_configure_health_rejects_api_router_first_arg() -> None:
    # F2: an APIRouter is not a supported first argument (mounting onto a
    # router directly, as distinct from mounting the health router ONTO an
    # app, was never the documented contract) — TypeError, not a silent
    # mis-dispatch into the name-first branch.
    with pytest.raises(TypeError):
        configure_health(APIRouter(), "x", "y")
