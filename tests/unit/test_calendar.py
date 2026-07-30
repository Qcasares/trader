"""
test_calendar.py
----------------
Known-answer tests against the real NYSE calendar. The library is not mocked —
mocking it would only prove our mock matches our expectation.

A calendar bug is a silent failure: a rebalance scheduled on 1 January simply
never fires, and a monthly strategy skips a month with no error anywhere.
"""

from __future__ import annotations

from datetime import date

import pytest

from src.core.calendar import (
    first_session_of_month,
    is_session,
    last_session_of_month,
    next_session,
    previous_session,
    sessions,
)


class TestHolidays:
    @pytest.mark.parametrize(
        "day",
        [
            date(2020, 1, 1),    # New Year's Day
            date(2020, 12, 25),  # Christmas
            date(2021, 1, 18),   # MLK Day
            date(2022, 6, 20),   # Juneteenth (observed)
            date(2024, 3, 29),   # Good Friday
            date(2020, 7, 3),    # Independence Day observed
        ],
    )
    def test_known_holidays_are_not_sessions(self, day: date) -> None:
        assert not is_session(day)

    @pytest.mark.parametrize(
        "day",
        [date(2020, 1, 2), date(2020, 12, 24), date(2024, 4, 1)],
    )
    def test_known_trading_days_are_sessions(self, day: date) -> None:
        assert is_session(day)

    def test_september_2001_closure(self) -> None:
        """
        The exchange was shut 11-14 September 2001 and reopened on the 17th.
        A hand-rolled weekday calendar gets this wrong.
        """
        for day in (11, 12, 13, 14):
            assert not is_session(date(2001, 9, day))
        assert is_session(date(2001, 9, 17))

    def test_hurricane_sandy_closure(self) -> None:
        assert not is_session(date(2012, 10, 29))
        assert not is_session(date(2012, 10, 30))
        assert is_session(date(2012, 10, 31))


class TestMonthlySchedule:
    """The rebalance schedule for every monthly strategy."""

    def test_january_rebalance_is_the_second_not_the_first(self) -> None:
        """
        The whole point. A naive ``day == 1`` check skips January entirely,
        because 1 January is always a holiday.
        """
        schedule = first_session_of_month(date(2020, 1, 1), date(2020, 12, 31))
        assert schedule[0] == date(2020, 1, 2)

    def test_one_rebalance_per_month(self) -> None:
        schedule = first_session_of_month(date(2020, 1, 1), date(2020, 12, 31))
        assert len(schedule) == 12
        assert [d.month for d in schedule] == list(range(1, 13))

    def test_every_scheduled_date_is_a_real_session(self) -> None:
        schedule = first_session_of_month(date(2015, 1, 1), date(2026, 6, 30))
        assert all(is_session(d) for d in schedule)

    def test_good_friday_shifts_the_march_month_end(self) -> None:
        """March 2024 ends on the 28th; the 29th was Good Friday."""
        ends = last_session_of_month(date(2024, 1, 1), date(2024, 12, 31))
        march = [d for d in ends if d.month == 3][0]
        assert march == date(2024, 3, 28)

    def test_leading_partial_month_is_documented_behaviour(self) -> None:
        """
        Starting mid-month yields that date, not the month's true first
        session. Callers wanting a clean schedule pass a month boundary.
        """
        schedule = first_session_of_month(date(2020, 3, 16), date(2020, 5, 31))
        assert schedule[0] == date(2020, 3, 16)


class TestSessionNavigation:
    def test_sessions_are_ascending_and_unique(self) -> None:
        got = sessions(date(2020, 1, 1), date(2020, 3, 31))
        assert got == sorted(got)
        assert len(got) == len(set(got))

    def test_next_session_skips_the_weekend(self) -> None:
        assert next_session(date(2020, 1, 3)) == date(2020, 1, 6)

    def test_previous_session_skips_new_year(self) -> None:
        assert previous_session(date(2020, 1, 2)) == date(2019, 12, 31)

    def test_calendar_reaches_back_before_2006(self) -> None:
        """
        The library's default XNYS bounds start in 2006, which would silently
        truncate any backtest wanting 1999. We widen them.
        """
        got = sessions(date(1999, 1, 1), date(1999, 1, 31))
        assert got[0] == date(1999, 1, 4)
