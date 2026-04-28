"""
Prometheus metrics middleware and /metrics endpoint.

Auto-collects RED metrics (Rate, Errors, Duration) for every HTTP request.
"""

import re
import time

from prometheus_client import Counter, Gauge, Histogram, generate_latest, CONTENT_TYPE_LATEST
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


REQUEST_COUNT = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["service", "method", "endpoint", "status_code"],
)

REQUEST_DURATION = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration in seconds",
    ["service", "method", "endpoint"],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)

REQUESTS_IN_PROGRESS = Gauge(
    "http_requests_in_progress",
    "Number of in-progress HTTP requests",
    ["service"],
)


# Path segment patterns to collapse (prevent label cardinality explosion)
_UUID_RE = re.compile(r"/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
_NUM_RE = re.compile(r"/\d+")


def _normalize_path(path: str) -> str:
    """Replace dynamic path segments with placeholders."""
    path = _UUID_RE.sub("/{id}", path)
    path = _NUM_RE.sub("/{id}", path)
    return path


class MetricsMiddleware(BaseHTTPMiddleware):
    """Collect Prometheus RED metrics for each request."""

    def __init__(self, app, service_name: str = "unknown"):
        super().__init__(app)
        self.service_name = service_name

    async def dispatch(self, request: Request, call_next):
        # Skip the metrics endpoint itself to avoid recursion
        if request.url.path == "/metrics":
            return await call_next(request)

        endpoint = _normalize_path(request.url.path)
        method = request.method

        REQUESTS_IN_PROGRESS.labels(service=self.service_name).inc()
        start = time.time()

        try:
            response = await call_next(request)
            duration = time.time() - start

            REQUEST_COUNT.labels(
                service=self.service_name,
                method=method,
                endpoint=endpoint,
                status_code=response.status_code,
            ).inc()

            REQUEST_DURATION.labels(
                service=self.service_name,
                method=method,
                endpoint=endpoint,
            ).observe(duration)

            return response
        except Exception:
            REQUEST_COUNT.labels(
                service=self.service_name,
                method=method,
                endpoint=endpoint,
                status_code=500,
            ).inc()
            raise
        finally:
            REQUESTS_IN_PROGRESS.labels(service=self.service_name).dec()


async def metrics_endpoint(request: Request) -> Response:
    """Prometheus metrics scrape endpoint — mount at GET /metrics."""
    return Response(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST,
    )
