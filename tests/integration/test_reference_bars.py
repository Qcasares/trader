"""
test_reference_bars.py
----------------------
The live ingest's one adjustment basis and the worker's reference bars, on
real Postgres.

Yahoo back-adjusts ``Adj Close`` at every distribution, so each fetch returns
the whole history on the basis of the day it was made. The live ingest used to
refetch ten days, which left every older row on the basis of the last day it
was fetched and a step at the ten-day boundary for every distribution since.
It now refetches each owned symbol's whole stored span, and every stored row
the fetch returns takes that fetch's adjusted close, while raw prices are
refreshed whole only inside ``INGEST_LOOKBACK_DAYS``, as they always were; the
reference job does the same for the sleeves no enabled deployment trades, and
never changes a row of a symbol the live ingest owns, nor writes one inside
its lookback, where the close the live decision sizes from lives. Both write
in one transaction, and the reference job runs only in its session's window
and fails while a sleeve is without its session's close; here through the
worker's own claim where the retry is the point.

A fake vendor stands in for Yahoo with Yahoo's shape: raw prices fixed per
session, adjusted prices multiplied down before every distribution the vendor
has seen, and a split dividing every earlier raw price. Two vendors, one before
a distribution and one after, are two days' fetches.

The rules themselves, one at a time and without a database, are
``tests/unit/test_reference_bars.py``. Skipped unless ``TEST_DATABASE_URL`` is
set.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import os
import uuid
from collections.abc import Iterable
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

pytest.importorskip("asyncpg")

import asyncpg  # noqa: E402

from src.core.calendar import bounds, session_close  # noqa: E402
from src.core.calendar import sessions as nyse_sessions  # noqa: E402
from src.core.panel import FIELDS, PricePanel  # noqa: E402
from src.core.types import Bar  # noqa: E402
from src.data import DataSourceError, bars_to_rows  # noqa: E402
from src.data.reference import (  # noqa: E402
    REFERENCE_MIN_ROWS,
    REFERENCE_PRIORITY,
    REFERENCE_SOURCE,
    REFERENCE_SYMBOLS,
    REFERENCE_WINDOW_DAYS,
)
from src.db.repos import jobs as job_repo  # noqa: E402
from src.engine.scheduler import INGEST_AFTER_CLOSE  # noqa: E402
from src.worker import maintenance_jobs  # noqa: E402
from src.worker.live_job import _load_panel  # noqa: E402
from src.worker.main import Worker  # noqa: E402
from src.worker.maintenance_jobs import (  # noqa: E402
    INGEST_LOOKBACK_DAYS,
    lookback_start,
    run_ingest_bars,
    run_ingest_reference_bars,
)
from src.worker.shadow_job import _price_map  # noqa: E402

TEST_DSN = os.environ.get("TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(not TEST_DSN, reason="TEST_DATABASE_URL not set")

#: Two consecutive NYSE sessions: one day's ingest, and the next.
FIRST = date(2026, 9, 24)
SECOND = date(2026, 9, 25)

#: A symbol no reference sleeve uses, so a deployment of it leaves every sleeve
#: to the reference job.
OTHER = "EFA"


def _refbars_dsn() -> str:
    base, _, tail = TEST_DSN.partition("?")
    return f"{base}_refbars?{tail}" if tail else f"{base}_refbars"


@pytest.fixture(scope="module")
def dsn() -> str:
    from src.db.migrate import migrate

    async def setup() -> str:
        admin = await asyncpg.connect(TEST_DSN)
        name = _refbars_dsn().partition("?")[0].rsplit("/", 1)[-1]
        await admin.execute(f'DROP DATABASE IF EXISTS "{name}"')
        await admin.execute(f'CREATE DATABASE "{name}"')
        await admin.close()
        await migrate(_refbars_dsn())
        return _refbars_dsn()

    return asyncio.run(setup())


class _Vendor:
    """
    Yahoo's shape, in miniature.

    Raw prices are fixed per session, except that a split divides every raw
    price before it, since Yahoo's ``Close`` is split-adjusted. Adjusted prices
    are the raw ones multiplied down by every distribution the vendor has seen
    whose ex-date is later, so each fetch returns the whole history on the
    basis of the day it is made.
    """

    name = REFERENCE_SOURCE

    def __init__(
        self,
        distributions: Iterable[tuple[str, date, float]] = (),
        splits: Iterable[tuple[str, date, float]] = (),
        omit: Iterable[tuple[str, date]] = (),
        fail: Exception | None = None,
        refuse_before: date | None = None,
    ) -> None:
        self.distributions = list(distributions)
        self.splits = list(splits)
        self.omit = set(omit)
        self.fail = fail
        #: A window starting before this is refused, as a long download that
        #: times out would be, while a short one is answered.
        self.refuse_before = refuse_before
        self.calls: list[tuple[tuple[str, ...], date, date]] = []

    def fetch(self, symbols: list[str], start: date, end: date) -> list[Bar]:
        self.calls.append((tuple(symbols), start, end))
        if self.fail is not None:
            raise self.fail
        if self.refuse_before is not None and start < self.refuse_before:
            raise DataSourceError(f"timed out fetching from {start}")
        return [
            self.bar(symbol, day)
            for day in nyse_sessions(start, end)
            for symbol in symbols
            if (symbol, day) not in self.omit
        ]

    def bar(self, symbol: str, day: date) -> Bar:
        raw = 60.0 + (day.toordinal() * 7 + len(symbol) * 13 + ord(symbol[0])) % 50
        for split_symbol, on, ratio in self.splits:
            if split_symbol == symbol and day < on:
                raw /= ratio
        adjusted = raw
        for paid_by, ex_date, factor in self.distributions:
            if paid_by == symbol and day < ex_date:
                adjusted *= factor
        return Bar(
            symbol=symbol,
            session=day,
            open=round(raw * 0.995, 4),
            high=round(raw * 1.01, 4),
            low=round(raw * 0.99, 4),
            close=round(raw, 4),
            volume=1_000_000.0,
            adj_close=round(adjusted, 6),
            source=self.name,
        )


def _window(session: date) -> list[date]:
    return nyse_sessions(session - timedelta(days=REFERENCE_WINDOW_DAYS), session)


async def _reset(conn: asyncpg.Connection, *owned: str) -> uuid.UUID | None:
    """
    No bars, no jobs, and one enabled deployment trading ``owned``, if any;
    its id.
    """
    await conn.execute("DELETE FROM daily_bars")
    await conn.execute("DELETE FROM jobs")
    await conn.execute("DELETE FROM deployments")
    if not owned:
        return None
    return await _deploy(conn, *owned)


async def _deploy(conn: asyncpg.Connection, *symbols: str) -> uuid.UUID:
    """One enabled operator deployment trading ``symbols``; its id."""
    deployment_id = uuid.uuid4()
    await conn.execute(
        """
        INSERT INTO deployments (id, strategy_name, params, mode,
                                 capital_usd, status)
        VALUES ($1, 'buy_and_hold', $2::jsonb, 'paper', 100000, 'enabled')
        """,
        deployment_id,
        json.dumps({"symbols": list(symbols)}),
    )
    return deployment_id


async def _set_status(
    conn: asyncpg.Connection, deployment_id: Any, status: str
) -> None:
    """What the API's enable and disable routes write."""
    column = "enabled_at" if status == "enabled" else "disabled_at"
    await conn.execute(
        f"UPDATE deployments SET status = $2, {column} = NOW() WHERE id = $1",
        deployment_id,
        status,
    )


