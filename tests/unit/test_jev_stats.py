"""
A figure computed over nothing is ``None``, never 0 (CLAUDE.md, honesty rules).

``src/programme/jev_stats.py`` holds the proportion and the Wilson interval the
forward report quotes coverage with, and from phase C9 what an evaluation
against labels needs: the Brier scores, the seeded bootstrap, the calibration
bins, the threshold search, Cohen's kappa and the flip count. Each is checked
against a copy of its formula written here with its constants as literals,
against published or hand-worked values, and on empty input and input nothing
validly answered, where a zero would be the most flattering lie a report about
a model that never answered could tell. The bootstrap is held to a copy of its
draw and to values pinned for a seed, so a figure recomputes from its dataset;
the threshold is shown to read nothing but the development items it is given.
"""

from __future__ import annotations

import math
import random
from decimal import Decimal

import pytest

from src.programme import jev_prereg
from src.programme.jev_stats import (
    DevItem,
    ThresholdChoice,
    bootstrap_interval,
    brier_choice,
    brier_noul,
    calibration_bins,
    choose_threshold,
    cohen_kappa,
    flip_rate,
    proportion,
    wilson,
)

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


# ---------------------------------------------------------------------------
# Phase C9: what an evaluation against labels needs
# ---------------------------------------------------------------------------


class TestTheBrierScore:
    def test_a_choice_against_hand_worked_values(self) -> None:
        answer = {"equities": 0.7, "bonds": 0.2, "insufficient_evidence": 0.1}
        # 0.3² + 0.2² + 0.1², and 0.7² + 0.8² + 0.1².
        assert brier_choice([answer], ["equities"]) == pytest.approx(0.14)
        assert brier_choice([answer], ["bonds"]) == pytest.approx(1.14)
        assert brier_choice([answer, answer], ["equities", "bonds"]) == (
            pytest.approx(0.64)
        )

    def test_a_noul_against_hand_worked_values(self) -> None:
        assert brier_noul([0.8], [True]) == pytest.approx(0.04)
        assert brier_noul([0.8], [False]) == pytest.approx(0.64)
        assert brier_noul([0.8, 0.8], [True, False]) == pytest.approx(0.34)

    def test_its_ends(self) -> None:
        sure = {"a": 1.0, "b": 0.0, "c": 0.0}
        assert brier_choice([sure], ["a"]) == 0.0
        assert brier_choice([sure], ["b"]) == 2.0
        assert brier_noul([1.0, 0.0], [True, False]) == 0.0
        assert brier_noul([1.0], [False]) == 1.0

    def test_a_rounded_distribution_is_read_as_summing_to_one(self) -> None:
        """
        The validator admits a sum within 0.02 of 1, and scored as written a
        certain wrong answer summing to 1.02 would score 2.0004, outside the
        range the schema holds a Brier score to.
        """
        rounded = {"a": 1.0, "b": 0.02, "c": 0.0}
        raw = 1.0**2 + 0.02**2 + 1.0**2
        assert raw > 2
        expected = (1 / 1.02) ** 2 + (0.02 / 1.02) ** 2 + 1.0
        assert brier_choice([rounded], ["c"]) == pytest.approx(expected)

    def test_it_stays_in_range(self) -> None:
        rng = random.Random(9)
        for _ in range(500):
            options = [f"o{i}" for i in range(rng.randint(2, 8))]
            weights = [rng.random() for _ in options]
            total = sum(weights) or 1.0
            answer = {o: w / total for o, w in zip(options, weights, strict=True)}
            label = rng.choice(options)
            assert 0.0 <= brier_choice([answer], [label]) <= 2.0
            p = rng.random()
            assert 0.0 <= brier_noul([p], [rng.random() < 0.5]) <= 1.0

    def test_nothing_is_none(self) -> None:
        assert brier_choice([], []) is None
        assert brier_noul([], []) is None

    def test_a_defect_is_refused_rather_than_scored(self) -> None:
        with pytest.raises(ValueError):
            brier_choice([{"a": 0.5, "b": 0.5}], ["c"])
        with pytest.raises(ValueError):
            brier_choice([{"a": 0.5}], ["a", "a"])
        with pytest.raises(ValueError):
            brier_choice([{"a": 0.0, "b": 0.0}], ["a"])
        with pytest.raises(ValueError):
            brier_choice([{"a": math.nan, "b": 0.5}], ["a"])
        with pytest.raises(ValueError):
            brier_noul([1.5], [True])
        with pytest.raises(TypeError):
            brier_noul([0.5], [1])  # type: ignore[list-item]
        with pytest.raises(TypeError):
            brier_noul([True], [True])


