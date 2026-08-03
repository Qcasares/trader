"""
statistics.py
-------------
The statistics that decide whether a backtest is evidence.

Everything here is pure: numbers in, numbers out, no I/O and no clock. That is
the same rule the gates follow, for the same reason — these are the figures a
promotion rests on, so they must be exhaustively testable without a database.

Why these four
~~~~~~~~~~~~~~
A Sharpe ratio and a standard error, which this repository already computes,
answer "could this be zero?". They do not answer the two questions that
actually kill a research programme:

* **How many times were the dice rolled?** The best of fifty parameter sets has
  a flattering Sharpe by construction. :func:`deflated_sharpe_ratio` discounts
  the observed figure by the maximum one would expect from that many trials
  under a null of no skill, and also for the non-normality that makes the
  ordinary standard error optimistic.
* **Was the winner chosen by the noise?** :func:`probability_of_backtest_overfitting`
  asks, over many in-sample/out-of-sample splits, how often the configuration
  that looked best in sample landed in the bottom half out of sample. A value
  near 0.5 means the selection procedure is a coin toss dressed as research.

The other two are about whether a result could be traded at all rather than
whether it is real: :func:`capacity_estimate` bounds how much capital the
thinnest leg of the portfolio can absorb, and :func:`days_to_exit` says how
long the position takes to unwind at a tolerable share of volume.

References
~~~~~~~~~~
Bailey and López de Prado, "The Deflated Sharpe Ratio" (2014); Bailey, Borwein,
López de Prado and Zhu, "The Probability of Backtest Overfitting" (2015).
Implemented from the described method, not from any published code.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Sequence
from itertools import combinations
from statistics import NormalDist

import numpy as np

logger = logging.getLogger(__name__)

_NORMAL = NormalDist()

#: Euler-Mascheroni constant, which appears in the expected maximum of a set of
#: independent normal draws.
EULER_MASCHERONI = 0.5772156649015329

#: Number of contiguous blocks the sample is cut into for the combinatorially
#: symmetric cross-validation in :func:`probability_of_backtest_overfitting`.
#:
#: Twelve gives C(12,6) = 924 splits: enough that the estimate is stable, few
#: enough that a study finishes. Sixteen is the figure in the paper and costs
#: fourteen times as much for a third decimal place nobody acts on.
DEFAULT_PBO_SPLITS = 12

#: Ceiling on the split count, because C(S, S/2) grows explosively and a caller
#: passing 30 would ask for 155 million combinations without meaning to.
MAX_PBO_SPLITS = 16

#: Share of a day's dollar volume a strategy may take without moving the price
#: against itself. A common desk assumption, and stated rather than assumed.
DEFAULT_PARTICIPATION_RATE = 0.10


# ---------------------------------------------------------------------------
# Deflated Sharpe ratio
# ---------------------------------------------------------------------------


def expected_max_sharpe(n_trials: int, sharpe_variance: float) -> float:
    """
    The Sharpe ratio the best of ``n_trials`` would show with no skill at all.

    This is the number the observed Sharpe has to beat before it means
    anything. With enough attempts, some configuration looks good by
    construction — the expected maximum of ``n`` independent draws grows
    roughly with the square root of their log — so a study that tried fifty
    parameter sets and reports the winner is reporting an order statistic, not
    an estimate.

    ``sharpe_variance`` is the variance of the Sharpe estimates *across those
    trials*, which is what makes this specific to the study rather than
    generic: a grid whose members all score similarly has little room for a
    lucky winner, and one with wildly dispersed scores has a great deal.
    """
    if n_trials <= 1 or sharpe_variance <= 0:
        return 0.0
    upper = 1.0 - 1.0 / n_trials
    lower = 1.0 - 1.0 / (n_trials * math.e)
    return math.sqrt(sharpe_variance) * (
        (1.0 - EULER_MASCHERONI) * _NORMAL.inv_cdf(upper)
        + EULER_MASCHERONI * _NORMAL.inv_cdf(lower)
    )


def deflated_sharpe_ratio(
    sharpe: float,
    n_observations: int,
    skew: float,
    kurtosis: float,
    n_trials: int,
    sharpe_variance: float,
) -> float | None:
    """
    The probability the true Sharpe is above zero, given how hard we looked.

    Returns a probability in [0, 1], or ``None`` when it cannot be computed —
    which is not the same as zero and must never be rendered as one. Fewer than
    two observations, or a variance term that goes non-positive under extreme
    skew, both make the statistic undefined rather than bad.

    ``sharpe`` must be **per-observation**, not annualised. Feeding an
    annualised figure inflates the statistic by the square root of the
    annualisation factor and produces a confident-looking number that means
    nothing; the caller converts, because only the caller knows the convention
    in force.

    ``kurtosis`` is non-excess: a normal distribution is 3. The correction
    matters because daily strategy returns are fat-tailed, which makes the
    ordinary Sharpe standard error optimistic exactly when it should not be.
    """
    if n_observations < 2:
        return None

    benchmark = expected_max_sharpe(n_trials, sharpe_variance)
    variance_term = 1.0 - skew * sharpe + ((kurtosis - 1.0) / 4.0) * sharpe**2
    if variance_term <= 0:
        logger.warning(
            "Deflated Sharpe is undefined: the variance term is %.4f under "
            "skew %.3f and kurtosis %.3f",
            variance_term,
            skew,
            kurtosis,
        )
        return None

    statistic = (
        (sharpe - benchmark) * math.sqrt(n_observations - 1)
    ) / math.sqrt(variance_term)
    return float(_NORMAL.cdf(statistic))


def sharpe_moments(returns: Sequence[float]) -> tuple[float, float, float, int]:
    """
    Per-observation Sharpe, skew, non-excess kurtosis and count.

    Exactly the inputs :func:`deflated_sharpe_ratio` needs, computed once so a
    caller cannot pair an annualised Sharpe with per-observation moments.
    """
    series = np.asarray([float(r) for r in returns], dtype=float)
    series = series[np.isfinite(series)]
    n = int(series.size)
    if n < 2:
        return 0.0, 0.0, 3.0, n

    mean = float(series.mean())
    sd = float(series.std(ddof=1))
    if sd == 0:
        return 0.0, 0.0, 3.0, n

    centred = (series - mean) / sd
    skew = float((centred**3).mean())
    kurtosis = float((centred**4).mean())
    return mean / sd, skew, kurtosis, n


# ---------------------------------------------------------------------------
# Probability of backtest overfitting
# ---------------------------------------------------------------------------


def probability_of_backtest_overfitting(
    returns_by_trial: Sequence[Sequence[float]],
    n_splits: int = DEFAULT_PBO_SPLITS,
) -> float | None:
    """
    How often the in-sample winner lands in the bottom half out of sample.

    Combinatorially symmetric cross-validation: cut the sample into ``n_splits``
    contiguous blocks, take every way of choosing half of them as in-sample,
    pick the configuration with the best in-sample Sharpe, and record where
    that same configuration ranks on the complementary blocks. The probability
    of backtest overfitting is the share of splits where it ranks below the
    median.

    A value near 0.5 says the selection procedure is a coin toss: whatever
    won in sample is no more likely than chance to win out of sample, so the
    winning configuration was chosen by the noise. Near 0 says the ranking
    carries information.

    Returns ``None`` rather than a number when the study cannot support the
    estimate — fewer than two configurations, or too few observations to cut
    into blocks. An unanswerable question has not been answered, and reporting
    0.0 for it would be the most dangerous possible lie here.
    """
    matrix = np.asarray(
        [[float(r) for r in row] for row in returns_by_trial], dtype=float
    )
    if matrix.ndim != 2 or matrix.shape[0] < 2:
        return None

    n_trials, n_periods = matrix.shape
    splits = max(2, min(int(n_splits), MAX_PBO_SPLITS))
    if splits % 2:
        splits -= 1
    if n_periods < splits * 2:
        logger.info(
            "Too few observations (%d) to cut into %d blocks for PBO",
            n_periods,
            splits,
        )
        return None

    blocks = np.array_split(np.arange(n_periods), splits)
    logits: list[float] = []

    for chosen in combinations(range(splits), splits // 2):
        in_sample = np.concatenate([blocks[i] for i in chosen])
        out_of_sample = np.concatenate(
            [blocks[i] for i in range(splits) if i not in chosen]
        )

        best = _argmax_sharpe(matrix[:, in_sample])
        oos_sharpes = _sharpe_per_row(matrix[:, out_of_sample])
        if best is None or oos_sharpes is None:
            continue

        # Relative rank of the in-sample winner among all trials out of sample,
        # in (0, 1). Ties are ranked pessimistically: a winner that merely
        # matched the field did not beat it.
        rank = float((oos_sharpes < oos_sharpes[best]).sum())
        relative = (rank + 1.0) / (n_trials + 1.0)
        logits.append(math.log(relative / (1.0 - relative)))

    if not logits:
        return None
    # A non-positive logit means the winner ranked at or below the median.
    return float(sum(1 for value in logits if value <= 0) / len(logits))


def _sharpe_per_row(block: np.ndarray) -> np.ndarray | None:
    """Per-observation Sharpe for every trial over one block of periods."""
    if block.shape[1] < 2:
        return None
    means = block.mean(axis=1)
    sds = block.std(axis=1, ddof=1)
    # A configuration that never moved has no Sharpe, not an infinite one.
    with np.errstate(divide="ignore", invalid="ignore"):
        out = np.where(sds > 0, means / sds, 0.0)
    return np.nan_to_num(out, nan=0.0, posinf=0.0, neginf=0.0)


def _argmax_sharpe(block: np.ndarray) -> int | None:
    sharpes = _sharpe_per_row(block)
    if sharpes is None:
        return None
    return int(np.argmax(sharpes))


# ---------------------------------------------------------------------------
# Capacity and liquidity
# ---------------------------------------------------------------------------


def capacity_estimate(
    weights: dict[str, float],
    adv_usd: dict[str, float],
    participation_rate: float = DEFAULT_PARTICIPATION_RATE,
) -> float | None:
    """
    The largest book this allocation could take without exceeding a share of
    volume in any single name.

    Bound by the *thinnest* leg, not the average one: a portfolio that is 90%
    SPY and 10% of something that trades nothing is capped by the something.
    Averaging would report a capacity that could never be reached without
    abandoning the weights the result was measured on.

    Returns ``None`` when no weighted symbol has a volume figure. A capacity of
    zero and an unmeasured capacity are different states.
    """
    if participation_rate <= 0:
        return None

    limits: list[float] = []
    for symbol, weight in weights.items():
        if weight <= 0:
            continue
        volume = adv_usd.get(symbol)
        if volume is None or volume <= 0:
            continue
        limits.append((participation_rate * volume) / weight)
    return min(limits) if limits else None


def days_to_exit(
    position_values: dict[str, float],
    adv_usd: dict[str, float],
    participation_rate: float = DEFAULT_PARTICIPATION_RATE,
) -> float | None:
    """
    Sessions to liquidate the book at ``participation_rate`` of daily volume.

    The maximum across positions rather than the total: the legs unwind in
    parallel, so the book is flat when the slowest one is. Reporting the sum
    would overstate the exit, and reporting the average would understate the
    risk that matters, which is the tail nobody can get out of.
    """
    if participation_rate <= 0:
        return None

    days: list[float] = []
    for symbol, value in position_values.items():
        if value <= 0:
            continue
        volume = adv_usd.get(symbol)
        if volume is None or volume <= 0:
            # A position in something with no measured volume cannot be given a
            # exit time; saying so beats quietly excluding it from a maximum.
            return None
        days.append(value / (participation_rate * volume))
    return max(days) if days else 0.0
