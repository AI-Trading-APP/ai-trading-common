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
    "require_secret",
    "require_config",
    "sign_token",
    "decode_token",
]

_logger = logging.getLogger(__name__)


class SecretError(RuntimeError):
    """Raised when a required secret or config value is missing/invalid.

    Covers: unset/empty/whitespace-only values, known-leaked/placeholder
    literals (BLOCKLIST), and — for ``decode_token`` — the case where every
    candidate secret passed in is itself an invalid value (misconfiguration,
    as distinct from a bad/expired/tampered token, which raises the
    corresponding ``jwt.InvalidTokenError``/``jwt.ExpiredSignatureError``).
    """


# Known-leaked / placeholder secret literals, normalized via
# ``.strip().casefold()``. Some entries are "prefix-family" literals that
# must ALSO match as a case-insensitive substring of a longer value (e.g.
# regimeservice's "dev-only-<anything>-change-me" family) — substring
# matching for those specific entries is handled in ``require_secret``.
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
) -> str:
    """Fail loud on a missing/blank/known-leaked secret value.

    Invalid = ``None`` | ``""`` | whitespace-only | normalized value is a
    member of :data:`BLOCKLIST` (including a blocklisted prefix-family
    literal appearing as a case-insensitive substring of ``value``).

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

    if not valid_secrets:
        # Every candidate secret was itself invalid — this is a
        # misconfiguration, not a bad/expired/tampered token.
        raise SecretError(
            "decode_token: all candidate secrets are invalid; "
            f"{len(secret_errors)} secret(s) failed validation"
        )

    last_error: Exception | None = None
    for valid_secret in valid_secrets:
        try:
            return jwt.decode(
                token,
                valid_secret,
                algorithms=list(algorithms),
                options=decode_options,
            )
        except jwt.ExpiredSignatureError as exc:
            # A well-formed, correctly-signed-but-expired token: no other
            # secret in the rotation set would change the expiry outcome,
            # but keep trying in case a different secret is the actual
            # signer (still expired either way) — preserve the most
            # meaningful error to re-raise if nothing verifies.
            last_error = exc
        except jwt.InvalidTokenError as exc:
            last_error = exc

    # No candidate secret verified the token.
    assert last_error is not None
    raise last_error
