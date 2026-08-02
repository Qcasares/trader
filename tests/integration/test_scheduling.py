"""
test_scheduling.py
------------------
The wire between the session planner and the job queue, and the three handlers
that had none.

``src/engine/scheduler.py`` computed a plan for every trading session and had
its own passing tests. Nothing ever called it: ``grep -rn plan_session src/``
matched only its own definition. The queue and the planner existed on either
side of a gap.

Three of the five kinds it emits — ``ingest_bars``, ``eod_marks`` and
``reconcile`` — had no handler in ``src/worker/main.py``, so had the wire
existed they would have failed with "no handler for job kind". ``ingest_bars``
is the one that mattered: the live decision reads ``daily_bars``, nothing
populated it, and the live loop could therefore never have run at all.

Runs against a real database. Skipped unless ``TEST_DATABASE_URL`` is set.
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from datetime import date
from decimal import Decimal

import pytest

pytest.importorskip("asyncpg")

import asyncpg  # noqa: E402

from src.core.calendar import sessions as nyse_sessions  # noqa: E402
from src.core.types import AccountState, Position  # noqa: E402
from src.data import SyntheticSource  # noqa: E402
from src.db.repos import jobs as job_repo  # noqa: E402
from src.db.repos import marks  # noqa: E402
from src.worker.main import HANDLERS, SCHEDULED_KINDS  # noqa: E402
from src.worker.maintenance_jobs import (  # noqa: E402
    run_eod_marks,
    run_ingest_bars,
    run_reconcile,
)
from src.worker.scheduling import plan_and_enqueue  # noqa: E402

TEST_DSN = os.environ.get("TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(not TEST_DSN, reason="TEST_DATABASE_URL not set")

UNIVERSE = ["SPY", "EFA", "IEF", "VNQ", "GSG"]
#: An ordinary NYSE session, deliberately not a Monday or a holiday-adjacent day.
SESSION = date(2021, 6, 16)


def _sched_dsn() -> str:
    base, _, tail = TEST_DSN.partition("?")
    return f"{base}_sched?{tail}" if tail else f"{base}_sched"


@pytest.fixture(scope="module")
def dsn():
    from src.db.migrate import migrate

    async def setup() -> str:
        admin = await asyncpg.connect(TEST_DSN)
        name = _sched_dsn().partition("?")[0].rsplit("/", 1)[-1]
        await admin.execute(f'DROP DATABASE IF EXISTS "{name}"')
        await admin.execute(f'CREATE DATABASE "{name}"')
        await admin.close()
        await migrate(_sched_dsn())
        return _sched_dsn()

    return asyncio.run(setup())


@pytest.fixture
def deployment(dsn):
    """One enabled paper deployment, with a backtest behind it."""

    async def seed():
        conn = await asyncpg.connect(dsn)
        try:
            await conn.execute("DELETE FROM deployments")
            run_id, deployment_id = uuid.uuid4(), uuid.uuid4()
            await conn.execute(
                """
                INSERT INTO backtest_runs (id, strategy_name, params, universe,
                    start_session, end_session, initial_cash, data_source,
                    cost_model, status)
                VALUES ($1,'asset_class_trend_following','{}'::jsonb,$2,
                        $3,$4,100000,'yfinance','{}'::jsonb,'succeeded')
                """,
                run_id, UNIVERSE, date(2015, 1, 1), date(2019, 12, 31),
            )
            await conn.execute(
                """
                INSERT INTO deployments (id, strategy_name, params, mode,
                    capital_usd, risk_limits, approved_backtest_run_id, status)
                VALUES ($1,'asset_class_trend_following','{}'::jsonb,'paper',
                        100000,'{}'::jsonb,$2,'enabled')
                """,
                deployment_id, run_id,
            )
            return deployment_id
        finally:
            await conn.close()

    return asyncio.run(seed())


class FakeBroker:
    """A venue with a known book, so reconciliation has something to disagree with."""

    def __init__(self, cash=Decimal("50000"), positions=None) -> None:
        self._cash = cash
        self._positions = positions or {}

    async def get_account(self) -> AccountState:
        invested = sum(
            p.qty * p.avg_entry_price for p in self._positions.values()
        )
        return AccountState(
            cash=self._cash,
            equity=self._cash + invested,
            buying_power=self._cash,
        )

    async def get_positions(self) -> dict[str, Position]:
        return dict(self._positions)


# ---------------------------------------------------------------------------
# Every planned kind has a handler
# ---------------------------------------------------------------------------


def test_every_scheduled_kind_has_a_handler() -> None:
    """
    The gap that let three job kinds be planned and never run.

    Asserted as a set comparison rather than by listing names, so adding a kind
    to the scheduler without adding a handler fails here rather than at 09:25
    on a trading morning.
    """
    missing = SCHEDULED_KINDS - set(HANDLERS)
    assert not missing, f"scheduler emits kinds no worker handles: {sorted(missing)}"


def test_scheduled_kinds_match_what_the_planner_emits() -> None:
    """And the constant must not drift from the planner it describes."""
    from src.engine.scheduler import plan_session

    emitted = {job.kind.value for job in plan_session(SESSION)}
    assert emitted == set(SCHEDULED_KINDS)


# ---------------------------------------------------------------------------
# Planning
# ---------------------------------------------------------------------------


class TestPlanAndEnqueue:
    def test_a_session_enqueues_its_whole_plan(self, dsn) -> None:
        async def check():
            conn = await asyncpg.connect(dsn)
            try:
                await conn.execute("DELETE FROM jobs")
                result = await plan_and_enqueue(conn, SESSION)
                rows = await conn.fetch(
                    "SELECT kind, scheduled_for, dedupe_key FROM jobs "
                    "ORDER BY scheduled_for"
                )
                return result, rows
            finally:
                await conn.close()

        result, rows = asyncio.run(check())
        assert result["enqueued"] == 5
        assert {r["kind"] for r in rows} == set(SCHEDULED_KINDS)
        # Ordering is the point of a calendar-derived plan: reconcile before
        # the open, decide after the close.
        assert [r["kind"] for r in rows][0] == "reconcile"
        assert [r["kind"] for r in rows][-1] == "eod_marks"
        for row in rows:
            assert row["dedupe_key"] == f"{row['kind']}:{SESSION.isoformat()}"

    def test_replanning_is_free(self, dsn) -> None:
        """
        Safe to run on every startup and every sweep.

        Without this the plan needs a durable scheduler, and a restart produces
        either a misfire storm or a silently missed session.
        """

        async def check():
            conn = await asyncpg.connect(dsn)
            try:
                await conn.execute("DELETE FROM jobs")
                first = await plan_and_enqueue(conn, SESSION)
                second = await plan_and_enqueue(conn, SESSION)
                third = await plan_and_enqueue(conn, SESSION)
                total = await conn.fetchval("SELECT COUNT(*) FROM jobs")
                return first, second, third, total
            finally:
                await conn.close()

        first, second, third, total = asyncio.run(check())
        assert first["enqueued"] == 5 and first["skipped"] == 0
        assert second["enqueued"] == 0 and second["skipped"] == 5
        assert third["enqueued"] == 0
        assert total == 5

    def test_a_holiday_schedules_nothing(self, dsn) -> None:
        """Christmas Day is not a session; it must not enqueue work that then
        has to discover it is a holiday."""

        async def check():
            conn = await asyncpg.connect(dsn)
            try:
                await conn.execute("DELETE FROM jobs")
                result = await plan_and_enqueue(conn, date(2021, 12, 25))
                return result, await conn.fetchval("SELECT COUNT(*) FROM jobs")
            finally:
                await conn.close()

        result, count = asyncio.run(check())
        assert result["enqueued"] == 0
        assert count == 0

    def test_ad_hoc_jobs_may_still_repeat(self, dsn) -> None:
        """
        The unique index is partial. A backtest queued twice from the UI is two
        legitimate jobs, and must not be deduplicated into one.
        """

        async def check():
            conn = await asyncpg.connect(dsn)
            try:
                await conn.execute("DELETE FROM jobs")
                a = await job_repo.enqueue(conn, "backtest", {"run_id": "1"})
                b = await job_repo.enqueue(conn, "backtest", {"run_id": "1"})
                return a, b, await conn.fetchval("SELECT COUNT(*) FROM jobs")
            finally:
                await conn.close()

        a, b, count = asyncio.run(check())
        assert a is not None and b is not None and a != b
        assert count == 2


# ---------------------------------------------------------------------------
# The handlers
# ---------------------------------------------------------------------------


class TestIngestBars:
    def test_bars_land_in_the_table_the_live_path_reads(
        self, dsn, deployment
    ) -> None:
        async def check():
            conn = await asyncpg.connect(dsn)
            try:
                await conn.execute("DELETE FROM daily_bars")
                result = await run_ingest_bars(
                    conn,
                    {"session": SESSION.isoformat()},
                    source_factory=SyntheticSource,
                )
                count = await conn.fetchval("SELECT COUNT(*) FROM daily_bars")
                symbols = await conn.fetch(
                    "SELECT DISTINCT symbol FROM daily_bars ORDER BY symbol"
                )
                return result, count, [r["symbol"] for r in symbols]
            finally:
                await conn.close()

        result, count, symbols = asyncio.run(check())
        assert result["bars"] > 0
        assert count == result["bars"]
        # The universe comes from the deployment, not from a hard-coded list.
        assert symbols == sorted(UNIVERSE)

    def test_reingesting_updates_rather_than_duplicates(
        self, dsn, deployment
    ) -> None:
        async def check():
            conn = await asyncpg.connect(dsn)
            try:
                await conn.execute("DELETE FROM daily_bars")
                first = await run_ingest_bars(
                    conn, {"session": SESSION.isoformat()},
                    source_factory=SyntheticSource,
                )
                after_first = await conn.fetchval(
                    "SELECT COUNT(*) FROM daily_bars"
                )
                await run_ingest_bars(
                    conn, {"session": SESSION.isoformat()},
                    source_factory=SyntheticSource,
                )
                after_second = await conn.fetchval(
                    "SELECT COUNT(*) FROM daily_bars"
                )
                return first, after_first, after_second
            finally:
                await conn.close()

        _first, after_first, after_second = asyncio.run(check())
        assert after_first == after_second

    def test_no_deployments_means_nothing_to_ingest(self, dsn) -> None:
        async def check():
            conn = await asyncpg.connect(dsn)
            try:
                await conn.execute("DELETE FROM deployments")
                return await run_ingest_bars(
                    conn, {"session": SESSION.isoformat()},
                    source_factory=SyntheticSource,
                )
            finally:
                await conn.close()

        result = asyncio.run(check())
        assert result["bars"] == 0


class TestEodMarks:
    def test_a_mark_is_written_every_session(self, dsn, deployment) -> None:
        """
        Not only on sessions that decide.

        The risk gate measures drawdown against MAX(equity) from this table, so
        a peak reached on a quiet day must not be forgotten.
        """

        async def check():
            conn = await asyncpg.connect(dsn)
            try:
                await conn.execute("DELETE FROM daily_marks")
                await run_eod_marks(
                    conn,
                    {"session": SESSION.isoformat()},
                    broker_factory=lambda: FakeBroker(cash=Decimal("120000")),
                )
                peak = await marks.peak_equity(conn)
                row = await conn.fetchrow(
                    "SELECT session, equity FROM daily_marks"
                )
                return peak, row
            finally:
                await conn.close()

        peak, row = asyncio.run(check())
        assert row is not None
        assert row["session"] == SESSION
        assert peak == Decimal("120000")


class TestReconcile:
    def test_a_clean_book_reports_no_mismatch(self, dsn, deployment) -> None:
        async def check():
            conn = await asyncpg.connect(dsn)
            try:
                await conn.execute("DELETE FROM daily_marks")
                return await run_reconcile(
                    conn,
                    {"session": SESSION.isoformat()},
                    broker_factory=lambda: FakeBroker(),
                )
            finally:
                await conn.close()

        result = asyncio.run(check())
        assert result["checked"] == 1
        assert result["mismatches"] == []

    def test_a_position_the_venue_holds_and_we_do_not_is_reported(
        self, dsn, deployment
    ) -> None:
        """
        The failure this job exists for.

        Acting on a ledger that disagrees with the broker is how a small
        bookkeeping error becomes a real position, so it is surfaced before the
        open and written to the audit log — and never silently corrected.
        """

        async def check():
            conn = await asyncpg.connect(dsn)
            try:
                await conn.execute("DELETE FROM daily_marks")
                await conn.execute("DELETE FROM audit_log")
                result = await run_reconcile(
                    conn,
                    {"session": SESSION.isoformat()},
                    broker_factory=lambda: FakeBroker(
                        positions={
                            "SPY": Position(
                                symbol="SPY",
                                qty=Decimal("10"),
                                avg_entry_price=Decimal("400"),
                            )
                        }
                    ),
                )
                logged = await conn.fetch(
                    "SELECT action, detail FROM audit_log "
                    "WHERE action = 'reconciliation_mismatch'"
                )
                return result, logged
            finally:
                await conn.close()

        result, logged = asyncio.run(check())
        assert len(result["mismatches"]) == 1
        mismatch = result["mismatches"][0]
        assert mismatch["kind"] == "position"
        assert mismatch["symbol"] == "SPY"
        assert mismatch["ours"] == "0"
        assert mismatch["venue"] == "10"
        assert logged, "a mismatch must reach the audit log, not only the return value"
        detail = logged[0]["detail"]
        assert "SPY" in (detail if isinstance(detail, str) else json.dumps(detail))

    def test_cash_drift_beyond_tolerance_is_reported(
        self, dsn, deployment
    ) -> None:
        async def check():
            conn = await asyncpg.connect(dsn)
            try:
                await conn.execute("DELETE FROM daily_marks")
                previous = nyse_sessions(date(2021, 6, 1), SESSION)[-2]
                await marks.record_mark(
                    conn, previous, Decimal("99000"), Decimal("99000")
                )
                return await run_reconcile(
                    conn,
                    {"session": SESSION.isoformat()},
                    broker_factory=lambda: FakeBroker(cash=Decimal("50000")),
                )
            finally:
                await conn.close()

        result = asyncio.run(check())
        cash = [m for m in result["mismatches"] if m["kind"] == "cash"]
        assert cash, "a $49,000 cash difference went unreported"
        assert cash[0]["drift"] == "49000"
