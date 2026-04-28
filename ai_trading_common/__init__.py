"""
AI Trading Common — shared observability + middleware for all backend
services in the AI-Trading-APP organisation.

Public API (v0.2):

    from ai_trading_common import (
        # Logging
        setup_logging, get_logger,
        # Correlation IDs
        CorrelationMiddleware, get_correlation_headers, get_correlation_id,
        # Health
        health_router, DependencyCheck, configure_health,
        # Metrics
        MetricsMiddleware, metrics_endpoint,
        # Errors
        register_exception_handlers,
        # Sentry
        setup_sentry,
    )

Each service should:
1. Pin a tagged version in `requirements.txt`, e.g.:
   `ai-trading-common @ git+https://github.com/AI-Trading-APP/ai-trading-common.git@v0.2.0`
2. Import from this package rather than re-implementing inline.
3. Avoid vendoring: per-service copies drift and defeat the point of a
   shared package.
"""

__version__ = "0.2.2"

from ai_trading_common.logging_config import setup_logging, get_logger
from ai_trading_common.correlation import CorrelationMiddleware, get_correlation_headers, get_correlation_id
from ai_trading_common.errors import register_exception_handlers
from ai_trading_common.health import health_router, DependencyCheck, configure_health
from ai_trading_common.metrics import MetricsMiddleware, metrics_endpoint
from ai_trading_common.sentry_setup import setup_sentry

__all__ = [
    "setup_logging",
    "get_logger",
    "CorrelationMiddleware",
    "get_correlation_headers",
    "get_correlation_id",
    "health_router",
    "DependencyCheck",
    "configure_health",
    "MetricsMiddleware",
    "metrics_endpoint",
    "register_exception_handlers",
    "setup_sentry",
]
