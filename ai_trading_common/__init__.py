"""
AI Trading Common — shared observability, middleware, and platform utilities.

Services should pin a tagged version and import shared capabilities here rather
than vendoring per-service copies.
"""

__version__ = "0.3.0"

from ai_trading_common.logging_config import setup_logging, get_logger
from ai_trading_common.correlation import CorrelationMiddleware, get_correlation_headers, get_correlation_id
from ai_trading_common.errors import register_exception_handlers, CauseCategory
from ai_trading_common.health import health_router, DependencyCheck, configure_health
from ai_trading_common.metrics import MetricsMiddleware, metrics_endpoint
from ai_trading_common.sentry_setup import setup_sentry
from ai_trading_common.provider_routing import AccountState, ProviderAccount, ProviderAccountPool

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
    "CauseCategory",
    "setup_sentry",
    "AccountState",
    "ProviderAccount",
    "ProviderAccountPool",
]
