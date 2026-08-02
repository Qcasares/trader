"""
test_secret_requirements.py
---------------------------
Which process needs which secret, and that moving the check did not soften it.

``SESSION_SECRET`` and ``ADMIN_PASSWORD_HASH`` were validated inside
``get_settings``, which every process calls. The worker therefore refused to
boot without an operator password it has no use for — it serves no HTTP and
verifies no session — which pushed a credential onto a process that never needs
it and failed deployments on a value that could not have affected them.

The validation moved to ``require_api_secrets``, called by ``create_app``, and
then out of ``create_app`` altogether — because raising there took ``/health``,
``/ready`` and ``/`` down with it, and a deployment missing one variable became
indistinguishable from one that failed to build.

Both moves are relocations, not relaxations, and this file is what makes the
difference checkable. The property that must survive is the one in config.py's
own docstring: *a signing key with a fallback value is a signing key an
attacker already knows*. An **empty** secret would be worse than a missing one
— HMAC over ``b""`` verifies perfectly well, so anyone could mint a session.

The property is now stated more precisely, and enforced somewhere better.
"Refuses to start" was only ever a proxy for what actually matters — **nobody
can obtain or present a valid session** — and it was a proxy that constrained
exactly one call site. That guarantee now lives in ``issue_session`` and
``verify_session`` themselves, which raise rather than touch an unusable key,
so it holds against a caller that never validated anything.
"""

from __future__ import annotations

import os

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from src.api.security import (  # noqa: E402
    AuthError,
    InsecureSecretError,
    hash_password,
    issue_session,
    verify_session,
)
from src.config import (  # noqa: E402
    MIN_SESSION_SECRET_LENGTH,
    ConfigError,
    get_settings,
    require_api_secrets,
)

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


class TestTheSigningPrimitivesRefuseAnUnusableKey:
    """
    Where the guarantee actually lives.

    Every test here would pass just as well if ``create_app`` had never checked
    anything, which is the point: these constrain the *operation*, so no
    arrangement of callers — present, future, or in a test — can produce a
    session under a key that fails the policy.

    ``issue_session`` is the mint and ``verify_session`` is the gate. Closing
    only one is not enough. Leaving the mint open lets this deployment hand out
    tokens under a guessable key; leaving the gate open lets it *accept* them,
    which is worse, because the attacker mints those.
    """

    @pytest.mark.parametrize("secret", ["", "   ", "tooshort", "x" * 31])
    def test_an_unusable_key_cannot_mint(self, secret) -> None:
        with pytest.raises(InsecureSecretError):
            issue_session(secret)

    @pytest.mark.parametrize("secret", ["", "   ", "tooshort", "x" * 31])
    def test_an_unusable_key_cannot_verify(self, secret) -> None:
        # The token argument is deliberately a *valid-looking* one. The check
        # must happen before the token is examined at all, or a caller could
        # conclude from a rejection that the signature was wrong.
        with pytest.raises(InsecureSecretError):
            verify_session(secret, "abc.def")

    def test_the_boundary_is_exactly_32(self) -> None:
        # Pinned so a later "tidy up" cannot lower it silently.
        assert MIN_SESSION_SECRET_LENGTH == 32
        with pytest.raises(InsecureSecretError):
            issue_session("x" * 31)
        assert issue_session("x" * 32)

    def test_an_empty_key_cannot_verify_a_token_it_just_signed(self) -> None:
        """
        The exact attack an empty key permits, stated as a test.

        With the guard removed, ``issue_session("")`` returns a token and
        ``verify_session("", token)`` accepts it — so anyone who knows the key
        is the empty string, which is everyone, is the operator. Both halves
        must refuse; neither is allowed to be the only one that does.
        """
        with pytest.raises(InsecureSecretError):
            token = issue_session("")
            verify_session("", token)

    def test_a_usable_key_still_round_trips(self) -> None:
        # The negative tests above are worthless if the positive path broke.
        token = issue_session("k" * 48, subject="operator")
        assert verify_session("k" * 48, token).subject == "operator"

    def test_insecure_is_not_an_auth_error(self) -> None:
        # Load-bearing for the 503-not-401 split: `current_session` catches
        # AuthError and answers 401. If InsecureSecretError were a subclass,
        # a server with no key would tell the operator their *password* was
        # the problem, and send them to a login that also cannot work.
        assert not issubclass(InsecureSecretError, AuthError)


