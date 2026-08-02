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
    """
    Three failure modes are claimed, so three are tested.

    CLAUDE.md says ``trading_enabled`` returns ``False`` on "a missing row, an
    unreadable value, or any database error". Only the third had a test. A
    fail-closed control that has never been observed failing closed is a claim
    rather than a control, and the missing-row case is the one that actually
    happens — a fresh database before migrations, or a row deleted by hand.
    """

    def test_database_error_means_disabled(self) -> None:
        """
        A control that defaults to "go" when it cannot determine the answer is
        not a safety control.
        """
        from src.db.repos.flags import trading_enabled

        class BrokenConn:
            async def fetchrow(self, *args, **kwargs):
                raise asyncpg.PostgresError("connection lost")

        assert asyncio.run(trading_enabled(BrokenConn())) is False

    def test_missing_row_means_disabled(self, client) -> None:
        """The state a fresh or hand-edited database is actually in."""
        from src.db.repos.flags import TRADING_ENABLED, set_flag, trading_enabled

        async def check():
            conn = await asyncpg.connect(TEST_DSN)
            try:
                await conn.execute(
                    "DELETE FROM system_flags WHERE key=$1", TRADING_ENABLED
                )
                absent = await trading_enabled(conn)
                # Restore, and confirm the fixture can still say yes — a
                # function that always returns False would pass the assertion
                # above while disabling the system permanently.
                await set_flag(conn, TRADING_ENABLED, True, "test")
                restored = await trading_enabled(conn)
                return absent, restored
            finally:
                await conn.close()

        absent, restored = asyncio.run(check())
        assert absent is False
        assert restored is True

    def test_a_non_boolean_value_means_disabled(self, client) -> None:
        """
        ``value is True``, not ``bool(value)``.

        The column is JSONB, so Postgres will not hold malformed JSON — but it
        will happily hold ``"true"``, ``1`` or ``null``. Each is a value
        somebody could set by hand believing it enables trading, and each must
        read as disabled rather than being coerced into permission.
        """
        from src.db.repos.flags import TRADING_ENABLED, set_flag, trading_enabled

        async def check():
            conn = await asyncpg.connect(TEST_DSN)
            results = {}
            try:
                for label, value in (
                    ("string-true", "true"),
                    ("integer-one", 1),
                    ("null", None),
                    ("empty-object", {}),
                ):
                    await set_flag(conn, TRADING_ENABLED, value, "test")
                    results[label] = await trading_enabled(conn)
                await set_flag(conn, TRADING_ENABLED, True, "test")
                results["real-true"] = await trading_enabled(conn)
                return results
            finally:
                await conn.close()

        results = asyncio.run(check())
        for label in ("string-true", "integer-one", "null", "empty-object"):
            assert results[label] is False, f"{label} was treated as permission"
        assert results["real-true"] is True


class TestPortfolio:
    """
    Account equity, P&L and positions, read from ``daily_marks``.

    The plan listed these endpoints from the start and neither existed. They
    could not have, usefully: nothing wrote ``daily_marks`` until the risk-gate
    work, so there was no equity history to serve.

    P&L here is a change in marked equity. The legacy ``get_daily_pnl`` sums
    buy/sell cash flow and would report a $100 purchase as a $100 loss; nothing
    in this router may reach it.
    """

    def test_requires_authentication(self, client) -> None:
        client.cookies.clear()
        assert client.get("/api/v1/portfolio").status_code == 401
        assert client.get("/api/v1/portfolio/history").status_code == 401

    def test_empty_history_reports_unknown_not_zero(self, authed) -> None:
        """
        Zero equity and *unknown* equity are different states.

        Rendering the second as the first shows an operator a flat line at zero
        where they should see "no data" — and a flat line is exactly what a
        broken mark writer would also produce.
        """
        import asyncio as _asyncio

        async def clear():
            conn = await asyncpg.connect(TEST_DSN)
            try:
                await conn.execute("DELETE FROM daily_marks")
            finally:
                await conn.close()

        _asyncio.run(clear())
        body = authed.get("/api/v1/portfolio").json()
        assert body["equity"] is None
        assert body["cumulative_pnl"] is None
        assert body["note"] == "no marks recorded yet"

    def test_reports_the_latest_mark_and_the_peak(self, authed) -> None:
        import asyncio as _asyncio
        from datetime import date as _date
        from decimal import Decimal as _Decimal

        from src.db.repos import marks

        async def seed():
            conn = await asyncpg.connect(TEST_DSN)
            try:
                await conn.execute("DELETE FROM daily_marks")
                await marks.record_mark(
                    conn, _date(2021, 3, 1), _Decimal("100000"), _Decimal("100000")
                )
                await marks.record_mark(
                    conn, _date(2021, 3, 2), _Decimal("110000"), _Decimal("10000")
                )
                await marks.record_mark(
                    conn, _date(2021, 3, 3), _Decimal("99000"), _Decimal("9000")
                )
            finally:
                await conn.close()

        _asyncio.run(seed())
        body = authed.get("/api/v1/portfolio").json()

        assert body["as_of"] == "2021-03-03"
        assert body["equity"] == 99000.0
        assert body["daily_pnl"] == -11000.0
        assert body["cumulative_pnl"] == -1000.0
        # The peak is the 110k session, not the latest — drawdown is measured
        # against the high-water mark or it is not a drawdown.
        assert body["peak_equity"] == 110000.0
        assert body["drawdown_pct"] == pytest.approx(-0.1, abs=1e-9)

    def test_history_is_oldest_first_for_plotting(self, authed) -> None:
        body = authed.get("/api/v1/portfolio/history").json()
        sessions = [m["session"] for m in body["marks"]]
        assert sessions == sorted(sessions)
        assert body["count"] == len(sessions)

    def test_an_unknown_mode_is_422_not_a_silent_empty_curve(self, authed) -> None:
        """
        A typo must not return an empty portfolio that looks like a real one.
        """
        assert authed.get("/api/v1/portfolio?mode=papper").status_code == 422
        assert (
            authed.get("/api/v1/portfolio/history?mode=nonsense").status_code == 422
        )

    def test_paper_and_live_are_never_mixed(self, authed) -> None:
        """Two accounts, two curves. Summing them would be meaningless."""
        import asyncio as _asyncio
        from datetime import date as _date
        from decimal import Decimal as _Decimal

        from src.db.repos import marks

        async def seed():
            conn = await asyncpg.connect(TEST_DSN)
            try:
                await marks.record_mark(
                    conn, _date(2021, 3, 3), _Decimal("5"), _Decimal("5"), mode="live"
                )
            finally:
                await conn.close()

        _asyncio.run(seed())
        paper = authed.get("/api/v1/portfolio?mode=paper").json()
        live = authed.get("/api/v1/portfolio?mode=live").json()
        assert paper["equity"] == 99000.0
        assert live["equity"] == 5.0


