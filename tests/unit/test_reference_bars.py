"""
test_reference_bars.py
----------------------
The reference bars, and the live ingest's one adjustment basis, as rules.

The forward clock describes three reference sleeves from ``daily_bars``.
Nothing in ``src/programme`` may write that table, so the worker keeps it:
``ingest_reference_bars``, which the programme's planner will enqueue (phase
C4) and nothing enqueues yet. Its rules are what this file holds: the symbols
are a constant, never a payload's; the job runs only in its session's own
window, from the moment its bars settle until the next session's do, by the
database's clock; a symbol no live deployment trades is refetched over its
whole stored span and refreshed; a symbol the live ingest owns — judged again
at the moment of the write — is backfilled when short, never inside the live
ingest's lookback, and otherwise not even fetched, and no row of it is ever
overwritten; a sleeve left without its session's close fails the job; the
download runs off the event loop; and whoever enqueues it names its priority.

The live ingest keeps the same basis for the symbols it owns: each run
refetches a symbol's whole stored span, at least ``REFERENCE_WINDOW_DAYS``
deep, and every stored row takes the fetch's adjusted close, so a distribution
no longer leaves a step at a ten-day boundary. Raw prices are refreshed whole
only inside ``INGEST_LOOKBACK_DAYS``, as they always were. A stored session the
fetch omits is counted, never fatal; a span that will not download lands the
ten-day window and then fails the job, so it is retried.

Here the rules run against a connection that answers the few queries the
ingests make from rows held in memory and records what they write, so each
rule is seen on its own. What the SQL does with them is held on real Postgres
by ``tests/integration/test_reference_bars.py``.
"""

from __future__ import annotations

import ast
import asyncio
import bisect
import itertools
import logging
import threading
from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from src.core.calendar import bounds, next_session, session_close
from src.core.calendar import sessions as nyse_sessions
from src.core.panel import PricePanel
from src.core.types import Bar
from src.data import DataSourceError, YFinanceSource
from src.data.reference import (
    REFERENCE_MIN_ROWS,
    REFERENCE_PRIORITY,
    REFERENCE_SLEEVES,
    REFERENCE_SOURCE,
    REFERENCE_SYMBOLS,
    REFERENCE_WINDOW_DAYS,
)
from src.engine.scheduler import INGEST_AFTER_CLOSE, JobKind
from src.programme.jev_features import MIN_HISTORY_SESSIONS, regime_state
from src.programme.jev_questions import SLEEVES
from src.programme.main import JEV_HANDLERS
from src.worker.kill_job import KILL_GATED_KINDS
from src.worker.main import HANDLERS, SCHEDULED_KINDS
from src.worker.maintenance_jobs import (
    INGEST_LOOKBACK_DAYS,
    lookback_start,
    plan_reference_bars,
    reference_window,
    refetch_start,
    run_ingest_bars,
    run_ingest_reference_bars,
)
from src.worker.scheduling import PRIORITY

KIND = "ingest_reference_bars"

#: An ordinary NYSE session.
SESSION = date(2026, 9, 25)
WINDOW_START = SESSION - timedelta(days=REFERENCE_WINDOW_DAYS)

#: When SESSION's bars settle: its close plus the live ingest's delay.
SETTLED = session_close(SESSION) + INGEST_AFTER_CLOSE

#: The first session the live ingest refreshes whole for SESSION, and the last
#: a reference job may write for a symbol the live ingest owns.
LOOKBACK = lookback_start(SESSION)
BACKFILL_END = LOOKBACK - timedelta(days=1)

#: A symbol no sleeve uses, so a deployment of it leaves every sleeve to the
#: reference job.
OTHER_SYMBOL = "EFA"


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


def _bar(symbol: str, session: date, source: str = REFERENCE_SOURCE) -> Bar:
    price = 50.0 + session.toordinal() % 97 + len(symbol)
    return Bar(
        symbol=symbol,
        session=session,
        open=price,
        high=price + 1,
        low=price - 1,
        close=price,
        volume=1_000_000.0,
        adj_close=price * 0.9,
        source=source,
    )


class _Source:
    """Answers any window from a formula, and records what it was asked."""

    def __init__(
        self,
        name: str = REFERENCE_SOURCE,
        omit: Iterable[tuple[str, date]] = (),
        fail: Exception | None = None,
        refuse_before: date | None = None,
        during: Any = None,
    ) -> None:
        self.name = name
        self.omit = set(omit)
        self.fail = fail
        #: A window starting before this is refused, as a long download that
        #: times out would be, while a short one is answered.
        self.refuse_before = refuse_before
        #: Called while the download runs: what the world does meanwhile.
        self.during = during
        self.calls: list[tuple[tuple[str, ...], date, date]] = []

    def fetch(self, symbols: list[str], start: date, end: date) -> list[Bar]:
        self.calls.append((tuple(symbols), start, end))
        if self.during is not None:
            self.during()
        if self.fail is not None:
            raise self.fail
        if self.refuse_before is not None and start < self.refuse_before:
            raise DataSourceError(f"timed out fetching from {start}")
        return [
            _bar(symbol, session, self.name)
            for session in nyse_sessions(start, end)
            for symbol in symbols
            if (symbol, session) not in self.omit
        ]


class _Transaction:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *exc: object) -> bool:
        return False


