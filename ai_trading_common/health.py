"""
Deep health check router — provides /health, /health/ready, /health/live endpoints.

Usage:
    from ai_trading_common import configure_health, DependencyCheck

    configure_health(app, "userservice", "3.0.0")
    DependencyCheck.register("postgresql", check_postgres_fn)
    # configure_health includes the router on `app` for you.
"""

import asyncio
import time
from datetime import datetime, timezone

from fastapi import APIRouter, FastAPI
from fastapi.responses import JSONResponse


health_router = APIRouter()

_start_time = time.time()
_service_meta = {"name": "unknown", "version": "0.0.0"}


def configure_health(app: FastAPI, service_name: str, version: str) -> None:
    """Set service metadata and mount the health router on `app`.

    One-call wire-up: stores name/version for the health responses, then
    `app.include_router(health_router, tags=["health"])`. Idempotent —
    safe to call again on the same app (router is mounted once per app).
    """
    _service_meta["name"] = service_name
    _service_meta["version"] = version
    # Avoid double-mounting if the caller (or a test) re-runs this.
    for route in app.router.routes:
        if getattr(route, "path", None) == "/health":
            return
    app.include_router(health_router, tags=["health"])


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
