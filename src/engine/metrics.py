"""
metrics.py
----------
Performance statistics, computed here rather than imported, so every number
shown in the UI is one we can defend line by line.

``ffn`` (MIT) is used in the test suite as an independent oracle — our Sharpe,
Sortino, CAGR and max drawdown must match ``ffn.calc_stats`` to within 1e-6 on
the same return series. That gives external validation without shipping a
dependency whose definitions might change under us.

On the Sharpe standard error
~~~~~~~~~~~~~~~~~~~~~~~~~~~~
:func:`sharpe_standard_error` is not decoration. Following Lo (2002), the
asymptotic standard error of an estimated Sharpe ratio under IID returns is
``sqrt((1 + SR^2/2) / T)`` at the sampling frequency. For five years of daily
data that works out to roughly **±0.45 annualised** — meaning a backtest
reporting Sharpe 0.50 is statistically indistinguishable from zero.

Every Sharpe this module produces carries its error bar, and the UI is expected
to render both. It is the single cheapest defence against deploying noise.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import date
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

#: Trading sessions per year, used to annualise.
PERIODS_PER_YEAR = 252


@dataclass(frozen=True, slots=True)
class PerformanceMetrics:
    """Summary statistics for one equity curve."""

    start: date | None
    end: date | None
    n_sessions: int

    initial_equity: float
    final_equity: float
    total_return: float
    cagr: float

    volatility: float
    sharpe: float
    sharpe_stderr: float
    sortino: float

    max_drawdown: float
    max_drawdown_start: date | None
    max_drawdown_end: date | None
    calmar: float

    exposure: float
    n_rebalances: int
    n_fills: int
    total_commission: float
    turnover_annual: float

    #: First session on which the strategy's whole universe was tradeable.
    #: A Sharpe measured before this is not the Sharpe of the strategy.
    effective_start: date | None = None

    #: Cost assumption this run used, so a number is never quoted without it.
    cost_stress_multiplier: float = 1.0

    #: Sessions per year used to annualise. Recorded for the same reason as the
    #: cost assumption: an annualised figure is meaningless without it. 252 is
    #: the NYSE year; a market that never closes has 365, and annualising 24/7
    #: returns at 252 understates volatility by sqrt(365/252) — about 20%.
    periods_per_year: int = PERIODS_PER_YEAR

    @property
    def sharpe_is_significant(self) -> bool:
        """Whether the Sharpe estimate clears two standard errors from zero."""
        return abs(self.sharpe) > 2 * self.sharpe_stderr

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        for key in ("start", "end", "max_drawdown_start", "max_drawdown_end",
                    "effective_start"):
            value = out.get(key)
            out[key] = value.isoformat() if value is not None else None
        out["sharpe_is_significant"] = self.sharpe_is_significant
        return out

    def summary(self) -> str:
        """One-line human summary, with the honesty built in."""
        flag = "" if self.sharpe_is_significant else "  [NOT significant vs zero]"
        return (
            f"{self.start}..{self.end}  "
            f"return {self.total_return:+.1%}  CAGR {self.cagr:+.2%}  "
            f"vol {self.volatility:.2%}  "
            f"Sharpe {self.sharpe:.3f} +/- {self.sharpe_stderr:.3f}{flag}  "
            f"maxDD {self.max_drawdown:.2%}"
        )


# ---------------------------------------------------------------------------
# Building blocks
# ---------------------------------------------------------------------------


def to_returns(equity: pd.Series) -> pd.Series:
    """Simple period returns from an equity curve."""
    return equity.pct_change().dropna()


def annualised_return(
    equity: pd.Series, periods_per_year: int = PERIODS_PER_YEAR
) -> float:
    """
    Compound annual growth rate.

    Uses the number of observations rather than calendar span so that a curve
    sampled on trading sessions annualises consistently with its volatility.
    """
    if len(equity) < 2:
        return 0.0
    start, end = float(equity.iloc[0]), float(equity.iloc[-1])
    if start <= 0:
        return 0.0
    years = (len(equity) - 1) / periods_per_year
    if years <= 0:
        return 0.0
    if end <= 0:
        return -1.0
    return (end / start) ** (1.0 / years) - 1.0


def annualised_volatility(
    returns: pd.Series, periods_per_year: int = PERIODS_PER_YEAR
) -> float:
    """Standard deviation of returns, annualised. Sample stdev (ddof=1)."""
    if len(returns) < 2:
        return 0.0
    return float(returns.std(ddof=1) * math.sqrt(periods_per_year))


def sharpe_ratio(
    returns: pd.Series,
    risk_free_rate: float = 0.0,
    periods_per_year: int = PERIODS_PER_YEAR,
) -> float:
    """Annualised Sharpe ratio. ``risk_free_rate`` is an annual figure."""
    if len(returns) < 2:
        return 0.0
    excess = returns - risk_free_rate / periods_per_year
    sd = excess.std(ddof=1)
    if sd == 0 or np.isnan(sd):
        return 0.0
    return float(excess.mean() / sd * math.sqrt(periods_per_year))


def sharpe_standard_error(
    sharpe_annualised: float,
    n_observations: int,
    periods_per_year: int = PERIODS_PER_YEAR,
) -> float:
    """
    Asymptotic standard error of an annualised Sharpe estimate (Lo, 2002).

    ``SE(SR_period) = sqrt((1 + SR_period^2 / 2) / T)``, then scaled by
    ``sqrt(periods_per_year)`` to annualise.

    Assumes IID returns. Real returns are autocorrelated and fat-tailed, which
    makes the true error *larger* than this — so treat the figure as a floor on
    the uncertainty, not an estimate of it.
    """
    if n_observations < 2:
        return float("inf")
    sr_period = sharpe_annualised / math.sqrt(periods_per_year)
    se_period = math.sqrt((1.0 + 0.5 * sr_period**2) / n_observations)
    return se_period * math.sqrt(periods_per_year)


def sortino_ratio(
    returns: pd.Series,
    risk_free_rate: float = 0.0,
    periods_per_year: int = PERIODS_PER_YEAR,
) -> float:
    """
    Sharpe, but penalising only downside deviation.

    Downside deviation divides the sum of squared negative excess returns by
    the **total** number of observations, not by the count of negative ones.
    Dividing by the negative count is a common mistake and it inverts the
    metric's meaning: it makes a strategy that rarely loses look *worse* than
    Sharpe, when the whole point of Sortino is that it should look better.
    """
    if len(returns) < 2:
        return 0.0
    excess = returns - risk_free_rate / periods_per_year
    downside = excess.clip(upper=0.0)
    dd = math.sqrt(float((downside**2).sum() / len(excess)))
    if dd == 0:
        return 0.0
    return float(excess.mean() / dd * math.sqrt(periods_per_year))


def drawdown_series(equity: pd.Series) -> pd.Series:
    """Fractional drawdown from the running peak, as negative numbers."""
    peak = equity.cummax()
    return equity / peak - 1.0


def max_drawdown(equity: pd.Series) -> tuple[float, date | None, date | None]:
    """Worst peak-to-trough decline, with the peak and trough dates."""
    if len(equity) < 2:
        return 0.0, None, None
    dd = drawdown_series(equity)
    trough_idx = dd.idxmin()
    worst = float(dd.loc[trough_idx])
    peak_idx = equity.loc[:trough_idx].idxmax()
    return (
        worst,
        _as_date(peak_idx),
        _as_date(trough_idx),
    )


def _as_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, pd.Timestamp):
        return value
    try:
        return pd.Timestamp(value).date()
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Top level
# ---------------------------------------------------------------------------


def compute_metrics(
    equity: pd.Series,
    *,
    invested_value: pd.Series | None = None,
    n_rebalances: int = 0,
    n_fills: int = 0,
    total_commission: float = 0.0,
    traded_notional: float = 0.0,
    effective_start: date | None = None,
    cost_stress_multiplier: float = 1.0,
    risk_free_rate: float = 0.0,
    periods_per_year: int = PERIODS_PER_YEAR,
) -> PerformanceMetrics:
    """
    Full metric set for an equity curve.

    Parameters
    ----------
    equity:
        Series indexed by session, values are total portfolio value.
    invested_value:
        Optional series of non-cash value, used for average exposure. A
        trend-following strategy that sits in cash half the time has a very
        different risk profile from one that is always invested, and Sharpe
        alone will not tell you which you are holding.
    traded_notional:
        Sum of absolute fill notionals, used for annualised turnover.
    """
    equity = equity.dropna()
    if equity.empty:
        return PerformanceMetrics(
            start=None, end=None, n_sessions=0,
            initial_equity=0.0, final_equity=0.0,
            total_return=0.0, cagr=0.0, volatility=0.0,
            sharpe=0.0, sharpe_stderr=float("inf"), sortino=0.0,
            max_drawdown=0.0, max_drawdown_start=None, max_drawdown_end=None,
            calmar=0.0, exposure=0.0, n_rebalances=0, n_fills=0,
            total_commission=0.0, turnover_annual=0.0,
            effective_start=effective_start,
            cost_stress_multiplier=cost_stress_multiplier,
            periods_per_year=periods_per_year,
        )

    returns = to_returns(equity)
    initial = float(equity.iloc[0])
    final = float(equity.iloc[-1])
    total_ret = (final / initial - 1.0) if initial > 0 else 0.0
    cagr = annualised_return(equity, periods_per_year)
    vol = annualised_volatility(returns, periods_per_year)
    sr = sharpe_ratio(returns, risk_free_rate, periods_per_year)
    se = sharpe_standard_error(sr, len(returns), periods_per_year)
    sortino = sortino_ratio(returns, risk_free_rate, periods_per_year)
    mdd, dd_start, dd_end = max_drawdown(equity)
    calmar = (cagr / abs(mdd)) if mdd < 0 else 0.0

    exposure = 0.0
    if invested_value is not None and not invested_value.empty:
        aligned = invested_value.reindex(equity.index).fillna(0.0)
        with np.errstate(divide="ignore", invalid="ignore"):
            ratio = (aligned / equity).replace([np.inf, -np.inf], np.nan).dropna()
        if not ratio.empty:
            exposure = float(ratio.mean())

    years = max((len(equity) - 1) / periods_per_year, 1e-9)
    avg_equity = float(equity.mean()) or 1.0
    turnover = (traded_notional / avg_equity) / years if traded_notional else 0.0

    return PerformanceMetrics(
        start=_as_date(equity.index[0]),
        end=_as_date(equity.index[-1]),
        n_sessions=len(equity),
        initial_equity=initial,
        final_equity=final,
        total_return=total_ret,
        cagr=cagr,
        volatility=vol,
        sharpe=sr,
        sharpe_stderr=se,
        sortino=sortino,
        max_drawdown=mdd,
        max_drawdown_start=dd_start,
        max_drawdown_end=dd_end,
        calmar=calmar,
        exposure=exposure,
        n_rebalances=n_rebalances,
        n_fills=n_fills,
        total_commission=total_commission,
        turnover_annual=turnover,
        effective_start=effective_start,
        cost_stress_multiplier=cost_stress_multiplier,
        periods_per_year=periods_per_year,
    )


def metrics_from_records(
    records: Sequence[Any],
    *,
    effective_start: date | None = None,
    cost_stress_multiplier: float = 1.0,
    risk_free_rate: float = 0.0,
    periods_per_year: int = PERIODS_PER_YEAR,
) -> PerformanceMetrics:
    """
    Convenience wrapper turning ``SessionRecord``s into metrics.

    ``periods_per_year`` is forwarded rather than left at the NYSE default,
    because the venue decides it: a 24/7 market has 365 sessions a year and
    annualising its returns at 252 understates volatility by about 20%.
    """
    if not records:
        return compute_metrics(
            pd.Series(dtype=float), periods_per_year=periods_per_year
        )

    index = pd.DatetimeIndex([pd.Timestamp(r.session) for r in records])
    equity = pd.Series([float(r.equity) for r in records], index=index)
    invested = pd.Series([float(r.invested_value) for r in records], index=index)

    n_fills = sum(len(r.fills) for r in records)
    commission = sum(float(f.commission) for r in records for f in r.fills)
    notional = sum(
        float(f.qty) * float(f.price) for r in records for f in r.fills
    )
    n_rebalances = sum(1 for r in records if r.rebalanced)

    return compute_metrics(
        equity,
        invested_value=invested,
        n_rebalances=n_rebalances,
        n_fills=n_fills,
        total_commission=commission,
        traded_notional=notional,
        effective_start=effective_start,
        cost_stress_multiplier=cost_stress_multiplier,
        risk_free_rate=risk_free_rate,
        periods_per_year=periods_per_year,
    )