class _Conn:
    """
    The ingests' queries, answered from rows held in memory; writes recorded.

    Only what the two ingests ask — the database's clock, the enabled
    deployments, each symbol's stored coverage, the stored keys in a span — is
    answered. Any other query fails, because a query this file has not
    accounted for is one whose effect it is not checking. The clock reads
    ``now``, a minute after SESSION's bars settle unless a test says otherwise.
    """

    def __init__(
        self,
        deployments: Iterable[tuple[str, dict[str, Any]]] = (),
        stored: Iterable[tuple[str, date]] = (),
        source: str = REFERENCE_SOURCE,
        now: datetime = SETTLED + timedelta(minutes=1),
    ) -> None:
        self.deployments = [
            {"id": i, "strategy_name": name, "params": params, "mode": "paper"}
            for i, (name, params) in enumerate(deployments)
        ]
        self.stored = {(symbol, day, source) for symbol, day in stored}
        self.now = now
        self.queries = 0
        self.writes: list[tuple[str, list[tuple[Any, ...]]]] = []

    async def fetchval(self, query: str, *args: Any) -> Any:
        self.queries += 1
        if " ".join(query.split()) == "SELECT clock_timestamp()":
            return self.now
        raise AssertionError(f"a query this fake does not answer: {query}")

    async def fetch(self, query: str, *args: Any) -> list[dict[str, Any]]:
        self.queries += 1
        text = " ".join(query.split())
        if text.startswith("SELECT id, strategy_name, params, mode FROM deployments"):
            return list(self.deployments)
        if "MIN(session) AS first_session" in text:
            source, symbols, session = args
            out = []
            for symbol in symbols:
                days = [d for s, d, src in self.stored if (s, src) == (symbol, source)]
                if days:
                    out.append(
                        {
                            "symbol": symbol,
                            "first_session": min(days),
                            "last_session": max(days),
                            "rows_to_session": sum(1 for d in days if d <= session),
                            "has_session": session in days,
                        }
                    )
            return out
        if text.startswith("SELECT symbol, session FROM daily_bars"):
            source, symbols, start, end = args
            return [
                {"symbol": s, "session": d}
                for s, d, src in sorted(self.stored)
                if src == source and s in symbols and start <= d <= end
            ]
        raise AssertionError(f"a query this fake does not answer: {text}")

    async def executemany(self, query: str, rows: Iterable[tuple[Any, ...]]) -> None:
        self.writes.append((" ".join(query.split()), list(rows)))

    def transaction(self) -> _Transaction:
        return _Transaction()

    def written(self, clause: str) -> list[tuple[str, date]]:
        """``(symbol, session)`` of every row sent to a statement with ``clause``."""
        return [
            (row[0], row[1])
            for query, rows in self.writes
            if clause in query
            for row in rows
        ]

    def refreshed(self, *, whole: bool) -> list[tuple[str, date]]:
        """
        ``(symbol, session)`` of every row the refresh sent, raw prices and all
        (``whole``) or its adjusted close alone: the statement's tenth argument.
        """
        return [
            (row[0], row[1])
            for query, rows in self.writes
            if "DO UPDATE" in query
            for row in rows
            if row[9] is whole
        ]


def _run(job: Any, conn: _Conn, source: _Source, **payload: Any) -> dict[str, Any]:
    payload.setdefault("session", SESSION.isoformat())
    return asyncio.run(job(conn, payload, source_factory=lambda: source))


def _owning(*symbols: str) -> list[tuple[str, dict[str, Any]]]:
    """One enabled deployment trading ``symbols``."""
    return [("buy_and_hold", {"symbols": list(symbols)})]


def _history(symbol: str, start: date, end: date = SESSION) -> list[tuple[str, date]]:
    return [(symbol, day) for day in nyse_sessions(start, end)]


# ---------------------------------------------------------------------------
# The constants
# ---------------------------------------------------------------------------


def test_the_reference_sleeves_are_the_regime_sleeves() -> None:
    assert tuple(REFERENCE_SLEEVES) == SLEEVES


def test_the_symbols_are_the_sleeves_and_nothing_else() -> None:
    assert REFERENCE_SYMBOLS == tuple(sorted(REFERENCE_SLEEVES.values()))
    assert REFERENCE_SYMBOLS == ("GSG", "IEF", "SPY")


def test_the_sleeves_cannot_be_rebound_at_runtime() -> None:
    with pytest.raises(TypeError):
        REFERENCE_SLEEVES["equities"] = "QQQ"  # type: ignore[index]


def test_the_regime_state_accepts_the_sleeves() -> None:
    """A mapping ``regime_state`` refused would be a caller's error, raised."""
    days = nyse_sessions(SESSION - timedelta(days=10), SESSION)
    rows = [
        (symbol, day, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0)
        for day in days
        for symbol in REFERENCE_SYMBOLS
    ]
    panel = PricePanel.from_bars(rows, as_of=SESSION)
    # Short of history, so no state: None, and not the ValueError of a bad map.
    assert regime_state(panel, SESSION, REFERENCE_SLEEVES) is None


def test_the_reference_source_is_the_live_ingests_vendor() -> None:
    assert YFinanceSource().name == REFERENCE_SOURCE


