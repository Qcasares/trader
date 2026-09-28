"""
jev_clock.py
------------
When the forward clock runs, what it records a session under, and the prices
it reads. Holds no client: the planner, the forward job and the evaluation
harness all read it, and the harness may reach nothing that can call a model
(``tests/unit/test_import_boundaries.py::test_the_harness_holds_no_key_and_reaches_no_client``).

Three times after each close, all read from the calendar
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
* **Close + 45 minutes**, :data:`REFERENCE_AFTER_CLOSE`: the worker's
  reference bars are fetched, the minute the live ingest fetches the same
  bars (``scheduler.INGEST_AFTER_CLOSE``), since before it the vendor has only
  the session in progress to give as its close.
* **Close + 50 minutes**, :data:`COLLECT_AFTER_CLOSE`: the regime is asked.
* **Close + 60 minutes**, :data:`DECISION_AFTER_CLOSE`: the decision cutoff,
  the moment the live decision reads the day's close
  (``scheduler.DECIDE_AFTER_CLOSE``). An answer recorded after it is
  backfilled, which the database decides from its own stamp, and nothing is
  asked about a session once the database's clock has reached it.

The programme may not import ``src.engine``, whose package reaches the code
that fills an order, so the two scheduler constants are restated here and
``tests/unit/test_jev_clock.py`` holds them equal: a cutoff that drifted from
the decision it serves would record as live an answer the decision could not
have read. Phase F moves the cutoff into ``src/core``, where the signals reader
will compute it too (docs/08 open item 26).

Every time comes from ``calendar.session_close``, so an early close moves all
three with it, and daylight saving does too: the cutoff is 17:00 New York time
on an ordinary day and 14:00 on a half day, always on the session's own New
York day, which is what ``jev_signals_cutoff_is_on_its_session`` requires.

The names a session is recorded under
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
The regime state holds labels and no tickers, so which instruments stand for
the sleeves is recorded beside the answer, never in it: a signal's ``symbol``
is :func:`sleeve_symbol`, ``equities=SPY;bonds=IEF;commodities=GSG``, and a
changed sleeve starts a new series. Its ``signal`` is the set, its version and
the question, ``decision.regime@1:regime``, so a version bump starts one too.

The prices
~~~~~~~~~~
:func:`load_regime_panel` reads the reference sleeves' adjusted closes under
``REFERENCE_SOURCE`` alone, dated on or before the session and no more than
``REFERENCE_WINDOW_DAYS`` before it: one vendor's idea of a price, never
stitched to another's, and never a bar from after the session. It reads the
adjusted close and nothing else, so no raw price reaches a regime state
(``tests/unit/test_daily_bars_readers.py`` holds the account of what it
reads). The programme reads ``daily_bars`` and never writes it: the worker's
``ingest_reference_bars`` does, when the planner enqueues it.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import asyncpg

from src.core import calendar
from src.core.panel import PricePanel
from src.data.reference import (
    REFERENCE_SLEEVES,
    REFERENCE_SOURCE,
    REFERENCE_SYMBOLS,
    REFERENCE_WINDOW_DAYS,
)
from src.programme.jev_questions import SLEEVES, QuestionSet

#: The exchange's own timezone: which session "today" is, and the day a
#: cutoff must fall on.
EXCHANGE_TZ = ZoneInfo("America/New_York")

#: When the worker fetches the reference bars for a session: its close plus
#: this. Equal to ``src/engine/scheduler.INGEST_AFTER_CLOSE``, by test.
REFERENCE_AFTER_CLOSE = timedelta(minutes=45)

#: When the regime is asked: after the bars have settled and before the
#: cutoff, with ten minutes for a late bar or a retry.
COLLECT_AFTER_CLOSE = timedelta(minutes=50)

#: The decision cutoff: the close plus this. Equal to
#: ``src/engine/scheduler.DECIDE_AFTER_CLOSE``, by test.
DECISION_AFTER_CLOSE = timedelta(minutes=60)

#: The worker's live ingest's job key prefix, ``scheduling.dedupe_key``'s
#: ``{kind}:{session}``; ``tests/unit/test_jev_clock.py`` holds the two to one
#: spelling.
INGEST_KIND = "ingest_bars"

#: The reference job's kind, owned by the worker.
REFERENCE_KIND = "ingest_reference_bars"

#: The forward clock's kind, owned by the programme.
REGIME_KIND = "jev_regime"


# ---------------------------------------------------------------------------
# Times
# ---------------------------------------------------------------------------


def decision_cutoff(session: date) -> datetime:
    """The decision cutoff for ``session``: its close plus an hour, in UTC."""
    return calendar.session_close(session) + DECISION_AFTER_CLOSE


def collect_at(session: date) -> datetime:
    """When the regime for ``session`` is asked: its close plus 50 minutes."""
    return calendar.session_close(session) + COLLECT_AFTER_CLOSE


def reference_at(session: date) -> datetime:
    """When the reference bars for ``session`` are fetched: its close plus 45."""
    return calendar.session_close(session) + REFERENCE_AFTER_CLOSE


def regime_as_of(session: date) -> datetime:
    """The instant a regime state describes: the session's close."""
    return calendar.session_close(session)


