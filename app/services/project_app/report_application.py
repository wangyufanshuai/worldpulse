"""Report application adapter for the Research Workspace context."""

from __future__ import annotations

from collections.abc import Callable
import json
from typing import Any

from app.core.models import (
    CausalGraphSnapshot,
    ProjectAIReport,
    ReportCitation,
    ResearchProject,
    ResearchRun,
    WarRoomRun,
)
from app.services.plugin_sdk import build_plugin_input, verify_stored_plugin_output
from app.services.plugin_sdk.builtins.report_renderer import (
    MarkdownRenderOutputV1,
    ReportRendererAdapter,
    build_renderer_lineage,
)

from .reports import (
    build_project_report,
    build_war_room_project_report,
    render_project_markdown,
    render_war_room_project_markdown,
)


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
        lineage: dict[str, Any] = {}

        def render(analysis, citations):
            markdown, captured = _render_project_markdown(
                project.project_id,
                run.run_id,
                analysis,
                citations,
            )
            lineage.update(captured)
            return markdown

        report = build_project_report(
            project,
            run,
            graph,
            causal,
            analyze_fn,
            render_fn=render,
        )
        report.citations.append(_renderer_lineage_citation(lineage))
        return report

    def build_war_room(
        self,
        project: ResearchProject,
        run: ResearchRun,
        graph: CausalGraphSnapshot,
        result: WarRoomRun,
    ) -> ProjectAIReport:
        lineage: dict[str, Any] = {}
        trust_manifest = (run.data_snapshot or {}).get("trust_manifest") or {}

        def render(analysis, citations):
            markdown, captured = _render_project_markdown(
                project.project_id,
                run.run_id,
                analysis,
                citations,
                renderer=lambda report, report_citations: (
                    render_war_room_project_markdown(
                        report,
                        report_citations,
                        trust_manifest,
                    )
                ),
            )
            lineage.update(captured)
            return markdown

        report = build_war_room_project_report(
            project,
            run,
            graph,
            result,
            render_fn=render,
        )
        report.citations.append(_renderer_lineage_citation(lineage))
        return report


def _render_project_markdown(
    project_id: str,
    run_id: str,
    analysis,
    citations: list[ReportCitation],
    *,
    renderer=render_project_markdown,
) -> tuple[str, dict[str, Any]]:
    adapter = ReportRendererAdapter(project_renderer=renderer)
    request = build_plugin_input(
        adapter.manifest,
        {
            "schema_version": "markdown-render-request.v1",
            "render_kind": "project_report",
            "payload": {
                "project_id": project_id,
                "run_id": run_id,
                "analysis": analysis.model_dump(mode="json"),
                "citations": [item.model_dump(mode="json") for item in citations],
            },
        },
        run_id=run_id,
    )
    stored = adapter.execute(request)
    verify_stored_plugin_output(
        adapter.manifest,
        stored,
        require_provider_free=True,
        require_zero_provider_calls=True,
    )
    output = MarkdownRenderOutputV1.model_validate(stored.payload)
    return output.markdown, build_renderer_lineage(
        adapter.manifest,
        request,
        stored,
    )


def _renderer_lineage_citation(lineage: dict[str, Any]) -> ReportCitation:
    if not lineage:
        raise ValueError("Report Renderer did not produce lineage")
    return ReportCitation(
        citation_id="P1",
        finding_index=0,
        kind="plugin_manifest",
        target_id=f"plugin:{lineage['plugin_id']}@{lineage['plugin_version']}",
        title="WorldPulse Markdown Report Renderer",
        summary=json.dumps(lineage, ensure_ascii=False, sort_keys=True),
        source="WorldPulse Plugin SDK",
        confidence=100.0,
    )


def report_renderer_lineage(report: ProjectAIReport) -> dict[str, Any] | None:
    matches = [
        item
        for item in report.citations
        if item.kind == "plugin_manifest"
        and item.source == "WorldPulse Plugin SDK"
    ]
    if not matches:
        return None
    if len(matches) != 1:
        raise ValueError("Report contains duplicate Renderer lineage citations")
    try:
        lineage = json.loads(matches[0].summary)
    except (TypeError, ValueError) as exc:
        raise ValueError("Report Renderer lineage citation is malformed") from exc
    if not isinstance(lineage, dict):
        raise ValueError("Report Renderer lineage citation must be an object")
    return lineage


report_service = ReportApplicationService()
