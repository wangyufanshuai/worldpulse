"""Public application contracts for Identity & Organization."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

from fastapi import Request

from app.core.organization_models import (
    Organization,
    OrganizationCreateRequest,
    OrganizationMember,
    OrganizationMemberAddRequest,
)
from app.core.trust_models import SessionStatus, UserIdentity, UserRole


@dataclass(frozen=True)
class SessionCookiePolicy:
    """Browser cookie contract exposed without leaking the legacy auth module."""

    session_cookie_name: str
    csrf_cookie_name: str
    max_age_seconds: int
    secure: bool
    same_site: Literal["lax", "strict", "none"] = "lax"
    path: str = "/"


class IdentityApplicationPort(Protocol):
    def auth_mode(self) -> str: ...

    def validate_security_config(self) -> None: ...

    def configured_cors_origins(self) -> list[str]: ...

    def cookie_policy(self) -> SessionCookiePolicy: ...

    def create_user(self, username: str, password: str, display_name: str, role: UserRole) -> UserIdentity: ...

    def authenticate_local_user(
        self,
        username: str,
        password: str,
        *,
        required_role: UserRole | None = None,
    ) -> UserIdentity: ...

    def ensure_system_user(self) -> UserIdentity: ...

    def login(self, username: str, password: str, request: Request) -> tuple[SessionStatus, str, str]: ...

    def authenticate_request(self, request: Request, *, touch: bool = True) -> UserIdentity: ...

    def require_csrf(self, request: Request) -> None: ...

    def logout(self, request: Request) -> None: ...

    def permission_for_request(self, method: str, path: str) -> str: ...

    def require_permission(self, identity: UserIdentity, permission: str) -> None: ...

    def enforce_rate_limit(self, event_type: str, key: str, *, limit: int, window_seconds: int) -> None: ...

    def enforce_actor_rate_limit(
        self,
        event_type: str,
        actor_user_id: str,
        *,
        limit: int,
        window_seconds: int,
    ) -> None: ...

    def record_security_event(
        self,
        event_type: str,
        outcome: str,
        *,
        actor_user_id: str | None = None,
        resource_type: str | None = None,
        resource_id: str | None = None,
        detail: dict | None = None,
        client_ip: str | None = None,
    ) -> None: ...


class OrganizationApplicationPort(Protocol):
    @property
    def default_organization_id(self) -> str: ...

    @property
    def write_roles(self) -> frozenset[str]: ...

    def ensure_default_membership(self, user: UserIdentity) -> None: ...

    def list_organizations(self, actor: UserIdentity) -> list[Organization]: ...

    def current_organization(self, actor: UserIdentity, requested_id: str | None = None) -> Organization: ...

    def create_organization(self, payload: OrganizationCreateRequest, actor: UserIdentity) -> Organization: ...

    def list_members(self, organization_id: str, actor: UserIdentity) -> list[OrganizationMember]: ...

    def add_member(
        self,
        organization_id: str,
        payload: OrganizationMemberAddRequest,
        actor: UserIdentity,
    ) -> OrganizationMember: ...

    def require_organization_role(self, organization_id: str, actor: UserIdentity, roles: set[str]) -> str: ...

    def scope_resource(self, organization_id: str, resource_type: str, resource_id: str) -> None: ...

    def require_resource_scope(self, organization_id: str, resource_type: str, resource_id: str) -> None: ...

    def enforce_api_resource_scope(
        self,
        organization_id: str,
        actor: UserIdentity,
        method: str,
        path: str,
    ) -> None: ...

    def scoped_resource_ids(self, organization_id: str, resource_type: str) -> set[str]: ...
