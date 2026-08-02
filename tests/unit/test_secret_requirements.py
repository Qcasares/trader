"""
test_secret_requirements.py
---------------------------
Which process needs which secret, and that moving the check did not soften it.

``SESSION_SECRET`` and ``ADMIN_PASSWORD_HASH`` were validated inside
``get_settings``, which every process calls. The worker therefore refused to
boot without an operator password it has no use for — it serves no HTTP and
verifies no session — which pushed a credential onto a process that never needs
it and failed deployments on a value that could not have affected them.

The validation moved to ``require_api_secrets``, called by ``create_app``. That
is a relocation, not a relaxation, and this file is what makes the difference
checkable. The property that must survive is the one in config.py's own
docstring: *a signing key with a fallback value is a signing key an attacker
already knows*. An **empty** secret would be worse than a missing one — HMAC
over ``b""`` verifies perfectly well, so anyone could mint a session.
"""

from __future__ import annotations

import os

import pytest

pytest.importorskip("fastapi")

from src.api.security import hash_password  # noqa: E402
from src.config import ConfigError, get_settings  # noqa: E402

# `src/api/main.py` ends with `app = create_app()`, because that is what
# `uvicorn src.api.main:app` needs. So *importing* the module builds an
# application, and the import fails outright under a stripped environment —
# before any `pytest.raises` in a test body can catch it. Import it once here
# under a valid environment; every later import is served from sys.modules, and
# the tests below call `create_app()` explicitly instead.
os.environ.setdefault("DATABASE_URL", "postgresql://localhost/unused")
os.environ.setdefault("SESSION_SECRET", "s" * 48)
os.environ.setdefault("ADMIN_PASSWORD_HASH", hash_password("bootstrap"))
get_settings.cache_clear()

from src.api.main import create_app  # noqa: E402


def _env(monkeypatch, **overrides: str | None) -> None:
    """Set a complete environment, then apply removals/overrides."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/unused")
    monkeypatch.setenv("SESSION_SECRET", "s" * 48)
    monkeypatch.setenv("ADMIN_PASSWORD_HASH", hash_password("unused"))
    for key, value in overrides.items():
        if value is None:
            monkeypatch.delenv(key, raising=False)
        else:
            monkeypatch.setenv(key, value)
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _clear_cache():
    yield
    get_settings.cache_clear()


class TestTheApiStillFailsClosed:
    """
    The whole point of the relocation being safe. `create_app` is the only way
    to obtain an application object, so every path that can serve a request
    passes through the check.
    """

    def test_no_session_secret_means_no_app(self, monkeypatch) -> None:
        _env(monkeypatch, SESSION_SECRET=None)
        with pytest.raises(ConfigError, match="SESSION_SECRET"):
            create_app()

    def test_an_empty_session_secret_means_no_app(self, monkeypatch) -> None:
        # Distinct from missing, and more dangerous: HMAC over b"" verifies,
        # so an empty key is a working key that everyone knows.
        _env(monkeypatch, SESSION_SECRET="   ")
        with pytest.raises(ConfigError, match="SESSION_SECRET"):
            create_app()

    def test_a_short_session_secret_means_no_app(self, monkeypatch) -> None:
        _env(monkeypatch, SESSION_SECRET="tooshort")
        with pytest.raises(ConfigError, match="at least 32"):
            create_app()

    def test_no_admin_password_means_no_app(self, monkeypatch) -> None:
        _env(monkeypatch, ADMIN_PASSWORD_HASH=None)
        with pytest.raises(ConfigError, match="ADMIN_PASSWORD_HASH"):
            create_app()

    def test_a_complete_environment_builds_an_app(self, monkeypatch) -> None:
        _env(monkeypatch)
        assert create_app() is not None


class TestTheWorkerNeedsNeither:
    """
    The reason for the change. A worker deployment should not carry the
    operator's password, and should not fail on its absence.
    """

    def test_settings_load_without_api_secrets(self, monkeypatch) -> None:
        _env(monkeypatch, SESSION_SECRET=None, ADMIN_PASSWORD_HASH=None)
        settings = get_settings()
        assert settings.database_url
        assert settings.session_secret == ""
        assert settings.admin_password_hash == ""

    def test_database_url_is_still_required_of_everyone(self, monkeypatch) -> None:
        # The relocation applies only to the two API secrets. Every process
        # talks to Postgres, so that one stays a hard requirement everywhere.
        _env(monkeypatch, DATABASE_URL=None)
        with pytest.raises(ConfigError, match="DATABASE_URL"):
            get_settings()

    def test_the_live_gates_still_default_closed(self, monkeypatch) -> None:
        # Adjacent, and worth asserting in the same breath: nothing about
        # relaxing the secret checks may relax these.
        _env(
            monkeypatch,
            SESSION_SECRET=None,
            ADMIN_PASSWORD_HASH=None,
            LIVE_TRADING_ENABLED=None,
            ALPACA_ALLOW_LIVE=None,
        )
        settings = get_settings()
        assert settings.live_trading_enabled is False
        assert settings.alpaca_allow_live is False