def _clock_at(monkeypatch: pytest.MonkeyPatch, instant: datetime) -> None:
    """The database's clock, as the reference job reads it, held at ``instant``."""

    async def database_now(conn: asyncpg.Connection) -> datetime:
        return instant

    monkeypatch.setattr(maintenance_jobs, "_database_now", database_now)


async def _session_rows(conn: asyncpg.Connection, day: date) -> list[str]:
    """The symbols with a stored row for ``day``."""
    rows = await conn.fetch(
        "SELECT symbol FROM daily_bars WHERE session = $1 ORDER BY symbol", day
    )
    return [row["symbol"] for row in rows]


async def _rows(conn: asyncpg.Connection, symbol: str) -> dict[date, dict[str, Any]]:
    rows = await conn.fetch(
        """
        SELECT session, open, high, low, close, volume, adj_close, ingested_at,
               xmin::text AS version
        FROM daily_bars WHERE symbol = $1 AND source = $2 ORDER BY session
        """,
        symbol,
        REFERENCE_SOURCE,
    )
    return {row["session"]: dict(row) for row in rows}


PRICE_FIELDS = ("open", "high", "low", "close", "volume", "adj_close")
RAW_FIELDS = ("open", "high", "low", "close", "volume")


def _as_fetched(bar: Bar) -> dict[str, float]:
    return {field: getattr(bar, field) for field in PRICE_FIELDS}


def _prices(row: dict[str, Any]) -> dict[str, float]:
    """
    A stored row's prices as the floats they were written from.

    asyncpg writes a float to ``NUMERIC`` as its exact binary expansion, so
    62.37 is stored as 62.3699999999999974…, and reads back as 62.37 exactly.
    """
    return {field: float(row[field]) for field in PRICE_FIELDS}


async def _sentinels(
    conn: asyncpg.Connection, symbol: str, days: Iterable[date]
) -> None:
    """Rows no vendor would print, as a live ingest wrote them."""
    await conn.executemany(
        """
        INSERT INTO daily_bars (symbol, session, source, open, high, low, close,
                                volume, adj_close)
        VALUES ($1, $2, $3, 9999.25, 9999.5, 9999, 9999.125, 7, 8888.0625)
        """,
        [(symbol, day, REFERENCE_SOURCE) for day in days],
    )


def _settled(session: date) -> datetime:
    """When ``session``'s bars settle: its close plus the live ingest's delay."""
    return session_close(session) + INGEST_AFTER_CLOSE


def _ingest(job: Any, conn: asyncpg.Connection, vendor: _Vendor, **payload: Any):
    """
    Run one ingest. The reference job runs inside its session's window: a
    minute after its bars settle, whatever the day the suite runs on.
    """
    if job is run_ingest_reference_bars:
        now = _settled(payload["session"]) + timedelta(minutes=1)
        return job(conn, payload, source_factory=lambda: vendor, now=now)
    return job(conn, payload, source_factory=lambda: vendor)


