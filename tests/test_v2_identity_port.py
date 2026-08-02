from __future__ import annotations

import ast
import inspect
from types import ModuleType

from app import main
from app.api import dependencies, v3, v4, v5, v6, v8, v9, v10, v11
from app.core.trust_models import UserIdentity
from app.services.identity import (
    IdentityApplicationPort,
    IdentityApplicationService,
    OrganizationApplicationPort,
    OrganizationApplicationService,
    identity_service,
    organization_service,
)
from app.services.identity import application as identity_application


def _imports(module: ModuleType) -> set[str]:
    tree = ast.parse(inspect.getsource(module))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.update(f"{node.module}.{alias.name}" for alias in node.names)
    return imported


def test_identity_adapter_delegates_security_decisions_to_legacy_service(monkeypatch):
    captured = {}

    def permission_for_request(method: str, path: str) -> str:
        captured.update({"method": method, "path": path})
        return "review"

    monkeypatch.setattr(identity_application.legacy_auth, "permission_for_request", permission_for_request)
    port: IdentityApplicationPort = IdentityApplicationService()

    assert port.permission_for_request("POST", "/api/v3/reviews/rev_1/decision") == "review"
    assert captured == {"method": "POST", "path": "/api/v3/reviews/rev_1/decision"}


def test_organization_adapter_delegates_scope_decisions_to_legacy_service(monkeypatch):
    captured = {}
    actor = UserIdentity(user_id="usr_1", username="analyst", display_name="Analyst", role="analyst")

    def require_organization_role(organization_id: str, delegated_actor: UserIdentity, roles: set[str]) -> str:
        captured.update({"organization_id": organization_id, "actor": delegated_actor, "roles": roles})
        return "analyst"

    monkeypatch.setattr(
        identity_application.legacy_organizations,
        "require_organization_role",
        require_organization_role,
    )
    port: OrganizationApplicationPort = OrganizationApplicationService()

    assert port.require_organization_role("org_1", actor, {"analyst"}) == "analyst"
    assert captured == {"organization_id": "org_1", "actor": actor, "roles": {"analyst"}}


def test_cookie_policy_preserves_names_lifetime_and_environment_security(monkeypatch):
    service = IdentityApplicationService()
    monkeypatch.setenv("WORLDPULSE_ENV", "development")
    development = service.cookie_policy()
    assert development.session_cookie_name == "worldpulse_session"
    assert development.csrf_cookie_name == "worldpulse_csrf"
    assert development.max_age_seconds == 8 * 60 * 60
    assert development.secure is False
    assert development.same_site == "lax"
    assert development.path == "/"

    monkeypatch.setenv("WORLDPULSE_ENV", "production")
    assert service.cookie_policy().secure is True


def test_api_entrypoints_use_public_identity_application_ports():
    assert main.identity is identity_service
    assert main.organization_context is organization_service
    assert dependencies.identity is identity_service
    assert v3.identity is identity_service
    assert v5.organization_context is organization_service

    for module in (main, dependencies, v3, v4, v5, v6, v8, v9, v10, v11):
        imports = _imports(module)
        assert not any(item == "app.services.auth" or item.startswith("app.services.auth.") for item in imports)
        assert not any(
            item == "app.services.organizations" or item.startswith("app.services.organizations.")
            for item in imports
        )