def test_the_window_covers_the_regime_history() -> None:
    """
    Every backfill the calendar can answer for — the window up to the live
    ingest's lookback, which a backfill never enters — holds more sessions than
    a full backfill needs, and a full backfill holds more than a regime state
    needs, so one backfill is enough and a symbol that has one is not
    refetched.
    """
    first, last = bounds()
    days = nyse_sessions(first, last)
    held = [
        bisect.bisect_right(days, lookback_start(day) - timedelta(days=1))
        - bisect.bisect_left(days, day - timedelta(days=REFERENCE_WINDOW_DAYS))
        for day in days
        if day - timedelta(days=REFERENCE_WINDOW_DAYS) >= first
    ]
    assert held, "the calendar holds no whole window, so this proves nothing"
    assert min(held) >= REFERENCE_MIN_ROWS > MIN_HISTORY_SESSIONS


# ---------------------------------------------------------------------------
# The span
# ---------------------------------------------------------------------------


def test_a_symbol_with_no_rows_is_fetched_a_window_deep() -> None:
    assert refetch_start(SESSION, None) == WINDOW_START


def test_the_span_reaches_back_to_the_first_stored_row() -> None:
    first = date(2004, 3, 1)
    assert refetch_start(SESSION, first) == first


def test_a_recent_first_row_does_not_shorten_the_window() -> None:
    assert refetch_start(SESSION, SESSION - timedelta(days=30)) == WINDOW_START


@pytest.mark.parametrize(
    "first_stored",
    [None, date(1999, 1, 4), WINDOW_START, SESSION - timedelta(days=3), SESSION],
)
def test_a_missed_session_is_caught_at_least_as_far_back_as_before(
    first_stored: date | None,
) -> None:
    """``INGEST_LOOKBACK_DAYS`` keeps its meaning; the span always covers it."""
    assert refetch_start(SESSION, first_stored) <= SESSION - timedelta(
        days=INGEST_LOOKBACK_DAYS
    )


# ---------------------------------------------------------------------------
# The plan
# ---------------------------------------------------------------------------


def test_a_reference_only_symbol_is_refetched_whole() -> None:
    plan = plan_reference_bars(
        SESSION,
        deployed=(),
        first_stored={"IEF": date(2010, 1, 4)},
        stored_rows={"IEF": 4200},
    )
    assert dict(plan.upsert) == {
        "GSG": WINDOW_START,
        "IEF": date(2010, 1, 4),
        "SPY": WINDOW_START,
    }
    assert not plan.backfill and not plan.untouched
    assert plan.start == date(2010, 1, 4)


@pytest.mark.parametrize(
    "rows, backfilled",
    [
        (0, True),
        (1, True),
        (REFERENCE_MIN_ROWS - 1, True),
        (REFERENCE_MIN_ROWS, False),
        (5_000, False),
    ],
)
def test_a_live_owned_symbol_is_only_backfilled(rows: int, backfilled: bool) -> None:
    plan = plan_reference_bars(
        SESSION,
        deployed={"SPY", "EFA"},
        first_stored={"SPY": date(1999, 1, 4)} if rows else {},
        stored_rows={"SPY": rows},
    )
    assert "SPY" not in plan.upsert, "the reference job overwrote the live ingest"
    if backfilled:
        assert dict(plan.backfill) == {"SPY": WINDOW_START}
        assert plan.untouched == ()
    else:
        assert not plan.backfill
        assert plan.untouched == ("SPY",)


@pytest.mark.parametrize(
    "deployed",
    [
        set(chosen) | {"AAPL"}
        for size in range(len(REFERENCE_SYMBOLS) + 1)
        for chosen in itertools.combinations(REFERENCE_SYMBOLS, size)
    ],
)
@pytest.mark.parametrize("rows", [0, REFERENCE_MIN_ROWS])
def test_each_reference_symbol_is_planned_once_and_nothing_else_is(
    deployed: set[str], rows: int
) -> None:
    plan = plan_reference_bars(
        SESSION,
        deployed=deployed,
        first_stored={"AAPL": date(1999, 1, 4)},
        stored_rows=dict.fromkeys((*REFERENCE_SYMBOLS, "AAPL"), rows),
    )
    parts = [set(plan.upsert), set(plan.backfill), set(plan.untouched)]
    assert sorted(itertools.chain.from_iterable(parts)) == list(REFERENCE_SYMBOLS)
    assert not set(plan.upsert) & deployed
    assert set(plan.symbols) <= set(REFERENCE_SYMBOLS)


# ---------------------------------------------------------------------------
# The reference job
# ---------------------------------------------------------------------------


def test_a_symbol_list_in_the_payload_is_ignored() -> None:
    conn, source = _Conn(), _Source()
    result = _run(
        run_ingest_reference_bars,
        conn,
        source,
        symbols=["AAPL", "TSLA"],
        sleeves={"equities": "AAPL"},
        deployment_ids=["x"],
    )
    assert [call[0] for call in source.calls] == [REFERENCE_SYMBOLS]
    assert {symbol for symbol, _ in conn.written("DO UPDATE")} == set(REFERENCE_SYMBOLS)
    assert sorted(result["upserted"]) == list(REFERENCE_SYMBOLS)


