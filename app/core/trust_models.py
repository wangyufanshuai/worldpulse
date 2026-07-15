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
