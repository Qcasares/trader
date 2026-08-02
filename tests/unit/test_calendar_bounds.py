"""
test_calendar_bounds.py
-----------------------
That a backtest window the calendar cannot answer for is refused at the
request, not discovered in the worker.

``CreateBacktestRequest`` validates types and ranges on every numeric field and
nothing at all on its dates, so pydantic accepted anything it could parse. The
engine cannot process most of it:

    start 1000-01-01  -> OverflowError from pandas; a year-1000 Timestamp does
                         not fit in nanoseconds
    end   9999-12-31  -> the same
    end   2030-01-01  -> DateOutOfBounds; exchange_calendars publishes
                         sessions only a couple of years ahead

Each was a 202 Accepted followed by a queued run, a claimed job, three retry
attempts, and a failure whose message mentions nanoseconds rather than the date
the operator typed. Cheap to prevent, and expensive to diagnose otherwise.

The bounds are read from the calendar rather than written down, because the
upper one belongs to the ``exchange_calendars`` release and moves when it is
upgraded. A literal here would be correct until the next `pip install`.
"""

from __future__ import annotations

from datetime import date

import pytest

from src.core.calendar import CALENDAR_START, bounds, sessions


class TestBoundsDescribeTheRealCalendar:
    def test_bounds_are_ordered(self) -> None:
        first, last = bounds()
        assert first < last

    def test_lower_bound_honours_the_widened_start(self) -> None:
        # The default XNYS calendar begins in 2006, which is useless for a
        # backtest wanting 1999. `nyse()` widens it; the bounds must reflect
        # the widened calendar, not the library default.
        first, _ = bounds()
        assert first <= date(1993, 12, 31), (
            f"lower bound {first} suggests the calendar was not widened to "
            f"{CALENDAR_START}"
        )

    def test_the_bounds_are_actually_usable(self) -> None:
        """
        The point of the whole exercise: a window at the reported limits must
        not raise. A bound that is itself out of range would simply move the
        crash rather than prevent it.
        """
        first, last = bounds()
        assert sessions(first, last), "no sessions between the reported bounds"


class TestTheRangesThatUsedToCrashTheWorker:
    """
    Each of these reached the engine and failed there. They are asserted as
    *outside the bounds*, which is what the API now checks — rather than
    asserting the exception, which would pin the test to whichever library
    happens to raise first.
    """

    @pytest.mark.parametrize(
        ("start", "end", "why"),
        [
            (date(1000, 1, 1), date(2020, 1, 1), "pandas nanosecond overflow"),
            (date(2020, 1, 1), date(9999, 12, 31), "pandas nanosecond overflow"),
            (date(2020, 1, 1), date(2400, 1, 1), "beyond published sessions"),
        ],
    )
    def test_is_outside_the_bounds(self, start: date, end: date, why: str) -> None:
        first, last = bounds()
        assert start < first or end > last, (
            f"{start}..{end} is reported as in range, but the engine fails on "
            f"it ({why})"
        )

    def test_an_ordinary_window_is_inside_the_bounds(self) -> None:
        # The guard has to admit the case the system exists for. A bound that
        # rejects a 1999 start would make the flagship backtest unrunnable.
        first, last = bounds()
        assert first <= date(1999, 1, 1)
        assert last >= date(2024, 12, 31)

    def test_raising_is_what_happens_without_the_guard(self) -> None:
        """
        Pins the premise. If a future pandas or exchange_calendars handled
        these gracefully, the guard would be unnecessary and this test is what
        would say so.
        """
        with pytest.raises(Exception):  # noqa: B017 - library choice, not ours
            sessions(date(1000, 1, 1), date(2020, 1, 1))