@pytest.mark.parametrize(
    "day",
    ["2021-12-25", "2021-06-19", "1980-01-02", "2099-01-02", "not a date"],
)
def test_a_day_that_is_not_a_session_is_refused_before_anything_is_asked(
    day: str,
) -> None:
    conn, source = _Conn(), _Source()
    with pytest.raises(ValueError):
        _run(run_ingest_reference_bars, conn, source, session=day)
    assert source.calls == [] and conn.queries == 0 and conn.writes == []


def test_a_source_that_is_not_the_reference_source_is_refused() -> None:
    conn, source = _Conn(), _Source(name="synthetic")
    with pytest.raises(ValueError, match="yfinance"):
        _run(run_ingest_reference_bars, conn, source)
    assert source.calls == [] and conn.writes == []


def test_a_live_owned_symbol_with_its_history_is_not_fetched() -> None:
    conn = _Conn(
        deployments=_owning("SPY"), stored=_history("SPY", date(2019, 1, 2))
    )
    source = _Source()
    result = _run(run_ingest_reference_bars, conn, source)
    assert [call[0] for call in source.calls] == [("GSG", "IEF")]
    assert "SPY" not in {symbol for symbol, _ in conn.written("")}
    assert result["untouched"] == ["SPY"]


def test_each_row_reaches_the_writer_its_owner_allows() -> None:
    """
    A reference-only symbol is upserted; a live-owned one only ever reaches
    ``ON CONFLICT DO NOTHING``, collisions with the live ingest's rows included.
    """
    stored = _history("SPY", SESSION - timedelta(days=20))
    conn = _Conn(deployments=_owning("SPY"), stored=stored)
    source = _Source()
    result = _run(run_ingest_reference_bars, conn, source)

    upserted = conn.written("DO UPDATE")
    inserted = conn.written("DO NOTHING")
    colliding = [key for key in stored if key[1] <= BACKFILL_END]
    assert {symbol for symbol, _ in upserted} == {"GSG", "IEF"}
    assert {symbol for symbol, _ in inserted} == {"SPY"}
    assert colliding and set(colliding) <= set(inserted), (
        "the colliding rows were not sent"
    )
    assert min(day for _, day in inserted) >= WINDOW_START
    assert result["backfilled"] == {"SPY": len(inserted) - len(colliding)}


def test_a_live_owned_symbols_lookback_is_never_written() -> None:
    """
    The rows the live ingest refreshes whole are its alone, and the session's
    own close among them is what the live decision sizes its orders from. A
    backfill of a symbol with no rows at all, which would insert every one of
    them, stops the day before the lookback, so a job the programme enqueues
    can never supply the bar money reads, even when the live ingest fails.
    """
    conn = _Conn(deployments=_owning("SPY"))
    _run_expecting_missing(conn, _Source())

    inserted = sorted(day for symbol, day in conn.written("DO NOTHING"))
    assert inserted == nyse_sessions(WINDOW_START, BACKFILL_END)
    assert "SPY" not in {symbol for symbol, _ in conn.written("DO UPDATE")}


def test_a_failed_fetch_fails_the_job_and_writes_nothing() -> None:
    conn, source = _Conn(), _Source(fail=DataSourceError("yahoo is down"))
    with pytest.raises(DataSourceError):
        _run(run_ingest_reference_bars, conn, source)
    assert conn.writes == []


def test_a_stored_session_the_fetch_omits_is_counted(
    caplog: pytest.LogCaptureFixture,
) -> None:
    gap = date(2024, 3, 12)
    conn = _Conn(stored=[("IEF", gap)])
    source = _Source(omit=[("IEF", gap)])
    with caplog.at_level(logging.WARNING):
        result = _run(run_ingest_reference_bars, conn, source)
    assert result["rows_not_refreshed"] == 1
    assert any("IEF 2024-03-12" in record.getMessage() for record in caplog.records)


def test_a_symbol_the_fetch_returned_nothing_for_is_named() -> None:
    """Its session's close already stored, by an earlier attempt, say."""
    days = nyse_sessions(WINDOW_START, SESSION)
    conn = _Conn(stored=[("GSG", SESSION)])
    source = _Source(omit=[("GSG", day) for day in days])
    result = _run(run_ingest_reference_bars, conn, source)
    assert result["returned_nothing"] == ["GSG"]
    assert result["upserted"]["GSG"] == 0


# ---------------------------------------------------------------------------
# Every sleeve's close for the session, or the job fails
# ---------------------------------------------------------------------------


def _run_expecting_missing(conn: _Conn, source: _Source, **payload: Any) -> str:
    """Run the reference job, which must fail for a missing close; its error."""
    with pytest.raises(DataSourceError, match="no close is stored for") as raised:
        _run(run_ingest_reference_bars, conn, source, **payload)
    return str(raised.value)


def test_a_sleeve_without_its_sessions_bar_fails_after_the_rest_is_written() -> None:
    """
    The job exists to put its session's close in the table. A vendor that
    leaves one sleeve's session bar out — late after the close, or a
    per-ticker failure that yfinance swallows while the other tickers load —
    fails the job, so the worker retries it rather than retiring it as done;
    what did land is written first, and stays.
    """
    conn = _Conn()
    error = _run_expecting_missing(conn, _Source(omit=[("GSG", SESSION)]))

    assert "GSG (commodities), which the vendor did not return" in error
    assert "IEF" not in error and "SPY" not in error
    written = conn.written("DO UPDATE")
    assert {symbol for symbol, _ in written} == set(REFERENCE_SYMBOLS)
    assert ("GSG", SESSION) not in written and ("IEF", SESSION) in written


