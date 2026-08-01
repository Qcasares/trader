"""
scheduling.py
-------------
Turns the calendar-derived session plan into rows in the job queue.

``src/engine/scheduler.py`` computes *what* a trading session needs and when.
Nothing called it. The module was written, tested and orphaned: the live loop
had a planner and a queue with no wire between them, so no live job was ever
enqueued and the three job kinds with no handler were never even reached.

This is that wire, kept deliberately thin. The planner stays pure — a function
from a date to a list of ``PlannedJob`` — and the database work lives here,
so the scheduling logic remains testable without a database and the enqueue
logic remains testable without a calendar.

Idempotency
~~~~~~~~~~~
Every scheduled job carries ``dedupe_key = "{kind}:{session}"`` and a unique
index refuses a second insert. That makes it safe to plan on every worker
startup, which is what makes the plan survive a restart without either a
durable scheduler or a misfire storm.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

import asyncpg

from src.db.repos import jobs as job_repo
from src.engine.scheduler import PlannedJob, plan_session

logger = logging.getLogger(__name__)

#: Reconciliation and submission are time-critical relative to the open;
#: research work can wait behind them.
PRIORITY: dict[str, int] = {
    "reconcile": 30,
    "submit_orders": 20,
    "live_decision": 10,
    "ingest_bars": 5,
    "eod_marks": 5,
}


def dedupe_key(kind: str, session: date) -> str:
    """Stable identity for one scheduled job."""
    return f"{kind}:{session.isoformat()}"


async def plan_and_enqueue(
    conn: asyncpg.Connection,
    session: date,
    deployment_ids: list[str] | None = None,
) -> dict[str, Any]:
    """
    Enqueue the day's jobs, skipping any already present.

    Returns a summary rather than raising on a duplicate: "already scheduled"
    is the expected outcome on every startup after the first, not an error.
    """
    planned: list[PlannedJob] = plan_session(session, deployment_ids)
    if not planned:
        logger.info("%s is not a trading session; nothing enqueued", session)
        return {"session": session.isoformat(), "enqueued": 0, "skipped": 0}

    enqueued: list[str] = []
    skipped: list[str] = []
    for job in planned:
        job_id = await job_repo.enqueue(
            conn,
            job.kind.value,
            payload=dict(job.payload),
            priority=PRIORITY.get(job.kind.value, 0),
            scheduled_for=job.run_at,
            dedupe_key=dedupe_key(job.kind.value, session),
        )
        (enqueued if job_id is not None else skipped).append(job.kind.value)

    logger.info(
        "%s: enqueued %d job(s), %d already scheduled",
        session, len(enqueued), len(skipped),
    )
    return {
        "session": session.isoformat(),
        "enqueued": len(enqueued),
        "skipped": len(skipped),
        "kinds": enqueued,
    }
