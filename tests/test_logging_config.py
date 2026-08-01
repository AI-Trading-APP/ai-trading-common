"""Tests for ai_trading_common.logging_config — opt-in PII masking (v0.4.2)."""

from __future__ import annotations

from ai_trading_common.logging_config import _mask_pii, get_logger, setup_logging


def test_mask_pii_processor_masks_sensitive_keys() -> None:
    event = {
        "password": "hunter2",
        "access_token": "abc",
        "user_email": "a@b.com",
        "Authorization": "Bearer x",
        "user": "alice",
        "count": 3,
    }
    out = _mask_pii(None, None, dict(event))
    assert out["password"] == "***MASKED***"
    assert out["access_token"] == "***MASKED***"
    assert out["user_email"] == "***MASKED***"  # substring match on "email"
    assert out["Authorization"] == "***MASKED***"  # case-insensitive
    # Non-sensitive fields untouched
    assert out["user"] == "alice"
    assert out["count"] == 3


def test_setup_logging_mask_pii_true_masks_output(capsys) -> None:
    setup_logging("test-svc", mask_pii=True)
    get_logger().info("login", email="a@b.com", secret_key="s3cr3t", user_id=1)
    out = capsys.readouterr().out
    assert "***MASKED***" in out
    assert "a@b.com" not in out
    assert "s3cr3t" not in out
    # Non-sensitive field survives
    assert "user_id" in out


def test_setup_logging_default_does_not_mask(capsys) -> None:
    # Default mask_pii=False → existing consumers' log output is unchanged.
    setup_logging("test-svc")
    get_logger().info("login", email="a@b.com")
    out = capsys.readouterr().out
    assert "a@b.com" in out
    assert "***MASKED***" not in out
