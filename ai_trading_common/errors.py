"""Shared exception handlers that include request correlation IDs."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .correlation import REQUEST_ID_HEADER, get_correlation_id

try:
    from slowapi.errors import RateLimitExceeded
except Exception:  # pragma: no cover - optional dependency
    RateLimitExceeded = None


def _correlation_id_for_request(request: Request) -> str | None:
    state_value = getattr(request.state, "correlation_id", None)
    if isinstance(state_value, str) and state_value:
        return state_value
    return get_correlation_id()


def _json_error_response(request: Request, status_code: int, error: object) -> JSONResponse:
    correlation_id = _correlation_id_for_request(request)
    response = JSONResponse(
        status_code=status_code,
        content={
            "error": error,
            "correlation_id": correlation_id,
        },
    )
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

