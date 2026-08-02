"""
drain.py
--------
Running queued **research** jobs from the API process, for hosts that cannot
run a worker.

Why this exists
~~~~~~~~~~~~~~~
``src/worker`` is a long-lived process that claims jobs and runs them. On a
serverless host there is nowhere to put one: every invocation is created for a
request and destroyed after it. Deploy the API there with no worker anywhere
and a submitted backtest sits in ``jobs`` forever, queued, with the UI honestly
reporting "waiting for a worker" and nothing ever arriving.

Why it is off by default
~~~~~~~~~~~~~~~~~~~~~~~~
"The API never runs a backtest inline" is a real invariant, not fastidiousness.
A backtest is CPU-bound pandas work; running one inside a request handler on a
long-lived server stalls every other request sharing that event loop —
including the one an operator is using to hit the kill switch. That argument
does not apply to a serverless invocation, which has no other requests to
stall, and applies with full force everywhere else. So this is opt-in via
``SERVERLESS_DRAIN_ENABLED`` and the docker-compose stack leaves it off.

The line it does not cross
~~~~~~~~~~~~~~~~~~~~~~~~~~
Research jobs only. ``live_decision`` and ``submit_orders`` are not drainable
and must never become so: "the worker is the only process that places an
order" is what makes the import boundary, the kill-switch check and the
three-gate design meaningful. An HTTP request that could reach a venue would
route around all of it. ``test_drain_boundary.py`` asserts the set.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import asyncpg

from src.db.repos import jobs as job_repo
from src.worker.backtest_job import run_backtest_job
from src.worker.walkforward_job import run_walkforward_job

logger = logging.getLogger(__name__)

#: The only job kinds a request may execute.
#:
#: Both are research: they read prices and write results, and neither can
#: reach a broker. Adding a trading kind here would let an HTTP request place
#: an order, which is precisely what the worker/API split prevents.
DRAINABLE: dict[str, Any] = {
    "backtest": run_backtest_job,
    "walkforward": run_walkforward_job,
}

#: Stop claiming new work past this, so the response returns before a platform
#: timeout kills the invocation mid-job. A 10-year backtest is ~2s; this leaves
#: room for several while staying under a 60s function limit.
DEFAULT_BUDGET_SECONDS = 25.0

#: Belt and braces alongside the time budget.
DEFAULT_MAX_JOBS = 5


async def drain_once(
    conn: asyncpg.Connection,
    worker_id: str = "serverless",
    budget_seconds: float = DEFAULT_BUDGET_SECONDS,
    max_jobs: int = DEFAULT_MAX_JOBS,
) -> dict[str, Any]:
    """
    Claim and run queued research jobs until the budget is spent.

    Uses the same ``claim``/``complete``/``fail`` calls as the worker, so a job
    run here is recorded identically to one run there — same attempt counting,
    same retry semantics, same lease. Two drains racing is safe for the same
    reason two workers are: ``FOR UPDATE SKIP LOCKED`` means the second claims
    a different row rather than the same one.

    Expired leases are swept first. Without a worker, nothing else would ever
    return a job abandoned by a timed-out invocation, and it would stay
    ``running`` forever — the failure mode where absence of action produces no
    error anywhere.
    """
    started = time.monotonic()
    requeued = await job_repo.requeue_expired(conn)
    if requeued:
        logger.info("Drain requeued %d abandoned job(s)", requeued)

    ran: list[dict[str, Any]] = []
    while len(ran) < max_jobs and (time.monotonic() - started) < budget_seconds:
        job = await job_repo.claim(conn, worker_id, kinds=list(DRAINABLE))
        if job is None:
            break

        handler = DRAINABLE.get(job.kind)
        if handler is None:
            # Unreachable while `claim` is passed the same key set, and cheap
            # insurance if that ever drifts: refusing beats running a kind
            # this endpoint was never authorised for.
            logger.error("Drain claimed non-drainable kind %r", job.kind)
            await job_repo.fail(
                conn, job.id, f"{job.kind} is not drainable", retry=False
            )
            ran.append({"id": str(job.id), "kind": job.kind, "status": "refused"})
            continue

        try:
            result = await handler(conn, job.payload)
            await job_repo.complete(conn, job.id, result)
            outcome = "succeeded"
        except Exception as exc:  # noqa: BLE001 - recorded, then keep draining
            outcome = await job_repo.fail(conn, job.id, str(exc))
            logger.error("Drained job %s (%s) failed: %s", job.id, job.kind, exc)
        ran.append({"id": str(job.id), "kind": job.kind, "status": outcome})

    return {
        "ran": len(ran),
        "jobs": ran,
        "requeued": requeued,
        "elapsed_seconds": round(time.monotonic() - started, 3),
    }
