"""
clock.py
--------
Time, as an injected dependency.

The driver never calls ``datetime.now()``. It asks its clock. That is what lets
the identical driver code run a 25-year backtest in seconds and then run live
against the wall clock — and what lets a test drive the live path to any
historical instant without patching global state.

A strategy never sees a clock at all: it receives ``session`` as an argument.
Deterministic by construction.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator, Sequence
from datetime import UTC, date, datetime
from typing import Protocol, runtime_checkable

logger = logging.getLogger(__name__)


@runtime_checkable
class Clock(Protocol):
    """Minimum time surface the engine needs."""

    def now(self) -> datetime:
        """Current instant, timezone-aware UTC."""
        ...

    def today(self) -> date:
        """The session currently being processed."""
        ...


class RealClock:
    """Wall-clock time. Used by the live path."""

    def now(self) -> datetime:
        return datetime.now(UTC)

    def today(self) -> date:
        return self.now().date()

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "RealClock()"


class SimClock:
    """
    A clock that walks a fixed list of sessions.

    The backtest advances it one session at a time. ``now()`` returns the
    session's close instant rather than a wall time, so any code that stamps a
    timestamp during a backtest records when the event *would* have happened.
    """

    __slots__ = ("_sessions", "_index", "_close_hour_utc")

    def __init__(
        self, sessions: Sequence[date], close_hour_utc: int = 21
    ) -> None:
        if not sessions:
            raise ValueError("SimClock requires at least one session")
        self._sessions = list(sessions)
        self._index = 0
        self._close_hour_utc = close_hour_utc

    def now(self) -> datetime:
        session = self._sessions[self._index]
        return datetime(
            session.year,
            session.month,
            session.day,
            self._close_hour_utc,
            tzinfo=UTC,
        )

    def today(self) -> date:
        return self._sessions[self._index]

    # ------------------------------------------------------------------
    # Simulation control
    # ------------------------------------------------------------------

    def advance(self) -> bool:
        """Move to the next session. Returns False when exhausted."""
        if self._index >= len(self._sessions) - 1:
            return False
        self._index += 1
        return True

    def seek(self, session: date) -> None:
        """Jump to a specific session. Raises if it is not in the schedule."""
        try:
            self._index = self._sessions.index(session)
        except ValueError:
            raise ValueError(
                f"{session} is not in this clock's session list"
            ) from None

    @property
    def remaining(self) -> int:
        return len(self._sessions) - self._index - 1

    def __iter__(self) -> Iterator[date]:
        """Iterate sessions, advancing the clock as it goes."""
        self._index = 0
        while True:
            yield self._sessions[self._index]
            if not self.advance():
                return

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"SimClock(today={self.today()}, remaining={self.remaining}, "
            f"total={len(self._sessions)})"
        )
