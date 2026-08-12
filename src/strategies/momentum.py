"""Long-only momentum strategies adapted to this engine's safety boundaries."""

from __future__ import annotations

from datetime import date

from pydantic import Field, field_validator, model_validator

from src.core.panel import PricePanel
from src.core.types import PortfolioState, TargetWeights
from src.strategies.base import Strategy, StrategyParams
from src.strategies.registry import register

TIME_SERIES_UNIVERSE = ("SPY", "EFA", "IEF", "VNQ", "GSG")
CROSS_SECTIONAL_UNIVERSE = (
    "XLB",
    "XLE",
    "XLF",
    "XLI",
    "XLK",
    "XLP",
    "XLU",
    "XLV",
    "XLY",
)


def _normalise_symbols(value: list[str]) -> list[str]:
    cleaned = [symbol.strip().upper() for symbol in value if symbol.strip()]
    if not cleaned:
        raise ValueError("symbols must contain at least one ticker")
    if len(set(cleaned)) != len(cleaned):
        raise ValueError(f"duplicate symbols in universe: {cleaned}")
    return cleaned


def _monthly_rebalance(session: date, last_rebalance: date | None) -> bool:
    return last_rebalance is None or (session.year, session.month) != (
        last_rebalance.year,
        last_rebalance.month,
    )


def _trailing_return(panel: PricePanel, symbol: str, lookback: int) -> float:
    prices = panel.series(symbol)
    return float(prices.iloc[-1] / prices.iloc[-lookback - 1] - 1.0)


class TimeSeriesMomentumParams(StrategyParams):
    symbols: list[str] = Field(default=list(TIME_SERIES_UNIVERSE), min_length=1)
    lookback_sessions: int = Field(default=252, ge=2, le=1000)
    max_weight_per_asset: float = Field(default=1.0, gt=0.0, le=1.0)

    _symbols = field_validator("symbols")(_normalise_symbols)


@register
class TimeSeriesMomentum(Strategy):
    """Equal-weight assets whose own trailing return is positive."""

    name = "time_series_momentum"
    description = (
        "Rebalance monthly and equal-weight assets with a positive trailing "
        "12-month adjusted return; hold the remainder in cash."
    )
    source = "Moskowitz, Ooi and Pedersen (2012), Time Series Momentum."
    params_model = TimeSeriesMomentumParams
    params: TimeSeriesMomentumParams

    def universe(self) -> list[str]:
        return list(self.params.symbols)

    @property
    def warmup_sessions(self) -> int:
        return self.params.lookback_sessions + 1

    def should_rebalance(
        self, session: date, last_rebalance: date | None
    ) -> bool:
        return _monthly_rebalance(session, last_rebalance)

    def target_weights(
        self, panel: PricePanel, state: PortfolioState, session: date
    ) -> TargetWeights:
        eligible = panel.available_symbols(
            self.params.symbols, self.warmup_sessions
        )
        winners = [
            symbol
            for symbol in eligible
            if _trailing_return(panel, symbol, self.params.lookback_sessions) > 0
        ]
        if not winners:
            return TargetWeights({}, f"{session}: no positive trailing returns.")

        weight = min(1.0 / len(winners), self.params.max_weight_per_asset)
        return TargetWeights(
            {symbol: weight for symbol in sorted(winners)},
            f"{session}: positive momentum in {', '.join(sorted(winners))}.",
        )


class CrossSectionalMomentumParams(StrategyParams):
    symbols: list[str] = Field(
        default=list(CROSS_SECTIONAL_UNIVERSE), min_length=2
    )
    lookback_sessions: int = Field(default=252, ge=2, le=1000)
    top_n: int = Field(default=3, ge=1)

    _symbols = field_validator("symbols")(_normalise_symbols)

    @model_validator(mode="after")
    def _top_n_fits_universe(self) -> CrossSectionalMomentumParams:
        if self.top_n > len(self.symbols):
            raise ValueError("top_n cannot exceed the number of symbols")
        return self


@register
class CrossSectionalMomentum(Strategy):
    """Equal-weight the strongest assets relative to their peers."""

    name = "cross_sectional_momentum"
    description = (
        "Rebalance monthly, rank the universe by trailing 12-month adjusted "
        "return and equal-weight the strongest assets. Long-only adaptation."
    )
    source = (
        "Jegadeesh and Titman (1993), Returns to Buying Winners and "
        "Selling Losers."
    )
    params_model = CrossSectionalMomentumParams
    params: CrossSectionalMomentumParams

    def universe(self) -> list[str]:
        return list(self.params.symbols)

    @property
    def warmup_sessions(self) -> int:
        return self.params.lookback_sessions + 1

    def should_rebalance(
        self, session: date, last_rebalance: date | None
    ) -> bool:
        return _monthly_rebalance(session, last_rebalance)

    def target_weights(
        self, panel: PricePanel, state: PortfolioState, session: date
    ) -> TargetWeights:
        eligible = panel.available_symbols(
            self.params.symbols, self.warmup_sessions
        )
        ranked = sorted(
            eligible,
            key=lambda symbol: (
                -_trailing_return(panel, symbol, self.params.lookback_sessions),
                symbol,
            ),
        )
        selected = ranked[: self.params.top_n]
        if not selected:
            return TargetWeights({}, f"{session}: no assets have full history.")

        weight = 1.0 / len(selected)
        return TargetWeights(
            {symbol: weight for symbol in sorted(selected)},
            f"{session}: top-ranked assets are {', '.join(selected)}.",
        )