def test_every_sleeve_without_its_sessions_bar_is_named() -> None:
    """
    The vendor late for all three: the job used to log that today's data was
    not yet available and succeed, retired for good with no close stored.
    """
    source = _Source(omit=[(symbol, SESSION) for symbol in REFERENCE_SYMBOLS])
    error = _run_expecting_missing(_Conn(), source)
    for sleeve, symbol in REFERENCE_SLEEVES.items():
        assert f"{symbol} ({sleeve}), which the vendor did not return" in error


@pytest.mark.parametrize(
    "stored_from",
    [date(2019, 1, 2), SESSION - timedelta(days=20)],
    ids=["with its history", "short of it"],
)
def test_a_live_owned_sleeve_without_its_sessions_bar_fails_naming_the_live_ingest(
    stored_from: date,
) -> None:
    """
    SPY is the live ingest's, and its session bar is not stored: that job's
    fetch left it out, or a deployment trading it was enabled after that job
    ran. This one may not write the bar the live decision sizes from, so it
    fails, saying whose bar it is, rather than succeed with a sleeve short.
    """
    stored = _history("SPY", stored_from, SESSION - timedelta(days=1))
    conn = _Conn(deployments=_owning("SPY"), stored=stored)
    error = _run_expecting_missing(conn, _Source())

    assert "SPY (equities), the live ingest's" in error
    assert "GSG" not in error and "IEF" not in error
    assert ("SPY", SESSION) not in conn.written("")


def test_a_live_owned_sleeve_with_its_sessions_bar_needs_nothing_more() -> None:
    conn = _Conn(deployments=_owning("SPY"), stored=_history("SPY", date(2019, 1, 2)))
    result = _run(run_ingest_reference_bars, conn, _Source())
    assert result["untouched"] == ["SPY"]


def test_with_every_sleeve_the_live_ingests_a_missing_close_still_fails() -> None:
    """
    Every sleeve traded and stored deep, so the job fetches nothing at all;
    it still checks that each has its session's close.
    """
    stored = [
        *_history("GSG", date(2019, 1, 2)),
        *_history("IEF", date(2019, 1, 2)),
        *_history("SPY", date(2019, 1, 2), SESSION - timedelta(days=1)),
    ]
    conn = _Conn(deployments=_owning(*REFERENCE_SYMBOLS), stored=stored)
    source = _Source()
    error = _run_expecting_missing(conn, source)
    assert "SPY (equities), the live ingest's" in error
    assert source.calls == [] and conn.writes == []


# ---------------------------------------------------------------------------
# When a reference job may run
# ---------------------------------------------------------------------------


def _utc(*parts: int) -> datetime:
    return datetime(*parts, tzinfo=UTC)


@pytest.mark.parametrize(
    "session, settles, superseded",
    [
        # Summer time: the close is 20:00 UTC; the next session is Monday.
        (date(2026, 9, 25), _utc(2026, 9, 25, 20, 45), _utc(2026, 9, 28, 20, 45)),
        # The day after Thanksgiving closes at 13:00 New York, 18:00 UTC.
        (date(2026, 11, 27), _utc(2026, 11, 27, 18, 45), _utc(2026, 11, 30, 21, 45)),
        # The Friday before the clocks go back: winter from the Monday.
        (date(2026, 10, 30), _utc(2026, 10, 30, 20, 45), _utc(2026, 11, 2, 21, 45)),
    ],
)
def test_the_window_runs_from_the_sessions_settling_to_the_next_ones(
    session: date, settles: datetime, superseded: datetime
) -> None:
    assert reference_window(session) == (settles, superseded)


def test_the_calendars_last_session_has_no_successor_to_wait_for() -> None:
    last = bounds()[1]
    settles, superseded = reference_window(last)
    assert settles == session_close(last) + INGEST_AFTER_CLOSE
    assert superseded is None


@pytest.mark.parametrize(
    "session, now",
    [
        # The session in progress, as a planner that forgot scheduled_for,
        # or an operator's job queued by hand, would run it.
        (SESSION, _utc(2026, 9, 25, 15, 0)),
        (SESSION, session_close(SESSION)),
        (SESSION, SETTLED - timedelta(seconds=1)),
        # A session that has not happened at all.
        (date(2027, 3, 1), SETTLED),
    ],
    ids=["intraday", "at the bell", "a second early", "a future session"],
)
def test_a_job_before_its_session_settles_is_refused_before_anything_is_fetched(
    session: date, now: datetime
) -> None:
    conn, source = _Conn(now=now), _Source()
    with pytest.raises(ValueError, match="settle at"):
        _run(run_ingest_reference_bars, conn, source, session=session.isoformat())
    assert source.calls == [] and conn.writes == []


