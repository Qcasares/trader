"""
maintenance_jobs.py
-------------------
The three job kinds the scheduler planned and nothing implemented, and the
forward clock's reference bars.

``src/engine/scheduler.py`` emits five kinds for a trading session. The worker
handled three of them; ``ingest_bars``, ``eod_marks`` and ``reconcile`` hit
"no handler for job kind" and failed without retry. The first of those is the
one that mattered most: the live decision reads ``daily_bars``, and nothing
populated it, so the live loop could never have run at all.

``ingest_reference_bars`` is planned by no one here. The AI programme's forward
clock describes three reference sleeves from ``daily_bars``, and the programme
may neither write that table nor import this module, so the programme's planner
enqueues the job (``src/programme/jev_plan.py``, from phase C4) and the worker
runs it, as it runs ``shadow_decision``. The planner does so only while the
programme, Jev and Jev's decisions area are switched on, with a usable pin and
a key, and every one of those is seeded off.

Each handler here is idempotent. A scheduled job may be retried, and a
re-ingested bar or a re-written mark must produce the same row rather than a
second one.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections import Counter
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import MappingProxyType
from typing import Any, NamedTuple

import asyncpg

from src.core.calendar import bounds, is_session, next_session, session_close
from src.core.types import Bar
from src.data import DataSourceError
from src.data.reference import (
    REFERENCE_MIN_ROWS,
    REFERENCE_SLEEVES,
    REFERENCE_SOURCE,
    REFERENCE_SYMBOLS,
    REFERENCE_WINDOW_DAYS,
)
from src.db.repos import marks
from src.engine.scheduler import INGEST_AFTER_CLOSE
from src.strategies import build_strategy

logger = logging.getLogger(__name__)

#: How far back a stored row is refreshed whole, raw prices included, as every
#: ingest always refreshed it: enough to catch a weekend or a short outage in
#: which the ingest did not run, and a vendor's correction of a recent bar.
#: Not how much is refetched. Every ingest refetches each symbol's whole stored
#: span, at least ``REFERENCE_WINDOW_DAYS`` deep (:func:`refetch_start`), which
#: always covers this; an older stored row takes only its new ``adj_close``
#: (:func:`_refresh_bars`), and an older missing one is inserted whole.
INGEST_LOOKBACK_DAYS = 10

#: How many of the stored rows a fetch left behind a warning names. The count
#: is always whole, in the job's result; the names are for a reader.
STALE_ROWS_NAMED = 5

#: Fractional tolerance for a position-quantity mismatch against the venue.
#: Not zero: a venue reports fractional quantities with its own rounding, and
#: a reconciliation that alerts on the ninth decimal place is one that gets
#: muted.
POSITION_TOLERANCE = Decimal("0.000001")

#: Absolute tolerance for a cash mismatch, in dollars. Not a cent: the
#: comparison is cross-time — the previous close's mark against the venue at
#: the next pre-open — and the venue's overnight processing moves cash by a
#: few cents on a margin account (observed: a constant $0.04 on the paper
#: book, every session). A cent-level tolerance therefore alerts daily on
#: noise, and an alert that fires every day is one that gets muted — the same
#: reasoning as POSITION_TOLERANCE above. A real unaccounted cash move is
#: bounded below by the sizer's minimum trade, so a dollar still catches it.
CASH_TOLERANCE = Decimal("1.00")


# ---------------------------------------------------------------------------
# Ingest
# ---------------------------------------------------------------------------


def refetch_start(session: date, first_stored: date | None) -> date:
    """
    Where an ingest of ``session`` starts refetching one symbol.

    The earlier of the symbol's first stored session and ``session -
    REFERENCE_WINDOW_DAYS``: every row already stored is refetched, so all of
    them end on the basis of one fetch, and a symbol with none is backfilled a
    window deep. Never later than :func:`lookback_start`, so a missed session
    is caught at least as far back as it always was.
    """
    start = session - timedelta(days=max(REFERENCE_WINDOW_DAYS, INGEST_LOOKBACK_DAYS))
    if first_stored is not None and first_stored < start:
        return first_stored
    return start


def lookback_start(session: date) -> date:
    """
    The first session an ingest of ``session`` refreshes whole, raw prices
    included: ``INGEST_LOOKBACK_DAYS`` back, the window the live ingest always
    fetched and still falls back to.

    For a symbol the live ingest owns, these rows are that job's alone. The
    session's own close is among them, and it is what the live decision sizes
    its orders from, so the reference job, which the programme enqueues, never
    writes one of them (:func:`_write_spans`).
    """
    return session - timedelta(days=INGEST_LOOKBACK_DAYS)


async def run_ingest_bars(
    conn: asyncpg.Connection,
    payload: dict[str, Any],
    source_factory: Any | None = None,
) -> dict[str, Any]:
    """
    Fetch every deployed universe's bars into ``daily_bars``, on one
    adjustment basis.

    Runs 45 minutes after the close because the free Alpaca tier will not
    return a bar until it is at least 15 minutes old — a job asking for today's
    bar at 16:05 ET gets nothing at all, silently.

    The upsert keys on ``(symbol, session, source)``, so re-running is safe and
    two vendors' views of the same day coexist rather than overwriting each
    other. That is what makes reconciliation possible later.

    One adjustment basis
    ~~~~~~~~~~~~~~~~~~~~
    Yahoo back-adjusts ``Adj Close`` at every distribution, so each fetch
    returns the whole history on the basis of the day it was made. This job
    used to refetch ten days and upsert them, which left every older row on the
    basis of the last day it was fetched: each distribution left a step at the
    ten-day boundary, the steps accumulated, and the stored series drifted from
    any fresh fetch of the same history by roughly the symbol's distribution
    yield a year (an estimate from the yields, not a measurement). A signal the
    live decision read from the table was then not the signal a backtest of the
    same days computed.

    So each symbol it owns is refetched over its whole stored span, from the
    earlier of its first stored session and ``session - REFERENCE_WINDOW_DAYS``
    (:func:`refetch_start`) to its latest stored session or ``session``,
    whichever is later, and written by :func:`_write_spans`: every stored row
    the fetch returns takes that fetch's ``adj_close``, so the adjusted series
    is on one basis even when a late job for an older session runs after a
    newer one, and a symbol with a short history gains a window of it. One
    fetch serves every symbol from the earliest span's start, and what it
    returns before a symbol's own span is dropped, so no symbol's span depends
    on another's. The fetch runs in a thread, as a backtest's does, so the
    lease and the heartbeat keep answering while years download, and the
    writes are one transaction, so no reader sees a series half re-based.

    A stored session in the span that the fetch did not return keeps its older
    basis. It is counted in the result's ``rows_not_refreshed``, with a
    warning, and the job still succeeds: a vendor that has stopped returning a
    session will not return it to a retry either, and the live path is never
    failed over a data-quality condition it did not fail on before. A symbol
    whose session bar the fetch left out is named in ``session_missing``, with
    a warning, and the job succeeds too: the live decision has no close for
    it, as it never had in that case.

    A fetch of the whole span that fails is another matter, because a retry
    can mend it. It is followed by one of the last ``INGEST_LOOKBACK_DAYS``,
    the window this job always fetched, and that is written, so the session's
    bar lands wherever the ten-day ingest landed it and the live decision
    loses nothing. The job then fails, naming the stored rows it could not
    re-base: they keep an older basis, a step at the ten-day boundary is back
    for every distribution since the last whole refetch, and a stored series
    read that day is not one basis. Failing says so where it is seen — the
    jobs page shows the error, and the daily report counts the job once its
    attempts run out — and it is how the worker retries the whole span, so
    ``ingest_bars:{session}`` succeeds only once one fetch has re-based every
    stored row it returns. Only a failure of the ten-day fetch too fails the
    job before anything is written, as a failed fetch always did, and a
    partial fetch stores what came back.

    Raw prices stay as they were written
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    ``daily_bars`` holds raw prices, and Yahoo's ``Close`` is split-adjusted:
    a split rewrites the raw prices of every earlier session in each fetch.
    Only rows inside ``INGEST_LOOKBACK_DAYS`` of the session are refreshed
    whole, raw prices included, as every ingest always refreshed them; any
    other stored row takes only its new ``adj_close`` (:func:`_refresh_bars`),
    so its open, high, low, close and volume stay as first written — which,
    for a row first fetched after an earlier split, are that fetch's
    split-adjusted prices — and the shadow replay, the one reader of old raw
    prices, prices its hypothetical book as it always did, a split repricing
    at most the lookback of it. No money reads an old row in any case: the
    decision sizes its orders and feeds the risk gate from the session's own
    close (``Driver._prices``), a strategy reads history only as
    ``adj_close``, marks come from the venue's account into ``daily_marks``,
    and fills from the venue's orders. ``tests/unit/test_daily_bars_readers.py``
    holds every reader of this table to that account.
    """
    session = _as_date(payload["session"])
    symbols = await _deployed_universe(conn)
    if not symbols:
        logger.info("%s: no enabled deployments; nothing to ingest", session)
        return {
            "session": session.isoformat(),
            "symbols": 0,
            "bars": 0,
            "rows_not_refreshed": 0,
        }

    source = source_factory() if source_factory else _default_source()
    owned = sorted(symbols)
    coverage = await _stored_coverage(conn, source.name, owned, session)
    spans = {
        symbol: refetch_start(
            session, coverage[symbol].first if symbol in coverage else None
        )
        for symbol in owned
    }
    end = _fetch_end(session, coverage.values())
    start = span_start = min(spans.values())
    span_failure: Exception | None = None

    try:
        bars = await _fetch_spans(source, spans, end)
    except Exception as exc:  # noqa: BLE001 - reported, then the old window tried
        # The span always starts before this (refetch_start), so the fallback
        # is a narrower request than the one that failed.
        fallback = lookback_start(session)
        logger.warning(
            "%s: refetching the stored span from %s failed (%s); fetching from "
            "%s, as the ingest always did, and failing the job once that lands",
            session,
            span_start,
            exc,
            fallback,
        )
        try:
            bars = await _fetch_spans(source, dict.fromkeys(owned, fallback), end)
        except Exception as again:  # noqa: BLE001 - reported as a job failure
            logger.error("%s: bar ingest failed: %s", session, again)
            raise
        start, span_failure = fallback, exc

    written = await _write_spans(
        conn,
        source.name,
        bars,
        refresh=spans,
        backfill={},
        session=session,
        end=end,
    )
    if written.left_behind:
        _warn_left_behind(session, written.left_behind)

    missing = [symbol for symbol in owned if (symbol, session) not in written.held]
    if missing:
        # Per symbol, not the newest bar across them: one symbol's bar can be
        # late while another's has landed, and a decision computed from a
        # stale panel is a decision made on the wrong day's prices.
        logger.warning(
            "%s: no bar is stored for %s — today's data is not yet available "
            "for them",
            session,
            ", ".join(missing),
        )

    latest = max((b.session for b in written.refreshed), default=None)
    logger.info(
        "%s: ingested %d new bar(s) for %d symbol(s) from %s, and re-based %d "
        "stored since %s",
        session,
        len(written.added),
        len(symbols),
        source.name,
        len(written.refreshed) - len(written.added),
        start,
    )
    if span_failure is not None:
        raise DataSourceError(
            f"{session.isoformat()}: refetching the stored span from "
            f"{span_start.isoformat()} failed ({span_failure}). The window from "
            f"{start.isoformat()} landed, as the ingest always fetched it, with "
            f"{len(written.added)} new bar(s); {len(written.left_behind)} stored "
            "row(s) it did not return keep an older adjustment basis, so the "
            "job fails for the worker to refetch the whole span"
        )
    return {
        "session": session.isoformat(),
        "symbols": len(symbols),
        # Every bar written: the new ones and the stored span they re-based.
        # ``new_bars`` is how many sessions the table did not hold before.
        "bars": len(written.refreshed),
        "new_bars": len(written.added),
        "source": source.name,
        "latest_session": latest.isoformat() if latest else None,
        "session_missing": missing,
        "refetched_from": start.isoformat(),
        "rows_not_refreshed": len(written.left_behind),
    }


# ---------------------------------------------------------------------------
# Reference bars
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ReferencePlan:
    """
    What one reference job does with each reference symbol.

    ``upsert`` maps each symbol no live deployment trades to the start of its
    span, refetched whole and written as the live ingest writes its own
    (:func:`_write_spans`). ``backfill`` maps each symbol the live ingest owns
    and that is short of history to the start of the window, inserted without
    overwriting a stored row and ending before the live ingest's lookback
    (:func:`lookback_start`), whose rows are that job's alone. ``untouched``
    is every symbol the live ingest owns that has its history, which the job
    leaves wholly to the live ingest: it is not even fetched.
    """

    upsert: Mapping[str, date]
    backfill: Mapping[str, date]
    untouched: tuple[str, ...]

    @property
    def symbols(self) -> tuple[str, ...]:
        """What the one fetch asks for."""
        return tuple(sorted({*self.upsert, *self.backfill}))

    @property
    def start(self) -> date | None:
        """The first session the one fetch asks for."""
        starts = [*self.upsert.values(), *self.backfill.values()]
        return min(starts) if starts else None


def plan_reference_bars(
    session: date,
    *,
    deployed: Iterable[str],
    first_stored: Mapping[str, date],
    stored_rows: Mapping[str, int],
) -> ReferencePlan:
    """
    Decide what the reference job does with each of ``REFERENCE_SYMBOLS``.

    ``deployed`` is the live ingest's universe — every symbol an enabled
    operator deployment trades, which is what makes a symbol the live
    ingest's — ``first_stored`` each symbol's first stored session under the
    reference source, and ``stored_rows`` its stored rows up to ``session``.
    Only the reference symbols are ever planned, whatever else is deployed or
    stored, and a symbol the live ingest owns is never upserted. Pure, so the
    rule is tested without a database.
    """
    owned = set(deployed)
    upsert: dict[str, date] = {}
    backfill: dict[str, date] = {}
    untouched: list[str] = []
    for symbol in REFERENCE_SYMBOLS:
        if symbol not in owned:
            upsert[symbol] = refetch_start(session, first_stored.get(symbol))
        elif stored_rows.get(symbol, 0) < REFERENCE_MIN_ROWS:
            backfill[symbol] = session - timedelta(days=REFERENCE_WINDOW_DAYS)
        else:
            untouched.append(symbol)
    return ReferencePlan(
        upsert=MappingProxyType(upsert),
        backfill=MappingProxyType(backfill),
        untouched=tuple(untouched),
    )


async def run_ingest_reference_bars(
    conn: asyncpg.Connection,
    payload: dict[str, Any],
    source_factory: Any | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """
    Keep the reference sleeves' history in ``daily_bars``, for the forward
    clock.

    Enqueued by the AI programme's planner (``jev_plan``, from phase C4), and
    never by the session planner, so it is absent from ``SCHEDULED_KINDS``; it reaches
    no venue, so it is not kill-gated, as ``ingest_bars`` is not; and it is the
    worker's, so the API cannot drain it. Its queue priority,
    ``REFERENCE_PRIORITY``, orders it behind every kind on the live path when
    both are due; it does not preempt a job already running, so the planner
    schedules it no earlier than ``ingest_bars``.

    The payload names a session, which must be an NYSE session, and nothing
    else in it is read. The symbols are ``REFERENCE_SYMBOLS``: a symbol list in
    a payload is ignored, so no job row chooses which instruments the worker
    fetches. Nor does its session choose when or how far back: the job runs
    only inside :func:`reference_window`, from the session's close plus
    ``INGEST_AFTER_CLOSE``, when the live ingest fetches the same bars, until
    the next session's bars settle, and is refused outside it by the
    database's clock (``now`` is a test seam). Earlier, the vendor has only the
    session in progress, or nothing, to give as its close. Later, the
    session's forward-clock cutoff has passed, the next session's job
    refetches everything this one would, and a stale session would count a
    sleeve's history only up to itself and backfill years in front of the live
    ingest's first row, moving where that job's span starts for good.

    A reference symbol no live deployment trades is refetched over its whole
    stored span, as the live ingest refetches its own (:func:`refetch_start`),
    and written as the live ingest writes (:func:`_write_spans`), so every
    stored row ends on one adjustment basis and a regime state recorded from
    the table recomputes from it later, whatever has been distributed since. A
    stored session the fetch omits is counted in ``rows_not_refreshed``, as the
    live ingest counts it.

    A symbol an enabled operator deployment trades is the live ingest's, and
    this job never overwrites a row of it. With fewer than
    ``REFERENCE_MIN_ROWS`` rows up to the session, its window is fetched and
    inserted with ``ON CONFLICT DO NOTHING``, which fills gaps and changes
    nothing stored, and the window ends before the live ingest's lookback
    (:func:`lookback_start`): those rows, the session's close among them, are
    what the live decision sizes its orders from, and a job the programme
    enqueues writes none of them. Otherwise the symbol is not fetched at all.
    The live ingest re-bases whatever was filled on its next whole refetch,
    since its span starts at the first stored session. Ownership is read again
    inside the transaction that writes, so a deployment enabled while years
    downloaded takes its sleeve back before any row of it is written; the
    result names it in ``taken_back``. Ownership follows the live ingest, which
    fetches only what enabled deployments trade, so a sleeve is always exactly
    one job's: disabling the last deployment that trades it hands it to this
    one, which refetches its whole span and writes it by the live ingest's own
    rules, and enabling one hands it back to the live ingest, whose next run
    re-bases the whole span again.

    One fetch serves every symbol that needs one, in a thread, and both writes
    are one transaction. A failed fetch raises, so the worker retries the job:
    nothing on the live path waits on this one, so it has no fallback. The job
    exists to put its session's close in the table for every sleeve, so it
    fails, after committing what landed, while any sleeve is without one,
    naming each and whose bar it is: the vendor's, which a retry can fetch, or
    the live ingest's, which this job never writes. A symbol the fetch
    returned nothing for is named in ``returned_nothing``. The result holds
    counts and symbols, never a price.
    """
    session = _reference_session(payload)
    source = source_factory() if source_factory else _default_source()
    if source.name != REFERENCE_SOURCE:
        raise ValueError(
            f"the reference bars are kept under {REFERENCE_SOURCE!r}, the only "
            f"source the forward clock reads; rows under {source.name!r} would "
            "be read by nothing"
        )
    _refuse_outside_the_window(
        session, now if now is not None else await _database_now(conn)
    )

    deployed = await _deployed_universe(conn)
    coverage = await _stored_coverage(conn, source.name, REFERENCE_SYMBOLS, session)
    plan = plan_reference_bars(
        session,
        deployed=deployed,
        first_stored={symbol: c.first for symbol, c in coverage.items()},
        stored_rows={symbol: c.rows for symbol, c in coverage.items()},
    )
    result: dict[str, Any] = {
        "session": session.isoformat(),
        "source": source.name,
        "upserted": {},
        "backfilled": {},
        "untouched": list(plan.untouched),
        "taken_back": [],
        "returned_nothing": [],
        "rows_not_refreshed": 0,
        "latest_session": None,
    }
    held = {(symbol, session) for symbol, c in coverage.items() if c.has_session}
    if plan.start is None:
        logger.info(
            "%s: every reference symbol is the live ingest's and has its "
            "history; nothing to fetch",
            session,
        )
        _require_every_close(session, held, live_owned=deployed)
        return result

    end = _fetch_end(
        session, [coverage[symbol] for symbol in plan.upsert if symbol in coverage]
    )
    try:
        bars = await _fetch_spans(source, {**plan.upsert, **plan.backfill}, end)
    except Exception as exc:  # noqa: BLE001 - reported as a job failure
        logger.error("%s: reference bar ingest failed: %s", session, exc)
        raise

    written = await _write_spans(
        conn,
        source.name,
        bars,
        refresh=plan.upsert,
        backfill=plan.backfill,
        session=session,
        end=end,
        live_universe=_deployed_universe,
    )
    if written.left_behind:
        _warn_left_behind(session, written.left_behind)
    if written.taken_back:
        logger.warning(
            "%s: %s became the live ingest's while the fetch ran; left to it",
            session,
            ", ".join(written.taken_back),
        )

    returned = {bar.symbol for bar in bars}
    nothing = [symbol for symbol in plan.symbols if symbol not in returned]
    if nothing:
        logger.warning(
            "%s: the reference fetch returned nothing for %s",
            session,
            ", ".join(nothing),
        )
    kept = [*written.refreshed, *written.backfill_window]
    latest = max((b.session for b in kept), default=None)

    refreshed = Counter(b.symbol for b in written.refreshed)
    filled = Counter(b.symbol for b in written.backfilled)
    result.update(
        upserted={
            symbol: refreshed[symbol]
            for symbol in sorted(plan.upsert)
            if symbol not in written.taken_back
        },
        backfilled={symbol: filled[symbol] for symbol in sorted(plan.backfill)},
        taken_back=list(written.taken_back),
        returned_nothing=nothing,
        rows_not_refreshed=len(written.left_behind),
        latest_session=latest.isoformat() if latest else None,
    )
    logger.info(
        "%s: reference bars from %s: upserted %s, backfilled %s, untouched %s",
        session,
        source.name,
        result["upserted"],
        result["backfilled"],
        result["untouched"],
    )
    _require_every_close(
        session, held | written.held, live_owned=deployed | set(written.taken_back)
    )
    return result


def _reference_session(payload: Mapping[str, Any]) -> date:
    """
    The one thing a reference job's payload says: which NYSE session.

    Every other key is ignored, a symbol list included. A day that is not a
    session is refused rather than fetched for: the job exists to put that
    session's close in the table, and no such close exists. When the job may
    run for it is :func:`reference_window`'s to say.
    """
    session = _as_date(payload["session"])
    first, last = bounds()
    if not first <= session <= last or not is_session(session):
        raise ValueError(
            f"{session.isoformat()} is not an NYSE session the calendar can "
            "answer for, and the reference bars are kept per session"
        )
    return session


def reference_window(session: date) -> tuple[datetime, datetime | None]:
    """
    When a reference job for ``session`` may run, as UTC instants.

    From the moment its bars settle, its close plus ``INGEST_AFTER_CLOSE``,
    which is when the live ingest fetches the same bars, so both jobs read the
    vendor's settled day; until the next session's bars settle, when that
    session's job supersedes this one, or without end on the calendar's last
    session. Both bounds come from the calendar, so an early close and
    daylight saving move them as they move the live ingest.
    """
    settles = session_close(session) + INGEST_AFTER_CLOSE
    if session >= bounds()[1]:
        return settles, None
    return settles, session_close(next_session(session)) + INGEST_AFTER_CLOSE


def _refuse_outside_the_window(session: date, now: datetime) -> None:
    """Refuse a job run outside :func:`reference_window`, before anything is read."""
    settles, superseded = reference_window(session)
    at = now.astimezone(UTC)
    if at < settles:
        delay = int(INGEST_AFTER_CLOSE.total_seconds() // 60)
        raise ValueError(
            f"{session.isoformat()}'s bars settle at {settles:%Y-%m-%d %H:%M} UTC, "
            f"its close plus {delay} minutes, when the live ingest fetches them; "
            f"this job ran at {at:%Y-%m-%d %H:%M:%S} UTC, when the vendor has "
            "only the session in progress, or nothing, to give as its close"
        )
    if superseded is not None and at >= superseded:
        raise ValueError(
            f"the reference job for {session.isoformat()} is superseded: the next "
            f"session's bars settled at {superseded:%Y-%m-%d %H:%M} UTC, and its "
            "job refetches everything this one would, while a stale session "
            "would count a sleeve's history only up to itself and choose how far "
            "back a backfill reaches"
        )


async def _database_now(conn: asyncpg.Connection) -> datetime:
    """
    The database's clock, which is the clock that released the job: the queue
    claims a row once ``scheduled_for <= NOW()``. A job the planner schedules
    at the moment its bars settle is therefore never refused over two
    machines' clocks disagreeing.
    """
    return await conn.fetchval("SELECT clock_timestamp()")


def _require_every_close(
    session: date, held: Iterable[tuple[str, date]], *, live_owned: Iterable[str]
) -> None:
    """
    Fail the job while any sleeve has no close stored for ``session``.

    Raised after the writes commit, so what landed stays, and the worker
    retries: the vendor's bar may land yet, and so may a live ingest's retry.
    The error names each sleeve and whose bar it is.
    """
    stored = set(held)
    owned = set(live_owned)
    missing = [s for s in REFERENCE_SYMBOLS if (s, session) not in stored]
    if not missing:
        return
    sleeve = {symbol: name for name, symbol in REFERENCE_SLEEVES.items()}
    reasons = [
        f"{symbol} ({sleeve[symbol]}), "
        + (
            "the live ingest's: an enabled deployment trades it, and this job "
            "writes none of its bars inside the live ingest's lookback"
            if symbol in owned
            else "which the vendor did not return"
        )
        for symbol in missing
    ]
    raise DataSourceError(
        f"{session.isoformat()}: no close is stored for " + "; ".join(reasons)
        + ". The job exists to put the session's close in the table for every "
        "sleeve, so it fails, keeping what it wrote, for the worker to retry it"
    )


# ---------------------------------------------------------------------------
# Fetching and writing a span, shared by both ingests
# ---------------------------------------------------------------------------


class _Coverage(NamedTuple):
    """What is stored of one symbol under one source."""

    #: The first stored session.
    first: date
    #: The latest stored session.
    last: date
    #: Rows stored up to the job's session.
    rows: int
    #: Whether the job's session itself is stored.
    has_session: bool


@dataclass(frozen=True, slots=True)
class _Written:
    """What one write of fetched spans did."""

    #: The bars written into the refreshed spans.
    refreshed: list[Bar]
    #: Of those, the sessions that were not stored yet: what the fetch added,
    #: as against the years it re-based.
    added: list[Bar]
    #: The bars the backfill window returned, stored or not.
    backfill_window: list[Bar]
    #: Of those, the sessions that were missing when the job read the table.
    #: Another worker's live ingest could fill one first, when ``DO NOTHING``
    #: skips it and this is one too many; no stored row changes either way.
    backfilled: list[Bar]
    #: Stored rows in the refreshed spans that the fetch did not return.
    left_behind: list[tuple[str, date]]
    #: Every ``(symbol, session)`` the written spans hold once the write
    #: commits: what they held before, and what the write sent. Rows are never
    #: deleted, so another writer can only add to it.
    held: frozenset[tuple[str, date]]
    #: Symbols dropped from the refresh because the live ingest had come to
    #: own them by the time of the write.
    taken_back: tuple[str, ...]


def _fetch_end(session: date, coverage: Iterable[_Coverage]) -> date:
    """
    Where a refetch ends: the job's session, or the latest stored session when
    a newer job has already written one, so that every stored row of the span
    is refetched, not only those up to this job's session.
    """
    return max([session, *(c.last for c in coverage)])


async def _fetch_spans(source: Any, spans: Mapping[str, date], end: date) -> list[Bar]:
    """
    One fetch for every span, from the earliest start, in a thread.

    The vendor call blocks. Run on the event loop it would stall the lease and
    the heartbeat for as long as years take to download, as a backtest's data
    would, which is why a backtest's runs in a thread too.
    ``test_reference_bars.py::test_the_fetch_leaves_the_event_loop_free`` holds
    it.
    """
    return list(
        await asyncio.to_thread(source.fetch, sorted(spans), min(spans.values()), end)
    )


async def _write_spans(
    conn: asyncpg.Connection,
    source_name: str,
    bars: Iterable[Bar],
    *,
    refresh: Mapping[str, date],
    backfill: Mapping[str, date],
    session: date,
    end: date,
    live_universe: Callable[[asyncpg.Connection], Awaitable[set[str]]] | None = None,
) -> _Written:
    """
    Write what a fetch returned, in one transaction.

    ``refresh`` maps each symbol whose span is refreshed to its start (to
    ``end``), through :func:`_refresh_bars`; ``backfill`` maps each symbol that
    is only to have gaps filled to its window's start, through
    :func:`_insert_missing_bars`. A backfilled symbol is one the live ingest
    owns, so its window ends the day before :func:`lookback_start`: the rows
    the live ingest refreshes whole, the session's close among them, are that
    job's alone. What the fetch returned outside those spans is dropped.

    ``live_universe``, when given, is read first, inside the transaction, and
    a symbol it names is dropped from ``refresh``: the reference job's rule
    that it never overwrites a symbol the live ingest owns is judged when it
    writes, not when it planned, before years downloaded. The stored keys are
    read inside the same transaction, so the rows left behind are counted
    against what the writes met. Nothing a reader can see changes until every
    statement has run, so a failure part-way leaves every stored row as it
    was: ``tests/integration/test_reference_bars.py::TestOneTransaction``.
    """
    bars = list(bars)
    async with conn.transaction():
        taken_back: tuple[str, ...] = ()
        if live_universe is not None:
            owned = await live_universe(conn)
            taken_back = tuple(sorted(set(refresh) & owned))
            refresh = {s: start for s, start in refresh.items() if s not in owned}
        refreshed = _in_spans(bars, refresh, end)
        window = _in_spans(
            bars, backfill, lookback_start(session) - timedelta(days=1)
        )
        stored = await _stored_keys(conn, source_name, {**refresh, **backfill}, end)
        await _refresh_bars(conn, source_name, refreshed, session)
        # Every row the window returned, not only the missing ones: ON
        # CONFLICT DO NOTHING is what keeps a stored row as the live ingest
        # wrote it, and the test that proves it drives this with the rows
        # that collide.
        await _insert_missing_bars(conn, source_name, window)
    sent = {(b.symbol, b.session) for b in (*refreshed, *window)}
    return _Written(
        refreshed=refreshed,
        added=[b for b in refreshed if (b.symbol, b.session) not in stored],
        backfill_window=window,
        backfilled=[b for b in window if (b.symbol, b.session) not in stored],
        left_behind=_left_behind(
            {key for key in stored if key[0] in refresh}, refreshed
        ),
        held=frozenset(stored | sent),
        taken_back=taken_back,
    )


def _in_spans(
    bars: Iterable[Bar], spans: Mapping[str, date], end: date
) -> list[Bar]:
    """The bars each symbol's span asked for, and nothing a wider fetch added."""
    return [
        bar
        for bar in bars
        if bar.symbol in spans and spans[bar.symbol] <= bar.session <= end
    ]


