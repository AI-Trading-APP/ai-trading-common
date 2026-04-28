"""Request correlation helpers shared by backend services."""

from __future__ import annotations

import time
import uuid
from contextvars import ContextVar

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

REQUEST_ID_HEADER = "X-Request-ID"
_correlation_id_var: ContextVar[str | None] = ContextVar("correlation_id", default=None)
logger = structlog.get_logger(__name__)


def generate_correlation_id() -> str:
    return str(uuid.uuid4())


def get_correlation_id() -> str | None:
    correlation_id = _correlation_id_var.get()
    if correlation_id:
        return correlation_id

    contextvars_data = structlog.contextvars.get_contextvars()
    value = contextvars_data.get("correlation_id")
    return value if isinstance(value, str) else None


def get_correlation_headers() -> dict[str, str]:
    correlation_id = get_correlation_id()
    return {REQUEST_ID_HEADER: correlation_id} if correlation_id else {}


class CorrelationMiddleware(BaseHTTPMiddleware):
    """Propagate a request correlation ID through headers and structlog context."""

    async def dispatch(self, request: Request, call_next):
        incoming_id = request.headers.get(REQUEST_ID_HEADER)
        correlation_id = incoming_id if incoming_id else generate_correlation_id()

        request.state.correlation_id = correlation_id
        structlog.contextvars.clear_contextvars()
        token = _correlation_id_var.set(correlation_id)
        structlog.contextvars.bind_contextvars(
            correlation_id=correlation_id,
            method=request.method.upper(),
            path=request.url.path,
        )

        started = time.perf_counter()
        response = None
        try:
            response = await call_next(request)
            response.headers[REQUEST_ID_HEADER] = correlation_id
            return response
        finally:
            duration_ms = round((time.perf_counter() - started) * 1000, 2)
            logger.info(
                "request_completed",
                method=request.method.upper(),
                endpoint=request.url.path,
                status_code=getattr(response, "status_code", 500),
                duration_ms=duration_ms,
            )
            structlog.contextvars.clear_contextvars()
            _correlation_id_var.reset(token)


