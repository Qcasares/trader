"""
jev_stats.py
------------
The statistics the Jev evaluation harness reports, and nothing that can call
anything. Pure: the standard library alone
(``tests/unit/test_import_boundaries.py::test_the_pure_modules_load_nothing``).

Phase C4 landed the two the forward clock's report needs, a proportion and its
Wilson interval; phase C9 adds what an evaluation against labels needs: the
Brier score of a Choice and of a Noul, a seeded bootstrap interval, the
calibration bins, the threshold search, Cohen's kappa and the flip count. One
rule runs through every function, because the research UI is a machine for
fooling yourself: **a figure computed over nothing is ``None``, never 0.** A
coverage of "0 of 0 sessions" is not a coverage of zero, and printed as 0.00
it is the most flattering lie a report about a model that never answered
could tell. ``tests/unit/test_jev_stats.py`` feeds every function empty input,
and input in which nothing was validly answered.

Two more rules, each a test there:

* **A bootstrap is reproducible from its seed.** The resamples are drawn with
  ``random.Random(seed).random()``, the one draw Python promises to repeat
  across versions for the same seed, and never ``randrange``, whose algorithm
  has changed between releases. The harness seeds it from the dataset's
  sha256 (``jev_prereg.BOOTSTRAP_SEED_RULE``), so a figure recomputes from
  its dataset.
* **A threshold depends on the development split alone.**
  :func:`choose_threshold` is handed the development items and nothing else;
  the harness measures what it chose on the test split afterwards.
"""

from __future__ import annotations

import math
import random
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from statistics import NormalDist
from typing import Literal, TypeVar

T = TypeVar("T")


def proportion(k: int, n: int) -> float | None:
    """``k / n``, or ``None`` when ``n`` is 0: nothing was measured."""
    _check_counts(k, n)
    return k / n if n else None


def wilson(
    k: int, n: int, level: float = 0.95, *, one_sided: bool = False
) -> tuple[float, float] | None:
    """
    The Wilson score interval for ``k`` successes in ``n`` trials, or ``None``
    when ``n`` is 0.

    Wilson rather than the normal approximation, which gives an interval of
    zero width at 0 of n and n of n and one reaching below 0 near them: exactly
    where a small forward sample sits. ``level`` is two-sided by default, so
    0.95 leaves 2.5% outside each bound. With ``one_sided``, each bound is a
    one-sided bound at ``level`` — the lower is the figure a gate compares with
    a target at, say, 0.995 — and the pair is not an interval at ``level``.

    At 0 of ``n`` the lower bound is exactly 0, and at ``n`` of ``n`` the upper
    exactly 1, as they are in exact arithmetic: the floating-point formula
    leaves a residue near 1e-17 there, which put the bound on the wrong side of
    the estimate itself (``tests/unit/test_jev_stats.py``).
    """
    _check_counts(k, n)
    _check_level(level)
    if n == 0:
        return None
    tail = 1.0 - level if one_sided else (1.0 - level) / 2.0
    z = NormalDist().inv_cdf(1.0 - tail)
    p = k / n
    denominator = 1.0 + z * z / n
    centre = (p + z * z / (2.0 * n)) / denominator
    half = z * math.sqrt(p * (1.0 - p) / n + z * z / (4.0 * n * n)) / denominator
    lower = 0.0 if k == 0 else max(0.0, centre - half)
    upper = 1.0 if k == n else min(1.0, centre + half)
    return lower, upper


# ---------------------------------------------------------------------------
# The Brier score
# ---------------------------------------------------------------------------


def brier_choice(
    probabilities: Sequence[Mapping[str, float]], labels: Sequence[str]
) -> float | None:
    """
    The mean Brier score of Choice answers against their labels, or ``None``
    on no items: per item ``Σₖ (pₖ − yₖ)²`` over the question's options, ``y``
    one-hot on the label, so 0 is a certain right answer and 2 a certain wrong
    one.

    Each distribution is read as the vendor's rounding of one that sums to 1 —
    the validator admits a sum within 0.02 of 1 as the decimals written
    (docs/08, fact 3) — and divided by its sum, so a score is never above 2
    because the vendor rounded up. A label that is not one of an answer's
    options, a distribution of a negative or non-finite probability, or one
    summing to nothing is a caller's defect, :class:`ValueError`.
    """
    _same_length(probabilities, labels)
    if not labels:
        return None
    total = 0.0
    for distribution, label in zip(probabilities, labels, strict=True):
        if label not in distribution:
            raise ValueError(f"the label {label!r} is not an option answered")
        values = {option: _probability(p) for option, p in distribution.items()}
        mass = math.fsum(values.values())
        if mass <= 0.0:
            raise ValueError("a distribution sums to nothing")
        total += math.fsum(
            (p / mass - (1.0 if option == label else 0.0)) ** 2
            for option, p in values.items()
        )
    return total / len(labels)


