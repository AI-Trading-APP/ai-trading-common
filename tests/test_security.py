"""Unit tests for ai_trading_common.security — guard + rotation-safe JWT.

One test per condition enumerated in the F1-LIB-UNIT roadmap ticket /
contract Security Verification Table:

 1. require_secret(None)                     -> SecretError
 2. require_secret("")                       -> SecretError
 3. require_secret("   ")                    -> SecretError
 4. require_secret(<each BLOCKLIST literal>) -> SecretError (parametrized)
 5. require_secret("dev-only-regime-change-me") (prefix-family substring)   -> SecretError
 6. require_secret(<valid value>)            -> returns value unchanged
 7. require_secret(<invalid>, allow_insecure=True) -> WARNING logged, returns value (no raise)
 8. require_config unset -> SecretError; allow_missing=True -> bypass
 9. sign_token / decode_token round-trip
10. decode_token([S_old, S_new]) accepts a token signed with either
11. expired token -> jwt.ExpiredSignatureError
12. tampered token -> jwt.InvalidTokenError
13. decode_token with an all-invalid secrets list -> SecretError
"""

from __future__ import annotations

import logging
import time

import jwt
import pytest

from ai_trading_common.security import (
    BLOCKLIST,
    SecretError,
    decode_token,
    require_config,
    require_secret,
    sign_token,
)

VALID_SECRET = "a-genuinely-random-looking-secret-value-123"


# --- 1-3: require_secret basic invalid inputs ------------------------------


def test_require_secret_none_raises() -> None:
    with pytest.raises(SecretError):
        require_secret(None, name="jwt-secret")


def test_require_secret_empty_string_raises() -> None:
    with pytest.raises(SecretError):
        require_secret("", name="jwt-secret")


def test_require_secret_whitespace_only_raises() -> None:
    with pytest.raises(SecretError):
        require_secret("   \t\n  ", name="jwt-secret")


# --- 4: every BLOCKLIST literal, parametrized -------------------------------


@pytest.mark.parametrize("literal", sorted(BLOCKLIST))
def test_require_secret_blocklist_literal_raises(literal: str) -> None:
    with pytest.raises(SecretError):
        require_secret(literal, name="jwt-secret")


@pytest.mark.parametrize(
    "variant",
    [
        "CHANGE_ME",
        "Change-Me",
        "  changeme  ",
        "PLACEHOLDER",
    ],
)
def test_require_secret_blocklist_case_and_whitespace_insensitive(variant: str) -> None:
    with pytest.raises(SecretError):
        require_secret(variant, name="jwt-secret")


# --- 5: prefix-family substring match --------------------------------------


def test_require_secret_prefix_family_substring_raises() -> None:
    # "dev-only-regime-change-me" is not a literal BLOCKLIST member, but
    # matches the "dev-only-...-change-me" family (regimeservice pattern).
    with pytest.raises(SecretError):
        require_secret("dev-only-regime-change-me", name="jwt-secret")


# --- 6: valid value passes through ------------------------------------------


def test_require_secret_valid_value_passes_through() -> None:
    assert require_secret(VALID_SECRET, name="jwt-secret") == VALID_SECRET


# --- 7: allow_insecure=True downgrades to WARNING + return -----------------


def test_require_secret_allow_insecure_logs_warning_and_returns(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING, logger="ai_trading_common.security")
    result = require_secret("placeholder", name="jwt-secret", allow_insecure=True)
    assert result == "placeholder"
    assert any(
        record.levelno == logging.WARNING and "jwt-secret" in record.message
        for record in caplog.records
    )


# --- 8: require_config -------------------------------------------------------


def test_require_config_unset_raises() -> None:
    with pytest.raises(SecretError):
        require_config(None, name="jwks-url")


def test_require_config_empty_raises() -> None:
    with pytest.raises(SecretError):
        require_config("", name="jwks-url")


