"""
live_job.py
-----------
The live path: decide, stage, submit.

Runs the **same** :class:`~src.engine.driver.Driver` as the backtest, with
:class:`~src.execution.alpaca.AlpacaBroker` swapped in for
``SimulatedBroker``. That substitution is the entire difference, and it is what
``tests/unit/test_parity.py`` holds in place.

Split into two jobs for a reason
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
``live_decision`` runs after the close and computes targets from the official
closing prices. ``submit_orders`` runs after the *next* open and sends them.
They are separate jobs because the decision and the execution genuinely happen
on different days, and because a persisted decision means a submission can be
retried — with the same deterministic client order ids — without recomputing
anything or risking a different answer.

Kill switch
~~~~~~~~~~~
Checked immediately before submission, not merely at the top of the job. A
check at job start would leave a window in which someone hits the switch and
orders still go out. It is re-read between orders too, so engaging it partway
through a batch stops the remainder.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import asyncpg

from src.core.calendar import previous_session
from src.core.calendar import sessions as nyse_sessions
from src.core.clock import RealClock
from src.core.orders import RebalanceConstraints
from src.core.panel import PricePanel
from src.core.risk import RiskEvent, RiskLimits, describe
from src.core.types import OrderIntent, PortfolioState, Side, TradingMode
from src.db.repos import flags
from src.engine import Driver, DriverConfig, client_order_id
from src.execution.alpaca import AlpacaBroker
from src.execution.base import BrokerAdapter, OrderRejectedError, TradingHaltedError
from src.strategies import build_strategy

logger = logging.getLogger(__name__)


class NoDeploymentError(RuntimeError):
    """No enabled deployment to act on."""


# ---------------------------------------------------------------------------
# Decision
# ---------------------------------------------------------------------------


async def run_live_decision(
    conn: asyncpg.Connection,
    payload: dict[str, Any],
    broker_factory: Any | None = None,
) -> dict[str, Any]:
    """
    Compute target weights from today's close and persist the intended orders.

    Submits nothing. The resulting ``decisions`` row is the record of what the
    strategy wanted, independent of whether it was ever executed — which is
    what makes the live-vs-backtest diff possible and what a dry run reads.
    """
    session = _as_date(payload["session"])
    deployments = await _enabled_deployments(conn, payload.get("deployment_ids"))
    if not deployments:
        logger.info("No enabled deployments; nothing to decide for %s", session)
        return {"session": session.isoformat(), "decisions": 0}

    made = 0
    for deployment in deployments:
        decision = await _decide_for(conn, deployment, session, broker_factory)
        if decision is not None:
            made += 1
    return {"session": session.isoformat(), "decisions": made}


async def _decide_for(
    conn: asyncpg.Connection,
    deployment: dict[str, Any],
    session: date,
    broker_factory: Any | None,
) -> uuid.UUID | None:
    strategy = build_strategy(deployment["strategy_name"], deployment["params"])
    panel = await _load_panel(conn, strategy.universe(), session)
    if panel is None:
        logger.error(
            "No market data for %s up to %s; cannot decide",
            strategy.universe(),
            session,
        )
        return None

    broker = broker_factory() if broker_factory else _alpaca_from_env(deployment)
    async with _maybe_context(broker):
        account = await broker.get_account()
        positions = await broker.get_positions()

    state = PortfolioState(
        cash=account.cash,
        positions=positions,
        equity=account.equity,
        as_of=session,
    )

    limits = deployment.get("risk_limits") or {}
    driver = Driver(
        strategy,
        broker,
        RealClock(),
        DriverConfig(
            constraints=_constraints_from(limits),
            run_ref=str(deployment["id"])[:8],
            risk_limits=risk_limits_from(limits),
        ),
        # The rebalance schedule has to survive process restarts, so it comes
        # from the deployment row rather than from a fresh Driver's memory.
        last_rebalance=deployment.get("last_rebalance"),
    )

    # The shared path: strategy -> apply_risk -> weights_to_orders, exactly as
    # the backtest runs it. This used to be reimplemented inline here, minus
    # the risk gate, which meant live ran an ungated strategy while the
    # backtest that authorised it ran a gated one.
    decision = driver.decide(panel, session, state)
    if not decision.rebalanced:
        logger.info("%s: not a rebalance session for %s", session, strategy.name)
        return None

    intents = decision.intents
    if decision.risk_events:
        logger.info("%s: risk gate — %s", session, describe(decision.risk_events))

    decision_id = uuid.uuid4()
    await conn.execute(
        """
        INSERT INTO decisions (id, deployment_id, session, target_weights,
                               order_intents, rationale, status,
                               raw_target_weights, risk_events)
        VALUES ($1, $2, $3, $4::jsonb, $5::jsonb, $6, 'planned',
                $7::jsonb, $8::jsonb)
        ON CONFLICT (deployment_id, session) DO NOTHING
        """,
        decision_id,
        deployment["id"],
        session,
        json.dumps(decision.targets.weights),
        json.dumps([_intent_to_dict(i) for i in intents]),
        decision.rationale,
        # Both stored: without the pre-gate weights there is no way to tell,
        # after the fact, whether a limit changed the answer or merely ran.
        json.dumps(decision.raw_targets.weights if decision.raw_targets else {}),
        json.dumps([_risk_event_to_dict(e) for e in decision.risk_events]),
    )
    logger.info(
        "%s: decided %d order(s) for %s — %s",
        session,
        len(intents),
        strategy.name,
        decision.rationale,
    )
    return decision_id


def _constraints_from(limits: dict[str, Any]) -> RebalanceConstraints:
    """Order-sizing constraints from a deployment's stored limits."""
    return RebalanceConstraints(
        min_trade_usd=Decimal(str(limits.get("min_trade_usd", 25.0))),
        max_weight_per_asset=float(limits.get("max_weight_per_asset", 1.0)),
    )


