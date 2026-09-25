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

The same gate is asked again at ``enable``, which is the moment that matters:
creation only writes a disabled row, and ``create`` is not the only thing that
writes rows.

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
from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.api.deps import AppSettings, AuthedSession, DbConn
from src.config import Settings
from src.db.repos import flags, marks
from src.strategies import build_strategy, get_strategy_class, list_strategies
from src.worker.live_job import NoDeploymentError, dry_run

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/deployments", tags=["deployments"])

#: The one owner whose deployments this API will enable: the operator's own
#: account, which ``create_deployment`` writes by the column's default and whose
#: marks the risk gate reads. The programme inserts its shadow deployments under
#: ``programme``, disabled, and they must stay that way — shadow mode reaches no
#: venue. The worker's ``_enabled_deployments`` also filters on owner, so this
#: is the first of two refusals rather than the only one.
ENABLEABLE_OWNER = marks.DEFAULT_OWNER


class RiskLimitsRequest(BaseModel):
    """
    A deployment's risk configuration, validated rather than taken on trust.

    This was a bare ``dict``, which meant an unrecognised key was accepted,
    stored, and returned by the API — while the worker, which reads specific
    keys, never saw it. Writing ``max_drawdown`` for ``max_drawdown_pct``
    produced a deployment that displayed a configured drawdown limit and had
    none. ``risk_limits_from`` already guards the read side ("a limit the API
    accepts and stores but that this function forgets is worse than one that
    does not exist"); this is the write side of the same argument.

    ``extra="forbid"`` is the point of the model. Range checks are useful, but
    the typo is the failure that actually happens, and it is silent.

    Bounds are not decoration either. ``max_gross_exposure`` above 1.0 is
    unreachable — ``TargetWeights`` refuses to construct a levered allocation —
    so accepting it would let a cooldown hold inflate the weights past a clamp
    that no longer catches them, and raise deep inside the worker instead.
    """

    model_config = ConfigDict(extra="forbid")

    #: Also feeds order sizing via ``_constraints_from``.
    max_weight_per_asset: float = Field(default=1.0, gt=0.0, le=1.0)
    min_trade_usd: float = Field(default=25.0, ge=0.0)

    max_gross_exposure: float = Field(default=1.0, gt=0.0, le=1.0)
    #: ``None`` disables. Zero would mean "halt on any loss at all", which is
    #: far more likely to be a mistake than an intention.
    max_daily_loss_usd: float | None = Field(default=None, gt=0.0)
    max_drawdown_pct: float | None = Field(default=None, gt=0.0, le=1.0)
    cooldown_minutes: int = Field(default=0, ge=0)
    #: Off by default. A stop on a monthly rebalancer is a different strategy,
    #: and its backtest has to model it.
    stop_loss_pct: float | None = Field(default=None, gt=0.0, le=1.0)
    #: Held back so a gap between decision and fill does not produce an
    #: insufficient-buying-power rejection. Must leave something to invest.
    cash_buffer_pct: float = Field(default=0.0, ge=0.0, lt=1.0)


