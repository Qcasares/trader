"""
test_statistics.py
------------------
The statistics that decide whether a backtest is evidence.

Each is driven against a case where the right answer is known by construction
rather than by running the function and writing down what it said. A test that
records current behaviour cannot tell a correct implementation from a
plausible one, and these four numbers are the ones a promotion rests on.

The recurring theme is ``None``. Every function here returns it rather than a
number when the question cannot be answered, and several tests exist only to
assert that — because a probability of overfitting reported as 0.0 when it is
actually unmeasurable is the most dangerous single value this module could
produce.
"""

from __future__ import annotations

import math
import random

import pytest

from src.engine.statistics import (
    DEFAULT_PARTICIPATION_RATE,
    MAX_PBO_SPLITS,
    capacity_estimate,
    days_to_exit,
    deflated_sharpe_ratio,
    expected_max_sharpe,
    probability_of_backtest_overfitting,
    sharpe_moments,
)


class TestExpectedMaxSharpe:
    def test_one_trial_expects_nothing(self) -> None:
        """With a single attempt there is no selection to correct for."""
        assert expected_max_sharpe(1, 0.25) == 0.0

    def test_zero_dispersion_expects_nothing(self) -> None:
        """
        A grid whose members all score identically has no room for a lucky
        winner, however many members it has.
        """
        assert expected_max_sharpe(100, 0.0) == 0.0

    def test_more_trials_raise_the_bar(self) -> None:
        assert expected_max_sharpe(50, 0.25) > expected_max_sharpe(5, 0.25)

    def test_more_dispersion_raises_the_bar(self) -> None:
        assert expected_max_sharpe(20, 1.0) > expected_max_sharpe(20, 0.1)

    def test_it_scales_with_the_standard_deviation(self) -> None:
        """Doubling the standard deviation doubles the expected maximum."""
        one = expected_max_sharpe(20, 1.0)
        four = expected_max_sharpe(20, 4.0)
        assert four == pytest.approx(2.0 * one)


class TestDeflatedSharpe:
    def _dsr(self, **overrides: float) -> float | None:
        kwargs: dict[str, float] = {
            "sharpe": 0.10,
            "n_observations": 1000,
            "skew": 0.0,
            "kurtosis": 3.0,
            "n_trials": 1,
            "sharpe_variance": 0.0,
        }
        kwargs.update(overrides)
        return deflated_sharpe_ratio(**kwargs)  # type: ignore[arg-type]

    def test_a_strong_result_from_one_trial_is_confident(self) -> None:
        assert (self._dsr() or 0.0) > 0.99

    def test_a_zero_sharpe_sits_at_a_coin_toss(self) -> None:
        """
        With no selection to correct for and no skew, a Sharpe of exactly zero
        gives a probability of exactly one half. A closed-form check rather
        than a recorded output.
        """
        assert self._dsr(sharpe=0.0) == pytest.approx(0.5)

    def test_searching_harder_deflates_it(self) -> None:
        one = self._dsr(n_trials=1, sharpe_variance=0.01)
        many = self._dsr(n_trials=200, sharpe_variance=0.01)
        assert one is not None and many is not None
        assert many < one

    def test_the_same_sharpe_can_flip_from_evidence_to_nothing(self) -> None:
        """
        The point of the statistic. One attempt at this Sharpe is a result;
        five hundred attempts at it is an order statistic.
        """
        alone = self._dsr(sharpe=0.05, n_trials=1, sharpe_variance=0.004)
        searched = self._dsr(sharpe=0.05, n_trials=500, sharpe_variance=0.004)
        assert alone is not None and searched is not None
        assert alone > 0.9
        assert searched < 0.5

    def test_negative_skew_deflates_it(self) -> None:
        """
        Fat left tails make the ordinary Sharpe standard error optimistic, and
        the correction has to bite in that direction.
        """
        symmetric = self._dsr(skew=0.0)
        left_tailed = self._dsr(skew=-1.5)
        assert symmetric is not None and left_tailed is not None
        assert left_tailed < symmetric

    def test_excess_kurtosis_deflates_it(self) -> None:
        normal = self._dsr(kurtosis=3.0)
        fat = self._dsr(kurtosis=12.0)
        assert normal is not None and fat is not None
        assert fat < normal

    def test_too_few_observations_is_unanswerable(self) -> None:
        assert self._dsr(n_observations=1) is None

    def test_an_impossible_variance_term_is_unanswerable(self) -> None:
        """Undefined, which is not the same as zero and must not render as one."""
        assert self._dsr(sharpe=3.0, skew=5.0, kurtosis=3.0) is None


