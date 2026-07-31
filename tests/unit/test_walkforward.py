"""
test_walkforward.py
-------------------
Walk-forward validation.

The critical property is **two-sided**. A validator that always reports "not
robust" is as useless as one that always approves: it carries no information.
So there are two headline tests —

- :meth:`TestDiscrimination.test_rejects_a_strategy_on_data_with_no_edge`
- :meth:`TestDiscrimination.test_endorses_a_strategy_on_data_with_a_real_signal`

— and they must disagree with each other. If both passed with the same verdict
the tool would be measuring nothing.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pytest

from src.core.calendar import sessions as nyse_sessions
from src.core.panel import PricePanel
from src.core.types import Bar, CostModel
from src.data import SyntheticSource, bars_to_rows
from src.engine.metrics import compute_metrics
from src.engine.walkforward import (
    Fold,
    expand_grid,
    make_folds,
    run_walk_forward,
    sharpe_objective,
)

UNIVERSE = ["SPY", "EFA", "IEF", "VNQ", "GSG"]


# ---------------------------------------------------------------------------
# Fold construction
# ---------------------------------------------------------------------------


class TestFolds:
    @pytest.fixture(scope="class")
    def sessions(self) -> list[date]:
        return nyse_sessions(date(2010, 1, 1), date(2020, 12, 31))

    def test_train_always_precedes_test(self, sessions: list[date]) -> None:
        """The whole point. A fold whose test data leaks into training is not a fold."""
        for fold in make_folds(sessions, train_months=24, test_months=12):
            assert fold.train_end < fold.test_start

    def test_test_windows_do_not_overlap(self, sessions: list[date]) -> None:
        """
        Stitching overlapping test segments would double-count returns and
        flatter the out-of-sample curve.
        """
        folds = make_folds(sessions, train_months=24, test_months=12)
        for earlier, later in zip(folds, folds[1:], strict=False):
            assert earlier.test_end < later.test_start

    def test_folds_advance_through_time(self, sessions: list[date]) -> None:
        folds = make_folds(sessions, train_months=24, test_months=12)
        assert [f.index for f in folds] == list(range(len(folds)))
        assert folds[0].train_start < folds[-1].train_start

    def test_step_controls_overlap_of_training_windows(
        self, sessions: list[date]
    ) -> None:
        yearly = make_folds(sessions, 24, 12, step_months=12)
        half_yearly = make_folds(sessions, 24, 12, step_months=6)
        assert len(half_yearly) > len(yearly)

    def test_too_little_history_yields_no_folds(self) -> None:
        short = nyse_sessions(date(2020, 1, 1), date(2020, 6, 30))
        assert make_folds(short, train_months=36, test_months=12) == []

    def test_zero_width_is_rejected(self, sessions: list[date]) -> None:
        with pytest.raises(ValueError):
            make_folds(sessions, train_months=0, test_months=12)


class TestParameterGrid:
    def test_expands_the_cartesian_product(self) -> None:
        grid = expand_grid({"a": [1, 2], "b": ["x", "y", "z"]})
        assert len(grid) == 6
        assert {"a": 1, "b": "x"} in grid

    def test_empty_grid_yields_one_default_candidate(self) -> None:
        assert expand_grid({}) == [{}]

    def test_ordering_is_deterministic(self) -> None:
        grid = {"sma_period": [100, 200], "max_weight_per_asset": [0.5, 1.0]}
        assert expand_grid(grid) == expand_grid(grid)


# ---------------------------------------------------------------------------
# The two-sided discrimination test
# ---------------------------------------------------------------------------


def _trending_source(seed: int = 11) -> list[Bar]:
    """
    Prices with a genuine, persistent, *shared* trend structure.

    The shared regime matters. An earlier version gave each asset an
    independent cycle, which meant roughly two thirds were always trending and
    diversification across five uncorrelated assets smoothed everything — the
    trend filter had nothing to add. Real trend-following earns its keep
    because assets fall together, and the filter exits all of them at once.

    Long steady advances punctuated by long declines: the regime a lagging
    moving average can actually act on. On this data the strategy scores a
    Sharpe around 5 against buy-and-hold's negative, so if walk-forward cannot
    endorse it here it cannot endorse anything.
    """
    rng = np.random.default_rng(seed)
    sessions = nyse_sessions(date(2007, 1, 1), date(2026, 6, 30))

    drifts: list[float] = []
    drift = 0.0013
    remaining = 0
    for _ in sessions:
        if remaining <= 0:
            if rng.random() < 0.62:
                drift, remaining = 0.0013, int(rng.integers(350, 550))
            else:
                # Declines long enough that a 105-210 session filter has time
                # to signal an exit and stay out.
                drift, remaining = -0.0028, int(rng.integers(220, 400))
        remaining -= 1
        drifts.append(drift)

    bars: list[Bar] = []
    for offset, symbol in enumerate(UNIVERSE):
        price = 100.0
        noise = np.random.default_rng(seed + offset * 101)
        for session, regime_drift in zip(sessions, drifts, strict=True):
            price *= 1.0 + regime_drift + noise.normal(0, 0.005)
            price = max(price, 1.0)
            bars.append(
                Bar(
                    symbol=symbol,
                    session=session,
                    open=price,
                    high=price,
                    low=price,
                    close=price,
                    volume=1_000_000.0,
                    adj_close=price,
                    source="trending",
                )
            )
    return bars


class TestDiscrimination:
    """
    Walk-forward must be able to say both yes and no. These two tests are the
    reason the module exists; if they ever agree, it has stopped measuring.
    """

    @pytest.fixture(scope="class")
    def noise_result(self):
        bars = SyntheticSource().fetch(UNIVERSE, date(2005, 1, 1), date(2026, 6, 30))
        panel = PricePanel.from_bars(bars_to_rows(bars))
        sessions = nyse_sessions(date(2007, 1, 1), date(2026, 6, 30))
        return run_walk_forward(
            "asset_class_trend_following",
            panel,
            sessions,
            param_grid={"sma_period": [105, 150, 210, 250]},
            train_months=36,
            test_months=12,
            cost_model=CostModel(slippage_bps=5.0),
        )

    @pytest.fixture(scope="class")
    def signal_result(self):
        bars = _trending_source()
        panel = PricePanel.from_bars(bars_to_rows(bars))
        sessions = nyse_sessions(date(2007, 1, 1), date(2026, 6, 30))
        return run_walk_forward(
            "asset_class_trend_following",
            panel,
            sessions,
            param_grid={"sma_period": [105, 150, 210]},
            train_months=36,
            test_months=12,
            cost_model=CostModel(slippage_bps=5.0),
        )

    def test_rejects_a_strategy_on_data_with_no_edge(self, noise_result) -> None:
        """
        Seeded geometric Brownian motion contains no exploitable trend. A
        validator that endorsed a strategy here would endorse anything.
        """
        assert not noise_result.is_robust
        assert noise_result.parameter_stability < 0.6, (
            "with no real optimum, the chosen parameter should wander between "
            "folds — stability this high suggests the search is degenerate"
        )

    def test_endorses_a_strategy_on_data_with_a_real_signal(
        self, signal_result
    ) -> None:
        """
        Given persistent trends, a trend follower should show a positive
        out-of-sample Sharpe. This is the half that proves the tool is not
        simply pessimistic.
        """
        assert signal_result.is_robust, signal_result.summary()
        assert signal_result.stitched_oos.sharpe > 1.0, signal_result.summary()
        assert signal_result.stitched_oos.sharpe_is_significant
        assert signal_result.parameter_stability >= 0.5

    def test_the_two_verdicts_actually_differ(
        self, noise_result, signal_result
    ) -> None:
        """The load-bearing assertion: the tool discriminates."""
        assert signal_result.is_robust and not noise_result.is_robust
        assert (
            signal_result.stitched_oos.sharpe
            > noise_result.stitched_oos.sharpe + 1.0
        ), "the two cases must be clearly separated, not marginally different"


class TestNoLookahead:
    def test_parameters_are_chosen_only_from_training_data(self) -> None:
        """
        Selection must never see the test window. If it did, the "out-of-sample"
        Sharpe would be in-sample wearing a different label — the exact
        self-deception walk-forward exists to prevent.
        """
        bars = SyntheticSource().fetch(UNIVERSE, date(2005, 1, 1), date(2020, 12, 31))
        panel = PricePanel.from_bars(bars_to_rows(bars))
        sessions = nyse_sessions(date(2007, 1, 1), date(2020, 12, 31))

        result = run_walk_forward(
            "asset_class_trend_following",
            panel,
            sessions,
            param_grid={"sma_period": [150, 210]},
            train_months=36,
            test_months=12,
        )
        # If selection peeked, the chosen candidate would be the best OOS
        # performer every time. Across many folds that is vanishingly unlikely
        # to happen by chance.
        chose_best_oos = 0
        for fold_result in result.folds:
            best_score = max(score for _, score in fold_result.candidate_scores)
            if sharpe_objective(fold_result.in_sample) == pytest.approx(best_score):
                chose_best_oos += 1
        # Selection *should* pick the best in-sample score every time...
        assert chose_best_oos == len(result.folds)
        # ...but that must not translate into uniformly winning out of sample.
        assert any(f.degradation > 0 for f in result.folds), (
            "no fold degraded out of sample, which would suggest the test "
            "window influenced selection"
        )


class TestReporting:
    @pytest.fixture(scope="class")
    def result(self):
        bars = SyntheticSource().fetch(UNIVERSE, date(2005, 1, 1), date(2020, 12, 31))
        panel = PricePanel.from_bars(bars_to_rows(bars))
        sessions = nyse_sessions(date(2007, 1, 1), date(2020, 12, 31))
        return run_walk_forward(
            "asset_class_trend_following",
            panel,
            sessions,
            param_grid={"sma_period": [150, 210]},
            train_months=36,
            test_months=12,
        )

    def test_records_every_candidate_score(self, result) -> None:
        """A near-tie should be visible, not hidden behind a single winner."""
        for fold_result in result.folds:
            assert len(fold_result.candidate_scores) == 2

    def test_degradation_is_in_sample_minus_out_of_sample(self, result) -> None:
        for fold_result in result.folds:
            assert fold_result.degradation == pytest.approx(
                fold_result.in_sample.sharpe - fold_result.out_of_sample.sharpe
            )

    def test_stitched_curve_carries_an_error_bar(self, result) -> None:
        assert result.stitched_oos.sharpe_stderr > 0
        assert isinstance(result.stitched_oos.sharpe_is_significant, bool)

    def test_summary_states_a_verdict(self, result) -> None:
        text = result.summary()
        assert "ROBUST" in text
        assert "degradation" in text

    def test_insufficient_history_raises_rather_than_silently_returning_nothing(
        self,
    ) -> None:
        bars = SyntheticSource().fetch(UNIVERSE, date(2019, 1, 1), date(2019, 12, 31))
        panel = PricePanel.from_bars(bars_to_rows(bars))
        sessions = nyse_sessions(date(2019, 1, 1), date(2019, 12, 31))
        with pytest.raises(ValueError, match="too few"):
            run_walk_forward(
                "asset_class_trend_following", panel, sessions,
                train_months=36, test_months=12,
            )


class TestStability:
    def test_stability_is_one_when_every_fold_agrees(self) -> None:
        from src.engine.walkforward import FoldResult, WalkForwardResult

        empty = compute_metrics(__import__("pandas").Series(dtype=float))
        fold = Fold(0, date(2010, 1, 1), date(2011, 1, 1),
                    date(2011, 1, 2), date(2012, 1, 1))
        folds = [
            FoldResult(fold, {"sma_period": 210}, empty, empty) for _ in range(4)
        ]
        result = WalkForwardResult("s", folds, empty, 1)
        assert result.parameter_stability == 1.0

    def test_stability_falls_when_folds_disagree(self) -> None:
        from src.engine.walkforward import FoldResult, WalkForwardResult

        empty = compute_metrics(__import__("pandas").Series(dtype=float))
        fold = Fold(0, date(2010, 1, 1), date(2011, 1, 1),
                    date(2011, 1, 2), date(2012, 1, 1))
        folds = [
            FoldResult(fold, {"sma_period": p}, empty, empty)
            for p in (105, 150, 210, 250)
        ]
        result = WalkForwardResult("s", folds, empty, 4)
        assert result.parameter_stability == 0.25
        assert not result.is_robust