@pytest.mark.parametrize(
    "session",
    [date(2021, 1, 4), next_session(date(2026, 9, 1)), SESSION],
    ids=["years stale", "weeks stale", "the next session has settled"],
)
def test_a_job_whose_next_session_has_settled_is_refused(session: date) -> None:
    """
    A stale session would count a live-owned sleeve's history only up to
    itself, find it short, and backfill years in front of the live ingest's
    first row, moving where that job's span starts for good; and the next
    session's job refetches everything it would.
    """
    now = session_close(next_session(SESSION)) + INGEST_AFTER_CLOSE
    conn = _Conn(
        deployments=_owning("SPY"),
        stored=_history("SPY", date(2020, 9, 16)),
        now=now,
    )
    source = _Source()
    with pytest.raises(ValueError, match="superseded"):
        _run(run_ingest_reference_bars, conn, source, session=session.isoformat())
    assert source.calls == [] and conn.writes == []


@pytest.mark.parametrize(
    "now",
    [SETTLED, reference_window(SESSION)[1] - timedelta(microseconds=1)],
    ids=["the moment its bars settle", "the moment before the next ones do"],
)
def test_a_job_runs_anywhere_inside_its_window(now: datetime) -> None:
    """A retry, or a worker back from a weekend's outage, still runs it."""
    conn, source = _Conn(now=now), _Source()
    result = _run(run_ingest_reference_bars, conn, source)
    assert sorted(result["upserted"]) == list(REFERENCE_SYMBOLS)
    assert source.calls


def test_the_window_is_judged_by_the_databases_clock() -> None:
    """The clock that released the job from the queue, not this machine's."""
    conn, source = _Conn(now=SETTLED - timedelta(minutes=1)), _Source()
    with pytest.raises(ValueError, match="settle at"):
        _run(run_ingest_reference_bars, conn, source)
    conn.now = SETTLED
    _run(run_ingest_reference_bars, conn, source)


def test_a_later_row_another_writer_stored_is_refetched_too() -> None:
    """
    Inside the window no reference job has written a later session; another
    writer can, when a sleeve changes hands. The refetch reaches it, so it is
    left on no other fetch's basis.
    """
    later = next_session(SESSION)
    conn = _Conn(stored=[("IEF", later)])
    source = _Source()
    _run(run_ingest_reference_bars, conn, source)
    assert source.calls == [(REFERENCE_SYMBOLS, WINDOW_START, later)]
    assert ("IEF", later) in conn.refreshed(whole=False)


# ---------------------------------------------------------------------------
# Who owns a sleeve, at the moment of the write
# ---------------------------------------------------------------------------


def test_a_sleeve_enabled_while_the_fetch_runs_is_left_to_the_live_ingest() -> None:
    """
    SPY is no deployment's when the job plans, so its span is fetched; a
    deployment trading it is enabled while years download. Ownership is read
    again inside the transaction that writes, so none of SPY's rows is
    written: they are the live ingest's now.
    """
    stored = _history("SPY", date(2020, 9, 16))
    conn = _Conn(stored=stored)

    def enable() -> None:
        conn.deployments.extend(_Conn(deployments=_owning("SPY")).deployments)

    result = _run(run_ingest_reference_bars, conn, _Source(during=enable))
    assert "SPY" not in {symbol for symbol, _ in conn.written("")}
    assert result["taken_back"] == ["SPY"]
    assert sorted(result["upserted"]) == ["GSG", "IEF"]


def test_a_sleeve_no_enabled_deployment_trades_is_the_reference_jobs() -> None:
    """
    The live ingest fetches only what enabled deployments trade, so a sleeve
    whose deployment is disabled is refreshed by this job, by the live
    ingest's rules, or by nobody.
    """
    conn = _Conn(stored=_history("SPY", date(2020, 9, 16)))
    result = _run(run_ingest_reference_bars, conn, _Source())
    assert "SPY" in result["upserted"]
    assert ("SPY", SESSION) in conn.refreshed(whole=True)
    assert ("SPY", LOOKBACK - timedelta(days=1)) in conn.refreshed(whole=False)


# ---------------------------------------------------------------------------
# The live ingest keeps one basis
# ---------------------------------------------------------------------------


def test_the_live_ingest_refetches_each_owned_symbols_whole_span() -> None:
    first = date(2010, 1, 4)
    conn = _Conn(deployments=_owning("SPY", "EFA"), stored=_history("SPY", first))
    source = _Source()
    result = _run(run_ingest_bars, conn, source)

    assert source.calls == [(("EFA", "SPY"), first, SESSION)]
    written = conn.written("DO UPDATE")
    spy = sorted(day for symbol, day in written if symbol == "SPY")
    efa = sorted(day for symbol, day in written if symbol == "EFA")
    assert spy == nyse_sessions(first, SESSION), "a stored SPY row was not refetched"
    # EFA has nothing stored, so it gains a window, and none of what the wider
    # fetch for SPY returned before its own span.
    assert efa == nyse_sessions(WINDOW_START, SESSION)
    assert conn.written("DO NOTHING") == []
    assert result["refetched_from"] == first.isoformat()
    assert result["rows_not_refreshed"] == 0


