"""
Shared, fail-loud secret guards + rotation-safe JWT helpers (F1 Audit
Remediation Program — ADR-002, ADR-003).

Public API (frozen contract:
``specs/audit-remediation/security-platform-lib/contracts/ai-trading-common-security.md``):

    from ai_trading_common.security import (
        SecretError,
        BLOCKLIST,
        require_secret,
        require_config,
        sign_token,
        decode_token,
    )

Design invariant (ADR-002): this module is **function-first and
env-var-name-agnostic** — it never reads an environment variable itself.
Every caller passes the already-resolved value (e.g. ``os.getenv("JWT_SECRET_KEY")``)
in from the outside. This kills the "which env var name does this service
actually use" drift trap (TIA/regimeservice name-drift incidents) because
the module has no opinion on naming at all — it only validates/signs/verifies
the value it's handed.

Rotation (ADR-003): ``decode_token`` accepts a single secret OR an ordered
sequence of secrets and returns claims on the FIRST one that verifies. This
is the zero-downtime rotation-window mechanism — during a rotation, callers
pass ``[S_old, S_new]`` so a verifier accepts tokens signed by either secret
while issuers flip over one at a time.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Mapping, Sequence

import jwt

__all__ = [
    "SecretError",
    "BLOCKLIST",
    "MIN_SECRET_BYTES",
    "require_secret",
    "require_config",
    "sign_token",
    "decode_token",
]

_logger = logging.getLogger(__name__)

# Minimum acceptable secret length, in UTF-8 bytes. RFC 7518 §3.2 requires an
# HMAC key at least as long as the hash output — 256 bits / 32 bytes for
# HS256 — so ``require_secret`` rejects anything below this by default
# (v0.4.1), closing the "weak-but-not-blocklisted secret slips through" gap.
MIN_SECRET_BYTES: int = 32


class SecretError(RuntimeError):
    """Raised when a required secret or config value is missing/invalid.

    Covers: unset/empty/whitespace-only values, known-leaked/placeholder
    literals (BLOCKLIST), and — for ``decode_token`` — the case where every
    candidate secret passed in is itself an invalid value (misconfiguration,
    as distinct from a bad/expired/tampered token, which raises the
    corresponding ``jwt.InvalidTokenError``/``jwt.ExpiredSignatureError``).
    """


# Known-leaked / placeholder secret literals, normalized via
# ``.strip().casefold()``. Matching against this exact set is done in
# ``_is_blocklisted``. Separately, some insecure literals come in a whole
# FAMILY sharing a fixed prefix AND suffix (e.g. regimeservice's
# "dev-only-<anything>-change-me"); those are matched by the
# prefix+suffix-anchored patterns in ``_PREFIX_SUFFIX_FAMILIES`` — anchored
# at both ends of the value, NOT a free-floating substring match.
BLOCKLIST: frozenset[str] = frozenset(
    {
        "your-secret-key-change-in-production",
        "your-secret-key",
        "dev-only-change-me",
        "change-me-app-v1",
        "dev-secret",
        "change-me",
        "changeme",
        "placeholder",
        "change_me",  # CHANGE_ME normalized via casefold
        "local-dev-secret-key-for-testing-only",
    }
)

# "Prefix-family" patterns — a BLOCKLIST member like "dev-only-change-me"
# represents an entire FAMILY of insecure literals sharing a prefix/suffix
# shape (regimeservice ships variants like "dev-only-regime-change-me",
# "dev-only-<anything>-change-me"), not just the one exact string. Each
# entry here is (prefix, suffix); a normalized value matches the family if
# it starts with the prefix AND ends with the suffix (arbitrary content in
# between), which also covers the canonical exact literal itself.
_PREFIX_SUFFIX_FAMILIES: tuple[tuple[str, str], ...] = (
    ("dev-only-", "change-me"),
)


def _normalize(value: str) -> str:
    return value.strip().casefold()


def _is_blocklisted(normalized_value: str) -> bool:
    if normalized_value in BLOCKLIST:
        return True
    for prefix, suffix in _PREFIX_SUFFIX_FAMILIES:
        if normalized_value.startswith(prefix) and normalized_value.endswith(suffix):
            return True
    return False


def require_secret(
    value: str | None,
    *,
    name: str = "secret",
    allow_insecure: bool = False,
    min_length: int = MIN_SECRET_BYTES,
) -> str:
    """Fail loud on a missing/blank/known-leaked/too-short secret value.

    Invalid = ``None`` | ``""`` | whitespace-only | normalized value matches
    :data:`BLOCKLIST` (an exact normalized member, OR a normalized
    prefix-family pattern — see :data:`_PREFIX_SUFFIX_FAMILIES` — anchored at
    BOTH the start and the end of the value, e.g.
    ``"dev-only-regime-change-me"``) | fewer than ``min_length`` UTF-8 bytes.

    The minimum-length guard (``min_length``, default
    :data:`MIN_SECRET_BYTES` = 32 bytes) rejects weak-but-not-blocklisted
    secrets: RFC 7518 §3.2 requires an HMAC key at least as long as the hash
    output (256 bits / 32 bytes for HS256), so anything shorter is
    cryptographically weak regardless of the blocklist. Length is measured in
    UTF-8 BYTES (not Unicode code points) to match the actual HMAC key
    material. Pass ``min_length=0`` to disable the check for a caller that
    legitimately needs it (rare).

    Raises :class:`SecretError` on invalid, UNLESS ``allow_insecure=True``
    (intended only for an explicit local/test escape hatch) — in that case
    logs a WARNING and returns ``value`` instead of raising.
    """
    invalid_reason: str | None = None
    normalized = ""
    if value is None:
        invalid_reason = "missing (None)"
    elif value.strip() == "":
        invalid_reason = "empty or whitespace-only"
    else:
        normalized = _normalize(value)
        if _is_blocklisted(normalized):
            invalid_reason = "known-leaked/placeholder value (blocklisted)"
        elif len(value.encode("utf-8")) < min_length:
            invalid_reason = (
                f"too short ({len(value.encode('utf-8'))} bytes; "
                f"minimum is {min_length} bytes for a secure HMAC key)"
            )

    if invalid_reason is None:
        return value  # type: ignore[return-value]  # value is guaranteed str here

    if allow_insecure:
        _logger.warning(
            "require_secret: %s is invalid (%s) but allow_insecure=True — "
            "proceeding with an insecure value. This must never be set in "
            "a real deployment.",
            name,
            invalid_reason,
        )
        return value  # type: ignore[return-value]

    raise SecretError(f"{name}: invalid secret ({invalid_reason})")


def require_config(
    value: str | None,
    *,
    name: str,
    allow_missing: bool = False,
) -> str:
    """Fail loud on a missing/blank required (non-secret) config value.

    Unlike :func:`require_secret`, this performs NO blocklist check — it is
    for required config that is not itself a secret (e.g. a JWKS URL,
    REQ-009).

    Raises :class:`SecretError` on unset/empty UNLESS ``allow_missing=True``.
    """
    if value is not None and value.strip() != "":
        return value

    if allow_missing:
        return value if value is not None else ""

    reason = "missing (None)" if value is None else "empty or whitespace-only"
    raise SecretError(f"{name}: required config value is {reason}")


def sign_token(
    claims: Mapping[str, Any],
    secret: str,
    *,
    algorithm: str = "HS256",
    expires_in: int | None = None,
) -> str:
    """PyJWT-equivalent encode. Preserves caller claims verbatim.

    If ``expires_in`` is set, adds ``exp = now + expires_in`` (seconds) to
    the claims before encoding. Calls :func:`require_secret` internally —
    raises :class:`SecretError` if ``secret`` is invalid.
    """
    validated_secret = require_secret(secret, name="signing-secret")

    payload = dict(claims)
    if expires_in is not None:
        payload["exp"] = int(time.time()) + expires_in

    return jwt.encode(payload, validated_secret, algorithm=algorithm)


def decode_token(
    token: str,
    secrets: str | Sequence[str],
    *,
    algorithms: Sequence[str] = ("HS256",),
    verify_exp: bool = True,
    options: dict | None = None,
) -> dict:
    """Decode+verify ``token`` against one or more candidate secrets.

    ``secrets`` is either a single secret string or an ordered sequence of
    secrets (the rotation-window mechanism, ADR-003) — each candidate is
    tried in order and claims are returned on the FIRST that verifies.

    Raises ``jwt.InvalidTokenError``/``jwt.ExpiredSignatureError`` (unchanged
    PyJWT wire semantics) if NO candidate secret verifies a well-formed
    token. Raises :class:`SecretError` if ALL candidate secrets are
    themselves invalid VALUES (misconfiguration, not a bad token).

    Multi-secret error precedence (expired-beats-invalid): PyJWT only
    reaches the ``exp`` check after a candidate's signature verifies, so an
    ``ExpiredSignatureError`` on ANY candidate proves that candidate is the
    token's genuine signer — the token is validly-ours but expired. If no
    candidate verifies outright, and at least one candidate raised
    ``ExpiredSignatureError``, that verdict is raised in preference to any
    ``InvalidSignatureError``/other ``InvalidTokenError`` seen on the other
    candidates (regardless of try order) — never "whichever candidate was
    tried last". This matters specifically for the rotation window
    (``[S_old, S_new]``): a token signed by ``S_old`` that has since expired
    must not be masked as a generic invalid token just because it also
    fails to verify against ``S_new``, since refresh handlers key off
    ``ExpiredSignatureError`` to trigger re-issuance.
    """
    candidates: list[str] = [secrets] if isinstance(secrets, str) else list(secrets)

    decode_options = dict(options) if options else {}
    decode_options.setdefault("verify_exp", verify_exp)

    valid_secrets: list[str] = []
    secret_errors: list[SecretError] = []
    for candidate in candidates:
        try:
            valid_secrets.append(require_secret(candidate, name="verification-secret"))
        except SecretError as exc:
            secret_errors.append(exc)

    # A candidate secret rejected as invalid (e.g. a legacy rotation secret
    # shorter than the 32-byte floor) while OTHER candidates are still valid
    # would otherwise be dropped silently — during a short→long rotation
    # window that means tokens signed by the dropped secret fail with an
    # opaque InvalidSignatureError and no diagnostic. Log it loudly so the
    # operator can see a candidate was skipped, without weakening the guard.
    if secret_errors and valid_secrets:
        _logger.warning(
            "decode_token: %d of %d candidate secret(s) were rejected as "
            "invalid and skipped during verification (%s). If this is a "
            "rotation window, tokens signed by a skipped secret will fail to "
            "verify — confirm every active signing secret meets the guard.",
            len(secret_errors),
            len(candidates),
            "; ".join(str(e) for e in secret_errors),
        )

    if not valid_secrets:
        # Every candidate secret was itself invalid — this is a
        # misconfiguration, not a bad/expired/tampered token.
        raise SecretError(
            "decode_token: all candidate secrets are invalid; "
            f"{len(secret_errors)} secret(s) failed validation"
        )

    # Error precedence across the candidate loop (SEV-3 fix, ADR-003):
    # PyJWT only reaches the ``exp`` check AFTER the signature verifies, so
    # ``ExpiredSignatureError`` from any candidate means that candidate's
    # secret IS the token's genuine signer — the token is validly-ours but
    # expired. That fact must never be shadowed by a LATER candidate's
    # ``InvalidSignatureError`` (a mismatched secret, which carries no
    # information once we already know who signed it). We therefore keep
    # looping (in case an EARLIER-tried secret was merely the wrong one and
    # a later one turns out to verify cleanly), but once any candidate
    # yields "expired", that verdict wins over any invalid-signature verdict
    # seen on other candidates — expired-beats-invalid, not last-wins. This
    # is required for the refresh-handler flow, which catches
    # ``ExpiredSignatureError`` specifically to trigger re-issuance during a
    # secret rotation window; masking it as a generic invalid token breaks
    # zero-downtime rotation.
    expired_error: jwt.ExpiredSignatureError | None = None
    last_invalid_error: jwt.InvalidTokenError | None = None
    for valid_secret in valid_secrets:
        try:
            return jwt.decode(
                token,
                valid_secret,
                algorithms=list(algorithms),
                options=decode_options,
            )
        except jwt.ExpiredSignatureError as exc:
            expired_error = exc
        except jwt.InvalidTokenError as exc:
            last_invalid_error = exc

    # No candidate secret verified the token. Prefer a genuine
    # "validly-signed-but-expired" verdict over a mere "no secret matched"
    # verdict from a different candidate.
    if expired_error is not None:
        raise expired_error
    assert last_invalid_error is not None
    raise last_invalid_error
