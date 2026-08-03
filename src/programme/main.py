"""
main.py
-------
The programme process.

    python -m src.programme.main

A third long-lived process, alongside the API and the worker. It is the only
one permitted to hold a model client, and the only one forbidden from importing
anything that can submit an order.

What it does on each pass is in :mod:`src.programme.tick`. What this module
does is decide *whether* to do it, and that decision fails closed.

Fail closed, and why it still matters here
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
``programme_enabled`` is read exactly like ``trading_enabled``: a missing row,
an unreadable value or a database error all mean disabled. It would be easy to
argue the stakes are lower — this process writes rows, it does not place
orders. That argument is wrong twice over. A runaway programme queues backtests
until the worker can do nothing else, which stalls the live decision path it
shares a queue with; and it spends money at a model API on every tick. A
control that defaults to "go" when it cannot determine the answer is not a
control, whatever it is controlling.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import socket

import asyncpg

from src.config import get_settings, require_database_url
from src.programme import repo
from src.programme.client import DEFAULT_MODEL
from src.programme.flags import PROGRAMME_WORKER_ID, programme_enabled
from src.programme.tick import run_tick

logger = logging.getLogger(__name__)

#: How long between scheduled passes.
#:
#: Hourly because the work a pass can do is bounded by what the worker has
#: finished since the last one, and a backtest takes minutes. Ticking every
#: thirty seconds would mostly re-read rows that had not changed and pay a
#: model call for the privilege.
DEFAULT_TICK_INTERVAL_SECONDS = 3600.0

#: How often liveness is written. Matches the worker's cadence, because the
#: API's staleness threshold is a multiple of it and applies to both.
HEARTBEAT_INTERVAL_SECONDS = 15.0

#: How often a requested tick is noticed. Short, because it is what an operator
#: pressing the button in the UI is waiting on.
REQUEST_POLL_SECONDS = 5.0


def tick_interval() -> float:
    raw = os.environ.get("PROGRAMME_TICK_SECONDS", "").strip()
    if not raw:
        return DEFAULT_TICK_INTERVAL_SECONDS
    try:
        return max(60.0, float(raw))
    except ValueError:
        logger.warning(
            "PROGRAMME_TICK_SECONDS is not a number (%r); using the default", raw
        )
        return DEFAULT_TICK_INTERVAL_SECONDS


class Programme:
    """The loop. Claims a tick, runs it, records what it did."""

    def __init__(self, dsn: str, model: str, api_key: str | None) -> None:
        self._dsn = dsn
        self._model = model
        self._api_key = api_key
        self._pool: asyncpg.Pool | None = None
        self._stopping = asyncio.Event()
        self._last_scheduled = 0.0

    async def start(self) -> None:
        require_database_url(get_settings())
        self._pool = await asyncpg.create_pool(self._dsn, min_size=1, max_size=4)
        logger.info(
            "Programme process up (model=%s, key=%s, interval=%.0fs)",
            self._model,
            "set" if self._api_key else "absent",
            tick_interval(),
        )
        heartbeat = asyncio.create_task(self._heartbeat_loop())
        try:
            await self._loop()
        finally:
            heartbeat.cancel()
            await self._record_shutdown()
            if self._pool is not None:
                await self._pool.close()

    def stop(self) -> None:
        self._stopping.set()

    async def _loop(self) -> None:
        assert self._pool is not None
        interval = tick_interval()
        while not self._stopping.is_set():
            try:
                async with self._pool.acquire() as conn:
                    if not await programme_enabled(conn):
                        # Requested ticks are left in place rather than
                        # consumed, so enabling the programme runs the pass the
                        # operator asked for instead of silently discarding it.
                        await self._wait(REQUEST_POLL_SECONDS)
                        continue

                    pending = await conn.fetchval(
                        "SELECT COUNT(*) FROM programme_runs WHERE status='requested'"
                    )
                    due = (
                        asyncio.get_running_loop().time() - self._last_scheduled
                        >= interval
                    )
                    if not pending and not due:
                        await self._wait(REQUEST_POLL_SECONDS)
                        continue

                    if not pending:
                        self._last_scheduled = asyncio.get_running_loop().time()
                    await self._run_one(conn, "manual" if pending else "scheduled")
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - the loop outlives one error
                logger.exception("Programme loop error: %s", exc)
                await self._wait(REQUEST_POLL_SECONDS)

    async def _run_one(self, conn: asyncpg.Connection, trigger: str) -> None:
        run_id = await repo.claim_tick(conn, trigger)
        if run_id is None:  # pragma: no cover - another runner took it
            return
        try:
            report = await run_tick(conn, self._api_key, self._model)
        except Exception as exc:  # noqa: BLE001 - recorded on the run row
            logger.exception("Tick %s failed", run_id)
            await repo.finish_tick(conn, run_id, [], status="failed", error=str(exc))
            return
        await repo.finish_tick(
            conn, run_id, report.actions, model=report.model_used
        )
        logger.info("Tick %s finished with %d actions", run_id, len(report.actions))

    async def _wait(self, seconds: float) -> None:
        try:
            await asyncio.wait_for(self._stopping.wait(), timeout=seconds)
        except TimeoutError:
            pass

    async def _heartbeat_loop(self) -> None:
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
                        PROGRAMME_WORKER_ID,
                    )
            except Exception as exc:  # noqa: BLE001 - liveness is not the work
                logger.warning("Could not write programme heartbeat: %s", exc)
            await self._wait(HEARTBEAT_INTERVAL_SECONDS)

    async def _record_shutdown(self) -> None:
        if self._pool is None:
            return
        try:
            async with self._pool.acquire() as conn:
                await conn.execute(
                    "UPDATE worker_heartbeats SET status='stopped', last_seen=NOW() "
                    "WHERE worker_id=$1",
                    PROGRAMME_WORKER_ID,
                )
        except Exception as exc:  # noqa: BLE001 - shutdown must not fail on this
            logger.warning("Could not record shutdown: %s", exc)


async def _amain() -> None:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    settings = get_settings()
    require_database_url(settings)

    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip() or None
    if not api_key:
        logger.warning(
            "ANTHROPIC_API_KEY is not set. The programme will reconcile "
            "experiments, evaluate gates and promote candidates; it will not "
            "propose new hypotheses."
        )
    model = os.environ.get("PROGRAMME_MODEL", "").strip() or DEFAULT_MODEL

    programme = Programme(settings.database_url, model, api_key)
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, programme.stop)
    logger.info("Programme runner on host %s", socket.gethostname())
    await programme.start()


def main() -> None:
    asyncio.run(_amain())


if __name__ == "__main__":
    main()
