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
