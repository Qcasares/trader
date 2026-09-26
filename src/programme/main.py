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

The jobs it owns
~~~~~~~~~~~~~~~~
Beside the tick, the process drains the queue it shares with the worker, for
the kinds in :data:`JEV_HANDLERS` and no others. The worker claims only its own
kinds for the reason this claims only these: a process that claimed every row
would take the other's work, find no handler, and fail it for good, with the
error written into a job that was never its to run.
``tests/unit/test_job_ownership.py`` holds the two dispatch tables apart and
requires every kind anything enqueues to have exactly one owner.

Jev's work runs here and not in the worker because it needs a model client,
which the worker may never import. It is gated twice, by ``programme_enabled``
and by ``jev_enabled``, both read before every claim: two independent switches
both required, neither derived from the other. Jev is a model API, so switching
the programme off stops Jev's spend as it stops the tick's, and switching Jev
off stops Jev without stopping the tick. Either one off and nothing is claimed,
so a queued job waits, its attempts untouched, for both to be on, rather than
failing while an operator has them off.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import socket
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

import asyncpg

from src.config import get_settings, require_database_url
from src.db.repos import jobs as job_repo
from src.db.repos import secrets as secret_repo
from src.programme import jev_lane, repo
from src.programme.flags import (
    PROGRAMME_WORKER_ID,
    jev_enabled,
    model_settings,
    programme_enabled,
    tick_seconds,
)
from src.programme.tick import run_tick

logger = logging.getLogger(__name__)

#: How often liveness is written. Matches the worker's cadence, because the
#: API's staleness threshold is a multiple of it and applies to both.
HEARTBEAT_INTERVAL_SECONDS = 15.0

#: How often a requested tick is noticed. Short, because it is what an operator
#: pressing the button in the UI is waiting on.
REQUEST_POLL_SECONDS = 5.0

#: How often the queue is looked at for Jev's jobs when there was nothing to
#: run. Nothing in them is urgent: a probe an operator asked for is waiting on
#: this, and fifteen seconds is short beside the work it starts.
JEV_POLL_SECONDS = 15.0

#: How often a running Jev job's lease is pushed out. Well under
#: ``job_repo.DEFAULT_LEASE``, because the worker's sweep returns any job whose
#: lease lapses to the queue, whoever owns it, and a job run twice is a call
#: paid for twice.
JEV_LEASE_REFRESH_SECONDS = 60.0

#: Connections: one each for the tick, the heartbeat, a Jev job and that job's
#: lease, and one spare so a slow acquire is never the thing a pass waits on.
POOL_MAX_SIZE = 5

#: A Jev job's handler: the connection, the job's payload, and the TypeSafe key
#: resolved for this job, which may be absent. What it returns is recorded as
#: the job's result.
JevHandler = Callable[
    [asyncpg.Connection, dict[str, Any], str | None], Awaitable[dict[str, Any]]
]


async def _jev_probe(
    conn: asyncpg.Connection, payload: dict[str, Any], api_key: str | None
) -> dict[str, Any]:
    """The connectivity probe. It takes nothing from its payload."""
    return await jev_lane.run_probe(conn, api_key)


#: The dispatch table, and also the claim filter: this process claims exactly
#: these kinds and leaves every other row in ``jobs`` for whoever owns it. Read
#: at claim time rather than copied into a second list, so the filter and the
#: table cannot disagree. No kind here may also be the worker's.
JEV_HANDLERS: dict[str, JevHandler] = {
    "jev_probe": _jev_probe,
}


