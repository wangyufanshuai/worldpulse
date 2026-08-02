from __future__ import annotations

from app.api import routes, v5
from app.services.project_app import (
    ResearchWorkspaceApplicationPort,
    ResearchWorkspaceApplicationService,
    research_workspace_service,
)
from app.services.project_app.read_models import ResearchWorkspaceReadService
from app.services.project_app import service as legacy_workspace_service
from app.services.project_app.replay_application import replay_pack_service
from app.services.project_app.report_application import report_service


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


def test_workspace_read_service_exposes_stable_query_contract():
    read_service = ResearchWorkspaceReadService()
    for method in ("list_projects", "get_project_detail", "war_room_workspace", "project_runs", "project_run_citations"):
        assert callable(getattr(read_service, method))


def test_legacy_workspace_facade_forwards_replay_pack_to_adapter(monkeypatch):
    captured = {}

    def build(project_id, **kwargs):
        captured.update({"project_id": project_id, **kwargs})
        return "replay-pack"

    monkeypatch.setattr(replay_pack_service, "build", build)
    result = legacy_workspace_service.war_room_replay_pack(
        "project_1",
        run_id="run_1",
        base_run_id="run_0",
        target_run_id="run_1",
    )

    assert result == "replay-pack"
    assert captured["project_id"] == "project_1"
    assert captured["run_id"] == "run_1"
    assert callable(captured["now_factory"])


def test_workspace_report_adapter_exposes_research_and_war_room_builders():
    assert callable(report_service.build_research)
    assert callable(report_service.build_war_room)
