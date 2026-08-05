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
import weakref
from datetime import datetime, timezone

from fastapi import APIRouter, FastAPI
from fastapi.responses import JSONResponse


health_router = APIRouter()

_start_time = time.time()
_service_meta = {"name": "unknown", "version": "0.0.0"}

# Tracks which FastAPI app instances already had the health router mounted.
# NOTE: newer FastAPI/Starlette releases (0.11x+) wrap `include_router`
# results in a lazily-resolved `_IncludedRouter` object rather than eagerly
# flattening the sub-router's routes into `app.router.routes` — so
# introspecting `app.router.routes` for a `path == "/health"` entry (the
# prior approach) silently found nothing and re-ran `include_router` every
# call. Tracking membership explicitly is robust across FastAPI/Starlette
# route-representation changes.
_configured_apps: "weakref.WeakSet[FastAPI]" = weakref.WeakSet()


def configure_health(app: FastAPI, service_name: str, version: str) -> None:
    """Set service metadata and mount the health router on `app`.

    One-call wire-up: stores name/version for the health responses, then
    `app.include_router(health_router, tags=["health"])`. Idempotent —
    safe to call again on the same app (router is mounted once per app).
    """
    _service_meta["name"] = service_name
    _service_meta["version"] = version
    # Avoid double-mounting if the caller (or a test) re-runs this.
    if app in _configured_apps:
        return
    app.include_router(health_router, tags=["health"])
    _configured_apps.add(app)


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
                raw = await asyncio.wait_for(fn(), timeout=timeout)
                # Support BOTH a 2-tuple (ok, latency_ms) and a 3-tuple
                # (ok, latency_ms, extras) where extras is a dict carrying
                # optional annotations (cause_category, last_known_good_ts,
                # warning, degraded, detail). v0.4.3 restores 3-tuple support
                # (present in an earlier ai-trading-common revision, dropped in
                # the v0.4.x rewrite) so services with soft/optional/degraded
                # dependency semantics — e.g. ScreenerService's yfinance
                # soft-fail — can report ok=True with a degraded annotation
                # instead of unpacking-crashing into a 503.
                if len(raw) == 2:
                    ok, latency = raw
                    extras: dict = {}
                else:
                    ok, latency, extras = raw[0], raw[1], raw[2]
                entry: dict = {
                    "status": "healthy" if ok else "unhealthy",
                    "latency_ms": round(latency, 1),
                }
                for field in (
                    "cause_category",
                    "last_known_good_ts",
                    "warning",
                    "degraded",
                    "detail",
                ):
                    if isinstance(extras, dict) and extras.get(field) is not None:
                        entry[field] = extras[field]
                results[name] = entry
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
