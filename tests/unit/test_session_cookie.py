"""
test_session_cookie.py
----------------------
``SameSite`` on the session cookie, which decides whether the deployed
frontend can authenticate at all.

This is a unit test rather than an API integration test on purpose: nothing
here touches a database, and putting it behind ``TEST_DATABASE_URL`` would mean
the check that protects the deployment only runs when someone remembers to
stand up Postgres. It runs in ``pytest tests/unit`` and therefore in CI.

The bug it exists to prevent is quiet. The locked topology puts the frontend on
Vercel and the API on a separate host, which makes every API call cross-*site*;
a browser will not attach a ``SameSite=Lax`` cookie to a cross-site fetch.
``POST /auth/login`` then returns 200 and sets a cookie that is never sent
again, so the login screen appears to reject a correct password. Nothing in the
server logs looks wrong, because from the server's point of view the login
succeeded and the next request was simply anonymous.
"""

from __future__ import annotations

import pytest
from starlette.requests import Request
from starlette.responses import Response

from src.api.routers.auth import _cookie_attrs, login, logout
from src.api.schemas import LoginRequest
from src.api.security import SESSION_COOKIE, hash_password
from src.config import ConfigError, get_settings

PASSWORD = "cookie-test-password"


def _settings(monkeypatch, **env: str):
    """Real settings from real environment parsing, not a hand-built object."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/unused")
    monkeypatch.setenv("SESSION_SECRET", "s" * 48)
    monkeypatch.setenv("ADMIN_PASSWORD_HASH", hash_password(PASSWORD))
    monkeypatch.delenv("CORS_ORIGINS", raising=False)
    monkeypatch.delenv("SESSION_COOKIE_SAMESITE", raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    try:
        return get_settings()
    finally:
        get_settings.cache_clear()


def _parse(header: str) -> dict[str, str]:
    """A Set-Cookie header as a lowercased attribute map."""
    attrs: dict[str, str] = {}
    for part in header.split(";"):
        part = part.strip()
        if not part:
            continue
        key, _, value = part.partition("=")
        attrs[key.strip().lower()] = value.strip()
    return attrs


def _request() -> Request:
    return Request(
        {"type": "http", "headers": [], "client": ("198.51.100.7", 51234)}
    )


class TestConfiguration:
    def test_default_is_lax(self, monkeypatch) -> None:
        assert _settings(monkeypatch).session_cookie_samesite == "lax"

    def test_none_is_accepted(self, monkeypatch) -> None:
        settings = _settings(monkeypatch, SESSION_COOKIE_SAMESITE="none")
        assert settings.session_cookie_samesite == "none"

    def test_case_and_whitespace_are_tolerated(self, monkeypatch) -> None:
        settings = _settings(monkeypatch, SESSION_COOKIE_SAMESITE="  None  ")
        assert settings.session_cookie_samesite == "none"

    def test_a_typo_is_rejected_rather_than_defaulted(self, monkeypatch) -> None:
        # Falling back to `lax` here would reproduce the exact cross-site
        # failure the setting exists to fix, while the configuration claims
        # otherwise. Loud beats quiet.
        with pytest.raises(ConfigError, match="SESSION_COOKIE_SAMESITE"):
            _settings(monkeypatch, SESSION_COOKIE_SAMESITE="cross-site")


class TestCorsOriginNormalisation:
    """
    A bare hostname in CORS_ORIGINS is completed to an https origin.

    Render's Blueprint wires one service's hostname into another's environment
    (``fromService``, property ``host``) — a hostname, no scheme. A browser's
    ``Origin`` header always carries a scheme, and the CORS match is exact, so
    an unnormalised bare host fails precisely like an unset value: login 200,
    every call after it 401, nothing in the server logs.
    """

    def test_a_bare_host_becomes_an_https_origin(self, monkeypatch) -> None:
        settings = _settings(monkeypatch, CORS_ORIGINS="trader-ui.onrender.com")
        assert settings.cors_origins == ["https://trader-ui.onrender.com"]

    def test_an_explicit_scheme_is_left_alone(self, monkeypatch) -> None:
        # http specifically: local development is the one place it is right,
        # and "normalising" it to https would break a working setup.
        settings = _settings(monkeypatch, CORS_ORIGINS="http://localhost:3000")
        assert settings.cors_origins == ["http://localhost:3000"]

    def test_mixed_lists_normalise_per_entry(self, monkeypatch) -> None:
        settings = _settings(
            monkeypatch,
            CORS_ORIGINS="ui.onrender.com, https://app.vercel.app ,http://localhost:3000",
        )
        assert settings.cors_origins == [
            "https://ui.onrender.com",
            "https://app.vercel.app",
            "http://localhost:3000",
        ]

    def test_empty_pieces_are_dropped_not_normalised(self, monkeypatch) -> None:
        settings = _settings(monkeypatch, CORS_ORIGINS=" , ,")
        assert settings.cors_origins == []


class TestSecureIsImpliedByNone:
    """
    Browsers reject ``SameSite=None`` without ``Secure`` outright. Requiring an
    operator to set both means one of them is eventually forgotten, and the
    result is not a cookie with weaker protection — it is no cookie at all.
    """

    def test_none_forces_secure_even_with_no_origins(self, monkeypatch) -> None:
        settings = _settings(monkeypatch, SESSION_COOKIE_SAMESITE="none")
        assert settings.cors_origins == []
        assert _cookie_attrs(settings)["secure"] is True

    def test_lax_stays_insecure_for_local_development(self, monkeypatch) -> None:
        # Plain HTTP on localhost is the one case where Secure would break a
        # working setup rather than protect it.
        attrs = _cookie_attrs(_settings(monkeypatch))
        assert attrs["samesite"] == "lax"
        assert attrs["secure"] is False

    def test_lax_becomes_secure_once_an_origin_is_configured(
        self, monkeypatch
    ) -> None:
        settings = _settings(
            monkeypatch, CORS_ORIGINS="https://app.example.com"
        )
        assert _cookie_attrs(settings)["secure"] is True


class TestTheShippedEndpoints:
    """
    Drives ``login`` and ``logout`` themselves rather than ``_cookie_attrs``.
    A helper that returns the right dictionary proves nothing if the endpoint
    does not use it.
    """

    async def test_login_emits_what_the_settings_ask_for(
        self, monkeypatch
    ) -> None:
        settings = _settings(monkeypatch, SESSION_COOKIE_SAMESITE="none")
        response = Response()

        await login(
            LoginRequest(password=PASSWORD), _request(), response, settings
        )

        header = response.headers["set-cookie"]
        assert header.startswith(f"{SESSION_COOKIE}=")
        attrs = _parse(header)
        assert attrs["samesite"] == "none"
        assert "secure" in attrs
        assert "httponly" in attrs

    async def test_logout_clears_with_matching_attributes(
        self, monkeypatch
    ) -> None:
        """
        A browser matches a deletion against name, path, domain, Secure and
        SameSite. A bare ``delete_cookie()`` against a ``SameSite=None; Secure``
        cookie leaves the original in place: logout returns 200, the UI drops
        its state, and the session is still valid on the next request.
        """
        settings = _settings(monkeypatch, SESSION_COOKIE_SAMESITE="none")

        set_response = Response()
        await login(
            LoginRequest(password=PASSWORD), _request(), set_response, settings
        )
        del_response = Response()
        await logout(del_response, settings)

        was_set = _parse(set_response.headers["set-cookie"])
        cleared = _parse(del_response.headers["set-cookie"])

        assert cleared[SESSION_COOKIE] == '""'
        for attribute in ("samesite", "path"):
            assert cleared[attribute] == was_set[attribute], attribute
        assert ("secure" in cleared) == ("secure" in was_set)

    async def test_lax_is_still_what_local_development_gets(
        self, monkeypatch
    ) -> None:
        settings = _settings(monkeypatch)
        response = Response()

        await login(
            LoginRequest(password=PASSWORD), _request(), response, settings
        )

        assert _parse(response.headers["set-cookie"])["samesite"] == "lax"
