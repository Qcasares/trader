"""
deps.py
-------
FastAPI dependencies: the connection pool and the auth guard.

The pool lives on ``app.state`` and is opened/closed by the lifespan handler,
so a request never creates a connection and a test can swap in its own pool.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Annotated

import asyncpg
from fastapi import Cookie, Depends, HTTPException, Request, status

from src.api.security import (
    SESSION_COOKIE,
    AuthError,
    InsecureSecretError,
    Session,
    verify_session,
)
from src.config import Settings, get_settings

logger = logging.getLogger(__name__)


async def get_pool(request: Request) -> asyncpg.Pool:
    pool = getattr(request.app.state, "pool", None)
    if pool is None:  # pragma: no cover - misconfiguration guard
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="database pool is not initialised",
        )
    return pool


async def get_conn(
    pool: Annotated[asyncpg.Pool, Depends(get_pool)],
) -> AsyncIterator[asyncpg.Connection]:
    """Check out a connection for the duration of one request."""
    async with pool.acquire() as conn:
        yield conn


def settings_dep() -> Settings:
    return get_settings()


async def current_session(
    request: Request,
    trader_session: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
) -> Session:
    """
    Require a valid session.

    Accepts the session cookie or an ``Authorization: Bearer <token>`` header —
    the cookie for the browser app, the header for CLI and scripted access,
    both carrying the same signed token.
    """
    token = trader_session
    if not token:
        header = request.headers.get("authorization", "")
        if header.lower().startswith("bearer "):
            token = header[7:].strip()

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        return verify_session(get_settings().session_secret, token)
    except InsecureSecretError as exc:
        # 503, not 401. The token may be perfectly good; this deployment has no
        # key to check it with, and that is a fault on this side of the wire.
        # Answering 401 would tell an operator their session had expired and
        # send them to log in again, which cannot succeed either.
        logger.error("Cannot verify sessions: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    except AuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


AuthedSession = Annotated[Session, Depends(current_session)]
DbConn = Annotated[asyncpg.Connection, Depends(get_conn)]
AppSettings = Annotated[Settings, Depends(settings_dep)]
