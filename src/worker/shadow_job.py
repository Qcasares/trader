"""
shadow_job.py
-------------
One shadow session: decide, record, submit nothing.

This lives in the worker rather than in ``src/programme`` for a structural
reason, not a stylistic one. Shadow mode runs the shipped live decision path,
which means importing ``src.worker.live_job`` — and ``src/programme`` is
forbidden from importing it, because ``src/programme`` is the one package
allowed to hold a model client. The programme enqueues; the worker runs. That
split is asserted by ``tests/unit/test_import_boundaries.py``.

The book is derived, never stored
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Every run seeds a fresh :class:`SimulatedBroker` and replays
``shadow_decisions`` in session order, filling each session's intents at the
*next* session's open. A stored book would be a second source of truth about a
portfolio that exists only on paper, free to drift from the decisions that
produced it. Deriving it makes "the hypothetical positions reconcile" a
property of the arrangement rather than a claim someone has to check.

It also gets the decision lag right by construction, using the same
``execute_pending`` a backtest uses: decided on S's close, filled at S+1's
open. The most recent decision has no next session and stays pending.

What this deliberately does not do
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
``dry_run`` seeds the risk gate's equity history from the *paper* book's marks,
because that is the mode the deployment carries. A shadow candidate has no
marks of its own, so the halting limits are not exercised here. That is a real
limitation and it is the reason stage 4 exists as a separate stage: proving the
limits bind, and proving a venue accepts the orders, are what broker paper
trading is for.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, date, datetime, time
from decimal import Decimal
from typing import Any

import asyncpg

from src.core.types import CostModel
from src.execution.simulated import SimulatedBroker
from src.strategies import build_strategy
from src.worker.live_job import (
    NoDeploymentError,
    _decode_deployment,
    _dict_to_intent,
    dry_run,
)

logger = logging.getLogger(__name__)

#: Opening balance for a shadow book.
#:
#: Fixed rather than taken from the deployment's ``capital_usd``, and
#: deliberately so: the shadow book's job is to answer "does this operate
#: sanely", not "what would it have earned". A figure that looked like a P&L
#: would be read as one.
SHADOW_INITIAL_CASH = Decimal("100000")


async def run_shadow_decision(
    conn: asyncpg.Connection,
    payload: dict[str, Any],
    broker_factory: Any | None = None,
) -> dict[str, Any]:
    """
    Record what a candidate would have decided on one session.

    ``broker_factory`` exists for tests and is otherwise unused: the whole
    point here is that the broker is the replayed shadow book.
    """
    candidate_id = payload["candidate_id"]
    session = _as_date(payload["session"])

    row = await conn.fetchrow(
        "SELECT deployment_id, strategy_name, params FROM candidates WHERE id = $1",
        uuid.UUID(candidate_id),
    )
    if row is None:
        raise NoDeploymentError(f"unknown candidate {candidate_id}")
    if row["deployment_id"] is None:
        raise NoDeploymentError(
            f"candidate {candidate_id} has no deployment to shadow against; "
            "one is created when it enters stage 3"
        )
    deployment_id = row["deployment_id"]

    deployment_row = await conn.fetchrow(
        "SELECT * FROM deployments WHERE id = $1", deployment_id
    )
    if deployment_row is None:  # pragma: no cover - FK makes this unreachable
        raise NoDeploymentError(f"unknown deployment {deployment_id}")
    deployment = _decode_deployment(deployment_row)
    strategy = build_strategy(deployment["strategy_name"], deployment["params"])

    broker, last_rebalance = await _replay(conn, candidate_id, deployment, session)

    # The strategy's own schedule, run against the shadow's history rather than
    # the deployment's. `dry_run` decides unconditionally, so this is what
    # separates a decision the schedule would have acted on from a preview.
    #
    # Only `should_rebalance` is called here. The intents themselves come back
    # from `dry_run`, which goes through `Driver.decide` and therefore through
    # `apply_risk` — nothing in this module produces an order.
    rebalanced = strategy.should_rebalance(session, last_rebalance)

    factory = broker_factory or (lambda: broker)
    try:
        result = await dry_run(conn, deployment_id, session, broker_factory=factory)
    except Exception as exc:  # noqa: BLE001 - recorded on the row, not fatal
        logger.exception("shadow decision failed for %s on %s", candidate_id, session)
        await _record(
            conn,
            candidate_id=candidate_id,
            deployment_id=deployment_id,
            session=session,
            rebalanced=False,
            result={},
            equity=None,
            underfunded=[],
            error=str(exc),
        )
        return {
            "candidate_id": candidate_id,
            "session": str(session),
            "error": str(exc),
        }

    error = result.get("error")
    await _record(
        conn,
        candidate_id=candidate_id,
        deployment_id=deployment_id,
        session=session,
        # A session the engine could not price is not a session the schedule
        # acted on, whatever the calendar says.
        rebalanced=rebalanced and not error,
        result=result,
        equity=result.get("equity"),
        underfunded=[
            {
                "symbol": u.symbol,
                "requested": str(u.requested_qty),
                "filled": str(u.filled_qty),
            }
            for u in broker.underfunded_buys
        ],
        error=error,
    )
    return {
        "candidate_id": candidate_id,
        "session": str(session),
        "rebalanced": rebalanced and not error,
        "order_intents": len(result.get("order_intents") or []),
        "equity": result.get("equity"),
        "error": error,
    }


async def _replay(
    conn: asyncpg.Connection,
    candidate_id: str,
    deployment: dict[str, Any],
    up_to: date,
) -> tuple[SimulatedBroker, date | None]:
    """
    Rebuild the shadow book from its own decision log.

    Returns the broker and the last session on which the schedule fired, which
    is the shadow's own ``last_rebalance`` — read from the log rather than from
    the deployment, whose schedule belongs to a live run that is not happening.
    """
    limits = deployment.get("risk_limits") or {}
    broker = SimulatedBroker(
        initial_cash=SHADOW_INITIAL_CASH,
        cost_model=CostModel(
            slippage_bps=float(limits.get("slippage_bps", 5.0)),
        ),
    )

    rows = await conn.fetch(
        """
        SELECT session, rebalanced, order_intents
        FROM shadow_decisions
        WHERE candidate_id = $1 AND session < $2 AND error IS NULL
        ORDER BY session
        """,
        uuid.UUID(candidate_id),
        up_to,
    )
    applied = [r for r in rows if r["rebalanced"]]
    last_rebalance = applied[-1]["session"] if applied else None
    if not applied:
        return broker, last_rebalance

    symbols = deployment.get("universe") or list(
        build_strategy(deployment["strategy_name"], deployment["params"]).universe()
    )
    prices = await _price_map(conn, symbols, applied[0]["session"], up_to)

    # Each session's intents fill at the *next* session's open. The final
    # decision has no next session inside the window and stays pending, which
    # is the decision-lag rule rather than an omission.
    sessions = sorted(prices)
    for entry in applied:
        intents = _loads(entry["order_intents"], [])
        for raw in intents:
            await broker.submit(_dict_to_intent(raw))
        following = _next_available(sessions, entry["session"])
        if following is None:
            break
        opens = {s: p["open"] for s, p in prices[following].items()}
        broker.execute_pending(opens, _at(following))
        broker.mark({s: p["close"] for s, p in prices[following].items()})

    return broker, last_rebalance


async def _price_map(
    conn: asyncpg.Connection, symbols: list[str], start: date, end: date
) -> dict[date, dict[str, dict[str, float]]]:
    """Opens and closes by session, for the replay to fill and mark against."""
    rows = await conn.fetch(
        """
        SELECT session, symbol, open, close FROM daily_bars
        WHERE symbol = ANY($1) AND session BETWEEN $2 AND $3
        ORDER BY session
        """,
        symbols,
        start,
        end,
    )
    out: dict[date, dict[str, dict[str, float]]] = {}
    for row in rows:
        out.setdefault(row["session"], {})[row["symbol"]] = {
            "open": float(row["open"]),
            "close": float(row["close"]),
        }
    return out


def _next_available(sessions: list[date], after: date) -> date | None:
    for candidate in sessions:
        if candidate > after:
            return candidate
    return None


def _at(session: date) -> datetime:
    """A fill timestamp carrying the date it happened, not the date it ran."""
    return datetime.combine(session, time(14, 30), tzinfo=UTC)


async def _record(
    conn: asyncpg.Connection,
    candidate_id: str,
    deployment_id: uuid.UUID,
    session: date,
    rebalanced: bool,
    result: dict[str, Any],
    equity: Any,
    underfunded: list[dict[str, Any]],
    error: str | None,
) -> None:
    """
    Persist the decision, idempotently.

    ``DO NOTHING`` on conflict rather than an upsert: the replay is ordered by
    session and a second entry for a day already recorded would fill the same
    intents twice. A retried job must be inert, not corrective.
    """
    await conn.execute(
        """
        INSERT INTO shadow_decisions (id, candidate_id, deployment_id, session,
            rebalanced, target_weights, order_intents, risk_events, rationale,
            equity, underfunded, error)
        VALUES ($1,$2,$3,$4,$5,$6::jsonb,$7::jsonb,$8::jsonb,$9,$10,$11::jsonb,$12)
        ON CONFLICT (candidate_id, session) DO NOTHING
        """,
        uuid.uuid4(),
        uuid.UUID(candidate_id),
        deployment_id,
        session,
        rebalanced,
        json.dumps(result.get("target_weights") or {}, default=str),
        json.dumps(result.get("order_intents") or [], default=str),
        json.dumps(result.get("risk_events") or [], default=str),
        result.get("rationale", ""),
        Decimal(str(equity)) if equity is not None else None,
        json.dumps(underfunded, default=str),
        error,
    )


def _as_date(value: Any) -> date:
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _loads(value: Any, default: Any) -> Any:
    if value is None:
        return default
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return default
    return value
