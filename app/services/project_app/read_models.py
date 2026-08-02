"""Side-effect-free Research Workspace read application."""

from __future__ import annotations

from typing import Protocol

from app.core.models import (
    ProjectDetail,
    ReportCitation,
    ResearchProject,
    ResearchRun,
    WarRoomWorkspaceState,
)

from .project_queries import get_project_detail, list_projects, war_room_workspace
from .run_queries import project_run_citations, project_run_detail, project_runs


class ResearchWorkspaceReadPort(Protocol):
    def list_projects(self, limit: int = 50, organization_id: str | None = None) -> list[ResearchProject]: ...

    def get_project_detail(self, project_id: str, run_id: str | None = None) -> ProjectDetail: ...

    def war_room_workspace(self, project_id: str, run_id: str | None = None) -> WarRoomWorkspaceState: ...

    def project_runs(self, project_id: str) -> list[ResearchRun]: ...

    def project_run_detail(self, project_id: str, run_id: str) -> ProjectDetail: ...

    def project_run_citations(self, project_id: str, run_id: str) -> list[ReportCitation]: ...


class ResearchWorkspaceReadService:
    """Stable read contract over the existing repository/query adapters."""

    def list_projects(self, limit: int = 50, organization_id: str | None = None) -> list[ResearchProject]:
        return list_projects(limit, organization_id=organization_id)

    def get_project_detail(self, project_id: str, run_id: str | None = None) -> ProjectDetail:
        return get_project_detail(project_id, run_id=run_id)

    def war_room_workspace(self, project_id: str, run_id: str | None = None) -> WarRoomWorkspaceState:
        return war_room_workspace(project_id, run_id=run_id)

    def project_runs(self, project_id: str) -> list[ResearchRun]:
        return project_runs(project_id)

    def project_run_detail(self, project_id: str, run_id: str) -> ProjectDetail:
        return project_run_detail(project_id, run_id)

    def project_run_citations(self, project_id: str, run_id: str) -> list[ReportCitation]:
        return project_run_citations(project_id, run_id)
