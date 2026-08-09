"""Auditable Plugin SDK adapter for existing Markdown report renderers."""

from __future__ import annotations

from collections.abc import Callable
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.core.models import (
    AIAnalysisResult,
    CausalGraphSnapshot,
    ReportCitation,
    ResearchRun,
)

from ..contracts import (
    PluginInputEnvelope,
    PluginManifest,
    PluginOutputEnvelope,
    build_plugin_manifest,
    build_plugin_output,
    canonical_hash,
)
from ..registry import PluginRegistry
from ..verification import verify_plugin_input


RenderKind = Literal["project_report", "war_room_replay"]
ProjectMarkdownRenderer = Callable[[AIAnalysisResult, list[ReportCitation]], str]
ReplayMarkdownRenderer = Callable[
    [
        str,
        ResearchRun,
        CausalGraphSnapshot | None,
        dict | None,
        dict,
        dict,
        dict,
        list[dict],
    ],
    str,
]


class ProjectMarkdownPayloadV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    project_id: str = Field(min_length=3, max_length=80)
    run_id: str = Field(min_length=3, max_length=80)
    analysis: AIAnalysisResult
    citations: tuple[ReportCitation, ...]


class ReplayMarkdownPayloadV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    project_id: str = Field(min_length=3, max_length=80)
    project_title: str = Field(min_length=1, max_length=200)
    target: ResearchRun
    graph: CausalGraphSnapshot | None = None
    diff: dict[str, Any] | None = None
    summary: dict[str, Any]
    manifest: dict[str, Any]
    model_inputs: dict[str, Any]
    audit_trail: tuple[dict[str, Any], ...]


class MarkdownRenderRequestV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["markdown-render-request.v1"] = (
        "markdown-render-request.v1"
    )
    render_kind: RenderKind
    payload: dict[str, Any]


class MarkdownRenderOutputV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["markdown-render-output.v1"] = (
        "markdown-render-output.v1"
    )
    render_kind: RenderKind
    markdown: str
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


def installed_report_renderer_manifest() -> PluginManifest:
    return build_plugin_manifest(
        plugin_id="report_renderer.markdown",
        kind="report_renderer",
        version="1.0.0",
        implementation_id="builtin.report_renderer.markdown.v1",
        capabilities=(
            "citation.render",
            "markdown.render",
            "uncertainty.separate",
        ),
        permissions=("report.render",),
        input_schema="markdown-render-request.v1",
        output_schema="markdown-render-output.v1",
        configuration=ReportRendererAdapter.configuration(),
    )


class ReportRendererAdapter:
    """Call injected legacy renderers through a closed, hash-bound envelope."""

    def __init__(
        self,
        *,
        project_renderer: ProjectMarkdownRenderer | None = None,
        replay_renderer: ReplayMarkdownRenderer | None = None,
    ) -> None:
        self._project_renderer = project_renderer
        self._replay_renderer = replay_renderer
        self._manifest = installed_report_renderer_manifest()

    @classmethod
    def configuration(cls) -> dict[str, Any]:
        return {
            "templates": {
                "project_report": "project-markdown.v1",
                "war_room_replay": "war-room-replay-markdown.v1",
            },
            "section_taxonomy": [
                "evidence",
                "deterministic_derivation",
                "agent_observation",
                "uncertainty",
            ],
            "provider_calls": False,
            "numeric_authority_write": False,
        }

    @property
    def manifest(self) -> PluginManifest:
        return self._manifest

    def execute(self, envelope: PluginInputEnvelope) -> PluginOutputEnvelope:
        self.manifest.verify_configuration(self.configuration())
        verified = verify_plugin_input(self.manifest, envelope)
        request = MarkdownRenderRequestV1.model_validate(verified.payload)
        if request.schema_version != self.manifest.input_schema:
            raise ValueError("Report Renderer input schema does not match manifest")
        if request.render_kind == "project_report":
            payload = ProjectMarkdownPayloadV1.model_validate(request.payload)
            if verified.invocation.run_id != payload.run_id:
                raise ValueError("project Report Renderer run binding mismatch")
            if self._project_renderer is None:
                raise ValueError("project Report Renderer implementation is unavailable")
            markdown = self._project_renderer(
                payload.analysis,
                list(payload.citations),
            )
        else:
            payload = ReplayMarkdownPayloadV1.model_validate(request.payload)
            if verified.invocation.run_id != payload.target.run_id:
                raise ValueError("Replay Renderer run binding mismatch")
            if self._replay_renderer is None:
                raise ValueError("Replay Renderer implementation is unavailable")
            markdown = self._replay_renderer(
                payload.project_title,
                payload.target,
                payload.graph,
                payload.diff,
                payload.summary,
                payload.manifest,
                payload.model_inputs,
                list(payload.audit_trail),
            )
        output = MarkdownRenderOutputV1(
            render_kind=request.render_kind,
            markdown=markdown,
            content_hash=canonical_hash(markdown),
        )
        return build_plugin_output(
            self.manifest,
            verified.invocation,
            output.model_dump(mode="json"),
            provider_calls=0,
        )


def build_renderer_lineage(
    manifest: PluginManifest,
    request: PluginInputEnvelope,
    output: PluginOutputEnvelope,
) -> dict[str, Any]:
    rendered = MarkdownRenderOutputV1.model_validate(output.payload)
    return {
        "schema_version": "plugin-renderer-lineage.v1",
        "plugin_id": manifest.plugin_id,
        "plugin_version": manifest.version,
        "plugin_manifest_hash": manifest.manifest_hash,
        "plugin_configuration_hash": manifest.configuration_hash,
        "input_schema": request.input_schema,
        "input_payload_hash": request.payload_hash,
        "invocation_hash": request.invocation.invocation_hash,
        "output_schema": output.output_schema,
        "output_payload_hash": output.payload_hash,
        "render_kind": rendered.render_kind,
        "content_hash": rendered.content_hash,
        "provider_calls": output.provider_calls,
    }


def verify_renderer_lineage(
    lineage: dict[str, Any],
    markdown: str,
    *,
    render_kind: RenderKind,
) -> dict[str, Any]:
    manifest = installed_report_renderer_manifest()
    expected_identity = {
        "plugin_id": manifest.plugin_id,
        "plugin_version": manifest.version,
        "plugin_manifest_hash": manifest.manifest_hash,
        "plugin_configuration_hash": manifest.configuration_hash,
        "input_schema": manifest.input_schema,
        "output_schema": manifest.output_schema,
        "render_kind": render_kind,
        "provider_calls": 0,
    }
    if lineage.get("schema_version") != "plugin-renderer-lineage.v1":
        raise ValueError("Report Renderer lineage schema mismatch")
    if any(lineage.get(key) != value for key, value in expected_identity.items()):
        raise ValueError("Report Renderer lineage identity mismatch")
    output = MarkdownRenderOutputV1(
        render_kind=render_kind,
        markdown=markdown,
        content_hash=canonical_hash(markdown),
    )
    if lineage.get("content_hash") != output.content_hash:
        raise ValueError("Report Renderer content hash mismatch")
    if lineage.get("output_payload_hash") != canonical_hash(
        output.model_dump(mode="json")
    ):
        raise ValueError("Report Renderer output payload hash mismatch")
    for key in ("input_payload_hash", "invocation_hash"):
        value = lineage.get(key)
        if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
            raise ValueError(f"Report Renderer {key} is invalid")
    return lineage


def built_in_report_renderer_registry() -> PluginRegistry:
    return PluginRegistry((installed_report_renderer_manifest(),))