def _mean(values: list[float]) -> float:
    return sum(values) / len(values)


def _bootstrap(
    values: list, statistic, resamples: int, seed: int, level: float
) -> tuple[float, float]:
    """The bootstrap written again: ``random()`` draws, sorted, type-7 quantiles."""
    rng = random.Random(seed)
    n = len(values)
    estimates = sorted(
        statistic([values[min(int(rng.random() * n), n - 1)] for _ in range(n)])
        for _ in range(resamples)
    )

    def quantile(q: float) -> float:
        position = q * (len(estimates) - 1)
        below = math.floor(position)
        above = min(below + 1, len(estimates) - 1)
        return estimates[below] + (estimates[above] - estimates[below]) * (
            position - below
        )

    tail = (1 - level) / 2
    return quantile(tail), quantile(1 - tail)


SAMPLE = [0.0, 0.25, 0.5, 0.75, 1.0, 0.1, 0.9, 0.3]
PAIRS = [(1, 0), (1, 1), (0, 0), (1, 0), (0, 1), (1, 1), (1, 0), (0, 0), (1, 1), (1, 0)]


def _difference(pairs: list[tuple[int, int]]) -> float:
    return sum(a for a, _ in pairs) / len(pairs) - sum(b for _, b in pairs) / len(pairs)


class TestTheBootstrap:
    def test_it_is_the_algorithm_written_again(self) -> None:
        for seed in (0, 1, 42, 2**63 - 1):
            assert bootstrap_interval(
                SAMPLE, _mean, resamples=500, seed=seed, level=0.95
            ) == _bootstrap(SAMPLE, _mean, 500, seed, 0.95)

    def test_it_is_reproducible_from_its_seed(self) -> None:
        """Values pinned for a seed, so a change to the draw fails here."""
        assert bootstrap_interval(
            SAMPLE, _mean, resamples=2_000, seed=42, level=0.95
        ) == pytest.approx((0.24375, 0.7125), abs=1e-12)
        assert bootstrap_interval(
            PAIRS, _difference, resamples=2_000, seed=7, level=0.99
        ) == pytest.approx((-0.2005, 0.8), abs=1e-12)

    def test_the_seed_is_the_datasets(self) -> None:
        """
        ``jev_prereg.BOOTSTRAP_SEED_RULE``: the first sixteen hex digits of the
        dataset's sha256, so one dataset always draws the same resamples.
        """
        assert jev_prereg.BOOTSTRAP_SEED_RULE == "int(dataset_sha256[:16], 16)"
        seed = int("f" * 16, 16)
        first = bootstrap_interval(SAMPLE, _mean, resamples=200, seed=seed, level=0.95)
        assert first == bootstrap_interval(
            SAMPLE, _mean, resamples=200, seed=seed, level=0.95
        )

    def test_another_seed_draws_other_resamples(self) -> None:
        intervals = {
            bootstrap_interval(SAMPLE, _mean, resamples=200, seed=s, level=0.95)
            for s in range(10)
        }
        assert len(intervals) > 1

    def test_it_holds_a_constant_and_brackets_a_mean(self) -> None:
        assert bootstrap_interval(
            [0.3] * 20, _mean, resamples=100, seed=1, level=0.95
        ) == pytest.approx((0.3, 0.3))
        low, high = bootstrap_interval(
            SAMPLE, _mean, resamples=2_000, seed=3, level=0.95
        )
        assert low <= _mean(SAMPLE) <= high

    def test_a_wider_level_is_a_wider_interval(self) -> None:
        narrow = bootstrap_interval(SAMPLE, _mean, resamples=1_000, seed=5, level=0.9)
        wide = bootstrap_interval(SAMPLE, _mean, resamples=1_000, seed=5, level=0.99)
        assert wide[0] <= narrow[0] <= narrow[1] <= wide[1]

    def test_paired_values_are_resampled_together(self) -> None:
        """A difference of one item with itself never moves, however drawn."""
        pairs = [(x, x) for x in SAMPLE]
        assert bootstrap_interval(
            pairs,
            lambda ps: _mean([a for a, _ in ps]) - _mean([b for _, b in ps]),
            resamples=300,
            seed=11,
            level=0.95,
        ) == (0.0, 0.0)

    def test_nothing_is_none(self) -> None:
        assert bootstrap_interval([], _mean, resamples=10, seed=1, level=0.95) is None

    @pytest.mark.parametrize("resamples", [0, -1, True, 1.5])
    def test_resamples_are_a_positive_count(self, resamples: object) -> None:
        with pytest.raises(ValueError):
            bootstrap_interval(
                SAMPLE,
                _mean,
                resamples=resamples,
                seed=1,
                level=0.95,  # type: ignore[arg-type]
            )

    @pytest.mark.parametrize("level", [0.0, 1.0, 1.5])
    def test_a_level_is_a_probability(self, level: float) -> None:
        with pytest.raises(ValueError):
            bootstrap_interval(SAMPLE, _mean, resamples=10, seed=1, level=level)

    def test_a_seed_is_an_integer(self) -> None:
        with pytest.raises(TypeError):
            bootstrap_interval(SAMPLE, _mean, resamples=10, seed="42", level=0.95)  # type: ignore[arg-type]


