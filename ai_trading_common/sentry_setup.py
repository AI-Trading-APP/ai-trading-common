"""
Sentry error tracking integration for FastAPI services.

Usage:
    from ai_trading_common.sentry_setup import setup_sentry
    setup_sentry(dsn=os.getenv("SENTRY_DSN"), service_name="userservice")
"""

import os


def setup_sentry(
    dsn: str | None = None,
    service_name: str = "unknown",
    environment: str | None = None,
    version: str = "1.0.0",
):
    """Initialize Sentry SDK if a DSN is configured.

    Silently no-ops if dsn is empty/None or sentry_sdk is not installed,
    so services work fine without Sentry in local dev.
    """
    dsn = dsn or os.getenv("SENTRY_DSN", "")
    if not dsn:
        return

    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration
    except ImportError:
        # sentry_sdk not installed — skip silently
        return

    env = environment or os.getenv("SENTRY_ENVIRONMENT", "production")

    sentry_sdk.init(
        dsn=dsn,
        environment=env,
        traces_sample_rate=0.1,
        profiles_sample_rate=0.1,
        integrations=[
            FastApiIntegration(transaction_style="endpoint"),
            SqlalchemyIntegration(),
        ],
        before_send=_scrub_pii,
        release=f"{service_name}@{version}",
    )


def _scrub_pii(event, hint):
    """Remove sensitive data before sending to Sentry."""
    if "request" in event:
        req = event["request"]
        # Scrub headers
        headers = req.get("headers", {})
        for key in list(headers.keys()):
            if key.lower() in ("authorization", "cookie", "x-csrf-token"):
                headers[key] = "[FILTERED]"
        # Scrub body fields
        data = req.get("data")
        if isinstance(data, dict):
            for field in ("password", "token", "secret", "email"):
                if field in data:
                    data[field] = "[FILTERED]"
    return event
