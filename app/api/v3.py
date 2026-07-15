from __future__ import annotations

import os

from fastapi import APIRouter, Request, Response

from app.core.trust_models import LoginRequest, SessionStatus
from app.services.auth import (
    ABSOLUTE_HOURS,
    CSRF_COOKIE,
    SESSION_COOKIE,
    auth_mode,
    ensure_system_user,
    login,
    logout,
)


router = APIRouter()


@router.post("/auth/login", response_model=SessionStatus)
def local_login(payload: LoginRequest, request: Request, response: Response) -> SessionStatus:
    if auth_mode() != "local":
        identity = ensure_system_user()
        return SessionStatus(authenticated=True, user=identity)
    status, token, csrf = login(payload.username, payload.password, request)
    secure = os.getenv("WORLDPULSE_ENV", "development").strip().lower() == "production"
    max_age = ABSOLUTE_HOURS * 60 * 60
    response.set_cookie(SESSION_COOKIE, token, httponly=True, secure=secure, samesite="lax", max_age=max_age, path="/")
    response.set_cookie(CSRF_COOKIE, csrf, httponly=False, secure=secure, samesite="lax", max_age=max_age, path="/")
    return status


@router.post("/auth/logout")
def local_logout(request: Request, response: Response) -> dict[str, bool]:
    logout(request)
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")
    return {"authenticated": False}


@router.get("/auth/me", response_model=SessionStatus)
def local_me(request: Request) -> SessionStatus:
    identity = getattr(request.state, "user", None) or ensure_system_user()
    return SessionStatus(authenticated=True, user=identity)
