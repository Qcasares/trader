"""
backtest_job.py
---------------
The handler that turns a queued ``backtest`` job into a stored result.

Runs the same :class:`~src.engine.driver.Driver` the live path uses, against
:class:`~src.execution.simulated.SimulatedBroker`. There is no separate
"backtest engine" — that is the whole point of the architecture, and it is what
``tests/unit/test_parity.py`` holds in place.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import asyncpg

from src.core.calendar import sessions as nyse_sessions
from src.core.clock import SimClock
from src.core.orders import RebalanceConstraints
from src.core.panel import PricePanel
from src.core.types import CostModel
from src.data import SyntheticSource, YFinanceSource, bars_to_rows
from src.data.base import DataSourceError
from src.db.repos import backtests as repo
from src.engine import Driver, DriverConfig, metrics_from_records
from src.execution.simulated import SimulatedBroker
from src.strategies import build_strategy

logger = logging.getLogger(__name__)

SOURCES = {"synthetic": SyntheticSource, "yfinance": YFinanceSource}


class BacktestJobError(RuntimeError):
    """The run could not be completed."""


async def run_backtest_job(conn: asyncpg.Connection, payload: dict[str, Any]) -> dict:
    """
    Execute one backtest and persist its results.

    The heavy work happens in a worker thread: pandas and numpy release the GIL
    for most of it, and keeping it off the event loop means the worker can still
    answer its lease heartbeat and notice the kill switch while a 25-year run is
    grinding.
    """
    run_id = uuid.UUID(payload["run_id"])
    run = await repo.get_run(conn, run_id)
    if run is None:
        raise BacktestJobError(f"unknown backtest run {run_id}")

    await repo.mark_running(conn, run_id)
    logger.info(
        "Running backtest %s: %s %s..%s via %s",
        run_id,
        run["strategy_name"],
        run["start_session"],
        run["end_session"],
        run["data_source"],
    )

    try:
        result = await asyncio.to_thread(_execute, run)
    except DataSourceError as exc:
        await repo.mark_failed(conn, run_id, f"data source: {exc}")
        raise BacktestJobError(str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - recorded on the run, then re-raised
        logger.exception("Backtest %s failed", run_id)
        await repo.mark_failed(conn, run_id, str(exc))
        raise

    await repo.store_results(
        conn,
        run_id,
        metrics=result["metrics"],
        equity_rows=result["equity_rows"],
        order_rows=result["order_rows"],
        target_rows=result["target_rows"],
    )
    logger.info(
        "Backtest %s done: sharpe=%.3f +/- %.3f significant=%s",
        run_id,
        result["metrics"]["sharpe"],
        result["metrics"]["sharpe_stderr"],
        result["metrics"]["sharpe_is_significant"],
    )
    return {
        "run_id": str(run_id),
        "sharpe": result["metrics"]["sharpe"],
        "effective_start": result["metrics"].get("effective_start"),
    }


def _execute(run: dict[str, Any]) -> dict[str, Any]:
    """Synchronous body of the backtest. Runs in a worker thread."""
    strategy = build_strategy(run["strategy_name"], run["params"])
    universe = strategy.universe()

    source_cls = SOURCES.get(run["data_source"])
    if source_cls is None:
        raise BacktestJobError(f"unknown data source {run['data_source']!r}")

    start = _as_date(run["start_session"])
    end = _as_date(run["end_session"])

    bars = source_cls().fetch(universe, start, end)
    if not bars:
        raise DataSourceError(
            f"no bars for {universe} between {start} and {end}"
        )
    panel = PricePanel.from_bars(bars_to_rows(bars))
    trading_sessions = nyse_sessions(start, end)

    cost = run["cost_model"] or {}
    clock = SimClock(trading_sessions)
    broker = SimulatedBroker(
        initial_cash=Decimal(str(run["initial_cash"])),
        cost_model=CostModel(
            slippage_bps=float(cost.get("slippage_bps", 5.0)),
            stress_multiplier=float(cost.get("stress_multiplier", 1.0)),
        ),
        clock=clock,
    )
    driver = Driver(
        strategy,
        broker,
        clock,
        DriverConfig(
            constraints=RebalanceConstraints(
                min_trade_usd=Decimal(str(cost.get("min_trade_usd", 25.0))),
                max_weight_per_asset=float(cost.get("max_weight_per_asset", 1.0)),
            ),
            run_ref=str(run["id"])[:8],
        ),
    )

    effective_start = driver.effective_start(panel, trading_sessions)

    async def _walk() -> list:
        records = []
        for session in trading_sessions:
            records.append(await driver.step(panel, session))
            clock.advance()
        return records

    records = asyncio.run(_walk())

    metrics = metrics_from_records(
        records,
        effective_start=effective_start,
        cost_stress_multiplier=float(cost.get("stress_multiplier", 1.0)),
    )

    equity_rows = [
        (r.session, float(r.equity), float(r.cash), 0.0) for r in records
    ]
    # Drawdown is computed here rather than in SQL so the stored curve and the
    # reported max drawdown come from one calculation.
    peak = float("-inf")
    for i, row in enumerate(equity_rows):
        peak = max(peak, row[1])
        drawdown = (row[1] / peak - 1.0) if peak > 0 else 0.0
        equity_rows[i] = (row[0], row[1], row[2], drawdown)

    order_rows = [
        (
            r.session,
            f.symbol,
            f.side.value,
            float(f.qty),
            float(f.price),
            float(f.qty) * float(f.price),
            float(f.commission),
            "fill",
        )
        for r in records
        for f in r.fills
    ]
    target_rows = [
        (r.session, symbol, float(weight))
        for r in records
        if r.targets is not None
        for symbol, weight in r.targets.weights.items()
    ]

    return {
        "metrics": metrics.to_dict(),
        "equity_rows": equity_rows,
        "order_rows": order_rows,
        "target_rows": target_rows,
    }


def _as_date(value: Any) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    return date.fromisoformat(str(value))
