"""
calendar.py
-----------
Trading-session helpers backed by ``exchange_calendars`` (XNYS).

Every date decision in the system routes through here so that the backtest
driver and the live scheduler agree on what "the first trading day of the
month" means. Getting this wrong is a quiet failure: a rebalance scheduled on
1 January never fires, and a monthly strategy silently skips a month.

The default XNYS calendar only spans 2006 onward, which is useless for a
backtest that wants 1999. :func:`nyse` widens the bounds and caches the result,
since calendar construction is not cheap.
"""

from __future__ import annotations

import functools
import logging
from datetime import date, datetime
from zoneinfo import ZoneInfo

import exchange_calendars as xcals
import pandas as pd

logger = logging.getLogger(__name__)

#: Earliest session the system will consider. SPY's inception is 1993-01-22,
#: so there is nothing tradeable before this in our universe.
CALENDAR_START = "1993-01-01"

EXCHANGE = "XNYS"


@functools.lru_cache(maxsize=4)
def nyse(start: str = CALENDAR_START) -> xcals.ExchangeCalendar:
    """Return the NYSE calendar, widened to ``start`` and cached."""
    return xcals.get_calendar(EXCHANGE, start=start)


def bounds(start: str = CALENDAR_START) -> tuple[date, date]:
    """
    The first and last session the calendar can answer for.

    Exists so callers can refuse an out-of-range request *before* queueing work
    on it. The API used to accept any pair of dates pydantic would parse, and
    the failure surfaced in the worker as an ``OverflowError`` from pandas (a
    year-1000 start cannot be a nanosecond timestamp) or a ``DateOutOfBounds``
    from the calendar — three retries later, under an error message that never
    mentions dates.

    The upper bound is not ours: ``exchange_calendars`` publishes holidays a
    couple of years ahead and stops. It therefore moves when the library is
    upgraded, which is exactly why it is read from the calendar here rather
    than written down as a literal somewhere it would quietly go stale.
    """
    calendar = nyse(start)
    return calendar.first_session.date(), calendar.last_session.date()


def _ts(value: date | datetime | str | pd.Timestamp) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    if ts.tzinfo is not None:
        ts = ts.tz_convert("UTC").tz_localize(None)
    return ts.normalize()


def is_session(day: date | str) -> bool:
    """Whether the exchange was open on ``day``."""
    return bool(nyse().is_session(_ts(day)))


def sessions(start: date | str, end: date | str) -> list[date]:
    """All trading sessions in ``[start, end]``, ascending."""
    index = nyse().sessions_in_range(_ts(start), _ts(end))
    return [ts.date() for ts in index]


def previous_session(day: date | str) -> date:
    """The last session strictly before ``day``."""
    return nyse().previous_session(_ts(day)).date()


def next_session(day: date | str) -> date:
    """The first session strictly after ``day``."""
    return nyse().next_session(_ts(day)).date()


def session_open(day: date | str) -> datetime:
    """UTC open for a session. Raises if ``day`` is not a session."""
    return nyse().session_open(_ts(day)).to_pydatetime()


def session_close(day: date | str) -> datetime:
    """
    UTC close for a session, correctly reflecting early closes.

    Half-days are real: 2025-11-28 closes at 18:00 UTC (13:00 ET), not 21:00.
    A scheduler that assumes a fixed close will fire its end-of-day work three
    hours after the market has already shut.
    """
    return nyse().session_close(_ts(day)).to_pydatetime()


#: The exchange's own timezone. "Is this early?" is only meaningful here.
EXCHANGE_TZ = ZoneInfo("America/New_York")

#: Ordinary NYSE close, exchange-local.
NORMAL_CLOSE_HOUR_LOCAL = 16


def is_early_close(day: date | str) -> bool:
    """
    Whether ``day`` closes before the usual 16:00 exchange-local.

    Compared in exchange-local time, never UTC. A UTC comparison against 21:00
    is correct only under Eastern Standard Time — for the eight months of
    daylight saving the ordinary close is 20:00 UTC, so every normal summer
    session would be misreported as a half-day.
    """
    if not is_session(day):
        return False
    close = nyse().session_close(_ts(day))
    if close.tzinfo is None:
        close = close.tz_localize("UTC")
    return bool(close.tz_convert(EXCHANGE_TZ).hour < NORMAL_CLOSE_HOUR_LOCAL)


def first_session_of_month(start: date | str, end: date | str) -> list[date]:
    """
    First trading session of each calendar month within ``[start, end]``.

    This is the monthly rebalance schedule. It returns 2020-01-02, never
    2020-01-01 — New Year's Day is a holiday, and a naive ``day == 1`` check
    would skip January entirely.

    Note that the first *returned* date may not be the true first session of
    its month if ``start`` falls mid-month; callers wanting a clean schedule
    should pass a month boundary or discard the leading entry.
    """
    all_sessions = sessions(start, end)
    out: list[date] = []
    seen: set[tuple[int, int]] = set()
    for session in all_sessions:
        key = (session.year, session.month)
        if key not in seen:
            seen.add(key)
            out.append(session)
    return out


def last_session_of_month(start: date | str, end: date | str) -> list[date]:
    """Last trading session of each calendar month within ``[start, end]``."""
    all_sessions = sessions(start, end)
    out: list[date] = []
    for i, session in enumerate(all_sessions):
        is_last = i == len(all_sessions) - 1
        if is_last or all_sessions[i + 1].month != session.month:
            out.append(session)
    return out


def sessions_between(start: date, end: date) -> int:
    """Count of trading sessions in ``[start, end]``."""
    return len(sessions(start, end))


def align_to_session(day: date | str, direction: str = "previous") -> date | None:
    """
    Snap ``day`` to a real session.

    ``direction='previous'`` returns ``day`` itself if it is a session, else the
    session before it. ``direction='next'`` does the reverse. Used when an
    external date (a config value, a URL parameter) has to be reconciled with
    the exchange's actual calendar.
    """
    target = _ts(day)
    calendar = nyse()
    if calendar.is_session(target):
        return target.date()
    if direction == "previous":
        return calendar.previous_session(target).date()
    if direction == "next":
        return calendar.next_session(target).date()
    raise ValueError(f"direction must be 'previous' or 'next', got {direction!r}")
