"""
config.py
---------
Typed settings from the environment.

Two safety properties are enforced here rather than left to discipline:

- ``live_trading_enabled`` defaults to ``False`` and is the *outer* of two
  gates. The inner gate is the database kill switch. Flipping the DB flag needs
  only API access; flipping this one needs a redeploy. Both must permit trading
  before a live order can leave the building.
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

    # Where the browser app is served from, for CORS.
    cors_origins: list[str] = field(default_factory=list)

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

    live = _bool_env("LIVE_TRADING_ENABLED", False)
    if live:
        logger.warning(
            "LIVE_TRADING_ENABLED is set. Real orders become possible once the "
            "database kill switch also permits trading."
        )

    return Settings(
        database_url=database_url,
        session_secret=session_secret,
        admin_password_hash=admin_password_hash,
        live_trading_enabled=live,
        cors_origins=cors_origins,
        session_ttl_seconds=_int_env("SESSION_TTL_SECONDS", 60 * 60 * 12),
        worker_poll_seconds=_int_env("WORKER_POLL_SECONDS", 2),
        worker_id=os.environ.get("WORKER_ID", "worker-1"),
        alpaca_key_id=os.environ.get("ALPACA_KEY_ID", ""),
        alpaca_secret_key=os.environ.get("ALPACA_SECRET_KEY", ""),
        alpaca_paper=_bool_env("ALPACA_PAPER", True),
    )
