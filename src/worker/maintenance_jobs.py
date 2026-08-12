"""
maintenance_jobs.py
-------------------
The three job kinds the scheduler planned and nothing implemented.

``src/engine/scheduler.py`` emits five kinds for a trading session. The worker
handled three of them; ``ingest_bars``, ``eod_marks`` and ``reconcile`` hit
"no handler for job kind" and failed without retry. The first of those is the
one that mattered most: the live decision reads ``daily_bars``, and nothing
populated it, so the live loop could never have run at all.

Each handler here is idempotent. A scheduled job may be retried, and a
re-ingested bar or a re-written mark must produce the same row rather than a
second one.
"""

from __future__ import annotations

import logging
import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import asyncpg

from src.db.repos import marks
from src.strategies import build_strategy

logger = logging.getLogger(__name__)

#: How much history to (re)fetch on an ingest. Enough to backfill a weekend or
#: a short outage without re-downloading years on every run.
INGEST_LOOKBACK_DAYS = 10

#: Fractional tolerance for a position-quantity mismatch against the venue.
#: Not zero: a venue reports fractional quantities with its own rounding, and
#: a reconciliation that alerts on the ninth decimal place is one that gets
#: muted.
POSITION_TOLERANCE = Decimal("0.000001")

#: Absolute tolerance for a cash mismatch, in dollars.
CASH_TOLERANCE = Decimal("0.01")


# ---------------------------------------------------------------------------
# Ingest
# ---------------------------------------------------------------------------


async def run_ingest_bars(
    conn: asyncpg.Connection,
    payload: dict[str, Any],
    source_factory: Any | None = None,
) -> dict[str, Any]:
    """
    Fetch recent daily bars for every deployed universe into ``daily_bars``.

    Runs 45 minutes after the close because the free Alpaca tier will not
    return a bar until it is at least 15 minutes old — a job asking for today's
    bar at 16:05 ET gets nothing at all, silently.

    The upsert keys on ``(symbol, session, source)``, so re-running is safe and
    two vendors' views of the same day coexist rather than overwriting each
    other. That is what makes reconciliation possible later.
    """
    session = _as_date(payload["session"])
    symbols = await _deployed_universe(conn)
    if not symbols:
        logger.info("%s: no enabled deployments; nothing to ingest", session)
        return {"session": session.isoformat(), "symbols": 0, "bars": 0}

    source = source_factory() if source_factory else _default_source()
    start = session - timedelta(days=INGEST_LOOKBACK_DAYS)

    try:
        bars = source.fetch(sorted(symbols), start, session)
    except Exception as exc:  # noqa: BLE001 - reported as a job failure
        logger.error("%s: bar ingest failed: %s", session, exc)
        raise

    rows = [
        (
            b.symbol, b.session, source.name, b.open, b.high, b.low,
            b.close, b.volume, b.adj_close,
        )
        for b in bars
    ]
    await conn.executemany(
        """
        INSERT INTO daily_bars (symbol, session, source, open, high, low,
                                close, volume, adj_close)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
        ON CONFLICT (symbol, session, source) DO UPDATE SET
            open = EXCLUDED.open, high = EXCLUDED.high, low = EXCLUDED.low,
            close = EXCLUDED.close, volume = EXCLUDED.volume,
            adj_close = EXCLUDED.adj_close
        """,
        rows,
    )

    latest = max((b.session for b in bars), default=None)
    if latest is not None and latest < session:
        # Worth a warning rather than a silent success: a decision computed
        # from a stale panel is a decision made on the wrong day's prices.
        logger.warning(
            "%s: newest ingested bar is %s — today's data is not yet available",
            session,
            latest,
        )

    logger.info(
        "%s: ingested %d bar(s) for %d symbol(s) from %s",
        session, len(rows), len(symbols), source.name,
    )
    return {
        "session": session.isoformat(),
        "symbols": len(symbols),
        "bars": len(rows),
        "source": source.name,
        "latest_session": latest.isoformat() if latest else None,
    }


