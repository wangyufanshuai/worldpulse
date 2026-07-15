from __future__ import annotations

from app.core.models import CausalGraphSnapshot, ResearchRun
from app.services.war_room_engine import WAR_ROOM_DISCLAIMER


def risk_score(run: ResearchRun) -> float | None:
    score = run.risk_snapshot.get("latest", {}).get("score") if isinstance(run.risk_snapshot, dict) else None
    return float(score) if score is not None else None


def event_names(run: ResearchRun) -> set[str]:
    names = set()
    for item in run.event_snapshot or []:
        if isinstance(item, dict) and item.get("name"):
            names.add(str(item["name"]))
    return names


def build_war_room_run_diff(base: ResearchRun, target: ResearchRun, base_graph: CausalGraphSnapshot | None, target_graph: CausalGraphSnapshot | None) -> dict | None:
    base_sim = base.simulation_snapshot or {}
    target_sim = target.simulation_snapshot or {}
    if not base_sim.get("risk_heatmap") or not target_sim.get("risk_heatmap"):
        return None

    country_risk_delta = country_risk_delta_rows(base_sim, target_sim)
    supply_chain_delta = supply_chain_delta_rows(base_sim, target_sim)
    agent_decision_changes = agent_decision_change_rows(base_sim, target_sim)
    timeline_delta = timeline_delta_summary(base_sim, target_sim)
    causal_edge_delta = causal_edge_delta_rows(base_graph, target_graph)
    top_country = country_risk_delta[0] if country_risk_delta else None
    top_chain = supply_chain_delta[0] if supply_chain_delta else None
    base_peak = timeline_delta.get("base_peak_global_risk")
    target_peak = timeline_delta.get("target_peak_global_risk")
    confidence_delta = None
    if base_graph and target_graph:
        confidence_delta = round((target_graph.confidence or 0) - (base_graph.confidence or 0), 2)

    observations = []
    if top_chain:
        direction = "increased" if top_chain["delta"] > 0 else "decreased"
        observations.append(f"{top_chain['name']} pressure {direction} by {top_chain['delta']:+.1f} points.")
    if top_country:
        direction = "increased" if top_country["delta"] > 0 else "decreased"
        observations.append(f"{top_country['country_name']} country-agent risk {direction} by {top_country['delta']:+.1f} points.")
    if base_peak is not None and target_peak is not None:
        observations.append(f"Peak global risk changed by {target_peak - base_peak:+.1f} points across the timeline.")
    if not observations:
        observations.append("No material War Room counterfactual deltas were detected.")

    return {
        "base_run_id": base.run_id,
        "target_run_id": target.run_id,
        "base_policy_actions": base_sim.get("scenario", {}).get("policy_actions", []),
        "target_policy_actions": target_sim.get("scenario", {}).get("policy_actions", []),
        "global_risk_delta": round_delta(
            target.simulation_snapshot.get("timeline", [])[-1].get("global_risk") if target.simulation_snapshot.get("timeline") else None,
            base.simulation_snapshot.get("timeline", [])[-1].get("global_risk") if base.simulation_snapshot.get("timeline") else None,
        ),
        "top_country_risk_delta": top_country,
        "top_chain_pressure_delta": top_chain,
        "graph_confidence_delta": confidence_delta,
        "country_risk_delta": country_risk_delta,
        "supply_chain_delta": supply_chain_delta,
        "agent_decision_changes": agent_decision_changes,
        "timeline_delta": timeline_delta,
        "causal_edge_delta": causal_edge_delta,
        "target_hybrid_trace": target_sim.get("hybrid_trace"),
        "counterfactual_observations": observations,
        "disclaimer": WAR_ROOM_DISCLAIMER,
    }


def country_risk_delta_rows(base_sim: dict, target_sim: dict) -> list[dict]:
    base_items = {item.get("country_code"): item for item in base_sim.get("risk_heatmap", [])}
    rows = []
    for target_item in target_sim.get("risk_heatmap", []):
        code = target_item.get("country_code")
        base_item = base_items.get(code, {})
        base_risk = float(base_item.get("risk") or 0)
        target_risk = float(target_item.get("risk") or 0)
        rows.append({
            "country_code": code,
            "country_name": target_item.get("country_name"),
            "base": round(base_risk, 1),
            "target": round(target_risk, 1),
            "delta": round(target_risk - base_risk, 1),
            "base_dominant_channel": base_item.get("dominant_channel"),
            "target_dominant_channel": target_item.get("dominant_channel"),
        })
    return sorted(rows, key=lambda item: abs(item["delta"]), reverse=True)