async def _enqueue_and_drain(
    dsn: str, kind: str, session: date, **enqueue: Any
) -> dict[str, Any]:
    """Queue one job, let the worker claim and run it once, and read it back."""
    conn = await asyncpg.connect(dsn)
    try:
        job_id = await job_repo.enqueue(
            conn, kind, {"session": session.isoformat()}, **enqueue
        )
    finally:
        await conn.close()
    worker = Worker(dsn, f"{kind}-test")
    await worker.start()
    try:
        await worker._drain()
    finally:
        await worker.stop()
    conn = await asyncpg.connect(dsn)
    try:
        row = await conn.fetchrow(
            "SELECT id, status, attempts, error, result FROM jobs WHERE id = $1",
            job_id,
        )
        return dict(row)
    finally:
        await conn.close()


async def _release(dsn: str, job_id: Any) -> None:
    """Make a job the worker put back with a backoff claimable now."""
    conn = await asyncpg.connect(dsn)
    try:
        await conn.execute(
            "UPDATE jobs SET scheduled_for = NOW() WHERE id = $1", job_id
        )
    finally:
        await conn.close()


# ---------------------------------------------------------------------------
# The live ingest
# ---------------------------------------------------------------------------


class TestTheLiveIngestKeepsOneBasis:
    def test_a_distribution_between_two_ingests_rebases_every_stored_row(
        self, dsn
    ) -> None:
        """
        The defect itself. With the ten-day refetch, every SPY row older than
        ten days kept the first day's basis while the rest took the second's.
        """
        before = _Vendor()
        after = _Vendor(distributions=[("SPY", SECOND, 0.99)])

        async def check():
            conn = await asyncpg.connect(dsn)
            try:
                await _reset(conn, "SPY", "IEF")
                await _ingest(run_ingest_bars, conn, before, session=FIRST)
                result = await _ingest(run_ingest_bars, conn, after, session=SECOND)
                return result, await _rows(conn, "SPY"), await _rows(conn, "IEF")
            finally:
                await conn.close()

        result, spy, ief = asyncio.run(check())
        assert result["rows_not_refreshed"] == 0
        boundary = SECOND - timedelta(days=INGEST_LOOKBACK_DAYS)
        assert len([day for day in spy if day < boundary]) > 1_000, (
            "too little history behind the old ten-day boundary to show it"
        )
        for day, row in spy.items():
            assert _prices(row) == _as_fetched(after.bar("SPY", day)), day
        for day, row in ief.items():
            assert _prices(row) == _as_fetched(after.bar("IEF", day)), day

    def test_a_split_reprices_raw_prices_only_where_the_ingest_always_did(
        self, dsn
    ) -> None:
        """
        Yahoo folds a split into ``Close``, so the second fetch halves every
        earlier raw price. The adjusted series takes that, everywhere, which is
        one basis. Raw prices are refreshed whole only inside the lookback, as
        the ingest always refreshed them; an older row keeps the raw prices it
        was written with. And the session's own close, which is all that money
        reads, is the vendor's.
        """
        before = _Vendor()
        after = _Vendor(splits=[("SPY", SECOND, 2.0)])

        async def check():
            conn = await asyncpg.connect(dsn)
            try:
                await _reset(conn, "SPY")
                await _ingest(run_ingest_bars, conn, before, session=FIRST)
                await _ingest(run_ingest_bars, conn, after, session=SECOND)
                panel = await _load_panel(conn, ["SPY"], SECOND)
                return await _rows(conn, "SPY"), panel
            finally:
                await conn.close()

        spy, panel = asyncio.run(check())
        boundary = SECOND - timedelta(days=INGEST_LOOKBACK_DAYS)
        older = [day for day in spy if day < boundary]
        recent = [day for day in spy if boundary <= day < SECOND]
        assert older and recent
        for day in older:
            stored = _prices(spy[day])
            first, second = before.bar("SPY", day), after.bar("SPY", day)
            assert stored["adj_close"] == second.adj_close, day
            assert {f: stored[f] for f in RAW_FIELDS} == {
                f: getattr(first, f) for f in RAW_FIELDS
            }, day
        for day in recent:
            assert _prices(spy[day]) == _as_fetched(after.bar("SPY", day)), day
        assert panel.value_on("SPY", SECOND, "close") == after.bar("SPY", SECOND).close
        assert after.bar("SPY", SECOND).close == before.bar("SPY", SECOND).close

    def test_the_shadow_replay_prices_an_old_session_as_it_did(self, dsn) -> None:
        """
        The one reader of old raw prices keeps reading what it read: a split
        after the fact leaves every price the replay fills and marks at, older
        than the lookback, as it was.
        """
        before = _Vendor()
        after = _Vendor(splits=[("SPY", SECOND, 2.0)])
        window = (FIRST - timedelta(days=200), FIRST - timedelta(days=20))

        async def check():
            conn = await asyncpg.connect(dsn)
            try:
                await _reset(conn, "SPY")
                await _ingest(run_ingest_bars, conn, before, session=FIRST)
                first = await _price_map(conn, ["SPY"], *window)
                await _ingest(run_ingest_bars, conn, after, session=SECOND)
                return first, await _price_map(conn, ["SPY"], *window)
            finally:
                await conn.close()

        first, second = asyncio.run(check())
        assert len(first) > 100
        assert second == first

    def test_the_live_panel_is_what_a_backtest_of_the_same_days_reads(
        self, dsn
    ) -> None:
        """
        Same shape as before — every field, the universe, cut at the session —
        and, after a distribution, the same numbers a fresh fetch of the same
        span gives, which is what a backtest reads.
        """
        before = _Vendor()
        after = _Vendor(distributions=[("SPY", SECOND, 0.985), ("IEF", FIRST, 0.99)])

        async def check():
            conn = await asyncpg.connect(dsn)
            try:
                await _reset(conn, "SPY", "IEF")
                await _ingest(run_ingest_bars, conn, before, session=FIRST)
                result = await _ingest(run_ingest_bars, conn, after, session=SECOND)
                panel = await _load_panel(conn, ["IEF", "SPY"], SECOND)
                return result, panel
            finally:
                await conn.close()

        result, live = asyncio.run(check())
        start = date.fromisoformat(result["refetched_from"])
        fresh = PricePanel.from_bars(
            bars_to_rows(after.fetch(["IEF", "SPY"], start, SECOND)), as_of=SECOND
        )
        assert live.fields == FIELDS
        assert live.symbols == ("IEF", "SPY")
        assert live.as_of == SECOND
        for field in FIELDS:
            assert live.frame(field).equals(fresh.frame(field)), field

    def test_a_stored_session_the_fetch_omits_is_counted_and_kept(self, dsn) -> None:
        gap = _window(SECOND)[100]
        vendor = _Vendor(omit=[("SPY", gap)])

        async def check():
            conn = await asyncpg.connect(dsn)
            try:
                await _reset(conn, "SPY")
                await _sentinels(conn, "SPY", [gap])
                result = await _ingest(run_ingest_bars, conn, vendor, session=SECOND)
                return result, await _rows(conn, "SPY")
            finally:
                await conn.close()

        result, spy = asyncio.run(check())
        assert result["rows_not_refreshed"] == 1
        assert spy[gap]["close"] == Decimal("9999.125"), "the row was not kept"
        assert len(spy) == len(_window(SECOND)), "the rest of the span was not written"

    def test_a_span_that_will_not_download_lands_the_old_window_then_fails(
        self, dsn
    ) -> None:
        """
        The session's bar lands wherever a ten-day fetch would have landed it,
        and older rows keep their basis; the job then fails, saying so, since
        a stored series with a step in it is not one basis however quietly it
        succeeds.
        """
        fallback = lookback_start(SECOND)
        older = [day for day in _window(SECOND) if day < fallback][-40:]
        vendor = _Vendor(refuse_before=fallback)

        async def check():
            conn = await asyncpg.connect(dsn)
            try:
                await _reset(conn, "SPY")
                await _sentinels(conn, "SPY", older)
                with pytest.raises(DataSourceError) as raised:
                    await _ingest(run_ingest_bars, conn, vendor, session=SECOND)
                return str(raised.value), await _rows(conn, "SPY")
            finally:
                await conn.close()

        error, spy = asyncio.run(check())
        assert f"{len(older)} stored row(s) it did not return keep" in error
        assert {spy[day]["close"] for day in older} == {Decimal("9999.125")}
        assert _prices(spy[SECOND]) == _as_fetched(vendor.bar("SPY", SECOND))

    def test_a_fallback_day_is_retried_until_the_span_lands(
        self, dsn, monkeypatch
    ) -> None:
        """
        Through the worker's own claim: the first attempt lands the ten-day
        window and fails, so the job goes back on the queue with the reason as
        its error, and the retry that fetches the whole span re-bases every
        stored row onto one basis and succeeds.
        """
        fallback = lookback_start(SECOND)
        before = _Vendor()
        after = _Vendor(distributions=[("SPY", SECOND, 0.99)])
        refusing = _Vendor(
            distributions=[("SPY", SECOND, 0.99)], refuse_before=fallback
        )
        vendors = iter([refusing, after])
        monkeypatch.setattr(maintenance_jobs, "_default_source", lambda: next(vendors))

        async def check():
            conn = await asyncpg.connect(dsn)
            try:
                await _reset(conn, "SPY")
                await _ingest(run_ingest_bars, conn, before, session=FIRST)
            finally:
                await conn.close()
            first = await _enqueue_and_drain(dsn, "ingest_bars", SECOND)
            conn = await asyncpg.connect(dsn)
            try:
                landed = await _rows(conn, "SPY")
            finally:
                await conn.close()
            await _release(dsn, first["id"])
            worker = Worker(dsn, "fallback-retry-test")
            await worker.start()
            try:
                await worker._drain()
            finally:
                await worker.stop()
            conn = await asyncpg.connect(dsn)
            try:
                again = await conn.fetchrow(
                    "SELECT status, attempts FROM jobs WHERE id = $1", first["id"]
                )
                return first, landed, dict(again), await _rows(conn, "SPY")
            finally:
                await conn.close()

        first, landed, again, spy = asyncio.run(check())
        assert first["status"] == "queued" and first["attempts"] == 1
        assert "keep an older adjustment basis" in first["error"]
        assert _prices(landed[SECOND]) == _as_fetched(after.bar("SPY", SECOND))
        stitched = [day for day in landed if day < fallback]
        assert stitched and all(
            float(landed[day]["adj_close"]) == before.bar("SPY", day).adj_close
            for day in stitched
        ), "the fallback re-based rows it never fetched"
        assert again == {"status": "succeeded", "attempts": 2}
        for day, row in spy.items():
            assert _prices(row) == _as_fetched(after.bar("SPY", day)), day

    def test_a_late_job_leaves_no_row_on_another_fetchs_basis(self, dsn) -> None:
        """
        A job for an older session that runs after a newer one: the rows the
        newer job wrote are refetched too, so a distribution between the two
        leaves no step at the older session.
        """
        before = _Vendor()
        after = _Vendor(distributions=[("SPY", date(2026, 9, 28), 0.98)])

        async def check():
            conn = await asyncpg.connect(dsn)
            try:
                await _reset(conn, "SPY")
                await _ingest(run_ingest_bars, conn, before, session=SECOND)
                await _ingest(run_ingest_bars, conn, after, session=FIRST)
                return await _rows(conn, "SPY")
            finally:
                await conn.close()

        rows = asyncio.run(check())
        assert SECOND in rows
        for day, row in rows.items():
            assert float(row["adj_close"]) == after.bar("SPY", day).adj_close, day

    def test_a_failed_fetch_fails_the_ingest_and_changes_nothing(self, dsn) -> None:
        days = _window(SECOND)[-5:]

        async def check():
            conn = await asyncpg.connect(dsn)
            try:
                await _reset(conn, "SPY")
                await _sentinels(conn, "SPY", days)
                with pytest.raises(DataSourceError):
                    await _ingest(
                        run_ingest_bars,
                        conn,
                        _Vendor(fail=DataSourceError("yahoo is down")),
                        session=SECOND,
                    )
                return await _rows(conn, "SPY")
            finally:
                await conn.close()

        spy = asyncio.run(check())
        assert sorted(spy) == days
        assert {row["close"] for row in spy.values()} == {Decimal("9999.125")}

    def test_a_rerun_rewrites_no_row_that_did_not_change(self, dsn) -> None:
        """Years are refetched every session; an unchanged row is left alone."""
        vendor = _Vendor()

        async def check():
            conn = await asyncpg.connect(dsn)
            try:
                await _reset(conn, "SPY")
                await _ingest(run_ingest_bars, conn, vendor, session=SECOND)
                first = await _rows(conn, "SPY")
                await _ingest(run_ingest_bars, conn, vendor, session=SECOND)
                return first, await _rows(conn, "SPY")
            finally:
                await conn.close()

        first, second = asyncio.run(check())
        assert first == second


