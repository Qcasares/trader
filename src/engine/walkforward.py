"""
walkforward.py
--------------
Walk-forward validation — the antidote to the research UI.

The loop the web app makes easy (edit a parameter, rerun, look at the Sharpe)
is a machine for overfitting. Run it twenty times and the best result is the
luckiest one, not the best strategy. Walk-forward is the cheapest honest
defence: choose parameters using *only* data available at the time, then
measure on data that had no say in the choice.

    |---- train ----|-- test --|
              |---- train ----|-- test --|
                        |---- train ----|-- test --|

Each fold selects parameters on its training window and evaluates them on the
window that follows. The stitched test segments form an out-of-sample curve
that nobody tuned against.

Reading the result
~~~~~~~~~~~~~~~~~~
The number that matters is not the OOS Sharpe on its own — it is the *gap*
between in-sample and out-of-sample. A strategy scoring 1.4 in-sample and 0.1
out-of-sample has not been validated; it has been shown to be curve-fitted, and
that is a useful thing to have learned cheaply. :attr:`WalkForwardResult.degradation`
reports it directly, and :attr:`is_robust` applies a deliberately blunt test.

This is not a substitute for out-of-sample *time*. Walk-forward reuses one
history repeatedly, so a parameter set that survives it has still only met one
realisation of the past.
"""

from __future__ import annotations

import itertools
import logging
import math
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

import numpy as np

from src.core.calendar import sessions as nyse_sessions
from src.core.clock import SimClock
from src.core.orders import RebalanceConstraints
from src.core.panel import PricePanel
from src.core.types import CostModel
from src.engine.driver import Driver, DriverConfig
from src.engine.metrics import (
    PerformanceMetrics,
    compute_metrics,
    metrics_from_records,
)
from src.engine.statistics import (
    deflated_sharpe_ratio,
    probability_of_backtest_overfitting,
)
from src.execution.simulated import SimulatedBroker
from src.strategies import build_strategy

logger = logging.getLogger(__name__)

#: Approximate trading sessions per month, for translating fold widths.
SESSIONS_PER_MONTH = 21


@dataclass(frozen=True, slots=True)
class Fold:
    """One train/test split."""

    index: int
    train_start: date
    train_end: date
    test_start: date
    test_end: date

    def __str__(self) -> str:  # pragma: no cover - logging aid
        return (
            f"fold {self.index}: train {self.train_start}..{self.train_end} "
            f"test {self.test_start}..{self.test_end}"
        )


@dataclass(slots=True)
class FoldResult:
    """Outcome of one fold: what was chosen, and how it then did."""

    fold: Fold
    chosen_params: dict[str, Any]
    in_sample: PerformanceMetrics
    out_of_sample: PerformanceMetrics
    #: Every candidate's in-sample score, so a near-tie is visible rather than
    #: hidden behind a single winner.
    candidate_scores: list[tuple[dict[str, Any], float]] = field(default_factory=list)

    @property
    def degradation(self) -> float:
        """In-sample Sharpe minus out-of-sample. Large positive = curve-fitted."""
        return self.in_sample.sharpe - self.out_of_sample.sharpe


