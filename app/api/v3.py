from __future__ import annotations

import os

from fastapi import APIRouter, Request, Response

from app.core.trust_models import (
    CalibrationCase,
    CalibrationRunRequest,
    CalibrationRunStatus,
    LoginRequest,
    RulePackCreateRequest,
    RulePackManifest,
    RulePackReviewRequest,
    SessionStatus,
)
from app.services.auth import (
    ABSOLUTE_HOURS,
    CSRF_COOKIE,
    SESSION_COOKIE,
    auth_mode,
    ensure_system_user,
    login,
    logout,
)
from app.services import rule_packs
from app.services import calibration


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


def _actor(request: Request):
    return getattr(request.state, "user", None) or ensure_system_user()


@router.get("/rule-packs", response_model=list[RulePackManifest])
def rule_pack_list() -> list[RulePackManifest]:
    return rule_packs.list_rule_packs()


@router.post("/rule-packs", response_model=RulePackManifest)
def rule_pack_create(payload: RulePackCreateRequest, request: Request) -> RulePackManifest:
    return rule_packs.create_rule_pack(payload, _actor(request))


@router.get("/rule-packs/{rule_pack_id}", response_model=RulePackManifest)
def rule_pack_detail(rule_pack_id: str) -> RulePackManifest:
    return rule_packs.get_rule_pack(rule_pack_id)


@router.post("/rule-packs/{rule_pack_id}/submit", response_model=RulePackManifest)
def rule_pack_submit(rule_pack_id: str, request: Request) -> RulePackManifest:
    return rule_packs.submit_rule_pack(rule_pack_id, _actor(request))


@router.post("/rule-packs/{rule_pack_id}/approve", response_model=RulePackManifest)
def rule_pack_approve(rule_pack_id: str, payload: RulePackReviewRequest, request: Request) -> RulePackManifest:
    return rule_packs.approve_rule_pack(rule_pack_id, _actor(request), payload.comment)


@router.post("/rule-packs/{rule_pack_id}/activate", response_model=RulePackManifest)
def rule_pack_activate(rule_pack_id: str, request: Request) -> RulePackManifest:
    return rule_packs.activate_rule_pack(rule_pack_id, _actor(request))


@router.get("/calibration/cases", response_model=list[CalibrationCase])
def calibration_case_list() -> list[CalibrationCase]:
    return calibration.list_calibration_cases()


@router.post("/calibration/runs", response_model=CalibrationRunStatus)
def calibration_run_create(payload: CalibrationRunRequest, request: Request) -> CalibrationRunStatus:
    return calibration.create_calibration_run(payload.rule_pack_id, payload.case_ids, _actor(request))


@router.get("/calibration/runs/{calibration_run_id}", response_model=CalibrationRunStatus)
def calibration_run_detail(calibration_run_id: str) -> CalibrationRunStatus:
    return calibration.get_calibration_run(calibration_run_id)