@pytest.mark.parametrize("job", [run_ingest_bars, run_ingest_reference_bars])
def test_raw_prices_are_refreshed_only_inside_the_lookback(job: Any) -> None:
    """
    A row inside ``INGEST_LOOKBACK_DAYS`` is refreshed whole, as it always was;
    an older one takes only its adjusted close, so a split the vendor folds
    into its old closes does not reprice what was written.
    """
    first = date(2010, 1, 4)
    conn = _Conn(deployments=_owning("SPY"), stored=_history("SPY", first))
    if job is run_ingest_reference_bars:
        conn = _Conn(deployments=_owning(OTHER_SYMBOL), stored=_history("IEF", first))
    _run(job, conn, _Source())

    boundary = SESSION - timedelta(days=INGEST_LOOKBACK_DAYS)
    whole = [day for _, day in conn.refreshed(whole=True)]
    adjusted = [day for _, day in conn.refreshed(whole=False)]
    assert whole and min(whole) >= boundary and max(whole) <= SESSION
    assert adjusted and max(adjusted) < boundary


def test_every_writer_sends_rows_in_one_order() -> None:
    """Two workers refreshing overlapping spans lock rows in one order."""
    conn = _Conn(deployments=_owning("SPY", "EFA"))
    _run(run_ingest_bars, conn, _Source())
    for _, rows in conn.writes:
        keys = [(row[0], row[1]) for row in rows]
        assert keys == sorted(keys)


def test_a_stored_session_the_fetch_omits_is_counted_not_raised(
    caplog: pytest.LogCaptureFixture,
) -> None:
    gap = date(2025, 7, 3)
    conn = _Conn(deployments=_owning("SPY"), stored=_history("SPY", date(2025, 6, 2)))
    source = _Source(omit=[("SPY", gap)])
    with caplog.at_level(logging.WARNING):
        result = _run(run_ingest_bars, conn, source)
    assert result["rows_not_refreshed"] == 1
    assert ("SPY", gap) not in conn.written("DO UPDATE")
    assert any("SPY 2025-07-03" in record.getMessage() for record in caplog.records)


