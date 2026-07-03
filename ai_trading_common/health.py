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


def configure_health(app_or_name, service_name_or_ver: str = None, version: str = None) -> None:
    """Set service metadata and (optionally) mount the health router on `app`.

    Supports two call styles for backward-compatibility:

        configure_health(app, name, ver)   # app-first (original signature)
        configure_health(name, ver)        # name-first (no app)

    The shim detects whether the first positional argument is a FastAPI /
    Starlette application instance or a plain string name, and dispatches
    accordingly.  Both styles are idempotent and safe to call more than once.
    """
    from starlette.applications import Starlette

    if isinstance(app_or_name, (FastAPI, Starlette)):
        # Original (app, name, ver) style.
        app: FastAPI = app_or_name
        service_name: str = service_name_or_ver
        ver: str = version
        _service_meta["name"] = service_name
        _service_meta["version"] = ver
        # Avoid double-mounting if the caller (or a test) re-runs this.
        # FastAPI wraps included routers in _IncludedRouter dataclass objects
        # that expose `original_router`; we check identity against our singleton.
        for route in app.router.routes:
            if getattr(route, "original_router", None) is health_router:
                return
        app.include_router(health_router, tags=["health"])
    else:
        # (name, ver) style — no app to mount on.
        service_name = app_or_name          # first arg is actually the name
        ver = service_name_or_ver           # second arg is the version
        _service_meta["name"] = service_name
        _service_meta["version"] = ver


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
                # Support both (ok, latency) and (ok, latency, extras) returns.
                # extras is a dict that MAY contain:
                #   cause_category      – str | None
                #   last_known_good_ts  – ISO-8601 str | None
                if len(raw) == 2:
                    ok, latency = raw
                    extras: dict = {}
                else:
                    ok, latency, extras = raw[0], raw[1], raw[2]
                entry: dict = {
                    "status": "healthy" if ok else "unhealthy",
                    "latency_ms": round(latency, 1),
                }
                # Thread optional reliability fields through only when present.
                cause_category = extras.get("cause_category") if extras else None
                last_known_good_ts = extras.get("last_known_good_ts") if extras else None
                if cause_category is not None:
                    entry["cause_category"] = str(cause_category)
                if last_known_good_ts is not None:
                    entry["last_known_good_ts"] = str(last_known_good_ts)
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
