"""
A figure computed over nothing is ``None``, never 0 (CLAUDE.md, honesty rules).

``src/programme/jev_stats.py`` holds the proportion and the Wilson interval the
forward report quotes coverage with. Each is checked against a copy of the
formula written here with its constant as a literal, against published values,
and on empty input, where a zero would be the most flattering lie a report
about a model that never answered could tell.
"""

from __future__ import annotations

import math

import pytest

from src.programme.jev_stats import proportion, wilson

#: The 97.5th percentile of the standard normal, as tables print it.
Z_95 = 1.959963984540054


def _wilson(k: int, n: int, z: float) -> tuple[float, float]:
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = (z / (1 + z * z / n)) * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return max(0.0, centre - half), min(1.0, centre + half)


class TestNothingMeasuredIsNone:
    def test_a_proportion_of_nothing_is_none(self) -> None:
        assert proportion(0, 0) is None

    def test_an_interval_about_nothing_is_none(self) -> None:
        assert wilson(0, 0) is None
        assert wilson(0, 0, 0.995, one_sided=True) is None

    def test_a_genuine_zero_stays_a_zero(self) -> None:
        """0 of 10 was measured: it is 0, and its interval is not empty."""
        assert proportion(0, 10) == 0.0
        lower, upper = wilson(0, 10)
        assert lower == 0.0 and upper > 0.25


class TestTheWilsonInterval:
    @pytest.mark.parametrize(
        ("k", "n", "lower", "upper"),
        [
            # Published values for the 95% Wilson score interval.
            (0, 10, 0.0, 0.2775),
            (5, 10, 0.2366, 0.7634),
            (10, 10, 0.7225, 1.0),
            (81, 263, 0.2553, 0.3662),
        ],
    )
    def test_published_values(self, k: int, n: int, lower: float, upper: float) -> None:
        got = wilson(k, n)
        assert got is not None
        assert got[0] == pytest.approx(lower, abs=5e-5)
        assert got[1] == pytest.approx(upper, abs=5e-5)

    def test_it_is_the_formula_written_again(self) -> None:
        for n in (1, 2, 7, 30, 251, 5_000):
            for k in sorted({0, 1, n // 3, n // 2, n - 1, n}):
                assert wilson(k, n) == pytest.approx(_wilson(k, n, Z_95), abs=1e-12)

    def test_the_ends_are_exact(self) -> None:
        """
        0 of n has a lower bound of exactly 0 and n of n an upper bound of
        exactly 1. The float formula leaves about 1e-17 there, a bound on the
        wrong side of its own estimate, which the next test also catches.
        """
        for n in range(1, 400):
            assert wilson(0, n)[0] == 0.0
            assert wilson(n, n)[1] == 1.0

    def test_it_holds_its_estimate_and_stays_a_probability(self) -> None:
        for n in range(1, 60):
            for k in range(n + 1):
                lower, upper = wilson(k, n)
                assert 0.0 <= lower <= k / n <= upper <= 1.0

    def test_it_is_symmetric(self) -> None:
        for n in (3, 20, 101):
            for k in range(n + 1):
                lower, upper = wilson(k, n)
                mirror_lower, mirror_upper = wilson(n - k, n)
                assert lower == pytest.approx(1.0 - mirror_upper, abs=1e-12)
                assert upper == pytest.approx(1.0 - mirror_lower, abs=1e-12)

    def test_more_trials_narrow_it(self) -> None:
        widths = [wilson(n // 2, n)[1] - wilson(n // 2, n)[0] for n in (10, 100, 1_000)]
        assert widths == sorted(widths, reverse=True)

    def test_a_one_sided_bound_is_the_two_sided_bound_at_twice_the_tail(self) -> None:
        """
        A gate's bound is one-sided at 0.995: the lower end of the two-sided
        interval at 0.99, and wider than the one-sided bound at 0.95.
        """
        for k, n in ((0, 30), (27, 30), (180, 200)):
            assert wilson(k, n, 0.995, one_sided=True) == pytest.approx(
                wilson(k, n, 0.99), abs=1e-12
            )
            assert (
                wilson(k, n, 0.995, one_sided=True)[0]
                <= wilson(k, n, 0.95, one_sided=True)[0]
            )


class TestCountsAreCounts:
    @pytest.mark.parametrize(("k", "n"), [(-1, 5), (6, 5), (0, -1), (1, 0)])
    def test_impossible_counts_are_refused(self, k: int, n: int) -> None:
        with pytest.raises(ValueError):
            proportion(k, n)
        with pytest.raises(ValueError):
            wilson(k, n)

    @pytest.mark.parametrize(("k", "n"), [(True, 5), (1, 5.0), (0.5, 1), ("1", 2)])
    def test_a_count_is_an_integer(self, k: object, n: object) -> None:
        """``True`` is not 1 here either: a count arriving as a boolean is a defect."""
        with pytest.raises(TypeError):
            proportion(k, n)  # type: ignore[arg-type]
        with pytest.raises(TypeError):
            wilson(k, n)  # type: ignore[arg-type]

    @pytest.mark.parametrize("level", [0.0, 1.0, -0.5, 95.0])
    def test_a_level_is_a_probability(self, level: float) -> None:
        with pytest.raises(ValueError):
            wilson(1, 2, level)
