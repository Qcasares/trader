"""
jev_features.py
---------------
The decision lane's only state: enumerated descriptors, computed in code from
prices, as of one session.

Labels rather than prices or returns, for two reasons, and the second does not
depend on the first. TypeSafe documents Jev as unreliable at arithmetic and
numeric comparison — "keep the arithmetic in code" — which one independent
study disputes. And Jev holds world knowledge with no disclosed cutoff, so
every exact figure is a fingerprint of the day it was observed: a one-day fall
of twelve percent in a broad equity index is a date to anything that remembers
March 2020, and a model that recognises the date can recall what happened next
instead of judging what it was shown. So each number is turned into a coarse
label here, and only the labels leave: trend against the 200-session average,
a volatility quintile, a drawdown bucket and the direction of the 63-session
return, for each sleeve. No session, no symbol, no figure. The labels and the
windows that define them live in ``jev_questions.py``, where they are written
into the question's instructions and hashed with it.

Point in time, structurally. Every price is read through
``PricePanel.at(session)``, which refuses to look past the panel's cutoff, and
only from ``adj_close`` on or before ``session``. Each sleeve is described from
exactly the trailing window its descriptors need and nothing earlier, so the
same prices give the same labels however much history precedes them. A rolling
statistic carried across decades would otherwise let the floating-point residue
of old data decide a boundary case today. The window counts closes, not
calendar sessions, as ``PricePanel.series`` and ``PricePanel.sma`` do: a day on
which one symbol has no bar — a halt, a gap in a vendor's history — is skipped
rather than treated as missing, because only the session itself has to have a
close for the state to describe it.

``None`` means missing, never a guess. A sleeve short of history, a symbol with
no bar on the session itself (a failed ingest would otherwise describe the
previous session as this one), or a price that is not a positive, finite number
makes the whole state ``None``, and the lane records the question as not
measured. A partial state would be a guess at the missing sleeve, and an answer
to a guessed state looks like evidence.

Pure: no I/O, no clock, no randomness.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Mapping
from datetime import date
from typing import cast

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view

from src.core.panel import PricePanel
from src.programme.jev_questions import (
    DRAWDOWN_DEEP,
    DRAWDOWN_HIGH_SESSIONS,
    DRAWDOWN_SEVERE,
    DRAWDOWN_SHALLOW,
    MOMENTUM_FLAT_BAND,
    MOMENTUM_SESSIONS,
    SLEEVES,
    TREND_AVERAGE_SESSIONS,
    TREND_NEAR_BAND,
    VOLATILITY_HISTORY_SESSIONS,
    VOLATILITY_SESSIONS,
    Drawdown,
    Momentum,
    RegimeState,
    SleeveState,
    Trend,
    VolatilityQuintile,
)

logger = logging.getLogger(__name__)

#: Adjusted closes a sleeve needs before it can be described: 1,280.
#:
#: The volatility quintile is the longest reach. It ranks the latest
#: 20-session volatility among the last 1,260 such readings; the oldest of
#: those readings needs 20 daily returns, and 20 returns need 21 closes. So
#: N closes give N - 1 returns and N - 20 readings, and 1,260 readings need
#: 1,260 + 20 closes. Every other descriptor reaches less far back: 200 closes
#: for the trend, 252 for the drawdown, 64 for the momentum.
MIN_HISTORY_SESSIONS = VOLATILITY_HISTORY_SESSIONS + VOLATILITY_SESSIONS


def _finite(value: float, what: str) -> float:
    # A NaN compares false with everything, so it would fall through every
    # branch below into whichever label is last. Refused instead.
    if not math.isfinite(value):
        raise ValueError(f"{what} must be a finite number, got {value!r}")
    return value


def trend_label(ratio: float) -> Trend:
    """
    The latest close against its average, as ``ratio = close / average - 1``.

    "near" within :data:`TREND_NEAR_BAND` either side, inclusive; "above" or
    "below" beyond it.
    """
    _finite(ratio, "the trend ratio")
    if ratio > TREND_NEAR_BAND:
        return "above"
    if ratio < -TREND_NEAR_BAND:
        return "below"
    return "near"


def drawdown_label(drawdown: float) -> Drawdown:
    """
    The fall from the trailing high, as a positive fraction of the high.

    "none" below :data:`DRAWDOWN_SHALLOW`; "shallow" from there to below
    :data:`DRAWDOWN_DEEP`; "deep" from there to :data:`DRAWDOWN_SEVERE`
    inclusive; "severe" beyond it.
    """
    _finite(drawdown, "the drawdown")
    if drawdown < 0:
        # The trailing high includes the latest close, so the close cannot sit
        # above it. A negative drawdown means the caller measured something else.
        raise ValueError(f"a drawdown is zero or more, got {drawdown!r}")
    if drawdown < DRAWDOWN_SHALLOW:
        return "none"
    if drawdown < DRAWDOWN_DEEP:
        return "shallow"
    if drawdown <= DRAWDOWN_SEVERE:
        return "deep"
    return "severe"


def momentum_label(change: float) -> Momentum:
    """
    The direction of the return over :data:`MOMENTUM_SESSIONS` sessions.

    "flat" when its size is strictly less than :data:`MOMENTUM_FLAT_BAND`.
    """
    _finite(change, "the momentum return")
    if abs(change) < MOMENTUM_FLAT_BAND:
        return "flat"
    return "up" if change > 0 else "down"


def volatility_quintile(readings: np.ndarray) -> VolatilityQuintile:
    """
    The quintile, 1 to 5, of the last reading among all of them, itself included.

    Ranked by mid-rank: a reading counts every reading below it, and half of
    those equal to it. The calmest reading of a history is quintile 1 and the
    most turbulent is 5, and a history of identical readings — a price that
    never moves — sits in the middle rather than at either end, because nothing
    about it is calm or turbulent relative to itself. The position is always
    below 1, since the reading is one of its own equals, so the quintile never
    exceeds 5.
    """
    values = np.asarray(readings, dtype=float)
    if values.ndim != 1 or values.size == 0:
        raise ValueError("volatility readings must be a non-empty 1-d array")
    if not np.all(np.isfinite(values)):
        raise ValueError("volatility readings must all be finite")
    latest = values[-1]
    below = int(np.count_nonzero(values < latest))
    level = int(np.count_nonzero(values == latest))
    position = (below + level / 2) / values.size
    return cast(VolatilityQuintile, int(position * 5) + 1)


def describe(closes: np.ndarray) -> SleeveState:
    """
    One sleeve's descriptors from its trailing adjusted closes, oldest first.

    Takes exactly :data:`MIN_HISTORY_SESSIONS` positive, finite closes and
    nothing else, so a description is a function of that window alone.
    Volatility is the sample standard deviation of daily log returns, each
    20-session reading computed from its own window rather than carried along
    by a running sum.
    """
    window = np.asarray(closes, dtype=float)
    if window.shape != (MIN_HISTORY_SESSIONS,):
        raise ValueError(
            f"describe takes exactly {MIN_HISTORY_SESSIONS} closes, got {window.shape}"
        )
    if not (np.all(np.isfinite(window)) and np.all(window > 0)):
        raise ValueError("closes must all be positive and finite")

    latest = float(window[-1])
    average = float(window[-TREND_AVERAGE_SESSIONS:].mean())
    high = float(window[-DRAWDOWN_HIGH_SESSIONS:].max())
    earlier = float(window[-1 - MOMENTUM_SESSIONS])
    returns = np.diff(np.log(window))
    readings = sliding_window_view(returns, VOLATILITY_SESSIONS).std(axis=1, ddof=1)

    return SleeveState(
        trend=trend_label(latest / average - 1.0),
        volatility_quintile=volatility_quintile(readings),
        drawdown=drawdown_label(1.0 - latest / high),
        momentum=momentum_label(latest / earlier - 1.0),
    )


def _sleeves_problem(sleeves: object) -> str | None:
    if not isinstance(sleeves, Mapping):
        return f"sleeves must map each sleeve to a symbol, got {sleeves!r}"
    if set(sleeves) != set(SLEEVES):
        return f"sleeves must name exactly {list(SLEEVES)}, got {list(sleeves)}"
    symbols = [sleeves[sleeve] for sleeve in SLEEVES]
    for sleeve, symbol in zip(SLEEVES, symbols, strict=True):
        if not isinstance(symbol, str) or not symbol:
            return f"sleeve {sleeve!r} must map to a symbol, got {symbol!r}"
    if len(set(symbols)) != len(symbols):
        return f"each sleeve needs its own symbol, got {dict(sleeves)}"
    return None


def _trailing_closes(
    view: PricePanel, session: date, sleeve: str, symbol: str
) -> np.ndarray | None:
    """The sleeve's last :data:`MIN_HISTORY_SESSIONS` closes, or ``None``."""
    if symbol not in view.symbols:
        logger.warning(
            "regime state missing: %s (%s) is not in the panel", sleeve, symbol
        )
        return None
    if view.value_on(symbol, session) is None:
        logger.info(
            "regime state missing: %s (%s) has no close on %s",
            sleeve,
            symbol,
            session,
        )
        return None
    series = view.series(symbol, "adj_close")
    if len(series) < MIN_HISTORY_SESSIONS:
        logger.info(
            "regime state missing: %s (%s) has %d of the %d closes it needs",
            sleeve,
            symbol,
            len(series),
            MIN_HISTORY_SESSIONS,
        )
        return None
    closes = series.to_numpy(dtype=float)[-MIN_HISTORY_SESSIONS:]
    if not (np.all(np.isfinite(closes)) and np.all(closes > 0)):
        logger.warning(
            "regime state missing: %s (%s) has a close that is not a positive "
            "finite number in its trailing window",
            sleeve,
            symbol,
        )
        return None
    return closes


def regime_state(
    panel: PricePanel, session: date, sleeves: Mapping[str, str]
) -> RegimeState | None:
    """
    The regime state as of the close of ``session``, or ``None`` if missing.

    ``sleeves`` maps each of ``jev_questions.SLEEVES`` to the symbol that
    stands for it. The symbols choose which prices are read and never appear in
    the state. A mapping that names other sleeves, or gives two sleeves one
    symbol, is a caller's error and raises :class:`ValueError`; a ``session``
    past the panel's cutoff raises :class:`~src.core.panel.LookAheadError`.
    Everything the data cannot support returns ``None``.
    """
    problem = _sleeves_problem(sleeves)
    if problem is not None:
        raise ValueError(problem)
    view = panel.at(session)
    described: dict[str, SleeveState] = {}
    for sleeve in SLEEVES:
        closes = _trailing_closes(view, session, sleeve, sleeves[sleeve])
        if closes is None:
            return None
        described[sleeve] = describe(closes)
    return RegimeState(**described)


__all__ = [
    "MIN_HISTORY_SESSIONS",
    "describe",
    "drawdown_label",
    "momentum_label",
    "regime_state",
    "trend_label",
    "volatility_quintile",
]
