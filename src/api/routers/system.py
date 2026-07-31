"""
system.py
---------
The control plane: status, kill switch, jobs.

The kill switch is the only endpoint here that matters under stress, so it is
deliberately the simplest: one POST, one required field, no toggle semantics.
Engaging never fails on a bad reason string and never requires a confirmation
token — the asymmetry is intentional. Stopping should be frictionless;
starting should not.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Query

from src.api.deps import AppSettings, AuthedSession, DbConn
from src.api.schemas import (
    JobSummary,
    KillSwitchRequest,
    ReleaseKillSwitchRequest,
    SystemStatus,
)
from src.db.repos import flags
from src.db.repos import jobs as job_repo

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/system", tags=["system"])


async def _build_status(conn, settings: AppSettings) -> SystemStatus:
    """
    Assemble the complete system status.

    Shared by every endpoint in this module rather than reconstructed per
    handler. An earlier version had ``/kill`` and ``/resume`` build their own
    response and omit ``workers``, which defaults to empty — so the moment an
    operator halted trading, the UI also told them no worker was alive. A false
    alarm is worst precisely when someone is already reacting to a problem.
    """
    state = await flags.system_state(conn)
    workers = await conn.fetch(
        "SELECT worker_id, last_seen, status FROM worker_heartbeats "
        "ORDER BY last_seen DESC LIMIT 10"
    )
    return SystemStatus(
        trading_enabled=state.trading_enabled,
        kill_reason=state.reason,
        updated_by=state.updated_by,
        updated_at=state.updated_at.isoformat() if state.updated_at else None,
        live_trading_enabled=settings.live_trading_enabled,
        broker_configured=settings.has_broker_credentials,
        jobs=await job_repo.counts_by_status(conn),
        workers=[
            {
                "worker_id": w["worker_id"],
                "last_seen": w["last_seen"].isoformat(),
                "status": w["status"],
            }
            for w in workers
        ],
        database_ok=True,
    )


@router.get("/status", response_model=SystemStatus)
async def get_status(
    session: AuthedSession, conn: DbConn, settings: AppSettings
) -> SystemStatus:
    """Everything needed to answer "is it running and is it safe"."""
    return await _build_status(conn, settings)


@router.post("/kill", response_model=SystemStatus)
async def kill(
    body: KillSwitchRequest,
    session: AuthedSession,
    conn: DbConn,
    settings: AppSettings,
) -> SystemStatus:
    """
    Engage the kill switch.

    Sets the durable flag the worker checks before every submission. In a
    deployment with a live broker this endpoint would also call
    ``broker.cancel_all()`` synchronously — the flag stops new orders, the
    cancel deals with the ones already in flight, and neither alone is enough.
    That half lands with the Alpaca adapter; today there is no live venue to
    cancel against, so engaging the flag is the whole of it.
    """
    await flags.engage_kill_switch(conn, body.reason, actor=session.subject)
    return await _build_status(conn, settings)


@router.post("/resume", response_model=SystemStatus)
async def resume(
    body: ReleaseKillSwitchRequest,
    session: AuthedSession,
    conn: DbConn,
    settings: AppSettings,
) -> SystemStatus:
    """
    Re-enable trading. Requires the literal confirmation string.

    The typed confirmation is validated by the request model, so a malformed
    attempt never reaches the flag.
    """
    await flags.release_kill_switch(conn, actor=session.subject, note=body.note)
    return await _build_status(conn, settings)


@router.get("/jobs", response_model=list[JobSummary])
async def list_jobs(
    session: AuthedSession,
    conn: DbConn,
    job_status: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[JobSummary]:
    rows = await job_repo.list_jobs(conn, job_status, limit)
    return [
        JobSummary(
            id=str(r["id"]),
            kind=r["kind"],
            status=r["status"],
            attempts=r["attempts"],
            max_attempts=r["max_attempts"],
            error=r["error"],
            created_at=r["created_at"].isoformat() if r["created_at"] else None,
            finished_at=r["finished_at"].isoformat() if r["finished_at"] else None,
        )
        for r in rows
    ]


@router.get("/audit")
async def audit(
    session: AuthedSession, conn: DbConn, limit: int = Query(default=50, ge=1, le=200)
) -> list[dict]:
    rows = await conn.fetch(
        "SELECT actor, action, entity_type, entity_id, detail, at "
        "FROM audit_log ORDER BY at DESC LIMIT $1",
        limit,
    )
    return [
        {
            "actor": r["actor"],
            "action": r["action"],
            "entity_type": r["entity_type"],
            "entity_id": r["entity_id"],
            "detail": r["detail"],
            "at": r["at"].isoformat(),
        }
        for r in rows
    ]