class CreateDeploymentRequest(BaseModel):
    strategy: str
    params: dict = Field(default_factory=dict)
    capital_usd: float = Field(gt=0)
    #: Required. A deployment without a completed backtest is a strategy nobody
    #: has evidence for, and the API refuses to create one.
    approved_backtest_run_id: str
    mode: str = "paper"
    risk_limits: RiskLimitsRequest = Field(default_factory=RiskLimitsRequest)

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
    run_uuid = await _deployment_gate(
        conn,
        strategy=body.strategy,
        params=body.params,
        mode=body.mode,
        approved_backtest_run_id=body.approved_backtest_run_id,
        settings=settings,
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
        json.dumps(body.risk_limits.model_dump()),
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
    settings: AppSettings,
) -> DeploymentResponse:
    """
    Enable a deployment. Requires the typed confirmation, and the gate.

    This used to flip the status and nothing else, on the reasoning that the
    gate had already been asked at creation. It had been asked of *that*
    request. ``create_deployment`` is one way into the table, not the only one —
    the programme inserts its shadow deployments directly, and any row can be
    written by hand — and the evidence can change after creation: a newer
    walk-forward of the same parameters that comes back NOT ROBUST supersedes
    the one that admitted the deployment. Enabling is the moment a strategy is
    turned loose on an account, so it is where the question has to be asked.

    Ownership is checked first, so a shadow deployment is refused for what it
    is rather than for whichever piece of evidence it happens to lack.
    """
    row = await _require(conn, deployment_id)
    if row["owner_id"] != ENABLEABLE_OWNER:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"deployment {deployment_id} belongs to {row['owner_id']!r}, not the "
            f"operator's account. Only the operator's own deployments can be "
            f"enabled here: the programme's shadow deployments stay disabled "
            f"because shadow mode reaches no venue, and no other owner has a "
            f"path to one yet.",
        )
    await _deployment_gate(
        conn,
        strategy=row["strategy_name"],
        # Passed as stored, not coerced with `or {}`: a row whose params are
        # JSON null would otherwise borrow the default parameters' walk-forward.
        params=_maybe_json(row["params"]),
        mode=row["mode"],
        approved_backtest_run_id=row["approved_backtest_run_id"],
        settings=settings,
    )
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


async def _deployment_gate(
    conn,
    *,
    strategy: str,
    params: dict,
    mode: str,
    approved_backtest_run_id: str | uuid.UUID | None,
    settings: Settings,
) -> uuid.UUID:
    """
    Everything a deployment must have before it may exist or be enabled.

    Raises ``HTTPException`` naming the first unmet condition; returns the
    approved backtest's id when every condition holds. One function for both
    ``create_deployment`` and ``enable``: a gate asked in one place and assumed
    in the other is how ``enable`` came to check nothing at all, and two copies
    would drift, the unwatched one first.
    """
    try:
        get_strategy_class(strategy)
        build_strategy(strategy, params)
    except KeyError:
        raise HTTPException(
            404,
            f"unknown strategy {strategy!r}; registered: {list_strategies()}",
        ) from None
    except Exception as exc:  # noqa: BLE001 - surfaced verbatim
        raise HTTPException(422, f"invalid parameters: {exc}") from exc

    # Anything but paper needs the environment gate. The request model and the
    # schema both restrict mode to paper or live, so this reads the same as
    # `mode == "live"` today; written this way, a mode nobody anticipated
    # fails closed instead of being waved through as not-live.
    if mode != "paper" and not settings.live_trading_enabled:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Live deployments require LIVE_TRADING_ENABLED in the environment. "
            "That gate needs a redeploy to change, deliberately.",
        )

    # The gate: no completed backtest, no deployment.
    if approved_backtest_run_id is None:
        # Only reachable from a row: the request model requires the field.
        raise HTTPException(
            422,
            "no approved backtest run. A deployment must be backed by a "
            "completed backtest.",
        )
    try:
        run_uuid = uuid.UUID(str(approved_backtest_run_id))
    except ValueError:
        raise HTTPException(422, "approved_backtest_run_id is not a valid id") from None

    run = await conn.fetchrow(
        "SELECT id, status, strategy_name, data_source, metrics "
        "FROM backtest_runs WHERE id = $1",
        run_uuid,
    )
    if run is None:
        raise HTTPException(422, f"unknown backtest run {approved_backtest_run_id}")
    if run["status"] != "succeeded":
        raise HTTPException(
            422,
            f"backtest run is '{run['status']}', not 'succeeded'. A deployment "
            "must be backed by a completed backtest.",
        )
    if run["strategy_name"] != strategy:
        raise HTTPException(
            422,
            f"backtest run is for {run['strategy_name']!r}, not {strategy!r}",
        )
    if run["data_source"] == "synthetic":
        raise HTTPException(
            422,
            "that backtest ran on synthetic data, which says nothing about real "
            "performance. Deploy only against a run on real market data.",
        )

    # The plan's own mitigation for its risk 7 — that a research UI is an
    # overfitting machine, and edit-params/rerun/look-at-Sharpe is exactly how
    # people fool themselves. A single backtest cannot distinguish a real edge
    # from parameters fitted to noise; only walking the parameters forward can.
    #
    # This refuses rather than warns. A warning on the screen where somebody is
    # already committed to deploying is not a control, and this gate is the
    # last point at which the question gets asked.
    verdict = await _walkforward_verdict(conn, strategy, params)
    if verdict is None:
        raise HTTPException(
            422,
            "no completed walk-forward study for this strategy and these "
            "parameters. A single backtest cannot tell an edge from parameters "
            "fitted to noise. Run POST /api/v1/backtests/{id}/walkforward "
            "first.",
        )
    if not verdict["is_robust"]:
        raise HTTPException(
            422,
            f"the walk-forward study for these parameters is NOT ROBUST. "
            f"{_why_not_robust(verdict)} Failing this is strong evidence "
            f"against the configuration. Degradation, for context, was "
            f"{float(verdict['degradation']):+.3f}.",
        )
    return run_uuid