def _left_behind(
    stored: Iterable[tuple[str, date]], fetched: Iterable[Bar]
) -> list[tuple[str, date]]:
    """Stored rows a fetch of their span did not return, in order."""
    returned = {(bar.symbol, bar.session) for bar in fetched}
    return sorted(key for key in stored if key not in returned)


def _warn_left_behind(session: date, stale: list[tuple[str, date]]) -> None:
    named = ", ".join(f"{symbol} {day}" for symbol, day in stale[:STALE_ROWS_NAMED])
    more = len(stale) - STALE_ROWS_NAMED
    logger.warning(
        "%s: %d stored row(s) the fetch did not return keep an older "
        "adjustment basis: %s%s",
        session,
        len(stale),
        named,
        f" and {more} more" if more > 0 else "",
    )


async def _stored_coverage(
    conn: asyncpg.Connection,
    source_name: str,
    symbols: Iterable[str],
    session: date,
) -> dict[str, _Coverage]:
    """
    Each symbol's first and latest stored session, its rows up to ``session``,
    and whether ``session`` itself is stored.
    """
    rows = await conn.fetch(
        """
        SELECT symbol, MIN(session) AS first_session,
               MAX(session) AS last_session,
               COUNT(*) FILTER (WHERE session <= $3) AS rows_to_session,
               bool_or(session = $3) AS has_session
        FROM daily_bars
        WHERE source = $1 AND symbol = ANY($2::text[])
        GROUP BY symbol
        """,
        source_name,
        sorted(symbols),
        session,
    )
    return {
        row["symbol"]: _Coverage(
            first=row["first_session"],
            last=row["last_session"],
            rows=int(row["rows_to_session"]),
            has_session=bool(row["has_session"]),
        )
        for row in rows
    }


