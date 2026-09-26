"""
kill_job.py
-----------
The kill switch's second half: cancel what this system has at the venue.

``POST /system/kill`` sets the flag every order path checks, which stops new
orders and does nothing about the ones already sent. An order submitted at the
open and not yet filled stayed live at the venue while /system called the state
safe. The route now queues ``cancel_open_orders`` as well, and this is the
handler. It is queued rather than called from the route for two reasons: the
endpoint that must never fail stays a database write, and the process that
talks to the venue about orders stays this one.

What it cancels is this system's own orders, by id: those whose client order id
carries the prefix one of the operator's deployments gives its orders
(``"{deployment_id[:8]}:"``, ``live_job.run_submit_orders``). Not the account's
whole book. The job can run minutes after the stop — behind a retry, or behind
a worker that was down, which /system answers with "orders stand until one
does", an invitation to act by hand — and an account-wide cancel would then
undo the operator's own orders placed at the venue since, sells to flatten
among them. Orders it did not place are counted and left alone. The prefix,
not the ledger, decides: the ledger row is written after the venue accepts an
order, so a worker that died in between left an order the ledger never heard
of, which this still cancels.

Positions are not closed. Flattening a book is a trading decision, with a
price and a cost, and a stop is not one.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any

import asyncpg

from src.db.repos import flags, marks
from src.worker.maintenance_jobs import _maybe_context, _sync_orders

logger = logging.getLogger(__name__)

#: The kinds that can place an order, and so fail while the kill switch is
#: engaged (``Worker._execute``). Research jobs are unaffected — halting trading
#: should not stop you investigating why you halted it — and so is the cancel
#: the switch queues, which runs only while it is engaged.
KILL_GATED_KINDS = frozenset({"live_decision", "submit_orders"})

#: How many rounds of cancel-and-look one attempt makes at a venue, and how far
#: apart. A cancel is asynchronous at Alpaca — an order sits in
#: ``pending_cancel`` until the venue confirms it, normally within a second or
#: two — and waiting here keeps the confirmation inside the attempt, rather
#: than behind the queue's backoff and whatever job the worker takes meanwhile.
CONFIRM_ROUNDS = 10
CONFIRM_INTERVAL_SECONDS = 2.0


class VenueCancelIncompleteError(RuntimeError):
    """An attempt ended with this system's orders open, or a venue unasked."""


async def run_cancel_open_orders(
    conn: asyncpg.Connection,
    payload: dict[str, Any],
    broker_factory: Callable[[str], Any] | None = None,
) -> dict[str, Any]:
    """
    Cancel this system's open orders at every venue the operator's book trades.

    Runs only while the switch is engaged, asked again before each venue.
    Queued by an engagement and claimed after a release, it would cancel what
    the resumed system had just placed. The switch is read fail-closed, so one
    that cannot be read counts as engaged, and cancelling is the safe side of
    that doubt.

    Each venue is handled on its own: one that cannot be reached, or that
    fails, is recorded and the next is still cancelled. Every attempt is
    audited, a failed one included, so what it cancelled is on record whatever
    follows. Success means every venue reached reports none of this system's
    orders open, and no order-placing job running in another worker that could
    still land one; anything else raises, and the job retries. A venue this
    process may not reach — live, with a gate closed, or no credentials at
    all — is reported as not reached, never reached around: the three gates
    bind a cancel as they bind an order.
    """
    if await flags.trading_enabled(conn):
        return {"skipped": "trading was re-enabled before the cancel ran"}

    deployments = await conn.fetch(
        "SELECT id, mode FROM deployments WHERE owner_id = $1 ORDER BY created_at",
        marks.DEFAULT_OWNER,
    )
    prefixes = tuple(f"{str(row['id'])[:8]}:" for row in deployments)
    by_mode: dict[str, list[Any]] = {}
    for row in deployments:
        by_mode.setdefault(row["mode"], []).append(row["id"])

    venues: list[dict[str, Any]] = []
    for mode in sorted(by_mode):
        # Asked again before each venue: a release while this ran means the
        # resumed system may already be placing orders there.
        if await flags.trading_enabled(conn):
            venues.append(
                {"mode": mode, "reached": False, "reason": "trading re-enabled"}
            )
            continue
        venues.append(
            await _one_venue(conn, mode, by_mode[mode], prefixes, broker_factory)
        )

    result = {"requested_by": payload.get("requested_by"), "venues": venues}
    await flags.record_audit(
        conn,
        actor="worker",
        action="kill_switch_venue_cancel",
        entity_type="system",
        detail=result,
    )

    problems = [_problem(venue) for venue in venues]
    problems = [p for p in problems if p]
    if problems:
        raise VenueCancelIncompleteError("; ".join(problems))
    return result