class TestTheApiStillFailsClosed:
    """
    The app now builds without secrets — so this is where the replacement
    guarantee is checked at the HTTP boundary. Building is not serving.
    """

    def _client(self, monkeypatch, **overrides):
        _env(monkeypatch, **overrides)
        return TestClient(create_app(), raise_server_exceptions=False)

    @pytest.mark.parametrize(
        "overrides",
        [
            {"SESSION_SECRET": None},
            {"SESSION_SECRET": "   "},
            {"SESSION_SECRET": "tooshort"},
            {"ADMIN_PASSWORD_HASH": None},
        ],
    )
    def test_login_is_refused_without_complete_config(
        self, monkeypatch, overrides
    ) -> None:
        client = self._client(monkeypatch, **overrides)
        response = client.post("/api/v1/auth/login", json={"password": "unused"})
        assert response.status_code == 503, (
            "an unconfigured deployment must refuse to mint a session, and "
            "must not answer 401 — the password was never the problem"
        )

    def test_login_is_refused_before_the_password_is_checked(
        self, monkeypatch
    ) -> None:
        # Even the *correct* password gets 503. If this ever returned 200 the
        # deployment would be minting sessions under a key it does not have.
        _env(monkeypatch, SESSION_SECRET=None)
        monkeypatch.setenv("ADMIN_PASSWORD_HASH", hash_password("correct-horse"))
        get_settings.cache_clear()
        client = TestClient(create_app(), raise_server_exceptions=False)
        response = client.post(
            "/api/v1/auth/login", json={"password": "correct-horse"}
        )
        assert response.status_code == 503
        assert "trader_session" not in response.cookies

    def test_an_authenticated_route_answers_503_not_401(self, monkeypatch) -> None:
        client = self._client(monkeypatch, SESSION_SECRET=None)
        response = client.get(
            "/api/v1/auth/me", headers={"Authorization": "Bearer anything"}
        )
        assert response.status_code == 503

    def test_a_forged_session_is_still_refused(self, monkeypatch) -> None:
        # The one that would matter if the guard were wrong. A token signed
        # with the empty key must not be accepted by a server whose key is
        # empty — that is the whole attack.
        client = self._client(monkeypatch, SESSION_SECRET=None)
        import base64
        import hashlib
        import hmac
        import json
        import time

        payload = json.dumps(
            {"sub": "operator", "iat": int(time.time()), "exp": 2**31}
        ).encode()
        body = base64.urlsafe_b64encode(payload).decode().rstrip("=")
        sig = hmac.new(b"", body.encode(), hashlib.sha256).digest()
        forged = f"{body}.{base64.urlsafe_b64encode(sig).decode().rstrip('=')}"

        response = client.get(
            "/api/v1/auth/me", headers={"Authorization": f"Bearer {forged}"}
        )
        assert response.status_code == 503, (
            "a token forged under the empty key must never authenticate"
        )
        assert response.status_code != 200

    def test_ready_names_what_is_missing(self, monkeypatch) -> None:
        client = self._client(monkeypatch, SESSION_SECRET=None)
        response = client.get("/api/v1/ready")
        assert response.status_code == 503
        assert any("SESSION_SECRET" in gap for gap in response.json()["config"])

    def test_ready_names_every_gap_at_once(self, monkeypatch) -> None:
        # Three redeploys to discover three missing variables is the failure
        # this replaces.
        client = self._client(
            monkeypatch, SESSION_SECRET=None, ADMIN_PASSWORD_HASH=None
        )
        gaps = " ".join(client.get("/api/v1/ready").json()["config"])
        assert "SESSION_SECRET" in gaps
        assert "ADMIN_PASSWORD_HASH" in gaps

    def test_health_survives_missing_secrets(self, monkeypatch) -> None:
        # The entire reason for the change: the endpoint that reports trouble
        # must not be taken down by the trouble.
        client = self._client(monkeypatch, SESSION_SECRET=None)
        assert client.get("/api/v1/health").status_code == 200
        assert client.get("/").status_code == 200

    def test_a_complete_environment_builds_an_app(self, monkeypatch) -> None:
        _env(monkeypatch)
        assert create_app() is not None

    def test_a_complete_environment_can_log_in(self, monkeypatch) -> None:
        _env(monkeypatch, ADMIN_PASSWORD_HASH=hash_password("s3kret"))
        client = TestClient(create_app(), raise_server_exceptions=False)
        assert (
            client.post(
                "/api/v1/auth/login", json={"password": "s3kret"}
            ).status_code
            == 200
        )


