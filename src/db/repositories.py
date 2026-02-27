"""
repositories.py
---------------
Typed async CRUD functions for all 9 database tables.

Every function takes a DatabasePool as its first argument and uses
parameterised queries ($1, $2, …) — never string interpolation.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from src.db.connection import DatabasePool

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _record_to_dict(record) -> dict[str, Any]:
    """Convert an asyncpg Record to a plain dict."""
    return dict(record)


def _records_to_dicts(records) -> list[dict[str, Any]]:
    """Convert a list of asyncpg Records to a list of dicts."""
    return [dict(r) for r in records]


# =========================================================================
# INSERT functions — each returns the new row's id
# =========================================================================

async def insert_social_post(pool: DatabasePool, data: dict[str, Any]) -> int:
    """Insert a raw social post. Returns the new row id."""
    return await pool.fetchval(
        """
        INSERT INTO raw_social_posts
            (source, post_id, text, author, follower_count, posted_at, url, mentioned_tickers)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        ON CONFLICT (post_id) DO NOTHING
        RETURNING id
        """,
        data["source"],
        data["post_id"],
        data["text"],
        data["author"],
        data.get("follower_count", 0),
        data["posted_at"],
        data.get("url", ""),
        data.get("mentioned_tickers", []),
    )


async def insert_price_candle(pool: DatabasePool, data: dict[str, Any]) -> int:
    """Insert a price candle. Returns the new row id."""
    return await pool.fetchval(
        """
        INSERT INTO price_candles
            (ticker, timestamp, open, high, low, close, volume)
        VALUES ($1, $2, $3, $4, $5, $6, $7)
        ON CONFLICT (ticker, timestamp) DO NOTHING
        RETURNING id
        """,
        data["ticker"],
        data["timestamp"],
        data["open"],
        data["high"],
        data["low"],
        data["close"],
        data.get("volume", 0),
    )


async def insert_sentiment_score(pool: DatabasePool, data: dict[str, Any]) -> int:
    """Insert a sentiment score row. Returns the new row id."""
    return await pool.fetchval(
        """
        INSERT INTO sentiment_scores
            (ticker, post_id, source, raw_score, confidence, method,
             follower_weight, weighted_score, composite_score, post_count,
             source_breakdown, momentum, anomaly_detected)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
        RETURNING id
        """,
        data["ticker"],
        data.get("post_id"),
        data.get("source"),
        data.get("raw_score"),
        data.get("confidence"),
        data.get("method"),
        data.get("follower_weight"),
        data.get("weighted_score"),
        data.get("composite_score"),
        data.get("post_count"),
        data.get("source_breakdown"),       # JSONB — asyncpg handles dicts
        data.get("momentum"),
        data.get("anomaly_detected", False),
    )


async def insert_technical_signal(pool: DatabasePool, data: dict[str, Any]) -> int:
    """Insert a technical signal row. Returns the new row id."""
    return await pool.fetchval(
        """
        INSERT INTO technical_signals
            (ticker, rsi_14, macd_line, macd_signal, macd_histogram,
             bb_upper, bb_middle, bb_lower, bb_position,
             obv, obv_trend, volume_surge, volume_ratio,
             current_price, price_change_pct,
             direction, strength, patterns, rationale)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13,
                $14, $15, $16, $17, $18, $19)
        RETURNING id
        """,
        data["ticker"],
        data.get("rsi_14"),
        data.get("macd_line"),
        data.get("macd_signal"),
        data.get("macd_histogram"),
        data.get("bb_upper"),
        data.get("bb_middle"),
        data.get("bb_lower"),
        data.get("bb_position"),
        data.get("obv"),
        data.get("obv_trend"),
        data.get("volume_surge", False),
        data.get("volume_ratio", 1.0),
        data.get("current_price"),
        data.get("price_change_pct"),
        data.get("direction"),
        data.get("strength"),
        data.get("patterns"),               # JSONB
        data.get("rationale", ""),
    )


async def insert_trade_signal(pool: DatabasePool, data: dict[str, Any]) -> int:
    """Insert a trade signal. Returns the new row id."""
    return await pool.fetchval(
        """
        INSERT INTO trade_signals
            (ticker, action, combined_score, confidence,
             sentiment_score, technical_score, volume_signal,
             rationale, anomaly_adjusted)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
        RETURNING id
        """,
        data["ticker"],
        data["action"],
        data["combined_score"],
        data["confidence"],
        data["sentiment_score"],
        data["technical_score"],
        data["volume_signal"],
        data.get("rationale", ""),
        data.get("anomaly_adjusted", False),
    )


async def insert_risk_decision(pool: DatabasePool, data: dict[str, Any]) -> int:
    """Insert a risk decision. Returns the new row id."""
    return await pool.fetchval(
        """
        INSERT INTO risk_decisions
            (ticker, approved, action, proposed_amount_usd,
             adjusted_amount_usd, reason, stop_loss_triggered,
             trade_signal_id)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        RETURNING id
        """,
        data["ticker"],
        data["approved"],
        data["action"],
        data["proposed_amount_usd"],
        data.get("adjusted_amount_usd"),
        data.get("reason", ""),
        data.get("stop_loss_triggered", False),
        data.get("trade_signal_id"),
    )


async def insert_trade_result(pool: DatabasePool, data: dict[str, Any]) -> int:
    """Insert a trade execution result. Returns the new row id."""
    return await pool.fetchval(
        """
        INSERT INTO trade_results
            (ticker, action, amount_usd, success, job_id,
             response, slippage_pct, error, risk_decision_id)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
        RETURNING id
        """,
        data["ticker"],
        data["action"],
        data["amount_usd"],
        data["success"],
        data.get("job_id"),
        data.get("response", ""),
        data.get("slippage_pct"),
        data.get("error"),
        data.get("risk_decision_id"),
    )


async def insert_portfolio_snapshot(pool: DatabasePool, data: dict[str, Any]) -> int:
    """Insert a portfolio snapshot. Returns the new row id."""
    return await pool.fetchval(
        """
        INSERT INTO portfolio_snapshots
            (total_value_usd, positions, daily_pnl_usd,
             cumulative_pnl_usd, max_drawdown_pct)
        VALUES ($1, $2, $3, $4, $5)
        RETURNING id
        """,
        data.get("total_value_usd", 0),
        data.get("positions", {}),          # JSONB
        data.get("daily_pnl_usd", 0),
        data.get("cumulative_pnl_usd", 0),
        data.get("max_drawdown_pct", 0),
    )


async def upsert_agent_heartbeat(pool: DatabasePool, data: dict[str, Any]) -> int:
    """
    Insert or update an agent heartbeat.

    Uses INSERT ... ON CONFLICT (agent_role) DO UPDATE to maintain
    a single row per agent.  Returns the row id.
    """
    return await pool.fetchval(
        """
        INSERT INTO agent_heartbeats
            (agent_role, last_seen, status, cycles_completed, last_error, updated_at)
        VALUES ($1, $2, $3, $4, $5, NOW())
        ON CONFLICT (agent_role) DO UPDATE SET
            last_seen        = EXCLUDED.last_seen,
            status           = EXCLUDED.status,
            cycles_completed = EXCLUDED.cycles_completed,
            last_error       = EXCLUDED.last_error,
            updated_at       = NOW()
        RETURNING id
        """,
        data["agent_role"],
        data.get("last_seen", datetime.now(timezone.utc)),
        data.get("status", "idle"),
        data.get("cycles_completed", 0),
        data.get("last_error"),
    )


# =========================================================================
# QUERY functions
# =========================================================================

async def get_recent_trades(
    pool: DatabasePool, ticker: str, limit: int = 10
) -> list[dict[str, Any]]:
    """Return the most recent trade results for a ticker."""
    rows = await pool.fetch(
        """
        SELECT * FROM trade_results
        WHERE ticker = $1
        ORDER BY executed_at DESC
        LIMIT $2
        """,
        ticker,
        limit,
    )
    return _records_to_dicts(rows)


async def get_daily_pnl(pool: DatabasePool) -> float:
    """
    Return today's aggregate P&L in USD.

    Convention: buy trades are negative (money out), sell trades are
    positive (money in).  Only successful trades are counted.
    """
    row = await pool.fetchrow(
        """
        SELECT COALESCE(
            SUM(
                CASE WHEN action = 'sell' THEN amount_usd
                     WHEN action = 'buy'  THEN -amount_usd
                     ELSE 0
                END
            ), 0
        ) AS daily_pnl
        FROM trade_results
        WHERE success = TRUE
          AND executed_at >= CURRENT_DATE
        """
    )
    return float(row["daily_pnl"]) if row else 0.0


async def get_portfolio_positions(pool: DatabasePool) -> dict[str, Any]:
    """Return the positions JSONB from the latest portfolio snapshot."""
    row = await pool.fetchrow(
        """
        SELECT positions FROM portfolio_snapshots
        ORDER BY snapshot_time DESC
        LIMIT 1
        """
    )
    if row is None:
        return {}
    return row["positions"] if row["positions"] else {}


async def get_latest_portfolio_snapshot(
    pool: DatabasePool,
) -> Optional[dict[str, Any]]:
    """Return the most recent portfolio snapshot as a dict, or None."""
    row = await pool.fetchrow(
        """
        SELECT * FROM portfolio_snapshots
        ORDER BY snapshot_time DESC
        LIMIT 1
        """
    )
    return _record_to_dict(row) if row else None


async def get_agent_heartbeat(
    pool: DatabasePool, agent_role: str
) -> Optional[dict[str, Any]]:
    """Return the heartbeat for a specific agent role, or None."""
    row = await pool.fetchrow(
        """
        SELECT * FROM agent_heartbeats
        WHERE agent_role = $1
        """,
        agent_role,
    )
    return _record_to_dict(row) if row else None


async def get_recent_signals(
    pool: DatabasePool, ticker: str, limit: int = 10
) -> list[dict[str, Any]]:
    """Return the most recent trade signals for a ticker."""
    rows = await pool.fetch(
        """
        SELECT * FROM trade_signals
        WHERE ticker = $1
        ORDER BY created_at DESC
        LIMIT $2
        """,
        ticker,
        limit,
    )
    return _records_to_dicts(rows)


async def get_trade_history(
    pool: DatabasePool, since_hours: int = 24
) -> list[dict[str, Any]]:
    """
    Return trade results joined with risk decisions for the last N hours.

    Provides a complete picture: why the trade was approved and what happened.
    """
    rows = await pool.fetch(
        """
        SELECT
            tr.id,
            tr.ticker,
            tr.action,
            tr.amount_usd,
            tr.success,
            tr.job_id,
            tr.slippage_pct,
            tr.error,
            tr.executed_at,
            rd.approved       AS risk_approved,
            rd.proposed_amount_usd AS risk_proposed,
            rd.adjusted_amount_usd AS risk_adjusted,
            rd.reason          AS risk_reason,
            rd.stop_loss_triggered
        FROM trade_results tr
        LEFT JOIN risk_decisions rd ON tr.risk_decision_id = rd.id
        WHERE tr.executed_at >= NOW() - INTERVAL '1 hour' * $1
        ORDER BY tr.executed_at DESC
        """,
        since_hours,
    )
    return _records_to_dicts(rows)
