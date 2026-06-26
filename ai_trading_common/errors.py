"""Shared exception handlers that include request correlation IDs."""

from __future__ import annotations

from enum import Enum

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .correlation import REQUEST_ID_HEADER, get_correlation_id


class CauseCategory(str, Enum):
    """Shared taxonomy of failure root-causes (COM-1 / REQ-B5 / US-9).

    Values are stable strings — do NOT rename them once services ship;
    add new entries instead.  Use ``UNKNOWN`` for novel failures.
    """

    TIMEOUT = "timeout"
    QUOTA = "quota"
    OUT_OF_UNIVERSE = "out-of-universe"
    IP_BLOCK = "IP-block"
    BREAKER_OPEN = "breaker-open"
    STALE_DATA = "stale-data"
    UNKNOWN = "unknown"

try:
    from slowapi.errors import RateLimitExceeded
except Exception:  # pragma: no cover - optional dependency
    RateLimitExceeded = None


def _correlation_id_for_request(request: Request) -> str | None:
    state_value = getattr(request.state, "correlation_id", None)
    if isinstance(state_value, str) and state_value:
        return state_value
    return get_correlation_id()


def _json_error_response(
    request: Request,
    status_code: int,
    error: object,
    *,
    cause_category: CauseCategory | str | None = None,
) -> JSONResponse:
    """Render an error response in the FastAPI-default `{"detail": ...}`
    shape, plus a `correlation_id` field for distributed tracing.

    Using `detail` (not `error`) because:
    - FastAPI's built-in `HTTPException` and `RequestValidationError`
      already use `detail` — preserving the key keeps existing
      consumer tests and clients working without rewrites
    - OpenAPI schema generation expects `detail`

    Args:
        cause_category: Optional :class:`CauseCategory` (or its string value)
            to include as ``cause_category`` in the response body.  Omitted
            entirely when ``None`` so existing consumers see no diff.
    """
    correlation_id = _correlation_id_for_request(request)
    content: dict[str, object] = {
        "detail": error,
        "correlation_id": correlation_id,
    }
    if cause_category is not None:
        # Accept both the enum and bare strings (forward-compat for callers
        # that haven't imported the enum yet).
        content["cause_category"] = (
            cause_category.value
            if isinstance(cause_category, CauseCategory)
            else str(cause_category)
        )
    response = JSONResponse(status_code=status_code, content=content)
    if correlation_id:
        response.headers[REQUEST_ID_HEADER] = correlation_id
    return response


def register_exception_handlers(app: FastAPI) -> None:
    """Install consistent JSON exception handlers with correlation IDs."""

    if RateLimitExceeded is not None:
        @app.exception_handler(RateLimitExceeded)
        async def _rate_limit_exception_handler(request: Request, exc: Exception) -> JSONResponse:
            detail = getattr(exc, "detail", "Rate limit exceeded")
            return _json_error_response(request, 429, detail)

    @app.exception_handler(StarletteHTTPException)
    async def _http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        return _json_error_response(request, exc.status_code, exc.detail)

    @app.exception_handler(RequestValidationError)
    async def _validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        return _json_error_response(request, 400, exc.errors())

    @app.exception_handler(Exception)
    async def _general_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        return _json_error_response(request, 500, "Internal server error")