class TestRequireApiSecretsStillRaises:
    """
    Kept for any process that does want to fail closed at boot, and because a
    policy stated in one raising form keeps ConfigError meaningful.
    """

    def test_no_session_secret_raises(self, monkeypatch) -> None:
        _env(monkeypatch, SESSION_SECRET=None)
        with pytest.raises(ConfigError, match="SESSION_SECRET"):
            require_api_secrets(get_settings())

    def test_a_short_session_secret_raises(self, monkeypatch) -> None:
        _env(monkeypatch, SESSION_SECRET="tooshort")
        with pytest.raises(ConfigError, match="at least 32"):
            require_api_secrets(get_settings())

    def test_no_admin_password_raises(self, monkeypatch) -> None:
        _env(monkeypatch, ADMIN_PASSWORD_HASH=None)
        with pytest.raises(ConfigError, match="ADMIN_PASSWORD_HASH"):
            require_api_secrets(get_settings())

    def test_a_complete_environment_does_not_raise(self, monkeypatch) -> None:
        _env(monkeypatch)
        require_api_secrets(get_settings())

    def test_create_app_no_longer_calls_it(self) -> None:
        # Deliberate asymmetry, pinned for the same reason as the
        # DATABASE_URL one below: restoring the call would restore the
        # crash-at-import and take /health down with it.
        import inspect

        from src.api import main as api_main

        assert "require_api_secrets" not in inspect.getsource(api_main.create_app)


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

    def test_settings_load_without_a_database_url_too(self, monkeypatch) -> None:
        """
        DATABASE_URL used to be required inside get_settings, which runs at
        import. On a serverless host that is the wrong trade: environment
        variables are configured *after* the first deploy, so the first deploy
        of a correctly-built application crashed at import and every route —
        `/health` included — returned an opaque FUNCTION_INVOCATION_FAILED,
        with the real reason visible only in a runtime log.

        It is now enforced where it matters instead. See the class below.
        """
        _env(monkeypatch, DATABASE_URL=None)
        assert get_settings().database_url == ""


class TestTheDatabaseIsRequiredWhereItMatters:
    """
    Relocated, not relaxed — the same argument as the API secrets above.

    A missing DATABASE_URL cannot make anything *insecure*; it can only make it
    useless. So the API degrades legibly (200 on /health, 503 on /ready) while
    the worker, which exists solely to claim jobs and write results, refuses to
    start at all: a loop that can never do anything, running quietly forever,
    is the failure mode this codebase treats as worse than crashing.
    """

    def test_require_database_url_rejects_an_empty_one(self, monkeypatch) -> None:
        from src.config import require_database_url

        _env(monkeypatch, DATABASE_URL=None)
        with pytest.raises(ConfigError, match="DATABASE_URL"):
            require_database_url(get_settings())

    def test_require_database_url_accepts_a_real_one(self, monkeypatch) -> None:
        from src.config import require_database_url

        _env(monkeypatch)
        require_database_url(get_settings())  # must not raise

    def test_the_worker_calls_it(self) -> None:
        # The function existing is not the guarantee; the worker calling it is.
        import inspect

        from src.worker import main

        assert "require_database_url" in inspect.getsource(main.async_main), (
            "the worker must refuse to start without a database, or it runs a "
            "loop that can never claim a job and says nothing about it"
        )

    def test_the_api_does_not_call_it(self) -> None:
        # Deliberate asymmetry, and worth pinning: adding it to create_app
        # would restore the crash-at-import behaviour and take /health down
        # with it on any half-configured deployment.
        import inspect

        from src.api import main as api_main

        assert "require_database_url" not in inspect.getsource(api_main.create_app)

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