def risk_limits_from(limits: dict[str, Any]) -> RiskLimits:
    """
    Build the shared gate's limits from a deployment's stored configuration.

    Every field is read here. A limit that the API accepts and stores but that
    this function forgets is worse than one that does not exist, because the
    UI will show it as configured and it will never bind.
    """
    max_daily_loss = limits.get("max_daily_loss_usd")
    max_drawdown = limits.get("max_drawdown_pct")
    stop_loss = limits.get("stop_loss_pct")
    return RiskLimits(
        max_weight_per_symbol=float(limits.get("max_weight_per_asset", 1.0)),
        max_gross_exposure=float(limits.get("max_gross_exposure", 1.0)),
        max_daily_loss_usd=(
            Decimal(str(max_daily_loss)) if max_daily_loss is not None else None
        ),
        max_drawdown_pct=(
            float(max_drawdown) if max_drawdown is not None else None
        ),
        cooldown_minutes=int(limits.get("cooldown_minutes", 0)),
        stop_loss_pct=float(stop_loss) if stop_loss is not None else None,
        cash_buffer_pct=float(limits.get("cash_buffer_pct", 0.0)),
    )


def _risk_event_to_dict(event: RiskEvent) -> dict[str, Any]:
    return {
        "code": event.code.value,
        "severity": event.severity.value,
        "message": event.message,
        "symbol": event.symbol,
        "binding": event.binding,
    }


# ---------------------------------------------------------------------------
# Submission
# ---------------------------------------------------------------------------


async def run_submit_orders(
    conn: asyncpg.Connection,
    payload: dict[str, Any],
    broker_factory: Any | None = None,
) -> dict[str, Any]:
    """
    Send the orders staged by the previous session's decision.

    The kill switch is checked before the batch *and* before each individual
    order, so engaging it partway through stops the remainder rather than only
    affecting the next cycle.
    """
    session = _as_date(payload["session"])
    previous = previous_session(session)

    rows = await conn.fetch(
        """
        SELECT d.id, d.deployment_id, d.order_intents, d.session,
               dep.mode, dep.strategy_name
        FROM decisions d
        JOIN deployments dep ON dep.id = d.deployment_id
        WHERE d.session = $1 AND d.status = 'planned' AND dep.status = 'enabled'
        """,
        previous,
    )
    if not rows:
        return {"session": session.isoformat(), "submitted": 0, "skipped": 0}

    if not await flags.trading_enabled(conn):
        logger.warning("Kill switch engaged; submitting nothing for %s", session)
        for row in rows:
            await conn.execute(
                "UPDATE decisions SET status='blocked_by_kill_switch' WHERE id=$1",
                row["id"],
            )
        return {
            "session": session.isoformat(),
            "submitted": 0,
            "skipped": len(rows),
            "reason": "kill switch engaged",
        }

    submitted = 0
    blocked = 0
    for row in rows:
        intents = row["order_intents"]
        if isinstance(intents, str):
            intents = json.loads(intents)

        broker = broker_factory() if broker_factory else _alpaca_from_row(row)
        async with _maybe_context(broker):
            for raw in intents:
                # Re-read between orders: engaging the switch mid-batch must
                # stop order 3 of 10, not merely the next cycle.
                if not await flags.trading_enabled(conn):
                    logger.warning(
                        "Kill switch engaged mid-batch; %d order(s) not sent",
                        len(intents) - submitted,
                    )
                    blocked += 1
                    break

                intent = _dict_to_intent(raw)
                coid = client_order_id(
                    str(row["deployment_id"])[:8], row["session"], intent.symbol
                )
                try:
                    ack = await broker.submit(intent, client_order_id=coid)
                except OrderRejectedError as exc:
                    # A duplicate client order id means this batch already went
                    # out — a retry, not a failure. Idempotency working.
                    logger.warning("Order %s rejected: %s", coid, exc)
                    await _record_order(conn, row, intent, coid, None, str(exc))
                    continue
                except TradingHaltedError:
                    blocked += 1
                    break

                await _record_order(conn, row, intent, coid, ack.broker_order_id, None)
                submitted += 1

        await conn.execute(
            "UPDATE decisions SET status='submitted' WHERE id=$1", row["id"]
        )

    return {
        "session": session.isoformat(),
        "submitted": submitted,
        "skipped": blocked,
    }