# ---------------------------------------------------------------------------
# Marks
# ---------------------------------------------------------------------------


async def run_eod_marks(
    conn: asyncpg.Connection,
    payload: dict[str, Any],
    broker_factory: Any | None = None,
) -> dict[str, Any]:
    """
    Mark the book to the close and record the session's P&L.

    ``daily_marks`` is written by the decision job too, but only on sessions
    that decide. This runs every session, so the equity curve stays continuous
    and — because the risk gate measures drawdown against ``MAX(equity)`` from
    this table — a peak reached on a non-rebalance day is not forgotten.
    """
    session = _as_date(payload["session"])
    deployments = await _enabled_deployment_rows(conn)
    if not deployments:
        logger.info("%s: no enabled deployments; nothing to mark", session)
        return {"session": session.isoformat(), "marks": 0}

    written = []
    for deployment in deployments:
        mode = deployment["mode"]
        broker = _broker_for(deployment, broker_factory)
        async with _maybe_context(broker):
            account = await broker.get_account()

        mark = await marks.record_mark(
            conn, session, account.equity, account.cash, mode=mode
        )
        written.append(mode)
        logger.info(
            "%s [%s]: equity %s, daily P&L %s, drawdown %.2f%%",
            session, mode, account.equity, mark["daily_pnl"],
            float(mark["drawdown_pct"]) * 100,
        )

    return {"session": session.isoformat(), "marks": len(written)}


# ---------------------------------------------------------------------------
# Reconcile
# ---------------------------------------------------------------------------