def test_a_failed_span_fetch_lands_the_ten_day_window_then_fails_the_job(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """
    The session's bar still lands when years will not download, wherever a
    ten-day fetch would have landed it, so the live decision loses nothing.
    The job then fails, naming what it could not re-base: those rows keep an
    older basis, a step at the ten-day boundary is back, and a job that
    succeeded would hide it in a result nothing reads. Failing is what retries
    the whole span.
    """
    fallback = lookback_start(SESSION)
    first = date(2024, 1, 2)
    stored = _history("SPY", first)
    conn = _Conn(deployments=_owning("SPY"), stored=stored)
    source = _Source(refuse_before=fallback)
    with caplog.at_level(logging.WARNING), pytest.raises(DataSourceError) as raised:
        _run(run_ingest_bars, conn, source)

    assert [call[1] for call in source.calls] == [WINDOW_START, fallback]
    written = sorted(day for _, day in conn.written("DO UPDATE"))
    assert written == nyse_sessions(fallback, SESSION)
    older = len([day for _, day in stored if day < fallback])
    assert f"{older} stored row(s) it did not return keep an older" in str(
        raised.value
    )
    assert f"from {WINDOW_START.isoformat()} failed" in str(raised.value)
    assert "timed out" in str(raised.value), "the span's own failure was lost"
    assert any(
        "failing the job once that lands" in record.getMessage()
        for record in caplog.records
    )


def test_the_live_ingest_names_each_symbol_without_its_sessions_bar(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """
    One symbol's bar late while another's has landed: the newest bar across
    them said the day was complete. Named, and not fatal — the live decision
    has no close for it, as it never had.
    """
    conn = _Conn(deployments=_owning("SPY", "EFA"))
    source = _Source(omit=[("SPY", SESSION)])
    with caplog.at_level(logging.WARNING):
        result = _run(run_ingest_bars, conn, source)
    assert result["session_missing"] == ["SPY"]
    assert result["latest_session"] == SESSION.isoformat()
    assert any(
        "no bar is stored for SPY" in record.getMessage() for record in caplog.records
    )


@pytest.mark.parametrize("job", [run_ingest_bars, run_ingest_reference_bars])
def test_the_fetch_leaves_the_event_loop_free(job: Any) -> None:
    """
    Years download while the job waits. On the loop's own thread the download
    would stall the lease and the heartbeat for as long as it takes, and the
    API would call the worker dead; so the fetch must run where a coroutine
    can still run beside it. Here one must, for the fetch to return at all.
    """
    started, released = threading.Event(), threading.Event()

    class _Blocking(_Source):
        def fetch(self, symbols: list[str], start: date, end: date) -> list[Bar]:
            started.set()
            if not released.wait(timeout=2):
                raise AssertionError(
                    "the fetch held the event loop: nothing else ran while it did"
                )
            return super().fetch(symbols, start, end)

    async def release() -> None:
        while not started.is_set():
            await asyncio.sleep(0.01)
        released.set()

    async def scenario() -> dict[str, Any]:
        conn = _Conn(deployments=_owning(OTHER_SYMBOL))
        beside = asyncio.create_task(release())
        payload = {"session": SESSION.isoformat()}
        try:
            return await job(conn, payload, source_factory=_Blocking)
        finally:
            beside.cancel()

    result = asyncio.run(scenario())
    assert released.is_set()
    assert result["session"] == SESSION.isoformat()


def test_a_late_job_refetches_what_a_newer_job_wrote() -> None:
    """
    A job for an older session that runs after a newer one refetches to the
    newest stored row, so no row is left on another fetch's basis; the rows
    after its own session take only their adjusted close.
    """
    first = date(2020, 3, 2)
    conn = _Conn(deployments=_owning("SPY"), stored=_history("SPY", first))
    source = _Source()
    older = date(2026, 9, 1)
    _run(run_ingest_bars, conn, source, session=older.isoformat())

    assert source.calls == [(("SPY",), first, SESSION)]
    later = [day for _, day in conn.written("DO UPDATE") if day > older]
    assert later == nyse_sessions(older + timedelta(days=1), SESSION)
    assert all(day <= older for _, day in conn.refreshed(whole=True))


def test_a_failed_fetch_still_fails_the_live_ingest() -> None:
    conn = _Conn(deployments=_owning("SPY"))
    source = _Source(fail=DataSourceError("yahoo is down"))
    with pytest.raises(DataSourceError):
        _run(run_ingest_bars, conn, source)
    assert conn.writes == []


def test_no_deployment_means_nothing_is_fetched() -> None:
    conn, source = _Conn(), _Source()
    result = _run(run_ingest_bars, conn, source)
    assert source.calls == [] and conn.writes == []
    assert result["bars"] == 0 and result["rows_not_refreshed"] == 0


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def test_it_is_the_workers_and_unscheduled() -> None:
    """The ``shadow_decision`` precedent: the worker's, and planned by nothing here."""
    assert HANDLERS[KIND] is run_ingest_reference_bars
    assert KIND not in SCHEDULED_KINDS
    assert KIND not in {kind.value for kind in JobKind}
    assert KIND not in KILL_GATED_KINDS
    assert KIND not in JEV_HANDLERS


def test_it_is_not_drainable() -> None:
    pytest.importorskip("fastapi")
    from src.api.drain import DRAINABLE

    assert KIND not in DRAINABLE


def test_it_waits_behind_every_kind_on_the_live_path() -> None:
    """
    The worker runs one job at a time, so a reference fetch planned for the
    same minute as ``ingest_bars`` must be claimed after it, and after the
    decision that reads it.
    """
    assert set(PRIORITY) == set(SCHEDULED_KINDS), (
        "a live-path kind has no priority, so this compares against too little"
    )
    assert 0 < REFERENCE_PRIORITY < min(PRIORITY.values())


def test_only_the_programmes_planner_may_enqueue_it() -> None:
    """
    Nothing enqueues it yet; the planner the forward clock needs will, and
    nothing else should.
    """
    from tests.unit.test_job_ownership import _every_enqueue

    kinds, _ = _every_enqueue()
    assert kinds.get(KIND, set()) <= {"src/programme/jev_plan.py"}


def _unprioritised(source: str) -> list[str]:
    """
    Every enqueue of the reference job whose priority is not
    ``REFERENCE_PRIORITY``, by name.

    ``enqueue(conn, kind, payload, priority, ...)``: the priority is the
    fourth positional argument or ``priority=``, and a literal, another name or
    none at all — the queue's default of 0 — is refused. The constant is what
    a test holds behind the live path; a number typed at the call is not.
    """
    found = []
    for node in ast.walk(ast.parse(source)):
        if not (isinstance(node, ast.Call) and _named(node.func) == "enqueue"):
            continue
        kind = node.args[1] if len(node.args) >= 2 else None
        priority = node.args[3] if len(node.args) >= 4 else None
        for keyword in node.keywords:
            if keyword.arg == "kind":
                kind = keyword.value
            elif keyword.arg == "priority":
                priority = keyword.value
        if not (isinstance(kind, ast.Constant) and kind.value == KIND):
            continue
        if _named(priority) != "REFERENCE_PRIORITY":
            found.append(f"line {node.lineno}: {ast.unparse(node)}")
    return found


def _named(node: ast.expr | None) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def test_every_enqueue_of_it_passes_the_reference_priority() -> None:
    """
    What makes "claimed behind every live-path kind" a rule rather than a hope:
    whoever enqueues the job passes the constant the test above holds below
    the live path. Vacuous until the planner lands, and binding on it then.
    """
    root = Path(__file__).resolve().parents[2]
    offenders = [
        f"{path.relative_to(root)} {found}"
        for path in sorted((root / "src").rglob("*.py"))
        for found in _unprioritised(path.read_text(encoding="utf-8"))
    ]
    assert not offenders, (
        f"{KIND} is enqueued without REFERENCE_PRIORITY, so nothing holds it "
        "behind the live path:\n" + "\n".join(offenders)
    )


@pytest.mark.parametrize(
    "source, refused",
    [
        (f'await job_repo.enqueue(conn, "{KIND}", p, priority=REFERENCE_PRIORITY)', 0),
        (f'await enqueue(conn, "{KIND}", p, reference.REFERENCE_PRIORITY)', 0),
        (f'await job_repo.enqueue(conn, "{KIND}", p)', 1),
        (f'await job_repo.enqueue(conn, "{KIND}", p, priority=1)', 1),
        (f'await job_repo.enqueue(conn, kind="{KIND}", priority=PRIORITY)', 1),
        ('await job_repo.enqueue(conn, "jev_probe", p)', 0),
    ],
)
def test_the_priority_scan_reads_each_spelling(source: str, refused: int) -> None:
    assert len(_unprioritised(source)) == refused
