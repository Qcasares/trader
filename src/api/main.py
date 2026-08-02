"""
main.py
-------
The FastAPI application.

Deliberately does three things and no more: serve read queries, validate and
enqueue work, and operate the kill switch. It never runs a backtest inline and
never places an order. Both are the worker's job, because a request handler
that blocks on CPU-bound pandas work stalls every other request — including the
one a human is trying to use to stop trading.

    uvicorn src.api.main:app --reload
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import asyncpg
from fastapi import FastAPI, Response, status
from fastapi.middleware.cors import CORSMiddleware

from src.api.routers import (
    auth,
    backtests,
    deployments,
    portfolio,
    strategies,
    system,
)
from src.config import get_settings, require_api_secrets

logger = logging.getLogger(__name__)

API_TITLE = "Systematic Trading Control Plane"
API_VERSION = "0.1.0"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Open the connection pool for the app's lifetime."""
    settings = get_settings()
    app.state.pool = await asyncpg.create_pool(
        settings.database_url, min_size=1, max_size=10
    )
    logger.info("Database pool ready")
    try:
        yield
    finally:
        pool = getattr(app.state, "pool", None)
        if pool is not None:
            await pool.close()
            logger.info("Database pool closed")


def create_app() -> FastAPI:
    settings = get_settings()
    # The single chokepoint for "this process will serve HTTP". Validated here
    # rather than in get_settings() so the worker — which serves nothing and
    # verifies no session — does not need an operator password to boot.
    require_api_secrets(settings)
    app = FastAPI(
        title=API_TITLE,
        version=API_VERSION,
        lifespan=lifespan,
        description=(
            "Research lab and control plane for deterministic, backtestable "
            "trading strategies. Every performance figure this API returns "
            "carries its cost assumption and its standard error."
        ),
    )

    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
            allow_headers=["*"],
        )
    else:
        logger.warning(
            "CORS_ORIGINS is empty — the browser app will not be able to call "
            "this API from another origin."
        )

    app.include_router(auth.router)
    app.include_router(strategies.router)
    app.include_router(backtests.router)
    app.include_router(deployments.router)
    app.include_router(portfolio.router)
    app.include_router(system.router)

    @app.get("/api/v1/health", tags=["health"])
    async def health() -> dict[str, str]:
        """Unauthenticated liveness probe. Reveals nothing about state."""
        return {"status": "ok", "version": API_VERSION}

    @app.get("/api/v1/ready", tags=["health"])
    async def ready(response: Response) -> dict[str, object]:
        """
        Readiness: can we actually reach the database?

        Answers with **503** when it cannot. This used to return 200 with
        ``{"ready": false}``, which every orchestrator that has ever existed
        reads as healthy — they route on the status code, not the body. An
        instance with a dead database would have stayed in the load balancer,
        serving 500s, while its readiness probe cheerfully reported success.
        """
        pool = getattr(app.state, "pool", None)
        if pool is None:
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
            return {"ready": False, "database": False}
        try:
            async with pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
            return {"ready": True, "database": True}
        except Exception as exc:  # noqa: BLE001 - probe must not raise
            logger.error("Readiness probe failed: %s", exc)
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
            return {"ready": False, "database": False}

    return app


app = create_app()
