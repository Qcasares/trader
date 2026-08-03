"""
test_migrate_endpoint.py
------------------------
The API can apply its own migrations, because a serverless host has no shell.

`python -m src.db.migrate_cli` assumes somewhere to run it. On the hosts this
project actually deploys to, there is nowhere — and the alternative people
reach for, pasting DDL into the database console, is how deployed schemas
drift from the repository. The endpoint runs the same runner as the CLI, so
"the deployed schema" keeps exactly one definition.

Unit tests: the migration *runner* is exercised against a real database by
every integration test's schema setup, so what needs proving here is the
endpoint's contract — who may call it, and what it does with the runner's
answers. The runner is faked per test; the auth path is the real one.
"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from src.api.security import hash_password  # noqa: E402
from src.config import get_settings  # noqa: E402
from src.db.migrate import MigrationError  # noqa: E402

PASSWORD = "migrate-endpoint-pw"
CRON = "cron-secret-for-tests"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/unused")
    monkeypatch.setenv("SESSION_SECRET", "m" * 48)
    monkeypatch.setenv("ADMIN_PASSWORD_HASH", hash_password(PASSWORD))
    monkeypatch.setenv("CRON_SECRET", CRON)
    get_settings.cache_clear()

    from src.api.main import create_app

    app = create_app()

    # The endpoint acquires a connection from the pool before auth is even
    # considered (DbConn is a dependency), so the unstarted app's missing pool
    # would 503 first. A stub pool keeps the focus on the endpoint's contract.
    class _Conn:
        pass

    class _Acquire:
        async def __aenter__(self):
            return _Conn()

        async def __aexit__(self, *exc):
            return False

    class _Pool:
        def acquire(self):
            return _Acquire()

    app.state.pool = _Pool()
    try:
        yield TestClient(app, raise_server_exceptions=False)
    finally:
        get_settings.cache_clear()


def _fake_runner(monkeypatch, applied=(), version=6, error=None):
    from src.api.routers import system

    async def fake_migrate(conn):
        if error is not None:
            raise error
        return list(applied)

    async def fake_version(conn):
        return version

    monkeypatch.setattr(system, "migrate", fake_migrate)
    monkeypatch.setattr(system, "current_version", fake_version)


class TestWhoMayCall:
    def test_anonymous_is_refused(self, client, monkeypatch) -> None:
        _fake_runner(monkeypatch)
        assert client.post("/api/v1/system/migrate").status_code == 401

    def test_a_wrong_bearer_is_refused(self, client, monkeypatch) -> None:
        _fake_runner(monkeypatch)
        response = client.post(
            "/api/v1/system/migrate",
            headers={"Authorization": "Bearer not-the-secret"},
        )
        assert response.status_code == 401

    def test_the_cron_secret_is_accepted(self, client, monkeypatch) -> None:
        _fake_runner(monkeypatch)
        response = client.post(
            "/api/v1/system/migrate",
            headers={"Authorization": f"Bearer {CRON}"},
        )
        assert response.status_code == 200

    def test_an_operator_session_is_accepted(self, client, monkeypatch) -> None:
        # Login works without a database — deliberately, and this endpoint is
        # why that ordering matters: the session that authorises the first
        # migration must be mintable before the schema exists.
        _fake_runner(monkeypatch)
        login = client.post("/api/v1/auth/login", json={"password": PASSWORD})
        assert login.status_code == 200
        assert client.post("/api/v1/system/migrate").status_code == 200

    def test_get_is_not_a_route(self, client, monkeypatch) -> None:
        # POST only. Unlike the drain, no platform scheduler needs this, so
        # there is no reason to accept the mutating-GET compromise here.
        _fake_runner(monkeypatch)
        response = client.get(
            "/api/v1/system/migrate",
            headers={"Authorization": f"Bearer {CRON}"},
        )
        assert response.status_code == 405


class TestWhatItReports:
    def test_applied_migrations_are_named(self, client, monkeypatch) -> None:
        _fake_runner(monkeypatch, applied=["0001_baseline", "0002_systematic"])
        body = client.post(
            "/api/v1/system/migrate",
            headers={"Authorization": f"Bearer {CRON}"},
        ).json()
        assert body["applied"] == ["0001_baseline", "0002_systematic"]
        assert body["current_version"] == 6

    def test_idempotent_second_call_reports_empty(self, client, monkeypatch) -> None:
        _fake_runner(monkeypatch, applied=[])
        body = client.post(
            "/api/v1/system/migrate",
            headers={"Authorization": f"Bearer {CRON}"},
        ).json()
        assert body["applied"] == []

    def test_a_migration_error_is_409_with_the_reason(
        self, client, monkeypatch
    ) -> None:
        # 409, not 500: retrying without changing the repository will refuse
        # identically, and the operator needs the runner's own words — an
        # edited applied migration names itself in them.
        _fake_runner(
            monkeypatch,
            error=MigrationError("0003_x has been modified since it was applied"),
        )
        response = client.post(
            "/api/v1/system/migrate",
            headers={"Authorization": f"Bearer {CRON}"},
        )
        assert response.status_code == 409
        assert "modified since it was applied" in response.json()["detail"]
