"""
test_risk_gate.py
-----------------
The shared risk gate.

This code runs on both the backtest and the live path, so a bug here is a bug
that shows up as a profitable backtest and an unprofitable account. The most
important test is the first one: with default limits the gate must change
nothing, or every existing backtest silently starts measuring the gate instead
of the strategy.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from src.core.risk import (
    RiskCode,
    RiskLimits,
    RiskState,
    Severity,
    apply_risk,
    describe,
)
from src.core.types import PortfolioState, Position, TargetWeights

SESSION = date(2026, 3, 10)
NOW = datetime(2026, 3, 10, 21, 0, tzinfo=UTC)


def _portfolio(equity: str = "100000", **positions: str) -> PortfolioState:
    return PortfolioState(
        cash=Decimal(equity),
        positions={
            symbol: Position(symbol, Decimal(qty), Decimal("100"))
            for symbol, qty in positions.items()
        },
        equity=Decimal(equity),
        as_of=SESSION,
    )


def _state(**kwargs) -> RiskState:
    defaults = {
        "session": SESSION,
        "current_equity": Decimal("100000"),
        "day_start_equity": Decimal("100000"),
        "peak_equity": Decimal("100000"),
        "now": NOW,
    }
    return RiskState(**{**defaults, **kwargs})


class TestPermissiveDefaultIsANoOp:
    """
    The property that keeps every prior backtest honest. If the gate bound by
    default, results computed before it existed would no longer describe the
    same system.
    """

    def test_weights_pass_through_unchanged(self) -> None:
        targets = TargetWeights({"SPY": 0.5, "IEF": 0.3, "VNQ": 0.2})
        result = apply_risk(targets, _portfolio(), _state(), RiskLimits())
        assert result.weights.weights == targets.weights
        assert result.binding_events == ()
        assert not result.blocked

    def test_full_allocation_is_allowed(self) -> None:
        targets = TargetWeights({"SPY": 1.0})
        result = apply_risk(targets, _portfolio(), _state(), RiskLimits())
        assert result.weights.weights == {"SPY": 1.0}

    def test_stop_loss_is_off_unless_asked_for(self) -> None:
        """
        An 8% stop on a monthly rebalancer is a different strategy, not a
        safety feature. Enabling it silently would make every backtest describe
        something other than what runs.
        """
        state = _state(
            entry_prices={"SPY": Decimal("100")},
            current_prices={"SPY": Decimal("50")},  # 50% underwater
        )
        result = apply_risk(
            TargetWeights({"SPY": 1.0}), _portfolio(), state, RiskLimits()
        )
        assert result.weights.weights == {"SPY": 1.0}
        assert not any(e.code is RiskCode.STOP_LOSS for e in result.events)


class TestBlockingChecks:
    """A halt must mean flat, not frozen."""

    def test_kill_switch_liquidates_rather_than_freezing(self) -> None:
        """
        Freezing keeps whatever exposure caused the halt. "Stop trading" has to
        mean go to cash.
        """
        result = apply_risk(
            TargetWeights({"SPY": 1.0}),
            _portfolio(SPY="100"),
            _state(kill_switch_active=True),
            RiskLimits(),
        )
        assert result.blocked
        assert result.weights.weights == {}
        assert result.events[0].code is RiskCode.KILL_SWITCH

    def test_daily_loss_limit_halts(self) -> None:
        state = _state(
            day_start_equity=Decimal("100000"),
            current_equity=Decimal("99700"),  # -$300
        )
        result = apply_risk(
            TargetWeights({"SPY": 1.0}),
            _portfolio(),
            state,
            RiskLimits(max_daily_loss_usd=Decimal("200")),
        )
        assert result.blocked
        assert result.weights.weights == {}

    def test_daily_loss_uses_marked_equity_not_cash_flow(self) -> None:
        """
        Regression against the original implementation, which summed buy/sell
        cash flow — a $100 purchase read as a $100 loss, so the breaker tripped
        after two purchases regardless of performance.
        """
        # Bought $60k of stock: cash fell, but equity is unchanged.
        state = _state(
            day_start_equity=Decimal("100000"),
            current_equity=Decimal("100000"),
        )
        result = apply_risk(
            TargetWeights({"SPY": 0.6}),
            _portfolio(),
            state,
            RiskLimits(max_daily_loss_usd=Decimal("200")),
        )
        assert not result.blocked
        assert result.weights.weights == {"SPY": 0.6}

    def test_drawdown_limit_halts(self) -> None:
        state = _state(peak_equity=Decimal("120000"), current_equity=Decimal("100000"))
        result = apply_risk(
            TargetWeights({"SPY": 1.0}),
            _portfolio(),
            state,
            RiskLimits(max_drawdown_pct=0.15),
        )
        assert result.blocked
        assert result.events[0].code is RiskCode.DRAWDOWN_BREACH

    def test_drawdown_within_limit_passes(self) -> None:
        state = _state(peak_equity=Decimal("105000"), current_equity=Decimal("100000"))
        result = apply_risk(
            TargetWeights({"SPY": 1.0}),
            _portfolio(),
            state,
            RiskLimits(max_drawdown_pct=0.15),
        )
        assert not result.blocked


class TestConcentrationCap:
    def test_excess_becomes_cash_not_a_redistribution(self) -> None:
        """
        Redistributing would override the strategy's intent. If a trend model
        wants everything in the one asset above its average, capping means
        cash — not a spread across assets the model explicitly rejected.
        """
        result = apply_risk(
            TargetWeights({"SPY": 1.0}),
            _portfolio(),
            _state(),
            RiskLimits(max_weight_per_symbol=0.4),
        )
        assert result.weights.weights == {"SPY": 0.4}
        assert result.weights.cash_weight == pytest.approx(0.6)

    def test_denominator_is_equity_not_equity_plus_the_trade(self) -> None:
        """
        The original computed ``portfolio_total + proposed_amount``, inflating
        the denominator. That is right when adding new money and wrong for a
        rebalance, where the cash is already inside equity — it let positions
        exceed the stated cap.
        """
        result = apply_risk(
            TargetWeights({"SPY": 0.5, "IEF": 0.5}),
            _portfolio(),
            _state(),
            RiskLimits(max_weight_per_symbol=0.4),
        )
        assert result.weights.weights == {"SPY": 0.4, "IEF": 0.4}
        assert all(w <= 0.4 + 1e-9 for w in result.weights.weights.values())

    def test_uncapped_weights_are_untouched(self) -> None:
        result = apply_risk(
            TargetWeights({"SPY": 0.3, "IEF": 0.3}),
            _portfolio(),
            _state(),
            RiskLimits(max_weight_per_symbol=0.4),
        )
        assert result.binding_events == ()


class TestGrossExposure:
    def test_scaling_preserves_relative_preferences(self) -> None:
        """
        The gate limits size, not opinion. A strategy that wants twice as much
        SPY as IEF should still want twice as much after scaling.
        """
        result = apply_risk(
            TargetWeights({"SPY": 0.6, "IEF": 0.3}),
            _portfolio(),
            _state(),
            RiskLimits(max_gross_exposure=0.45),
        )
        weights = result.weights.weights
        assert sum(weights.values()) == pytest.approx(0.45)
        assert weights["SPY"] / weights["IEF"] == pytest.approx(2.0)

    def test_cash_buffer_holds_some_back(self) -> None:
        """
        A gap between decision and fill can otherwise produce an
        insufficient-buying-power rejection on an order the model wanted.
        """
        result = apply_risk(
            TargetWeights({"SPY": 1.0}),
            _portfolio(),
            _state(),
            RiskLimits(cash_buffer_pct=0.01),
        )
        assert sum(result.weights.weights.values()) == pytest.approx(0.99)
        assert any(e.code is RiskCode.CASH_BUFFER for e in result.events)


class TestStopLoss:
    def test_exits_a_position_past_the_stop(self) -> None:
        state = _state(
            entry_prices={"SPY": Decimal("100")},
            current_prices={"SPY": Decimal("90")},
        )
        result = apply_risk(
            TargetWeights({"SPY": 0.5, "IEF": 0.5}),
            _portfolio(),
            state,
            RiskLimits(stop_loss_pct=0.08),
        )
        assert "SPY" not in result.weights.weights
        assert result.weights.weights == {"IEF": 0.5}

    def test_leaves_a_position_within_the_stop(self) -> None:
        state = _state(
            entry_prices={"SPY": Decimal("100")},
            current_prices={"SPY": Decimal("95")},
        )
        result = apply_risk(
            TargetWeights({"SPY": 0.5}),
            _portfolio(),
            state,
            RiskLimits(stop_loss_pct=0.08),
        )
        assert result.weights.weights == {"SPY": 0.5}

    def test_missing_prices_do_not_trigger_a_stop(self) -> None:
        """Absence of data is not evidence of a loss."""
        result = apply_risk(
            TargetWeights({"SPY": 0.5}),
            _portfolio(),
            _state(),
            RiskLimits(stop_loss_pct=0.08),
        )
        assert result.weights.weights == {"SPY": 0.5}


class TestCooldown:
    def test_recent_trade_holds_the_current_weight(self) -> None:
        state = _state(
            last_trade_at={"SPY": NOW - timedelta(minutes=5)},
            current_prices={"SPY": Decimal("100")},
        )
        portfolio = PortfolioState(
            cash=Decimal("70000"),
            positions={"SPY": Position("SPY", Decimal("300"), Decimal("100"))},
            equity=Decimal("100000"),
            as_of=SESSION,
        )
        result = apply_risk(
            TargetWeights({"SPY": 0.8}),
            portfolio,
            state,
            RiskLimits(cooldown_minutes=15),
        )
        # Held at its present 30%, not moved to the requested 80%.
        assert result.weights.weights["SPY"] == pytest.approx(0.3)
        assert any(e.code is RiskCode.COOLDOWN for e in result.events)

    def test_expired_cooldown_allows_the_trade(self) -> None:
        state = _state(
            last_trade_at={"SPY": NOW - timedelta(minutes=30)},
            current_prices={"SPY": Decimal("100")},
        )
        result = apply_risk(
            TargetWeights({"SPY": 0.8}),
            _portfolio(),
            state,
            RiskLimits(cooldown_minutes=15),
        )
        assert result.weights.weights["SPY"] == pytest.approx(0.8)

    def test_zero_cooldown_is_disabled(self) -> None:
        state = _state(last_trade_at={"SPY": NOW})
        result = apply_risk(
            TargetWeights({"SPY": 0.8}), _portfolio(), state, RiskLimits()
        )
        assert result.weights.weights["SPY"] == pytest.approx(0.8)


class TestEventStream:
    def test_events_are_deterministic(self) -> None:
        """
        The event stream is compared between paths. Two runs reaching the same
        weights via different clamps is a divergence only the stream reveals,
        so its order must be stable.
        """
        # Sums to 1.0 — TargetWeights rejects anything above it as leverage,
        # so the cap has to be exercised within a legal allocation.
        args = (
            TargetWeights({"SPY": 0.6, "IEF": 0.4}),
            _portfolio(),
            _state(),
            RiskLimits(max_weight_per_symbol=0.3),
        )
        first, second = apply_risk(*args), apply_risk(*args)
        assert first.events == second.events
        assert len(first.binding_events) == 2, "both symbols should be clamped"

    def test_binding_is_distinguished_from_merely_evaluated(self) -> None:
        """A limit that never binds is not a limit that is working."""
        result = apply_risk(
            TargetWeights({"SPY": 0.2}),
            _portfolio(),
            _state(),
            RiskLimits(max_weight_per_symbol=0.5, stop_loss_pct=0.08),
        )
        assert result.binding_events == ()

    def test_describe_reports_only_binding_events(self) -> None:
        clean = apply_risk(
            TargetWeights({"SPY": 0.2}), _portfolio(), _state(), RiskLimits()
        )
        assert describe(clean.events) == "no risk limits bound"

        capped = apply_risk(
            TargetWeights({"SPY": 1.0}),
            _portfolio(),
            _state(),
            RiskLimits(max_weight_per_symbol=0.4),
        )
        assert "max_weight_clamp" in describe(capped.events)

    def test_blocking_event_is_marked_block(self) -> None:
        result = apply_risk(
            TargetWeights({"SPY": 1.0}),
            _portfolio(),
            _state(kill_switch_active=True),
            RiskLimits(),
        )
        assert result.events[0].severity is Severity.BLOCK
