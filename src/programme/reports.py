"""
reports.py
----------
The daily trading report, §8.11.

Assembled entirely from rows. No model writes any part of it, and that is not
an oversight: a daily report is the artefact an operator skims fastest and
trusts most, so it is the worst possible place for generated prose. Every line
here is either a number the engine produced or a plain statement that the
number does not exist.

Sections that cannot be filled say why
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
§8.11 asks for seventeen sections. This system can populate about half of them
today: there is no venue, so there are no fills, no slippage and no rejections;
there is no factor model, so there is no factor attribution. Those sections
appear with an explicit reason rather than being silently dropped, because a
report that lists only what it can measure reads as complete.

The distinction that matters most is between zero and absent. No orders were
submitted today and no order data exists are different days, and a report that
renders both as "0 orders" is lying about one of them.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date
from typing import Any

import asyncpg

logger = logging.getLogger(__name__)

#: Sections §8.11 asks for that this system cannot produce, and the reason.
#:
#: Carried in the report itself rather than left as a gap. An operator reading
#: a report with no execution section should be told the system has never
#: contacted a venue, not left to assume execution was clean.
UNAVAILABLE_SECTIONS: dict[str, str] = {
    "slippage": (
        "no venue has been contacted, so there is no realised fill price to "
        "compare against a decision price"
    ),
    "rejections": "no order has ever been submitted to a broker",
    "factor_attribution": (
        "no factor model is implemented; attributing to factors that do not "
        "exist would be worse than leaving this empty"
    ),
    "model_drift": (
        "no machine-learning model is in the decision path, so there is "
        "nothing to drift"
    ),
}


@dataclass(frozen=True, slots=True)
class DailyReport:
    """One trading day, as far as the rows can describe it."""

    session: date
    portfolio: dict[str, Any]
    risk: dict[str, Any]
    programme: dict[str, Any]
    operations: dict[str, Any]
    data_health: dict[str, Any]
    actions: list[str]
    unavailable: dict[str, str]

    def as_dict(self) -> dict[str, Any]:
        return {
            "session": self.session.isoformat(),
            "portfolio": self.portfolio,
            "risk": self.risk,
            "programme": self.programme,
            "operations": self.operations,
            "data_health": self.data_health,
            "required_actions": self.actions,
            "unavailable_sections": self.unavailable,
        }


async def build_daily_report(
    conn: asyncpg.Connection, session: date, mode: str = "paper"
) -> DailyReport:
    """
    Assemble the report for one session.

    Every figure is nullable and a null is rendered by the caller as "no data",
    never as zero. The most common state of this system is having no marks at
    all, and a report that showed a flat line at zero equity for it would be
    describing a portfolio that had lost everything.
    """
    mark = await conn.fetchrow(
        """
        SELECT session, equity, cash, daily_pnl, cumulative_pnl, drawdown_pct
        FROM daily_marks WHERE mode = $1 AND session <= $2
        ORDER BY session DESC LIMIT 1
        """,
        mode,
        session,
    )
    # `positions_snapshot` keys on `as_of`, not `session`. The two tables use
    # different names for the same idea, which is exactly the sort of thing
    # that makes a report quietly return nothing rather than fail loudly.
    positions = await conn.fetch(
        """
        SELECT symbol, qty, avg_entry_price, market_value FROM positions_snapshot
        WHERE mode = $1
          AND as_of = (
              SELECT MAX(as_of) FROM positions_snapshot
              WHERE mode = $1 AND as_of <= $2
          )
        """,
        mode,
        session,
    )

    portfolio = {
        # Nullable throughout. Zero equity and unknown equity are different
        # states and the UI must be able to tell them apart.
        "as_of": mark["session"].isoformat() if mark else None,
        "equity": _num(mark["equity"]) if mark else None,
        "cash": _num(mark["cash"]) if mark else None,
        "daily_pnl": _num(mark["daily_pnl"]) if mark else None,
        "cumulative_pnl": _num(mark["cumulative_pnl"]) if mark else None,
        "drawdown_pct": _num(mark["drawdown_pct"]) if mark else None,
        "positions": [
            {
                "symbol": p["symbol"],
                "qty": _num(p["qty"]),
                "avg_entry_price": _num(p["avg_entry_price"]),
                "market_value": _num(p["market_value"]),
            }
            for p in positions
        ],
        "note": (
            None
            if mark
            else "no marks recorded for this mode; nothing has operated yet"
        ),
    }

    orders = await conn.fetchrow(
        "SELECT COUNT(*) AS n FROM orders WHERE submitted_at::date = $1", session
    )
    decisions = await conn.fetchrow(
        "SELECT COUNT(*) AS n FROM decisions WHERE session = $1", session
    )
    shadow = await conn.fetchrow(
        """
        SELECT COUNT(*) AS n, COUNT(*) FILTER (WHERE error IS NOT NULL) AS failed
        FROM shadow_decisions WHERE session = $1
        """,
        session,
    )

    # `risk_events` is a JSONB column on `decisions`, not a table: the risk
    # gate's interventions are recorded alongside the decision they modified,
    # so a decision and the clamps applied to it cannot be separated.
    risk_rows = await conn.fetch(
        "SELECT risk_events FROM decisions WHERE session = $1", session
    )
    event_counts: dict[str, int] = {}
    for row in risk_rows:
        for event in _loads(row["risk_events"], []):
            code = str(event.get("code", "unknown"))
            event_counts[code] = event_counts.get(code, 0) + 1

    trading_enabled = await conn.fetchval(
        "SELECT value FROM system_flags WHERE key = 'trading_enabled'"
    )
    risk = {
        "trading_enabled": trading_enabled is True or trading_enabled == "true",
        "risk_events": event_counts,
        "note": (
            "risk utilisation against configured limits is reported per "
            "deployment, not programme-wide, until a programme risk budget is "
            "configured"
        ),
    }

    candidates = await conn.fetch(
        "SELECT stage, COUNT(*) AS n FROM candidates WHERE status = 'active' "
        "GROUP BY stage ORDER BY stage"
    )
    findings = await conn.fetchrow(
        """
        SELECT COUNT(*) AS open_count,
               COUNT(*) FILTER (WHERE severity IN ('high','critical')) AS severe
        FROM findings WHERE status = 'open'
        """
    )
    promotions = await conn.fetch(
        """
        SELECT candidate_id, to_stage, approved_by, evaluated_at
        FROM gate_evaluations
        WHERE promoted AND evaluated_at::date = $1
        """,
        session,
    )

    programme = {
        "by_stage": {int(r["stage"]): int(r["n"]) for r in candidates},
        "open_findings": int(findings["open_count"]) if findings else 0,
        "severe_findings": int(findings["severe"]) if findings else 0,
        "promotions_today": [
            {
                "candidate_id": str(p["candidate_id"]),
                "to_stage": p["to_stage"],
                "approved_by": p["approved_by"] or "gate_engine",
            }
            for p in promotions
        ],
    }

    jobs = await conn.fetch(
        "SELECT status, COUNT(*) AS n FROM jobs "
        "WHERE created_at::date = $1 GROUP BY status",
        session,
    )
    workers = await conn.fetch(
        "SELECT worker_id, status, EXTRACT(EPOCH FROM (NOW() - last_seen)) AS age "
        "FROM worker_heartbeats"
    )
    operations = {
        "decisions": int(decisions["n"]) if decisions else 0,
        "orders_submitted": int(orders["n"]) if orders else 0,
        "shadow_sessions": int(shadow["n"]) if shadow else 0,
        "shadow_failures": int(shadow["failed"]) if shadow else 0,
        "jobs": {r["status"]: int(r["n"]) for r in jobs},
        "workers": [
            {
                "worker_id": w["worker_id"],
                "age_seconds": float(w["age"]),
                # 60s matches the API's own threshold, which is four missed
                # heartbeats at the 15s write interval.
                "stale": float(w["age"]) > 60.0,
            }
            for w in workers
        ],
    }

    bars = await conn.fetchrow(
        """
        SELECT COUNT(*) AS n, COUNT(DISTINCT symbol) AS symbols,
               MAX(session) AS latest
        FROM daily_bars WHERE session <= $1
        """,
        session,
    )
    latest = bars["latest"] if bars else None
    data_health = {
        "symbols": int(bars["symbols"]) if bars else 0,
        "rows": int(bars["n"]) if bars else 0,
        "latest_session": latest.isoformat() if latest else None,
        "sessions_behind": (session - latest).days if latest else None,
        "note": (
            None
            if latest
            else "no market data has been ingested; nothing can decide"
        ),
    }

    actions = _required_actions(portfolio, risk, programme, operations, data_health)
    return DailyReport(
        session=session,
        portfolio=portfolio,
        risk=risk,
        programme=programme,
        operations=operations,
        data_health=data_health,
        actions=actions,
        unavailable=dict(UNAVAILABLE_SECTIONS),
    )


def _required_actions(
    portfolio: dict[str, Any],
    risk: dict[str, Any],
    programme: dict[str, Any],
    operations: dict[str, Any],
    data_health: dict[str, Any],
) -> list[str]:
    """
    What an operator has to do about today.

    Derived from thresholds rather than written, so the list cannot be
    persuasive. An empty list means nothing crossed a threshold, which is not
    the same as everything being well — the report's other sections say that.
    """
    actions: list[str] = []
    if programme["severe_findings"]:
        actions.append(
            f"{programme['severe_findings']} open high or critical finding(s) "
            "are blocking promotions; only an operator can close one"
        )
    stale = [w["worker_id"] for w in operations["workers"] if w["stale"]]
    if stale:
        actions.append(
            f"stale heartbeat from {', '.join(stale)}: a dead process "
            "produces no error anywhere and both halting limits go inert"
        )
    if operations["shadow_failures"]:
        actions.append(
            f"{operations['shadow_failures']} shadow session(s) failed today; "
            "stable operation is what stage 3 exists to demonstrate"
        )
    if data_health["sessions_behind"] and data_health["sessions_behind"] > 3:
        actions.append(
            f"market data is {data_health['sessions_behind']} day(s) behind; "
            "the live decision path reads daily_bars"
        )
    if data_health["latest_session"] is None:
        actions.append("no market data ingested at all")
    if operations["jobs"].get("failed"):
        actions.append(f"{operations['jobs']['failed']} job(s) failed today")
    return actions


def _loads(value: Any, default: Any) -> Any:
    if value is None:
        return default
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return default
    return value


def _num(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
