"""Tests for ai_trading_common.health — DependencyCheck registry + endpoints."""

from __future__ import annotations

import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ai_trading_common.health import (
    DependencyCheck,
    configure_health,
    health_router,
)


@pytest.fixture(autouse=True)
def _reset_health_state():
    DependencyCheck.clear()
    configure_health("test-service", "1.0.0")
    yield
    DependencyCheck.clear()


@pytest.fixture
def app() -> FastAPI:
    app = FastAPI()
    app.include_router(health_router)
    return app


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