def sessions_to_plan(now: datetime) -> list[date]:
    """
    The sessions the planner schedules work for at ``now``: today's New York
    session while its cutoff is still ahead, and the next session.

    Never a session whose cutoff has passed, so the planner never builds a
    backlog: a session missed is absent, not asked about late. The next
    session is planned a day ahead so that the worker's reference job is in
    the queue at its minute even if this process is restarting then. Nothing
    past the calendar's last session, which moves with the process
    (docs/08 open item 30).
    """
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    first, last = calendar.bounds()
    today = now.astimezone(EXCHANGE_TZ).date()
    planned: list[date] = []
    if first <= today <= last and calendar.is_session(today):
        if decision_cutoff(today) > now:
            planned.append(today)
    if first <= today < last:
        # The calendar's next_session takes a session, and today may be a
        # Saturday or a holiday; no NYSE closure runs longer than a few days.
        ahead = calendar.sessions(
            today + timedelta(days=1), min(today + timedelta(days=_LOOK_AHEAD), last)
        )
        if ahead:
            planned.append(ahead[0])
    return planned


#: How far ahead the next session is looked for: past any weekend and
#: holiday together, and any closure the exchange has had since 2001.
_LOOK_AHEAD = 14


async def database_now(conn: asyncpg.Connection) -> datetime:
    """
    The database's clock, the one that stamps ``available_at`` and so decides
    whether a signal was live. Read with ``clock_timestamp()``, the moment of
    the read, not ``now()``, the start of a transaction a caller may hold.
    """
    return await conn.fetchval("SELECT clock_timestamp()")


# ---------------------------------------------------------------------------
# Names
# ---------------------------------------------------------------------------


def regime_signal(question_set: QuestionSet, key: str) -> str:
    """
    The signal a question's answers are recorded under:
    ``decision.regime@1:regime``. The version is in it, so a bump starts a new
    series rather than pooling answers to two sets of words.
    """
    return f"{question_set.name}@{question_set.version}:{key}"


def sleeve_symbol(sleeves: Mapping[str, str] = REFERENCE_SLEEVES) -> str:
    """
    The symbol a regime signal is recorded under: each sleeve and its
    instrument, in the state's order, ``equities=SPY;bonds=IEF;commodities=GSG``.

    The only place the instruments are recorded, since the state deliberately
    names none. A changed sleeve is a new series.
    """
    if set(sleeves) != set(SLEEVES):
        raise ValueError(f"sleeves must name exactly {list(SLEEVES)}, got {sleeves}")
    return ";".join(f"{sleeve}={sleeves[sleeve]}" for sleeve in SLEEVES)


def regime_job_key(question_set: QuestionSet, session: date) -> str:
    """``jev_regime:decision.regime@1:2026-09-28``: one job per set version and
    session, ever, since ``jobs.dedupe_key`` is unique across every status."""
    return (
        f"{REGIME_KIND}:{question_set.name}@{question_set.version}:"
        f"{session.isoformat()}"
    )


def reference_job_key(session: date) -> str:
    """``ingest_reference_bars:2026-09-28``."""
    return f"{REFERENCE_KIND}:{session.isoformat()}"


def ingest_job_key(session: date) -> str:
    """``ingest_bars:2026-09-28``: the worker's live ingest for the session."""
    return f"{INGEST_KIND}:{session.isoformat()}"


# ---------------------------------------------------------------------------
# The prices
# ---------------------------------------------------------------------------


async def load_regime_panel(
    conn: asyncpg.Connection,
    session: date,
    symbols: Sequence[str] = REFERENCE_SYMBOLS,
) -> PricePanel | None:
    """
    The sleeves' adjusted closes under ``REFERENCE_SOURCE``, dated from
    ``REFERENCE_WINDOW_DAYS`` before ``session`` to ``session`` itself, as a
    panel cut at ``session``; ``None`` when no row is stored.

    One source, so no second vendor's rows are stitched into the series; the
    live path's own readers have no such filter (docs/08 open item 24), and
    this one never needed to go without it. The session bound is in the SQL,
    so no bar after the session is ever in memory. Only ``adj_close`` is read:
    the panel's raw fields are NaN, and nothing here reads them.
    """
    rows = await conn.fetch(
        """
        SELECT symbol, session, adj_close
        FROM daily_bars
        WHERE symbol = ANY($1::text[]) AND source = $2
          AND session <= $3 AND session >= $3::date - $4::int
        ORDER BY session, symbol
        """,
        sorted(symbols),
        REFERENCE_SOURCE,
        session,
        REFERENCE_WINDOW_DAYS,
    )
    if not rows:
        return None
    nan = math.nan
    return PricePanel.from_bars(
        [
            (r["symbol"], r["session"], nan, nan, nan, nan, nan, float(r["adj_close"]))
            for r in rows
        ],
        as_of=session,
    )


__all__ = [
    "COLLECT_AFTER_CLOSE",
    "DECISION_AFTER_CLOSE",
    "EXCHANGE_TZ",
    "INGEST_KIND",
    "REFERENCE_AFTER_CLOSE",
    "REFERENCE_KIND",
    "REGIME_KIND",
    "collect_at",
    "database_now",
    "decision_cutoff",
    "ingest_job_key",
    "load_regime_panel",
    "reference_at",
    "reference_job_key",
    "regime_as_of",
    "regime_job_key",
    "regime_signal",
    "sessions_to_plan",
    "sleeve_symbol",
]
