"""
synthetic.py
------------
A deterministic, seeded price generator.

**Nothing produced here is a real price and no result computed from it says
anything about a real strategy.** It exists for two legitimate purposes:

1. Engine verification. Testing that the driver, ledger, cost model and
   metrics are correct does not require real data — it requires *known* data.
   A seeded generator gives a series whose properties we chose, so a metric
   that comes out wrong is unambiguously a bug rather than a market.
2. Development where market data is unreachable (this environment's egress
   policy blocks Yahoo, Stooq and Alpaca).

Inception dates match the real ETFs, because the availability-window logic is
one of the things most worth testing: a five-ETF strategy backtested from 1999
is a one-ETF strategy for its first two years, and the engine has to notice.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

import numpy as np

from src.core.calendar import sessions as nyse_sessions
from src.core.types import Bar
from src.data.base import Coverage, PriceSource

logger = logging.getLogger(__name__)

SOURCE_NAME = "synthetic"


@dataclass(frozen=True, slots=True)
class SymbolSpec:
    """Generating parameters for one instrument."""

    symbol: str
    inception: date
    start_price: float
    annual_drift: float
    annual_vol: float
    annual_dividend_yield: float = 0.0


#: Real inception dates. SPY 1993-01-22, EFA 2001-08-14, IEF 2002-07-22,
#: VNQ 2004-09-23, GSG 2006-07-10 — so a "2000 start" backtest of this basket
#: has only one asset until late 2001 and no full universe until mid-2006.
DEFAULT_SPECS: tuple[SymbolSpec, ...] = (
    SymbolSpec("SPY", date(1993, 1, 22), 44.0, 0.090, 0.160, 0.018),
    SymbolSpec("EFA", date(2001, 8, 14), 55.0, 0.055, 0.180, 0.028),
    SymbolSpec("IEF", date(2002, 7, 22), 80.0, 0.035, 0.065, 0.030),
    SymbolSpec("VNQ", date(2004, 9, 23), 50.0, 0.075, 0.220, 0.040),
    SymbolSpec("GSG", date(2006, 7, 10), 50.0, 0.005, 0.230, 0.000),
)

#: Regimes with a drift override, so trend following has something to avoid.
#: Loosely echoes 2008 and 2020 without pretending to reproduce them.
BEAR_REGIMES: tuple[tuple[date, date, float], ...] = (
    (date(2000, 3, 10), date(2002, 10, 9), -0.28),
    (date(2007, 10, 9), date(2009, 3, 9), -0.45),
    (date(2020, 2, 19), date(2020, 3, 23), -2.20),
    (date(2022, 1, 3), date(2022, 10, 12), -0.24),
)


class SyntheticSource(PriceSource):
    """
    Seeded geometric Brownian motion with regime shifts and dividends.

    Deterministic: the same seed and date range always produce byte-identical
    output, which is what makes it usable as a test fixture.
    """

    def __init__(
        self,
        specs: Sequence[SymbolSpec] = DEFAULT_SPECS,
        seed: int = 20260730,
        apply_regimes: bool = True,
    ) -> None:
        self._specs = {s.symbol: s for s in specs}
        self._seed = seed
        self._apply_regimes = apply_regimes

    @property
    def name(self) -> str:
        return SOURCE_NAME

    def fetch(
        self,
        symbols: Sequence[str],
        start: date,
        end: date,
    ) -> list[Bar]:
        all_sessions = nyse_sessions(start, end)
        bars: list[Bar] = []

        for offset, symbol in enumerate(symbols):
            spec = self._specs.get(symbol)
            if spec is None:
                logger.warning("No synthetic spec for %s; skipping", symbol)
                continue

            live = [s for s in all_sessions if s >= spec.inception]
            if not live:
                continue

            # Seed per symbol so adding a symbol does not perturb the others.
            rng = np.random.default_rng(self._seed + offset * 7919)
            bars.extend(self._generate(spec, live, rng))

        bars.sort(key=lambda b: (b.session, b.symbol))
        return bars

    def coverage(self, symbols: Sequence[str]) -> list[Coverage]:
        today = date.today()
        out: list[Coverage] = []
        for symbol in symbols:
            spec = self._specs.get(symbol)
            if spec is None:
                out.append(Coverage(symbol, None, None, 0, SOURCE_NAME))
                continue
            live = nyse_sessions(spec.inception, today)
            out.append(
                Coverage(
                    symbol=symbol,
                    first_session=live[0] if live else None,
                    last_session=live[-1] if live else None,
                    n_sessions=len(live),
                    source=SOURCE_NAME,
                )
            )
        return out

    # ------------------------------------------------------------------
    # Generation
    # ------------------------------------------------------------------

    def _generate(
        self,
        spec: SymbolSpec,
        live_sessions: list[date],
        rng: np.random.Generator,
    ) -> list[Bar]:
        n = len(live_sessions)
        dt = 1.0 / 252.0
        sigma = spec.annual_vol

        drifts = np.full(n, spec.annual_drift, dtype=float)
        if self._apply_regimes:
            for i, session in enumerate(live_sessions):
                for begin, finish, regime_drift in BEAR_REGIMES:
                    if begin <= session <= finish:
                        drifts[i] = regime_drift
                        break

        shocks = rng.standard_normal(n)
        log_steps = (drifts - 0.5 * sigma**2) * dt + sigma * np.sqrt(dt) * shocks

        # Total-return path (what adj_close represents).
        total_return_path = spec.start_price * np.exp(np.cumsum(log_steps))

        # Raw price path strips out reinvested dividends, so raw < adjusted by
        # the cumulative yield — matching how real adjusted series behave.
        div_drag = np.exp(-spec.annual_dividend_yield * dt * np.arange(n))
        raw_close = total_return_path * div_drag

        intraday = np.abs(rng.standard_normal(n)) * sigma * np.sqrt(dt) * 0.6
        gap = rng.standard_normal(n) * sigma * np.sqrt(dt) * 0.3

        bars: list[Bar] = []
        for i, session in enumerate(live_sessions):
            close = float(raw_close[i])
            open_ = float(close * (1.0 + gap[i]))
            high = float(max(open_, close) * (1.0 + intraday[i]))
            low = float(min(open_, close) * (1.0 - intraday[i]))
            volume = float(rng.integers(1_000_000, 90_000_000))
            bars.append(
                Bar(
                    symbol=spec.symbol,
                    session=session,
                    open=round(open_, 4),
                    high=round(high, 4),
                    low=round(low, 4),
                    close=round(close, 4),
                    volume=volume,
                    adj_close=round(float(total_return_path[i]), 4),
                    source=SOURCE_NAME,
                )
            )
        return bars
