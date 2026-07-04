from __future__ import annotations

from .utils import _base_agent, _top_drivers

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


def _agent_decisions(agents: list[WarRoomCountryAgent], heatmap: list[WarRoomHeatmapCell]) -> list[AgentDecision]:
    heatmap_by_code = {item.country_code: item for item in heatmap}
    decisions = []
    for agent in agents[:10]:
        breakdown = heatmap_by_code.get(agent.code).risk_breakdown if heatmap_by_code.get(agent.code) else {}
        drivers = _top_drivers(breakdown)
        if agent.energy_dependency > 78 and agent.risk_score > 58:
            action = "Diversify emergency energy cargoes"
            rationale = "High import dependency and rising supply-chain pressure make energy substitution the first stabilizer."
            tradeoff = "Lowers energy exposure but may increase shipping and settlement costs."
        elif agent.chip_dependency > 65 and agent.risk_score > 55:
            action = "Prioritize chip allocation and export controls"
            rationale = "Semiconductor exposure dominates the simulated causal chain."
            tradeoff = "Protects critical capacity while raising trade friction."
        elif agent.military_pressure > 62:
            action = "Signal deterrence while opening crisis channel"
            rationale = "Military pressure is elevated, so de-escalation channels reduce second-order risk."
            tradeoff = "Improves deterrence but can keep public and market stress elevated."
        elif agent.financial_stress > 55:
            action = "Coordinate liquidity and settlement safeguards"
            rationale = "Financial stress is becoming the main propagation channel."
            tradeoff = "Buffers markets but does not resolve physical bottlenecks."
        else:
            action = "Monitor alliances and prepare substitution"
            rationale = "Risk remains manageable but linked supply chains require contingency buffers."
            tradeoff = "Preserves options but may lag fast-moving disruption."
        decisions.append(
            AgentDecision(
                country_code=agent.code,
                country_name=agent.name,
                action=action,
                rationale=rationale,
                drivers=drivers,
                confidence=round(min(88, 54 + agent.risk_score * 0.34), 1),
                risk_delta=round(agent.risk_score - _base_agent(agent.code).risk_score, 1),
                expected_tradeoff=tradeoff,
            )
        )
    return decisions

