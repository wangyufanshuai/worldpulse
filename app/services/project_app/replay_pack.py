from __future__ import annotations

import json
import hashlib

from app.core.models import CausalGraphSnapshot, ResearchRun
from app.services.project_store import connect, loads
from app.services.war_room_engine import WAR_ROOM_DISCLAIMER
from app.services.consistency.models import AgentActionProjectionAudit
from app.services.consistency.projection import verify_action_projection_audit


HYBRID_REPLAY_ARTIFACTS = (
    "agent_runtime_audit",
    "agent_action_proposals",
    "consistency_audit",
    "agent_action_projection_audit",
    "deterministic_action_modifiers",
    "hybrid_replay_record",
)


def _replay_pack_lifecycle_artifacts(target: ResearchRun) -> dict:
    """Load a verified, replay-safe subset without invoking an Agent or LLM."""

    lifecycle_job_id = (target.data_snapshot or {}).get("lifecycle_job_id")
    if not lifecycle_job_id:
        return {}
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT artifact_type, schema_version, content_json, sha256
            FROM run_artifacts
            WHERE run_id = ?
            ORDER BY created_at ASC, rowid ASC
            """,
            (lifecycle_job_id,),
        ).fetchall()
    verified = {}
    for row in rows:
        if row["artifact_type"] not in HYBRID_REPLAY_ARTIFACTS:
            continue
        digest = hashlib.sha256(row["content_json"].encode("utf-8")).hexdigest()
        if digest != row["sha256"]:
            raise ValueError(f"Replay artifact hash mismatch: {row['artifact_type']}")
        verified[row["artifact_type"]] = {
            "schema_version": row["schema_version"],
            "sha256": row["sha256"],
            "content": loads(row["content_json"], {}),
        }
        if row["artifact_type"] == "agent_action_projection_audit":
            projection_audit = AgentActionProjectionAudit.model_validate(verified[row["artifact_type"]]["content"])
            verify_action_projection_audit(projection_audit)
    if "hybrid_replay_record" not in verified:
        return {}
    return {"lifecycle_job_id": lifecycle_job_id, "artifacts": verified}


def _replay_pack_manifest(project_id: str, project_title: str, target: ResearchRun, base: ResearchRun | None, diff: dict | None, generated_at: str, lifecycle_artifacts: dict | None = None) -> dict:
    trust_manifest = (target.data_snapshot or {}).get("trust_manifest") or (target.simulation_snapshot or {}).get("trust_manifest")
    return {
        "pack_version": "war-room-replay-pack.audit.v1",
        "project_id": project_id,
        "project_title": project_title,
        "run_id": target.run_id,
        "base_run_id": base.run_id if base else None,
        "target_run_id": target.run_id if base else None,
        "generated_at": generated_at,
        "run_started_at": target.started_at,
        "run_completed_at": target.completed_at,
        "is_counterfactual": bool(diff),
        "artifact_types": ["markdown", "json_manifest"],
        "lifecycle_job_id": (lifecycle_artifacts or {}).get("lifecycle_job_id"),
        "verified_lifecycle_artifacts": sorted((lifecycle_artifacts or {}).get("artifacts", {})),
        "disclaimer": WAR_ROOM_DISCLAIMER,
        "trust_manifest": trust_manifest,
    }


def _replay_pack_model_inputs(sim: dict) -> dict:
    scenario = sim.get("scenario", {}) or {}
    return {
        "scenario": {
            "key": scenario.get("key") or scenario.get("scenario_key"),
            "name": scenario.get("name"),
            "description": scenario.get("description"),
        },
        "duration_days": scenario.get("duration_days"),
        "intensity": scenario.get("intensity"),
        "propagation": scenario.get("propagation"),
        "target_countries": scenario.get("target_countries", []),
        "target_chains": scenario.get("target_chains", []),
        "policy_actions": scenario.get("policy_actions", []),
        "country_overrides": scenario.get("country_overrides", {}),
        "chain_overrides": scenario.get("chain_overrides", {}),
    }


def _replay_pack_model_outputs(sim: dict, graph: CausalGraphSnapshot | None, diff: dict | None, lifecycle_artifacts: dict | None = None) -> dict:
    outputs = {
        "risk_heatmap": sim.get("risk_heatmap", []),
        "supply_chains": sim.get("supply_chains", []),
        "agent_decisions": sim.get("agent_decisions", []),
        "timeline": sim.get("timeline", []),
        "impact_graph": sim.get("impact_graph", graph.model_dump() if graph else {}),
        "ui_state": sim.get("ui_state", {}),
        "diff_metrics": diff or {},
    }
    if lifecycle_artifacts:
        outputs["hybrid"] = lifecycle_artifacts
    return outputs


def _replay_pack_audit_trail(base: ResearchRun | None, target: ResearchRun, diff: dict | None, lifecycle_artifacts: dict | None = None) -> list[dict]:
    trail = [
        {
            "step": "stored_run_snapshot",
            "source": "research_runs.simulation_snapshot",
            "detail": f"Loaded target War Room run {target.run_id} from existing project storage.",
        },
        {
            "step": "user_controls",
            "source": "scenario_config",
            "detail": "Scenario builder inputs were copied from the stored run snapshot; no live intelligence or market feed was used.",
        },
        {
            "step": "deterministic_rules",
            "source": "war_room_engine.py",
            "detail": "Country risk, supply-chain pressure, timeline, and agent decisions were produced by local deterministic rules.",
        },
        {
            "step": "counterfactual_diff" if diff else "single_run_export",
            "source": "compare API" if diff else "target run only",
            "detail": f"Compared base run {base.run_id} with target run {target.run_id}." if diff and base else "No base run was selected; the pack audits one run only.",
        },
        {
            "step": "template_generated_artifacts",
            "source": "Replay Pack renderer",
            "detail": "Markdown and JSON manifest were generated from stored snapshots and deterministic diff data.",
        },
        {
            "step": "boundary",
            "source": "WorldPulse disclaimer",
            "detail": WAR_ROOM_DISCLAIMER,
        },
    ]
    if lifecycle_artifacts:
        trail.insert(-2, {
            "step": "hybrid_offline_evidence_chain",
            "source": "verified run_artifacts",
            "detail": "Agent proposals, consistency decisions, deterministic modifiers, and replay hashes were loaded from SQLite and SHA-256 verified; no Agent or LLM was called.",
        })
    return trail


def _replay_pack_summary(target: ResearchRun, diff: dict | None, lifecycle_artifacts: dict | None = None) -> dict:
    sim = target.simulation_snapshot or {}
    heatmap = sim.get("risk_heatmap", [])
    chains = sim.get("supply_chains", [])
    timeline = sim.get("timeline", [])
    top_country = max(heatmap, key=lambda item: float(item.get("risk") or 0), default={})
    top_chain = max(chains, key=lambda item: float(item.get("pressure_score") or 0), default={})
    peak = max((float(item.get("global_risk") or 0) for item in timeline), default=None)
    hybrid_record = ((lifecycle_artifacts or {}).get("artifacts", {}).get("hybrid_replay_record", {}).get("content", {}))
    return {
        "run_id": target.run_id,
        "policy_actions": sim.get("scenario", {}).get("policy_actions", []),
        "top_risk_country": top_country,
        "top_chain": top_chain,
        "timeline_peak_global_risk": round(peak, 1) if peak is not None else None,
        "top_chain_delta": diff.get("top_chain_pressure_delta") if diff else None,
        "timeline_peak_delta": diff.get("timeline_delta", {}).get("peak_delta") if diff else None,
        "is_counterfactual": bool(diff),
        "hybrid": hybrid_record or None,
    }


def _render_war_room_replay_markdown(project_title: str, target: ResearchRun, graph: CausalGraphSnapshot | None, diff: dict | None, summary: dict, manifest: dict, model_inputs: dict, audit_trail: list[dict]) -> str:
    sim = target.simulation_snapshot or {}
    scenario = sim.get("scenario", {})
    policy_actions = scenario.get("policy_actions", [])
    heatmap = sim.get("risk_heatmap", [])
    chains = diff.get("supply_chain_delta", []) if diff else sim.get("supply_chains", [])
    decisions = sim.get("agent_decisions", [])
    timeline = sim.get("timeline", [])
    assumptions = sim.get("assumptions", [])
    edges = (graph.edges if graph else sim.get("impact_graph", {}).get("edges", [])) or []
    observations = diff.get("counterfactual_observations", []) if diff else ["Single-run Replay Pack; no base run was selected for counterfactual comparison."]

    lines = [
        f"# {project_title} War Room Replay Pack",
        "",
        f"> {WAR_ROOM_DISCLAIMER}",
        "",
        "## Replay Pack Manifest",
        f"- Pack version: `{manifest.get('pack_version')}`",
        f"- Project ID: `{manifest.get('project_id')}`",
        f"- Run ID: `{manifest.get('run_id')}`",
        f"- Base run ID: `{manifest.get('base_run_id') or 'none'}`",
        f"- Target run ID: `{manifest.get('target_run_id') or manifest.get('run_id')}`",
        f"- Generated at: {manifest.get('generated_at')}",
        f"- Counterfactual: {manifest.get('is_counterfactual')}",
        "",
        "## Scenario Setup",
        f"- Run ID: `{target.run_id}`",
        f"- Scenario: {scenario.get('name') or scenario.get('key') or 'War Room scenario'}",
        f"- Duration: {scenario.get('duration_days')} days",
        f"- Intensity: {scenario.get('intensity')}",
        f"- Propagation: {scenario.get('propagation')}",
        f"- Target countries: {', '.join(scenario.get('target_countries') or []) or 'none'}",
        f"- Target chains: {', '.join(scenario.get('target_chains') or []) or 'none'}",
        "",
        "## Policy Actions",
        *(f"- {item}" for item in (policy_actions or ["none"])),
        "",
        "## Model Inputs",
        f"- Duration: {model_inputs.get('duration_days')} days",
        f"- Intensity: {model_inputs.get('intensity')}",
        f"- Propagation: {model_inputs.get('propagation')}",
        f"- Target countries: {', '.join(model_inputs.get('target_countries') or []) or 'none'}",
        f"- Target chains: {', '.join(model_inputs.get('target_chains') or []) or 'none'}",
        f"- Policy actions: {', '.join(model_inputs.get('policy_actions') or []) or 'none'}",
        "",
        "## User Overrides",
        f"- Country overrides: `{json.dumps(model_inputs.get('country_overrides') or {}, ensure_ascii=False)}`",
        f"- Chain overrides: `{json.dumps(model_inputs.get('chain_overrides') or {}, ensure_ascii=False)}`",
        "",
        "## Risk Hotspots",
        *[
            f"- {item.get('country_name')} ({item.get('country_code')}): {float(item.get('risk') or 0):.1f}/100, dominant channel `{item.get('dominant_channel')}`"
            for item in heatmap[:8]
        ],
        "",
        "## Supply Chain Bottlenecks",
    ]
    if diff:
        lines.extend(
            f"- {item.get('name')}: {item.get('base_pressure')} -> {item.get('target_pressure')} ({float(item.get('delta') or 0):+.1f})"
            for item in chains[:8]
        )
    else:
        lines.extend(
            f"- {item.get('name')}: pressure {float(item.get('pressure_score') or 0):.1f}/100, capacity {item.get('capacity')}"
            for item in chains[:8]
        )
    lines.extend(
        [
            "",
            "## Agent Decisions",
            *[
                f"- {item.get('country_name')} ({item.get('country_code')}): {item.get('action')} | drivers: {', '.join(item.get('drivers') or []) or 'none'}"
                for item in decisions[:8]
            ],
            "",
            "## Timeline Turning Points",
            *[
                f"- D+{item.get('day')}: global risk {float(item.get('global_risk') or 0):.1f}/100 - {item.get('key_development')}"
                for item in timeline
                if item.get("turning_point") or item.get("day") in {0, scenario.get("duration_days")}
            ],
            "",
            "## Causal Mechanisms",
            *[
                f"- {edge.get('source')} -> {edge.get('target')}: {edge.get('relation')} | weight {edge.get('weight')} | {edge.get('mechanism') or edge.get('explanation')}"
                for edge in edges[:10]
            ],
            "",
            "## Deterministic Rule Trace",
            "- Scenario inputs were normalized before simulation.",
            "- Policy actions adjusted supply-chain pressure and country-agent risk through local rule deltas.",
            "- Risk heatmap, agent decisions, timeline, and causal edges were rendered from stored deterministic outputs.",
            "- AI text, when present elsewhere in the project, is explanatory and does not determine core numeric results.",
            "",
            "## Counterfactual Observations",
            *(f"- {item}" for item in observations),
            "",
            "## Audit Trail",
            *[f"- `{item.get('step')}` ({item.get('source')}): {item.get('detail')}" for item in audit_trail],
            "",
            "## Model Assumptions",
            *(f"- {item}" for item in assumptions),
            "",
            "## Replay Summary",
            f"- Top risk country: {summary.get('top_risk_country', {}).get('country_name')} ({summary.get('top_risk_country', {}).get('risk')})",
            f"- Top chain: {summary.get('top_chain', {}).get('name')} ({summary.get('top_chain', {}).get('pressure_score')})",
            f"- Timeline peak global risk: {summary.get('timeline_peak_global_risk')}",
            f"- Timeline peak delta: {summary.get('timeline_peak_delta')}",
            "",
            f"_{WAR_ROOM_DISCLAIMER}_",
            "",
        ]
    )
    return "\n".join(lines)
