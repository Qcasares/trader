"""
jobs.py
-------
A durable job queue built on Postgres.

No Redis. At the volume this system will see — a few dozen jobs a day — a
second stateful service to run, back up and monitor buys nothing that
``SELECT ... FOR UPDATE SKIP LOCKED`` does not already provide, and the queue
being in the same database as the results means a job and its output commit or
roll back together.

Leases rather than locks
~~~~~~~~~~~~~~~~~~~~~~~~
A claimed job records ``lease_expires_at``. A worker that dies mid-job does not
hold anything forever: :func:`requeue_expired` returns the job to the queue
once its lease lapses. This is why a long-running job must call
:func:`extend_lease` — a backtest that takes longer than its lease will
otherwise be picked up a second time and run twice.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import asyncpg

logger = logging.getLogger(__name__)

DEFAULT_LEASE = timedelta(minutes=5)


@dataclass(frozen=True, slots=True)
class Job:
    id: uuid.UUID
    kind: str
    payload: dict[str, Any]
    status: str
    attempts: int
    max_attempts: int
    created_at: datetime

    @property
    def is_final_attempt(self) -> bool:
        return self.attempts >= self.max_attempts


def _row_to_job(row: asyncpg.Record) -> Job:
    payload = row["payload"]
    if isinstance(payload, str):
        payload = json.loads(payload)
    return Job(
        id=row["id"],
        kind=row["kind"],
        payload=payload or {},
        status=row["status"],
        attempts=row["attempts"],
        max_attempts=row["max_attempts"],
        created_at=row["created_at"],
    )


async def enqueue(
    conn: asyncpg.Connection,
    kind: str,
    payload: dict[str, Any] | None = None,
    priority: int = 0,
    max_attempts: int = 3,
    scheduled_for: datetime | None = None,
    dedupe_key: str | None = None,
) -> uuid.UUID | None:
    """
    Add a job. Returns its id, or ``None`` when ``dedupe_key`` already exists.

    A ``dedupe_key`` makes the insert idempotent, which is what lets the
    session planner run on every worker startup without enqueuing the day's
    work twice. Ad-hoc jobs pass no key and may repeat freely.
    """
    job_id = uuid.uuid4()
    inserted = await conn.fetchval(
        """
        INSERT INTO jobs (id, kind, payload, priority, max_attempts,
                          scheduled_for, dedupe_key)
        VALUES ($1, $2, $3::jsonb, $4, $5, COALESCE($6, NOW()), $7)
        ON CONFLICT (dedupe_key) WHERE dedupe_key IS NOT NULL DO NOTHING
        RETURNING id
        """,
        job_id,
        kind,
        json.dumps(payload or {}),
        priority,
        max_attempts,
        scheduled_for,
        dedupe_key,
    )
    if inserted is None:
        return None
    # Wake an idle worker immediately rather than waiting for its poll tick.
    await conn.execute("SELECT pg_notify('jobs_new', $1)", kind)
    return job_id


async def claim(
    conn: asyncpg.Connection,
    worker_id: str,
    kinds: list[str] | None = None,
    lease: timedelta = DEFAULT_LEASE,
) -> Job | None:
    """
    Atomically take the next available job.

    ``FOR UPDATE SKIP LOCKED`` is what makes this safe with several workers:
    each skips rows another has locked rather than blocking behind them.
    """
    row = await conn.fetchrow(
        """
        WITH next_job AS (
            SELECT id FROM jobs
            WHERE status = 'queued'
              AND scheduled_for <= NOW()
              AND ($2::text[] IS NULL OR kind = ANY($2))
            ORDER BY priority DESC, scheduled_for
            FOR UPDATE SKIP LOCKED
            LIMIT 1
        )
        UPDATE jobs
        SET status = 'running',
            locked_by = $1,
            lease_expires_at = NOW() + $3::interval,
            attempts = attempts + 1,
            started_at = COALESCE(started_at, NOW())
        FROM next_job
        WHERE jobs.id = next_job.id
        RETURNING jobs.*
        """,
        worker_id,
        kinds,
        lease,
    )
    return _row_to_job(row) if row else None


async def extend_lease(
    conn: asyncpg.Connection, job_id: uuid.UUID, lease: timedelta = DEFAULT_LEASE
) -> None:
    """Push a running job's lease out. Call periodically from long jobs."""
    await conn.execute(
        "UPDATE jobs SET lease_expires_at = NOW() + $2::interval "
        "WHERE id = $1 AND status = 'running'",
        job_id,
        lease,
    )


