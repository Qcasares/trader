"""
backtests.py
------------
Enqueue and inspect backtest runs.

``POST`` returns 202 immediately with a run id. Backtests are CPU-bound pandas
work taking seconds to minutes; running one inside a request would block the
event loop and, in a single-process deployment, stall every other request
including the kill switch.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import date

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator

from src.api.deps import AuthedSession, DbConn
from src.api.schemas import (
    BacktestOrder,
    BacktestRun,
    CreateBacktestRequest,
    CreateBacktestResponse,
    EquityPoint,
)
from src.db.repos import backtests as repo
from src.db.repos import jobs as job_repo
from src.strategies import build_strategy, get_strategy_class, list_strategies

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/backtests", tags=["backtests"])


@router.post(
    "", response_model=CreateBacktestResponse, status_code=status.HTTP_202_ACCEPTED
)
async def create(
    body: CreateBacktestRequest, session: AuthedSession, conn: DbConn
) -> CreateBacktestResponse:
    """Validate the request, persist a queued run, and enqueue the work."""
    try:
        strategy_cls = get_strategy_class(body.strategy)
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"unknown strategy {body.strategy!r}; "
                f"registered: {list_strategies()}"
            ),
        ) from None

    # Validate parameters now, against the strategy's own model, so a bad value
    # is a 422 at request time rather than a failed job discovered later.
    try:
        strategy = build_strategy(body.strategy, body.params)
    except Exception as exc:  # noqa: BLE001 - surfaced verbatim to the caller
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"invalid parameters: {exc}",
        ) from exc

    end = body.end or date.today()
    if end <= body.start:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"end ({end}) must be after start ({body.start})",
        )

    request = repo.BacktestRequest(
        strategy_name=body.strategy,
        strategy_version=strategy_cls.version,
        params=strategy.params_dict(),
        universe=strategy.universe(),
        start_session=body.start,
        end_session=end,
        initial_cash=body.initial_cash,
        data_source=body.data_source,
        cost_model={
            "slippage_bps": body.slippage_bps,
            "stress_multiplier": body.cost_stress,
            "min_trade_usd": body.min_trade_usd,
            "max_weight_per_asset": body.max_weight_per_asset,
        },
    )
    run_id = await repo.create_run(conn, request)
    job_id = await job_repo.enqueue(conn, "backtest", {"run_id": str(run_id)})
    logger.info("Queued backtest %s for %s", run_id, body.strategy)
    return CreateBacktestResponse(
        run_id=str(run_id), job_id=str(job_id), status="queued"
    )


@router.get("", response_model=list[BacktestRun])
async def list_all(
    session: AuthedSession,
    conn: DbConn,
    strategy: str | None = None,
    run_status: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[BacktestRun]:
    rows = await repo.list_runs(conn, strategy, run_status, limit)
    return [BacktestRun(**_shape(r)) for r in rows]


@router.get("/{run_id}", response_model=BacktestRun)
async def get_one(run_id: str, session: AuthedSession, conn: DbConn) -> BacktestRun:
    row = await repo.get_run(conn, _uuid(run_id))
    if row is None:
        raise HTTPException(status_code=404, detail=f"unknown run {run_id}")
    return BacktestRun(**_shape(row))


@router.get("/{run_id}/equity", response_model=list[EquityPoint])
async def equity(
    run_id: str,
    session: AuthedSession,
    conn: DbConn,
    max_points: int = Query(default=2000, ge=10, le=20000),
) -> list[EquityPoint]:
    """Equity curve, downsampled for charting with endpoints preserved."""
    if await repo.get_run(conn, _uuid(run_id)) is None:
        raise HTTPException(status_code=404, detail=f"unknown run {run_id}")
    points = await repo.get_equity_curve(conn, _uuid(run_id), max_points)
    return [EquityPoint(**p) for p in points]


@router.get("/{run_id}/orders", response_model=list[BacktestOrder])
async def orders(
    run_id: str,
    session: AuthedSession,
    conn: DbConn,
    limit: int = Query(default=500, ge=1, le=5000),
) -> list[BacktestOrder]:
    if await repo.get_run(conn, _uuid(run_id)) is None:
        raise HTTPException(status_code=404, detail=f"unknown run {run_id}")
    return [
        BacktestOrder(**o) for o in await repo.get_orders(conn, _uuid(run_id), limit)
    ]


def _uuid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError:
        raise HTTPException(
            status_code=422, detail=f"{value!r} is not a valid run id"
        ) from None


def _shape(row: dict) -> dict:
    """Normalise a DB row into the response model's shape."""
    out = dict(row)
    for key in ("created_at", "finished_at", "started_at"):
        value = out.get(key)
        if value is not None and not isinstance(value, str):
            out[key] = value.isoformat()
    out["initial_cash"] = float(out["initial_cash"])
    out.pop("owner_id", None)
    out.pop("started_at", None)
    return out