class TestTheCalibrationBins:
    def test_only_bins_something_fell_in(self) -> None:
        bins = calibration_bins([0.95, 0.91, 0.55], [True, False, True])
        assert [(b["low"], b["high"], b["n"]) for b in bins] == [
            (0.5, 0.6, 1),
            (0.9, 1.0, 2),
        ]
        top = bins[1]
        assert top["mean_p"] == pytest.approx(0.93)
        assert top["agreement"] == 0.5
        assert top["wilson"] == pytest.approx(list(wilson(1, 2)))

    def test_a_probability_is_binned_by_the_decimal_written(self) -> None:
        """0.3 is in the bin from 0.3, whatever its float rounds to."""
        for written in ("0.1", "0.2", "0.3", "0.4", "0.6", "0.7", "0.8", "0.9"):
            (only,) = calibration_bins([float(written)], [True])
            assert only["low"] == float(Decimal(written)), written
        # Written just below a third, it is below a third, though its float
        # times 3 rounds up to 1.
        assert float("0.3333333333333333") * 3 == 1.0
        (third,) = calibration_bins([0.3333333333333333], [True], bins=3)
        assert third["low"] == 0.0

    def test_the_ends(self) -> None:
        bins = calibration_bins([0.0, 1.0], [False, True])
        assert [(b["low"], b["high"]) for b in bins] == [(0.0, 0.1), (0.9, 1.0)]

    def test_a_genuine_zero_agreement_is_zero(self) -> None:
        (only,) = calibration_bins([0.8, 0.85], [False, False])
        assert only["agreement"] == 0.0
        assert only["wilson"][0] == 0.0

    def test_nothing_is_no_bins(self) -> None:
        assert calibration_bins([], []) == []

    def test_a_defect_is_refused(self) -> None:
        with pytest.raises(ValueError):
            calibration_bins([1.2], [True])
        with pytest.raises(TypeError):
            calibration_bins([0.5], [1])  # type: ignore[list-item]
        with pytest.raises(ValueError):
            calibration_bins([0.5], [True], bins=0)


def _dev(
    label: str, predicted: str | None = None, margin: float | None = None
) -> DevItem:
    return DevItem(label=label, predicted=predicted, margin=margin)


