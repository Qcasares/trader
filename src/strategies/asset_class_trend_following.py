"""
asset_class_trend_following.py
------------------------------
Asset Class Trend Following — five asset-class ETFs, held only while each is
above its 10-month moving average, equal-weighted, rebalanced monthly.

Reference: paperswithbacktest/awesome-systematic-trading,
``static/strategies/asset-class-trend-following.py`` (reported Sharpe 0.502,
volatility 10.4%, monthly rebalance), after Faber's "A Quantitative Approach to
Tactical Asset Allocation".

Three deliberate departures from the reference implementation
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

1. **Rebalance timing.** The reference guards with
   ``if self.Time.hour != 9 and self.Time.minute != 31`` — ``and`` where ``or``
   was clearly meant, so it also passes at 10:31, 11:31, and so on. We
   implement the stated intent: the first trading session of each calendar
   month.

2. **Availability windows.** The reference starts in 2000 and equal-weights
   across five ETFs, but EFA did not list until 2001-08-14, IEF until
   2002-07-22, VNQ until 2004-09-23 and GSG until 2006-07-10. Dividing by five
   in 2001 would have implied an 80% cash position that the strategy never
   intended. We weight only over symbols that actually have enough history,
   and report ``effective_start_date`` so the headline metric is never quoted
   over a window where the strategy was not yet itself.

3. **Signal source.** Signals are computed on split- and dividend-adjusted
   closes. VNQ yields roughly 4% and IEF is mostly coupon; on raw closes their
   moving averages drift downward relative to price and the trend filter fires
   at the wrong times.
"""

from __future__ import annotations

import logging
from datetime import date

from pydantic import Field, field_validator

from src.core.panel import PricePanel
from src.core.types import PortfolioState, TargetWeights
from src.strategies.base import Strategy, StrategyParams
from src.strategies.registry import register

logger = logging.getLogger(__name__)

#: SPY (US equities), EFA (developed ex-US), IEF (7-10y Treasuries),
#: VNQ (REITs), GSG (broad commodities).
DEFAULT_UNIVERSE: tuple[str, ...] = ("SPY", "EFA", "IEF", "VNQ", "GSG")

#: 10 months x 21 trading days, matching the reference implementation.
DEFAULT_SMA_PERIOD = 210


class AssetClassTrendFollowingParams(StrategyParams):
    """Tunable parameters, rendered as the web form via JSON Schema."""

    symbols: list[str] = Field(
        default=list(DEFAULT_UNIVERSE),
        min_length=1,
        description="Asset-class ETFs to rotate between.",
    )
    sma_period: int = Field(
        default=DEFAULT_SMA_PERIOD,
        ge=2,
        le=1000,
        description=(
            "Simple moving average lookback in trading sessions. 210 ~ 10 months."
        ),
    )
    max_weight_per_asset: float = Field(
        default=1.0,
        gt=0.0,
        le=1.0,
        description=(
            "Concentration cap. At the default of 1.0 a single surviving asset "
            "may take the whole book, which is the reference behaviour."
        ),
    )

    @field_validator("symbols")
    @classmethod
    def _normalise_symbols(cls, value: list[str]) -> list[str]:
        cleaned = [s.strip().upper() for s in value if s and s.strip()]
        if not cleaned:
            raise ValueError("symbols must contain at least one ticker")
        if len(set(cleaned)) != len(cleaned):
            raise ValueError(f"duplicate symbols in universe: {cleaned}")
        return cleaned


@register
class AssetClassTrendFollowing(Strategy):
    """Equal-weight the asset classes currently in an uptrend; hold cash otherwise."""

    name = "asset_class_trend_following"
    version = "1.0"
    description = (
        "Hold each of five asset-class ETFs only while it trades above its "
        "10-month simple moving average, equal-weighted, rebalanced on the "
        "first trading day of each month. Anything not qualifying is cash."
    )
    source = (
        "paperswithbacktest/awesome-systematic-trading — "
        "static/strategies/asset-class-trend-following.py"
    )
    params_model = AssetClassTrendFollowingParams

    params: AssetClassTrendFollowingParams

    # ------------------------------------------------------------------
    # Contract
    # ------------------------------------------------------------------

    def universe(self) -> list[str]:
        return list(self.params.symbols)

    @property
    def warmup_sessions(self) -> int:
        return self.params.sma_period

    def should_rebalance(
        self, session: date, last_rebalance: date | None
    ) -> bool:
        """
        Rebalance on the first trading session of each calendar month.

        The driver calls this for every session in order, so the first session
        whose ``(year, month)`` differs from the last rebalance *is* the first
        trading day of the month. That derives the schedule from the sessions
        actually presented rather than from a separate calendar lookup, so a
        holiday or an unscheduled closure cannot desynchronise the two.
        """
        if last_rebalance is None:
            return True
        return (session.year, session.month) != (
            last_rebalance.year,
            last_rebalance.month,
        )

    def target_weights(
        self,
        panel: PricePanel,
        state: PortfolioState,
        session: date,
    ) -> TargetWeights:
        period = self.params.sma_period

        # Only symbols with a full lookback are eligible. A symbol that has not
        # listed yet is excluded from the denominator, not held at zero.
        eligible = [
            symbol
            for symbol in self.params.symbols
            if panel.is_available(symbol, min_history=period)
        ]

        qualifying: list[str] = []
        for symbol in eligible:
            price = panel.latest(symbol)
            average = panel.sma(symbol, period)
            if price is None or average is None:
                continue
            if price > average:
                qualifying.append(symbol)

        if not qualifying:
            return TargetWeights(
                weights={},
                rationale=(
                    f"{session}: none of {len(eligible)} eligible asset classes "
                    f"above their {period}-session SMA — 100% cash."
                ),
            )

        weight = 1.0 / len(qualifying)
        cap = self.params.max_weight_per_asset
        weights = {symbol: min(weight, cap) for symbol in sorted(qualifying)}

        allocated = sum(weights.values())
        rationale = (
            f"{session}: {len(qualifying)} of {len(eligible)} eligible asset "
            f"classes above their {period}-session SMA "
            f"({', '.join(sorted(qualifying))}); "
            f"{allocated:.1%} invested, {1 - allocated:.1%} cash."
        )
        return TargetWeights(weights=weights, rationale=rationale)