def supply_chain_delta_rows(base_sim: dict, target_sim: dict) -> list[dict]:
    base_items = {item.get("key"): item for item in base_sim.get("supply_chains", [])}
    rows = []
    for target_item in target_sim.get("supply_chains", []):
        key = target_item.get("key")
        base_item = base_items.get(key, {})
        base_pressure = float(base_item.get("pressure_score") or 0)
        target_pressure = float(target_item.get("pressure_score") or 0)
        rows.append({
            "key": key,
            "name": target_item.get("name"),
            "base_pressure": round(base_pressure, 1),
            "target_pressure": round(target_pressure, 1),
            "delta": round(target_pressure - base_pressure, 1),
            "base_capacity": base_item.get("capacity"),
            "target_capacity": target_item.get("capacity"),
        })
    return sorted(rows, key=lambda item: abs(item["delta"]), reverse=True)


def agent_decision_change_rows(base_sim: dict, target_sim: dict) -> list[dict]:
    base_items = {item.get("country_code"): item for item in base_sim.get("agent_decisions", [])}
    rows = []
    for target_item in target_sim.get("agent_decisions", []):
        code = target_item.get("country_code")
        base_item = base_items.get(code)
        if base_item is None:
            status = "new"
            base_action = None
        else:
            base_action = base_item.get("action")
            status = "changed" if base_action != target_item.get("action") else "unchanged"
        rows.append({
            "country_code": code,
            "country_name": target_item.get("country_name"),
            "status": status,
            "base_action": base_action,
            "target_action": target_item.get("action"),
            "base_risk_delta": base_item.get("risk_delta") if base_item else None,
            "target_risk_delta": target_item.get("risk_delta"),
            "drivers": target_item.get("drivers", []),
        })
    return sorted(rows, key=lambda item: {"changed": 0, "new": 1, "unchanged": 2}.get(item["status"], 3))


def timeline_delta_summary(base_sim: dict, target_sim: dict) -> dict:
    base_items = {item.get("day"): item for item in base_sim.get("timeline", [])}
    points = []
    for target_item in target_sim.get("timeline", []):
        day = target_item.get("day")
        base_item = base_items.get(day, {})
        base_risk = float(base_item.get("global_risk") or 0)
        target_risk = float(target_item.get("global_risk") or 0)
        points.append({
            "day": day,
            "base_global_risk": round(base_risk, 1),
            "target_global_risk": round(target_risk, 1),
            "delta": round(target_risk - base_risk, 1),
            "turning_point": bool(target_item.get("turning_point") or base_item.get("turning_point")),
        })
    base_peak = max((float(item.get("global_risk") or 0) for item in base_sim.get("timeline", [])), default=None)
    target_peak = max((float(item.get("global_risk") or 0) for item in target_sim.get("timeline", [])), default=None)
    return {
        "base_peak_global_risk": round(base_peak, 1) if base_peak is not None else None,
        "target_peak_global_risk": round(target_peak, 1) if target_peak is not None else None,
        "peak_delta": round_delta(target_peak, base_peak),
        "points": points,
    }


def causal_edge_delta_rows(base_graph: CausalGraphSnapshot | None, target_graph: CausalGraphSnapshot | None) -> list[dict]:
    if not base_graph or not target_graph:
        return []
    base_edges = {edge_signature(edge): edge for edge in base_graph.edges or []}
    rows = []
    for edge in target_graph.edges or []:
        signature = edge_signature(edge)
        base_edge = base_edges.get(signature, {})
        base_weight = float(base_edge.get("weight") or 0)
        target_weight = float(edge.get("weight") or 0)
        rows.append({
            "source": edge.get("source"),
            "target": edge.get("target"),
            "relation": edge.get("relation"),
            "base_weight": round(base_weight, 3),
            "target_weight": round(target_weight, 3),
            "delta": round(target_weight - base_weight, 3),
            "mechanism": edge.get("mechanism") or edge.get("explanation"),
        })
    return sorted(rows, key=lambda item: abs(item["delta"]), reverse=True)[:8]


def edge_signature(edge: dict) -> str:
    return f"{edge.get('source')}->{edge.get('target')}:{edge.get('relation')}"


def round_delta(target_value: float | None, base_value: float | None) -> float | None:
    if target_value is None or base_value is None:
        return None
    return round(float(target_value) - float(base_value), 1)
