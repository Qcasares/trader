"""
strategies.py
-------------
Strategy discovery.

The parameter JSON Schema returned here is generated from each strategy's
pydantic model, so the web form is derived from the same declaration that
validates a backtest request. There is no second place to update when a
parameter is added.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, status

from src.api.deps import AuthedSession, DbConn
from src.api.schemas import StrategyDescriptor
from src.db.repos import backtests as backtest_repo
from src.strategies import describe_all, get_strategy_class, list_strategies

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/strategies", tags=["strategies"])


@router.get("", response_model=list[StrategyDescriptor])
async def list_all(
    session: AuthedSession, conn: DbConn
) -> list[StrategyDescriptor]:
    """Every registered strategy, with its parameter schema and run count."""
    out: list[StrategyDescriptor] = []
    for descriptor in describe_all():
        count = await backtest_repo.count_runs_for_strategy(conn, descriptor["name"])
        out.append(StrategyDescriptor(**descriptor, backtest_count=count))
    return out


@router.get("/{name}", response_model=StrategyDescriptor)
async def get_one(
    name: str, session: AuthedSession, conn: DbConn
) -> StrategyDescriptor:
    try:
        strategy_cls = get_strategy_class(name)
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"unknown strategy {name!r}; registered: {list_strategies()}",
        ) from None
    descriptor = strategy_cls().describe()
    count = await backtest_repo.count_runs_for_strategy(conn, name)
    return StrategyDescriptor(**descriptor, backtest_count=count)
