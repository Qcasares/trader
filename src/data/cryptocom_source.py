"""
cryptocom_source.py
-------------------
Daily candles from the Crypto.com Exchange public market-data API.

Why this exists
~~~~~~~~~~~~~~~
Every number this repository has produced so far came from
:class:`~src.data.synthetic.SyntheticSource`. That was honest — it labels
itself synthetic everywhere — but it means the ingest -> ``PricePanel`` ->
``Driver`` -> metrics path had never once been run on prices a market actually
printed. A generator you wrote cannot surprise you, and the whole point of
running real data is to be surprised.

This adapter is the first one whose output is genuinely observed. It is *not* a
step toward trading crypto: the locked plan is equities first, and the strategy
in this repository targets asset-class ETFs. It exists so the engine can be
exercised against real prices.

What is and is not verified
~~~~~~~~~~~~~~~~~~~~~~~~~~~
The distinction matters, so it is stated rather than implied:

- **The prices are real.** ``tests/fixtures/cryptocom_candles.json`` holds
  candles captured verbatim from the venue, with their provenance recorded
  alongside them.
- **The HTTP path is not exercised.** ``api.crypto.com`` is unreachable from
  the build environment, so :meth:`CryptoComSource.fetch` is written against
  the documented contract and has never spoken to the host — exactly the
  status of ``YFinanceSource``. Do not read a green test suite as evidence
  that the fetch works.

Adjusted closes
~~~~~~~~~~~~~~~
A spot crypto pair has no splits and pays no dividends, so ``adj_close`` equals
``close`` *by construction*. This is the one case where the two may coincide.
It emphatically does not generalise: on equities, using raw closes for signals
makes a moving average drift against price by the cumulative dividend, and the
trend filter fires at the wrong times.

Sessions
~~~~~~~~
Crypto trades continuously, so a session is a UTC calendar day and there are no
holidays. The NYSE calendar in :mod:`src.core.calendar` does not apply and is
deliberately not used here — see :func:`continuous_sessions`.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable, Sequence
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from src.core.types import Bar
from src.data.base import Coverage, DataSourceError, PriceSource

logger = logging.getLogger(__name__)

SOURCE_NAME = "cryptocom"

#: Documented public endpoint. Unauthenticated, no key required.
BASE_URL = "https://api.crypto.com/exchange/v1/public/get-candlestick"

#: The venue caps a candlestick response. Anything wanting more history has to
#: page, and the public endpoint offers no cursor — so this adapter is honest
#: about being shallow rather than pretending otherwise.
MAX_CANDLES = 50


def continuous_sessions(start: date, end: date) -> list[date]:
    """
    Every UTC calendar day in ``[start, end]``.

    The 24/7 counterpart to :func:`src.core.calendar.sessions`. It is a
    separate function rather than a flag on the NYSE one because "which days
    are sessions" is a property of the venue, and silently reusing an equity
    calendar for a market that never closes would drop roughly two sevenths of
    the data on the floor.
    """
    if end < start:
        raise ValueError(f"end {end} precedes start {start}")
    span = (end - start).days
    return [start + timedelta(days=offset) for offset in range(span + 1)]


class CryptoComSource(PriceSource):
    """Daily candles for spot pairs such as ``BTC_USDT``."""

    def __init__(self, timeout: int = 30) -> None:
        self._timeout = timeout
        self._cache: dict[str, list[Bar]] = {}

    @property
    def name(self) -> str:
        return SOURCE_NAME

    # ------------------------------------------------------------------
    # Construction from already-captured candles
    # ------------------------------------------------------------------

    @classmethod
    def from_payloads(
        cls, payloads: dict[str, Iterable[dict[str, Any]]]
    ) -> CryptoComSource:
        """
        Build a source from candle dictionaries already in hand.

        Used for the captured fixture, and for any caller that obtained candles
        by some route other than this adapter's own HTTP call. The parsing is
        the same code either way, so a fixture-backed run exercises the real
        normalisation rather than a test-only shortcut.
        """
        source = cls()
        for symbol, rows in payloads.items():
            source._cache[symbol] = _parse_candles(symbol, rows)
        return source

    @classmethod
    def from_fixture(cls, path: str | Path) -> CryptoComSource:
        """Build from a captured-candles JSON file, provenance and all."""
        data = json.loads(Path(path).read_text())
        instruments = data.get("instruments")
        if not instruments:
            raise DataSourceError(f"{path} has no 'instruments' section")
        return cls.from_payloads(instruments)

    # ------------------------------------------------------------------
    # PriceSource
    # ------------------------------------------------------------------

    def fetch(
        self,
        symbols: Sequence[str],
        start: date,
        end: date,
    ) -> list[Bar]:
        bars: list[Bar] = []
        for symbol in symbols:
            candles = self._cache.get(symbol)
            if candles is None:
                candles = _parse_candles(symbol, self._download(symbol))
                self._cache[symbol] = candles
            bars.extend(b for b in candles if start <= b.session <= end)

        if not bars:
            raise DataSourceError(
                f"cryptocom returned no bars for {list(symbols)} "
                f"between {start} and {end}"
            )
        bars.sort(key=lambda b: (b.session, b.symbol))
        return bars

    def coverage(self, symbols: Sequence[str]) -> list[Coverage]:
        out: list[Coverage] = []
        for symbol in symbols:
            candles = self._cache.get(symbol)
            if candles is None:
                try:
                    candles = _parse_candles(symbol, self._download(symbol))
                    self._cache[symbol] = candles
                except DataSourceError:
                    out.append(Coverage(symbol, None, None, 0, SOURCE_NAME))
                    continue
            sessions = sorted({b.session for b in candles})
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

    def _download(self, symbol: str) -> list[dict[str, Any]]:
        """
        One HTTP call for one instrument.

        Written against the documented contract and **never executed against
        the live host** from this environment. Treat it as unverified.
        """
        try:
            import requests
        except ImportError as exc:  # pragma: no cover - dependency guard
            raise DataSourceError("requests is not installed") from exc

        try:
            response = requests.get(
                BASE_URL,
                params={"instrument_name": symbol, "timeframe": "1D"},
                timeout=self._timeout,
            )
            response.raise_for_status()
            body = response.json()
        except Exception as exc:
            raise DataSourceError(
                f"cryptocom candlestick request failed for {symbol}: {exc}"
            ) from exc

        result = body.get("result") or {}
        rows = result.get("data")
        if not rows:
            raise DataSourceError(f"cryptocom returned no candles for {symbol}")
        return list(rows)


def _parse_candles(symbol: str, rows: Iterable[dict[str, Any]]) -> list[Bar]:
    """
    Normalise raw candles into :class:`Bar` objects, ascending by session.

    The venue returns newest-first and may repeat a session across pages; both
    are handled here so that a caller never has to think about it. Duplicate
    sessions keep the last occurrence, matching how ``daily_bars`` upserts.
    """
    by_session: dict[date, Bar] = {}
    for row in rows:
        session = _session_of(row)
        close = float(row["close"])
        by_session[session] = Bar(
            symbol=symbol,
            session=session,
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=close,
            volume=float(row.get("volume") or 0.0),
            # No corporate actions on a spot pair; see the module docstring.
            adj_close=close,
            source=SOURCE_NAME,
        )

    if not by_session:
        raise DataSourceError(f"no usable candles for {symbol}")
    return [by_session[s] for s in sorted(by_session)]


def _session_of(row: dict[str, Any]) -> date:
    """
    The UTC calendar day a candle belongs to.

    Accepts both shapes the venue emits: an ISO-8601 ``timestamp`` string and
    the epoch-millisecond ``t`` field. Milliseconds are interpreted in UTC
    explicitly — reading them in local time would shift every session by a day
    for anyone running outside UTC, which is the kind of bug that only shows up
    once a strategy is live.
    """
    raw = row.get("timestamp")
    if raw is not None:
        text = str(raw).replace("Z", "+00:00")
        return datetime.fromisoformat(text).date()

    millis = row.get("t") or row.get("time")
    if millis is None:
        raise DataSourceError(f"candle has no timestamp: {row!r}")
    return datetime.fromtimestamp(int(millis) / 1000, tz=UTC).date()