async def run_reconcile(
    conn: asyncpg.Connection,
    payload: dict[str, Any],
    broker_factory: Any | None = None,
) -> dict[str, Any]:
    """
    Compare our recorded positions against the venue's, before the open.

    Runs first in the session for a reason: acting on a ledger that disagrees
    with the broker is how a small bookkeeping error becomes a real position.
    Discrepancies are reported and recorded, never silently corrected — an
    automatic "fix" that trades to make the books agree is exactly the runaway
    this is meant to catch.
    """
    session = _as_date(payload["session"])
    deployments = await _enabled_deployment_rows(conn)
    if not deployments:
        return {"session": session.isoformat(), "checked": 0, "mismatches": []}

    mismatches: list[dict[str, Any]] = []
    checked = 0

    for deployment in deployments:
        mode = deployment["mode"]
        broker = _broker_for(deployment, broker_factory)
        async with _maybe_context(broker):
            await _sync_orders(conn, deployment["id"], broker)
            account = await broker.get_account()
            venue_positions = await broker.get_positions()

        ours = await _recorded_positions(conn, deployment["id"])
        checked += 1

        for symbol in sorted(set(ours) | set(venue_positions)):
            theirs = (
                venue_positions[symbol].qty
                if symbol in venue_positions
                else Decimal("0")
            )
            mine = ours.get(symbol, Decimal("0"))
            if abs(theirs - mine) > POSITION_TOLERANCE:
                mismatches.append(
                    {
                        "deployment_id": str(deployment["id"]),
                        "kind": "position",
                        "symbol": symbol,
                        "ours": str(mine),
                        "venue": str(theirs),
                    }
                )

        last_mark = await conn.fetchrow(
            "SELECT cash FROM daily_marks WHERE mode = $1 "
            "AND session < $2 ORDER BY session DESC LIMIT 1",
            mode,
            session,
        )
        if last_mark is not None:
            drift = abs(Decimal(last_mark["cash"]) - account.cash)
            if drift > CASH_TOLERANCE:
                mismatches.append(
                    {
                        "deployment_id": str(deployment["id"]),
                        "kind": "cash",
                        "ours": str(Decimal(last_mark["cash"])),
                        "venue": str(account.cash),
                        "drift": str(drift),
                    }
                )

    if mismatches:
        # Loud, and written to the audit log: this is the signal that the
        # backtest's model of the account has diverged from the account.
        logger.error(
            "%s: reconciliation found %d mismatch(es): %s",
            session, len(mismatches), mismatches,
        )
        await conn.execute(
            "INSERT INTO audit_log (actor, action, entity_type, detail) "
            "VALUES ('worker', 'reconciliation_mismatch', 'system', $1::jsonb)",
            _json(mismatches),
        )
    else:
        logger.info("%s: reconciliation clean across %d deployment(s)",
                    session, checked)

    return {
        "session": session.isoformat(),
        "checked": checked,
        "mismatches": mismatches,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _json(value: Any) -> str:
    import json

    return json.dumps(value, default=str)


async def _deployed_universe(conn: asyncpg.Connection) -> set[str]:
    """Every symbol any enabled deployment needs."""
    symbols: set[str] = set()
    for row in await _enabled_deployment_rows(conn):
        params = row["params"]
        if isinstance(params, str):
            import json

            params = json.loads(params)
        strategy = build_strategy(row["strategy_name"], params or {})
        symbols.update(strategy.universe())
    return symbols


async def _enabled_deployment_rows(conn: asyncpg.Connection) -> list[Any]:
    return await conn.fetch(
        "SELECT id, strategy_name, params, mode FROM deployments "
        "WHERE status = 'enabled' ORDER BY created_at"
    )


async def _recorded_positions(
    conn: asyncpg.Connection, deployment_id: Any
) -> dict[str, Decimal]:
    """
    Net position per symbol implied by the fills we recorded.

    Derived from fills rather than read from a positions table, because the
    fills are the primitive: a snapshot table can drift from them, and if it
    has, that is itself the thing worth discovering.
    """
    rows = await conn.fetch(
        """
        SELECT o.symbol,
               SUM(CASE WHEN o.side = 'buy' THEN f.qty ELSE -f.qty END) AS qty
        FROM fills f
        JOIN orders o ON o.id = f.order_id
        WHERE o.deployment_id = $1
        GROUP BY o.symbol
        """,
        deployment_id,
    )
    return {
        r["symbol"]: Decimal(r["qty"])
        for r in rows
        if r["qty"] is not None and abs(Decimal(r["qty"])) > POSITION_TOLERANCE
    }


async def _sync_orders(
    conn: asyncpg.Connection, deployment_id: Any, broker: Any
) -> None:
    rows = await conn.fetch(
        "SELECT id, broker_order_id FROM orders "
        "WHERE deployment_id = $1 AND broker_order_id IS NOT NULL "
        "AND status IN ('pending', 'submitted', 'partially_filled')",
        deployment_id,
    )
    for row in rows:
        status = await broker.get_order(row["broker_order_id"])
        async with conn.transaction():
            await conn.execute(
                "UPDATE orders SET status = $2, updated_at = NOW() WHERE id = $1",
                row["id"],
                status.state.value,
            )
            if status.fills:
                fill = status.fills[0]
                await conn.execute("DELETE FROM fills WHERE order_id = $1", row["id"])
                await conn.execute(
                    """
                    INSERT INTO fills (id, order_id, symbol, side, qty, price,
                                       commission, filled_at)
                    VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
                    """,
                    uuid.uuid4(),
                    row["id"],
                    fill.symbol,
                    fill.side.value,
                    fill.qty,
                    fill.price,
                    fill.commission,
                    fill.filled_at,
                )


def _default_source() -> Any:
    from src.data import YFinanceSource

    return YFinanceSource()


def _broker_for(deployment: Any, broker_factory: Any | None) -> Any:
    if broker_factory is not None:
        return broker_factory()
    from src.worker.live_job import _alpaca_from_env

    return _alpaca_from_env({"mode": deployment["mode"]})


class _NullContext:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *exc: object) -> None:
        return None


def _maybe_context(broker: Any) -> Any:
    return broker if hasattr(broker, "__aenter__") else _NullContext()


def _as_date(value: Any) -> date:
    from datetime import datetime

    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    return date.fromisoformat(str(value))


__all__ = [
    "run_eod_marks",
    "run_ingest_bars",
    "run_reconcile",
]