async def _stored_keys(
    conn: asyncpg.Connection,
    source_name: str,
    spans: Mapping[str, date],
    end: date,
) -> set[tuple[str, date]]:
    """The stored ``(symbol, session)`` pairs inside each symbol's span."""
    if not spans:
        return set()
    rows = await conn.fetch(
        """
        SELECT symbol, session FROM daily_bars
        WHERE source = $1 AND symbol = ANY($2::text[])
          AND session >= $3 AND session <= $4
        """,
        source_name,
        sorted(spans),
        min(spans.values()),
        end,
    )
    return {
        (row["symbol"], row["session"])
        for row in rows
        if row["session"] >= spans[row["symbol"]]
    }


def _bar_rows(source_name: str, bars: Iterable[Bar]) -> list[tuple[Any, ...]]:
    """Rows in ``(symbol, session)`` order, so every writer locks in one order."""
    return [
        (
            b.symbol, b.session, source_name, b.open, b.high, b.low,
            b.close, b.volume, b.adj_close,
        )
        for b in sorted(bars, key=lambda bar: (bar.symbol, bar.session))
    ]


async def _refresh_bars(
    conn: asyncpg.Connection, source_name: str, bars: Iterable[Bar], session: date
) -> None:
    """
    Write a refetched span: its adjusted closes everywhere, its raw prices only
    where they were always refreshed.

    A session from :func:`lookback_start` up to and including ``session`` is
    replaced whole, as every ingest has always replaced it, so a vendor's
    correction of a recent bar lands. Any other session already stored takes
    only its new ``adj_close``, which is what puts the adjusted series on one
    basis; its raw open, high, low, close and volume stay as first written, so
    a split after the fact, which Yahoo folds into ``Close``, reprices what the
    shadow replay reads only inside the lookback, as it always did. The ratio
    of an old row's adjusted close to its raw close is therefore no adjustment
    factor after a split, and nothing reads it as one. A session not yet
    stored is inserted whole, on the split basis of the day it is fetched: a
    row first written after a split holds the vendor's split-adjusted raw
    prices, and a gap older than the lookback, filled after a split, sits on
    another raw basis than the rows either side of it, which the ten-day
    ingest never filled at all.

    A row whose values the fetch repeats is left alone rather than rewritten:
    each ingest refetches years, and on a day with no distribution nearly all
    of it is unchanged, so rewriting it would churn a new version of every row
    every session for nothing. One statement, in ``(symbol, session)`` order,
    so two workers refreshing overlapping spans lock rows in one order and
    cannot deadlock each other.
    """
    recent_from = lookback_start(session)
    rows = [
        (*row, recent_from <= row[1] <= session)
        for row in _bar_rows(source_name, bars)
    ]
    await conn.executemany(
        """
        INSERT INTO daily_bars AS stored (symbol, session, source, open, high,
                                          low, close, volume, adj_close)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
        ON CONFLICT (symbol, session, source) DO UPDATE SET
            open = CASE WHEN $10 THEN EXCLUDED.open ELSE stored.open END,
            high = CASE WHEN $10 THEN EXCLUDED.high ELSE stored.high END,
            low = CASE WHEN $10 THEN EXCLUDED.low ELSE stored.low END,
            close = CASE WHEN $10 THEN EXCLUDED.close ELSE stored.close END,
            volume = CASE WHEN $10 THEN EXCLUDED.volume ELSE stored.volume END,
            adj_close = EXCLUDED.adj_close
        WHERE stored.adj_close IS DISTINCT FROM EXCLUDED.adj_close
           OR ($10 AND (stored.open, stored.high, stored.low, stored.close,
                        stored.volume)
                       IS DISTINCT FROM
                       (EXCLUDED.open, EXCLUDED.high, EXCLUDED.low,
                        EXCLUDED.close, EXCLUDED.volume))
        """,
        rows,
    )