async def _walkforward_verdict(conn, strategy: str, params: dict) -> dict | None:
    """
    The most recent completed walk-forward for this exact configuration.

    Matched on the *parameters*, not merely the strategy name. A study of
    `sma_period=210` says nothing about `sma_period=50`, and letting one vouch
    for the other would turn the gate into a formality — which is precisely
    the failure mode it exists to prevent.

    Returns None when no completed study matches.
    """
    row = await conn.fetchrow(
        """
        SELECT is_robust, degradation, id, metrics, folds
        FROM walkforward_runs
        WHERE strategy_name = $1
          AND status = 'succeeded'
          AND params = $2::jsonb
        ORDER BY created_at DESC LIMIT 1
        """,
        strategy,
        json.dumps(params, sort_keys=True),
    )
    return dict(row) if row is not None else None


def _why_not_robust(verdict: dict) -> str:
    """
    Name the condition that actually failed.

    The refusal used to quote `degradation` and say out-of-sample performance
    "did not survive fixing the parameters in advance". Degradation is not the
    test — `WalkForwardResult.is_robust` requires a *significant*, positive
    stitched out-of-sample Sharpe and a majority of folds agreeing on one
    parameter set, and reports degradation separately. So a study could be
    refused at +0.046 degradation, which is performance very nearly surviving,
    with a message asserting that it had not. An operator reading it would go
    looking for overfitting in the wrong place.

    Every failing condition, not the first: a configuration that is both
    insignificant and unstable should say so once rather than over two
    attempts.
    """
    metrics = verdict.get("metrics") or {}
    if isinstance(metrics, str):
        metrics = json.loads(metrics)
    folds = verdict.get("folds") or []
    if isinstance(folds, str):
        folds = json.loads(folds)

    reasons: list[str] = []

    sharpe = float(metrics.get("sharpe", 0.0))
    stderr = float(metrics.get("sharpe_stderr", 0.0))
    if not metrics.get("sharpe_is_significant", False):
        reasons.append(
            f"the stitched out-of-sample Sharpe is {sharpe:+.3f} ± {stderr:.3f}, "
            f"which does not clear two standard errors of zero — the result is "
            f"indistinguishable from no edge"
        )
    elif sharpe <= 0:
        reasons.append(f"the stitched out-of-sample Sharpe is {sharpe:+.3f}")

    if folds:
        chosen = [json.dumps(f.get("chosen_params", {}), sort_keys=True) for f in folds]
        stability = max(chosen.count(k) for k in set(chosen)) / len(chosen)
        if stability < 0.5:
            reasons.append(
                f"only {stability:.0%} of folds chose the same parameter set, so "
                f"there is no stable optimum to deploy"
            )

    if not reasons:
        # The stored verdict disagrees with what the stored figures imply.
        # Reporting the disagreement beats inventing a reason for it.
        return (
            "the stored verdict is not robust, though the recorded figures do "
            "not show which condition failed; re-run the study."
        )
    # Upper-case the first character only. `str.capitalize` lower-cases the
    # rest, which turns "Sharpe" into "sharpe".
    joined = "; and ".join(reasons)
    return joined[0].upper() + joined[1:] + "."
