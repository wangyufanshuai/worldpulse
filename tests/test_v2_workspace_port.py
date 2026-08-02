from __future__ import annotations

from app.api import routes, v5
from app.services.project_app import (
    ResearchWorkspaceApplicationPort,
    ResearchWorkspaceApplicationService,
    research_workspace_service,
)


def test_project_routes_use_research_workspace_application_port():
    route_service: ResearchWorkspaceApplicationPort = routes.project_service
    v5_service: ResearchWorkspaceApplicationPort = v5.project_service
    assert route_service is research_workspace_service
    assert v5_service is research_workspace_service
    for method in ("create_project", "get_project_detail", "run_project", "war_room_replay_pack", "chat_with_project"):
        assert callable(getattr(route_service, method))


def test_research_workspace_adapter_delegates_to_legacy_service():
    captured = {}

    class Delegate:
        def list_projects(self, *, limit, organization_id):
            captured.update({"limit": limit, "organization_id": organization_id})
            return []

    service = ResearchWorkspaceApplicationService(Delegate())
    assert service.list_projects(limit=12, organization_id="org_1") == []
    assert captured == {"limit": 12, "organization_id": "org_1"}
