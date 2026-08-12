from __future__ import annotations

from datetime import date
from decimal import Decimal

import pandas as pd
import pytest

from src.core.panel import PricePanel
from src.core.types import PortfolioState
from src.strategies import build_strategy, list_strategies


def _panel(series: dict[str, list[float]]) -> PricePanel:
    sessions = pd.bdate_range("2024-01-02", periods=len(next(iter(series.values()))))
    rows = []
    for symbol, prices in series.items():
        rows.extend(
            (
                symbol,
                session.date(),
                price,
                price,
                price,
                price,
                1_000_000.0,
                price,
            )
            for session, price in zip(sessions, prices, strict=True)
        )
    return PricePanel.from_bars(rows)


def _state(session: date) -> PortfolioState:
    return PortfolioState(
        cash=Decimal("100000"),
        positions={},
        equity=Decimal("100000"),
        as_of=session,
    )


def test_momentum_strategies_are_registered() -> None:
    assert {"time_series_momentum", "cross_sectional_momentum"} <= set(
        list_strategies()
    )


def test_time_series_momentum_holds_only_positive_trends() -> None:
    panel = _panel({"UP": [100, 105, 110], "DOWN": [100, 95, 90]})
    strategy = build_strategy(
        "time_series_momentum",
        {"symbols": ["UP", "DOWN"], "lookback_sessions": 2},
    )

    target = strategy.target_weights(panel, _state(panel.as_of), panel.as_of)

    assert target.weights == {"UP": 1.0}
    assert target.cash_weight == 0.0


def test_time_series_momentum_holds_cash_without_positive_trends() -> None:
    panel = _panel({"FLAT": [100, 100, 100], "DOWN": [100, 95, 90]})
    strategy = build_strategy(
        "time_series_momentum",
        {"symbols": ["FLAT", "DOWN"], "lookback_sessions": 2},
    )

    target = strategy.target_weights(panel, _state(panel.as_of), panel.as_of)

    assert target.weights == {}
    assert target.cash_weight == 1.0


def test_cross_sectional_momentum_holds_the_top_ranked_assets() -> None:
    panel = _panel(
        {
            "BEST": [100, 110, 130],
            "SECOND": [100, 105, 115],
            "LAST": [100, 99, 101],
        }
    )
    strategy = build_strategy(
        "cross_sectional_momentum",
        {
            "symbols": ["LAST", "BEST", "SECOND"],
            "lookback_sessions": 2,
            "top_n": 2,
        },
    )

    target = strategy.target_weights(panel, _state(panel.as_of), panel.as_of)

    assert target.weights == {"BEST": 0.5, "SECOND": 0.5}


def test_cross_sectional_momentum_excludes_incomplete_history() -> None:
    panel = _panel({"FULL": [100, 110, 120], "SHORT": [float("nan"), 100, 200]})
    strategy = build_strategy(
        "cross_sectional_momentum",
        {"symbols": ["FULL", "SHORT"], "lookback_sessions": 2, "top_n": 1},
    )

    target = strategy.target_weights(panel, _state(panel.as_of), panel.as_of)

    assert target.weights == {"FULL": 1.0}


def test_momentum_parameters_reject_duplicate_symbols() -> None:
    with pytest.raises(ValueError, match="duplicate symbols"):
        build_strategy("time_series_momentum", {"symbols": ["spy", "SPY"]})


def test_momentum_rebalances_once_per_month() -> None:
    strategy = build_strategy("time_series_momentum")
    assert strategy.should_rebalance(date(2026, 2, 2), date(2026, 1, 30))
    assert not strategy.should_rebalance(date(2026, 2, 3), date(2026, 2, 2))
