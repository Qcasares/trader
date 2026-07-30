"""
panel.py
--------
``PricePanel`` — the only way a strategy is allowed to see market data.

Look-ahead bias is prevented *structurally* rather than by discipline. A panel
is constructed with an ``as_of`` session and every accessor slices to that
session inclusive. A strategy holding a panel cannot widen its own window:
:meth:`PricePanel.at` refuses to move forward in time, and every lookup of a
session beyond ``as_of`` raises :class:`LookAheadError`.

This matters more than it sounds. The usual way a backtest lies is that some
piece of the pipeline quietly uses tomorrow's close to decide today's trade,
and the resulting equity curve looks superb. Making that raise is cheaper than
auditing for it.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import date

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

#: Field names a panel is expected to carry.
FIELDS: tuple[str, ...] = ("open", "high", "low", "close", "volume", "adj_close")


class LookAheadError(LookupError):
    """Raised when code attempts to read market data beyond the panel's as_of."""


def _to_ts(value: date | pd.Timestamp | str) -> pd.Timestamp:
    return pd.Timestamp(value).normalize()


class PricePanel:
    """
    A time-sliced, multi-symbol view of daily bars.

    Parameters
    ----------
    frames:
        Mapping of field name -> wide DataFrame indexed by session
        (``DatetimeIndex``, normalised, ascending) with one column per symbol.
        All frames must share the same index and columns.
    as_of:
        The latest session visible through this panel, inclusive.
    """

    __slots__ = ("_frames", "_as_of", "_symbols", "_cutoff")

    def __init__(
        self,
        frames: dict[str, pd.DataFrame],
        as_of: date | pd.Timestamp,
    ) -> None:
        if not frames:
            raise ValueError("PricePanel requires at least one field frame")

        reference = next(iter(frames.values()))
        for name, frame in frames.items():
            if not isinstance(frame.index, pd.DatetimeIndex):
                raise TypeError(f"frame {name!r} must have a DatetimeIndex")
            if not frame.index.is_monotonic_increasing:
                raise ValueError(f"frame {name!r} index must be ascending")
            if not frame.index.equals(reference.index):
                raise ValueError(f"frame {name!r} index differs from the others")
            if list(frame.columns) != list(reference.columns):
                raise ValueError(f"frame {name!r} columns differ from the others")

        self._frames = frames
        self._as_of = _to_ts(as_of)
        self._cutoff = self._as_of
        self._symbols = tuple(str(c) for c in reference.columns)

    # ------------------------------------------------------------------
    # Identity
    # ------------------------------------------------------------------

    @property
    def as_of(self) -> date:
        return self._as_of.date()

    @property
    def symbols(self) -> tuple[str, ...]:
        return self._symbols

    @property
    def fields(self) -> tuple[str, ...]:
        return tuple(self._frames.keys())

    @property
    def sessions(self) -> pd.DatetimeIndex:
        """Visible sessions, i.e. everything up to and including ``as_of``."""
        index = next(iter(self._frames.values())).index
        return index[index <= self._cutoff]

    def __len__(self) -> int:
        return len(self.sessions)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"PricePanel(as_of={self.as_of}, symbols={len(self._symbols)}, "
            f"sessions={len(self)})"
        )

    # ------------------------------------------------------------------
    # Time slicing
    # ------------------------------------------------------------------

    def at(self, session: date | pd.Timestamp) -> PricePanel:
        """
        Return a narrower view ending at ``session``.

        Refuses to move forward: a panel can only ever be re-sliced to an
        earlier or equal session. This is what stops a strategy from reaching
        past its own cutoff.
        """
        target = _to_ts(session)
        if target > self._as_of:
            raise LookAheadError(
                f"Cannot re-slice panel to {target.date()}: it is later than "
                f"as_of {self.as_of}. A strategy may not widen its own window."
            )
        narrowed = PricePanel.__new__(PricePanel)
        object.__setattr__(narrowed, "_frames", self._frames)
        object.__setattr__(narrowed, "_as_of", target)
        object.__setattr__(narrowed, "_cutoff", target)
        object.__setattr__(narrowed, "_symbols", self._symbols)
        return narrowed

    # ------------------------------------------------------------------
    # Data access — every path below is truncated to the cutoff
    # ------------------------------------------------------------------

    def frame(self, field: str = "adj_close") -> pd.DataFrame:
        """The full visible history for one field, all symbols."""
        self._check_field(field)
        return self._frames[field].loc[: self._cutoff]

    def series(self, symbol: str, field: str = "adj_close") -> pd.Series:
        """
        Visible history for one symbol/field with missing sessions dropped.

        Dropping NaNs is what makes pre-inception history invisible: an ETF
        that did not exist yet simply has no observations, rather than a run of
        zeros that would silently poison a moving average.
        """
        self._check_field(field)
        self._check_symbol(symbol)
        return self._frames[field].loc[: self._cutoff, symbol].dropna()

    def latest(self, symbol: str, field: str = "adj_close") -> float | None:
        """Most recent non-null observation at or before ``as_of``."""
        series = self.series(symbol, field)
        if series.empty:
            return None
        return float(series.iloc[-1])

    def value_on(
        self, symbol: str, session: date | pd.Timestamp, field: str = "adj_close"
    ) -> float | None:
        """Observation for an exact session, or ``None`` if the market was shut."""
        target = _to_ts(session)
        if target > self._cutoff:
            raise LookAheadError(
                f"Refusing to read {symbol} {field} on {target.date()}: "
                f"panel as_of is {self.as_of}."
            )
        self._check_field(field)
        self._check_symbol(symbol)
        try:
            raw = self._frames[field].at[target, symbol]
        except KeyError:
            return None
        if raw is None or (isinstance(raw, float) and np.isnan(raw)):
            return None
        return float(raw)

    # ------------------------------------------------------------------
    # Derived signals
    # ------------------------------------------------------------------

    def sma(
        self, symbol: str, period: int, field: str = "adj_close"
    ) -> float | None:
        """
        Simple moving average of the last ``period`` observations.

        Returns ``None`` when there is insufficient history — the caller is
        expected to treat that as "no signal", never as zero.
        """
        if period <= 0:
            raise ValueError(f"period must be positive, got {period}")
        series = self.series(symbol, field)
        if len(series) < period:
            return None
        return float(series.iloc[-period:].mean())

    # ------------------------------------------------------------------
    # Availability windows
    # ------------------------------------------------------------------

    def first_session(self, symbol: str) -> date | None:
        """
        First session with an observation for ``symbol``, within the visible
        window. Approximates the instrument's inception date.
        """
        series = self.series(symbol)
        if series.empty:
            return None
        return series.index[0].date()

    def is_available(self, symbol: str, min_history: int = 1) -> bool:
        """
        Whether ``symbol`` has at least ``min_history`` observations by now.

        Assets failing this check are *excluded from the universe*, not treated
        as cash. That distinction is the difference between a five-asset
        equal-weight strategy and a one-asset strategy wearing its costume: in
        2001 only SPY existed of the SPY/EFA/IEF/VNQ/GSG basket, and dividing
        by five back then would understate the position by 5x.
        """
        return len(self.series(symbol)) >= min_history

    def available_symbols(
        self, symbols: Iterable[str] | None = None, min_history: int = 1
    ) -> tuple[str, ...]:
        """Subset of ``symbols`` that have enough history to be traded today."""
        candidates = tuple(symbols) if symbols is not None else self._symbols
        return tuple(s for s in candidates if self.is_available(s, min_history))

    # ------------------------------------------------------------------
    # Construction helpers
    # ------------------------------------------------------------------

    @classmethod
    def from_bars(
        cls,
        rows: Iterable[tuple[str, date, float, float, float, float, float, float]],
        as_of: date | pd.Timestamp | None = None,
    ) -> PricePanel:
        """
        Build a panel from ``(symbol, session, o, h, l, c, v, adj_close)`` rows.

        This is the shape returned by the ``daily_bars`` query, so the DB layer
        and the tests construct panels the same way.
        """
        frame = pd.DataFrame(
            list(rows),
            columns=["symbol", "session", *FIELDS],
        )
        if frame.empty:
            raise ValueError("cannot build a PricePanel from zero rows")
        frame["session"] = pd.to_datetime(frame["session"]).dt.normalize()

        frames: dict[str, pd.DataFrame] = {}
        for field in FIELDS:
            wide = frame.pivot_table(
                index="session", columns="symbol", values=field, aggfunc="last"
            ).sort_index()
            frames[field] = wide.astype(float)

        # pivot_table can drop all-NaN columns per field; realign them so every
        # frame carries an identical index and column set.
        all_symbols = sorted(frame["symbol"].unique())
        all_sessions = frames["adj_close"].index
        for field in FIELDS:
            frames[field] = frames[field].reindex(
                index=all_sessions, columns=all_symbols
            )

        cutoff = as_of if as_of is not None else all_sessions[-1]
        return cls(frames, cutoff)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _check_field(self, field: str) -> None:
        if field not in self._frames:
            raise KeyError(
                f"unknown field {field!r}; panel carries {sorted(self._frames)}"
            )

    def _check_symbol(self, symbol: str) -> None:
        if symbol not in self._symbols:
            raise KeyError(
                f"unknown symbol {symbol!r}; panel carries {list(self._symbols)}"
            )
