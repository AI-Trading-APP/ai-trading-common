"""Shared logging setup for AI Trading App services."""

from __future__ import annotations

import logging
import os
import sys
from typing import Optional

import structlog

# Keys whose values must never appear in logs. A log event field whose name
# CONTAINS any of these (case-insensitive substring) has its value replaced
# with ``***MASKED***`` when PII masking is enabled. Ported into the shared
# lib from ScreenerService's vendored copy in v0.4.2 (opt-in — see
# ``setup_logging(..., mask_pii=...)``).
_MASKED_KEYS = frozenset(
    {"password", "secret", "token", "authorization", "cookie", "email", "ssn"}
)


def _mask_pii(_logger, _method_name, event_dict):
    """structlog processor: replace sensitive field values with ***MASKED***."""
    for key in list(event_dict.keys()):
        lowered = key.lower()
        if any(masked in lowered for masked in _MASKED_KEYS):
            event_dict[key] = "***MASKED***"
    return event_dict


def setup_logging(
    service_name: str = "ai-trading-app",
    level: Optional[str] = None,
    *,
    mask_pii: bool = False,
) -> None:
    """Configure stdlib logging and structlog with a shared service context.

    ``mask_pii`` (opt-in, default ``False``, v0.4.2): when ``True``, inserts a
    processor that masks the value of any log field whose name contains a
    known-sensitive token (password/secret/token/authorization/cookie/email/
    ssn). Default is ``False`` so existing consumers' log output is unchanged;
    a service that wants the guarantee (e.g. ScreenerService) opts in.
    """
    log_level = (level or os.getenv("LOG_LEVEL", "INFO")).upper()
    numeric_level = getattr(logging, log_level, logging.INFO)

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=numeric_level,
    )

    processors = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]
    # Mask right before rendering so masking applies to the fully-merged event
    # (contextvars + call-site kwargs), regardless of where a field entered.
    if mask_pii:
        processors.append(_mask_pii)
    processors.append(structlog.processors.JSONRenderer())

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(numeric_level),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )

    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(service=service_name)


def get_logger(name: Optional[str] = None):
    """Return a structlog logger bound to the provided name."""
    return structlog.get_logger(name) if name else structlog.get_logger()
