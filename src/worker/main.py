"""
main.py
-------
The worker process.

    python -m src.worker.main

One long-lived asyncio process that drains the ``jobs`` table. It is the only
thing in the system that runs a backtest or places an order; the API only ever
writes job rows.

Wakeup is ``LISTEN/NOTIFY`` plus a polling fallback. NOTIFY gives near-instant
pickup when the API enqueues something; the poll covers scheduled jobs, missed
notifications, and connection drops. Relying on NOTIFY alone would mean a job
enqueued during a reconnect sits forever.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import socket
from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import Any

import asyncpg

from src.config import get_settings
from src.db.repos import flags
from src.db.repos import jobs as job_repo
from src.worker.backtest_job import run_backtest_job

logger = logging.getLogger(__name__)

#: How often to sweep for jobs whose worker died mid-run.
SWEEP_INTERVAL = timedelta(seconds=30)

#: Refresh a running job's lease at this interval. Must be well under the
#: lease itself or a long backtest gets picked up a second time.
HEARTBEAT_INTERVAL = 60.0

JobHandler = Callable[[asyncpg.Connection, dict[str, Any]], Awaitable[dict]]

HANDLERS: dict[str, JobHandler] = {
    "backtest": run_backtest_job,
}


class Worker:
    """Claims jobs, runs them, records the outcome."""

    def __init__(self, dsn: str, worker_id: str, poll_seconds: float = 2.0) -> None:
        self._dsn = dsn
        self._worker_id = worker_id
        self._poll = poll_seconds
        self._pool: asyncpg.Pool | None = None
        self._listener: asyncpg.Connection | None = None
        self._wake = asyncio.Event()
        self._stopping = asyncio.Event()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        self._pool = await asyncpg.create_pool(self._dsn, min_size=1, max_size=5)
        await self._start_listener()
        logger.info("Worker %s ready", self._worker_id)

    async def stop(self) -> None:
        self._stopping.set()
        self._wake.set()
        if self._listener is not None:
            await self._listener.close()
        if self._pool is not None:
            await self._pool.close()
        logger.info("Worker %s stopped", self._worker_id)

    async def _start_listener(self) -> None:
        """Subscribe to job notifications so enqueue wakes us immediately."""
        try:
            self._listener = await asyncpg.connect(self._dsn)
            await self._listener.add_listener("jobs_new", self._on_notify)
            logger.info("Listening on channel jobs_new")
        except Exception as exc:  # noqa: BLE001 - polling still works without it
            logger.warning(
                "Could not subscribe to jobs_new (%s); falling back to polling", exc
            )
            self._listener = None

    def _on_notify(self, *_: object) -> None:
        self._wake.set()

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    async def run(self) -> None:
        assert self._pool is not None, "call start() first"
        sweeper = asyncio.create_task(self._sweep_loop())
        heartbeat = asyncio.create_task(self._heartbeat_loop())
        try:
            while not self._stopping.is_set():
                worked = await self._drain()
                if worked:
                    continue
                # Idle: sleep until notified or the poll interval elapses.
                self._wake.clear()
                try:
                    await asyncio.wait_for(self._wake.wait(), timeout=self._poll)
                except TimeoutError:
                    pass
        finally:
            sweeper.cancel()
            heartbeat.cancel()
            await asyncio.gather(sweeper, heartbeat, return_exceptions=True)

    async def _drain(self) -> bool:
        """Run every currently-available job. Returns whether any ran."""
        assert self._pool is not None
        did_work = False
        while not self._stopping.is_set():
            async with self._pool.acquire() as conn:
                job = await job_repo.claim(conn, self._worker_id)
                if job is None:
                    return did_work
                did_work = True
                await self._execute(conn, job)
        return did_work

    async def _execute(self, conn: asyncpg.Connection, job: job_repo.Job) -> None:
        handler = HANDLERS.get(job.kind)
        if handler is None:
            logger.error("No handler for job kind %r", job.kind)
            await job_repo.fail(conn, job.id, f"no handler for {job.kind}", retry=False)
            return

        # Trading jobs check the kill switch immediately before doing anything.
        # Research jobs (backtests) are unaffected: halting trading should not
        # stop you investigating why you halted it.
        if job.kind in {"live_decision", "submit_orders"}:
            if not await flags.trading_enabled(conn):
                logger.warning("Kill switch engaged; skipping %s job", job.kind)
                await job_repo.fail(
                    conn, job.id, "kill switch engaged", retry=False
                )
                return

        keepalive = asyncio.create_task(self._extend_lease(job.id))
        try:
            result = await handler(conn, job.payload)
            await job_repo.complete(conn, job.id, result)
            logger.info("Job %s (%s) succeeded", job.id, job.kind)
        except Exception as exc:  # noqa: BLE001 - recorded, then the loop continues
            status = await job_repo.fail(conn, job.id, str(exc))
            logger.error(
                "Job %s (%s) failed -> %s: %s", job.id, job.kind, status, exc
            )
        finally:
            keepalive.cancel()
            await asyncio.gather(keepalive, return_exceptions=True)

    async def _extend_lease(self, job_id: Any) -> None:
        """Keep a long job's lease alive on its own connection."""
        assert self._pool is not None
        while True:
            await asyncio.sleep(HEARTBEAT_INTERVAL)
            try:
                async with self._pool.acquire() as conn:
                    await job_repo.extend_lease(conn, job_id)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Could not extend lease for %s: %s", job_id, exc)

    async def _sweep_loop(self) -> None:
        """Periodically return jobs abandoned by dead workers."""
        assert self._pool is not None
        while not self._stopping.is_set():
            await asyncio.sleep(SWEEP_INTERVAL.total_seconds())
            try:
                async with self._pool.acquire() as conn:
                    if await job_repo.requeue_expired(conn):
                        self._wake.set()
            except Exception as exc:  # noqa: BLE001
                logger.warning("Sweep failed: %s", exc)

    async def _heartbeat_loop(self) -> None:
        """
        Record liveness.

        A dead scheduler produces no error anywhere — absence of action looks
        exactly like nothing needing to be done. This row is what an external
        dead-man's switch watches.
        """
        assert self._pool is not None
        while not self._stopping.is_set():
            try:
                async with self._pool.acquire() as conn:
                    await conn.execute(
                        """
                        INSERT INTO worker_heartbeats (worker_id, last_seen, status)
                        VALUES ($1, NOW(), 'alive')
                        ON CONFLICT (worker_id) DO UPDATE
                        SET last_seen = NOW(), status = 'alive'
                        """,
                        self._worker_id,
                    )
            except Exception as exc:  # noqa: BLE001
                logger.warning("Heartbeat failed: %s", exc)
            await asyncio.sleep(15)


async def async_main() -> int:
    settings = get_settings()
    worker_id = settings.worker_id or f"worker-{socket.gethostname()}-{os.getpid()}"
    worker = Worker(settings.database_url, worker_id, settings.worker_poll_seconds)
    await worker.start()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, lambda: asyncio.create_task(worker.stop()))
        except NotImplementedError:  # pragma: no cover - non-POSIX
            pass

    try:
        await worker.run()
    finally:
        await worker.stop()
    return 0


def main() -> int:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )
    return asyncio.run(async_main())


if __name__ == "__main__":
    raise SystemExit(main())
