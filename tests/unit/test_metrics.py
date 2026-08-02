"""
test_metrics.py
---------------
Performance statistics, including the Sharpe error bar.

The significance check is the one that matters commercially: it is what stops a
backtest reporting "Sharpe 0.50" from being read as evidence when five years of
daily data cannot distinguish 0.50 from zero.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from src.engine.metrics import (
    annualised_return,
    annualised_volatility,
    compute_metrics,
    drawdown_series,
    max_drawdown,
    sharpe_ratio,
    sharpe_standard_error,
    sortino_ratio,
)


def _curve(values: list[float]) -> pd.Series:
    return pd.Series(values, index=pd.bdate_range("2020-01-01", periods=len(values)))


class TestReturnAndVolatility:
    def test_flat_curve_has_zero_return_and_vol(self) -> None:
        curve = _curve([100.0] * 100)
        assert annualised_return(curve) == pytest.approx(0.0)
        assert annualised_volatility(curve.pct_change().dropna()) == pytest.approx(0.0)

    def test_doubling_in_one_year_is_100pc_cagr(self) -> None:
        curve = pd.Series(
            np.linspace(100, 200, 253),
            index=pd.bdate_range("2020-01-01", periods=253),
        )
        assert annualised_return(curve) == pytest.approx(1.0, abs=0.01)

    def test_volatility_annualises_by_root_252(self) -> None:
        rng = np.random.default_rng(42)
        daily = pd.Series(rng.normal(0, 0.01, 5000))
        assert annualised_volatility(daily) == pytest.approx(
            0.01 * math.sqrt(252), rel=0.05
        )


class TestSharpe:
    def test_zero_volatility_gives_zero_not_infinity(self) -> None:
        assert sharpe_ratio(pd.Series([0.001] * 50)) == 0.0

    def test_positive_drift_gives_positive_sharpe(self) -> None:
        rng = np.random.default_rng(7)
        returns = pd.Series(rng.normal(0.0005, 0.01, 2520))
        assert sharpe_ratio(returns) > 0

    def test_standard_error_matches_lo_2002(self) -> None:
        """
        Five years of daily data at Sharpe 0.5 gives SE ~0.45 annualised.
        SE(SR_period) = sqrt((1 + SR_period^2/2) / T), scaled by sqrt(252).
        """
        se = sharpe_standard_error(0.5, n_observations=1260)
        assert se == pytest.approx(0.447, abs=0.01)

    def test_standard_error_shrinks_with_more_data(self) -> None:
        short = sharpe_standard_error(0.5, 252)
        long = sharpe_standard_error(0.5, 252 * 20)
        assert long < short
        assert long == pytest.approx(short / math.sqrt(20), rel=0.02)

    def test_sharpe_of_half_over_five_years_is_not_significant(self) -> None:
        """
        The honesty check. A 0.5 Sharpe on five years of daily data is inside
        two standard errors of zero, so it is not evidence of anything.
        """
        metrics = _metrics_with(sharpe=0.5, n=1260)
        assert not metrics.sharpe_is_significant

    def test_a_strong_long_history_sharpe_is_significant(self) -> None:
        metrics = _metrics_with(sharpe=1.2, n=252 * 20)
        assert metrics.sharpe_is_significant


class TestDrawdown:
    def test_monotonic_rise_has_no_drawdown(self) -> None:
        assert max_drawdown(_curve([100.0 + i for i in range(50)]))[0] == pytest.approx(
            0.0
        )

    def test_halving_is_a_fifty_percent_drawdown(self) -> None:
        worst, peak, trough = max_drawdown(_curve([100, 120, 60, 90]))
        assert worst == pytest.approx(-0.5)
        assert peak is not None and trough is not None
        assert peak < trough

    def test_drawdown_series_is_never_positive(self) -> None:
        rng = np.random.default_rng(3)
        curve = _curve(list(100 * np.exp(np.cumsum(rng.normal(0, 0.01, 500)))))
        assert (drawdown_series(curve) <= 1e-12).all()


class TestSortino:
    def test_no_downside_returns_zero(self) -> None:
        assert sortino_ratio(pd.Series([0.01] * 50)) == 0.0

    def test_sortino_exceeds_sharpe_when_downside_is_rare(self) -> None:
        returns = pd.Series([0.02] * 90 + [-0.01] * 10)
        assert sortino_ratio(returns) > sharpe_ratio(returns)


class TestComputeMetrics:
    def test_empty_curve_does_not_raise(self) -> None:
        metrics = compute_metrics(pd.Series(dtype=float))
        assert metrics.n_sessions == 0
        assert metrics.sharpe_stderr == float("inf")
        assert not metrics.sharpe_is_significant

    def test_cost_multiplier_is_recorded_on_the_result(self) -> None:
        """A performance number without its cost assumption is not a number."""
        metrics = compute_metrics(
            _curve([100.0, 101.0, 102.0]), cost_stress_multiplier=3.0
        )
        assert metrics.cost_stress_multiplier == 3.0
        assert metrics.to_dict()["cost_stress_multiplier"] == 3.0

    def test_exposure_reflects_time_in_market(self) -> None:
        equity = _curve([100.0] * 10)
        invested = _curve([50.0] * 10)
        got = compute_metrics(equity, invested_value=invested)
        assert got.exposure == pytest.approx(0.5)

    def test_effective_start_is_carried_through(self) -> None:
        from datetime import date

        metrics = compute_metrics(
            _curve([100.0, 101.0]), effective_start=date(2007, 5, 9)
        )
        assert metrics.effective_start == date(2007, 5, 9)
        assert metrics.to_dict()["effective_start"] == "2007-05-09"


def _metrics_with(sharpe: float, n: int):
    """Synthesise a curve with an approximately known Sharpe."""
    rng = np.random.default_rng(11)
    daily_sr = sharpe / math.sqrt(252)
    sigma = 0.01
    returns = rng.normal(daily_sr * sigma, sigma, n)
    curve = pd.Series(
        100 * np.cumprod(1 + returns), index=pd.bdate_range("2000-01-03", periods=n)
    )
    return compute_metrics(curve)


def test_the_api_schema_declares_every_engine_metric() -> None:
    """
    Pydantic drops undeclared fields, so a metric the engine computes can be
    silently absent from the API response.

    That happened: ``periods_per_year`` was added to ``PerformanceMetrics``,
    stored in the database, rendered by the UI — and stripped in between,
    because ``BacktestMetrics`` never declared it. The UI's ``?? 252`` fallback
    hid it, and every existing test checked specific keys rather than the whole
    surface.

    Comparing the two as sets means the next added metric fails here rather
    than disappearing quietly.
    """
    pytest.importorskip("fastapi")
    from src.api.schemas import BacktestMetrics

    computed = set(compute_metrics(pd.Series(dtype=float)).to_dict())
    declared = set(BacktestMetrics.model_fields)

    # sharpe_is_significant is derived in to_dict() rather than being a field;
    # it is declared on the schema, so it appears in both.
    missing = computed - declared
    assert not missing, (
        f"the engine computes {sorted(missing)} and the API schema would drop "
        "them from every response"
    )