async def _one_venue(
    conn: asyncpg.Connection,
    mode: str,
    deployment_ids: list[Any],
    prefixes: tuple[str, ...],
    broker_factory: Callable[[str], Any] | None,
) -> dict[str, Any]:
    """One venue's outcome, never an exception: an error is part of it."""
    try:
        broker = _venue(mode, broker_factory)
    except (RuntimeError, ValueError) as exc:
        # TradingHaltedError (a RuntimeError) is a closed live gate;
        # RuntimeError and ValueError otherwise are credentials the factory or
        # the adapter refused.
        return {"mode": mode, "reached": False, "reason": str(exc)}

    cancelled: set[str] = set()
    try:
        async with _maybe_context(broker):
            still_open, foreign, in_flight = await _cancel_ours(
                conn, broker, prefixes, cancelled
            )
            unsynced = await _sync_ledger(conn, deployment_ids, broker)
    except Exception as exc:  # noqa: BLE001 - recorded; the next venue still runs
        logger.error("Cancelling at the %s venue failed: %s", mode, exc)
        return {
            "mode": mode,
            "reached": True,
            "cancelled": len(cancelled),
            "error": f"{type(exc).__name__}: {exc}",
        }
    return {
        "mode": mode,
        "reached": True,
        "cancelled": len(cancelled),
        "still_open": still_open,
        "foreign_open": len(foreign),
        "in_flight_elsewhere": in_flight,
        "ledger_unsynced": unsynced,
    }


async def _cancel_ours(
    conn: asyncpg.Connection,
    broker: Any,
    prefixes: tuple[str, ...],
    cancelled: set[str],
) -> tuple[list[dict[str, str]], list[dict[str, str]], int]:
    """
    Cancel this system's open orders by id, and look again, until the venue
    reports none of them open and no order-placing job is running in another
    worker, or the rounds run out. Returns what is still open of ours, what is
    open that is not ours, and how many such jobs were still running at the
    last look. ``cancelled`` gathers the ids the venue accepted a cancel for,
    as it goes, so a failure part way still reports them.

    Each look asks about the jobs first and the venue second. A job seen
    finished has had every order it sent answered by the venue, so the
    listing that follows includes them; asked the other way round, an order
    landed between the two would be missed and the stop confirmed with it
    open.

    A listing that fails raises: an unanswered question is not an empty book.
    """
    for round_ in range(CONFIRM_ROUNDS + 1):
        in_flight = await _submissions_in_flight(conn)
        ours, foreign = _split(await broker.open_orders(), prefixes)
        if (not ours and not in_flight) or round_ == CONFIRM_ROUNDS:
            return ours, foreign, in_flight
        for order in ours:
            # A pending cancel is asked for already; asking again changes
            # nothing at the venue.
            if order["status"] != "pending_cancel" and await broker.cancel_order(
                order["id"]
            ):
                cancelled.add(order["id"])
        await asyncio.sleep(CONFIRM_INTERVAL_SECONDS)
    raise AssertionError("unreachable: the last round returns")


def _split(
    orders: list[dict[str, str]], prefixes: tuple[str, ...]
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """This system's orders, by their client order id's prefix, and the rest."""

    def ours(order: dict[str, str]) -> bool:
        return bool(prefixes) and order["client_order_id"].startswith(prefixes)

    return [o for o in orders if ours(o)], [o for o in orders if not ours(o)]


async def _submissions_in_flight(conn: asyncpg.Connection) -> int:
    """
    Order-placing jobs running in another worker, whose last read of the
    switch may have come before it was engaged: one of them can land an order
    after this attempt has looked. A job whose lease has lapsed belongs to a
    dead worker and is not counted. This worker runs one job at a time, so any
    that is running is another's.
    """
    return await conn.fetchval(
        "SELECT COUNT(*) FROM jobs WHERE status = 'running' "
        "AND kind = ANY($1::text[]) AND lease_expires_at > NOW()",
        sorted(KILL_GATED_KINDS),
    )


def _problem(venue: dict[str, Any]) -> str:
    """Why this venue's outcome is not done, or ``""``."""
    if venue.get("error"):
        return f"{venue['mode']}: {venue['error']}"
    still_open = venue.get("still_open") or []
    if still_open:
        pending = sum(o["status"] == "pending_cancel" for o in still_open)
        orders = ", ".join(f"{o['symbol']} {o['status']}" for o in still_open)
        return (
            f"{venue['mode']}: {len(still_open)} of this system's order(s) still "
            f"open at the venue ({pending} awaiting its confirmation): {orders}"
        )
    if venue.get("in_flight_elsewhere"):
        return (
            f"{venue['mode']}: an order-placing job is still running in another "
            "worker, and could land an order after this looked"
        )
    return ""


def _venue(mode: str, broker_factory: Callable[[str], Any] | None) -> Any:
    """
    The venue for ``mode``, through the shipped factory unless a test passes
    its own — by mode, so a test can hand paper a fake and still leave live to
    the factory's gates.
    """
    if broker_factory is not None:
        return broker_factory(mode)
    from src.worker.live_job import _alpaca_from_env

    return _alpaca_from_env({"mode": mode})


async def _sync_ledger(
    conn: asyncpg.Connection, deployment_ids: list[Any], broker: Any
) -> list[dict[str, str]]:
    """
    Record the venue's order states now rather than at the next reconcile, so
    the orders page agrees with the venue. Best effort, and said so: the
    cancel is what matters here, and a ledger that lags is caught up by the
    next reconcile, where a job failed for it would read as a cancel that
    failed.
    """
    unsynced = []
    for deployment_id in deployment_ids:
        try:
            await _sync_orders(conn, deployment_id, broker)
        except Exception as exc:  # noqa: BLE001 - reported, then the next one
            logger.warning("Could not sync orders for %s: %s", deployment_id, exc)
            unsynced.append({"deployment_id": str(deployment_id), "error": str(exc)})
    return unsynced