@dataclass(slots=True)
class WalkForwardResult:
    """The whole study."""

    strategy_name: str
    folds: list[FoldResult]
    stitched_oos: PerformanceMetrics
    param_grid_size: int

    #: Probability that the configuration which looked best in sample would
    #: land in the bottom half out of sample. ``None`` when the study could not
    #: support the estimate — one candidate, or too short a sample — which is
    #: emphatically not the same as zero. See
    #: :func:`src.engine.statistics.probability_of_backtest_overfitting`.
    pbo: float | None = None

    #: Probability the true Sharpe of the stitched out-of-sample curve is above
    #: zero, discounted for how many configurations were tried. ``None`` when
    #: undefined.
    deflated_sharpe: float | None = None

    @property
    def mean_in_sample_sharpe(self) -> float:
        if not self.folds:
            return 0.0
        return sum(f.in_sample.sharpe for f in self.folds) / len(self.folds)

    @property
    def mean_out_of_sample_sharpe(self) -> float:
        if not self.folds:
            return 0.0
        return sum(f.out_of_sample.sharpe for f in self.folds) / len(self.folds)

    @property
    def degradation(self) -> float:
        """
        How much performance evaporated once parameters were fixed in advance.

        This is the headline number. A small gap means the parameters were not
        doing much work; a large one means they were fitted to noise.
        """
        return self.mean_in_sample_sharpe - self.mean_out_of_sample_sharpe

    @property
    def parameter_stability(self) -> float:
        """
        Fraction of folds that chose the most common parameter set.

        A strategy whose optimum jumps around between folds has no stable
        optimum — which is itself a finding, and usually means the parameter is
        fitting noise rather than a persistent effect.
        """
        if not self.folds:
            return 0.0
        keys = [_freeze(f.chosen_params) for f in self.folds]
        return max(keys.count(k) for k in set(keys)) / len(keys)

    @property
    def is_robust(self) -> bool:
        """
        A blunt, deliberately conservative verdict.

        Requires the stitched out-of-sample Sharpe to clear two standard errors
        of zero, and the majority of folds to agree on a parameter set. Passing
        is weak evidence; failing is strong evidence against.
        """
        return (
            self.stitched_oos.sharpe_is_significant
            and self.stitched_oos.sharpe > 0
            and self.parameter_stability >= 0.5
        )

    def summary(self) -> str:
        verdict = "ROBUST" if self.is_robust else "NOT ROBUST"
        return (
            f"{self.strategy_name}: {len(self.folds)} folds, "
            f"{self.param_grid_size} candidate(s) per fold\n"
            f"  in-sample  Sharpe {self.mean_in_sample_sharpe:+.3f}\n"
            f"  OOS (mean) Sharpe {self.mean_out_of_sample_sharpe:+.3f}\n"
            f"  degradation       {self.degradation:+.3f}\n"
            f"  stitched OOS      {self.stitched_oos.sharpe:+.3f} "
            f"+/- {self.stitched_oos.sharpe_stderr:.3f}\n"
            f"  param stability   {self.parameter_stability:.0%}\n"
            f"  verdict           {verdict}"
        )


def make_folds(
    sessions: Sequence[date],
    train_months: int = 36,
    test_months: int = 12,
    step_months: int | None = None,
) -> list[Fold]:
    """
    Split a session list into rolling train/test folds.

    Widths are in *sessions* derived from months, not calendar arithmetic, so a
    fold contains a consistent amount of data regardless of holidays. ``step``
    defaults to ``test_months``, giving non-overlapping test windows — which is
    what makes stitching them into one curve legitimate.
    """
    train_len = train_months * SESSIONS_PER_MONTH
    test_len = test_months * SESSIONS_PER_MONTH
    step_len = (step_months or test_months) * SESSIONS_PER_MONTH

    if train_len <= 0 or test_len <= 0:
        raise ValueError("train_months and test_months must be positive")

    folds: list[Fold] = []
    start = 0
    index = 0
    while start + train_len + test_len <= len(sessions):
        train_slice = sessions[start : start + train_len]
        test_slice = sessions[start + train_len : start + train_len + test_len]
        folds.append(
            Fold(
                index=index,
                train_start=train_slice[0],
                train_end=train_slice[-1],
                test_start=test_slice[0],
                test_end=test_slice[-1],
            )
        )
        start += step_len
        index += 1
    return folds


def expand_grid(grid: dict[str, Sequence[Any]]) -> list[dict[str, Any]]:
    """Cartesian product of a parameter grid."""
    if not grid:
        return [{}]
    keys = sorted(grid)
    return [
        dict(zip(keys, values, strict=True))
        for values in itertools.product(*(grid[k] for k in keys))
    ]


def sharpe_objective(metrics: PerformanceMetrics) -> float:
    """Default selection criterion."""
    return metrics.sharpe


