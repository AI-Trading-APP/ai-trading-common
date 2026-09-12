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


def configure_health(
    app_or_name=None,
    service_name_or_ver: str = None,
    version: str = None,
    *,
    app=None,
    service_name=None,
) -> None:
    """Set service metadata and (optionally) mount the health router on `app`.

    Supports two call styles for backward-compatibility, both positional
    and keyword:

        configure_health(app, name, ver)                              # app-first, positional
        configure_health(app=app, service_name=name, version=ver)     # app-first, keyword (original v0.4.4 kwarg names)
        configure_health(app, service_name=name, version=ver)         # app-first, mixed
        configure_health(name, ver)                                   # name-first (no app)

    The shim detects whether the (positional-or-keyword-resolved) first
    argument is a FastAPI / Starlette application instance or a plain string
    name, and dispatches accordingly. Both styles are idempotent and safe to
    call more than once — the app-first style tracks mounted apps in a
    `WeakSet` (see `_configured_apps` above for why route-introspection is
    not used).

    Raises:
        TypeError: if the resolved first argument is neither a FastAPI/
            Starlette app nor a string service name (e.g. an `APIRouter`,
            `None`, or any other object). Silently degrading on a bad first
            argument was a defect in an earlier revision of this shim.
    """
    from starlette.applications import Starlette

    # Keyword-only `app=`/`service_name=` (the original v0.4.4 parameter
    # names) take precedence when supplied; otherwise fall back to the
    # positional/dual-purpose args.
    resolved_app_or_name = app if app is not None else app_or_name
    resolved_name = service_name if service_name is not None else service_name_or_ver

    if isinstance(resolved_app_or_name, (FastAPI, Starlette)):
        # app-first style: (app, name, ver).
        app_obj: FastAPI = resolved_app_or_name
        svc_name: str = resolved_name
        ver: str = version
        _service_meta["name"] = svc_name
        _service_meta["version"] = ver
        # Avoid double-mounting if the caller (or a test) re-runs this.
        if app_obj in _configured_apps:
            return
        app_obj.include_router(health_router, tags=["health"])
        _configured_apps.add(app_obj)
    elif isinstance(resolved_app_or_name, str):
        # name-first style: (name, ver) — no app to mount on.
        svc_name = resolved_app_or_name
        ver = resolved_name
        _service_meta["name"] = svc_name
        _service_meta["version"] = ver
    else:
        raise TypeError(
            "configure_health() expects a FastAPI/Starlette app or a str "
            f"service name as the first argument, got {type(resolved_app_or_name).__name__!r}. "
            "An APIRouter is not a supported first argument."
        )


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
