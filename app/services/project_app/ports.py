"""Application port for the Research Workspace bounded context."""

from __future__ import annotations

from typing import Any, Protocol

from app.core.models import (
    CausalGraphSnapshot,
    GraphEditRequest,
    ProjectAIReport,
    ProjectChatMessage,
    ProjectChatRequest,
    ProjectDetail,
    ReportCitation,
    ResearchProject,
    ResearchProjectCreate,
    ResearchRun,
    ResearchRunDiff,
    WarRoomReplayPack,
    WarRoomRun,
    WarRoomScenarioRequest,
    WarRoomWorkspaceState,
)

from .read_models import ResearchWorkspaceReadPort, ResearchWorkspaceReadService


class ResearchWorkspaceApplicationPort(Protocol):
    def create_project(self, payload: ResearchProjectCreate, organization_id: str = "org_default") -> ResearchProject: ...

    def list_projects(self, limit: int = 50, organization_id: str | None = None) -> list[ResearchProject]: ...

    def get_project_detail(self, project_id: str, run_id: str | None = None) -> ProjectDetail: ...

    def war_room_workspace(self, project_id: str, run_id: str | None = None) -> WarRoomWorkspaceState: ...

    def run_project(self, project_id: str, mode: str = "fast") -> ProjectDetail: ...

    def run_project_war_room(self, project_id: str, request: WarRoomScenarioRequest | None = None) -> ProjectDetail: ...

    def persist_war_room_result(
        self,
        project_id: str,
        result: WarRoomRun,
        *,
        run_id: str | None = None,
        started: str | None = None,
        completed: str | None = None,
        lifecycle_job_id: str | None = None,
    ) -> ProjectDetail: ...

    def latest_project_graph(self, project_id: str) -> CausalGraphSnapshot: ...

    def latest_project_report(self, project_id: str) -> ProjectAIReport: ...

    def project_runs(self, project_id: str) -> list[ResearchRun]: ...

    def project_run_detail(self, project_id: str, run_id: str) -> ProjectDetail: ...

    def project_run_citations(self, project_id: str, run_id: str) -> list[ReportCitation]: ...

    def edit_project_graph(self, project_id: str, payload: GraphEditRequest) -> ProjectDetail: ...

    def compare_project_runs(self, project_id: str, base_run_id: str, target_run_id: str) -> ResearchRunDiff: ...

    def war_room_replay_pack(
        self,
        project_id: str,
        run_id: str | None = None,
        base_run_id: str | None = None,
        target_run_id: str | None = None,
    ) -> WarRoomReplayPack: ...

    def chat_with_project(self, project_id: str, payload: ProjectChatRequest) -> ProjectChatMessage: ...


class ResearchWorkspaceApplicationService:
    """Compatibility adapter over the existing project application service."""

    def __init__(self, delegate: Any | None = None, read_service: ResearchWorkspaceReadPort | None = None) -> None:
        self._uses_read_service = delegate is None
        if delegate is None:
            from app.services import projects

            delegate = projects
        self._delegate = delegate
        self._read_service = read_service or ResearchWorkspaceReadService()

    def _read_target(self) -> Any:
        return self._read_service if self._uses_read_service else self._delegate

    def create_project(self, payload: ResearchProjectCreate, organization_id: str = "org_default") -> ResearchProject:
        return self._delegate.create_project(payload, organization_id=organization_id)

    def list_projects(self, limit: int = 50, organization_id: str | None = None) -> list[ResearchProject]:
        return self._read_target().list_projects(limit=limit, organization_id=organization_id)

    def get_project_detail(self, project_id: str, run_id: str | None = None) -> ProjectDetail:
        return self._read_target().get_project_detail(project_id, run_id=run_id)

    def war_room_workspace(self, project_id: str, run_id: str | None = None) -> WarRoomWorkspaceState:
        return self._read_target().war_room_workspace(project_id, run_id=run_id)

    def run_project(self, project_id: str, mode: str = "fast") -> ProjectDetail:
        return self._delegate.run_project(project_id, mode=mode)

    def run_project_war_room(self, project_id: str, request: WarRoomScenarioRequest | None = None) -> ProjectDetail:
        return self._delegate.run_project_war_room(project_id, request)

    def persist_war_room_result(self, project_id: str, result: WarRoomRun, *, run_id: str | None = None, started: str | None = None, completed: str | None = None, lifecycle_job_id: str | None = None) -> ProjectDetail:
        return self._delegate.persist_war_room_result(project_id, result, run_id=run_id, started=started, completed=completed, lifecycle_job_id=lifecycle_job_id)

    def latest_project_graph(self, project_id: str) -> CausalGraphSnapshot:
        return self._delegate.latest_project_graph(project_id)

    def latest_project_report(self, project_id: str) -> ProjectAIReport:
        return self._delegate.latest_project_report(project_id)

    def project_runs(self, project_id: str) -> list[ResearchRun]:
        return self._read_target().project_runs(project_id)

    def project_run_detail(self, project_id: str, run_id: str) -> ProjectDetail:
        return self._read_target().project_run_detail(project_id, run_id)

    def project_run_citations(self, project_id: str, run_id: str) -> list[ReportCitation]:
        return self._read_target().project_run_citations(project_id, run_id)

    def edit_project_graph(self, project_id: str, payload: GraphEditRequest) -> ProjectDetail:
        return self._delegate.edit_project_graph(project_id, payload)

    def compare_project_runs(self, project_id: str, base_run_id: str, target_run_id: str) -> ResearchRunDiff:
        return self._delegate.compare_project_runs(project_id, base_run_id=base_run_id, target_run_id=target_run_id)

    def war_room_replay_pack(self, project_id: str, run_id: str | None = None, base_run_id: str | None = None, target_run_id: str | None = None) -> WarRoomReplayPack:
        return self._delegate.war_room_replay_pack(project_id, run_id=run_id, base_run_id=base_run_id, target_run_id=target_run_id)

    def chat_with_project(self, project_id: str, payload: ProjectChatRequest) -> ProjectChatMessage:
        return self._delegate.chat_with_project(project_id, payload)


research_workspace_service: ResearchWorkspaceApplicationPort = ResearchWorkspaceApplicationService()
