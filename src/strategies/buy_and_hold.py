"""
buy_and_hold.py
---------------
Equal-weight the universe and leave it alone.

This exists because the promotion gates require one. Gate 1 -> 2 will not pass
a candidate without a benchmark comparison, and a benchmark that is not
runnable by the same engine, over the same window, under the same cost model,
is not a comparison — it is a number quoted from somewhere else.

So it is deliberately the dullest strategy that can be written: hold the
universe in equal weights from the first session each symbol is available.
Anything cleverer would make it a competitor rather than a floor.

Two details matter for the comparison to be fair:

* Availability is honoured exactly as it is everywhere else in this system. A
  symbol that has not listed is excluded from the denominator, not held at
  zero — otherwise the benchmark holds cash the strategy under test does not,
  and beating it means nothing.
* The target never changes, so the benchmark's turnover is whatever price
  drift forces through the sizer's minimum-trade threshold and no more. A
  calendar rebalance would give it a turnover the strategy under test does not
  have, and therefore a cost the comparison would silently attribute to being
  passive.
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

DEFAULT_UNIVERSE: tuple[str, ...] = ("SPY",)


class BuyAndHoldParams(StrategyParams):
    """Tunable parameters."""

    symbols: list[str] = Field(
        default=list(DEFAULT_UNIVERSE),
        min_length=1,
        description="Symbols to hold in equal weight.",
    )
    min_history: int = Field(
        default=1,
        ge=1,
        le=1000,
        description=(
            "Sessions of history a symbol needs before it is bought. Kept at "
            "one so the benchmark is invested as early as the data allows."
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
class BuyAndHold(Strategy):
    """Equal-weight the available universe, and otherwise do nothing."""

    name = "buy_and_hold"
    version = "1.0"
    description = (
        "Equal-weight every symbol that has listed and hold it. The benchmark "
        "the promotion gates compare against."
    )
    source = "Benchmark floor; no external reference."
    params_model = BuyAndHoldParams

    params: BuyAndHoldParams

    def universe(self) -> list[str]:
        return list(self.params.symbols)

    @property
    def warmup_sessions(self) -> int:
        return self.params.min_history

    def should_rebalance(
        self, session: date, last_rebalance: date | None
    ) -> bool:
        """
        Every session is a candidate, and almost none of them trade.

        There is deliberately no drift band here and none in
        :meth:`target_weights`. The target never changes, so once the book
        matches it the sizer's minimum-trade threshold suppresses the small
        deltas that price movement creates — which *is* a drift band,
        implemented in the one place that knows both the current book and the
        current prices.

        An earlier version returned the *current* weights when nothing had
        drifted, and it was wrong in a way worth recording: current weights are
        position value at today's close over equity marked at whenever the
        broker last marked. On the live path those are different moments, so
        the weights could sum above one and trip the leverage guard in
        ``TargetWeights``. Shadow mode found it on its fourth session.
        """
        return True

    def target_weights(
        self,
        panel: PricePanel,
        state: PortfolioState,
        session: date,
    ) -> TargetWeights:
        available = [
            symbol
            for symbol in self.params.symbols
            if panel.is_available(symbol, min_history=self.params.min_history)
        ]
        if not available:
            return TargetWeights({})

        target = 1.0 / len(available)
        return TargetWeights({symbol: target for symbol in available})
