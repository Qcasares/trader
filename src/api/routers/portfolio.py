"""
portfolio.py
------------
What the account is actually worth, and how it got there.

Reads ``daily_marks`` — the equity-change record. Its predecessor,
``get_daily_pnl``, summed buy/sell cash flow and would have reported a $100
purchase as a $100 loss; it was deleted with the pipeline it served.

Why this is a separate router from ``deployments``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
A deployment is a strategy running with a configuration. The portfolio is the
account, which several deployments may share. Reporting P&L per deployment
would require attributing a shared cash balance between them, and any such
attribution is an accounting choice rather than a fact. The account is the unit
that has an unambiguous equity curve, so it is the unit reported here.

Every figure carries its mode. A paper equity curve and a live one are not
comparable and must never be summed.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from src.api.deps import AuthedSession, DbConn
from src.db.repos import marks

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/portfolio", tags=["portfolio"])

VALID_MODES = ("paper", "live")


def _check_mode(mode: str) -> str:
    if mode not in VALID_MODES:
        raise HTTPException(422, f"mode must be one of {VALID_MODES}, got {mode!r}")
    return mode


@router.get("")
async def portfolio(
    session: AuthedSession,
    conn: DbConn,
    mode: str = Query(default="paper"),
) -> dict[str, Any]:
    """
    Current equity, cash, P&L and open positions.

    Returns nulls rather than zeros when there is no history. Zero equity and
    *unknown* equity are different states, and rendering the second as the
    first would show an operator a flat line where they should see "no data".
    """
    _check_mode(mode)

    # `owner_id` is filtered here for the same reason `marks.history` and
    # `marks.peak_equity` filter it, and this query was the one place that did
    # not. `daily_marks` is keyed on (owner_id, mode, session), so without it
    # this read crosses accounts while the two figures it is displayed beside
    # do not: the equity in the metric grid came from whichever owner happened
    # to hold the newest row, while the curve underneath it and the peak it is
    # measured against came from `default`. One owner's balance above another
    # owner's equity curve, with nothing on screen to say so.
    #
    # Latent while `record_mark` is the only writer, since it defaults to
    # `default` — but a query that disagrees with its two siblings is a bug
    # waiting for a second account, and it produced exactly that mismatch the
    # first time one existed.
    latest = await conn.fetchrow(
        """
        SELECT session, equity, cash, daily_pnl, cumulative_pnl, drawdown_pct
        FROM daily_marks WHERE owner_id = $1 AND mode = $2
        ORDER BY session DESC LIMIT 1
        """,
        marks.DEFAULT_OWNER,
        mode,
    )
    peak = await marks.peak_equity(conn, mode=mode)
    positions = await _open_positions(conn, mode)

    if latest is None:
        return {
            "mode": mode,
            "as_of": None,
            "equity": None,
            "cash": None,
            "daily_pnl": None,
            "cumulative_pnl": None,
            "drawdown_pct": None,
            "peak_equity": None,
            "positions": positions,
            "note": "no marks recorded yet",
        }

    return {
        "mode": mode,
        "as_of": latest["session"].isoformat(),
        "equity": float(latest["equity"]),
        "cash": float(latest["cash"]),
        "daily_pnl": float(latest["daily_pnl"]),
        "cumulative_pnl": float(latest["cumulative_pnl"]),
        "drawdown_pct": float(latest["drawdown_pct"]),
        "peak_equity": float(peak),
        "positions": positions,
    }


@router.get("/history")
async def history(
    session: AuthedSession,
    conn: DbConn,
    mode: str = Query(default="paper"),
    limit: int = Query(default=500, ge=1, le=5000),
) -> dict[str, Any]:
    """
    The live equity curve, oldest first so a chart can plot it directly.

    ``marks.history`` returns newest-first because that is what a table wants;
    reversing here rather than adding a second query keeps one definition of
    what a mark is.
    """
    _check_mode(mode)
    rows = await marks.history(conn, mode=mode, limit=limit)
    rows.reverse()
    return {"mode": mode, "count": len(rows), "marks": rows}


async def _open_positions(conn: Any, mode: str) -> list[dict[str, Any]]:
    """
    Net position per symbol, derived from recorded fills.

    Derived rather than read from a snapshot table for the same reason
    reconciliation derives it: the fills are the primitive, and a snapshot that
    disagrees with them is a finding rather than a source.
    """
    rows = await conn.fetch(
        """
        SELECT o.symbol,
               SUM(CASE WHEN o.side = 'buy' THEN f.qty ELSE -f.qty END) AS qty,
               SUM(CASE WHEN o.side = 'buy' THEN f.qty * f.price ELSE 0 END) AS bought,
               SUM(CASE WHEN o.side = 'buy' THEN f.qty ELSE 0 END) AS bought_qty
        FROM fills f
        JOIN orders o ON o.id = f.order_id
        JOIN deployments d ON d.id = o.deployment_id
        WHERE d.mode = $1
        GROUP BY o.symbol
        ORDER BY o.symbol
        """,
        mode,
    )
    out: list[dict[str, Any]] = []
    for row in rows:
        qty = Decimal(row["qty"] or 0)
        if abs(qty) < Decimal("0.000001"):
            continue
        bought_qty = Decimal(row["bought_qty"] or 0)
        avg = (
            float(Decimal(row["bought"] or 0) / bought_qty)
            if bought_qty > 0
            else None
        )
        out.append(
            {
                "symbol": row["symbol"],
                "qty": float(qty),
                # Average *purchase* price, not a mark. Naming it
                # avg_entry_price rather than "value" avoids implying this
                # endpoint knows a current price; it does not, and inventing
                # one from a stale bar would be worse than omitting it.
                "avg_entry_price": avg,
            }
        )
    return out