def brier_noul(p_true: Sequence[float], labels: Sequence[bool]) -> float | None:
    """
    The mean Brier score of Noul answers, or ``None`` on no items: per item
    ``(p − y)²``, ``p`` the stated probability of ``true`` and ``y`` 1 when the
    label is true, so the score is in [0, 1]. A label is a boolean and nothing
    else: ``1`` is not ``True`` here, as in the validator.
    """
    _same_length(p_true, labels)
    if not labels:
        return None
    total = 0.0
    for p, label in zip(p_true, labels, strict=True):
        if not isinstance(label, bool):
            raise TypeError(f"a Noul's label is a boolean, got {label!r}")
        total += (_probability(p) - (1.0 if label else 0.0)) ** 2
    return total / len(labels)


# ---------------------------------------------------------------------------
# The bootstrap
# ---------------------------------------------------------------------------


def bootstrap_interval(
    values: Sequence[T],
    statistic: Callable[[Sequence[T]], float],
    *,
    resamples: int,
    seed: int,
    level: float,
) -> tuple[float, float] | None:
    """
    The percentile bootstrap interval of ``statistic`` over ``values``, two-
    sided at ``level``, or ``None`` on no values.

    ``resamples`` samples of ``len(values)`` drawn with replacement by a
    ``random.Random(seed)`` that draws with :meth:`random.Random.random`
    alone (see the module docstring), the statistic of each, and the
    quantiles of the results by linear interpolation between order
    statistics. A paired difference passes tuples and a statistic of them, so
    the pairs are resampled together. The ends of a two-sided interval at
    ``2g − 1`` are each a one-sided bound at ``g``, which is how a gate's
    bound is asked for.
    """
    if isinstance(resamples, bool) or not isinstance(resamples, int) or resamples < 1:
        raise ValueError(f"resamples is a positive count, got {resamples!r}")
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise TypeError(f"a seed is an integer, got {seed!r}")
    _check_level(level)
    n = len(values)
    if n == 0:
        return None
    draw = random.Random(seed).random
    estimates = sorted(
        float(statistic([values[min(int(draw() * n), n - 1)] for _ in range(n)]))
        for _ in range(resamples)
    )
    tail = (1.0 - level) / 2.0
    return _quantile(estimates, tail), _quantile(estimates, 1.0 - tail)


def _quantile(ordered: Sequence[float], q: float) -> float:
    position = q * (len(ordered) - 1)
    below = math.floor(position)
    above = min(below + 1, len(ordered) - 1)
    fraction = position - below
    return ordered[below] + (ordered[above] - ordered[below]) * fraction


# ---------------------------------------------------------------------------
# Calibration
# ---------------------------------------------------------------------------


def calibration_bins(
    probabilities: Sequence[float], correct: Sequence[bool], bins: int = 10
) -> list[dict]:
    """
    The stated probabilities in ``bins`` equal bins of [0, 1], the last
    closed, and for each bin anything fell in: its bounds, how many answers
    (``n``), their mean stated probability (``mean_p``), how often the
    outcome held (``agreement``), and that share's Wilson interval at 95%,
    the reporting level. A bin nothing fell in is left out rather than shown
    as a bin of zero.

    ``probabilities`` are a Choice's top probability or a Noul's ``p(true)``;
    ``correct`` is whether the top option was the label, or whether the label
    was true. A probability is binned by the decimal it was written as, so
    0.3 is in the bin from 0.3 and never, by a float's rounding, below it.
    """
    _same_length(probabilities, correct)
    if isinstance(bins, bool) or not isinstance(bins, int) or bins < 1:
        raise ValueError(f"bins is a positive count, got {bins!r}")
    members: dict[int, list[tuple[float, bool]]] = {}
    for p, outcome in zip(probabilities, correct, strict=True):
        value = _probability(p)
        if not isinstance(outcome, bool):
            raise TypeError(f"an outcome is a boolean, got {outcome!r}")
        index = min(int(Decimal(repr(value)) * bins), bins - 1)
        members.setdefault(index, []).append((value, outcome))
    found = []
    for index in sorted(members):
        inside = members[index]
        held = sum(1 for _, outcome in inside if outcome)
        interval = wilson(held, len(inside))
        found.append(
            {
                "low": index / bins,
                "high": (index + 1) / bins,
                "n": len(inside),
                "mean_p": math.fsum(p for p, _ in inside) / len(inside),
                "agreement": proportion(held, len(inside)),
                "wilson": list(interval) if interval is not None else None,
            }
        )
    return found


# ---------------------------------------------------------------------------
# The threshold
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DevItem:
    """
    One labelled item of the development split, as the threshold search sees
    it: its label, the option its answer chose where the answer was valid
    (``predicted``, ``None`` for an invalid answer or none at all), and that
    answer's margin, its lead over the next option.
    """

    label: str
    predicted: str | None
    margin: float | None

    def __post_init__(self) -> None:
        if self.predicted is not None and self.margin is None:
            raise ValueError("a valid answer carries its margin")


ThresholdOutcome = Literal["not_attempted", "none_found", "chosen"]


