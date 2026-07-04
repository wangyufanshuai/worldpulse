from __future__ import annotations

from .agent_engine import _agent_decisions
from .causal_engine import _apply_agent_pressure, _apply_supply_chain_pressure, _build_timeline, _risk_heatmap, _summary, _assumptions
from .data import WAR_ROOM_DISCLAIMER
from .impact_graph import _impact_graph
from .scenario import _resolve_scenario
from .ui_projection import _ui_state

from app.core.models import (
    AgentDecision,
    ConflictEvent,
    SupplyChainLink,
    WarRoomCountryAgent,
    WarRoomHeatmapCell,
    WarRoomImpactGraph,
    WarRoomPresetBundle,
    WarRoomRun,
    WarRoomScenario,
    WarRoomScenarioRequest,
    WarRoomTimelinePoint,
)


def run_war_room(request: WarRoomScenarioRequest) -> WarRoomRun:
    scenario = _resolve_scenario(request)
    chains = _apply_supply_chain_pressure(scenario)
    agents = _apply_agent_pressure(scenario, chains)
    timeline = _build_timeline(scenario, chains, agents)
    heatmap = _risk_heatmap(agents, chains)
    decisions = _agent_decisions(agents, heatmap)
    graph = _impact_graph(scenario, chains, agents, decisions)
    summary = _summary(scenario, timeline, agents, chains)
    ui_state = _ui_state(scenario, timeline, agents, chains, heatmap, decisions, graph)
    return WarRoomRun(
        scenario=scenario,
        timeline=timeline,
        country_agents=agents,
        supply_chains=chains,
        impact_graph=graph,
        risk_heatmap=heatmap,
        agent_decisions=decisions,
        summary=summary,
        disclaimer=WAR_ROOM_DISCLAIMER,
        assumptions=_assumptions(scenario),
        ui_state=ui_state,
    )