# ---------------------------------------------------------------------------
# The reference job
# ---------------------------------------------------------------------------


class TestTheReferenceJob:
    def test_a_live_owned_symbols_rows_are_never_changed(self, dsn) -> None:
        """
        SPY is the live ingest's. Its rows — here sentinels no vendor prints —
        survive the reference job whole, and the job fills only the sessions
        missing from its window.
        """
        vendor = _Vendor()
        stored = _window(SECOND)[-30:]

        async def check():
            conn = await asyncpg.connect(dsn)
            try:
                await _reset(conn, "SPY")
                await _sentinels(conn, "SPY", stored)
                before = await _rows(conn, "SPY")
                result = await _ingest(
                    run_ingest_reference_bars, conn, vendor, session=SECOND
                )
                return before, await _rows(conn, "SPY"), result
            finally:
                await conn.close()

        before, after, result = asyncio.run(check())
        assert len(stored) < REFERENCE_MIN_ROWS
        for day in stored:
            assert after[day] == before[day], f"the live ingest's {day} row changed"
        assert sorted(after) == _window(SECOND)
        assert result["backfilled"] == {"SPY": len(_window(SECOND)) - len(stored)}
        assert sorted(result["upserted"]) == ["GSG", "IEF"]

    def test_a_live_owned_symbol_with_its_history_is_not_even_fetched(
        self, dsn
    ) -> None:
        vendor = _Vendor()
        stored = _window(SECOND)

        async def check():
            conn = await asyncpg.connect(dsn)
            try:
                await _reset(conn, "SPY")
                await _sentinels(conn, "SPY", stored)
                before = await _rows(conn, "SPY")
                result = await _ingest(
                    run_ingest_reference_bars, conn, vendor, session=SECOND
                )
                return before, await _rows(conn, "SPY"), result
            finally:
                await conn.close()

        before, after, result = asyncio.run(check())
        assert len(stored) >= REFERENCE_MIN_ROWS
        assert after == before
        assert [call[0] for call in vendor.calls] == [("GSG", "IEF")]
        assert result["untouched"] == ["SPY"]

    def test_a_rebased_fetch_rewrites_every_reference_only_row(self, dsn) -> None:
        """
        Every stored row, not only the latest window's: the second day's span
        starts at the first stored session, so a regime state recorded from
        the table recomputes from it after a distribution.
        """
        before = _Vendor()
        after = _Vendor(distributions=[("IEF", SECOND, 0.97), ("GSG", FIRST, 0.98)])

        async def check():
            conn = await asyncpg.connect(dsn)
            try:
                await _reset(conn, OTHER)
                await _ingest(run_ingest_reference_bars, conn, before, session=FIRST)
                result = await _ingest(
                    run_ingest_reference_bars, conn, after, session=SECOND
                )
                stored = {s: await _rows(conn, s) for s in REFERENCE_SYMBOLS}
                return result, stored
            finally:
                await conn.close()

        result, stored = asyncio.run(check())
        assert result["rows_not_refreshed"] == 0
        # The first day's window starts earlier than the second's; a refetch of
        # the second's window alone would have left these on the old basis.
        oldest = min(stored["IEF"])
        assert oldest < SECOND - timedelta(days=REFERENCE_WINDOW_DAYS)
        for symbol, rows in stored.items():
            assert min(rows) == oldest
            for day, row in rows.items():
                expected = _as_fetched(after.bar(symbol, day))
                assert _prices(row) == expected, (symbol, day)

    def test_rerunning_is_idempotent(self, dsn) -> None:
        vendor = _Vendor()

        async def check():
            conn = await asyncpg.connect(dsn)
            try:
                await _reset(conn, "SPY")
                await _sentinels(conn, "SPY", _window(SECOND)[-10:])
                first = await _ingest(
                    run_ingest_reference_bars, conn, vendor, session=SECOND
                )
                tables = {s: await _rows(conn, s) for s in REFERENCE_SYMBOLS}
                second = await _ingest(
                    run_ingest_reference_bars, conn, vendor, session=SECOND
                )
                again = {s: await _rows(conn, s) for s in REFERENCE_SYMBOLS}
                return first, second, tables, again
            finally:
                await conn.close()

        first, second, tables, again = asyncio.run(check())
        assert again == tables, "a second run changed a row"
        assert first["backfilled"]["SPY"] > 0
        # One backfill was enough: SPY now has its history, and is left alone.
        assert second["backfilled"] == {} and second["untouched"] == ["SPY"]
        assert second["upserted"] == first["upserted"]

    def test_a_symbol_list_in_the_payload_is_ignored(self, dsn) -> None:
        vendor = _Vendor()

        async def check():
            conn = await asyncpg.connect(dsn)
            try:
                await _reset(conn)
                await _ingest(
                    run_ingest_reference_bars,
                    conn,
                    vendor,
                    session=SECOND,
                    symbols=["AAPL", "TSLA"],
                )
                return await conn.fetch("SELECT DISTINCT symbol FROM daily_bars")
            finally:
                await conn.close()

        symbols = asyncio.run(check())
        assert sorted(r["symbol"] for r in symbols) == list(REFERENCE_SYMBOLS)
        assert [call[0] for call in vendor.calls] == [REFERENCE_SYMBOLS]

    def test_the_worker_runs_it_with_the_kill_switch_engaged(
        self, dsn, monkeypatch
    ) -> None:
        """
        Claimed through the worker's own table, run by its own dispatch, and not
        stopped by the kill switch — which stops what reaches a venue, and this
        reaches none, as the live ingest does not.
        """
        vendor = _Vendor()
        monkeypatch.setattr(maintenance_jobs, "_default_source", lambda: vendor)
        _clock_at(monkeypatch, _settled(SECOND) + timedelta(minutes=1))

        async def check():
            conn = await asyncpg.connect(dsn)
            try:
                await _reset(conn)
                await conn.execute(
                    "UPDATE system_flags SET value = 'false'::jsonb "
                    "WHERE key = 'trading_enabled'"
                )
                job_id = await job_repo.enqueue(
                    conn,
                    "ingest_reference_bars",
                    {"session": SECOND.isoformat()},
                    priority=REFERENCE_PRIORITY,
                )
            finally:
                await conn.close()

            worker = Worker(dsn, "reference-bars-test")
            await worker.start()
            try:
                await worker._drain()
            finally:
                await worker.stop()

            conn = await asyncpg.connect(dsn)
            try:
                job = await conn.fetchrow(
                    "SELECT status, error, result FROM jobs WHERE id = $1", job_id
                )
                count = await conn.fetchval("SELECT COUNT(*) FROM daily_bars")
                await conn.execute(
                    "UPDATE system_flags SET value = 'true'::jsonb "
                    "WHERE key = 'trading_enabled'"
                )
                return job, count
            finally:
                await conn.close()

        job, count = asyncio.run(check())
        assert job["status"] == "succeeded", job["error"]
        assert count == len(_window(SECOND)) * len(REFERENCE_SYMBOLS)

    def test_a_sleeve_left_without_its_sessions_bar_is_retried(
        self, dsn, monkeypatch
    ) -> None:
        """
        The vendor leaves GSG's session bar out, late after the close or a
        per-ticker failure yfinance swallows. Through the worker's own claim,
        the job fails after what landed commits and goes back on the queue
        naming GSG, where it used to succeed and retire for good with a sleeve
        short; the retry, the bar published, succeeds.
        """
        vendors = iter([_Vendor(omit=[("GSG", SECOND)]), _Vendor()])
        monkeypatch.setattr(maintenance_jobs, "_default_source", lambda: next(vendors))
        _clock_at(monkeypatch, _settled(SECOND) + timedelta(minutes=1))

        async def check():
            conn = await asyncpg.connect(dsn)
            try:
                await _reset(conn, OTHER)
            finally:
                await conn.close()
            first = await _enqueue_and_drain(
                dsn, "ingest_reference_bars", SECOND, priority=REFERENCE_PRIORITY
            )
            conn = await asyncpg.connect(dsn)
            try:
                landed = await _session_rows(conn, SECOND)
            finally:
                await conn.close()
            await _release(dsn, first["id"])
            worker = Worker(dsn, "reference-retry-test")
            await worker.start()
            try:
                await worker._drain()
            finally:
                await worker.stop()
            conn = await asyncpg.connect(dsn)
            try:
                again = await conn.fetchrow(
                    "SELECT status, attempts FROM jobs WHERE id = $1", first["id"]
                )
                return first, landed, dict(again), await _session_rows(conn, SECOND)
            finally:
                await conn.close()

        first, landed, again, complete = asyncio.run(check())
        assert first["status"] == "queued" and first["attempts"] == 1
        assert "GSG (commodities), which the vendor did not return" in first["error"]
        assert landed == ["IEF", "SPY"], "what landed was not kept"
        assert again == {"status": "succeeded", "attempts": 2}
        assert complete == list(REFERENCE_SYMBOLS)

    def test_a_sleeve_enabled_after_the_live_ingest_ran_fails_the_job(
        self, dsn
    ) -> None:
        """
        The live ingest for the session runs owning only EFA; a deployment
        trading GSG is enabled before the reference job runs. GSG is the live
        ingest's now, and this job writes none of its session's bars, so it
        fails naming GSG and whose bar it is, where it used to succeed with
        GSG's close missing.
        """
        vendor = _Vendor()

        async def check():
            conn = await asyncpg.connect(dsn)
            try:
                await _reset(conn, OTHER)
                await _ingest(run_ingest_reference_bars, conn, vendor, session=FIRST)
                await _ingest(run_ingest_bars, conn, vendor, session=SECOND)
                await _deploy(conn, "GSG")
                with pytest.raises(DataSourceError) as raised:
                    await _ingest(
                        run_ingest_reference_bars, conn, vendor, session=SECOND
                    )
                return str(raised.value), await _session_rows(conn, SECOND)
            finally:
                await conn.close()

        error, landed = asyncio.run(check())
        assert "GSG (commodities), the live ingest's" in error
        assert "IEF" not in error and "SPY" not in error
        assert landed == [OTHER, "IEF", "SPY"]


