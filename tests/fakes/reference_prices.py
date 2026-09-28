"""
reference_prices.py
-------------------
Reference bars whose regime state is known and does not move from one session
to the next, for the tests that drive the forward clock on a real database.

Two sessions whose states are equal are what a replay needs, and a real
series' descriptors move with every bar. So every reference sleeve here rises
calmly for years and then turbulently for its last sixty sessions: every
close a new high, the latest far above its 200-session average, its 63-session
return large, and its 20-session volatility above every calm reading, which
puts it in the top quintile whatever the noise among the turbulent ones. The
state is therefore ``above / 5 / none / up`` for each sleeve, on the last
session and on the one before it.

The sessions are the ones whose cutoffs are ahead of the database's clock
(:func:`forward_sessions`), because the clock never measures a past session,
and the bars are stored under ``REFERENCE_SOURCE``, the one vendor the clock
reads.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

import asyncpg

from src.core import calendar
from src.data.reference import (
    REFERENCE_SOURCE,
    REFERENCE_SYMBOLS,
    REFERENCE_WINDOW_DAYS,
)
from src.programme import jev_clock
from src.programme.jev_questions import RegimeState, SleeveState

#: How many of the last sessions move turbulently.
TURBULENT_SESSIONS = 60

#: Each sleeve's state on the last two sessions of the series.
RISING = SleeveState(
    trend="above", volatility_quintile=5, drawdown="none", momentum="up"
)
EXPECTED_STATE = RegimeState(equities=RISING, bonds=RISING, commodities=RISING)


def forward_sessions(now: datetime) -> tuple[date, date]:
    """
    Two consecutive sessions whose cutoffs are both ahead of ``now``: the next
    session the clock plans, and the one after it.
    """
    first = jev_clock.sessions_to_plan(now)[-1]
    return first, calendar.next_session(first)


def closes(count: int) -> list[float]:
    """``count`` closes: calm growth, then :data:`TURBULENT_SESSIONS` of storm."""
    price = 100.0
    series = []
    for i in range(count):
        if i:
            turbulent = i >= count - TURBULENT_SESSIONS
            if turbulent:
                price *= 1.04 if i % 2 == 0 else 1.001
            else:
                price *= 1.0005
        series.append(price)
    return series


def reference_rows(end: date) -> list[tuple]:
    """Every reference symbol's bars, one per NYSE session, up to ``end``."""
    sessions = calendar.sessions(end - timedelta(days=REFERENCE_WINDOW_DAYS), end)
    rows = []
    for symbol in REFERENCE_SYMBOLS:
        for session, close in zip(sessions, closes(len(sessions)), strict=True):
            price = Decimal(repr(close))
            rows.append(
                (
                    symbol,
                    session,
                    REFERENCE_SOURCE,
                    price,
                    price,
                    price,
                    price,
                    10**6,
                    price,
                )
            )
    return rows


async def seed_reference_bars(conn: asyncpg.Connection, end: date) -> None:
    """Store :func:`reference_rows`, leaving any bar already there as it was."""
    await conn.executemany(
        """
        INSERT INTO daily_bars (symbol, session, source, open, high, low, close,
                                volume, adj_close)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
        ON CONFLICT DO NOTHING
        """,
        reference_rows(end),
    )
