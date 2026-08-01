"""
test_live_path.py
-----------------
The live trading path: deployment gate, dry run, and kill-switch enforcement.

Runs against a real PostgreSQL database and the fake Alpaca venue, so the
whole chain — decision persisted, orders staged, kill switch consulted, orders
submitted over HTTP — is exercised rather than mocked.

Skipped unless ``TEST_DATABASE_URL`` is set.
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("aiohttp")

import asyncpg  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from src.api.security import hash_password  # noqa: E402
from src.core.calendar import sessions as nyse_sessions  # noqa: E402
from src.data import SyntheticSource  # noqa: E402
from src.db.repos import flags, marks  # noqa: E402
from src.execution.alpaca import AlpacaBroker  # noqa: E402
from src.worker.live_job import (  # noqa: E402
    _decide_for,
    _enabled_deployments,
    dry_run,
    run_live_decision,
    run_submit_orders,
)
from tests.fakes.alpaca_server import KEY_ID, SECRET_KEY, FakeAlpaca  # noqa: E402

TEST_DSN = os.environ.get("TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(not TEST_DSN, reason="TEST_DATABASE_URL not set")

PASSWORD = "test-password-123"
UNIVERSE = ["SPY", "EFA", "IEF", "VNQ", "GSG"]


def _live_dsn() -> str:
    """A separate database so these tests cannot disturb the API suite."""
    base, _, tail = TEST_DSN.partition("?")
    return f"{base}_live?{tail}" if tail else f"{base}_live"


def _live_db_name() -> str:
    """
    The bare database name.

    Taken from the portion *before* the query string: a Unix-socket DSN puts
    ``host=/tmp`` in the query, so splitting the whole URL on "/" returns the
    socket path rather than the database.
    """
    base, _, _tail = _live_dsn().partition("?")
    return base.rsplit("/", 1)[-1]


@pytest.fixture(scope="module")
def dsn():
    from src.db.migrate import migrate

    async def setup() -> str:
        admin = await asyncpg.connect(TEST_DSN)
        name = _live_db_name()
        await admin.execute(f'DROP DATABASE IF EXISTS "{name}"')
        await admin.execute(f'CREATE DATABASE "{name}"')
        await admin.close()
        await migrate(_live_dsn())
        return _live_dsn()

    return asyncio.run(setup())


@pytest.fixture(scope="module")
def seeded(dsn):
    """A database with bars, a succeeded backtest, and an enabled deployment."""

    async def seed():
        conn = await asyncpg.connect(dsn)
        sessions = nyse_sessions(date(2020, 1, 1), date(2021, 6, 30))
        bars = SyntheticSource().fetch(UNIVERSE, date(2015, 1, 1), sessions[-1])
        await conn.executemany(
            "INSERT INTO daily_bars (symbol, session, source, open, high, low, "
            "close, volume, adj_close) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9) "
            "ON CONFLICT DO NOTHING",
            [
                (b.symbol, b.session, "synthetic", b.open, b.high, b.low,
                 b.close, b.volume, b.adj_close)
                for b in bars
            ],
        )

        run_id = uuid.uuid4()
        await conn.execute(
            """
            INSERT INTO backtest_runs (id, strategy_name, params, universe,
                start_session, end_session, initial_cash, data_source,
                cost_model, status, metrics)
            VALUES ($1,'asset_class_trend_following','{}'::jsonb,$2,
                    $3,$4,100000,'yfinance','{}'::jsonb,'succeeded','{}'::jsonb)
            """,
            run_id, UNIVERSE, date(2015, 1, 1), date(2019, 12, 31),
        )

        deployment_id = uuid.uuid4()
        await conn.execute(
            """
            INSERT INTO deployments (id, strategy_name, params, mode,
                capital_usd, risk_limits, approved_backtest_run_id, status)
            VALUES ($1,'asset_class_trend_following','{}'::jsonb,'paper',
                    100000,'{}'::jsonb,$2,'enabled')
            """,
            deployment_id, run_id,
        )
        # The deployment gate now also requires a completed, robust
        # walk-forward for the strategy+params. Seeded here so the tests that
        # exercise the gate's *other* conditions can reach them; the
        # walk-forward condition has its own tests below.
        await _seed_robust_walkforward(
            conn, run_id, "asset_class_trend_following", {}
        )
        await conn.close()
        return {
            "run_id": str(run_id),
            "deployment_id": deployment_id,
            "sessions": sessions,
        }

    return asyncio.run(seed())


@pytest.fixture
def client(dsn):
    from src.config import get_settings

    os.environ["DATABASE_URL"] = dsn
    os.environ["SESSION_SECRET"] = "b" * 48
    os.environ["ADMIN_PASSWORD_HASH"] = hash_password(PASSWORD)
    os.environ.pop("LIVE_TRADING_ENABLED", None)
    get_settings.cache_clear()

    from src.api.main import create_app

    with TestClient(create_app()) as test_client:
        test_client.post("/api/v1/auth/login", json={"password": PASSWORD})
        yield test_client


async def _with_venue(fn, **server_kwargs):
    server = FakeAlpaca(**server_kwargs)
    base_url = await server.start()

    def factory():
        return AlpacaBroker(KEY_ID, SECRET_KEY, base_url=base_url)

    try:
        return await fn(factory, server)
    finally:
        await server.stop()


async def _seed_robust_walkforward(conn, run_id, strategy, params=None):
    """
    Record a completed, robust walk-forward for a strategy+params.

    The deployment gate refuses without one — a single backtest cannot tell an
    edge from parameters fitted to noise. These tests are about the *other*
    gate conditions, so they satisfy this one explicitly rather than having it
    quietly disabled for them.
    """
    await conn.execute(
        """
        INSERT INTO walkforward_runs (id, backtest_run_id, strategy_name,
            params, param_grid, start_session, end_session, train_months,
            test_months, data_source, status, is_robust, degradation, n_folds)
        VALUES ($1,$2,$3,$4::jsonb,'{}'::jsonb,$5,$6,36,12,'yfinance',
                'succeeded', TRUE, 0.05, 4)
        """,
        uuid.uuid4(), run_id, strategy,
        json.dumps(params or {}, sort_keys=True),
        date(2015, 1, 1), date(2019, 12, 31),
    )


def _in_window(session):
    """
    A clock reading just after ``session``'s open.

    These tests use 2021 dates, whose real submission window closed years ago.
    Pinning the clock keeps them testing submission rather than the staleness
    guard — which has its own tests, in both directions.
    """
    from src.core.calendar import session_open
    from src.engine.scheduler import SUBMIT_AFTER_OPEN

    return session_open(session) + SUBMIT_AFTER_OPEN


class TestDeploymentGate:
    """A deployment must be backed by a real, completed backtest."""

    def test_unknown_backtest_is_refused(self, client, seeded) -> None:
        response = client.post(
            "/api/v1/deployments",
            json={
                "strategy": "asset_class_trend_following",
                "capital_usd": 10000,
                "approved_backtest_run_id": str(uuid.uuid4()),
            },
        )
        assert response.status_code == 422
        assert "unknown backtest run" in response.json()["detail"]

    def test_synthetic_backtest_cannot_back_a_deployment(
        self, client, dsn
    ) -> None:
        """
        Synthetic data says nothing about real performance. Allowing it to
        justify a deployment would make the gate ceremonial.
        """

        async def make_synthetic_run() -> str:
            conn = await asyncpg.connect(dsn)
            run_id = uuid.uuid4()
            await conn.execute(
                """
                INSERT INTO backtest_runs (id, strategy_name, params, universe,
                    start_session, end_session, initial_cash, data_source,
                    cost_model, status)
                VALUES ($1,'asset_class_trend_following','{}'::jsonb,$2,
                        $3,$4,100000,'synthetic','{}'::jsonb,'succeeded')
                """,
                run_id, UNIVERSE, date(2020, 1, 1), date(2020, 12, 31),
            )
            await conn.close()
            return str(run_id)

        run_id = asyncio.run(make_synthetic_run())
        response = client.post(
            "/api/v1/deployments",
            json={
                "strategy": "asset_class_trend_following",
                "capital_usd": 10000,
                "approved_backtest_run_id": run_id,
            },
        )
        assert response.status_code == 422
        assert "synthetic" in response.json()["detail"]

    def test_queued_backtest_cannot_back_a_deployment(self, client, dsn) -> None:
        async def make_queued_run() -> str:
            conn = await asyncpg.connect(dsn)
            run_id = uuid.uuid4()
            await conn.execute(
                """
                INSERT INTO backtest_runs (id, strategy_name, params, universe,
                    start_session, end_session, initial_cash, data_source,
                    cost_model, status)
                VALUES ($1,'asset_class_trend_following','{}'::jsonb,$2,
                        $3,$4,100000,'yfinance','{}'::jsonb,'queued')
                """,
                run_id, UNIVERSE, date(2020, 1, 1), date(2020, 12, 31),
            )
            await conn.close()
            return str(run_id)

        response = client.post(
            "/api/v1/deployments",
            json={
                "strategy": "asset_class_trend_following",
                "capital_usd": 10000,
                "approved_backtest_run_id": asyncio.run(make_queued_run()),
            },
        )
        assert response.status_code == 422
        assert "not 'succeeded'" in response.json()["detail"]

    def test_valid_backtest_creates_a_disabled_deployment(
        self, client, seeded
    ) -> None:
        """New deployments never start enabled."""
        response = client.post(
            "/api/v1/deployments",
            json={
                "strategy": "asset_class_trend_following",
                "capital_usd": 10000,
                "approved_backtest_run_id": seeded["run_id"],
            },
        )
        assert response.status_code == 201
        assert response.json()["status"] == "disabled"

    def test_live_mode_refused_without_environment_gate(
        self, client, seeded
    ) -> None:
        response = client.post(
            "/api/v1/deployments",
            json={
                "strategy": "asset_class_trend_following",
                "capital_usd": 10000,
                "approved_backtest_run_id": seeded["run_id"],
                "mode": "live",
            },
        )
        assert response.status_code == 403
        assert "LIVE_TRADING_ENABLED" in response.json()["detail"]

    def test_enable_requires_typed_confirmation(self, client, seeded) -> None:
        created = client.post(
            "/api/v1/deployments",
            json={
                "strategy": "asset_class_trend_following",
                "capital_usd": 10000,
                "approved_backtest_run_id": seeded["run_id"],
            },
        ).json()
        deployment_id = created["id"]

        for wrong in ("yes", "enable deployment", ""):
            assert (
                client.post(
                    f"/api/v1/deployments/{deployment_id}/enable",
                    json={"confirm": wrong},
                ).status_code
                == 422
            )

        ok = client.post(
            f"/api/v1/deployments/{deployment_id}/enable",
            json={"confirm": "ENABLE DEPLOYMENT"},
        )
        assert ok.json()["status"] == "enabled"

        # Disabling needs no confirmation — stopping is always easy.
        assert (
            client.post(f"/api/v1/deployments/{deployment_id}/disable").json()[
                "status"
            ]
            == "disabled"
        )


class TestDryRun:
    def test_computes_orders_without_submitting_any(self, dsn, seeded) -> None:
        """
        The most useful endpoint: what would this do, without doing it.
        """

        async def check(factory, server):
            conn = await asyncpg.connect(dsn)
            try:
                # First session of a month, so the strategy rebalances.
                session = next(
                    s for s in seeded["sessions"] if s >= date(2021, 3, 1)
                )
                result = await dry_run(
                    conn, seeded["deployment_id"], session, broker_factory=factory
                )
                return result, server.submitted
            finally:
                await conn.close()

        result, submitted = asyncio.run(_with_venue(check))
        assert result["submitted"] is False
        assert submitted == [], "dry run must not reach the venue"
        assert "target_weights" in result
        assert result["order_intents"], "expected orders from an all-cash start"
        # Deterministic ids make the result comparable with the backtest.
        for intent in result["order_intents"]:
            assert intent["client_order_id"].count(":") == 2


class TestKillSwitchStopsSubmission:
    """
    The property that matters most. The database flag must prevent orders
    reaching the venue, not merely be recorded somewhere.
    """

    def test_orders_are_submitted_when_trading_is_enabled(
        self, dsn, seeded
    ) -> None:
        async def check(factory, server):
            conn = await asyncpg.connect(dsn)
            try:
                await flags.release_kill_switch(conn, actor="test")
                decision_session = next(
                    s for s in seeded["sessions"] if s >= date(2021, 4, 1)
                )
                await conn.execute(
                    "DELETE FROM decisions WHERE deployment_id=$1",
                    seeded["deployment_id"],
                )
                await run_live_decision(
                    conn,
                    {"session": decision_session.isoformat()},
                    broker_factory=factory,
                )
                nxt = next(s for s in seeded["sessions"] if s > decision_session)
                result = await run_submit_orders(
                    conn, {"session": nxt.isoformat()}, broker_factory=factory,
                    now=_in_window(nxt),
                )
                return result, server.submitted
            finally:
                await conn.close()

        result, submitted = asyncio.run(_with_venue(check))
        assert result["submitted"] > 0
        assert len(submitted) == result["submitted"]

    def test_kill_switch_blocks_every_order(self, dsn, seeded) -> None:
        async def check(factory, server):
            conn = await asyncpg.connect(dsn)
            try:
                await flags.release_kill_switch(conn, actor="test")
                decision_session = next(
                    s for s in seeded["sessions"] if s >= date(2021, 5, 1)
                )
                await conn.execute(
                    "DELETE FROM decisions WHERE deployment_id=$1 AND session=$2",
                    seeded["deployment_id"], decision_session,
                )
                await run_live_decision(
                    conn,
                    {"session": decision_session.isoformat()},
                    broker_factory=factory,
                )
                # Engage AFTER the decision but BEFORE submission — the exact
                # window a check at job start would miss.
                await flags.engage_kill_switch(conn, "test halt", actor="test")
                nxt = next(s for s in seeded["sessions"] if s > decision_session)
                result = await run_submit_orders(
                    conn, {"session": nxt.isoformat()}, broker_factory=factory,
                    now=_in_window(nxt),
                )
                status = await conn.fetchval(
                    "SELECT status FROM decisions WHERE deployment_id=$1 "
                    "AND session=$2",
                    seeded["deployment_id"], decision_session,
                )
                return result, server.submitted, status
            finally:
                await flags.release_kill_switch(conn, actor="test")
                await conn.close()

        result, submitted, status = asyncio.run(_with_venue(check))
        assert result["submitted"] == 0
        assert submitted == [], "kill switch must stop orders reaching the venue"
        assert status == "blocked_by_kill_switch"

    def test_decision_is_recorded_even_when_blocked(self, dsn, seeded) -> None:
        """
        Halting trading must not stop the system recording what it *would*
        have done. Losing that record is losing the ability to investigate the
        thing you halted for.
        """

        async def check(factory, server):
            conn = await asyncpg.connect(dsn)
            try:
                rows = await conn.fetch(
                    "SELECT session, order_intents, status FROM decisions "
                    "WHERE deployment_id=$1 ORDER BY session",
                    seeded["deployment_id"],
                )
                return rows
            finally:
                await conn.close()

        rows = asyncio.run(_with_venue(check))
        assert rows, "decisions should persist regardless of submission outcome"
        for row in rows:
            intents = row["order_intents"]
            assert isinstance(
                json.loads(intents) if isinstance(intents, str) else intents, list
            )


class TestKillSwitchEngagedMidBatch:
    """
    The switch thrown *between* orders, which is the case the pre-batch check
    cannot cover.

    ``live_job``'s docstring promises the flag is "re-read between orders too,
    so engaging it partway through a batch stops the remainder". The check
    exists, but the class above only ever engages the switch *before*
    ``run_submit_orders`` is called, so it tests the pre-batch guard and returns
    early. Everything after that guard was unexercised.

    Two things must hold when a batch is cut short, and neither is about the
    orders that did go out:

    1. The decision must not be recorded as ``submitted``. It is the system's
       account of what happened, and "submitted" for a batch that was halted
       three orders in is simply false.
    2. That record is also the retry filter — ``run_submit_orders`` selects
       ``status = 'planned'``. Marking a halted batch ``submitted`` retires it,
       so the un-sent remainder can never go out, even after the switch is
       released. The orders are not deferred; they are lost silently, and the
       ledger claims a rebalance that never fully happened.
    """

    @staticmethod
    def _halting_factory(inner_factory, dsn, after=1):
        """
        A broker that engages the kill switch once ``after`` orders are away.

        Stands in for an operator hitting the switch while a batch is in
        flight. It wraps rather than replaces the real adapter, so the orders
        preceding the halt take the genuine path to the fake venue.
        """

        class HaltsMidBatch:
            def __init__(self) -> None:
                self._inner = inner_factory()
                self.sent = 0

            async def __aenter__(self):
                await self._inner.__aenter__()
                return self

            async def __aexit__(self, *exc):
                return await self._inner.__aexit__(*exc)

            async def get_account(self):
                return await self._inner.get_account()

            async def get_positions(self):
                return await self._inner.get_positions()

            async def submit(self, intent, client_order_id=None):
                ack = await self._inner.submit(
                    intent, client_order_id=client_order_id
                )
                self.sent += 1
                if self.sent == after:
                    halt_conn = await asyncpg.connect(dsn)
                    try:
                        await flags.engage_kill_switch(
                            halt_conn, "halted mid-batch", actor="test"
                        )
                    finally:
                        await halt_conn.close()
                return ack

        return HaltsMidBatch

    def test_a_halted_batch_is_not_recorded_as_submitted(self, dsn, seeded) -> None:
        async def check(factory, server):
            conn = await asyncpg.connect(dsn)
            try:
                await flags.release_kill_switch(conn, actor="test")
                # Reset the schedule as well as the decisions. `last_rebalance`
                # persists across tests in this module, and a stale value in
                # the same month makes `should_rebalance` return False, so the
                # decision below is never created and the test measures
                # nothing. Control the variable rather than depending on order.
                await conn.execute(
                    "DELETE FROM decisions WHERE deployment_id=$1",
                    seeded["deployment_id"],
                )
                await conn.execute(
                    "UPDATE deployments SET last_rebalance=NULL WHERE id=$1",
                    seeded["deployment_id"],
                )
                decision_session = next(
                    s for s in seeded["sessions"] if s >= date(2021, 4, 1)
                )
                await run_live_decision(
                    conn,
                    {"session": decision_session.isoformat()},
                    broker_factory=factory,
                )
                planned = await conn.fetchval(
                    "SELECT order_intents FROM decisions "
                    "WHERE deployment_id=$1 AND session=$2",
                    seeded["deployment_id"], decision_session,
                )
                planned = (
                    json.loads(planned) if isinstance(planned, str) else planned
                )

                nxt = next(s for s in seeded["sessions"] if s > decision_session)
                result = await run_submit_orders(
                    conn,
                    {"session": nxt.isoformat()},
                    broker_factory=self._halting_factory(factory, dsn, after=1),
                    now=_in_window(nxt),
                )
                status = await conn.fetchval(
                    "SELECT status FROM decisions "
                    "WHERE deployment_id=$1 AND session=$2",
                    seeded["deployment_id"], decision_session,
                )
                return result, server.submitted, status, planned
            finally:
                await flags.release_kill_switch(conn, actor="test")
                await conn.close()

        result, submitted, status, planned = asyncio.run(_with_venue(check))

        # The scenario is only meaningful if there was a remainder to stop.
        assert len(planned) >= 2, "need a multi-order batch to cut short"
        assert len(submitted) == 1, "the halt should stop the batch after one"

        assert status != "submitted", (
            "a batch halted after 1 of "
            f"{len(planned)} orders was recorded as fully submitted; the "
            "un-sent remainder can never be retried because run_submit_orders "
            "only selects status='planned'"
        )
        assert status == "partially_submitted", status
        assert result["submitted"] == 1
        assert result["skipped"] == 1

    def test_a_batch_halted_before_its_first_order_says_so(
        self, dsn, seeded
    ) -> None:
        """
        Halted with nothing sent is a different outcome from halted halfway,
        and the status distinguishes them. "Partially submitted" when nothing
        was submitted would send an operator looking for fills that do not
        exist.
        """

        async def check(factory, server):
            conn = await asyncpg.connect(dsn)
            try:
                await flags.release_kill_switch(conn, actor="test")
                # Reset the schedule as well as the decisions. `last_rebalance`
                # persists across tests in this module, and a stale value in
                # the same month makes `should_rebalance` return False, so the
                # decision below is never created and the test measures
                # nothing. Control the variable rather than depending on order.
                await conn.execute(
                    "DELETE FROM decisions WHERE deployment_id=$1",
                    seeded["deployment_id"],
                )
                await conn.execute(
                    "UPDATE deployments SET last_rebalance=NULL WHERE id=$1",
                    seeded["deployment_id"],
                )
                decision_session = next(
                    s for s in seeded["sessions"] if s >= date(2021, 4, 1)
                )
                await run_live_decision(
                    conn,
                    {"session": decision_session.isoformat()},
                    broker_factory=factory,
                )
                nxt = next(s for s in seeded["sessions"] if s > decision_session)

                # after=0 never fires inside submit, so engage it here: the
                # batch passes the pre-flight check and is stopped on the
                # first per-order re-read.
                await flags.engage_kill_switch(conn, "pre-flight", actor="test")
                result = await run_submit_orders(
                    conn,
                    {"session": nxt.isoformat()},
                    broker_factory=factory,
                    now=_in_window(nxt),
                )
                status = await conn.fetchval(
                    "SELECT status FROM decisions "
                    "WHERE deployment_id=$1 AND session=$2",
                    seeded["deployment_id"], decision_session,
                )
                return result, server.submitted, status
            finally:
                await flags.release_kill_switch(conn, actor="test")
                await conn.close()

        result, submitted, status = asyncio.run(_with_venue(check))
        assert submitted == []
        assert status == "blocked_by_kill_switch"
        assert result["submitted"] == 0


class TestIdempotency:
    def test_resubmitting_the_same_session_does_not_double_trade(
        self, dsn, seeded
    ) -> None:
        """
        A retried submit job reuses the deterministic client order ids, which
        the venue rejects as duplicates. The position cannot be doubled.
        """

        async def check(factory, server):
            conn = await asyncpg.connect(dsn)
            try:
                await flags.release_kill_switch(conn, actor="test")
                decision_session = next(
                    s for s in seeded["sessions"] if s >= date(2021, 6, 1)
                )
                await conn.execute(
                    "DELETE FROM decisions WHERE deployment_id=$1 AND session=$2",
                    seeded["deployment_id"], decision_session,
                )
                await run_live_decision(
                    conn,
                    {"session": decision_session.isoformat()},
                    broker_factory=factory,
                )
                nxt = next(s for s in seeded["sessions"] if s > decision_session)
                first = await run_submit_orders(
                    conn, {"session": nxt.isoformat()}, broker_factory=factory,
                    now=_in_window(nxt),
                )
                # Re-arm the decision to simulate a retry of the same batch.
                await conn.execute(
                    "UPDATE decisions SET status='planned' WHERE deployment_id=$1 "
                    "AND session=$2",
                    seeded["deployment_id"], decision_session,
                )
                await run_submit_orders(
                    conn, {"session": nxt.isoformat()}, broker_factory=factory,
                    now=_in_window(nxt),
                )
                return first, len(server.orders)
            finally:
                await conn.close()

        first, orders_at_venue = asyncio.run(_with_venue(check))
        assert first["submitted"] > 0
        # The retry is refused, so the venue holds exactly one batch.
        assert orders_at_venue == first["submitted"]


class TestRiskGateOnTheLivePath:
    """
    The live decision must go through ``apply_risk``, same as the backtest.

    This is CLAUDE.md safety rule 3: *every trade path goes through
    ``apply_risk`` — the same call on both paths*. It was violated. The live
    job constructed a ``Driver``, never called it, and reimplemented the
    sequence inline without the gate — so live ran an ungated strategy while
    the backtest that authorised it ran a gated one. No cash buffer, no
    daily-loss halt, no drawdown halt, no cooldown.

    ``test_parity.py`` could not see it: both of its paths call
    ``Driver.step``, and neither touches ``run_live_decision``. That is the
    hole this class closes — it asserts against the *shipped live job*, not
    against the driver the live job was supposed to be using.
    """

    #: The strategy equal-weights five ETFs at 0.20 each, so a 0.15 cap binds
    #: on every one of them. Chosen so the assertion cannot pass by accident.
    CAP = 0.15

    @pytest.fixture(scope="class")
    def gated_deployment(self, dsn, seeded):
        """A second deployment whose risk limits actually bind."""

        async def seed():
            conn = await asyncpg.connect(dsn)
            try:
                deployment_id = uuid.uuid4()
                await conn.execute(
                    """
                    INSERT INTO deployments (id, strategy_name, params, mode,
                        capital_usd, risk_limits, approved_backtest_run_id,
                        status)
                    VALUES ($1,'asset_class_trend_following','{}'::jsonb,'paper',
                            100000,$2::jsonb,$3,'disabled')
                    """,
                    deployment_id,
                    json.dumps(
                        {"max_weight_per_asset": self.CAP, "min_trade_usd": 25.0}
                    ),
                    uuid.UUID(seeded["run_id"]),
                )
                return deployment_id
            finally:
                await conn.close()

        return asyncio.run(seed())

    def test_a_binding_limit_actually_binds_on_the_live_path(
        self, dsn, seeded, gated_deployment
    ) -> None:
        """
        A configured cap changes the persisted decision.

        Before the fix the stored weights were the strategy's raw 0.20 — the
        limit was accepted by the API, shown in the UI as configured, and
        silently never applied.
        """

        async def check(factory, server):
            conn = await asyncpg.connect(dsn)
            try:
                await conn.execute(
                    "UPDATE deployments SET status='enabled' WHERE id=$1",
                    gated_deployment,
                )
                # Isolate: the other deployment would also decide this session.
                await conn.execute(
                    "UPDATE deployments SET status='disabled' WHERE id=$1",
                    seeded["deployment_id"],
                )
                session = next(
                    s for s in seeded["sessions"] if s >= date(2021, 6, 1)
                )
                await conn.execute(
                    "DELETE FROM decisions WHERE deployment_id=$1", gated_deployment
                )
                await run_live_decision(
                    conn,
                    {
                        "session": session.isoformat(),
                        "deployment_ids": [str(gated_deployment)],
                    },
                    broker_factory=factory,
                )
                return await conn.fetchrow(
                    "SELECT target_weights, raw_target_weights, risk_events, "
                    "order_intents FROM decisions WHERE deployment_id=$1",
                    gated_deployment,
                )
            finally:
                # Restore the shared fixture for whatever runs next.
                await conn.execute(
                    "UPDATE deployments SET status='enabled' WHERE id=$1",
                    seeded["deployment_id"],
                )
                await conn.close()

        row = asyncio.run(_with_venue(check))
        assert row is not None, "the gated deployment produced no decision"

        gated = _as_json(row["target_weights"])
        raw = _as_json(row["raw_target_weights"])
        events = _as_json(row["risk_events"])

        assert gated, "expected a non-empty allocation to gate"
        for symbol, weight in gated.items():
            assert weight <= self.CAP + 1e-9, f"{symbol} escaped the cap"

        # Both sides recorded. Without the raw weights there is no way to tell,
        # after the fact, whether a limit changed the answer or merely ran.
        assert raw, "pre-gate weights were not recorded"
        assert max(raw.values()) > self.CAP, (
            "the strategy did not exceed the cap, so this test proves nothing"
        )

        binding = [e for e in events if e["binding"]]
        assert binding, "the gate bound but recorded no event"
        assert any(e["code"] == "max_weight_clamp" for e in binding)

    def test_dry_run_previews_gated_orders(
        self, dsn, seeded, gated_deployment
    ) -> None:
        """
        The preview shows what will actually happen, gate included.

        An operator reads this screen before authorising a deployment. A
        preview of ungated orders is worse than no preview.
        """

        async def check(factory, server):
            conn = await asyncpg.connect(dsn)
            try:
                session = next(
                    s for s in seeded["sessions"] if s >= date(2021, 6, 1)
                )
                return await dry_run(
                    conn,
                    gated_deployment,
                    session,
                    broker_factory=factory,
                )
            finally:
                await conn.close()

        result = asyncio.run(_with_venue(check))

        assert result["order_intents"], "expected orders from an all-cash start"
        for symbol, weight in result["target_weights"].items():
            assert weight <= self.CAP + 1e-9, f"{symbol} escaped the cap"
        assert max(result["raw_target_weights"].values()) > self.CAP
        assert any(e["binding"] for e in result["risk_events"])


def _as_json(value):
    """asyncpg returns JSONB as str or dict depending on codec registration."""
    return json.loads(value) if isinstance(value, str) else value


class TestMarksFeedTheRiskGate:
    """
    A live process is rebuilt for every session; its risk memory must not be.

    ``max_drawdown_pct`` is measured against peak equity, and a ``Driver``
    constructed fresh each job knows of no peak but the one it was just told.
    Without ``daily_marks`` behind it the peak is zero, the drawdown is zero,
    and the limit is inert — while the backtest that authorised the deployment
    honours it. That is the exact backtest/live divergence this repository
    exists to prevent, so it gets a test against the shipped job.

    ``daily_marks`` also carries the P&L record. It had a table, a schema, and
    a paragraph in CLAUDE.md describing it as the source of truth — and no
    writer at all.
    """

    def test_a_mark_is_recorded_for_the_decision_session(
        self, dsn, seeded
    ) -> None:
        async def check(factory, server):
            conn = await asyncpg.connect(dsn)
            try:
                session = next(
                    s for s in seeded["sessions"] if s >= date(2021, 6, 1)
                )
                await conn.execute("DELETE FROM daily_marks")
                await conn.execute(
                    "DELETE FROM decisions WHERE deployment_id=$1",
                    seeded["deployment_id"],
                )
                await run_live_decision(
                    conn,
                    {"session": session.isoformat()},
                    broker_factory=factory,
                )
                return await conn.fetchrow(
                    "SELECT session, equity, cash, daily_pnl, drawdown_pct "
                    "FROM daily_marks ORDER BY session DESC LIMIT 1"
                )
            finally:
                await conn.close()

        row = asyncio.run(_with_venue(check))
        assert row is not None, "the live decision recorded no mark"
        assert row["equity"] > 0
        # The first mark has nothing to difference against, so zero is the
        # honest daily P&L rather than the whole opening balance booked as a
        # gain. (The legacy get_daily_pnl would have reported cash flow here.)
        assert float(row["daily_pnl"]) == 0.0

    def test_pnl_is_a_change_in_equity_not_cash_flow(self, dsn) -> None:
        """
        ``equity_t - equity_{t-1} - net deposits``.

        Written directly against the repository because the legacy
        ``get_daily_pnl`` sums buy/sell cash flow, which makes a $100 purchase
        read as a $100 loss. The distinction is the whole reason this table
        exists, so it is asserted rather than assumed.
        """

        async def check():
            conn = await asyncpg.connect(dsn)
            try:
                await conn.execute("DELETE FROM daily_marks")
                await marks.record_mark(
                    conn, date(2021, 3, 1), Decimal("100000"), Decimal("100000")
                )
                # Equity up 5k, but 4k of it was deposited: P&L is 1k.
                second = await marks.record_mark(
                    conn,
                    date(2021, 3, 2),
                    Decimal("105000"),
                    Decimal("5000"),
                    deposits=Decimal("4000"),
                )
                third = await marks.record_mark(
                    conn, date(2021, 3, 3), Decimal("94500"), Decimal("500")
                )
                peak = await marks.peak_equity(conn)
                prior = await marks.prior_equity(conn, date(2021, 3, 3))
                return second, third, peak, prior
            finally:
                await conn.close()

        second, third, peak, prior = asyncio.run(check())

        assert second["daily_pnl"] == Decimal("1000")
        assert second["cumulative_pnl"] == Decimal("1000")
        assert third["daily_pnl"] == Decimal("-10500")
        assert third["cumulative_pnl"] == Decimal("-9500")

        # Drawdown is measured against the peak, which is the 105k session.
        assert peak == Decimal("105000")
        assert third["drawdown_pct"] == pytest.approx(Decimal("-0.1"), abs=1e-9)
        # And "prior" is the session before, not the latest.
        assert prior == Decimal("105000")

    def test_a_breached_drawdown_halts_a_freshly_built_live_process(
        self, dsn, seeded
    ) -> None:
        """
        The end-to-end claim: history in the table, halt in the decision.

        A peak planted well above current equity must make the *next* live
        decision refuse to allocate, even though the process computing it has
        no memory of that peak beyond what it reads back.
        """

        async def check(factory, server):
            conn = await asyncpg.connect(dsn)
            try:
                session = next(
                    s for s in seeded["sessions"] if s >= date(2021, 6, 1)
                )
                await conn.execute("DELETE FROM daily_marks")
                await conn.execute(
                    "DELETE FROM decisions WHERE deployment_id=$1",
                    seeded["deployment_id"],
                )
                # Clear the schedule: this test is about the drawdown limit,
                # and a last_rebalance left by an earlier test would make the
                # session decline before the gate is ever consulted.
                await conn.execute(
                    "UPDATE deployments SET last_rebalance = NULL WHERE id = $1",
                    seeded["deployment_id"],
                )
                # A prior session at 10x the current book: a ~90% drawdown.
                await marks.record_mark(
                    conn,
                    session - timedelta(days=1),
                    Decimal("1000000"),
                    Decimal("1000000"),
                )
                await conn.execute(
                    "UPDATE deployments SET risk_limits=$2::jsonb WHERE id=$1",
                    seeded["deployment_id"],
                    json.dumps({"max_drawdown_pct": 0.10}),
                )
                await run_live_decision(
                    conn,
                    {"session": session.isoformat()},
                    broker_factory=factory,
                )
                return await conn.fetchrow(
                    "SELECT target_weights, risk_events FROM decisions "
                    "WHERE deployment_id=$1 AND session=$2",
                    seeded["deployment_id"], session,
                )
            finally:
                await conn.execute(
                    "UPDATE deployments SET risk_limits='{}'::jsonb WHERE id=$1",
                    seeded["deployment_id"],
                )
                await conn.close()

        row = asyncio.run(_with_venue(check))
        assert row is not None

        events = _as_json(row["risk_events"])
        codes = {e["code"] for e in events}
        assert "drawdown_breach" in codes, (
            "a 10% drawdown limit did not fire against a 90% drawdown — the "
            "live process is not reading its equity history"
        )
        # Halted means flat, not frozen.
        assert _as_json(row["target_weights"]) == {}


class TestDecisionIdempotency:
    """
    A re-run decision job keeps the first answer and returns its real id.

    The insert carries ``ON CONFLICT (deployment_id, session) DO NOTHING``,
    which is the intended idempotency: a retried job must not be able to
    produce a second day's orders, and the persisted decision stays the
    authority even if prices have moved. But the function generated a fresh
    UUID and returned it unconditionally, so on a retry it handed back an id
    that had never been written and could not be resolved — while the caller
    counted the run as having made a decision.
    """

    def test_a_rerun_returns_the_existing_id_and_writes_no_second_row(
        self, dsn, seeded
    ) -> None:
        async def check(factory, server):
            conn = await asyncpg.connect(dsn)
            try:
                session = next(
                    s for s in seeded["sessions"] if s >= date(2021, 6, 1)
                )
                await conn.execute(
                    "DELETE FROM decisions WHERE deployment_id=$1",
                    seeded["deployment_id"],
                )
                # Via the real loader: it decodes the JSONB columns, and a
                # hand-built row would be testing a different shape than the
                # worker actually receives.
                await conn.execute(
                    "UPDATE deployments SET last_rebalance = NULL WHERE id = $1",
                    seeded["deployment_id"],
                )
                (deployment,) = await _enabled_deployments(
                    conn, [str(seeded["deployment_id"])]
                )
                first = await _decide_for(conn, deployment, session, factory)

                # Simulate the recovery case this clause exists for: the
                # decision landed but the schedule update did not, so a retry
                # gets past should_rebalance and reaches the insert. Without
                # resetting it the retry would decline at the schedule instead,
                # which is correct behaviour but tests a different thing.
                await conn.execute(
                    "UPDATE deployments SET last_rebalance = NULL WHERE id = $1",
                    seeded["deployment_id"],
                )
                (deployment,) = await _enabled_deployments(
                    conn, [str(seeded["deployment_id"])]
                )
                second = await _decide_for(conn, deployment, session, factory)
                rows = await conn.fetchval(
                    "SELECT COUNT(*) FROM decisions WHERE deployment_id=$1 "
                    "AND session=$2",
                    seeded["deployment_id"], session,
                )
                stored = await conn.fetchval(
                    "SELECT id FROM decisions WHERE deployment_id=$1 AND session=$2",
                    seeded["deployment_id"], session,
                )
                return first, second, rows, stored
            finally:
                await conn.close()

        first, second, rows, stored = asyncio.run(_with_venue(check))

        assert rows == 1, "the retry wrote a second decision for one session"
        assert first == stored
        # The id handed back on the retry must resolve to the row that exists,
        # not to the throwaway UUID the retry generated.
        assert second == stored


class TestTheRebalanceScheduleSurvivesRestarts:
    """
    A monthly strategy must rebalance monthly *live*, not daily.

    ``Strategy.should_rebalance(session, last_rebalance)`` returns True when
    ``last_rebalance`` is None — that is how a backtest's first session gets to
    trade. A backtest then keeps the value in memory while it walks.

    The live path read it from ``deployment["last_rebalance"]``, and that column
    did not exist. Every job therefore saw None, ``should_rebalance`` returned
    True on every session, and a monthly strategy rebalanced daily: roughly 21x
    the intended turnover and 21x the cost, against a backtest that rebalanced
    twelve times a year.

    Nothing caught it. The parity test walks one process and accumulates the
    schedule in memory, exactly as the backtest does, so both of its paths
    agreed with each other and neither matched production.
    """

    def test_a_second_session_in_the_same_month_does_not_rebalance(
        self, dsn, seeded
    ) -> None:
        async def check(factory, server):
            conn = await asyncpg.connect(dsn)
            try:
                await conn.execute(
                    "DELETE FROM decisions WHERE deployment_id=$1",
                    seeded["deployment_id"],
                )
                await conn.execute(
                    "UPDATE deployments SET last_rebalance = NULL WHERE id = $1",
                    seeded["deployment_id"],
                )
                june = [
                    s for s in seeded["sessions"]
                    if s.year == 2021 and s.month == 6
                ][:5]

                made = []
                for day in june:
                    (deployment,) = await _enabled_deployments(
                        conn, [str(seeded["deployment_id"])]
                    )
                    result = await _decide_for(conn, deployment, day, factory)
                    made.append((day, result is not None))

                stored = await conn.fetchval(
                    "SELECT last_rebalance FROM deployments WHERE id=$1",
                    seeded["deployment_id"],
                )
                rows = await conn.fetchval(
                    "SELECT COUNT(*) FROM decisions WHERE deployment_id=$1",
                    seeded["deployment_id"],
                )
                return june, made, stored, rows
            finally:
                await conn.close()

        june, made, stored, rows = asyncio.run(_with_venue(check))

        # The first session of the month decides; the next four must not.
        assert made[0][1] is True, "the first session of the month did not decide"
        assert [m[1] for m in made[1:]] == [False, False, False, False], (
            f"a monthly strategy decided on {sum(1 for m in made if m[1])} of "
            f"{len(made)} consecutive sessions"
        )
        assert rows == 1, "more than one decision was written for one month"
        # And the schedule is persisted, not merely held in the process that
        # happened to run first.
        assert stored == june[0]

    def test_a_fresh_process_reads_the_schedule_back(self, dsn, seeded) -> None:
        """
        The property that matters: no shared memory between jobs.

        Each ``_decide_for`` call above built its own ``Driver``. This asserts
        the persisted value is what stops the second one, by planting a
        last_rebalance directly and requiring the next session to decline.
        """

        async def check(factory, server):
            conn = await asyncpg.connect(dsn)
            try:
                await conn.execute(
                    "DELETE FROM decisions WHERE deployment_id=$1",
                    seeded["deployment_id"],
                )
                june = [
                    s for s in seeded["sessions"]
                    if s.year == 2021 and s.month == 6
                ]
                await conn.execute(
                    "UPDATE deployments SET last_rebalance = $2 WHERE id = $1",
                    seeded["deployment_id"], june[0],
                )
                (deployment,) = await _enabled_deployments(
                    conn, [str(seeded["deployment_id"])]
                )
                same_month = await _decide_for(conn, deployment, june[3], factory)

                # A new month must be allowed through, or the schedule would
                # halt the strategy permanently rather than pace it.
                may = [
                    s for s in seeded["sessions"]
                    if s.year == 2021 and s.month == 5
                ]
                await conn.execute(
                    "UPDATE deployments SET last_rebalance = $2 WHERE id = $1",
                    seeded["deployment_id"], may[0],
                )
                (deployment,) = await _enabled_deployments(
                    conn, [str(seeded["deployment_id"])]
                )
                next_month = await _decide_for(conn, deployment, june[0], factory)
                return same_month, next_month
            finally:
                await conn.close()

        same_month, next_month = asyncio.run(_with_venue(check))
        assert same_month is None, "rebalanced twice in one month"
        assert next_month is not None, "a new month was refused"


class TestStaleSubmissionsExpire:
    """
    A late submit job must not fill at a price the backtest never modelled.

    The scheduler aims to submit five minutes after the open, and the backtest
    models exactly that. A worker restarted mid-afternoon, or a backed-up
    queue, would otherwise send a morning decision near the close — silently,
    at whatever the market had done in between.

    The parity test cannot see this: the *intents* are identical either way and
    it is the fill price that diverges. So the job refuses.

    Refusing is the conservative side. A missed rebalance costs one period of
    drift; an unexpected fill at an unmodelled price costs whatever the market
    did that day.
    """

    def test_a_decision_submitted_hours_late_is_expired_not_sent(
        self, dsn, seeded
    ) -> None:
        async def check(factory, server):
            conn = await asyncpg.connect(dsn)
            try:
                await flags.release_kill_switch(conn, actor="test")
                decision_session = next(
                    s for s in seeded["sessions"] if s >= date(2021, 6, 1)
                )
                await conn.execute(
                    "DELETE FROM decisions WHERE deployment_id=$1",
                    seeded["deployment_id"],
                )
                await conn.execute(
                    "UPDATE deployments SET last_rebalance = NULL WHERE id = $1",
                    seeded["deployment_id"],
                )
                await run_live_decision(
                    conn,
                    {"session": decision_session.isoformat()},
                    broker_factory=factory,
                )
                # The submit job for the *next* session. 2021 is long past, so
                # its window closed years ago — exactly the "ran far too late"
                # case, without needing to fake a clock.
                nxt = next(s for s in seeded["sessions"] if s > decision_session)
                # Explicitly late: the window plus a working day. Stated as an
                # offset from the window rather than "now" so the test says what
                # it means and does not depend on the calendar year it runs in.
                result = await run_submit_orders(
                    conn, {"session": nxt.isoformat()}, broker_factory=factory,
                    now=_in_window(nxt) + timedelta(hours=6),
                )
                status = await conn.fetchval(
                    "SELECT status FROM decisions WHERE deployment_id=$1 "
                    "AND session=$2",
                    seeded["deployment_id"], decision_session,
                )
                return result, status, len(server.orders)
            finally:
                await conn.close()

        result, status, orders_at_venue = asyncio.run(_with_venue(check))

        assert result["submitted"] == 0
        assert result["skipped"] >= 1
        assert "window passed" in result["reason"]
        assert status == "expired"
        assert orders_at_venue == 0, "a stale batch reached the venue"

    def test_the_guard_leaves_an_in_window_submission_alone(self) -> None:
        """
        The other direction, unit-style: a job running on time must not expire.

        A guard that expired everything would satisfy the assertion above while
        making the system untradeable — and would look identical in production
        to a system that simply never trades.
        """
        from datetime import timedelta as _td

        from src.core.calendar import session_open
        from src.engine.scheduler import SUBMIT_AFTER_OPEN
        from src.worker.live_job import MAX_SUBMISSION_LATENESS, _stale_by

        session = date(2021, 6, 16)
        on_time = session_open(session) + SUBMIT_AFTER_OPEN
        assert _stale_by(session, now=on_time) is None
        assert _stale_by(session, now=on_time + _td(minutes=30)) is None
        # Right at the boundary is still allowed; past it is not.
        assert _stale_by(session, now=on_time + MAX_SUBMISSION_LATENESS) is None
        assert (
            _stale_by(session, now=on_time + MAX_SUBMISSION_LATENESS + _td(minutes=1))
            is not None
        )


class TestWalkForwardIsRequiredToDeploy:
    """
    The plan's mitigation for its own risk 7, finally enforceable.

    A research UI is an overfitting machine: edit parameters, rerun, look at
    the Sharpe, repeat. A single backtest cannot distinguish a real edge from
    parameters fitted to noise — only walking them forward can, because only
    that fixes the parameters *before* seeing the data they are judged on.

    The engine has implemented walk-forward since Phase 4 and the CLI could run
    it. Nothing persisted the result, so the gate had nothing to consult and
    "mandatory before deployment" was advice rather than a control.

    It refuses rather than warns. A warning shown to somebody already committed
    to deploying is not a control.
    """

    @staticmethod
    def _fresh_backtest(conn, params):
        async def make():
            run_id = uuid.uuid4()
            await conn.execute(
                """
                INSERT INTO backtest_runs (id, strategy_name, params, universe,
                    start_session, end_session, initial_cash, data_source,
                    cost_model, status, metrics)
                VALUES ($1,'asset_class_trend_following',$2::jsonb,$3,
                        $4,$5,100000,'yfinance','{}'::jsonb,'succeeded',
                        '{}'::jsonb)
                """,
                run_id, json.dumps(params), UNIVERSE,
                date(2015, 1, 1), date(2019, 12, 31),
            )
            return run_id

        return make()

    def test_deployment_is_refused_without_a_study(self, client, dsn) -> None:
        params = {"sma_period": 111}

        async def seed():
            conn = await asyncpg.connect(dsn)
            try:
                return await self._fresh_backtest(conn, params)
            finally:
                await conn.close()

        run_id = asyncio.run(seed())
        response = client.post(
            "/api/v1/deployments",
            json={
                "strategy": "asset_class_trend_following",
                "params": params,
                "capital_usd": 10000,
                "approved_backtest_run_id": str(run_id),
            },
        )
        assert response.status_code == 422
        assert "walk-forward" in response.json()["detail"]

    def test_a_not_robust_study_is_refused(self, client, dsn) -> None:
        """
        Failing a walk-forward is strong evidence against a configuration, and
        must not be deployable merely because the study exists.
        """
        params = {"sma_period": 112}

        async def seed():
            conn = await asyncpg.connect(dsn)
            try:
                run_id = await self._fresh_backtest(conn, params)
                await conn.execute(
                    """
                    INSERT INTO walkforward_runs (id, backtest_run_id,
                        strategy_name, params, param_grid, start_session,
                        end_session, train_months, test_months, data_source,
                        status, is_robust, degradation, n_folds)
                    VALUES ($1,$2,'asset_class_trend_following',$3::jsonb,
                            '{}'::jsonb,$4,$5,36,12,'yfinance','succeeded',
                            FALSE, 1.85, 4)
                    """,
                    uuid.uuid4(), run_id, json.dumps(params, sort_keys=True),
                    date(2015, 1, 1), date(2019, 12, 31),
                )
                return run_id
            finally:
                await conn.close()

        run_id = asyncio.run(seed())
        response = client.post(
            "/api/v1/deployments",
            json={
                "strategy": "asset_class_trend_following",
                "params": params,
                "capital_usd": 10000,
                "approved_backtest_run_id": str(run_id),
            },
        )
        assert response.status_code == 422
        detail = response.json()["detail"]
        assert "NOT ROBUST" in detail
        assert "+1.850" in detail, "the degradation figure must be quoted"

    def test_a_study_of_different_parameters_does_not_vouch(
        self, client, dsn
    ) -> None:
        """
        Matched on parameters, not just the strategy name.

        A study of sma_period=210 says nothing about sma_period=50. Letting one
        vouch for the other would turn the gate into a formality — exactly the
        failure mode it exists to prevent, since the whole risk is somebody
        tuning parameters until the number looks good.
        """
        async def seed():
            conn = await asyncpg.connect(dsn)
            try:
                run_id = await self._fresh_backtest(conn, {"sma_period": 210})
                await _seed_robust_walkforward(
                    conn, run_id, "asset_class_trend_following",
                    {"sma_period": 210},
                )
                return run_id
            finally:
                await conn.close()

        run_id = asyncio.run(seed())

        # The robust study is for 210. Deploying 50 against it must fail.
        refused = client.post(
            "/api/v1/deployments",
            json={
                "strategy": "asset_class_trend_following",
                "params": {"sma_period": 50},
                "capital_usd": 10000,
                "approved_backtest_run_id": str(run_id),
            },
        )
        assert refused.status_code == 422
        assert "walk-forward" in refused.json()["detail"]

        # And the configuration it *was* run for goes through, so the gate is
        # discriminating rather than simply refusing everything.
        allowed = client.post(
            "/api/v1/deployments",
            json={
                "strategy": "asset_class_trend_following",
                "params": {"sma_period": 210},
                "capital_usd": 10000,
                "approved_backtest_run_id": str(run_id),
            },
        )
        assert allowed.status_code == 201

    def test_a_walkforward_can_be_queued_for_a_backtest(
        self, client, seeded
    ) -> None:
        response = client.post(
            f"/api/v1/backtests/{seeded['run_id']}/walkforward",
            json={"param_grid": {"sma_period": [105, 150, 210]}},
        )
        assert response.status_code == 202
        assert response.json()["status"] == "queued"

        listed = client.get(
            f"/api/v1/backtests/{seeded['run_id']}/walkforward"
        ).json()
        assert any(w["status"] == "queued" for w in listed)
        # Queued means no verdict yet. Null and False must be distinguishable:
        # "not yet judged" is not "judged and failed".
        queued = next(w for w in listed if w["status"] == "queued")
        assert queued["is_robust"] is None
        assert queued["degradation"] is None

    def test_a_walkforward_on_synthetic_data_is_refused(
        self, client, dsn
    ) -> None:
        """
        A generator has no regime to fail to generalise across, so a study of
        it would return a robust verdict that means nothing.
        """

        async def seed():
            conn = await asyncpg.connect(dsn)
            try:
                run_id = uuid.uuid4()
                await conn.execute(
                    """
                    INSERT INTO backtest_runs (id, strategy_name, params,
                        universe, start_session, end_session, initial_cash,
                        data_source, cost_model, status)
                    VALUES ($1,'asset_class_trend_following','{}'::jsonb,$2,
                            $3,$4,100000,'synthetic','{}'::jsonb,'succeeded')
                    """,
                    run_id, UNIVERSE, date(2015, 1, 1), date(2019, 12, 31),
                )
                return run_id
            finally:
                await conn.close()

        run_id = asyncio.run(seed())
        response = client.post(
            f"/api/v1/backtests/{run_id}/walkforward", json={"param_grid": {}}
        )
        assert response.status_code == 422
        assert "synthetic" in response.json()["detail"]
