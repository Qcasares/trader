"""
test_health_probes.py
---------------------
What the liveness and readiness endpoints tell an orchestrator.

A unit test, deliberately. The interesting case is "the database is not
reachable", and the cheapest honest way to produce that is to build the app
without running its lifespan, so no pool is ever created. That needs no
Postgres, which means this runs in the ordinary unit suite rather than only
when someone remembers to start one — appropriate for a check about what
happens when infrastructure is missing.

The bug: ``/ready`` returned **200** with ``{"ready": false}``. Every
orchestrator routes on the status code and ignores the body, so an instance
with a dead database stayed in the load balancer serving 500s while its
readiness probe reported success. The body was honest and the response was not,
and only the response is read.
"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from src.api.security import hash_password  # noqa: E402


@pytest.fixture
def app_without_lifespan(monkeypatch):
    """
    The application, never started.

    ``TestClient`` only runs lifespan handlers when used as a context manager.
    Constructing it directly therefore gives an app whose ``state.pool`` was
    never set — exactly the shape of a process that came up before its database
    did, which is the common case on a cold deploy.
    """
    from src.config import get_settings

    monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/unused")
    monkeypatch.setenv("SESSION_SECRET", "p" * 48)
    monkeypatch.setenv("ADMIN_PASSWORD_HASH", hash_password("unused"))
    get_settings.cache_clear()

    from src.api.main import create_app

    try:
        yield TestClient(create_app())
    finally:
        get_settings.cache_clear()


class TestReadiness:
    def test_unready_answers_503_not_200(self, app_without_lifespan) -> None:
        response = app_without_lifespan.get("/api/v1/ready")
        assert response.status_code == 503, (
            "a readiness probe that answers 200 while unready keeps a broken "
            "instance in the load balancer; orchestrators read the status "
            "code, never the body"
        )

    def test_the_body_still_explains_why(self, app_without_lifespan) -> None:
        body = app_without_lifespan.get("/api/v1/ready").json()
        assert body["ready"] is False
        assert body["database"] is False


class TestLiveness:
    """
    Liveness answers "is this process running", not "is it useful". It must
    stay 200 without a database: a restart loop triggered by an outage in a
    *dependency* turns a recoverable incident into an unrecoverable one,
    because the instance never stays up long enough for the dependency's
    recovery to be noticed.
    """

    def test_health_is_200_even_with_no_database(self, app_without_lifespan) -> None:
        response = app_without_lifespan.get("/api/v1/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    def test_health_needs_no_authentication(self, app_without_lifespan) -> None:
        # A probe that requires a session cannot be used by the thing that
        # decides whether to keep the process alive.
        assert app_without_lifespan.get("/api/v1/health").status_code == 200

    def test_health_reveals_nothing_about_state(self, app_without_lifespan) -> None:
        body = app_without_lifespan.get("/api/v1/health").json()
        # Unauthenticated, so it must not leak whether trading is enabled,
        # whether a broker is configured, or anything else an attacker could
        # use to decide this endpoint is worth more attention.
        assert set(body) == {"status", "version"}