# ---------------------------------------------------------------------------
# Walk-forward
# ---------------------------------------------------------------------------


class WalkForwardRequest(BaseModel):
    """
    A walk-forward study over a parameter grid.

    The grid is the point. A study with one candidate per fold measures whether
    a *fixed* configuration survives out of sample; a study with several
    measures whether *choosing* between them survives, which is the question
    that matters when a UI lets you tune parameters and rerun.
    """

    param_grid: dict[str, list] = Field(default_factory=dict)
    train_months: int = Field(default=36, ge=6, le=240)
    test_months: int = Field(default=12, ge=1, le=60)

    @field_validator("param_grid")
    @classmethod
    def _non_empty_values(cls, value: dict[str, list]) -> dict[str, list]:
        for name, options in value.items():
            if not options:
                raise ValueError(f"{name} has no candidate values")
        return value


@router.post("/{run_id}/walkforward", status_code=202)
async def create_walkforward(
    run_id: str,
    body: WalkForwardRequest,
    session: AuthedSession,
    conn: DbConn,
) -> dict:
    """
    Queue a walk-forward study over the same window as a backtest.

    Returns 202: the study is many backtests and belongs in the worker, not in
    a request handler holding a connection open.
    """
    run = await _require_run(conn, run_id)
    if run["data_source"] == "synthetic":
        raise HTTPException(
            422,
            "a walk-forward on synthetic data proves nothing about robustness — "
            "the generator has no regime to fail to generalise across.",
        )

    params = run["params"]
    if isinstance(params, str):
        params = json.loads(params)

    wf_id = uuid.uuid4()
    await conn.execute(
        """
        INSERT INTO walkforward_runs (id, backtest_run_id, strategy_name,
            params, param_grid, start_session, end_session, train_months,
            test_months, data_source, status)
        VALUES ($1,$2,$3,$4::jsonb,$5::jsonb,$6,$7,$8,$9,$10,'queued')
        """,
        wf_id,
        run["id"],
        run["strategy_name"],
        json.dumps(params, sort_keys=True),
        json.dumps(body.param_grid),
        run["start_session"],
        run["end_session"],
        body.train_months,
        body.test_months,
        run["data_source"],
    )
    job_id = await job_repo.enqueue(
        conn, "walkforward", {"walkforward_run_id": str(wf_id)}
    )
    return {
        "walkforward_run_id": str(wf_id),
        "job_id": str(job_id),
        "status": "queued",
    }


@router.get("/{run_id}/walkforward")
async def list_walkforward(
    run_id: str, session: AuthedSession, conn: DbConn
) -> list[dict]:
    """Studies for a backtest, newest first."""
    run = await _require_run(conn, run_id)
    rows = await conn.fetch(
        """
        SELECT id, status, is_robust, degradation, mean_is_sharpe,
               mean_oos_sharpe, n_folds, folds, metrics, error,
               train_months, test_months, param_grid, created_at, finished_at
        FROM walkforward_runs WHERE backtest_run_id = $1
        ORDER BY created_at DESC
        """,
        run["id"],
    )
    return [
        {
            "id": str(r["id"]),
            "status": r["status"],
            # Nullable until the study completes. A missing verdict is not a
            # negative one, and the UI must be able to tell them apart.
            "is_robust": r["is_robust"],
            "degradation": _maybe_float(r["degradation"]),
            "mean_in_sample_sharpe": _maybe_float(r["mean_is_sharpe"]),
            "mean_out_of_sample_sharpe": _maybe_float(r["mean_oos_sharpe"]),
            "n_folds": r["n_folds"],
            "train_months": r["train_months"],
            "test_months": r["test_months"],
            "param_grid": _maybe_json(r["param_grid"]),
            "folds": _maybe_json(r["folds"]),
            "metrics": _maybe_json(r["metrics"]),
            "error": r["error"],
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            "finished_at": (
                r["finished_at"].isoformat() if r["finished_at"] else None
            ),
        }
        for r in rows
    ]


def _maybe_float(value) -> float | None:
    return None if value is None else float(value)


def _maybe_json(value):
    """asyncpg hands JSONB back as str or as a decoded object, depending."""
    return json.loads(value) if isinstance(value, str) else value


async def _require_run(conn, run_id: str) -> dict:
    """Fetch a backtest run or 404. Shared by the walk-forward endpoints."""
    row = await conn.fetchrow(
        "SELECT * FROM backtest_runs WHERE id = $1", _uuid(run_id)
    )
    if row is None:
        raise HTTPException(404, f"unknown backtest run {run_id}")
    return dict(row)
