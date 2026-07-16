from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


UserRole = Literal["admin", "analyst", "reviewer", "viewer"]


class UserIdentity(BaseModel):
    user_id: str
    username: str
    display_name: str
    role: UserRole
    is_active: bool = True


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=512)


class SessionStatus(BaseModel):
    authenticated: bool
    user: UserIdentity
    csrf_token: str | None = None
    idle_expires_at: str | None = None
    absolute_expires_at: str | None = None


class SecurityAuditEvent(BaseModel):
    event_id: str
    actor_user_id: str | None = None
    event_type: str
    outcome: str
    resource_type: str | None = None
    resource_id: str | None = None
    detail: dict = {}
    client_ip: str | None = None
    created_at: str


RulePackStatus = Literal["draft", "candidate", "active", "retired"]


class RulePackCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    version: str = Field(min_length=1, max_length=80)
    war_room_rule_version: str = Field(min_length=1, max_length=80)
    consistency_rule_version: str = Field(min_length=1, max_length=80)
    action_adapter_version: str = Field(min_length=1, max_length=80)
    scoring_weights_version: str = Field(min_length=1, max_length=80)
    evidence_policy_version: str = Field(min_length=1, max_length=80)
    supersedes_rule_pack_id: str | None = Field(default=None, max_length=80)


class RulePackManifest(BaseModel):
    rule_pack_id: str
    name: str
    version: str
    war_room_rule_version: str
    consistency_rule_version: str
    action_adapter_version: str
    scoring_weights_version: str
    evidence_policy_version: str
    manifest: dict
    manifest_hash: str
    status: RulePackStatus
    creator_user_id: str | None = None
    created_at: str
    submitted_at: str | None = None
    activated_at: str | None = None
    supersedes_rule_pack_id: str | None = None


class RulePackReview(BaseModel):
    review_id: str
    rule_pack_id: str
    reviewer_user_id: str
    decision: Literal["approve", "reject", "request_revision"]
    comment: str = ""
    created_at: str


class RulePackReviewRequest(BaseModel):
    comment: str = Field(default="", max_length=2000)


class CalibrationCase(BaseModel):
    case_id: str
    version: str
    category: str
    title: str
    cutoff_date: str
    observation_window_days: int
    input_snapshot: dict
    labels: dict
    evidence: list[dict]
    label_confidence: float
    case_hash: str
    is_active: bool = True


class CalibrationRunRequest(BaseModel):
    rule_pack_id: str = Field(min_length=3, max_length=80)
    case_ids: list[str] = Field(default_factory=list, max_length=100)


class CalibrationMetric(BaseModel):
    key: str
    value: float | int
    threshold: float | int | None = None
    passed: bool
    unit: str = "ratio"


class CalibrationRunStatus(BaseModel):
    calibration_run_id: str
    rule_pack_id: str
    lifecycle_run_id: str | None = None
    status: str
    metrics: dict = {}
    gate_status: str
    created_by_user_id: str | None = None
    created_at: str
    completed_at: str | None = None
    lifecycle_status: str | None = None


ReviewDecisionType = Literal["confirmed", "request_revision", "reject_promotion", "approve_promotion"]


class ReviewCase(BaseModel):
    review_id: str
    review_type: str
    resource_type: str
    resource_id: str
    severity: str
    status: str
    reason: str
    payload: dict = {}
    assigned_to_user_id: str | None = None
    created_at: str
    closed_at: str | None = None


class ReviewDecision(BaseModel):
    decision_id: str
    review_id: str
    reviewer_user_id: str
    decision: ReviewDecisionType
    comment: str = ""
    created_at: str


class ReviewDecisionRequest(BaseModel):
    decision: ReviewDecisionType
    comment: str = Field(default="", max_length=3000)


class TrustSummary(BaseModel):
    project_id: str
    rule_pack: RulePackManifest
    calibration: CalibrationRunStatus | None = None
    calibration_status: str
    golden_gate: dict
    security_gate: dict
    agent_admission_matrix: dict
    data_coverage: float
    pending_review_count: int
    reviews: list[ReviewCase] = []
    rule_pack_history: list[RulePackManifest] = []
    report_allowed: bool
    evidence_registry: dict = {}
    mode_eligibility: dict = {}
    generated_at: str
