"""
test_api.py
-----------
API tests against a real PostgreSQL database.

Skipped unless ``TEST_DATABASE_URL`` is set, because these are integration
tests and mocking asyncpg would only prove the mock matches the expectation.
To run them:

    createdb trader_test
    TEST_DATABASE_URL=postgresql://localhost/trader_test \
        pytest tests/integration/test_api.py

The suite applies migrations to whatever database it is pointed at, so the
target must be disposable.
"""

from __future__ import annotations

import asyncio
import os

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("asyncpg")

import asyncpg  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from src.api.security import hash_password  # noqa: E402

TEST_DSN = os.environ.get("TEST_DATABASE_URL", "")

pytestmark = pytest.mark.skipif(
    not TEST_DSN, reason="TEST_DATABASE_URL not set; skipping API integration tests"
)

PASSWORD = "test-password-123"


@pytest.fixture(scope="module")
def client():
    """A TestClient wired to a freshly migrated database."""
    from src.config import get_settings
    from src.db.migrate import migrate

    os.environ["DATABASE_URL"] = TEST_DSN
    os.environ["SESSION_SECRET"] = "a" * 48
    os.environ["ADMIN_PASSWORD_HASH"] = hash_password(PASSWORD)
    os.environ.pop("LIVE_TRADING_ENABLED", None)
    get_settings.cache_clear()

    asyncio.run(migrate(TEST_DSN))

    from src.api.main import create_app

    with TestClient(create_app()) as test_client:
        yield test_client


@pytest.fixture
def authed(client):
    response = client.post("/api/v1/auth/login", json={"password": PASSWORD})
    assert response.status_code == 200
    return client


class TestHealth:
    def test_health_needs_no_auth(self, client) -> None:
        assert client.get("/api/v1/health").json()["status"] == "ok"

    def test_ready_reports_database(self, client) -> None:
        assert client.get("/api/v1/ready").json()["database"] is True


class TestAuth:
    def test_endpoints_require_authentication(self, client) -> None:
        client.cookies.clear()
        for path in (
            "/api/v1/strategies",
            "/api/v1/backtests",
            "/api/v1/system/status",
        ):
            assert client.get(path).status_code == 401, path

    def test_wrong_password_is_rejected(self, client) -> None:
        assert (
            client.post("/api/v1/auth/login", json={"password": "nope"}).status_code
            == 401
        )

    def test_login_then_access(self, authed) -> None:
        assert authed.get("/api/v1/auth/me").json()["subject"] == "operator"

    def test_tampered_session_is_rejected(self, client) -> None:
        """A forged cookie must not authenticate — the signature is the guard."""
        client.cookies.clear()
        client.cookies.set("trader_session", "eyJzdWIiOiJvcGVyYXRvciJ9.deadbeef")
        assert client.get("/api/v1/strategies").status_code == 401
        client.cookies.clear()


class TestStrategies:
    def test_lists_with_param_schema(self, authed) -> None:
        strategies = authed.get("/api/v1/strategies").json()
        assert len(strategies) >= 1
        first = strategies[0]
        assert first["name"] == "asset_class_trend_following"
        # The schema is what renders the web form; a missing property means a
        # parameter silently becomes untunable in the UI.
        assert "sma_period" in first["params_schema"]["properties"]
        assert isinstance(first["backtest_count"], int)

    def test_unknown_strategy_is_404(self, authed) -> None:
        assert authed.get("/api/v1/strategies/nope").status_code == 404


