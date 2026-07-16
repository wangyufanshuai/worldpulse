from __future__ import annotations

from datetime import datetime
import re
from uuid import uuid4

from fastapi import HTTPException

from app.core.organization_models import Organization, OrganizationCreateRequest, OrganizationMember, OrganizationMemberAddRequest
from app.core.trust_models import UserIdentity
from app.services.project_store import connect, init_db


DEFAULT_ORGANIZATION_ID = "org_default"
ORG_MANAGE_ROLES = {"owner", "admin"}
ORG_WRITE_ROLES = {"owner", "admin", "analyst"}
ORG_REVIEW_ROLES = {"owner", "admin", "reviewer"}


def ensure_default_membership(user: UserIdentity) -> None:
    init_db()
    role = "owner" if user.role == "admin" else user.role
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO organization_members
            (organization_id, user_id, role, status, created_at)
            VALUES (?, ?, ?, 'active', ?)
            ON CONFLICT(organization_id, user_id) DO NOTHING
            """,
            (DEFAULT_ORGANIZATION_ID, user.user_id, role, _now()),
        )


def list_organizations(actor: UserIdentity) -> list[Organization]:
    init_db()
    ensure_default_membership(actor)
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT o.*, m.role AS member_role FROM organizations o
            JOIN organization_members m ON m.organization_id = o.organization_id
            WHERE m.user_id = ? AND m.status = 'active' AND o.status = 'active'
            ORDER BY o.name, o.organization_id
            """,
            (actor.user_id,),
        ).fetchall()
    return [_organization(row) for row in rows]


def current_organization(actor: UserIdentity, requested_id: str | None = None) -> Organization:
    organizations = list_organizations(actor)
    default = next((item for item in organizations if item.organization_id == DEFAULT_ORGANIZATION_ID), None)
    target = requested_id or (default.organization_id if default else (organizations[0].organization_id if organizations else None))
    organization = next((item for item in organizations if item.organization_id == target), None)
    if organization is None:
        raise HTTPException(status_code=403, detail="Organization membership is required")
    return organization


def create_organization(payload: OrganizationCreateRequest, actor: UserIdentity) -> Organization:
    if actor.role != "admin":
        raise HTTPException(status_code=403, detail="Only a global administrator can create an organization")
    init_db()
    organization_id = f"org_{uuid4().hex[:16]}"
    now = _now()
    try:
        with connect() as conn:
            conn.execute(
                "INSERT INTO organizations(organization_id, slug, name, status, created_by_user_id, created_at, updated_at) VALUES (?, ?, ?, 'active', ?, ?, ?)",
                (organization_id, payload.slug, payload.name, actor.user_id, now, now),
            )
            conn.execute(
                "INSERT INTO organization_members(organization_id, user_id, role, status, added_by_user_id, created_at) VALUES (?, ?, 'owner', 'active', ?, ?)",
                (organization_id, actor.user_id, actor.user_id, now),
            )
    except Exception as exc:
        if "UNIQUE" in str(exc).upper():
            raise HTTPException(status_code=409, detail="Organization slug already exists") from exc
        raise
    return current_organization(actor, organization_id)


