"""
test_orders.py
--------------
The shared weights-to-orders conversion.

This code runs on both the backtest and live paths, so a bug here is a bug that
shows up as a profitable backtest and an unprofitable account.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from src.core.orders import (
    RebalanceConstraints,
    apply_concentration_cap,
    realised_weights,
    weights_to_orders,
)
from src.core.types import PortfolioState, Position, Side, TargetWeights

PRICES = {"SPY": 400.0, "IEF": 100.0, "VNQ": 80.0}


def _state(cash: str, equity: str, **positions: str) -> PortfolioState:
    return PortfolioState(
        cash=Decimal(cash),
        positions={
            symbol: Position(symbol, Decimal(qty), Decimal(str(PRICES[symbol])))
            for symbol, qty in positions.items()
        },
        equity=Decimal(equity),
        as_of=date(2020, 1, 2),
    )


class TestOrderGeneration:
    def test_allocates_from_all_cash(self) -> None:
        orders = weights_to_orders(
            _state("100000", "100000"), TargetWeights({"SPY": 0.5, "IEF": 0.5}), PRICES
        )
        by_symbol = {o.symbol: o for o in orders}
        assert by_symbol["SPY"].qty == Decimal("125.000000000")
        assert by_symbol["IEF"].qty == Decimal("500.000000000")
        assert all(o.side is Side.BUY for o in orders)

    def test_liquidates_symbols_absent_from_targets(self) -> None:
        state = _state("0", "100000", VNQ="625", SPY="125")
        orders = weights_to_orders(state, TargetWeights({"SPY": 1.0}), PRICES)
        vnq = [o for o in orders if o.symbol == "VNQ"]
        assert len(vnq) == 1
        assert vnq[0].side is Side.SELL
        assert vnq[0].qty == Decimal("625.000000000")

    def test_sells_are_emitted_before_buys(self) -> None:
        """Sells must settle first so their cash funds the buys."""
        state = _state("0", "100000", VNQ="625", SPY="125")
        orders = weights_to_orders(state, TargetWeights({"SPY": 1.0}), PRICES)
        sides = [o.side for o in orders]
        assert sides == sorted(sides, key=lambda s: 0 if s is Side.SELL else 1)

    def test_no_orders_when_already_on_target(self) -> None:
        state = _state("0", "100000", SPY="250")
        assert weights_to_orders(state, TargetWeights({"SPY": 1.0}), PRICES) == []

    def test_min_trade_suppresses_dust_churn(self) -> None:
        """A tiny drift must not generate a commissionable trade every month."""
        state = _state("10", "100000", SPY="249.98")
        orders = weights_to_orders(
            state,
            TargetWeights({"SPY": 1.0}),
            PRICES,
            RebalanceConstraints(min_trade_usd=Decimal("100")),
        )
        assert orders == []

    def test_never_sells_more_than_held(self) -> None:
        state = _state("0", "100000", SPY="10")
        orders = weights_to_orders(state, TargetWeights({}), PRICES)
        assert orders[0].qty <= Decimal("10")

    def test_symbol_without_a_price_is_skipped_not_guessed(self) -> None:
        state = _state("100000", "100000")
        orders = weights_to_orders(
            state, TargetWeights({"SPY": 0.5, "MISSING": 0.5}), PRICES
        )
        assert {o.symbol for o in orders} == {"SPY"}

    def test_zero_equity_produces_no_orders(self) -> None:
        state = PortfolioState(Decimal("0"), {}, Decimal("0"), date(2020, 1, 2))
        assert weights_to_orders(state, TargetWeights({"SPY": 1.0}), PRICES) == []

    def test_whole_share_venue_floors_quantities(self) -> None:
        orders = weights_to_orders(
            _state("100000", "100000"),
            TargetWeights({"SPY": 0.5}),
            {"SPY": 333.33},
            RebalanceConstraints(allow_fractional=False),
        )
        assert orders[0].qty == orders[0].qty.to_integral_value()

    def test_output_is_deterministic(self) -> None:
        state = _state("100000", "100000")
        targets = TargetWeights({"SPY": 0.3, "IEF": 0.3, "VNQ": 0.3})
        assert weights_to_orders(state, targets, PRICES) == weights_to_orders(
            state, targets, PRICES
        )


class TestConcentrationCap:
    def test_excess_becomes_cash_not_a_redistribution(self) -> None:
        """
        Redistributing would override the strategy's intent. If a trend model
        wants everything in the one asset above its average, capping means
        cash — not a spread across assets the model explicitly rejected.
        """
        capped = apply_concentration_cap(
            TargetWeights({"SPY": 1.0}), RebalanceConstraints(max_weight_per_asset=0.4)
        )
        assert capped.weights == {"SPY": 0.4}
        assert capped.cash_weight == pytest.approx(0.6)

    def test_cap_of_one_is_a_no_op(self) -> None:
        targets = TargetWeights({"SPY": 0.5, "IEF": 0.5})
        assert apply_concentration_cap(targets, RebalanceConstraints()) is targets


class TestTargetWeightValidation:
    def test_leverage_is_rejected_at_construction(self) -> None:
        with pytest.raises(ValueError, match="leverage"):
            TargetWeights({"SPY": 0.7, "IEF": 0.7})

    def test_negative_weight_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="[Nn]egative"):
            TargetWeights({"SPY": -0.1})

    def test_fully_invested_is_allowed(self) -> None:
        assert TargetWeights({"SPY": 0.5, "IEF": 0.5}).cash_weight == pytest.approx(0.0)


class TestRealisedWeights:
    def test_reports_actual_allocation(self) -> None:
        state = _state("50000", "100000", SPY="125")
        got = realised_weights(state, PRICES)
        assert got["SPY"] == pytest.approx(0.5)