class TestBacktests:
    def test_invalid_params_rejected_at_request_time(self, authed) -> None:
        """
        A bad parameter must fail the request, not the job. Discovering it in a
        worker log minutes later is a much worse experience.
        """
        response = authed.post(
            "/api/v1/backtests",
            json={
                "strategy": "asset_class_trend_following",
                "params": {"sma_period": -1},
            },
        )
        assert response.status_code == 422
        assert "sma_period" in response.text

    def test_unknown_strategy_rejected(self, authed) -> None:
        response = authed.post("/api/v1/backtests", json={"strategy": "nope"})
        assert response.status_code == 404

    def test_end_before_start_rejected(self, authed) -> None:
        response = authed.post(
            "/api/v1/backtests",
            json={
                "strategy": "asset_class_trend_following",
                "start": "2020-01-01",
                "end": "2019-01-01",
            },
        )
        assert response.status_code == 422

    def test_create_returns_202_and_queues_a_job(self, authed) -> None:
        response = authed.post(
            "/api/v1/backtests",
            json={
                "strategy": "asset_class_trend_following",
                "data_source": "synthetic",
                "start": "2015-01-01",
                "end": "2016-12-31",
            },
        )
        assert response.status_code == 202
        body = response.json()
        assert body["status"] == "queued"

        run = authed.get(f"/api/v1/backtests/{body['run_id']}").json()
        assert run["status"] in {"queued", "running", "succeeded"}
        # Stamped so a stored result can never be reinterpreted under different
        # assumptions than the ones it was produced under.
        assert run["decision_lag_sessions"] == 1
        assert run["engine_version"]
        assert run["cost_model"]["slippage_bps"] == 5.0

    def test_malformed_run_id_is_422_not_500(self, authed) -> None:
        assert authed.get("/api/v1/backtests/not-a-uuid").status_code == 422


class TestSystemControl:
    def test_status_reports_both_live_gates(self, authed) -> None:
        status = authed.get("/api/v1/system/status").json()
        # Live trading needs the environment gate AND the database flag. The
        # env gate is unset in tests, so no real order is possible.
        assert status["live_trading_enabled"] is False
        assert "trading_enabled" in status

    def test_kill_switch_engages_and_records_a_reason(self, authed) -> None:
        status = authed.post(
            "/api/v1/system/kill", json={"reason": "unit test"}
        ).json()
        assert status["trading_enabled"] is False
        assert status["kill_reason"] == "unit test"

    def test_resume_requires_the_exact_phrase(self, authed) -> None:
        authed.post("/api/v1/system/kill", json={"reason": "for the resume test"})
        for wrong in ("yes", "enable trading", "ENABLE  TRADING", ""):
            assert (
                authed.post(
                    "/api/v1/system/resume", json={"confirm": wrong}
                ).status_code
                == 422
            ), wrong
        assert (
            authed.post(
                "/api/v1/system/resume",
                json={"confirm": "ENABLE TRADING", "note": "ok"},
            ).json()["trading_enabled"]
            is True
        )

    def test_kill_response_carries_the_worker_list(self, authed) -> None:
        """
        Regression: /kill and /resume once built their own response and omitted
        ``workers``, which defaults to empty. The UI replaced its state with
        that and told the operator no worker was alive — a false alarm raised
        at the exact moment someone was reacting to a real problem.
        """
        killed = authed.post("/api/v1/system/kill", json={"reason": "regression"})
        resumed = authed.post(
            "/api/v1/system/resume", json={"confirm": "ENABLE TRADING"}
        )
        status = authed.get("/api/v1/system/status").json()
        for payload in (killed.json(), resumed.json()):
            assert "workers" in payload
            assert len(payload["workers"]) == len(status["workers"])

    def test_audit_log_records_control_actions(self, authed) -> None:
        authed.post("/api/v1/system/kill", json={"reason": "audit check"})
        actions = [row["action"] for row in authed.get("/api/v1/system/audit").json()]
        assert "kill_switch_engaged" in actions
        authed.post("/api/v1/system/resume", json={"confirm": "ENABLE TRADING"})


class TestKillSwitchFailsClosed:
    def test_unreadable_flag_means_disabled(self) -> None:
        """
        A control that defaults to "go" when it cannot determine the answer is
        not a safety control.
        """
        from src.db.repos.flags import trading_enabled

        class BrokenConn:
            async def fetchrow(self, *args, **kwargs):
                raise asyncpg.PostgresError("connection lost")

        assert asyncio.run(trading_enabled(BrokenConn())) is False
