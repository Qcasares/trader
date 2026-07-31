"""
backtests.py
------------
Persistence for backtest runs and their outputs.

Every run records the inputs that determine its result — strategy version,
parameters, data source, cost model, decision lag, engine version — so a stored
number can never be reinterpreted later under assumptions it was not produced
under. A Sharpe without its cost assumption is not a Sharpe.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

import asyncpg

logger = logging.getLogger(__name__)

ENGINE_VERSION = "0.1.0"


@dataclass(frozen=True, slots=True)
class BacktestRequest:
    """Everything needed to run and reproduce a backtest."""

    strategy_name: str
    params: dict[str, Any]
    universe: list[str]
    start_session: date
    end_session: date
    initial_cash: float
    data_source: str
    cost_model: dict[str, Any]
    strategy_version: str = "1.0"
    decision_lag_sessions: int = 1
    owner_id: str = "default"


async def create_run(
    conn: asyncpg.Connection, request: BacktestRequest
) -> uuid.UUID:
    """Insert a queued run and return its id."""
    run_id = uuid.uuid4()
    await conn.execute(
        """
        INSERT INTO backtest_runs (
            id, owner_id, strategy_name, strategy_version, params, universe,
            start_session, end_session, initial_cash, data_source, cost_model,
            decision_lag_sessions, engine_version, status
        ) VALUES ($1,$2,$3,$4,$5::jsonb,$6,$7,$8,$9,$10,$11::jsonb,$12,$13,'queued')
        """,
        run_id,
        request.owner_id,
        request.strategy_name,
        request.strategy_version,
        json.dumps(request.params),
        request.universe,
        request.start_session,
        request.end_session,
        request.initial_cash,
        request.data_source,
        json.dumps(request.cost_model),
        request.decision_lag_sessions,
        ENGINE_VERSION,
    )
    return run_id


async def mark_running(conn: asyncpg.Connection, run_id: uuid.UUID) -> None:
    await conn.execute(
        "UPDATE backtest_runs SET status='running', started_at=NOW() WHERE id=$1",
        run_id,
    )


async def mark_failed(conn: asyncpg.Connection, run_id: uuid.UUID, error: str) -> None:
    await conn.execute(
        "UPDATE backtest_runs SET status='failed', error=$2, finished_at=NOW() "
        "WHERE id=$1",
        run_id,
        error[:4000],
    )


async def store_results(
    conn: asyncpg.Connection,
    run_id: uuid.UUID,
    metrics: dict[str, Any],
    equity_rows: Sequence[tuple[date, float, float, float]],
    order_rows: Sequence[tuple[date, str, str, float, float, float, float, str]],
    target_rows: Sequence[tuple[date, str, float]] = (),
) -> None:
    """
    Write a completed run's outputs in one transaction.

    All-or-nothing on purpose: a run marked 'succeeded' whose equity curve only
    partially wrote would render a chart that silently stops mid-history.
    """
    async with conn.transaction():
        if equity_rows:
            await conn.executemany(
                "INSERT INTO backtest_equity (run_id, session, equity, cash, "
                "drawdown_pct) VALUES ($1,$2,$3,$4,$5) ON CONFLICT DO NOTHING",
                [(run_id, *row) for row in equity_rows],
            )
        if order_rows:
            await conn.executemany(
                "INSERT INTO backtest_orders (run_id, session, symbol, side, qty, "
                "price, notional, commission, reason) "
                "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)",
                [(run_id, *row) for row in order_rows],
            )
        if target_rows:
            await conn.executemany(
                "INSERT INTO backtest_targets (run_id, session, symbol, "
                "target_weight) VALUES ($1,$2,$3,$4) ON CONFLICT DO NOTHING",
                [(run_id, *row) for row in target_rows],
            )
        await conn.execute(
            "UPDATE backtest_runs SET status='succeeded', metrics=$2::jsonb, "
            "finished_at=NOW() WHERE id=$1",
            run_id,
            json.dumps(metrics, default=str),
        )


async def get_run(
    conn: asyncpg.Connection, run_id: uuid.UUID
) -> dict[str, Any] | None:
    row = await conn.fetchrow("SELECT * FROM backtest_runs WHERE id = $1", run_id)
    return _decode_run(row) if row else None


async def list_runs(
    conn: asyncpg.Connection,
    strategy_name: str | None = None,
    status: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    rows = await conn.fetch(
        """
        SELECT * FROM backtest_runs
        WHERE ($1::text IS NULL OR strategy_name = $1)
          AND ($2::text IS NULL OR status = $2)
        ORDER BY created_at DESC
        LIMIT $3
        """,
        strategy_name,
        status,
        limit,
    )
    return [_decode_run(r) for r in rows]


async def count_runs_for_strategy(
    conn: asyncpg.Connection, strategy_name: str
) -> int:
    """
    How many backtests this strategy has accumulated.

    Surfaced in the UI as a multiple-testing counter. The research loop — tweak
    a parameter, rerun, look at Sharpe — is a machine for fooling yourself, and
    the honest defence is showing how many times the dice have been rolled.
    """
    return int(
        await conn.fetchval(
            "SELECT COUNT(*) FROM backtest_runs WHERE strategy_name = $1",
            strategy_name,
        )
        or 0
    )


async def get_equity_curve(
    conn: asyncpg.Connection, run_id: uuid.UUID, max_points: int = 2000
) -> list[dict[str, Any]]:
    """
    Equity curve, downsampled to at most ``max_points`` rows.

    A 25-year daily backtest is ~6,300 points; sending them all to a chart that
    is 800px wide wastes bandwidth to draw sub-pixel detail. Downsampling keeps
    the first and last row so the endpoints stay exact.
    """
    total = int(
        await conn.fetchval(
            "SELECT COUNT(*) FROM backtest_equity WHERE run_id = $1", run_id
        )
        or 0
    )
    if total == 0:
        return []
    stride = max(1, total // max_points)
    rows = await conn.fetch(
        """
        SELECT session, equity, cash, drawdown_pct FROM (
            SELECT session, equity, cash, drawdown_pct,
                   ROW_NUMBER() OVER (ORDER BY session) AS rn
            FROM backtest_equity WHERE run_id = $1
        ) t
        WHERE rn % $2 = 0 OR rn = 1 OR rn = $3
        ORDER BY session
        """,
        run_id,
        stride,
        total,
    )
    return [
        {
            "session": r["session"].isoformat(),
            "equity": float(r["equity"]),
            "cash": float(r["cash"]),
            "drawdown_pct": float(r["drawdown_pct"]),
        }
        for r in rows
    ]


async def get_orders(
    conn: asyncpg.Connection, run_id: uuid.UUID, limit: int = 500
) -> list[dict[str, Any]]:
    rows = await conn.fetch(
        "SELECT session, symbol, side, qty, price, notional, commission, reason "
        "FROM backtest_orders WHERE run_id = $1 ORDER BY session DESC, symbol "
        "LIMIT $2",
        run_id,
        limit,
    )
    return [
        {
            "session": r["session"].isoformat(),
            "symbol": r["symbol"],
            "side": r["side"],
            "qty": float(r["qty"]),
            "price": float(r["price"]),
            "notional": float(r["notional"]),
            "commission": float(r["commission"]),
            "reason": r["reason"],
        }
        for r in rows
    ]


def _decode_run(row: asyncpg.Record) -> dict[str, Any]:
    out = dict(row)
    for key in ("params", "cost_model", "metrics"):
        value = out.get(key)
        if isinstance(value, str):
            out[key] = json.loads(value)
    out["id"] = str(out["id"])
    for key in ("start_session", "end_session"):
        if out.get(key) is not None:
            out[key] = out[key].isoformat()
    return out
