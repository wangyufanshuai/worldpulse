from __future__ import annotations

from fastapi import HTTPException

from app.core.models import ProjectDetail, ReportCitation, ResearchRun
from app.services.project_app.project_queries import get_project_detail
from app.services.project_app.repository import get_project, project_runs as repository_project_runs, report_for_run


def project_runs(project_id: str) -> list[ResearchRun]:
    get_project(project_id)
    return repository_project_runs(project_id)


def project_run_detail(project_id: str, run_id: str) -> ProjectDetail:
    return get_project_detail(project_id, run_id=run_id)


def project_run_citations(project_id: str, run_id: str) -> list[ReportCitation]:
    report = report_for_run(project_id, run_id)
    if report is None:
        raise HTTPException(status_code=404, detail=f"Report not found for run: {run_id}")
    return report.citations