# ---------------------------------------------------------------------------
# Dry run
# ---------------------------------------------------------------------------


async def dry_run(
    conn: asyncpg.Connection,
    deployment_id: uuid.UUID,
    session: date,
    broker_factory: Any | None = None,
) -> dict[str, Any]:
    """
    Compute what would be ordered, and submit nothing.

    The most useful endpoint in the control plane: it answers "what would this
    do today" without doing it, and its output is directly comparable against
    what the backtest produced for the same session.
    """
    row = await conn.fetchrow("SELECT * FROM deployments WHERE id = $1", deployment_id)
    if row is None:
        raise NoDeploymentError(f"unknown deployment {deployment_id}")

    deployment = _decode_deployment(row)
    strategy = build_strategy(deployment["strategy_name"], deployment["params"])
    panel = await _load_panel(conn, strategy.universe(), session)
    if panel is None:
        return {
            "session": session.isoformat(),
            "error": "no market data available up to this session",
            "order_intents": [],
        }

    broker = broker_factory() if broker_factory else _alpaca_from_env(deployment)
    async with _maybe_context(broker):
        account = await broker.get_account()
        positions = await broker.get_positions()

    state = PortfolioState(
        cash=account.cash,
        positions=positions,
        equity=account.equity,
        as_of=session,
    )
    limits = deployment.get("risk_limits") or {}
    ref = str(deployment_id)[:8]

    # ``last_rebalance=None`` on purpose: a preview answers "what would you do
    # if you rebalanced now", so it decides unconditionally. Whether today is
    # actually a rebalance session is reported separately as
    # ``would_rebalance``, computed from the persisted schedule.
    #
    # It goes through the same ``decide`` as the live job, gate included. A
    # preview that showed ungated orders would be worse than no preview: it is
    # the screen an operator reads before authorising a deployment.
    driver = Driver(
        strategy,
        broker,
        RealClock(),
        DriverConfig(
            constraints=_constraints_from(limits),
            run_ref=ref,
            risk_limits=risk_limits_from(limits),
        ),
        last_rebalance=None,
    )
    decision = driver.decide(panel, session, state)

    return {
        "session": session.isoformat(),
        "strategy": strategy.name,
        "would_rebalance": strategy.should_rebalance(
            session, deployment.get("last_rebalance")
        ),
        "target_weights": decision.targets.weights if decision.targets else {},
        "raw_target_weights": (
            decision.raw_targets.weights if decision.raw_targets else {}
        ),
        "rationale": decision.rationale,
        "risk_events": [_risk_event_to_dict(e) for e in decision.risk_events],
        "equity": float(state.equity),
        "order_intents": [
            {
                **_intent_to_dict(intent),
                "client_order_id": client_order_id(ref, session, intent.symbol),
            }
            for intent in decision.intents
        ],
        "submitted": False,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _enabled_deployments(
    conn: asyncpg.Connection, ids: list[str] | None
) -> list[dict[str, Any]]:
    if ids:
        rows = await conn.fetch(
            "SELECT * FROM deployments WHERE status='enabled' AND id = ANY($1::uuid[])",
            [uuid.UUID(i) for i in ids],
        )
    else:
        rows = await conn.fetch("SELECT * FROM deployments WHERE status='enabled'")
    return [_decode_deployment(r) for r in rows]


def _decode_deployment(row: asyncpg.Record) -> dict[str, Any]:
    out = dict(row)
    for key in ("params", "risk_limits"):
        value = out.get(key)
        if isinstance(value, str):
            out[key] = json.loads(value)
    return out


async def _load_panel(
    conn: asyncpg.Connection, symbols: list[str], session: date
) -> PricePanel | None:
    """
    Build a panel from stored bars, truncated to ``session``.

    The ``session <= $2`` filter is not an optimisation — it is what makes
    look-ahead impossible on the live path too. Loading everything and slicing
    later would leave a window where future bars are in memory.
    """
    rows = await conn.fetch(
        """
        SELECT symbol, session, open, high, low, close, volume, adj_close
        FROM daily_bars
        WHERE symbol = ANY($1) AND session <= $2
        ORDER BY session, symbol
        """,
        symbols,
        session,
    )
    if not rows:
        return None
    tuples = [
        (
            r["symbol"],
            r["session"],
            float(r["open"]),
            float(r["high"]),
            float(r["low"]),
            float(r["close"]),
            float(r["volume"]),
            float(r["adj_close"]),
        )
        for r in rows
    ]
    return PricePanel.from_bars(tuples, as_of=session)


def _close_prices(
    panel: PricePanel, symbols: list[str], session: date
) -> dict[str, float]:
    """Raw closes for order sizing. Signals use adjusted; money uses raw."""
    out: dict[str, float] = {}
    for symbol in symbols:
        try:
            value = panel.value_on(symbol, session, "close")
        except KeyError:
            continue
        if value is not None and value > 0:
            out[symbol] = value
    return out


async def _record_order(
    conn: asyncpg.Connection,
    row: asyncpg.Record,
    intent: OrderIntent,
    coid: str,
    broker_order_id: str | None,
    error: str | None,
) -> None:
    await conn.execute(
        """
        INSERT INTO orders (id, deployment_id, decision_id, client_order_id,
                            broker_order_id, mode, symbol, side, order_type,
                            qty, notional, status, submitted_at, raw)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,NOW(),$13::jsonb)
        ON CONFLICT (client_order_id) DO NOTHING
        """,
        uuid.uuid4(),
        row["deployment_id"],
        row["id"],
        coid,
        broker_order_id,
        row["mode"],
        intent.symbol,
        intent.side.value,
        intent.order_type.value,
        intent.qty,
        intent.notional,
        "rejected" if error else "submitted",
        json.dumps({"error": error} if error else {}),
    )


def _intent_to_dict(intent: OrderIntent) -> dict[str, Any]:
    return {
        "symbol": intent.symbol,
        "side": intent.side.value,
        "qty": str(intent.qty) if intent.qty is not None else None,
        "notional": str(intent.notional) if intent.notional is not None else None,
        "order_type": intent.order_type.value,
        "reason": intent.reason,
    }


def _dict_to_intent(raw: dict[str, Any]) -> OrderIntent:
    from src.core.types import OrderType

    return OrderIntent(
        symbol=raw["symbol"],
        side=Side(raw["side"]),
        qty=Decimal(raw["qty"]) if raw.get("qty") else None,
        notional=Decimal(raw["notional"]) if raw.get("notional") else None,
        order_type=OrderType(raw.get("order_type", "market")),
        reason=raw.get("reason", ""),
    )


def _alpaca_from_env(deployment: dict[str, Any]) -> BrokerAdapter:
    from src.config import get_settings

    settings = get_settings()
    if not settings.has_broker_credentials:
        raise RuntimeError(
            "Alpaca credentials are not configured (ALPACA_KEY_ID / "
            "ALPACA_SECRET_KEY); cannot reach a venue."
        )
    mode = TradingMode(deployment.get("mode", "paper"))
    return AlpacaBroker(
        settings.alpaca_key_id,
        settings.alpaca_secret_key,
        mode=mode,
        live_enabled=settings.live_trading_enabled,
        allow_live=mode is TradingMode.LIVE and settings.live_trading_enabled,
    )


def _alpaca_from_row(row: asyncpg.Record) -> BrokerAdapter:
    return _alpaca_from_env({"mode": row["mode"]})


class _NullContext:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *exc: object) -> None:
        return None


def _maybe_context(broker: Any) -> Any:
    """Use the broker's async context manager when it has one."""
    return broker if hasattr(broker, "__aenter__") else _NullContext()


def _as_date(value: Any) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    return date.fromisoformat(str(value))


def sessions_between(start: date, end: date) -> list[date]:
    """Re-exported for the scheduler's convenience."""
    return nyse_sessions(start, end)