class TestLoginBackoff:
    """
    The throttle, over real HTTP through the real route.

    ``tests/unit/test_login_throttle.py`` proves the counter's arithmetic. This
    proves the route consults it — the same distinction that hid four of the
    bugs found in this codebase, where a correct component was never reached by
    the code that ships.
    """

    def _reset(self):
        from src.api.throttle import throttle

        throttle.reset()

    def test_repeated_failures_eventually_return_429(self, client) -> None:
        from src.api.throttle import FREE_ATTEMPTS

        self._reset()
        client.cookies.clear()

        # The free allowance must all come back as 401 — a throttle that
        # engaged immediately would break the operator's first typo. The
        # attempt *past* the allowance is also a 401: it is what arms the
        # block, and a request already being processed cannot be refused
        # retroactively. The one after it is the first to be turned away.
        for _ in range(FREE_ATTEMPTS + 1):
            assert (
                client.post(
                    "/api/v1/auth/login", json={"password": "wrong"}
                ).status_code
                == 401
            )

        blocked = client.post("/api/v1/auth/login", json={"password": "wrong"})
        assert blocked.status_code == 429
        assert "Retry-After" in blocked.headers
        assert "retry in" in blocked.json()["detail"]
        self._reset()

    def test_a_blocked_source_is_refused_even_with_the_right_password(
        self, client
    ) -> None:
        """
        The credentials are never checked while blocked.

        Otherwise the backoff would be advisory: an attacker who guessed
        correctly on attempt 500 would still be let in.
        """
        from src.api.throttle import FREE_ATTEMPTS

        self._reset()
        client.cookies.clear()
        for _ in range(FREE_ATTEMPTS + 1):
            client.post("/api/v1/auth/login", json={"password": "wrong"})

        refused = client.post("/api/v1/auth/login", json={"password": PASSWORD})
        assert refused.status_code == 429
        self._reset()

    def test_a_correct_password_still_works_and_clears_the_count(
        self, client
    ) -> None:
        """
        The other direction. A control nobody can satisfy gets removed by the
        next person in a hurry.
        """
        self._reset()
        client.cookies.clear()
        client.post("/api/v1/auth/login", json={"password": "wrong"})

        ok = client.post("/api/v1/auth/login", json={"password": PASSWORD})
        assert ok.status_code == 200
        assert client.get("/api/v1/auth/me").status_code == 200

        # And the failure count is gone, so the next typo starts fresh.
        from src.api.throttle import throttle

        assert throttle.retry_after("testclient") == 0.0
        self._reset()

    def test_status_reports_all_three_live_gates_separately(self, authed) -> None:
        """
        Each gate reported on its own, never summarised into one flag.

        The System page used to say "both gates". An operator reading that
        would reasonably conclude LIVE_TRADING_ENABLED was sufficient — which
        is precisely the misunderstanding the third gate exists to prevent, and
        precisely the mistake `_alpaca_from_env` itself once made by deriving
        one gate from another.
        """
        status = authed.get("/api/v1/system/status").json()
        assert status["live_trading_enabled"] is False
        assert status["alpaca_allow_live"] is False
        # Reported independently: neither may be inferred from the other.
        assert "live_trading_enabled" in status and "alpaca_allow_live" in status