def test_require_config_allow_missing_bypasses() -> None:
    assert require_config(None, name="jwks-url", allow_missing=True) == ""
    assert require_config("", name="jwks-url", allow_missing=True) == ""


def test_require_config_no_blocklist_check() -> None:
    # require_config performs NO blocklist check — a value that would be
    # rejected by require_secret must pass through require_config untouched.
    assert require_config("placeholder", name="some-url") == "placeholder"


def test_require_config_valid_value_passes_through() -> None:
    assert require_config("https://issuer.example.com/.well-known/jwks.json", name="jwks-url") == (
        "https://issuer.example.com/.well-known/jwks.json"
    )


# --- 9: sign_token / decode_token round trip --------------------------------


def test_sign_and_decode_round_trip() -> None:
    token = sign_token({"sub": "user-1", "role": "admin"}, VALID_SECRET)
    claims = decode_token(token, VALID_SECRET)
    assert claims["sub"] == "user-1"
    assert claims["role"] == "admin"


def test_sign_token_with_expires_in_adds_exp_claim() -> None:
    before = int(time.time())
    token = sign_token({"sub": "user-1"}, VALID_SECRET, expires_in=60)
    claims = decode_token(token, VALID_SECRET)
    assert claims["exp"] >= before + 60
    assert claims["sub"] == "user-1"


def test_sign_token_preserves_claims_verbatim() -> None:
    claims_in = {"sub": "user-1", "custom": {"nested": True}, "n": 42}
    token = sign_token(claims_in, VALID_SECRET)
    claims_out = decode_token(token, VALID_SECRET)
    for key, value in claims_in.items():
        assert claims_out[key] == value


def test_sign_token_invalid_secret_raises() -> None:
    with pytest.raises(SecretError):
        sign_token({"sub": "user-1"}, "placeholder")


# --- 10: rotation window — decode accepts either of [S_old, S_new] ---------


def test_decode_token_rotation_window_accepts_old_secret() -> None:
    s_old = "old-secret-value-abcdefghijklmnop"
    s_new = "new-secret-value-qrstuvwxyz123456"
    token_signed_with_old = sign_token({"sub": "svc-a"}, s_old)
    claims = decode_token(token_signed_with_old, [s_old, s_new])
    assert claims["sub"] == "svc-a"


def test_decode_token_rotation_window_accepts_new_secret() -> None:
    s_old = "old-secret-value-abcdefghijklmnop"
    s_new = "new-secret-value-qrstuvwxyz123456"
    token_signed_with_new = sign_token({"sub": "svc-b"}, s_new)
    claims = decode_token(token_signed_with_new, [s_old, s_new])
    assert claims["sub"] == "svc-b"


# --- 11: expired token -------------------------------------------------------


def test_decode_token_expired_raises_expired_signature_error() -> None:
    token = sign_token({"sub": "user-1"}, VALID_SECRET, expires_in=-10)
    with pytest.raises(jwt.ExpiredSignatureError):
        decode_token(token, VALID_SECRET)


# --- 12: tampered token -------------------------------------------------------


def test_decode_token_tampered_raises_invalid_token_error() -> None:
    token = sign_token({"sub": "user-1"}, VALID_SECRET)
    tampered = token[:-2] + ("aa" if not token.endswith("aa") else "bb")
    with pytest.raises(jwt.InvalidTokenError):
        decode_token(tampered, VALID_SECRET)


def test_decode_token_wrong_secret_raises_invalid_token_error() -> None:
    token = sign_token({"sub": "user-1"}, VALID_SECRET)
    with pytest.raises(jwt.InvalidTokenError):
        decode_token(token, "a-completely-different-secret-value")


# --- 13: all-invalid secrets list -> SecretError ---------------------------


def test_decode_token_all_invalid_secrets_raises_secret_error() -> None:
    token = sign_token({"sub": "user-1"}, VALID_SECRET)
    with pytest.raises(SecretError):
        decode_token(token, ["placeholder", "", "changeme"])