async def _insert_missing_bars(
    conn: asyncpg.Connection, source_name: str, bars: Iterable[Bar]
) -> None:
    """Write each bar whose session is not stored, and change nothing that is."""
    await conn.executemany(
        """
        INSERT INTO daily_bars (symbol, session, source, open, high, low,
                                close, volume, adj_close)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
        ON CONFLICT (symbol, session, source) DO NOTHING
        """,
        _bar_rows(source_name, bars),
    )


# ---------------------------------------------------------------------------
# Marks
# ---------------------------------------------------------------------------


async def run_eod_marks(
    conn: asyncpg.Connection,
    payload: dict[str, Any],
    broker_factory: Any | None = None,
) -> dict[str, Any]:
    """
    Mark the book to the close and record the session's P&L.

    ``daily_marks`` is written by the decision job too, but only on sessions
    that decide. This runs every session, so the equity curve stays continuous
    and — because the risk gate measures drawdown against ``MAX(equity)`` from
    this table — a peak reached on a non-rebalance day is not forgotten.
    """
    session = _as_date(payload["session"])
    deployments = await _enabled_deployment_rows(conn)
    if not deployments:
        logger.info("%s: no enabled deployments; nothing to mark", session)
        return {"session": session.isoformat(), "marks": 0}

    written = []
    for deployment in deployments:
        mode = deployment["mode"]
        broker = _broker_for(deployment, broker_factory)
        async with _maybe_context(broker):
            account = await broker.get_account()

        mark = await marks.record_mark(
            conn, session, account.equity, account.cash, mode=mode
        )
        written.append(mode)
        logger.info(
            "%s [%s]: equity %s, daily P&L %s, drawdown %.2f%%",
            session, mode, account.equity, mark["daily_pnl"],
            float(mark["drawdown_pct"]) * 100,
        )

    return {"session": session.isoformat(), "marks": len(written)}


