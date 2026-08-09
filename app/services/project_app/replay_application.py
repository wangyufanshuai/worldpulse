"""Replay Pack application adapter for the Research Workspace context."""

from __future__ import annotations

from collections.abc import Callable
import json

from fastapi import HTTPException

from app.core.models import WarRoomReplayPack
from app.services.plugin_sdk import (
    build_plugin_input,
    canonical_hash,
    verify_stored_plugin_output,
)
from app.services.plugin_sdk.builtins.report_renderer import (
    MarkdownRenderOutputV1,
    ReportRendererAdapter,
    build_renderer_lineage,
    verify_renderer_lineage,
)
from app.services.world_model import WORLD_MODEL_DISCLAIMER as WAR_ROOM_DISCLAIMER

from .diffing import build_war_room_run_diff
from .replay_pack import (
    _render_war_room_replay_markdown,
    _replay_pack_audit_trail,
    _replay_pack_lifecycle_artifacts,
    _replay_pack_manifest,
    _replay_pack_model_inputs,
    _replay_pack_model_outputs,
    _replay_pack_summary,
)
from .repository import get_project, graph_for_run, latest_run, run_by_id


class ReplayPackApplicationService:
    """Assemble verified Replay Packs exclusively from stored state."""

    def build(
        self,
        project_id: str,
        *,
        run_id: str | None = None,
        base_run_id: str | None = None,
        target_run_id: str | None = None,
        now_factory: Callable[[], str],
    ) -> WarRoomReplayPack:
        project = get_project(project_id)
        target = run_by_id(project_id, target_run_id or run_id) if (target_run_id or run_id) else latest_run(project_id)
        if target is None:
            raise HTTPException(status_code=404, detail="No run available for replay pack")
        target_graph = graph_for_run(project_id, target.run_id)
        target_sim = target.simulation_snapshot or {}
        if not target_sim.get("scenario"):
            raise HTTPException(status_code=422, detail="Replay Pack requires a War Room run")

        base = run_by_id(project_id, base_run_id) if base_run_id else None
        base_graph = graph_for_run(project_id, base.run_id) if base else None
        diff = build_war_room_run_diff(base, target, base_graph, target_graph) if base else None
        lifecycle_artifacts = _replay_pack_lifecycle_artifacts(target)
        summary = _replay_pack_summary(target, diff, lifecycle_artifacts)
        generated_at = now_factory()
        manifest = _replay_pack_manifest(
            project_id,
            project.title,
            target,
            base,
            diff,
            generated_at,
            lifecycle_artifacts,
        )
        model_inputs = _replay_pack_model_inputs(target_sim)
        model_outputs = _replay_pack_model_outputs(target_sim, target_graph, diff, lifecycle_artifacts)
        audit_trail = _replay_pack_audit_trail(base, target, diff, lifecycle_artifacts)
        renderer = ReportRendererAdapter(
            replay_renderer=_render_war_room_replay_markdown,
        )
        render_request = build_plugin_input(
            renderer.manifest,
            {
                "schema_version": "markdown-render-request.v1",
                "render_kind": "war_room_replay",
                "payload": {
                    "project_id": project_id,
                    "project_title": project.title,
                    "target": target.model_dump(mode="json"),
                    "graph": (
                        target_graph.model_dump(mode="json")
                        if target_graph
                        else None
                    ),
                    "diff": diff,
                    "summary": summary,
                    "manifest": manifest,
                    "model_inputs": model_inputs,
                    "audit_trail": audit_trail,
                },
            },
            run_id=target.run_id,
        )
        stored_render = renderer.execute(render_request)
        verify_stored_plugin_output(
            renderer.manifest,
            stored_render,
            require_provider_free=True,
            require_zero_provider_calls=True,
        )
        rendered = MarkdownRenderOutputV1.model_validate(stored_render.payload)
        markdown = rendered.markdown
        plugin_lineage = manifest.get("plugin_lineage")
        if not isinstance(plugin_lineage, dict):
            raise ValueError("Replay Pack plugin lineage must be an object")
        plugin_lineage["replay_renderer"] = build_renderer_lineage(
            renderer.manifest,
            render_request,
            stored_render,
        )
        manifest["manifest_hash"] = canonical_hash(manifest)
        verify_replay_pack_plugin_lineage(manifest, markdown)
        json_manifest = json.dumps(
            {
                "manifest": manifest,
                "model_inputs": model_inputs,
                "model_outputs": model_outputs,
                "audit_trail": audit_trail,
                "summary": summary,
                "counterfactual_observations": diff.get("counterfactual_observations", []) if diff else [],
                "disclaimer": WAR_ROOM_DISCLAIMER,
            },
            ensure_ascii=False,
            indent=2,
        )
        return WarRoomReplayPack(
            project_id=project_id,
            run_id=target.run_id,
            base_run_id=base.run_id if base else None,
            target_run_id=target.run_id if base else None,
            title=f"{project.title} Replay Pack",
            scenario=target_sim.get("scenario", {}),
            policy_actions=target_sim.get("scenario", {}).get("policy_actions", []),
            risk_heatmap=target_sim.get("risk_heatmap", []),
            supply_chain_delta=diff.get("supply_chain_delta", []) if diff else [],
            agent_decisions=target_sim.get("agent_decisions", []),
            timeline=target_sim.get("timeline", []),
            timeline_delta=diff.get("timeline_delta", {}) if diff else {},
            impact_graph=target_sim.get("impact_graph", target_graph.model_dump() if target_graph else {}),
            assumptions=target_sim.get("assumptions", []),
            counterfactual_observations=diff.get("counterfactual_observations", []) if diff else [],
            summary=summary,
            manifest=manifest,
            model_inputs=model_inputs,
            model_outputs=model_outputs,
            audit_trail=audit_trail,
            artifacts={"markdown": markdown, "json_manifest": json_manifest},
            markdown=markdown,
            disclaimer=WAR_ROOM_DISCLAIMER,
        )


replay_pack_service = ReplayPackApplicationService()


def verify_replay_pack_plugin_lineage(
    manifest: dict,
    markdown: str,
) -> dict:
    stored_manifest_hash = manifest.get("manifest_hash")
    if not isinstance(stored_manifest_hash, str):
        raise ValueError("Replay Pack manifest hash is missing")
    manifest_preimage = {
        key: value
        for key, value in manifest.items()
        if key != "manifest_hash"
    }
    if canonical_hash(manifest_preimage) != stored_manifest_hash:
        raise ValueError("Replay Pack manifest hash mismatch")
    plugin_lineage = manifest.get("plugin_lineage")
    if not isinstance(plugin_lineage, dict):
        raise ValueError("Replay Pack plugin lineage must be an object")
    renderer_lineage = plugin_lineage.get("replay_renderer")
    if not isinstance(renderer_lineage, dict):
        raise ValueError("Replay Pack Renderer lineage is missing")
    verify_renderer_lineage(
        renderer_lineage,
        markdown,
        render_kind="war_room_replay",
    )
    return manifest
