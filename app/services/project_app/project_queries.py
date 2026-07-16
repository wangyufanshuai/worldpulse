from __future__ import annotations

from app.core.models import ProjectDetail, ResearchProject, WarRoomWorkspaceState
from app.services.project_app.repository import (
    chat_messages,
    get_project,
    graph_for_run,
    project_from_row,
    project_runs,
    report_for_run,
    run_by_id,
)
from app.services.project_app.workspace import build_war_room_workspace_state, is_war_room_run
from app.services.project_store import connect, init_db


def list_projects(limit: int = 50, organization_id: str | None = None) -> list[ResearchProject]:
    init_db()
    with connect() as conn:
        if organization_id:
            rows = conn.execute(
                """
                SELECT p.* FROM research_projects p
                JOIN organization_resources r ON r.resource_id = p.project_id
                WHERE r.organization_id = ? AND r.resource_type = 'project'
                ORDER BY p.updated_at DESC, p.project_id DESC LIMIT ?
                """,
                (organization_id, max(1, min(limit, 100))),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM research_projects ORDER BY updated_at DESC, project_id DESC LIMIT ?",
                (max(1, min(limit, 100)),),
            ).fetchall()
    return [project_from_row(row) for row in rows]


def get_project_detail(project_id: str, run_id: str | None = None) -> ProjectDetail:
    project = get_project(project_id)
    runs = project_runs(project_id)
    selected_run = run_by_id(project_id, run_id) if run_id else (runs[0] if runs else None)
    return ProjectDetail(
        project=project,
        latest_run=selected_run,
        runs=runs,
        graph=graph_for_run(project_id, selected_run.run_id) if selected_run else None,
        report=report_for_run(project_id, selected_run.run_id) if selected_run else None,
        chat_messages=chat_messages(project_id),
    )


def war_room_workspace(project_id: str, run_id: str | None = None) -> WarRoomWorkspaceState:
    project = get_project(project_id)
    runs = project_runs(project_id)
    war_room_runs = [run for run in runs if is_war_room_run(run)]
    selected_run = run_by_id(project_id, run_id) if run_id else (war_room_runs[0] if war_room_runs else None)
    return build_war_room_workspace_state(project, war_room_runs, selected_run)