# ---------------------------------------------------------------------------
# When the reference job may run
# ---------------------------------------------------------------------------


class TestTheWindow:
    def test_the_database_clock_refuses_an_unsettled_and_a_stale_session(
        self, dsn
    ) -> None:
        """
        No clock held here: the job reads Postgres's. The calendar's last
        session has not settled, and a 2021 session was superseded long ago;
        neither fetches or writes anything.
        """
        last = bounds()[1]
        vendor = _Vendor()

        async def check():
            conn = await asyncpg.connect(dsn)
            try:
                await _reset(conn)
                now = await conn.fetchval("SELECT clock_timestamp()")
                errors = []
                for session in (last, date(2021, 1, 4)):
                    with pytest.raises(ValueError) as raised:
                        await run_ingest_reference_bars(
                            conn,
                            {"session": session.isoformat()},
                            source_factory=lambda: vendor,
                        )
                    errors.append(str(raised.value))
                count = await conn.fetchval("SELECT COUNT(*) FROM daily_bars")
                return now, errors, count
            finally:
                await conn.close()

        now, (early, stale), count = asyncio.run(check())
        if now >= _settled(last):
            pytest.skip("the calendar's last session has settled; upgrade it")
        assert "settle at" in early
        assert "superseded" in stale
        assert vendor.calls == [] and count == 0

    def test_a_stale_session_moves_nothing_the_live_ingest_reads(self, dsn) -> None:
        """
        The review's case: SPY is the live ingest's, stored six years deep. A
        job for 2021-01-04 would have counted SPY's rows only up to that day,
        found it short, and backfilled years in front of the live ingest's
        first row, which every later live ingest would then refetch from. It
        is refused, and SPY is as the live ingest left it.
        """
        vendor = _Vendor()

        async def check():
            conn = await asyncpg.connect(dsn)
            try:
                await _reset(conn, "SPY")
                await _ingest(run_ingest_bars, conn, vendor, session=SECOND)
                before = await _rows(conn, "SPY")
                with pytest.raises(ValueError, match="superseded"):
                    await run_ingest_reference_bars(
                        conn,
                        {"session": "2021-01-04"},
                        source_factory=lambda: vendor,
                        now=_settled(SECOND) + timedelta(minutes=1),
                    )
                return before, await _rows(conn, "SPY")
            finally:
                await conn.close()

        before, after = asyncio.run(check())
        assert after == before
        assert min(after) == min(_window(SECOND))