async def complete(
    conn: asyncpg.Connection, job_id: uuid.UUID, result: dict[str, Any] | None = None
) -> None:
    await conn.execute(
        """
        UPDATE jobs
        SET status = 'succeeded', result = $2::jsonb,
            finished_at = NOW(), lease_expires_at = NULL, error = NULL
        WHERE id = $1
        """,
        job_id,
        json.dumps(result or {}),
    )


async def fail(
    conn: asyncpg.Connection, job_id: uuid.UUID, error: str, retry: bool = True
) -> str:
    """
    Mark a job failed. Requeues it if retries remain and ``retry`` is set.

    Returns the resulting status so the caller can log which happened.
    """
    row = await conn.fetchrow(
        "SELECT attempts, max_attempts FROM jobs WHERE id = $1", job_id
    )
    if row is None:
        raise KeyError(f"unknown job {job_id}")

    should_retry = retry and row["attempts"] < row["max_attempts"]
    status = "queued" if should_retry else "failed"
    await conn.execute(
        """
        UPDATE jobs
        SET status = $2,
            error = $3,
            lease_expires_at = NULL,
            locked_by = NULL,
            finished_at = CASE WHEN $2 = 'failed' THEN NOW() ELSE NULL END,
            -- back off a little before the next attempt
            scheduled_for = CASE
                WHEN $2 = 'queued' THEN NOW() + (attempts * INTERVAL '10 seconds')
                ELSE scheduled_for END
        WHERE id = $1
        """,
        job_id,
        status,
        error[:4000],
    )
    return status


async def requeue_expired(conn: asyncpg.Connection) -> int:
    """
    Return jobs whose worker died to the queue. Run periodically.

    Without this a crashed worker's job stays 'running' forever and the work
    silently never happens — the worst failure mode for a scheduler, because
    absence of action produces no error anywhere.
    """
    rows = await conn.fetch(
        """
        UPDATE jobs
        SET status = CASE WHEN attempts >= max_attempts THEN 'failed' ELSE 'queued' END,
            locked_by = NULL,
            lease_expires_at = NULL,
            error = COALESCE(error, 'lease expired; worker presumed dead')
        WHERE status = 'running' AND lease_expires_at < NOW()
        RETURNING id
        """
    )
    if rows:
        logger.warning("Requeued %d job(s) with expired leases", len(rows))
    return len(rows)


async def get(conn: asyncpg.Connection, job_id: uuid.UUID) -> Job | None:
    row = await conn.fetchrow("SELECT * FROM jobs WHERE id = $1", job_id)
    return _row_to_job(row) if row else None


async def list_jobs(
    conn: asyncpg.Connection, status: str | None = None, limit: int = 50
) -> list[dict[str, Any]]:
    rows = await conn.fetch(
        """
        SELECT id, kind, status, attempts, max_attempts, error,
               created_at, started_at, finished_at
        FROM jobs
        WHERE ($1::text IS NULL OR status = $1)
        ORDER BY created_at DESC
        LIMIT $2
        """,
        status,
        limit,
    )
    return [dict(r) for r in rows]


async def counts_by_status(conn: asyncpg.Connection) -> dict[str, int]:
    rows = await conn.fetch("SELECT status, COUNT(*) AS n FROM jobs GROUP BY status")
    return {r["status"]: r["n"] for r in rows}
