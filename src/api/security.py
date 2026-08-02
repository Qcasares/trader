"""
security.py
-----------
Single-operator authentication.

Deliberately small. There is no user table, no registration, no password reset
— one operator, one bcrypt-hashed password in the environment, and an
HMAC-signed session cookie. Adding a user model before there is a second user
would be inventing an attack surface to defend.

Sessions are stateless and signed rather than stored, so a restart does not log
you out and there is no session table to leak. The trade-off is that a session
cannot be revoked individually before it expires; rotating ``SESSION_SECRET``
invalidates all of them at once, which for one operator is the right blunt
instrument.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import secrets
import time
from dataclasses import dataclass

import bcrypt

logger = logging.getLogger(__name__)

SESSION_COOKIE = "trader_session"


class AuthError(Exception):
    """Authentication failed."""


@dataclass(frozen=True, slots=True)
class Session:
    subject: str
    issued_at: int
    expires_at: int

    @property
    def is_expired(self) -> bool:
        return time.time() >= self.expires_at


def hash_password(password: str) -> str:
    """Produce a bcrypt hash for ADMIN_PASSWORD_HASH."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, stored_hash: str) -> bool:
    """
    Check a password against its bcrypt hash.

    bcrypt's comparison is already constant-time. A malformed stored hash
    returns False rather than raising, so a misconfigured deployment fails
    closed instead of 500-ing in a way that distinguishes it from a wrong
    password.
    """
    try:
        return bcrypt.checkpw(password.encode("utf-8"), stored_hash.encode("utf-8"))
    except (ValueError, TypeError) as exc:
        logger.error("ADMIN_PASSWORD_HASH is not a valid bcrypt hash: %s", exc)
        return False


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def issue_session(secret: str, subject: str = "operator", ttl: int = 43200) -> str:
    """Create a signed session token."""
    now = int(time.time())
    payload = {"sub": subject, "iat": now, "exp": now + ttl}
    body = _b64encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signature = hmac.new(
        secret.encode("utf-8"), body.encode("ascii"), hashlib.sha256
    ).digest()
    return f"{body}.{_b64encode(signature)}"


def verify_session(secret: str, token: str) -> Session:
    """
    Validate a session token and return its claims.

    Raises :class:`AuthError` on a bad signature, malformed token, or expiry.
    The signature is checked before the payload is parsed, so untrusted JSON is
    never deserialised on an unauthenticated path.
    """
    if not token or "." not in token:
        raise AuthError("malformed session token")

    body, _, provided = token.partition(".")
    expected = hmac.new(
        secret.encode("utf-8"), body.encode("ascii"), hashlib.sha256
    ).digest()
    try:
        provided_raw = _b64decode(provided)
    except (ValueError, base64.binascii.Error) as exc:  # type: ignore[attr-defined]
        raise AuthError("malformed session signature") from exc

    if not hmac.compare_digest(expected, provided_raw):
        raise AuthError("invalid session signature")

    try:
        payload = json.loads(_b64decode(body))
    except (ValueError, KeyError) as exc:
        raise AuthError("malformed session payload") from exc

    session = Session(
        subject=str(payload.get("sub", "")),
        issued_at=int(payload.get("iat", 0)),
        expires_at=int(payload.get("exp", 0)),
    )
    if session.is_expired:
        raise AuthError("session expired")
    return session


def constant_time_equals(a: str, b: str) -> bool:
    """Compare two strings without leaking length-prefix timing."""
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


def new_confirmation_token() -> str:
    """
    A short token the UI must echo back to confirm a dangerous action.

    Used for kill-switch release and (later) deployment enable. The point is
    not cryptographic — it is to make the action deliberate rather than a
    misclick, and to give the audit log something to record.
    """
    return secrets.token_urlsafe(8)
