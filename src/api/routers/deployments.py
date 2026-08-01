"""
deployments.py
--------------
Running a strategy against a broker account.

The deployment gate is enforced here, in the API, not merely suggested in a
runbook: a deployment cannot be created without a **completed backtest run**
for the same strategy. That keeps the research lab upstream of the control
plane rather than parallel to it, which is the one structural defence against
the failure mode where a beautiful control plane ends up driving a strategy
nobody ever tested.

``POST /{id}/dry-run`` is the most useful endpoint in this module. It computes
today's target weights and the exact orders that would follow — including their
deterministic client order ids — and submits nothing. It is how you check what
the system intends before letting it act, and its output is directly comparable
with what the backtest produced for the same session.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import date

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator

from src.api.deps import AppSettings, AuthedSession, DbConn
from src.db.repos import flags
from src.strategies import build_strategy, get_strategy_class, list_strategies
from src.worker.live_job import NoDeploymentError, dry_run

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/deployments", tags=["deployments"])


class CreateDeploymentRequest(BaseModel):
    strategy: str
    params: dict = Field(default_factory=dict)
    capital_usd: float = Field(gt=0)
    #: Required. A deployment without a completed backtest is a strategy nobody
    #: has evidence for, and the API refuses to create one.
    approved_backtest_run_id: str
    mode: str = "paper"
    risk_limits: dict = Field(default_factory=dict)

    @field_validator("mode")
    @classmethod
    def _paper_or_live(cls, value: str) -> str:
        if value not in {"paper", "live"}:
            raise ValueError("mode must be 'paper' or 'live'")
        return value


class EnableRequest(BaseModel):
    #: Typed confirmation, as with the kill switch. Turning a strategy loose on
    #: an account should be deliberate, not a toggle.
    confirm: str

    @field_validator("confirm")
    @classmethod
    def _must_confirm(cls, value: str) -> str:
        if value != "ENABLE DEPLOYMENT":
            raise ValueError("confirm must be exactly 'ENABLE DEPLOYMENT'")
        return value


class DeploymentResponse(BaseModel):
    id: str
    strategy_name: str
    params: dict
    mode: str
    capital_usd: float
    status: str
    halt_reason: str | None = None
    approved_backtest_run_id: str | None = None
    created_at: str | None = None
    enabled_at: str | None = None


@router.get("", response_model=list[DeploymentResponse])
async def list_deployments(
    session: AuthedSession, conn: DbConn
) -> list[DeploymentResponse]:
    rows = await conn.fetch("SELECT * FROM deployments ORDER BY created_at DESC")
    return [_shape(r) for r in rows]


@router.post("", response_model=DeploymentResponse, status_code=201)
async def create_deployment(
    body: CreateDeploymentRequest,
    session: AuthedSession,
    conn: DbConn,
    settings: AppSettings,
) -> DeploymentResponse:
    """Create a deployment. Always starts disabled."""
    try:
        get_strategy_class(body.strategy)
        build_strategy(body.strategy, body.params)
    except KeyError:
        raise HTTPException(
            404,
            f"unknown strategy {body.strategy!r}; registered: {list_strategies()}",
        ) from None
    except Exception as exc:  # noqa: BLE001 - surfaced verbatim
        raise HTTPException(422, f"invalid parameters: {exc}") from exc

    if body.mode == "live" and not settings.live_trading_enabled:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Live deployments require LIVE_TRADING_ENABLED in the environment. "
            "That gate needs a redeploy to change, deliberately.",
        )

    # The gate: no completed backtest, no deployment.
    try:
        run_uuid = uuid.UUID(body.approved_backtest_run_id)
    except ValueError:
        raise HTTPException(422, "approved_backtest_run_id is not a valid id") from None

    run = await conn.fetchrow(
        "SELECT id, status, strategy_name, data_source, metrics "
        "FROM backtest_runs WHERE id = $1",
        run_uuid,
    )
    if run is None:
        raise HTTPException(
            422, f"unknown backtest run {body.approved_backtest_run_id}"
        )
    if run["status"] != "succeeded":
        raise HTTPException(
            422,
            f"backtest run is '{run['status']}', not 'succeeded'. A deployment "
            "must be backed by a completed backtest.",
        )
    if run["strategy_name"] != body.strategy:
        raise HTTPException(
            422,
            f"backtest run is for {run['strategy_name']!r}, not {body.strategy!r}",
        )
    if run["data_source"] == "synthetic":
        raise HTTPException(
            422,
            "that backtest ran on synthetic data, which says nothing about real "
            "performance. Deploy only against a run on real market data.",
        )

    deployment_id = uuid.uuid4()
    await conn.execute(
        """
        INSERT INTO deployments (id, strategy_name, params, mode, capital_usd,
                                 risk_limits, approved_backtest_run_id, status)
        VALUES ($1,$2,$3::jsonb,$4,$5,$6::jsonb,$7,'disabled')
        """,
        deployment_id,
        body.strategy,
        json.dumps(body.params),
        body.mode,
        body.capital_usd,
        json.dumps(body.risk_limits),
        run_uuid,
    )
    await flags.record_audit(
        conn,
        session.subject,
        "deployment_created",
        "deployment",
        str(deployment_id),
        {"strategy": body.strategy, "mode": body.mode},
    )
    row = await conn.fetchrow("SELECT * FROM deployments WHERE id=$1", deployment_id)
    return _shape(row)


@router.post("/{deployment_id}/enable", response_model=DeploymentResponse)
async def enable(
    deployment_id: str,
    body: EnableRequest,
    session: AuthedSession,
    conn: DbConn,
) -> DeploymentResponse:
    """Enable a deployment. Requires the typed confirmation."""
    row = await _require(conn, deployment_id)
    await conn.execute(
        "UPDATE deployments SET status='enabled', enabled_at=NOW(), "
        "halt_reason=NULL WHERE id=$1",
        row["id"],
    )
    await flags.record_audit(
        conn, session.subject, "deployment_enabled", "deployment", deployment_id
    )
    updated = await conn.fetchrow("SELECT * FROM deployments WHERE id=$1", row["id"])
    return _shape(updated)


@router.post("/{deployment_id}/disable", response_model=DeploymentResponse)
async def disable(
    deployment_id: str, session: AuthedSession, conn: DbConn
) -> DeploymentResponse:
    """Disable a deployment. No confirmation — stopping is always easy."""
    row = await _require(conn, deployment_id)
    await conn.execute(
        "UPDATE deployments SET status='disabled', disabled_at=NOW() WHERE id=$1",
        row["id"],
    )
    await flags.record_audit(
        conn, session.subject, "deployment_disabled", "deployment", deployment_id
    )
    updated = await conn.fetchrow("SELECT * FROM deployments WHERE id=$1", row["id"])
    return _shape(updated)


@router.post("/{deployment_id}/dry-run")
async def deployment_dry_run(
    deployment_id: str,
    session: AuthedSession,
    conn: DbConn,
    for_session: date | None = Query(default=None, alias="session"),
) -> dict:
    """
    Compute today's orders without placing any.

    Answers "what would this do" without doing it. Works whether or not the
    deployment is enabled, and whether or not the kill switch is engaged —
    reading intent must never be gated on permission to act, or you lose the
    ability to inspect a system precisely when you have halted it.
    """
    row = await _require(conn, deployment_id)
    target = for_session or date.today()
    try:
        result = await dry_run(conn, row["id"], target)
    except NoDeploymentError as exc:
        raise HTTPException(404, str(exc)) from exc
    except RuntimeError as exc:
        # Missing broker credentials, typically.
        raise HTTPException(503, str(exc)) from exc
    return result


@router.get("/{deployment_id}/decisions")
async def decisions(
    deployment_id: str,
    session: AuthedSession,
    conn: DbConn,
    limit: int = Query(default=50, ge=1, le=200),
) -> list[dict]:
    """
    Decision history — what was intended, and whether it was acted on.

    Returns the pre-gate weights alongside the approved ones. A live decision
    that differs from its backtest is either a data difference or a risk limit
    binding, and only these two fields together tell you which.
    """
    row = await _require(conn, deployment_id)
    rows = await conn.fetch(
        "SELECT session, target_weights, raw_target_weights, risk_events, "
        "order_intents, rationale, status, created_at FROM decisions "
        "WHERE deployment_id=$1 ORDER BY session DESC LIMIT $2",
        row["id"],
        limit,
    )
    return [
        {
            "session": r["session"].isoformat(),
            "target_weights": _maybe_json(r["target_weights"]),
            "raw_target_weights": _maybe_json(r["raw_target_weights"]),
            "risk_events": _maybe_json(r["risk_events"]),
            "order_intents": _maybe_json(r["order_intents"]),
            "rationale": r["rationale"],
            "status": r["status"],
            "created_at": r["created_at"].isoformat(),
        }
        for r in rows
    ]


async def _require(conn, deployment_id: str):
    try:
        parsed = uuid.UUID(deployment_id)
    except ValueError:
        raise HTTPException(422, f"{deployment_id!r} is not a valid id") from None
    row = await conn.fetchrow("SELECT * FROM deployments WHERE id=$1", parsed)
    if row is None:
        raise HTTPException(404, f"unknown deployment {deployment_id}")
    return row


def _maybe_json(value):
    return json.loads(value) if isinstance(value, str) else value


def _shape(row) -> DeploymentResponse:
    return DeploymentResponse(
        id=str(row["id"]),
        strategy_name=row["strategy_name"],
        params=_maybe_json(row["params"]) or {},
        mode=row["mode"],
        capital_usd=float(row["capital_usd"]),
        status=row["status"],
        halt_reason=row["halt_reason"],
        approved_backtest_run_id=(
            str(row["approved_backtest_run_id"])
            if row["approved_backtest_run_id"]
            else None
        ),
        created_at=row["created_at"].isoformat() if row["created_at"] else None,
        enabled_at=row["enabled_at"].isoformat() if row["enabled_at"] else None,
    )