def _search(dev: list[DevItem], acting_class: str | None = None) -> ThresholdChoice:
    return choose_threshold(
        dev,
        grid=jev_prereg.MARGIN_GRID,
        target=0.80,
        min_covered=jev_prereg.MIN_COVERED,
        level=jev_prereg.GATE_CI,
        acting_class=acting_class,
        min_dev=jev_prereg.MIN_DEV_ITEMS,
    )


class TestTheThreshold:
    def test_below_the_floor_it_is_not_attempted(self) -> None:
        dev = [_dev("a", "a", 0.9)] * (jev_prereg.MIN_DEV_ITEMS - 1)
        assert _search(dev) == ThresholdChoice("not_attempted")

    def test_nothing_answered_finds_none_and_never_a_zero(self) -> None:
        """Items nobody validly answered: searched, and nothing qualifies."""
        dev = [_dev("a")] * 150
        assert _search(dev) == ThresholdChoice("none_found")

    def test_the_smallest_threshold_that_meets_the_target_by_its_lower_bound(
        self,
    ) -> None:
        """
        Below a margin of 0.5 the answers are a coin; above it they are right.
        The point estimate over everything never reaches 0.80, and the
        smallest threshold whose one-sided lower bound at the gate level does
        is chosen, with how many it covered.
        """
        dev = [_dev("a", "a", 0.9)] * 60 + [
            _dev("a", "b" if i % 2 else "a", 0.2) for i in range(60)
        ]
        choice = _search(dev)
        assert choice.outcome == "chosen"
        assert choice.threshold == 0.22
        assert (choice.covered, choice.correct) == (60, 60)
        assert choice.lower == pytest.approx(
            wilson(60, 60, jev_prereg.GATE_CI, one_sided=True)[0]
        )
        assert choice.lower >= 0.80

    def test_a_point_estimate_that_meets_the_target_is_not_enough(self) -> None:
        """24 of 30 is 0.80 and its lower bound at the gate level is far below."""
        dev = [_dev("a", "a", 0.9)] * 24 + [_dev("a", "b", 0.9)] * 6 + [_dev("a")] * 90
        assert _search(dev) == ThresholdChoice("none_found")

    def test_fewer_covered_than_the_floor_is_never_chosen(self) -> None:
        dev = [_dev("a", "a", 0.9)] * (jev_prereg.MIN_COVERED - 1) + [_dev("a")] * 110
        assert _search(dev) == ThresholdChoice("none_found")

    def test_an_escape_is_covered_and_never_right(self) -> None:
        """
        A confident escape is covered, and no label is the escape, so it
        counts against covered accuracy rather than out of it.
        """
        dev = (
            [_dev("a", "a", 0.9)] * 40
            + [_dev("a", "insufficient_evidence", 0.9)] * 10
            + [_dev("a")] * 60
        )
        assert _search(dev) == ThresholdChoice("none_found")

    def test_an_acting_class_is_measured_by_its_precision(self) -> None:
        """
        For a guardrail the answer that acts is ``true``, so the statistic is
        how many of the confident ``true`` answers were labelled true; the
        ``false`` answers, right or wrong, are not what acts.
        """
        dev = (
            [_dev("true", "true", 0.95)] * 40
            + [_dev("true", "false", 0.95)] * 40
            + [_dev("false", "true", 0.1)] * 30
        )
        choice = _search(dev, acting_class="true")
        assert choice.outcome == "chosen"
        assert choice.threshold == 0.12
        assert (choice.covered, choice.correct) == (40, 40)
        assert _search(dev).outcome == "none_found"

    def test_it_reads_the_dev_items_it_is_given_and_nothing_else(self) -> None:
        """Their order changes nothing: the search is a function of the set."""
        dev = [_dev("a", "a", 0.9)] * 60 + [
            _dev("a", "b" if i % 2 else "a", 0.2) for i in range(60)
        ]
        shuffled = list(dev)
        random.Random(4).shuffle(shuffled)
        assert _search(shuffled) == _search(dev)

    def test_a_valid_answer_carries_its_margin(self) -> None:
        with pytest.raises(ValueError):
            DevItem(label="a", predicted="a", margin=None)

    @pytest.mark.parametrize("field", ["min_covered", "min_dev"])
    def test_the_floors_are_counts(self, field: str) -> None:
        kwargs = {
            "grid": (0.0,),
            "target": 0.8,
            "min_covered": 1,
            "level": 0.995,
            "acting_class": None,
            "min_dev": 1,
            field: 0,
        }
        with pytest.raises(ValueError):
            choose_threshold([_dev("a", "a", 0.5)], **kwargs)


