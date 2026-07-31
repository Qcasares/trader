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

import logging
import uuid
from datetime import date

from fastapi import APIRouter, HTTPException, Query, status

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
