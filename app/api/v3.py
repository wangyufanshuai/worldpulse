from __future__ import annotations

from fastapi import APIRouter, Query, Request, Response

from app.api.dependencies import current_actor
from app.core.trust_models import (
    CalibrationCase,
    CalibrationRunRequest,
    CalibrationRunStatus,
    LoginRequest,
    RulePackCreateRequest,
    RulePackManifest,
    RulePackReviewRequest,
    SessionStatus,
    ReviewCase,
    ReviewDecision,
    ReviewDecisionRequest,
    TrustSummary,
    UserIdentity,
)
from app.services import rule_packs
from app.services import calibration
from app.services import reviews
from app.services.identity import IdentityApplicationPort, identity_service
from app.services.trust_center import project_trust_summary


router = APIRouter()
identity: IdentityApplicationPort = identity_service


@router.post("/auth/login", response_model=SessionStatus)
def local_login(payload: LoginRequest, request: Request, response: Response) -> SessionStatus:
    if identity.auth_mode() != "local":
        actor = identity.ensure_system_user()
        return SessionStatus(authenticated=True, user=actor)
    status, token, csrf = identity.login(payload.username, payload.password, request)
    cookies = identity.cookie_policy()
    response.set_cookie(
        cookies.session_cookie_name,
        token,
        httponly=True,
        secure=cookies.secure,
        samesite=cookies.same_site,
        max_age=cookies.max_age_seconds,
        path=cookies.path,
    )
    response.set_cookie(
        cookies.csrf_cookie_name,
        csrf,
        httponly=False,
        secure=cookies.secure,
        samesite=cookies.same_site,
        max_age=cookies.max_age_seconds,
        path=cookies.path,
    )
    return status


@router.post("/auth/logout")
def local_logout(request: Request, response: Response) -> dict[str, bool]:
    identity.logout(request)
    cookies = identity.cookie_policy()
    response.delete_cookie(cookies.session_cookie_name, path=cookies.path)
    response.delete_cookie(cookies.csrf_cookie_name, path=cookies.path)
    return {"authenticated": False}


@router.get("/auth/me", response_model=SessionStatus)
def local_me(request: Request) -> SessionStatus:
    actor = getattr(request.state, "user", None) or identity.ensure_system_user()
    return SessionStatus(authenticated=True, user=actor)


def _actor(request: Request) -> UserIdentity:
    return current_actor(request)


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


@router.get("/reviews", response_model=list[ReviewCase])
def review_list(status: str | None = Query(default=None)) -> list[ReviewCase]:
    return reviews.list_reviews(status=status)


@router.get("/reviews/{review_id}", response_model=ReviewCase)
def review_detail(review_id: str) -> ReviewCase:
    return reviews.get_review(review_id)


@router.post("/reviews/{review_id}/decision", response_model=ReviewDecision)
def review_decision(review_id: str, payload: ReviewDecisionRequest, request: Request) -> ReviewDecision:
    return reviews.decide_review(review_id, payload.decision, payload.comment, _actor(request))


@router.get("/projects/{project_id}/trust-summary", response_model=TrustSummary)
def trust_summary(project_id: str) -> TrustSummary:
    return project_trust_summary(project_id)
