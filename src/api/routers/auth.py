"""Login and logout."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Response, status

from src.api.deps import AppSettings, AuthedSession
from src.api.schemas import LoginRequest, LoginResponse
from src.api.security import SESSION_COOKIE, issue_session, verify_password

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/login", response_model=LoginResponse)
async def login(
    body: LoginRequest, response: Response, settings: AppSettings
) -> LoginResponse:
    """
    Exchange the operator password for a signed session.

    A failed attempt is logged but the response says only "invalid password" —
    there is one account, so there is nothing to enumerate, and a detailed
    error would only help someone guessing.
    """
    if not verify_password(body.password, settings.admin_password_hash):
        logger.warning("Failed login attempt")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid password"
        )

    token = issue_session(
        settings.session_secret, ttl=settings.session_ttl_seconds
    )
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=settings.session_ttl_seconds,
        httponly=True,
        samesite="lax",
        # Secure requires HTTPS; disabled only when no origins are configured,
        # which is the local-development case.
        secure=bool(settings.cors_origins),
    )
    return LoginResponse(token=token, expires_in=settings.session_ttl_seconds)


@router.post("/logout")
async def logout(response: Response) -> dict[str, str]:
    response.delete_cookie(SESSION_COOKIE)
    return {"status": "logged out"}


@router.get("/me")
async def me(session: AuthedSession) -> dict[str, object]:
    return {"subject": session.subject, "expires_at": session.expires_at}