class TestCohensKappa:
    def test_a_textbook_table(self) -> None:
        """Yes/no, 20 both yes, 15 both no, 5 and 10 apart: kappa 0.4."""
        first = ["y"] * 20 + ["y"] * 5 + ["n"] * 10 + ["n"] * 15
        second = ["y"] * 20 + ["n"] * 5 + ["y"] * 10 + ["n"] * 15
        assert cohen_kappa(first, second) == pytest.approx(0.4)

    def test_it_is_the_formula_written_again(self) -> None:
        rng = random.Random(17)
        for _ in range(300):
            n = rng.randint(1, 40)
            labels = ["a", "b", "c", "d"][: rng.randint(1, 4)]
            first = [rng.choice(labels) for _ in range(n)]
            second = [rng.choice(labels) for _ in range(n)]
            p_o = sum(a == b for a, b in zip(first, second, strict=True)) / n
            p_e = sum((first.count(c) / n) * (second.count(c) / n) for c in labels)
            expected = None if p_e >= 1 else (p_o - p_e) / (1 - p_e)
            got = cohen_kappa(first, second)
            if expected is None:
                assert got is None
            else:
                assert got == pytest.approx(expected, abs=1e-12)
                assert -1.0 <= got <= 1.0

    def test_perfect_agreement_is_one(self) -> None:
        assert cohen_kappa(["a", "b", "a"], ["a", "b", "a"]) == pytest.approx(1.0)

    def test_undefined_is_none(self) -> None:
        assert cohen_kappa([], []) is None
        assert cohen_kappa(["a"] * 5, ["a"] * 5) is None

    def test_a_length_mismatch_is_refused(self) -> None:
        with pytest.raises(ValueError):
            cohen_kappa(["a"], ["a", "b"])


class TestTheFlipCount:
    def test_only_pairs_with_both_answers_count(self) -> None:
        pairs = [("a", "a"), ("a", "b"), (None, "a"), ("b", None), (None, None)]
        assert flip_rate(pairs) == (1, 2)

    def test_nothing_compared_is_no_rate(self) -> None:
        for pairs in ([], [(None, "a"), (None, None)]):
            flipped, n = flip_rate(pairs)
            assert (flipped, n) == (0, 0)
            assert proportion(flipped, n) is None

    def test_a_genuine_zero_is_a_zero(self) -> None:
        flipped, n = flip_rate([("a", "a"), ("b", "b")])
        assert proportion(flipped, n) == 0.0


class TestNothingIsNeverZero:
    """
    The property the module exists for, fed to every function at once: empty
    input, and input in which nothing was validly answered, measure nothing.
    """

    def test_empty_input_measures_nothing(self) -> None:
        assert proportion(0, 0) is None
        assert wilson(0, 0) is None
        assert brier_choice([], []) is None
        assert brier_noul([], []) is None
        assert bootstrap_interval([], _mean, resamples=5, seed=1, level=0.95) is None
        assert calibration_bins([], []) == []
        assert cohen_kappa([], []) is None
        assert flip_rate([]) == (0, 0)
        assert _search([]) == ThresholdChoice("not_attempted")

    @pytest.mark.parametrize("n", [1, 7, 150])
    def test_nothing_validly_answered_measures_nothing(self, n: int) -> None:
        dev = [_dev("a")] * n
        choice = _search(dev)
        assert choice.outcome in ("not_attempted", "none_found")
        assert choice.threshold is None and choice.covered is None
        flipped, compared = flip_rate([(None, None)] * n)
        assert proportion(flipped, compared) is None
