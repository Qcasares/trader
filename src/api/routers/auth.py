"""Login and logout."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response, status

from src.api.deps import AppSettings, AuthedSession
from src.api.schemas import LoginRequest, LoginResponse
from src.api.security import SESSION_COOKIE, issue_session, verify_password
from src.api.throttle import throttle
from src.config import Settings, missing_api_config

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


def _cookie_attrs(settings: Settings) -> dict[str, Any]:
    """
    The cookie attributes, resolved once and used by both set and delete.

    A browser matches a deletion against name, path, domain, ``Secure`` and
    ``SameSite``. Clearing a ``SameSite=None; Secure`` cookie with a bare
    ``delete_cookie()`` therefore leaves it in place, and logout appears to
    work while the session survives. Deriving both calls from one function is
    what stops those drifting apart.

    ``Secure`` is forced on whenever ``SameSite=None``, because browsers reject
    that combination outright — a cookie that is never stored is a harder
    failure than the cross-site one this is here to fix.
    """
    samesite = settings.session_cookie_samesite
    return {
        "httponly": True,
        "samesite": samesite,
        "secure": samesite == "none" or bool(settings.cors_origins),
        "path": "/",
    }


@router.post("/login", response_model=LoginResponse)
async def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    settings: AppSettings,
) -> LoginResponse:
    """
    Exchange the operator password for a signed session.

    A failed attempt is logged but the response says only "invalid password" —
    there is one account, so there is nothing to enumerate, and a detailed
    error would only help someone guessing.

    Repeated failures from one source back off exponentially. bcrypt already
    costs an attacker ~100ms per guess, but that is ten a second serially and
    far more in parallel, and there is exactly one password standing between
    the internet and a system that places orders.
    """
    # Before the throttle and before the password check, because a deployment
    # missing its configuration would otherwise answer 401 "invalid password"
    # — blaming the operator for a password that was never wrong, and spending
    # their throttle budget doing it. There is also nothing to check against:
    # an absent ADMIN_PASSWORD_HASH makes `verify_password` return False for
    # every input, so every attempt is a "failure" that can never succeed.
    gaps = missing_api_config(settings)
    if gaps:
        logger.error("Login attempted against an unconfigured deployment: %s", gaps)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="; ".join(gaps),
        )

    source = _source(request)

    wait = throttle.retry_after(source)
    if wait > 0:
        # 429 rather than 401: the credentials were never checked, and saying
        # "invalid password" here would be a lie that also leaks that the
        # attempt was even considered.
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"too many failed attempts; retry in {wait:.0f}s",
            headers={"Retry-After": str(int(wait) + 1)},
        )

    if not verify_password(body.password, settings.admin_password_hash):
        delay = throttle.record_failure(source)
        logger.warning(
            "Failed login attempt from %s%s",
            source,
            f"; backing off {delay:.0f}s" if delay else "",
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid password"
        )

    throttle.record_success(source)
    token = issue_session(
        settings.session_secret, ttl=settings.session_ttl_seconds
    )
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=settings.session_ttl_seconds,
        **_cookie_attrs(settings),
    )
    return LoginResponse(token=token, expires_in=settings.session_ttl_seconds)


@router.post("/logout")
async def logout(response: Response, settings: AppSettings) -> dict[str, str]:
    response.delete_cookie(SESSION_COOKIE, **_cookie_attrs(settings))
    return {"status": "logged out"}


@router.get("/me")
async def me(session: AuthedSession) -> dict[str, object]:
    return {"subject": session.subject, "expires_at": session.expires_at}


def _source(request: Request) -> str:
    """
    The address a login attempt came from.

    ``X-Forwarded-For`` is honoured because this runs behind a proxy in every
    real deployment, and its *first* entry is taken — the rest are appended by
    intermediaries and the leftmost is the original client. A client can forge
    the header, which is why the throttle is a cost-raiser rather than a
    control: forging it evades the counter exactly as rotating source addresses
    does, and the module docstring says so.
    """
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"
