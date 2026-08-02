"""Replay Pack application adapter for the Research Workspace context."""

from __future__ import annotations

from collections.abc import Callable
import json

from fastapi import HTTPException

from app.core.models import WarRoomReplayPack
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
        markdown = _render_war_room_replay_markdown(
            project.title,
            target,
            target_graph,
            diff,
            summary,
            manifest,
            model_inputs,
            audit_trail,
        )
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
