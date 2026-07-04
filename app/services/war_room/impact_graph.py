from __future__ import annotations

from .causal_engine import _chain_score

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


def _impact_graph(scenario: WarRoomScenario, chains: list[SupplyChainLink], agents: list[WarRoomCountryAgent], decisions: list[AgentDecision]) -> WarRoomImpactGraph:
    nodes = [
        {"id": "scenario", "label": scenario.name, "kind": "event", "score": round(scenario.intensity * 100, 1)},
        {"id": "market", "label": "Financial Stress", "kind": "market", "score": _chain_score(chains, "settlement")},
        {"id": "opinion", "label": "Public Opinion", "kind": "public_opinion", "score": round(sum(agent.public_opinion_pressure for agent in agents[:5]) / 5, 1)},
        {"id": "alliance", "label": "Diplomatic Alliance", "kind": "alliance", "score": round(sum(agent.military_pressure for agent in agents[:5]) / 5, 1)},
        {"id": "policy", "label": "Sanctions / Countermeasures", "kind": "policy_response", "score": round(scenario.propagation * 100, 1)},
    ]
    nodes.extend({"id": f"chain:{chain.key}", "label": chain.name, "kind": "supply_chain", "score": chain.pressure_score} for chain in chains)
    nodes.extend({"id": f"country:{agent.code}", "label": agent.name, "kind": "country", "score": agent.risk_score} for agent in agents[:6])

    edges = []
    for chain in chains:
        edges.append({
            "source": "scenario",
            "target": f"chain:{chain.key}",
            "relation": "disrupts capacity",
            "weight": round(chain.disruption / 100, 3),
            "lag_days": chain.lag_days,
            "confidence": 72,
            "mechanism": "Shock intensity is multiplied by propagation, substitution gap, lag, target selection, and policy actions.",
            "explanation": f"{scenario.name} raises {chain.name} disruption to {chain.disruption:.1f}.",
        })
        for code in chain.affected_countries[:4]:
            if any(agent.code == code for agent in agents[:6]):
                edges.append({
                    "source": f"chain:{chain.key}",
                    "target": f"country:{code}",
                    "relation": "transmits pressure",
                    "weight": round(chain.pressure_score / 100, 3),
                    "lag_days": chain.lag_days,
                    "confidence": 68,
                    "mechanism": "Country pressure is derived from dependency, trade exposure, financial stress, and limited substitution.",
                    "explanation": f"{chain.name} pressure propagates through exposure and substitution limits.",
                })
    for decision in decisions[:4]:
        edges.append({
            "source": f"country:{decision.country_code}",
            "target": "policy",
            "relation": decision.action,
            "weight": round(decision.confidence / 100, 3),
            "lag_days": 2,
            "confidence": decision.confidence,
            "mechanism": f"Decision drivers: {', '.join(decision.drivers) or 'baseline monitoring'}.",
            "explanation": decision.rationale,
        })
    edges.extend(
        [
            {"source": "policy", "target": "market", "relation": "reprices sanctions and liquidity", "weight": 0.58, "lag_days": 3, "confidence": 63, "mechanism": "Policy actions reallocate physical pressure into market and settlement channels.", "explanation": "Policy responses can reduce physical risk while raising market and settlement stress."},
            {"source": "policy", "target": "opinion", "relation": "shapes public narrative", "weight": 0.52, "lag_days": 4, "confidence": 60, "mechanism": "Messaging and economic stress shift public-opinion pressure.", "explanation": "Domestic narratives affect stability and escalation pressure."},
            {"source": "alliance", "target": "policy", "relation": "coordinates response", "weight": 0.55, "lag_days": 5, "confidence": 62, "mechanism": "Alliance alignment changes sanctions, deterrence, and substitute routing.", "explanation": "Alliance alignment affects sanctions, deterrence, and substitute routing."},
        ]
    )
    confidence = round(min(82, 58 + len(edges) * 0.6), 1)
    return WarRoomImpactGraph(nodes=nodes, edges=edges[:36], confidence=confidence)