def run_walk_forward(
    strategy_name: str,
    panel: PricePanel,
    sessions: Sequence[date],
    param_grid: dict[str, Sequence[Any]] | None = None,
    base_params: dict[str, Any] | None = None,
    train_months: int = 36,
    test_months: int = 12,
    step_months: int | None = None,
    initial_cash: float = 100_000.0,
    cost_model: CostModel | None = None,
    constraints: RebalanceConstraints | None = None,
    objective: Callable[[PerformanceMetrics], float] = sharpe_objective,
) -> WalkForwardResult:
    """
    Run a full walk-forward study.

    Each fold evaluates every candidate on its training window, selects the
    best by ``objective``, and re-runs that single candidate on the test
    window. The test window never influences the choice — that is the entire
    point, and it is why selection and evaluation are separate calls rather
    than one pass over the whole history.
    """
    candidates = expand_grid(param_grid or {})
    if base_params:
        candidates = [{**base_params, **c} for c in candidates]

    folds = make_folds(sessions, train_months, test_months, step_months)
    if not folds:
        raise ValueError(
            f"{len(sessions)} sessions is too few for "
            f"{train_months}+{test_months} months of folds"
        )

    logger.info(
        "Walk-forward: %d fold(s) x %d candidate(s) = %d backtests",
        len(folds),
        len(candidates),
        len(folds) * (len(candidates) + 1),
    )

    results: list[FoldResult] = []
    oos_segments: list[list[Any]] = []

    for fold in folds:
        scores: list[tuple[dict[str, Any], float]] = []
        best_params: dict[str, Any] = candidates[0]
        best_metrics: PerformanceMetrics | None = None
        best_score = float("-inf")

        for params in candidates:
            metrics, _ = _run_segment(
                strategy_name, params, panel, sessions,
                fold.train_start, fold.train_end,
                initial_cash, cost_model, constraints,
            )
            score = objective(metrics)
            scores.append((params, score))
            if score > best_score:
                best_score, best_params, best_metrics = score, params, metrics

        oos_metrics, records = _run_segment(
            strategy_name, best_params, panel, sessions,
            fold.test_start, fold.test_end,
            initial_cash, cost_model, constraints,
        )
        oos_segments.append(records)

        results.append(
            FoldResult(
                fold=fold,
                chosen_params=best_params,
                in_sample=best_metrics or oos_metrics,
                out_of_sample=oos_metrics,
                candidate_scores=scores,
            )
        )
        logger.info(
            "%s -> %s | IS %.3f OOS %.3f",
            fold, best_params, best_score, oos_metrics.sharpe,
        )

    stitched = _stitch_out_of_sample(results, oos_segments)
    pbo, deflated = _overfitting_statistics(
        strategy_name,
        candidates,
        panel,
        sessions,
        initial_cash,
        cost_model,
        constraints,
        stitched,
    )
    return WalkForwardResult(
        strategy_name=strategy_name,
        folds=results,
        stitched_oos=stitched,
        param_grid_size=len(candidates),
        pbo=pbo,
        deflated_sharpe=deflated,
    )


def _overfitting_statistics(
    strategy_name: str,
    candidates: Sequence[dict[str, Any]],
    panel: PricePanel,
    sessions: Sequence[date],
    initial_cash: float,
    cost_model: CostModel | None,
    constraints: RebalanceConstraints | None,
    stitched: PerformanceMetrics,
) -> tuple[float | None, float | None]:
    """
    How much of this study's winner is selection, and how much is signal.

    Two questions the fold results cannot answer between them. Walk-forward
    already tells you whether performance survives fixing the parameters in
    advance; it does not tell you whether the parameter that won did so by
    chance, and it does not discount the headline for the number of attempts.

    The extra cost is one backtest per candidate over the whole window, against
    the ``folds x candidates`` the study has already run — so a few percent for
    the two figures the research-integrity section of the operating prompt puts
    at the top of its list.

    Both are returned as ``None`` when the study cannot support them. A single
    candidate has no selection to overfit, and reporting 0.0 for that would be
    the most flattering possible lie.
    """
    if len(candidates) < 2:
        return None, _deflate(stitched, n_trials=max(1, len(candidates)),
                              sharpe_variance=0.0)

    start, end = sessions[0], sessions[-1]
    returns_by_trial: list[list[float]] = []
    per_trial_sharpe: list[float] = []
    for params in candidates:
        metrics, records = _run_segment(
            strategy_name, params, panel, sessions, start, end,
            initial_cash, cost_model, constraints,
        )
        returns_by_trial.append(_returns_of(records))
        per_trial_sharpe.append(metrics.sharpe)

    pbo = probability_of_backtest_overfitting(returns_by_trial)
    variance = float(np.var(per_trial_sharpe, ddof=1)) if per_trial_sharpe else 0.0
    return pbo, _deflate(stitched, len(candidates), variance)


def _deflate(
    metrics: PerformanceMetrics, n_trials: int, sharpe_variance: float
) -> float | None:
    """
    Deflate the stitched out-of-sample Sharpe for the size of the search.

    The annualised Sharpe is converted back to per-observation units first.
    Feeding an annualised figure into the statistic inflates it by the square
    root of the annualisation factor and produces a confident-looking number
    that means nothing.

    ``sharpe_variance`` is the dispersion of the *annualised* candidate
    Sharpes, so it is rescaled by the same factor rather than passed through.
    """
    periods = max(1, metrics.periods_per_year)
    scale = math.sqrt(periods)
    return deflated_sharpe_ratio(
        sharpe=metrics.sharpe / scale,
        n_observations=metrics.n_sessions,
        # The stitched curve's own higher moments are not carried on
        # PerformanceMetrics, so the normal case is assumed and stated. This
        # makes the figure *optimistic* for a fat-tailed strategy, which is the
        # direction worth knowing about.
        skew=0.0,
        kurtosis=3.0,
        n_trials=max(1, n_trials),
        sharpe_variance=sharpe_variance / periods,
    )


