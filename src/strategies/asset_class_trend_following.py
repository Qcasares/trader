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
from typing import Literal

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

#: How often the book is re-weighted. ``monthly`` is the reference cadence;
#: the others exist because a strategy's sensitivity to its own rebalance
#: frequency is a robustness question worth being able to ask.
Cadence = Literal["monthly", "weekly", "daily"]


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
    rebalance: Cadence = Field(
        default="monthly",
        description=(
            "Rebalance cadence. Monthly matches the reference implementation; "
            "shorter cadences trade more and pay more cost for it."
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


def _period_key(session: date, cadence: Cadence) -> tuple[int, ...]:
    """
    The bucket a session falls into, for the cadence in force.

    ISO week rather than "day of year // 7": ISO weeks always start on Monday,
    so a weekly cadence rebalances on the first session of the week rather than
    drifting through the week as the year progresses.
    """
    if cadence == "monthly":
        return (session.year, session.month)
    if cadence == "weekly":
        iso = session.isocalendar()
        return (iso.year, iso.week)
    return (session.year, session.month, session.day)


@register
class AssetClassTrendFollowing(Strategy):
    """Equal-weight the asset classes currently in an uptrend; hold cash otherwise."""

    name = "asset_class_trend_following"
    version = "1.0"
    description = (
        "Hold each of five asset-class ETFs only while it trades above its "
        "10-month simple moving average, equal-weighted, rebalanced on the "
        "first trading day of each period (monthly by default). Anything not "
        "qualifying is cash."
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
        Rebalance on the first session of each period.

        The schedule is derived entirely from the sessions the driver actually
        presents, never from a separate calendar lookup. The driver walks
        sessions in order, so the first session whose period differs from the
        last rebalance's period *is* the first session of that period — whether
        the venue is NYSE with its holidays or a market that never closes. A
        calendar lookup would desynchronise the moment the two disagreed about
        what days exist.
        """
        if last_rebalance is None:
            return True
        return _period_key(session, self.params.rebalance) != _period_key(
            last_rebalance, self.params.rebalance
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
