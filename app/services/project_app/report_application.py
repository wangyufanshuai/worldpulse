"""Report application adapter for the Research Workspace context."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.core.models import CausalGraphSnapshot, ProjectAIReport, ResearchProject, ResearchRun, WarRoomRun

from .reports import build_project_report, build_war_room_project_report


class ReportApplicationService:
    """Build version-compatible reports through explicit application inputs."""

    def build_research(
        self,
        project: ResearchProject,
        run: ResearchRun,
        graph: CausalGraphSnapshot,
        causal: Any,
        *,
        analyze_fn: Callable,
    ) -> ProjectAIReport:
        return build_project_report(project, run, graph, causal, analyze_fn)

    def build_war_room(
        self,
        project: ResearchProject,
        run: ResearchRun,
        graph: CausalGraphSnapshot,
        result: WarRoomRun,
    ) -> ProjectAIReport:
        return build_war_room_project_report(project, run, graph, result)


report_service = ReportApplicationService()
