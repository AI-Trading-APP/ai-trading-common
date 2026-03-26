"""Shared logging setup for AI Trading App services."""

from __future__ import annotations

import logging
import os
import sys
from typing import Optional

import structlog


def setup_logging(service_name: str = "ai-trading-app", level: Optional[str] = None) -> None:
    """Configure stdlib logging and structlog with a shared service context."""
    log_level = (level or os.getenv("LOG_LEVEL", "INFO")).upper()
    numeric_level = getattr(logging, log_level, logging.INFO)

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=numeric_level,
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(numeric_level),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )

    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(service=service_name)


def get_logger(name: Optional[str] = None):
    """Return a structlog logger bound to the provided name."""
    return structlog.get_logger(name) if name else structlog.get_logger()