@dataclass(frozen=True)
class ThresholdChoice:
    """
    What the search came to. ``chosen`` carries the threshold, the number of
    development items its statistic was measured on at it (``covered``), how
    many of those were right (``correct``), and the one-sided Wilson lower
    bound that met the target (``lower``); the other two outcomes carry none
    of it, and never a threshold of 0 standing for "none".
    """

    outcome: ThresholdOutcome
    threshold: float | None = None
    covered: int | None = None
    correct: int | None = None
    lower: float | None = None


def choose_threshold(
    dev: Sequence[DevItem],
    *,
    grid: Sequence[float],
    target: float,
    min_covered: int,
    level: float,
    acting_class: str | None,
    min_dev: int,
) -> ThresholdChoice:
    """
    The smallest margin threshold on ``grid`` at which the plan's statistic,
    measured on the development items alone, reaches ``target`` by its
    one-sided Wilson lower bound at ``level``, on at least ``min_covered``
    items.

    With no ``acting_class`` the statistic is covered accuracy: of the items
    whose valid answer leads by at least the threshold, how many chose the
    label — an escape, which no label is, among them and never right. With
    one, it is covered precision of that class: of the valid answers
    choosing it by at least the threshold, how many were labelled it, since
    that is the answer that would act. ``not_attempted`` below ``min_dev``
    development items, which the plan registers as the floor of a search
    (``jev_prereg.MIN_DEV_ITEMS``) and the caller passes, this module loading
    nothing; ``none_found`` when no threshold on the grid qualifies.
    """
    for name, value in (("min_covered", min_covered), ("min_dev", min_dev)):
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValueError(f"{name} is a positive count, got {value!r}")
    _check_level(level)
    if len(dev) < min_dev:
        return ThresholdChoice("not_attempted")
    for threshold in sorted(grid):
        covered = [
            item
            for item in dev
            if item.predicted is not None
            and item.margin is not None
            and item.margin >= threshold
            and (acting_class is None or item.predicted == acting_class)
        ]
        if len(covered) < min_covered:
            # Coverage only falls as the threshold rises.
            break
        right = sum(
            1
            for item in covered
            if item.label
            == (acting_class if acting_class is not None else item.predicted)
        )
        bound = wilson(right, len(covered), level, one_sided=True)
        assert bound is not None  # covered is not empty
        if bound[0] >= target:
            return ThresholdChoice("chosen", threshold, len(covered), right, bound[0])
    return ThresholdChoice("none_found")


# ---------------------------------------------------------------------------
# Agreement and consistency
# ---------------------------------------------------------------------------


def cohen_kappa(first: Sequence[str], second: Sequence[str]) -> float | None:
    """
    Cohen's kappa between two labellings of the same items, or ``None`` where
    it is undefined: no items, or both labellers giving every item the one
    same label, when the agreement chance alone predicts is already 1 and
    there is nothing left for skill to explain.
    """
    _same_length(first, second)
    n = len(first)
    if n == 0:
        return None
    observed = sum(1 for a, b in zip(first, second, strict=True) if a == b) / n
    counts_first: dict[str, int] = {}
    counts_second: dict[str, int] = {}
    for a, b in zip(first, second, strict=True):
        counts_first[a] = counts_first.get(a, 0) + 1
        counts_second[b] = counts_second.get(b, 0) + 1
    expected = math.fsum(
        (counts_first[label] / n) * (counts_second.get(label, 0) / n)
        for label in counts_first
    )
    if expected >= 1.0:
        return None
    return (observed - expected) / (1.0 - expected)


def flip_rate(pairs: Sequence[tuple[str | None, str | None]]) -> tuple[int, int]:
    """
    ``(flipped, n)``: of the pairs whose two argmaxes are both present — a
    canonical answer and its re-ask, each valid — how many moved. A pair
    with either side missing is no comparison, so it is in neither count;
    the rate is ``proportion(flipped, n)``, ``None`` over no pairs.
    """
    compared = [(a, b) for a, b in pairs if a is not None and b is not None]
    return sum(1 for a, b in compared if a != b), len(compared)


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------


def _check_counts(k: int, n: int) -> None:
    for name, value in (("k", k), ("n", n)):
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError(f"{name} is a count, got {value!r}")
    if n < 0 or not 0 <= k <= n:
        raise ValueError(f"k and n are counts with 0 <= k <= n, got k={k}, n={n}")


def _check_level(level: float) -> None:
    if not 0.0 < level < 1.0:
        raise ValueError(
            f"level is a probability strictly between 0 and 1, got {level}"
        )


def _probability(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"a probability is a number, got {value!r}")
    number = float(value)
    if not math.isfinite(number) or not 0.0 <= number <= 1.0:
        raise ValueError(f"a probability is in [0, 1], got {value!r}")
    return number


def _same_length(first: Sequence[object], second: Sequence[object]) -> None:
    if len(first) != len(second):
        raise ValueError(f"one value per item: {len(first)} against {len(second)}")


__all__ = [
    "DevItem",
    "ThresholdChoice",
    "ThresholdOutcome",
    "bootstrap_interval",
    "brier_choice",
    "brier_noul",
    "calibration_bins",
    "choose_threshold",
    "cohen_kappa",
    "flip_rate",
    "proportion",
    "wilson",
]