class Programme:
    """
    The loop. Claims a tick, runs it, records what it did; and beside it, runs
    the jobs in :data:`JEV_HANDLERS`.
    """

    def __init__(
        self,
        dsn: str,
        api_key: str | None,
        secrets_key: str,
        typesafe_key: str | None = None,
    ) -> None:
        self._dsn = dsn
        self._api_key = api_key
        self._secrets_key = secrets_key
        self._typesafe_key = typesafe_key
        self._pool: asyncpg.Pool | None = None
        self._stopping = asyncio.Event()
        self._last_scheduled = 0.0

    async def start(self) -> None:
        require_database_url(get_settings())
        self._pool = await asyncpg.create_pool(
            self._dsn, min_size=1, max_size=POOL_MAX_SIZE
        )
        logger.info(
            "Programme process up (key=%s, TypeSafe key=%s); the model and the "
            "cadence are read from the control plane on every pass",
            "set" if self._api_key else "absent",
            "set" if self._typesafe_key else "absent",
        )
        heartbeat = asyncio.create_task(self._heartbeat_loop())
        jev = asyncio.create_task(self._jev_loop())
        try:
            await self._loop()
        finally:
            heartbeat.cancel()
            jev.cancel()
            # Waited for before the pool closes, so a Jev job cancelled
            # mid-handler has handed its connection back first. Its row stays
            # `running` until the lease lapses and the worker's sweep requeues
            # it.
            await asyncio.gather(heartbeat, jev, return_exceptions=True)
            await self._record_shutdown()
            if self._pool is not None:
                await self._pool.close()

    def stop(self) -> None:
        self._stopping.set()

    async def _loop(self) -> None:
        assert self._pool is not None
        while not self._stopping.is_set():
            try:
                async with self._pool.acquire() as conn:
                    # Re-read every pass rather than once at startup. The
                    # cadence is a spend control, and a control an operator can
                    # only change by restarting the process is one they will
                    # reach for last.
                    interval = float(await tick_seconds(conn))

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
            # Read here rather than held on the instance, so an operator's
            # change takes effect on the next pass instead of the next deploy.
            # `model_settings` fails closed to None, and `run_tick` treats that
            # as "do everything that does not need a model".
            settings = await model_settings(conn)
            api_key = await self._resolve_api_key(conn)
            report = await run_tick(conn, api_key, settings)
        except Exception as exc:  # noqa: BLE001 - recorded on the run row
            logger.exception("Tick %s failed", run_id)
            await repo.finish_tick(conn, run_id, [], status="failed", error=str(exc))
            return
        await repo.finish_tick(conn, run_id, report.actions, model=report.model_used)
        logger.info("Tick %s finished with %d actions", run_id, len(report.actions))

    async def _resolve_api_key(self, conn: asyncpg.Connection) -> str | None:
        """
        The model credential: the vault first, the environment second.

        Read per pass rather than held on the instance, so setting the key in
        the UI takes effect on the next tick instead of the next restart. That
        is the point of putting it in the control plane at all.

        The environment remains a fallback rather than being removed, because
        every deployment that existed before the vault used it and none of them
        should break on upgrade. The order is vault-then-environment because the
        vault is the one an operator can see and change; a stale `.env` silently
        overriding what the UI displays would make the page a liar.

        Both absent is a supported state. The runner reconciles experiments,
        evaluates gates and promotes candidates without a model, and says so.
        """
        from_vault = await secret_repo.get(
            conn, secret_repo.ANTHROPIC_API_KEY, self._secrets_key
        )
        if from_vault:
            return from_vault
        return self._api_key

    async def _resolve_typesafe_key(self, conn: asyncpg.Connection) -> str | None:
        """
        TypeSafe's key, for Jev: the vault first, the environment second.

        :meth:`_resolve_api_key`'s rule, for its reasons. Read per job, so a key
        set in the UI is used by the next job rather than after a restart; the
        vault first, because it is the one an operator can see, and a stale
        ``.env`` silently overriding it would make the configuration page a
        liar. The key is only ever passed to the lane, which hands it to
        ``jev_client`` as ``api_key=``; nothing here or there lets the SDK find
        one in the environment for itself.

        Both absent is a supported state, and the ordinary one while every Jev
        switch is off. The lane asks nothing without a key, and says so.
        """
        from_vault = await secret_repo.get(
            conn, secret_repo.TYPESAFE_API_KEY, self._secrets_key
        )
        if from_vault:
            return from_vault
        return self._typesafe_key

    # ------------------------------------------------------------------
    # Jev's jobs
    # ------------------------------------------------------------------

    async def _jev_loop(self) -> None:
        """Run the Jev jobs in the queue, and look again when there are none."""
        while not self._stopping.is_set():
            try:
                ran = await self._drain_jev()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - the loop outlives one error
                logger.exception("Jev loop error: %s", exc)
                ran = False
            if not ran:
                await self._wait(JEV_POLL_SECONDS)

    async def _drain_jev(self) -> bool:
        """Run every Jev job currently available. Returns whether any ran."""
        assert self._pool is not None
        ran = False
        while not self._stopping.is_set():
            async with self._pool.acquire() as conn:
                # Asked before every claim rather than once per drain, so
                # switching either off stops the next job and not the next
                # poll. A job left queued is not failed: it keeps its attempts
                # for when the switches are on.
                if not await self._jev_switched_on(conn):
                    return ran
                job = await job_repo.claim(
                    conn, PROGRAMME_WORKER_ID, kinds=list(JEV_HANDLERS)
                )
                if job is None:
                    return ran
                ran = True
                await self._execute_jev(conn, job)
        return ran

    async def _jev_switched_on(self, conn: asyncpg.Connection) -> bool:
        """Both switches, each read fail-closed by its own reader."""
        return await programme_enabled(conn) and await jev_enabled(conn)

    async def _execute_jev(self, conn: asyncpg.Connection, job: job_repo.Job) -> None:
        handler = JEV_HANDLERS.get(job.kind)
        if handler is None:
            # Unreachable while `claim` is passed the same key set, and cheap
            # insurance if that ever drifts: refusing loudly beats guessing at
            # a handler.
            logger.error("No Jev handler for job kind %r", job.kind)
            await job_repo.fail(conn, job.id, f"no handler for {job.kind}", retry=False)
            return

        keepalive = asyncio.create_task(self._keep_lease(job.id))
        api_key: str | None = None
        try:
            api_key = await self._resolve_typesafe_key(conn)
            result = await handler(conn, job.payload, api_key)
            await job_repo.complete(conn, job.id, result)
            logger.info("Job %s (%s) succeeded", job.id, job.kind)
        except Exception as exc:  # noqa: BLE001 - recorded, then the loop continues
            # The job's error is shown on the jobs page. Whatever raised, the
            # key is not part of what it said: SDK releases before 0.7.1 could
            # echo a key into an error's text, and a page is a place it leaks
            # from.
            error = _without_secret(str(exc), api_key)
            status = await job_repo.fail(conn, job.id, error)
            logger.error(
                "Job %s (%s) failed -> %s: %s", job.id, job.kind, status, error
            )
        finally:
            keepalive.cancel()
            await asyncio.gather(keepalive, return_exceptions=True)

    async def _keep_lease(self, job_id: uuid.UUID) -> None:
        """Keep a running job's lease alive, on a connection of its own."""
        assert self._pool is not None
        while True:
            await asyncio.sleep(JEV_LEASE_REFRESH_SECONDS)
            try:
                async with self._pool.acquire() as conn:
                    await job_repo.extend_lease(conn, job_id)
            except Exception as exc:  # noqa: BLE001 - the job itself carries on
                logger.warning("Could not extend lease for %s: %s", job_id, exc)

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
    # The fallback for the vault's typesafe_api_key. Absent is the ordinary
    # state while every Jev switch is off, so it is not worth a warning.
    typesafe_key = os.environ.get("TYPESAFE_API_KEY", "").strip() or None
    if not typesafe_key:
        logger.info(
            "TYPESAFE_API_KEY is not set; Jev reads its key from the vault, "
            "and asks nothing without one."
        )
    programme = Programme(
        settings.database_url, api_key, settings.secrets_key, typesafe_key
    )
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, programme.stop)
    logger.info("Programme runner on host %s", socket.gethostname())
    await programme.start()


def _without_secret(text: str, secret: str | None) -> str:
    """
    ``text`` with every occurrence of ``secret`` replaced, if there is one.

    Stripped first: the SDK strips a key before it uses one, so a key stored
    with a trailing newline would be echoed without it.
    """
    secret = (secret or "").strip()
    if not secret:
        return text
    return text.replace(secret, "[redacted]")


def main() -> None:
    asyncio.run(_amain())


if __name__ == "__main__":
    main()
