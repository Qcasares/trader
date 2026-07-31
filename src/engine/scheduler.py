"""
scheduler.py
------------
Market-calendar-driven job planning.

**Never use wall-clock cron for a market event.** A container running UTC with
a cron at "16:30" fires at 11:30 ET in summer and 12:30 in winter, and on a
half-day it fires three hours after the exchange has already shut. Both
failures are silent.

Instead, once a day this computes the session's actual bounds from
``exchange_calendars`` and emits a list of one-shot jobs at times derived from
them. Early closes are handled for free because the bounds come from the
calendar, and the resulting plan is a plain data structure you can inspect via
``GET /api/v1/system/jobs`` rather than behaviour hidden inside a scheduler.

The plan is *derived state*, recomputed each morning — which is why it is held
in memory rather than a durable job store, and why a worker restart cannot
produce the classic misfire storm.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import StrEnum
from zoneinfo import ZoneInfo

from src.core.calendar import is_session, session_close, session_open

logger = logging.getLogger(__name__)

#: The exchange's own timezone. Every "is this early?" comparison happens here,
#: never in UTC — see :func:`is_early_close`.
EXCHANGE_TZ = ZoneInfo("America/New_York")

#: Ordinary NYSE close, exchange-local.
NORMAL_CLOSE_HOUR_LOCAL = 16


def _local_close_hour(session: date) -> int:
    """Closing hour in exchange-local time, DST included."""
    return session_close(session).astimezone(EXCHANGE_TZ).hour


class JobKind(StrEnum):
    """Job kinds the scheduler emits. Handlers live in ``src/worker``."""

    RECONCILE = "reconcile"
    SUBMIT_ORDERS = "submit_orders"
    LIVE_DECISION = "live_decision"
    EOD_MARKS = "eod_marks"
    INGEST_BARS = "ingest_bars"


@dataclass(frozen=True, slots=True)
class PlannedJob:
    """One scheduled unit of work."""

    kind: JobKind
    run_at: datetime
    payload: dict[str, object]
    reason: str

    def __str__(self) -> str:  # pragma: no cover - logging aid
        return f"{self.kind.value}@{self.run_at:%Y-%m-%d %H:%M}Z ({self.reason})"


#: Reconcile before the open, so a mismatch is known before we act on it.
RECONCILE_BEFORE_OPEN = timedelta(minutes=5)

#: Submit shortly after the open rather than at it. Alpaca does not accept
#: market-on-open for fractional or notional orders, so "the open" is not
#: available to us and pretending otherwise would put a price in the backtest
#: that the live system can never achieve.
SUBMIT_AFTER_OPEN = timedelta(minutes=5)

#: Decide after the close using the official closing prices.
DECIDE_AFTER_CLOSE = timedelta(minutes=30)

#: Mark the book once end-of-day data has settled.
MARKS_AFTER_CLOSE = timedelta(minutes=60)

#: Alpaca's free tier will not return a bar until it is at least 15 minutes
#: old. A job asking for today's bar at 16:05 ET gets nothing at all.
INGEST_AFTER_CLOSE = timedelta(minutes=45)


def plan_session(
    session: date, deployment_ids: list[str] | None = None
) -> list[PlannedJob]:
    """
    Jobs for one trading session, in execution order.

    Returns an empty list when ``session`` is not a trading day — a holiday
    schedules nothing rather than scheduling work that then has to detect it is
    a holiday.
    """
    if not is_session(session):
        logger.info("%s is not a trading session; nothing scheduled", session)
        return []

    opened = session_open(session)
    closed = session_close(session)
    payload: dict[str, object] = {
        "session": session.isoformat(),
        "deployment_ids": deployment_ids or [],
    }

    jobs = [
        PlannedJob(
            JobKind.RECONCILE,
            opened - RECONCILE_BEFORE_OPEN,
            payload,
            "verify our ledger matches the broker before acting on it",
        ),
        PlannedJob(
            JobKind.SUBMIT_ORDERS,
            opened + SUBMIT_AFTER_OPEN,
            payload,
            "execute orders staged by the previous session's decision",
        ),
        PlannedJob(
            JobKind.INGEST_BARS,
            closed + INGEST_AFTER_CLOSE,
            payload,
            "fetch today's bar (free-tier data is delayed 15 minutes)",
        ),
        PlannedJob(
            JobKind.LIVE_DECISION,
            closed + DECIDE_AFTER_CLOSE,
            payload,
            "compute targets from today's close; execute at tomorrow's open",
        ),
        PlannedJob(
            JobKind.EOD_MARKS,
            closed + MARKS_AFTER_CLOSE,
            payload,
            "mark the book and record daily P&L",
        ),
    ]
    return sorted(jobs, key=lambda job: job.run_at)


def is_early_close(session: date) -> bool:
    """
    Whether the session closes before the usual 16:00 exchange-local.

    Half-days are real — the day after Thanksgiving and Christmas Eve close at
    13:00 ET, and a scheduler assuming a fixed close fires its end-of-day work
    three hours late on those days.

    The comparison **must** be in exchange-local time. Checking the UTC hour
    instead (``< 21``) looks right in winter and is wrong for eight months of
    the year: under daylight saving the normal close is 20:00 UTC, so every
    ordinary summer session would be reported as a half-day.
    """
    if not is_session(session):
        return False
    return _local_close_hour(session) < NORMAL_CLOSE_HOUR_LOCAL


def describe_plan(session: date) -> str:
    """Human-readable plan, for logs and the system page."""
    jobs = plan_session(session)
    if not jobs:
        return f"{session}: not a trading session — nothing scheduled"
    lines = [f"{session}: {len(jobs)} job(s)"]
    if is_early_close(session):
        lines.append("  (early close — end-of-day work moves earlier to match)")
    lines.extend(f"  {job}" for job in jobs)
    return "\n".join(lines)


def next_run_after(
    session: date, kind: JobKind, now: datetime | None = None
) -> datetime | None:
    """When ``kind`` next runs on ``session``, or None if it has passed."""
    for job in plan_session(session):
        if job.kind is kind and (now is None or job.run_at > now):
            return job.run_at
    return None