class TestSharpeMoments:
    def test_it_returns_per_observation_units(self) -> None:
        returns = [0.01, -0.005, 0.02, 0.0, 0.015] * 40
        sharpe, _, _, n = sharpe_moments(returns)
        assert n == 200
        # Per observation, not annualised: a daily Sharpe near 1 would be
        # extraordinary and this series is ordinary.
        assert 0.0 < sharpe < 1.0

    def test_a_flat_series_has_no_sharpe(self) -> None:
        sharpe, skew, kurtosis, n = sharpe_moments([0.0] * 50)
        assert sharpe == 0.0
        assert (skew, kurtosis) == (0.0, 3.0)
        assert n == 50

    def test_a_normal_series_has_kurtosis_near_three(self) -> None:
        rng = random.Random(7)
        returns = [rng.gauss(0.0, 0.01) for _ in range(5000)]
        _, skew, kurtosis, _ = sharpe_moments(returns)
        assert abs(skew) < 0.2
        assert kurtosis == pytest.approx(3.0, abs=0.3)

    def test_it_ignores_non_finite_values(self) -> None:
        _, _, _, n = sharpe_moments([0.01, float("nan"), 0.02, float("inf")])
        assert n == 2


class TestProbabilityOfBacktestOverfitting:
    def _noise(self, trials: int, periods: int, seed: int = 1) -> list[list[float]]:
        rng = random.Random(seed)
        return [
            [rng.gauss(0.0, 0.01) for _ in range(periods)] for _ in range(trials)
        ]

    def test_pure_noise_is_near_a_coin_toss(self) -> None:
        """
        No configuration has an edge, so whichever wins in sample is no more
        likely than chance to win out of sample. The statistic should say so.
        """
        pbo = probability_of_backtest_overfitting(self._noise(12, 600))
        assert pbo is not None
        assert 0.3 < pbo < 0.7

    def test_a_genuinely_better_configuration_is_detected(self) -> None:
        """
        One trial has a real edge in every period, so the in-sample winner is
        the same one out of sample and the overfitting probability collapses.
        """
        rng = random.Random(3)
        matrix = [
            [rng.gauss(0.0, 0.01) for _ in range(600)] for _ in range(8)
        ]
        matrix.append([rng.gauss(0.004, 0.01) for _ in range(600)])
        pbo = probability_of_backtest_overfitting(matrix)
        assert pbo is not None
        assert pbo < 0.1

    def test_it_is_a_probability(self) -> None:
        pbo = probability_of_backtest_overfitting(self._noise(6, 400))
        assert pbo is not None
        assert 0.0 <= pbo <= 1.0

    def test_one_configuration_is_unanswerable(self) -> None:
        """
        There is no selection to overfit with a single candidate, and the
        honest answer is that the question does not apply — not zero.
        """
        assert probability_of_backtest_overfitting(self._noise(1, 500)) is None

    def test_too_few_observations_is_unanswerable(self) -> None:
        assert probability_of_backtest_overfitting(self._noise(5, 10)) is None

    def test_an_empty_study_is_unanswerable(self) -> None:
        assert probability_of_backtest_overfitting([]) is None

    def test_the_split_count_is_capped(self) -> None:
        """
        C(S, S/2) grows explosively, so a caller asking for thirty splits must
        not be given 155 million combinations.
        """
        pbo = probability_of_backtest_overfitting(
            self._noise(4, 400), n_splits=100
        )
        assert pbo is not None
        assert MAX_PBO_SPLITS == 16

    def test_an_odd_split_count_is_made_even(self) -> None:
        """The method needs equal halves; an odd count has none."""
        assert (
            probability_of_backtest_overfitting(self._noise(4, 400), n_splits=7)
            is not None
        )

    def test_a_motionless_configuration_does_not_win(self) -> None:
        """A trial that never moved has no Sharpe, not an infinite one."""
        matrix = [[0.0] * 400, *self._noise(3, 400)]
        pbo = probability_of_backtest_overfitting(matrix)
        assert pbo is not None
        assert math.isfinite(pbo)


