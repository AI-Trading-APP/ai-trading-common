"""Contract-conformance + wire-parity tests for ai_trading_common.security.

Guards the frozen API boundary declared in
``specs/audit-remediation/security-platform-lib/contracts/ai-trading-common-security.md``.
Any signature drift here is a contract violation requiring a contract
amendment + Phase-2 re-sign-off, per the contract file's own header.

Two distinct checks:
 1. Signature conformance — inspect.signature() on all 5 public symbols,
    asserting param names/defaults/order match the frozen contract verbatim.
 2. Wire-parity (both directions) — a token minted with raw PyJWT.encode
    (pre-rewire style) decodes via decode_token, and a token minted via
    sign_token decodes via raw PyJWT.decode — proving byte-identical wire
    format (US-1 AC, US-2 AC "no wire-format regression").
"""

from __future__ import annotations

import inspect
import time

import jwt

from ai_trading_common.security import (
    BLOCKLIST,
    SecretError,
    decode_token,
    require_config,
    require_secret,
    sign_token,
)

SECRET = "a-genuinely-random-looking-secret-value-123"


# --- 1. Signature conformance ------------------------------------------------


def test_secret_error_is_a_runtime_error_subclass() -> None:
    assert issubclass(SecretError, RuntimeError)


def test_blocklist_is_a_frozenset_of_strings() -> None:
    assert isinstance(BLOCKLIST, frozenset)
    assert all(isinstance(item, str) for item in BLOCKLIST)


def test_require_secret_signature_matches_contract() -> None:
    sig = inspect.signature(require_secret)
    params = list(sig.parameters.values())

    assert params[0].name == "value"
    assert params[0].kind == inspect.Parameter.POSITIONAL_OR_KEYWORD
    assert params[0].default is inspect.Parameter.empty

    kwonly = {p.name: p for p in params[1:]}
    assert all(p.kind == inspect.Parameter.KEYWORD_ONLY for p in kwonly.values())

    assert kwonly["name"].default == "secret"
    assert kwonly["allow_insecure"].default is False

    assert list(kwonly.keys()) == ["name", "allow_insecure"]


def test_require_config_signature_matches_contract() -> None:
    sig = inspect.signature(require_config)
    params = list(sig.parameters.values())

    assert params[0].name == "value"
    assert params[0].kind == inspect.Parameter.POSITIONAL_OR_KEYWORD
    assert params[0].default is inspect.Parameter.empty

    kwonly = {p.name: p for p in params[1:]}
    assert all(p.kind == inspect.Parameter.KEYWORD_ONLY for p in kwonly.values())

    # `name` is required (no default) per the contract signature.
    assert kwonly["name"].default is inspect.Parameter.empty
    assert kwonly["allow_missing"].default is False

    assert list(kwonly.keys()) == ["name", "allow_missing"]


def test_sign_token_signature_matches_contract() -> None:
    sig = inspect.signature(sign_token)
    params = list(sig.parameters.values())

    assert params[0].name == "claims"
    assert params[0].kind == inspect.Parameter.POSITIONAL_OR_KEYWORD
    assert params[0].default is inspect.Parameter.empty

    assert params[1].name == "secret"
    assert params[1].kind == inspect.Parameter.POSITIONAL_OR_KEYWORD
    assert params[1].default is inspect.Parameter.empty

    kwonly = {p.name: p for p in params[2:]}
    assert all(p.kind == inspect.Parameter.KEYWORD_ONLY for p in kwonly.values())

    assert kwonly["algorithm"].default == "HS256"
    assert kwonly["expires_in"].default is None

    assert list(kwonly.keys()) == ["algorithm", "expires_in"]


def test_decode_token_signature_matches_contract() -> None:
    sig = inspect.signature(decode_token)
    params = list(sig.parameters.values())

    assert params[0].name == "token"
    assert params[0].kind == inspect.Parameter.POSITIONAL_OR_KEYWORD
    assert params[0].default is inspect.Parameter.empty

    assert params[1].name == "secrets"
    assert params[1].kind == inspect.Parameter.POSITIONAL_OR_KEYWORD
    assert params[1].default is inspect.Parameter.empty

    kwonly = {p.name: p for p in params[2:]}
    assert all(p.kind == inspect.Parameter.KEYWORD_ONLY for p in kwonly.values())

    assert kwonly["algorithms"].default == ("HS256",)
    assert kwonly["verify_exp"].default is True
    assert kwonly["options"].default is None

    assert list(kwonly.keys()) == ["algorithms", "verify_exp", "options"]


# --- 2. Wire-parity (both directions) ---------------------------------------


def test_raw_pyjwt_minted_token_decodes_via_decode_token() -> None:
    # Simulates a pre-rewire service (e.g. userservice pre-adoption) that
    # still mints tokens with raw PyJWT directly.
    exp = int(time.time()) + 60
    raw_token = jwt.encode({"sub": "legacy-user", "exp": exp}, SECRET, algorithm="HS256")

    claims = decode_token(raw_token, SECRET)

    assert claims["sub"] == "legacy-user"
    assert claims["exp"] == exp


def test_sign_token_minted_token_decodes_via_raw_pyjwt() -> None:
    # Simulates a rewired service's token being verified by a not-yet-rewired
    # consumer still calling raw PyJWT.decode directly.
    our_token = sign_token({"sub": "new-user"}, SECRET, expires_in=60)

    claims = jwt.decode(our_token, SECRET, algorithms=["HS256"])

    assert claims["sub"] == "new-user"
    assert "exp" in claims
