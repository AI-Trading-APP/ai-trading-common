from __future__ import annotations

import logging
import os
from typing import Any

import structlog

_ALLOWED_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR"}
_ALLOWED_LOG_FORMATS = {"json", "text"}
_CURRENT_SERVICE_NAME: str | None = None

_PII_KEYWORDS = (
    "password",
    "passwd",
    "secret",
    "token",
    "authorization",
    "cookie",
    "email",
    "ssn",
    "api_key",
    "apikey",
    "phone",
)


def _should_mask_key(key: str) -> bool:
    normalized_key = key.lower()
    return any(keyword in normalized_key for keyword in _PII_KEYWORDS)


def _mask_pii(value: Any) -> Any:
    if isinstance(value, dict):
        masked: dict[str, Any] = {}
        for key, item in value.items():
            if _should_mask_key(key):
                masked[key] = "***"
            else:
                masked[key] = _mask_pii(item)
        return masked

    if isinstance(value, list):
        return [_mask_pii(item) for item in value]

    if isinstance(value, tuple):
        return tuple(_mask_pii(item) for item in value)

    return value


def _mask_pii_processor(
    logger: logging.Logger,
    method_name: str,
    event_dict: structlog.typing.EventDict,
) -> structlog.typing.EventDict:
    del method_name

    service_name = event_dict.get("service") or _CURRENT_SERVICE_NAME
    if service_name:
        event_dict.setdefault("service", service_name)

    logger_name = getattr(logger, "name", None)
    if logger_name:
        event_dict.setdefault("logger_name", logger_name)

    correlation_id = structlog.contextvars.get_contextvars().get("correlation_id")
    event_dict.setdefault("correlation_id", correlation_id)

    return _mask_pii(event_dict)


def _resolve_log_level() -> int:
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    if level_name not in _ALLOWED_LOG_LEVELS:
        level_name = "INFO"
    return getattr(logging, level_name, logging.INFO)


def _resolve_log_format() -> str:
    log_format = os.getenv("LOG_FORMAT", "json").lower()
    if log_format not in _ALLOWED_LOG_FORMATS:
        return "json"
    return log_format


def _renderer() -> structlog.typing.Processor:
    if _resolve_log_format() == "text":
        return structlog.dev.ConsoleRenderer()
    return structlog.processors.JSONRenderer()


def setup_logging(service_name: str) -> None:
    global _CURRENT_SERVICE_NAME
    _CURRENT_SERVICE_NAME = service_name

    logging.basicConfig(
        level=_resolve_log_level(),
        format="%(message)s",
        force=True,
    )

    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.stdlib.add_log_level,
            _mask_pii_processor,
            _renderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(_resolve_log_level()),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(
    logger_name: str | None = None,
) -> structlog.typing.FilteringBoundLogger:
    logger = structlog.get_logger(logger_name)
    if _CURRENT_SERVICE_NAME:
        return logger.bind(service=_CURRENT_SERVICE_NAME)
    return logger