def list_members(organization_id: str, actor: UserIdentity) -> list[OrganizationMember]:
    require_organization_role(organization_id, actor, {"owner", "admin", "analyst", "reviewer", "viewer"})
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT m.*, u.username, u.display_name FROM organization_members m
            JOIN users u ON u.user_id = m.user_id
            WHERE m.organization_id = ? AND m.status = 'active'
            ORDER BY m.role, u.username
            """,
            (organization_id,),
        ).fetchall()
    return [_member(row) for row in rows]


def add_member(organization_id: str, payload: OrganizationMemberAddRequest, actor: UserIdentity) -> OrganizationMember:
    require_organization_role(organization_id, actor, ORG_MANAGE_ROLES)
    with connect() as conn:
        user = conn.execute("SELECT user_id FROM users WHERE user_id = ? AND is_active = 1", (payload.user_id,)).fetchone()
        if user is None:
            raise HTTPException(status_code=404, detail=f"Unknown active user: {payload.user_id}")
        conn.execute(
            """
            INSERT INTO organization_members(organization_id, user_id, role, status, added_by_user_id, created_at)
            VALUES (?, ?, ?, 'active', ?, ?)
            ON CONFLICT(organization_id, user_id) DO UPDATE SET
                role = excluded.role, status = 'active', added_by_user_id = excluded.added_by_user_id
            """,
            (organization_id, payload.user_id, payload.role, actor.user_id, _now()),
        )
    return next(item for item in list_members(organization_id, actor) if item.user_id == payload.user_id)


def require_organization_role(organization_id: str, actor: UserIdentity, roles: set[str]) -> str:
    init_db()
    ensure_default_membership(actor)
    with connect() as conn:
        row = conn.execute(
            "SELECT role FROM organization_members WHERE organization_id = ? AND user_id = ? AND status = 'active'",
            (organization_id, actor.user_id),
        ).fetchone()
    if row is None or row["role"] not in roles:
        raise HTTPException(status_code=403, detail="Organization role does not permit this operation")
    return row["role"]


def scope_resource(organization_id: str, resource_type: str, resource_id: str) -> None:
    init_db()
    with connect() as conn:
        conn.execute(
            "INSERT INTO organization_resources(organization_id, resource_type, resource_id, created_at) VALUES (?, ?, ?, ?) ON CONFLICT(organization_id, resource_type, resource_id) DO NOTHING",
            (organization_id, resource_type, resource_id, _now()),
        )


def require_resource_scope(organization_id: str, resource_type: str, resource_id: str) -> None:
    with connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM organization_resources WHERE organization_id = ? AND resource_type = ? AND resource_id = ?",
            (organization_id, resource_type, resource_id),
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Resource is not available in organization: {resource_type}/{resource_id}")


def enforce_api_resource_scope(organization_id: str, actor: UserIdentity, method: str, path: str) -> None:
    """Enforce organization membership for legacy project and v2 run URLs.

    The public v1-v4 response contracts remain unchanged. Organization selection is
    carried by ``X-WorldPulse-Org`` and defaults to ``org_default``.
    """
    project_match = re.search(r"/projects/([^/?]+)", path)
    project_id = project_match.group(1) if project_match else None
    if not project_id:
        run_match = re.search(r"/v2/runs/([^/?]+)", path)
        if run_match:
            with connect() as conn:
                row = conn.execute("SELECT project_id FROM run_jobs WHERE run_id = ?", (run_match.group(1),)).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail=f"Unknown lifecycle run: {run_match.group(1)}")
            project_id = row["project_id"]
    if not project_id:
        return
    allowed = ORG_WRITE_ROLES if method.upper() in {"POST", "PUT", "PATCH", "DELETE"} else {"owner", "admin", "analyst", "reviewer", "viewer"}
    require_organization_role(organization_id, actor, allowed)
    with connect() as conn:
        scoped = conn.execute(
            "SELECT 1 FROM organization_resources WHERE resource_type = 'project' AND resource_id = ? LIMIT 1",
            (project_id,),
        ).fetchone()
    if scoped is None and organization_id == DEFAULT_ORGANIZATION_ID:
        # Compatibility for pre-V1.5 fixtures and databases that receive a legacy
        # direct insert after the baseline migration. Normal creation paths always
        # write the resource scope atomically with the project.
        scope_resource(DEFAULT_ORGANIZATION_ID, "project", project_id)
    require_resource_scope(organization_id, "project", project_id)


def scoped_resource_ids(organization_id: str, resource_type: str) -> set[str]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT resource_id FROM organization_resources WHERE organization_id = ? AND resource_type = ?",
            (organization_id, resource_type),
        ).fetchall()
    return {row["resource_id"] for row in rows}


def _organization(row) -> Organization:
    return Organization(
        organization_id=row["organization_id"], slug=row["slug"], name=row["name"], status=row["status"],
        member_role=row["member_role"] if "member_role" in row.keys() else None,
        created_by_user_id=row["created_by_user_id"], created_at=row["created_at"], updated_at=row["updated_at"],
    )


def _member(row) -> OrganizationMember:
    return OrganizationMember(
        organization_id=row["organization_id"], user_id=row["user_id"], username=row["username"],
        display_name=row["display_name"], role=row["role"], status=row["status"],
        added_by_user_id=row["added_by_user_id"], created_at=row["created_at"],
    )


def _now() -> str:
    return datetime.now().isoformat(timespec="milliseconds")
