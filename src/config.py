"""
config.py
---------
Typed settings from the environment.

Two safety properties are enforced here rather than left to discipline:

- ``live_trading_enabled`` defaults to ``False`` and is the *outer* of two
  gates. The inner gate is the database kill switch. Flipping the DB flag needs
  only API access; flipping this one needs a redeploy. Both must permit trading
  before a live order can leave the building.
- ``alpaca_allow_live`` is a third, independent flag. It exists because a
  derived gate is not a gate: deriving it from ``live_trading_enabled`` — as
  the broker factory once did — reduced three documented conditions to two.
  Each must now be set by a separate deliberate act.
- ``session_secret`` has no default. A signing key with a fallback value is a
  signing key an attacker already knows, so the app refuses to start without
  one rather than quietly using a placeholder.
"""

from __future__ import annotations

import functools
import logging
import os
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


class ConfigError(RuntimeError):
    """A required setting is missing or invalid."""


def _bool_env(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer, got {raw!r}") from exc


@dataclass(frozen=True, slots=True)
class Settings:
    """Runtime configuration."""

    database_url: str
    session_secret: str
    admin_password_hash: str

    # Outer gate for real money. See module docstring.
    live_trading_enabled: bool = False

    #: The third, independent gate. ``LIVE_TRADING_ENABLED`` says the
    #: *deployment* may reach a live venue at all; this says a given process is
    #: authorised to place the order. They are separate variables on purpose:
    #: ``_alpaca_from_env`` used to derive ``allow_live`` from
    #: ``live_trading_enabled``, which collapsed the documented three
    #: independent conditions into two and made a stray LIVE_TRADING_ENABLED=true
    #: sufficient on its own — the exact scenario
    #: ``test_alpaca_broker.py`` claims to protect against.
    alpaca_allow_live: bool = False

    # Where the browser app is served from, for CORS.
    cors_origins: list[str] = field(default_factory=list)

    #: ``SameSite`` on the session cookie.
    #:
    #: ``lax`` is right when the browser app and the API are the same *site* —
    #: which includes different ports, so it covers local development
    #: (``localhost:3000`` calling ``localhost:8000``) and a shared parent
    #: domain such as ``app.example.com`` calling ``api.example.com``.
    #:
    #: It is wrong for the deployment this project actually targets. The
    #: frontend goes to Vercel and the API to a separate host, so the request
    #: is cross-*site*, and a browser will not attach a ``Lax`` cookie to a
    #: cross-site fetch. The failure is quiet and misleading: ``/auth/login``
    #: returns 200 and sets the cookie, and every authenticated call after it
    #: gets 401, which reads as "the password did not work" when in fact it
    #: did. ``none`` is the setting that permits it, and browsers reject
    #: ``SameSite=None`` unless ``Secure`` is also set — so ``none`` implies
    #: ``secure`` below rather than trusting an operator to set both.
    session_cookie_samesite: str = "lax"

    session_ttl_seconds: int = 60 * 60 * 12
    worker_poll_seconds: int = 2
    worker_id: str = "worker-1"

    alpaca_key_id: str = ""
    alpaca_secret_key: str = ""
    alpaca_paper: bool = True

    @property
    def has_broker_credentials(self) -> bool:
        return bool(self.alpaca_key_id and self.alpaca_secret_key)


@functools.lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Load and validate settings once per process."""
    database_url = os.environ.get("DATABASE_URL", "").strip()
    if not database_url:
        raise ConfigError(
            "DATABASE_URL is required. Example: "
            "postgresql://user:pass@localhost:5432/trader"
        )

    session_secret = os.environ.get("SESSION_SECRET", "").strip()
    if not session_secret:
        raise ConfigError(
            "SESSION_SECRET is required and has no default. Generate one with: "
            "python -c 'import secrets; print(secrets.token_urlsafe(48))'"
        )
    if len(session_secret) < 32:
        raise ConfigError("SESSION_SECRET must be at least 32 characters")

    admin_password_hash = os.environ.get("ADMIN_PASSWORD_HASH", "").strip()
    if not admin_password_hash:
        raise ConfigError(
            "ADMIN_PASSWORD_HASH is required. Generate one with: python -c "
            "\"import bcrypt;print(bcrypt.hashpw(b'yourpassword', "
            'bcrypt.gensalt()).decode())"'
        )

    origins_raw = os.environ.get("CORS_ORIGINS", "").strip()
    cors_origins = [o.strip() for o in origins_raw.split(",") if o.strip()]

    samesite = os.environ.get("SESSION_COOKIE_SAMESITE", "lax").strip().lower()
    if samesite not in {"lax", "strict", "none"}:
        # Rejected rather than defaulted. A typo silently falling back to `lax`
        # would produce exactly the cross-site 401 this setting exists to fix,
        # with the configuration appearing to say otherwise.
        raise ConfigError(
            f"SESSION_COOKIE_SAMESITE must be one of lax, strict, none "
            f"(got {samesite!r})"
        )

    live = _bool_env("LIVE_TRADING_ENABLED", False)
    allow_live = _bool_env("ALPACA_ALLOW_LIVE", False)
    if live:
        logger.warning(
            "LIVE_TRADING_ENABLED is set. Real orders become possible once the "
            "database kill switch also permits trading."
        )
    if live and allow_live:
        logger.warning(
            "LIVE_TRADING_ENABLED *and* ALPACA_ALLOW_LIVE are both set. A "
            "deployment in live mode will place REAL orders."
        )
    if allow_live and not live:
        # Harmless on its own, and worth saying so: an operator who set only
        # this one may believe live trading is armed when it is not.
        logger.info(
            "ALPACA_ALLOW_LIVE is set but LIVE_TRADING_ENABLED is not; live "
            "trading remains disabled."
        )

    return Settings(
        database_url=database_url,
        session_secret=session_secret,
        admin_password_hash=admin_password_hash,
        live_trading_enabled=live,
        cors_origins=cors_origins,
        session_cookie_samesite=samesite,
        session_ttl_seconds=_int_env("SESSION_TTL_SECONDS", 60 * 60 * 12),
        worker_poll_seconds=_int_env("WORKER_POLL_SECONDS", 2),
        worker_id=os.environ.get("WORKER_ID", "worker-1"),
        alpaca_key_id=os.environ.get("ALPACA_KEY_ID", ""),
        alpaca_secret_key=os.environ.get("ALPACA_SECRET_KEY", ""),
        alpaca_paper=_bool_env("ALPACA_PAPER", True),
        alpaca_allow_live=allow_live,
    )
