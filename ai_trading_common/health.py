"""
Deep health check router — provides /health, /health/ready, /health/live endpoints.

Usage:
    from ai_trading_common.health import health_router, DependencyCheck, configure_health

    configure_health("userservice", "3.0.0")
    DependencyCheck.register("postgresql", check_postgres_fn)
    app.include_router(health_router, tags=["health"])
"""

import asyncio
import time
from datetime import datetime, timezone

from fastapi import APIRouter
from fastapi.responses import JSONResponse


health_router = APIRouter()

_start_time = time.time()
_service_meta = {"name": "unknown", "version": "0.0.0"}


def configure_health(service_name: str, version: str):
    """Set service metadata returned in health responses."""
    _service_meta["name"] = service_name
    _service_meta["version"] = version


class DependencyCheck:
    """Registry of async health-check functions for service dependencies."""

    _checks: dict = {}

    @classmethod
    def register(cls, name: str, check_fn):
        """Register a dependency check.

        check_fn must be an async callable returning (ok: bool, latency_ms: float).
        """
        cls._checks[name] = check_fn

    @classmethod
    async def run_all(cls, timeout: float = 5.0) -> dict:
        results = {}
        for name, fn in cls._checks.items():
            try:
                ok, latency = await asyncio.wait_for(fn(), timeout=timeout)
                results[name] = {
                    "status": "healthy" if ok else "unhealthy",
                    "latency_ms": round(latency, 1),
                }
            except asyncio.TimeoutError:
                results[name] = {"status": "unhealthy", "error": "timeout", "latency_ms": None}
            except Exception as e:
                results[name] = {"status": "unhealthy", "error": str(e), "latency_ms": None}
        return results

    @classmethod
    def clear(cls):
        """Remove all registered checks (useful for testing)."""
        cls._checks.clear()


@health_router.get("/health")
async def health_shallow():
    """Shallow health check — process is alive."""
    return {
        "status": "healthy",
        "service": _service_meta["name"],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@health_router.get("/health/ready")
async def health_ready():
    """Deep readiness check — all dependencies verified."""
    deps = await DependencyCheck.run_all(timeout=5.0)
    all_healthy = all(d["status"] == "healthy" for d in deps.values())

    return JSONResponse(
        status_code=200 if all_healthy else 503,
        content={
            "status": "healthy" if all_healthy else "unhealthy",
            "service": _service_meta["name"],
            "version": _service_meta["version"],
            "uptime_seconds": round(time.time() - _start_time),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "dependencies": deps,
        },
    )


@health_router.get("/health/live")
async def health_live():
    """Liveness probe — event loop is responsive."""
    return {
        "status": "alive",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
