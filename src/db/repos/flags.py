"""
flags.py
--------
System flags, of which the kill switch is the one that matters.

Fail-closed is the governing rule. :func:`trading_enabled` returns ``False`` on
a missing row, an unreadable value, *or* a database error. A control that
defaults to "go" when it cannot determine the answer is not a safety control.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import asyncpg

logger = logging.getLogger(__name__)

TRADING_ENABLED = "trading_enabled"
KILL_REASON = "kill_reason"


@dataclass(frozen=True, slots=True)
class SystemState:
    trading_enabled: bool
    reason: str | None
    updated_by: str
    updated_at: datetime | None


async def get_flag(conn: asyncpg.Connection, key: str) -> Any:
    row = await conn.fetchrow("SELECT value FROM system_flags WHERE key = $1", key)
    if row is None:
        return None
    value = row["value"]
    return json.loads(value) if isinstance(value, str) else value


async def set_flag(
    conn: asyncpg.Connection, key: str, value: Any, updated_by: str = "system"
) -> None:
    await conn.execute(
        """
        INSERT INTO system_flags (key, value, updated_by, updated_at)
        VALUES ($1, $2::jsonb, $3, NOW())
        ON CONFLICT (key) DO UPDATE
        SET value = EXCLUDED.value,
            updated_by = EXCLUDED.updated_by,
            updated_at = NOW()
        """,
        key,
        json.dumps(value),
        updated_by,
    )


async def trading_enabled(conn: asyncpg.Connection) -> bool:
    """
    Whether trading is permitted right now.

    Any failure to establish that answer returns ``False``. A worker that
    cannot reach the database must not keep placing orders on the assumption
    that nothing has changed.
    """
    try:
        value = await get_flag(conn, TRADING_ENABLED)
    except Exception as exc:  # noqa: BLE001 - deliberately broad; see docstring
        logger.error("Cannot read kill switch (%s); treating trading as DISABLED", exc)
        return False
    return value is True


async def engage_kill_switch(
    conn: asyncpg.Connection, reason: str, actor: str = "api"
) -> None:
    """Disable trading and record why."""
    async with conn.transaction():
        await set_flag(conn, TRADING_ENABLED, False, actor)
        await set_flag(conn, KILL_REASON, reason, actor)
        await conn.execute(
            "INSERT INTO audit_log (actor, action, entity_type, detail) "
            "VALUES ($1, 'kill_switch_engaged', 'system', $2::jsonb)",
            actor,
            json.dumps({"reason": reason}),
        )
    logger.warning("KILL SWITCH ENGAGED by %s: %s", actor, reason)


async def release_kill_switch(
    conn: asyncpg.Connection, actor: str = "api", note: str = ""
) -> None:
    """
    Re-enable trading.

    Deliberately a separate function from :func:`engage_kill_switch` rather
    than a boolean setter, so re-enabling is always an explicit, audited act.
    """
    async with conn.transaction():
        await set_flag(conn, TRADING_ENABLED, True, actor)
        await set_flag(conn, KILL_REASON, None, actor)
        await conn.execute(
            "INSERT INTO audit_log (actor, action, entity_type, detail) "
            "VALUES ($1, 'kill_switch_released', 'system', $2::jsonb)",
            actor,
            json.dumps({"note": note}),
        )
    logger.warning("Kill switch RELEASED by %s: %s", actor, note or "(no note)")


async def system_state(conn: asyncpg.Connection) -> SystemState:
    rows = await conn.fetch(
        "SELECT key, value, updated_by, updated_at FROM system_flags "
        "WHERE key = ANY($1)",
        [TRADING_ENABLED, KILL_REASON],
    )
    by_key = {r["key"]: r for r in rows}
    enabled_row = by_key.get(TRADING_ENABLED)
    reason_row = by_key.get(KILL_REASON)

    def _val(row: asyncpg.Record | None) -> Any:
        if row is None:
            return None
        value = row["value"]
        return json.loads(value) if isinstance(value, str) else value

    return SystemState(
        trading_enabled=_val(enabled_row) is True,
        reason=_val(reason_row),
        updated_by=enabled_row["updated_by"] if enabled_row else "unknown",
        updated_at=enabled_row["updated_at"] if enabled_row else None,
    )


async def record_audit(
    conn: asyncpg.Connection,
    actor: str,
    action: str,
    entity_type: str = "",
    entity_id: str = "",
    detail: dict[str, Any] | None = None,
) -> None:
    """Append to the audit log. Every control-plane mutation calls this."""
    await conn.execute(
        "INSERT INTO audit_log (actor, action, entity_type, entity_id, detail) "
        "VALUES ($1, $2, $3, $4, $5::jsonb)",
        actor,
        action,
        entity_type,
        entity_id,
        json.dumps(detail or {}),
    )
