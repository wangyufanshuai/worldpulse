"""Compatibility adapters for the Identity & Organization context.

The adapters intentionally delegate every security-sensitive decision to the
V1 services.  They give API callers a stable application boundary while
session persistence, CSRF, RBAC and organization storage migrate later.
"""

from __future__ import annotations

import os

from fastapi import Request

from app.core.organization_models import (
    Organization,
    OrganizationCreateRequest,
    OrganizationMember,
    OrganizationMemberAddRequest,
)
from app.core.trust_models import SessionStatus, UserIdentity, UserRole
from app.services import auth as legacy_auth
from app.services import organizations as legacy_organizations

from .ports import IdentityApplicationPort, OrganizationApplicationPort, SessionCookiePolicy


class IdentityApplicationService:
    def auth_mode(self) -> str:
        return legacy_auth.auth_mode()

    def validate_security_config(self) -> None:
        legacy_auth.validate_security_config()

    def configured_cors_origins(self) -> list[str]:
        return legacy_auth.configured_cors_origins()

    def cookie_policy(self) -> SessionCookiePolicy:
        secure = os.getenv("WORLDPULSE_ENV", "development").strip().lower() == "production"
        return SessionCookiePolicy(
            session_cookie_name=legacy_auth.SESSION_COOKIE,
            csrf_cookie_name=legacy_auth.CSRF_COOKIE,
            max_age_seconds=legacy_auth.ABSOLUTE_HOURS * 60 * 60,
            secure=secure,
        )

    def create_user(self, username: str, password: str, display_name: str, role: UserRole) -> UserIdentity:
        return legacy_auth.create_user(username, password, display_name, role)

    def authenticate_local_user(
        self,
        username: str,
        password: str,
        *,
        required_role: UserRole | None = None,
    ) -> UserIdentity:
        return legacy_auth.authenticate_local_user(username, password, required_role=required_role)

    def ensure_system_user(self) -> UserIdentity:
        return legacy_auth.ensure_system_user()

    def login(self, username: str, password: str, request: Request) -> tuple[SessionStatus, str, str]:
        return legacy_auth.login(username, password, request)

    def authenticate_request(self, request: Request, *, touch: bool = True) -> UserIdentity:
        return legacy_auth.authenticate_request(request, touch=touch)

    def require_csrf(self, request: Request) -> None:
        legacy_auth.require_csrf(request)

    def logout(self, request: Request) -> None:
        legacy_auth.logout(request)

    def permission_for_request(self, method: str, path: str) -> str:
        return legacy_auth.permission_for_request(method, path)

    def require_permission(self, identity: UserIdentity, permission: str) -> None:
        legacy_auth.require_permission(identity, permission)

    def enforce_rate_limit(self, event_type: str, key: str, *, limit: int, window_seconds: int) -> None:
        legacy_auth.enforce_rate_limit(event_type, key, limit=limit, window_seconds=window_seconds)

    def enforce_actor_rate_limit(
        self,
        event_type: str,
        actor_user_id: str,
        *,
        limit: int,
        window_seconds: int,
    ) -> None:
        legacy_auth.enforce_actor_rate_limit(
            event_type,
            actor_user_id,
            limit=limit,
            window_seconds=window_seconds,
        )

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
    ) -> None:
        legacy_auth.record_security_event(
            event_type,
            outcome,
            actor_user_id=actor_user_id,
            resource_type=resource_type,
            resource_id=resource_id,
            detail=detail,
            client_ip=client_ip,
        )


class OrganizationApplicationService:
    @property
    def default_organization_id(self) -> str:
        return legacy_organizations.DEFAULT_ORGANIZATION_ID

    @property
    def write_roles(self) -> frozenset[str]:
        return frozenset(legacy_organizations.ORG_WRITE_ROLES)

    def ensure_default_membership(self, user: UserIdentity) -> None:
        legacy_organizations.ensure_default_membership(user)

    def list_organizations(self, actor: UserIdentity) -> list[Organization]:
        return legacy_organizations.list_organizations(actor)

    def current_organization(self, actor: UserIdentity, requested_id: str | None = None) -> Organization:
        return legacy_organizations.current_organization(actor, requested_id)

    def create_organization(self, payload: OrganizationCreateRequest, actor: UserIdentity) -> Organization:
        return legacy_organizations.create_organization(payload, actor)

    def list_members(self, organization_id: str, actor: UserIdentity) -> list[OrganizationMember]:
        return legacy_organizations.list_members(organization_id, actor)

    def add_member(
        self,
        organization_id: str,
        payload: OrganizationMemberAddRequest,
        actor: UserIdentity,
    ) -> OrganizationMember:
        return legacy_organizations.add_member(organization_id, payload, actor)

    def require_organization_role(self, organization_id: str, actor: UserIdentity, roles: set[str]) -> str:
        return legacy_organizations.require_organization_role(organization_id, actor, roles)

    def scope_resource(self, organization_id: str, resource_type: str, resource_id: str) -> None:
        legacy_organizations.scope_resource(organization_id, resource_type, resource_id)

    def require_resource_scope(self, organization_id: str, resource_type: str, resource_id: str) -> None:
        legacy_organizations.require_resource_scope(organization_id, resource_type, resource_id)

    def enforce_api_resource_scope(
        self,
        organization_id: str,
        actor: UserIdentity,
        method: str,
        path: str,
    ) -> None:
        legacy_organizations.enforce_api_resource_scope(organization_id, actor, method, path)

    def scoped_resource_ids(self, organization_id: str, resource_type: str) -> set[str]:
        return legacy_organizations.scoped_resource_ids(organization_id, resource_type)


identity_service: IdentityApplicationPort = IdentityApplicationService()
organization_service: OrganizationApplicationPort = OrganizationApplicationService()