class TestCapacity:
    def test_it_is_bound_by_the_thinnest_leg(self) -> None:
        """
        A book that is 90% liquid and 10% illiquid is capped by the illiquid
        tenth. Averaging would report a capacity that could only be reached by
        abandoning the weights the result was measured on.
        """
        weights = {"SPY": 0.9, "TINY": 0.1}
        adv = {"SPY": 500_000_000.0, "TINY": 1_000_000.0}
        # 0.10 * 1e6 / 0.1 = 1e6, against 0.10 * 5e8 / 0.9 = 5.6e7 for SPY.
        assert capacity_estimate(weights, adv) == pytest.approx(1_000_000.0)

    def test_a_larger_weight_lowers_capacity(self) -> None:
        adv = {"SPY": 100_000_000.0}
        small = capacity_estimate({"SPY": 0.1}, adv)
        large = capacity_estimate({"SPY": 1.0}, adv)
        assert small is not None and large is not None
        assert large < small

    def test_a_higher_participation_rate_raises_it(self) -> None:
        weights, adv = {"SPY": 1.0}, {"SPY": 100_000_000.0}
        conservative = capacity_estimate(weights, adv, participation_rate=0.01)
        aggressive = capacity_estimate(weights, adv, participation_rate=0.20)
        assert conservative is not None and aggressive is not None
        assert aggressive > conservative

    def test_zero_weights_are_ignored(self) -> None:
        weights = {"SPY": 1.0, "UNHELD": 0.0}
        adv = {"SPY": 100_000_000.0, "UNHELD": 1.0}
        assert capacity_estimate(weights, adv) == pytest.approx(10_000_000.0)

    def test_no_volume_anywhere_is_unanswerable(self) -> None:
        """Zero capacity and unmeasured capacity are different states."""
        assert capacity_estimate({"SPY": 1.0}, {}) is None

    def test_a_nonsensical_participation_rate_is_unanswerable(self) -> None:
        assert (
            capacity_estimate(
                {"SPY": 1.0}, {"SPY": 1e8}, participation_rate=0.0
            )
            is None
        )


class TestDaysToExit:
    def test_it_is_the_slowest_leg(self) -> None:
        """
        The legs unwind in parallel, so the book is flat when the slowest one
        is. A sum would overstate it; an average would hide the tail.
        """
        positions = {"SPY": 1_000_000.0, "TINY": 500_000.0}
        adv = {"SPY": 500_000_000.0, "TINY": 1_000_000.0}
        # TINY: 5e5 / (0.10 * 1e6) = 5 sessions; SPY is a fraction of one.
        assert days_to_exit(positions, adv) == pytest.approx(5.0)

    def test_an_empty_book_exits_immediately(self) -> None:
        assert days_to_exit({}, {"SPY": 1e8}) == 0.0

    def test_a_position_with_no_volume_is_unanswerable(self) -> None:
        """
        Quietly dropping it from the maximum would report a comfortable exit
        for a book containing something nobody can sell.
        """
        positions = {"SPY": 1_000_000.0, "UNTRADED": 1_000.0}
        assert days_to_exit(positions, {"SPY": 5e8}) is None

    def test_the_default_participation_rate_is_stated(self) -> None:
        assert DEFAULT_PARTICIPATION_RATE == 0.10
