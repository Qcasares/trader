"""
test_scheduler.py
-----------------
Market-calendar-driven job planning.

Every assertion is against the real NYSE calendar. A scheduling bug is a silent
failure — work that never runs produces no error anywhere — so these are
known-answer tests on dates whose correct behaviour is a matter of record.
"""

from __future__ import annotations

from datetime import date

import pytest

from src.core.calendar import session_close, session_open
from src.engine.scheduler import (
    EXCHANGE_TZ,
    JobKind,
    is_early_close,
    next_run_after,
    plan_session,
)


class TestHolidaysScheduleNothing:
    @pytest.mark.parametrize(
        "holiday",
        [
            date(2026, 1, 1),    # New Year's Day
            date(2026, 12, 25),  # Christmas
            date(2024, 3, 29),   # Good Friday
            date(2026, 7, 4),    # Independence Day (a Saturday)
            date(2026, 3, 7),    # a Saturday
        ],
    )
    def test_no_jobs_on_a_non_session(self, holiday: date) -> None:
        """
        A holiday schedules nothing, rather than scheduling work that then has
        to discover it is a holiday.
        """
        assert plan_session(holiday) == []

    def test_september_2001_closure_schedules_nothing(self) -> None:
        assert plan_session(date(2001, 9, 12)) == []


class TestOrdinarySession:
    def test_emits_the_full_day(self) -> None:
        jobs = plan_session(date(2026, 3, 10))
        assert {job.kind for job in jobs} == {
            JobKind.RECONCILE,
            JobKind.SUBMIT_ORDERS,
            JobKind.INGEST_BARS,
            JobKind.LIVE_DECISION,
            JobKind.EOD_MARKS,
        }

    def test_jobs_are_ordered_by_time(self) -> None:
        jobs = plan_session(date(2026, 3, 10))
        assert [j.run_at for j in jobs] == sorted(j.run_at for j in jobs)

    def test_reconcile_precedes_the_open(self) -> None:
        """Know the book matches the broker before acting on it."""
        session = date(2026, 3, 10)
        reconcile = next(
            j for j in plan_session(session) if j.kind is JobKind.RECONCILE
        )
        assert reconcile.run_at < session_open(session)

    def test_submission_follows_the_open(self) -> None:
        """
        Alpaca will not take market-on-open for fractional or notional orders,
        so submission is deliberately after the open rather than at it.
        """
        session = date(2026, 3, 10)
        submit = next(
            j for j in plan_session(session) if j.kind is JobKind.SUBMIT_ORDERS
        )
        assert submit.run_at > session_open(session)

    def test_decision_follows_the_close(self) -> None:
        """Targets come from the official close, which does not exist before it."""
        session = date(2026, 3, 10)
        decision = next(
            j for j in plan_session(session) if j.kind is JobKind.LIVE_DECISION
        )
        assert decision.run_at > session_close(session)

    def test_ingest_waits_out_the_fifteen_minute_delay(self) -> None:
        """
        Alpaca's free tier withholds a bar until it is 15 minutes old. A job
        asking at 16:05 ET gets nothing at all.
        """
        session = date(2026, 3, 10)
        ingest = next(
            j for j in plan_session(session) if j.kind is JobKind.INGEST_BARS
        )
        delay = (ingest.run_at - session_close(session)).total_seconds() / 60
        assert delay >= 15


class TestEarlyCloses:
    """Half-days shift end-of-day work earlier; nothing may assume 16:00."""

    @pytest.mark.parametrize(
        "half_day",
        [
            date(2025, 11, 28),  # day after Thanksgiving
            date(2025, 12, 24),  # Christmas Eve
            date(2024, 7, 3),    # day before Independence Day
        ],
    )
    def test_detected(self, half_day: date) -> None:
        assert is_early_close(half_day)

    @pytest.mark.parametrize(
        "ordinary",
        [
            date(2026, 1, 15),   # EST — normal close is 21:00 UTC
            date(2026, 3, 10),   # EDT — normal close is 20:00 UTC
            date(2026, 7, 15),   # EDT
        ],
    )
    def test_ordinary_sessions_are_not_early(self, ordinary: date) -> None:
        """
        Regression: comparing the UTC hour against 21 marks every daylight-saving
        session as a half-day, because the ordinary close is 20:00 UTC for eight
        months of the year. The comparison must be exchange-local.
        """
        assert not is_early_close(ordinary)

    def test_end_of_day_work_moves_with_the_close(self) -> None:
        half_day = date(2025, 11, 28)
        ordinary = date(2025, 11, 26)

        def decision_hour(session: date) -> int:
            job = next(
                j for j in plan_session(session) if j.kind is JobKind.LIVE_DECISION
            )
            return job.run_at.astimezone(EXCHANGE_TZ).hour

        # 13:00 close vs 16:00 close — three hours earlier, derived not assumed.
        assert decision_hour(half_day) == decision_hour(ordinary) - 3


class TestDaylightSaving:
    def test_same_local_time_different_utc_instants(self) -> None:
        """
        The classic bug this design avoids: a UTC cron at a fixed hour drifts an
        hour against the market twice a year.
        """
        winter = next(
            j for j in plan_session(date(2026, 1, 15))
            if j.kind is JobKind.LIVE_DECISION
        )
        summer = next(
            j for j in plan_session(date(2026, 7, 15))
            if j.kind is JobKind.LIVE_DECISION
        )
        assert winter.run_at.hour != summer.run_at.hour
        assert (
            winter.run_at.astimezone(EXCHANGE_TZ).hour
            == summer.run_at.astimezone(EXCHANGE_TZ).hour
        )

    def test_all_times_are_timezone_aware(self) -> None:
        """A naive datetime in a scheduler is a bug waiting for a DST boundary."""
        for job in plan_session(date(2026, 3, 10)):
            assert job.run_at.tzinfo is not None


class TestQueries:
    def test_next_run_after_filters_by_time(self) -> None:
        session = date(2026, 3, 10)
        close = session_close(session)
        assert next_run_after(session, JobKind.EOD_MARKS, now=close) is not None
        # Nothing is scheduled a week later.
        far_future = close.replace(day=close.day + 1)
        assert next_run_after(session, JobKind.EOD_MARKS, now=far_future) is None

    def test_payload_carries_the_session(self) -> None:
        jobs = plan_session(date(2026, 3, 10))
        assert all(job.payload["session"] == "2026-03-10" for job in jobs)