# ---------------------------------------------------------------------------
# Who owns a sleeve, and what the live decision reads
# ---------------------------------------------------------------------------


class TestWhoOwnsASleeve:
    def test_disabling_hands_the_sleeve_over_and_enabling_hands_it_back(
        self, dsn
    ) -> None:
        """
        Ownership follows the live ingest, which fetches only what enabled
        deployments trade. With the deployment disabled, the reference job
        refreshes SPY as the live ingest would have — the adjusted close
        everywhere on the new basis — so the sleeve is left to neither job;
        enabled again, SPY is the live ingest's, and the reference job leaves
        every row of it alone.
        """
        before = _Vendor()
        after = _Vendor(distributions=[("SPY", SECOND, 0.99)])

        async def check():
            conn = await asyncpg.connect(dsn)
            try:
                deployment = await _reset(conn, "SPY")
                await _ingest(run_ingest_bars, conn, before, session=FIRST)
                await _set_status(conn, deployment, "disabled")
                handed = await _ingest(
                    run_ingest_reference_bars, conn, after, session=SECOND
                )
                spy = await _rows(conn, "SPY")
                await _set_status(conn, deployment, "enabled")
                back = await _ingest(
                    run_ingest_reference_bars, conn, after, session=SECOND
                )
                return handed, spy, back, await _rows(conn, "SPY")
            finally:
                await conn.close()

        handed, spy, back, again = asyncio.run(check())
        assert "SPY" in handed["upserted"]
        for day, row in spy.items():
            assert _prices(row) == _as_fetched(after.bar("SPY", day)), day
        assert back["untouched"] == ["SPY"]
        assert again == spy, "the reference job wrote a row the live ingest owns"

    def test_a_deployment_enabled_while_the_fetch_runs_takes_its_sleeve_back(
        self, dsn
    ) -> None:
        """
        SPY is no enabled deployment's when the job plans, so its span is
        fetched; the operator enables a deployment trading it while years
        download. Ownership is read again inside the transaction that writes,
        so every SPY row is as it was, down to its version.
        """
        state: dict[str, Any] = {}

        class _Enabling(_Vendor):
            def fetch(self, symbols, start, end):
                async def enable() -> None:
                    conn = await asyncpg.connect(state["dsn"])
                    try:
                        await _set_status(conn, state["deployment"], "enabled")
                    finally:
                        await conn.close()

                # The fetch runs in a thread, which has no loop of its own.
                asyncio.run(enable())
                return super().fetch(symbols, start, end)

        async def check():
            conn = await asyncpg.connect(dsn)
            try:
                deployment = await _reset(conn, "SPY")
                await _set_status(conn, deployment, "disabled")
                await _sentinels(conn, "SPY", _window(SECOND))
                state.update(dsn=dsn, deployment=deployment)
                before = await _rows(conn, "SPY")
                result = await _ingest(
                    run_ingest_reference_bars, conn, _Enabling(), session=SECOND
                )
                return before, result, await _rows(conn, "SPY")
            finally:
                await conn.close()

        before, result, after = asyncio.run(check())
        assert result["taken_back"] == ["SPY"]
        assert sorted(result["upserted"]) == ["GSG", "IEF"]
        assert after == before

    def test_the_live_decisions_close_is_never_the_reference_jobs(self, dsn) -> None:
        """
        The review's case: a deployment trading SPY is newly enabled, so SPY
        has no rows, and the reference job runs as early as it may. It
        backfills SPY's history, but none of the live ingest's lookback, and
        fails naming SPY as that job's. The live ingest then fails too: the
        live panel has no close for SPY, as before the reference job existed,
        rather than one a job the programme enqueued wrote. When the live
        ingest lands, its close is the one read.
        """
        vendor = _Vendor()

        async def check():
            conn = await asyncpg.connect(dsn)
            try:
                await _reset(conn, "SPY")
                with pytest.raises(DataSourceError) as raised:
                    await _ingest(
                        run_ingest_reference_bars, conn, vendor, session=SECOND
                    )
                with pytest.raises(DataSourceError):
                    await _ingest(
                        run_ingest_bars,
                        conn,
                        _Vendor(fail=DataSourceError("yahoo refused the download")),
                        session=SECOND,
                    )
                panel = await _load_panel(conn, ["SPY"], SECOND)
                backfilled = await _rows(conn, "SPY")
                await _ingest(run_ingest_bars, conn, vendor, session=SECOND)
                landed = await _load_panel(conn, ["SPY"], SECOND)
                return str(raised.value), panel, backfilled, landed
            finally:
                await conn.close()

        error, panel, backfilled, landed = asyncio.run(check())
        assert "SPY (equities), the live ingest's" in error
        assert len(backfilled) >= REFERENCE_MIN_ROWS
        assert max(backfilled) < lookback_start(SECOND)
        assert panel.value_on("SPY", SECOND, "close") is None
        closed = vendor.bar("SPY", SECOND).close
        assert landed.value_on("SPY", SECOND, "close") == closed