# ---------------------------------------------------------------------------
# Reconcile
# ---------------------------------------------------------------------------


async def run_reconcile(
    conn: asyncpg.Connection,
    payload: dict[str, Any],
    broker_factory: Any | None = None,
) -> dict[str, Any]:
    """
    Compare our recorded positions against the venue's, before the open.

    Runs first in the session for a reason: acting on a ledger that disagrees
    with the broker is how a small bookkeeping error becomes a real position.
    Discrepancies are reported and recorded, never silently corrected — an
    automatic "fix" that trades to make the books agree is exactly the runaway
    this is meant to catch.
    """
    session = _as_date(payload["session"])
    deployments = await _enabled_deployment_rows(conn)
    if not deployments:
        return {"session": session.isoformat(), "checked": 0, "mismatches": []}

    mismatches: list[dict[str, Any]] = []
    checked = 0

    for deployment in deployments:
        mode = deployment["mode"]
        broker = _broker_for(deployment, broker_factory)
        async with _maybe_context(broker):
            await _sync_orders(conn, deployment["id"], broker)
            account = await broker.get_account()
            venue_positions = await broker.get_positions()

        ours = await _recorded_positions(conn, deployment["id"])
        checked += 1

        for symbol in sorted(set(ours) | set(venue_positions)):
            theirs = (
                venue_positions[symbol].qty
                if symbol in venue_positions
                else Decimal("0")
            )
            mine = ours.get(symbol, Decimal("0"))
            if abs(theirs - mine) > POSITION_TOLERANCE:
                mismatches.append(
                    {
                        "deployment_id": str(deployment["id"]),
                        "kind": "position",
                        "symbol": symbol,
                        "ours": str(mine),
                        "venue": str(theirs),
                    }
                )

        last_mark = await conn.fetchrow(
            "SELECT cash FROM daily_marks WHERE mode = $1 "
            "AND session < $2 ORDER BY session DESC LIMIT 1",
            mode,
            session,
        )
        if last_mark is not None:
            drift = abs(Decimal(last_mark["cash"]) - account.cash)
            if drift > CASH_TOLERANCE:
                mismatches.append(
                    {
                        "deployment_id": str(deployment["id"]),
                        "kind": "cash",
                        "ours": str(Decimal(last_mark["cash"])),
                        "venue": str(account.cash),
                        "drift": str(drift),
                    }
                )

    if mismatches:
        # Loud, and written to the audit log: this is the signal that the
        # backtest's model of the account has diverged from the account.
        logger.error(
            "%s: reconciliation found %d mismatch(es): %s",
            session, len(mismatches), mismatches,
        )
        await conn.execute(
            "INSERT INTO audit_log (actor, action, entity_type, detail) "
            "VALUES ('worker', 'reconciliation_mismatch', 'system', $1::jsonb)",
            _json(mismatches),
        )
    else:
        logger.info("%s: reconciliation clean across %d deployment(s)",
                    session, checked)

    return {
        "session": session.isoformat(),
        "checked": checked,
        "mismatches": mismatches,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _json(value: Any) -> str:
    import json

    return json.dumps(value, default=str)


async def _deployed_universe(conn: asyncpg.Connection) -> set[str]:
    """Every symbol any enabled deployment needs."""
    symbols: set[str] = set()
    for row in await _enabled_deployment_rows(conn):
        params = row["params"]
        if isinstance(params, str):
            import json

            params = json.loads(params)
        strategy = build_strategy(row["strategy_name"], params or {})
        symbols.update(strategy.universe())
    return symbols


async def _enabled_deployment_rows(conn: asyncpg.Connection) -> list[Any]:
    # The same owner filter as ``live_job._enabled_deployments``, for the same
    # reason: marks and reconciliation are the operator's account, and a row
    # that the live loop will not trade must not be marked or reconciled as
    # though it were.
    return await conn.fetch(
        "SELECT id, strategy_name, params, mode FROM deployments "
        "WHERE status = 'enabled' AND owner_id = $1 ORDER BY created_at",
        marks.DEFAULT_OWNER,
    )


async def _recorded_positions(
    conn: asyncpg.Connection, deployment_id: Any
) -> dict[str, Decimal]:
    """
    Net position per symbol implied by the fills we recorded.

    Derived from fills rather than read from a positions table, because the
    fills are the primitive: a snapshot table can drift from them, and if it
    has, that is itself the thing worth discovering.
    """
    rows = await conn.fetch(
        """
        SELECT o.symbol,
               SUM(CASE WHEN o.side = 'buy' THEN f.qty ELSE -f.qty END) AS qty
        FROM fills f
        JOIN orders o ON o.id = f.order_id
        WHERE o.deployment_id = $1
        GROUP BY o.symbol
        """,
        deployment_id,
    )
    return {
        r["symbol"]: Decimal(r["qty"])
        for r in rows
        if r["qty"] is not None and abs(Decimal(r["qty"])) > POSITION_TOLERANCE
    }


async def _sync_orders(
    conn: asyncpg.Connection, deployment_id: Any, broker: Any
) -> None:
    rows = await conn.fetch(
        "SELECT id, broker_order_id FROM orders "
        "WHERE deployment_id = $1 AND broker_order_id IS NOT NULL "
        "AND status IN ('pending', 'submitted', 'partially_filled')",
        deployment_id,
    )
    for row in rows:
        status = await broker.get_order(row["broker_order_id"])
        async with conn.transaction():
            await conn.execute(
                "UPDATE orders SET status = $2, updated_at = NOW() WHERE id = $1",
                row["id"],
                status.state.value,
            )
            if status.fills:
                fill = status.fills[0]
                await conn.execute("DELETE FROM fills WHERE order_id = $1", row["id"])
                await conn.execute(
                    """
                    INSERT INTO fills (id, order_id, symbol, side, qty, price,
                                       commission, filled_at)
                    VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
                    """,
                    uuid.uuid4(),
                    row["id"],
                    fill.symbol,
                    fill.side.value,
                    fill.qty,
                    fill.price,
                    fill.commission,
                    fill.filled_at,
                )


def _default_source() -> Any:
    from src.data import YFinanceSource

    return YFinanceSource()


def _broker_for(deployment: Any, broker_factory: Any | None) -> Any:
    if broker_factory is not None:
        return broker_factory()
    from src.worker.live_job import _alpaca_from_env

    return _alpaca_from_env({"mode": deployment["mode"]})


class _NullContext:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *exc: object) -> None:
        return None


def _maybe_context(broker: Any) -> Any:
    return broker if hasattr(broker, "__aenter__") else _NullContext()


def _as_date(value: Any) -> date:
    from datetime import datetime

    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    return date.fromisoformat(str(value))


__all__ = [
    "INGEST_LOOKBACK_DAYS",
    "ReferencePlan",
    "lookback_start",
    "plan_reference_bars",
    "refetch_start",
    "reference_window",
    "run_eod_marks",
    "run_ingest_bars",
    "run_ingest_reference_bars",
    "run_reconcile",
]