def _returns_of(records: Sequence[Any]) -> list[float]:
    """Per-session returns from a segment's equity path."""
    equities = [float(r.equity) for r in records if getattr(r, "equity", None)]
    return [
        (equities[i] - equities[i - 1]) / equities[i - 1]
        for i in range(1, len(equities))
        if equities[i - 1] > 0
    ]


def _stitch_out_of_sample(
    results: Sequence[FoldResult], segments: Sequence[Sequence[Any]]
) -> PerformanceMetrics:
    """
    Join the test windows into one continuous out-of-sample curve.

    Each fold's test window is an independent backtest that starts from the
    same initial cash, so their equity series all begin at the same value.
    Concatenating those raw values would put a cliff at every fold boundary —
    a jump from wherever fold *n* ended back down to the starting balance —
    and the return series would read each cliff as a real one-day loss. On a
    sixteen-fold study that is sixteen fabricated crashes, which is enough to
    turn a genuinely good strategy into a mediocre one.

    So the returns are chained instead: take each segment's returns, drop the
    junctions, concatenate, and compound into a single synthetic curve.
    """
    import pandas as pd

    pieces: list[pd.Series] = []
    for segment in segments:
        if len(segment) < 2:
            continue
        index = pd.DatetimeIndex([pd.Timestamp(r.session) for r in segment])
        equity = pd.Series([float(r.equity) for r in segment], index=index)
        # pct_change drops the first observation of each segment, which is
        # exactly the junction we must not treat as a return.
        pieces.append(equity.pct_change().dropna())

    if not pieces:
        return compute_metrics(pd.Series(dtype=float))

    returns = pd.concat(pieces).sort_index()
    curve = 100_000.0 * (1.0 + returns).cumprod()

    invested = pd.concat(
        [
            pd.Series(
                [float(r.invested_value) for r in segment],
                index=pd.DatetimeIndex([pd.Timestamp(r.session) for r in segment]),
            )
            for segment in segments
            if len(segment) >= 2
        ]
    ).sort_index()

    n_rebalances = sum(1 for seg in segments for r in seg if r.rebalanced)
    n_fills = sum(len(r.fills) for seg in segments for r in seg)
    commission = sum(
        float(f.commission) for seg in segments for r in seg for f in r.fills
    )
    notional = sum(
        float(f.qty) * float(f.price)
        for seg in segments
        for r in seg
        for f in r.fills
    )

    return compute_metrics(
        curve,
        invested_value=invested.reindex(curve.index),
        n_rebalances=n_rebalances,
        n_fills=n_fills,
        total_commission=commission,
        traded_notional=notional,
    )


def _run_segment(
    strategy_name: str,
    params: dict[str, Any],
    panel: PricePanel,
    all_sessions: Sequence[date],
    start: date,
    end: date,
    initial_cash: float,
    cost_model: CostModel | None,
    constraints: RebalanceConstraints | None,
) -> tuple[PerformanceMetrics, list[Any]]:
    """Backtest one window. Synchronous — the driver's step is awaited inline."""
    import asyncio

    window = [s for s in all_sessions if start <= s <= end]
    strategy = build_strategy(strategy_name, params)
    clock = SimClock(window)
    broker = SimulatedBroker(
        initial_cash=Decimal(str(initial_cash)),
        cost_model=cost_model or CostModel(),
        clock=clock,
    )
    driver = Driver(
        strategy,
        broker,
        clock,
        DriverConfig(
            constraints=constraints or RebalanceConstraints(),
            run_ref="wf",
        ),
    )

    async def walk() -> list[Any]:
        out = []
        for session in window:
            out.append(await driver.step(panel, session))
            clock.advance()
        return out

    records = asyncio.run(walk())
    return metrics_from_records(records), records


def _freeze(params: dict[str, Any]) -> tuple:
    """Hashable form of a parameter dict, for counting agreement across folds."""
    return tuple(sorted((k, _hashable(v)) for k, v in params.items()))


def _hashable(value: Any) -> Any:
    if isinstance(value, list):
        return tuple(value)
    if isinstance(value, dict):
        return tuple(sorted(value.items()))
    return value


def sessions_for(start: date, end: date) -> list[date]:
    """Convenience wrapper so callers need not import the calendar."""
    return nyse_sessions(start, end)


def describe_folds(folds: Iterable[Fold]) -> str:  # pragma: no cover - display
    return "\n".join(str(f) for f in folds)
