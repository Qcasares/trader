"""
marks.py
--------
``daily_marks`` — the equity curve of the live account, and the memory the
risk gate runs on.

Two jobs, and the second is the one that was missing
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
1. It is the P&L record. ``daily_pnl = equity_t - equity_{t-1} - net deposits``
   — a change in *marked equity*, never a sum of cash flow. The legacy
   ``get_daily_pnl`` in ``src/db/repositories.py`` sums buy/sell cash flow, so
   a $100 purchase reads as a $100 loss and a daily-loss breaker built on it
   trips after two trades regardless of performance. That is why this exists
   separately rather than being fixed in place.

2. It is where a live :class:`~src.engine.driver.Driver` gets its equity
   history. A backtest walks every session in one process and accumulates
   peak and prior equity as it goes. A live process is constructed fresh for
   each job, so without persistence its peak equity is zero, its drawdown is
   zero, and ``max_drawdown_pct`` never binds — the backtest would honour a
   limit the live system ignored.

The table has no ``peak_equity`` column and does not need one: the peak is
``MAX(equity)`` over the history, which cannot drift out of step with the
equity it is derived from.
"""

from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal
from typing import Any

import asyncpg

logger = logging.getLogger(__name__)

DEFAULT_OWNER = "default"


async def record_mark(
    conn: asyncpg.Connection,
    session: date,
    equity: Decimal,
    cash: Decimal,
    mode: str = "paper",
    deposits: Decimal = Decimal("0"),
    withdrawals: Decimal = Decimal("0"),
    owner_id: str = DEFAULT_OWNER,
) -> dict[str, Any]:
    """
    Write one session's mark, deriving P&L and drawdown from history.

    Idempotent on ``(owner_id, mode, session)``: a retried job overwrites its
    own row rather than creating a second one, because the mark is a statement
    about a session and a session has only one closing equity.
    """
    previous = await conn.fetchrow(
        """
        SELECT equity, cumulative_pnl FROM daily_marks
        WHERE owner_id = $1 AND mode = $2 AND session < $3
        ORDER BY session DESC LIMIT 1
        """,
        owner_id,
        mode,
        session,
    )

    net_flow = deposits - withdrawals
    if previous is None:
        # The first mark has nothing to difference against, so the honest
        # daily P&L is zero rather than the whole opening balance.
        daily_pnl = Decimal("0")
        cumulative = Decimal("0")
    else:
        daily_pnl = equity - Decimal(previous["equity"]) - net_flow
        cumulative = Decimal(previous["cumulative_pnl"]) + daily_pnl

    peak = await peak_equity(conn, mode=mode, owner_id=owner_id, upto=session)
    peak = max(peak, equity)
    drawdown = (equity / peak - 1) if peak > 0 else Decimal("0")

    await conn.execute(
        """
        INSERT INTO daily_marks (owner_id, mode, session, equity, cash,
                                 deposits, withdrawals, daily_pnl,
                                 cumulative_pnl, drawdown_pct)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
        ON CONFLICT (owner_id, mode, session) DO UPDATE SET
            equity = EXCLUDED.equity,
            cash = EXCLUDED.cash,
            deposits = EXCLUDED.deposits,
            withdrawals = EXCLUDED.withdrawals,
            daily_pnl = EXCLUDED.daily_pnl,
            cumulative_pnl = EXCLUDED.cumulative_pnl,
            drawdown_pct = EXCLUDED.drawdown_pct
        """,
        owner_id,
        mode,
        session,
        equity,
        cash,
        deposits,
        withdrawals,
        daily_pnl,
        cumulative,
        drawdown,
    )
    return {
        "session": session,
        "equity": equity,
        "daily_pnl": daily_pnl,
        "cumulative_pnl": cumulative,
        "drawdown_pct": drawdown,
    }


async def peak_equity(
    conn: asyncpg.Connection,
    mode: str = "paper",
    owner_id: str = DEFAULT_OWNER,
    upto: date | None = None,
) -> Decimal:
    """
    Highest marked equity so far. ``Decimal("0")`` when there is no history.

    ``upto`` is exclusive, so recomputing a session's mark does not let that
    session's own equity define the peak it is measured against.
    """
    if upto is None:
        row = await conn.fetchrow(
            "SELECT MAX(equity) AS peak FROM daily_marks "
            "WHERE owner_id = $1 AND mode = $2",
            owner_id,
            mode,
        )
    else:
        row = await conn.fetchrow(
            "SELECT MAX(equity) AS peak FROM daily_marks "
            "WHERE owner_id = $1 AND mode = $2 AND session < $3",
            owner_id,
            mode,
            upto,
        )
    if row is None or row["peak"] is None:
        return Decimal("0")
    return Decimal(row["peak"])


async def prior_equity(
    conn: asyncpg.Connection,
    session: date,
    mode: str = "paper",
    owner_id: str = DEFAULT_OWNER,
) -> Decimal:
    """
    Marked equity as of the last session before ``session``.

    This is what a session opens at, and therefore what its daily loss is
    measured from. Zero when there is no prior mark, which the gate reads as
    "no daily P&L yet" rather than as a total loss.
    """
    row = await conn.fetchrow(
        """
        SELECT equity FROM daily_marks
        WHERE owner_id = $1 AND mode = $2 AND session < $3
        ORDER BY session DESC LIMIT 1
        """,
        owner_id,
        mode,
        session,
    )
    if row is None:
        return Decimal("0")
    return Decimal(row["equity"])


async def history(
    conn: asyncpg.Connection,
    mode: str = "paper",
    owner_id: str = DEFAULT_OWNER,
    limit: int = 500,
) -> list[dict[str, Any]]:
    """Marks, most recent first. The live equity curve the UI plots."""
    rows = await conn.fetch(
        """
        SELECT session, equity, cash, daily_pnl, cumulative_pnl, drawdown_pct
        FROM daily_marks WHERE owner_id = $1 AND mode = $2
        ORDER BY session DESC LIMIT $3
        """,
        owner_id,
        mode,
        limit,
    )
    return [
        {
            "session": r["session"].isoformat(),
            "equity": float(r["equity"]),
            "cash": float(r["cash"]),
            "daily_pnl": float(r["daily_pnl"]),
            "cumulative_pnl": float(r["cumulative_pnl"]),
            "drawdown_pct": float(r["drawdown_pct"]),
        }
        for r in rows
    ]
