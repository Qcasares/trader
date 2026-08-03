"""
buy_and_hold.py
---------------
Equal-weight the universe and leave it alone.

This exists because the promotion gates require one. Gate 1 -> 2 will not pass
a candidate without a benchmark comparison, and a benchmark that is not
runnable by the same engine, over the same window, under the same cost model,
is not a comparison — it is a number quoted from somewhere else.

So it is deliberately the dullest strategy that can be written: buy the
universe in equal weights on the first session each symbol is available, and
rebalance only when the drift band is breached. Anything cleverer would make it
a competitor rather than a floor.

Two details matter for the comparison to be fair:

* Availability is honoured exactly as it is everywhere else in this system. A
  symbol that has not listed is excluded from the denominator, not held at
  zero — otherwise the benchmark holds cash the strategy under test does not,
  and beating it means nothing.
* Rebalancing is banded rather than periodic. A calendar rebalance would give
  the benchmark a turnover the strategy under test does not have, and
  therefore a cost the comparison would silently attribute to being passive.
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
    drift_band: float = Field(
        default=0.05,
        ge=0.0,
        le=1.0,
        description=(
            "Rebalance once any holding's weight differs from its target by "
            "more than this. Zero rebalances every session, which is a "
            "different strategy and a much more expensive one."
        ),
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
    """Equal-weight the available universe; trade only to correct drift."""

    name = "buy_and_hold"
    version = "1.0"
    description = (
        "Equal-weight every symbol that has listed, and rebalance only when a "
        "holding drifts outside the band. The benchmark the promotion gates "
        "compare against."
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
        Every session is a candidate; the weights decide whether anything moves.

        Returning ``True`` here and letting :meth:`target_weights` emit the
        same weights as yesterday costs nothing: the order sizer turns an
        unchanged target into no order. The alternative — deciding the band
        here — would need the portfolio state, which this method is not given,
        and inventing a calendar for it would give the benchmark a turnover it
        does not have.
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
        weights = {symbol: target for symbol in available}

        # Hold the current book unless something has drifted out of band. The
        # equity may be zero on the first session, before any mark exists; the
        # band cannot be evaluated then, so buy in.
        equity = float(state.equity or 0.0)
        if equity <= 0.0:
            return TargetWeights(weights)

        current: dict[str, float] = {}
        for symbol in available:
            # Raw close, not adjusted: this is a money question, and the
            # adjusted series disagrees with the broker by the cumulative
            # dividend adjustment.
            price = panel.latest(symbol, field="close")
            quantity = float(state.qty_of(symbol))
            current[symbol] = (
                (quantity * float(price)) / equity if price is not None else 0.0
            )

        drifted = any(
            abs(current[symbol] - target) > self.params.drift_band
            for symbol in available
        )
        return TargetWeights(weights if drifted else current)
