"""
yfinance_source.py
------------------
Research-only history from Yahoo Finance, back to each instrument's inception.

Why this exists at all: Alpaca carries roughly seven years of history, which
excludes 2008 — the exact regime in which a trend-following strategy earns its
keep. Backtesting asset-class trend following on 2016-onward data measures a
bull market with two brief interruptions.

Why it is research-only:

- The API is unofficial and undocumented, and it breaks without notice.
- Yahoo's terms of service are a separate question from the ``yfinance``
  package's Apache-2.0 licence, and they are not obviously compatible with a
  commercial hosted product.

So: cache into ``daily_bars`` with ``source='yfinance'``, backtest against it,
and never let a live decision depend on a live call to it.

``auto_adjust=False`` is set explicitly. Recent ``yfinance`` versions default it
to ``True``, which silently overwrites OHLC with adjusted values and drops the
``Adj Close`` column — leaving no way to recover raw prices. We need both: raw
for the ledger and for what the broker will actually charge, adjusted for
signals.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import date, timedelta
from typing import Any

from src.core.types import Bar
from src.data.base import Coverage, DataSourceError, PriceSource

logger = logging.getLogger(__name__)

SOURCE_NAME = "yfinance"


class YFinanceSource(PriceSource):
    """Daily bars from Yahoo Finance. Research use only."""

    def __init__(self, timeout: int = 30) -> None:
        self._timeout = timeout

    @property
    def name(self) -> str:
        return SOURCE_NAME

    def fetch(
        self,
        symbols: Sequence[str],
        start: date,
        end: date,
    ) -> list[Bar]:
        frame = self._download(symbols, start, end)
        if frame is None or frame.empty:
            raise DataSourceError(
                f"yfinance returned no rows for {list(symbols)} "
                f"between {start} and {end}"
            )
        return self._to_bars(frame, symbols)

    def coverage(self, symbols: Sequence[str]) -> list[Coverage]:
        """Cheap probe of available history using a wide date range."""
        out: list[Coverage] = []
        for symbol in symbols:
            try:
                bars = self.fetch([symbol], date(1990, 1, 1), date.today())
            except DataSourceError:
                out.append(Coverage(symbol, None, None, 0, SOURCE_NAME))
                continue
            sessions = sorted({b.session for b in bars})
            out.append(
                Coverage(
                    symbol=symbol,
                    first_session=sessions[0] if sessions else None,
                    last_session=sessions[-1] if sessions else None,
                    n_sessions=len(sessions),
                    source=SOURCE_NAME,
                )
            )
        return out

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _download(self, symbols: Sequence[str], start: date, end: date) -> Any:
        try:
            import yfinance as yf
        except ImportError as exc:  # pragma: no cover - dependency guard
            raise DataSourceError(
                "yfinance is not installed; it is a research-only dependency"
            ) from exc

        # `end` is exclusive in yfinance and inclusive in `PriceSource.fetch`,
        # so the last session asked for has to be one day past the last session
        # wanted. Without this the panel stops a day short of the requested
        # window, and the failure surfaces nowhere near the cause: the ingest
        # reports success, and the driver then refuses to read the final
        # session's open with "panel as_of is <the day before>". A backtest to
        # 2024-12-31 failed for exactly that reason.
        try:
            return yf.download(
                list(symbols),
                start=start.isoformat(),
                end=(end + timedelta(days=1)).isoformat(),
                auto_adjust=False,  # keep BOTH raw OHLC and Adj Close
                actions=False,
                progress=False,
                threads=False,
                group_by="column",
            )
        except Exception as exc:
            raise DataSourceError(f"yfinance download failed: {exc}") from exc

    def _to_bars(self, frame: Any, symbols: Sequence[str]) -> list[Bar]:
        """
        Normalise yfinance's shape into ``Bar`` objects.

        yfinance returns a MultiIndex ``(field, symbol)`` for several tickers
        and a flat index for one, so both are handled rather than assuming the
        multi-symbol case and breaking on a single-symbol backfill.
        """
        import pandas as pd

        bars: list[Bar] = []
        multi = isinstance(frame.columns, pd.MultiIndex)

        for symbol in symbols:
            if multi:
                try:
                    sub = frame.xs(symbol, axis=1, level=1)
                except KeyError:
                    logger.warning("yfinance returned no data for %s", symbol)
                    continue
            else:
                sub = frame

            sub = sub.dropna(subset=["Close"])
            for ts, row in sub.iterrows():
                adj = row.get("Adj Close")
                close = float(row["Close"])
                bars.append(
                    Bar(
                        symbol=symbol,
                        session=pd.Timestamp(ts).date(),
                        open=float(row["Open"]),
                        high=float(row["High"]),
                        low=float(row["Low"]),
                        close=close,
                        volume=float(row.get("Volume", 0.0) or 0.0),
                        adj_close=float(adj) if adj is not None and adj == adj
                        else close,
                        source=SOURCE_NAME,
                    )
                )

        if not bars:
            raise DataSourceError(
                f"yfinance produced no usable bars for {list(symbols)}"
            )
        bars.sort(key=lambda b: (b.session, b.symbol))
        return bars