# ---------------------------------------------------------------------------
# One transaction
# ---------------------------------------------------------------------------


class TestOneTransaction:
    def test_a_write_that_fails_part_way_changes_no_stored_row(self, dsn) -> None:
        """
        IEF and GSG are the job's, and their stored rows are rewritten by the
        first statement; SPY is the live ingest's and short, so its history is
        inserted by the second, and a bar the database refuses there fails it,
        as a dropped connection or a statement timeout would. Every row IEF
        and GSG held is as it was, down to its version: no reader ever sees
        one sleeve re-based and another not, nor half a history.
        """
        refused_on = _window(SECOND)[500]

        class _Refused(_Vendor):
            def bar(self, symbol: str, day: date) -> Bar:
                bar = super().bar(symbol, day)
                if (symbol, day) == ("SPY", refused_on):
                    return dataclasses.replace(bar, open=None)
                return bar

        vendor = _Refused(
            distributions=[("IEF", SECOND, 0.97), ("GSG", SECOND, 0.98)]
        )

        async def check():
            conn = await asyncpg.connect(dsn)
            try:
                await _reset(conn, "SPY")
                for symbol in ("GSG", "IEF"):
                    await _sentinels(conn, symbol, _window(SECOND)[-30:])
                before = {s: await _rows(conn, s) for s in REFERENCE_SYMBOLS}
                with pytest.raises(asyncpg.NotNullViolationError):
                    await _ingest(
                        run_ingest_reference_bars, conn, vendor, session=SECOND
                    )
                return before, {s: await _rows(conn, s) for s in REFERENCE_SYMBOLS}
            finally:
                await conn.close()

        before, after = asyncio.run(check())
        assert after == before
        assert before["SPY"] == {} and len(before["IEF"]) == 30
