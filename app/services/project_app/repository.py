from __future__ import annotations

from fastapi import HTTPException

from app.core.models import CausalGraphSnapshot, ProjectAIReport, ProjectChatMessage, ResearchProject, ResearchRun
from app.services.plugin_sdk.builtins.report_renderer import verify_renderer_lineage
from app.services.project_store import connect, init_db, loads

from .report_application import report_renderer_lineage


def get_project(project_id: str) -> ResearchProject:
    init_db()
    with connect() as conn:
        row = conn.execute("SELECT * FROM research_projects WHERE project_id = ?", (project_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Unknown project: {project_id}")
    return project_from_row(row)


def latest_run(project_id: str) -> ResearchRun | None:
    init_db()
    with connect() as conn:
        row = conn.execute("SELECT * FROM research_runs WHERE project_id = ? ORDER BY started_at DESC, run_id DESC LIMIT 1", (project_id,)).fetchone()
    return run_from_row(row) if row else None


def project_runs(project_id: str, limit: int = 20) -> list[ResearchRun]:
    init_db()
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM research_runs WHERE project_id = ? ORDER BY started_at DESC, run_id DESC LIMIT ?",
            (project_id, max(1, min(limit, 50))),
        ).fetchall()
    return [run_from_row(row) for row in rows]


def run_by_id(project_id: str, run_id: str | None) -> ResearchRun | None:
    if not run_id:
        return None
    init_db()
    with connect() as conn:
        row = conn.execute("SELECT * FROM research_runs WHERE project_id = ? AND run_id = ?", (project_id, run_id)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Unknown run for project: {run_id}")
    return run_from_row(row)


def latest_graph(project_id: str) -> CausalGraphSnapshot | None:
    init_db()
    with connect() as conn:
        row = conn.execute("SELECT * FROM causal_graph_snapshots WHERE project_id = ? ORDER BY generated_at DESC LIMIT 1", (project_id,)).fetchone()
    return graph_from_row(row) if row else None


def graph_for_run(project_id: str, run_id: str) -> CausalGraphSnapshot | None:
    init_db()
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM causal_graph_snapshots WHERE project_id = ? AND run_id = ? ORDER BY generated_at DESC LIMIT 1",
            (project_id, run_id),
        ).fetchone()
    return graph_from_row(row) if row else None


def latest_report(project_id: str) -> ProjectAIReport | None:
    init_db()
    with connect() as conn:
        row = conn.execute(
            """
            SELECT reports.*, runs.data_snapshot AS run_data_snapshot
            FROM ai_reports AS reports
            LEFT JOIN research_runs AS runs
              ON runs.project_id = reports.project_id AND runs.run_id = reports.run_id
            WHERE reports.project_id = ?
            ORDER BY reports.generated_at DESC
            LIMIT 1
            """,
            (project_id,),
        ).fetchone()
    return report_from_row(row) if row else None


def report_for_run(project_id: str, run_id: str) -> ProjectAIReport | None:
    init_db()
    with connect() as conn:
        row = conn.execute(
            """
            SELECT reports.*, runs.data_snapshot AS run_data_snapshot
            FROM ai_reports AS reports
            LEFT JOIN research_runs AS runs
              ON runs.project_id = reports.project_id AND runs.run_id = reports.run_id
            WHERE reports.project_id = ? AND reports.run_id = ?
            ORDER BY reports.generated_at DESC
            LIMIT 1
            """,
            (project_id, run_id),
        ).fetchone()
    return report_from_row(row) if row else None


def chat_messages(project_id: str) -> list[ProjectChatMessage]:
    init_db()
    with connect() as conn:
        rows = conn.execute("SELECT * FROM chat_messages WHERE project_id = ? ORDER BY created_at ASC LIMIT 80", (project_id,)).fetchall()
    return [
        ProjectChatMessage(
            message_id=row["message_id"],
            project_id=row["project_id"],
            role=row["role"],
            content=row["content"],
            created_at=row["created_at"],
            mode=row["mode"],
        )
        for row in rows
    ]


def project_from_row(row) -> ResearchProject:
    return ResearchProject(
        project_id=row["project_id"],
        title=row["title"],
        question=row["question"],
        region=row["region"],
        asset_scope=loads(row["asset_scope"], []),
        event_window_days=int(row["event_window_days"]),
        event_types=loads(row["event_types"], []),
        mode=row["mode"] if "mode" in row.keys() else "research",
        scenario_config=loads(row["scenario_config"] if "scenario_config" in row.keys() else None, {}),
        status=row["status"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def run_from_row(row) -> ResearchRun:
    return ResearchRun(
        run_id=row["run_id"],
        project_id=row["project_id"],
        status=row["status"],
        started_at=row["started_at"],
        completed_at=row["completed_at"],
        summary=row["summary"],
        data_snapshot=loads(row["data_snapshot"], {}),
        risk_snapshot=loads(row["risk_snapshot"], {}),
        event_snapshot=loads(row["event_snapshot"], []),
        simulation_snapshot=loads(row["simulation_snapshot"], {}),
        backtest_snapshot=loads(row["backtest_snapshot"], {}),
    )


def graph_from_row(row) -> CausalGraphSnapshot:
    return CausalGraphSnapshot(
        graph_id=row["graph_id"],
        project_id=row["project_id"],
        run_id=row["run_id"],
        generated_at=row["generated_at"],
        nodes=loads(row["nodes"], []),
        edges=loads(row["edges"], []),
        confidence=float(row["confidence"]),
        evidence_sources=loads(row["evidence_sources"], []),
    )


def report_from_row(row) -> ProjectAIReport:
    report = ProjectAIReport(
        report_id=row["report_id"],
        project_id=row["project_id"],
        run_id=row["run_id"],
        generated_at=row["generated_at"],
        mode=row["mode"],
        title=row["title"],
        summary=row["summary"],
        key_findings=loads(row["key_findings"], []),
        evidence=loads(row["evidence"], []),
        uncertainties=loads(row["uncertainties"], []),
        watch_signals=loads(row["watch_signals"], []),
        scenario_suggestions=loads(row["scenario_suggestions"], []),
        citations=loads(row["citations"] if "citations" in row.keys() else None, []),
        markdown=row["markdown"],
        disclaimer=row["disclaimer"],
    )
    lineage = report_renderer_lineage(report)
    run_data = loads(
        row["run_data_snapshot"] if "run_data_snapshot" in row.keys() else None,
        {},
    )
    run_plugin_lineage = run_data.get("plugin_lineage") or {}
    if not isinstance(run_plugin_lineage, dict):
        raise ValueError("Run plugin lineage must be an object")
    stored_lineage = run_plugin_lineage.get("report_renderer")
    if stored_lineage is not None:
        if not isinstance(stored_lineage, dict):
            raise ValueError("Run Report Renderer lineage must be an object")
        if lineage is None:
            raise ValueError("Report Renderer lineage citation is missing")
        if lineage != stored_lineage:
            raise ValueError("Report Renderer lineage does not match Run lineage")
    if lineage is not None:
        verify_renderer_lineage(
            lineage,
            report.markdown,
            render_kind="project_report",
        )
    return report
