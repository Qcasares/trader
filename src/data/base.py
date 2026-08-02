"""
base.py
-------
The ``PriceSource`` protocol.

Two implementations, deliberately kept apart:

- ``YFinanceSource`` — long history back to inception, used for research only.
  It is an unofficial API and it does break; nothing on the live path may
  depend on it.
- ``AlpacaSource`` — the venue we actually trade against, ~7 years deep.

They are not interchangeable and there is no silent fallback between them. A
fallback that swaps sources mid-series is worse than an outage: it produces a
continuous-looking curve stitched from two different vendors' idea of what a
price was. The reconciliation job's job is to make them disagree *loudly*.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Protocol, runtime_checkable

from src.core.types import Bar

logger = logging.getLogger(__name__)


class DataSourceError(RuntimeError):
    """Any failure fetching market data."""


class InsufficientDataError(DataSourceError):
    """A source returned less history than the caller requires."""


@dataclass(frozen=True, slots=True)
class Coverage:
    """What a source actually has for one symbol."""

    symbol: str
    first_session: date | None
    last_session: date | None
    n_sessions: int
    source: str

    @property
    def is_empty(self) -> bool:
        return self.n_sessions == 0


@runtime_checkable
class PriceSource(Protocol):
    """Fetches daily bars for a set of symbols."""

    @property
    def name(self) -> str:
        """Stable identifier, stored in ``daily_bars.source``."""
        ...

    def fetch(
        self,
        symbols: Sequence[str],
        start: date,
        end: date,
    ) -> list[Bar]:
        """
        Daily bars in ``[start, end]``.

        Must return ``adj_close`` populated with split- *and* dividend-adjusted
        closes. A source that cannot supply those is not usable for
        backtesting: VNQ yields ~4% and IEF is mostly coupon, so on raw closes
        their moving averages drift against price and the trend filter fires at
        the wrong times.
        """
        ...

    def coverage(self, symbols: Sequence[str]) -> list[Coverage]:
        """What history is available, without fetching all of it."""
        ...


def bars_to_rows(
    bars: Iterable[Bar],
) -> list[tuple[str, date, float, float, float, float, float, float]]:
    """
    Flatten bars into the tuple shape ``PricePanel.from_bars`` expects.

    Keeps the DB query result and the in-memory source on one code path, so a
    panel built from Postgres and a panel built from a live fetch are
    constructed identically.
    """
    return [
        (b.symbol, b.session, b.open, b.high, b.low, b.close, b.volume, b.adj_close)
        for b in bars
    ]
