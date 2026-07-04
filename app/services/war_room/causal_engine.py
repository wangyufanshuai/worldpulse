from __future__ import annotations

from copy import deepcopy
from math import sin

from .data import COUNTRIES, POLICY_ACTIONS, SUPPLY_CHAINS, WAR_ROOM_DISCLAIMER
from .utils import _clamp

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


def _apply_supply_chain_pressure(scenario: WarRoomScenario) -> list[SupplyChainLink]:
    out = []
    for chain in deepcopy(SUPPLY_CHAINS):
        _apply_chain_override(chain, scenario.chain_overrides.get(chain.key, {}))
        direct = 1.0 if chain.key in scenario.target_chains else 0.35
        substitution_gap = (100 - chain.substitution) / 100
        lag_multiplier = 1 + chain.lag_days / 45
        disruption = scenario.intensity * scenario.propagation * 100 * direct * substitution_gap * lag_multiplier
        disruption += _policy_chain_delta(scenario.policy_actions, chain.key)
        disruption = min(95.0, max(0.0, disruption))
        chain.disruption = round(disruption, 1)
        chain.capacity = round(max(5.0, 100 - disruption), 1)
        chain.pressure_score = round(min(100.0, chain.pressure_score + disruption * 0.78), 1)
        out.append(chain)
    return sorted(out, key=lambda item: item.pressure_score, reverse=True)


def _apply_agent_pressure(scenario: WarRoomScenario, chains: list[SupplyChainLink]) -> list[WarRoomCountryAgent]:
    chain_pressure = {chain.key: chain.pressure_score for chain in chains}
    out = []
    for agent in deepcopy(COUNTRIES):
        _apply_country_override(agent, scenario.country_overrides.get(agent.code, {}))
        _apply_policy_agent_delta(agent, scenario.policy_actions)
        targeted = 1.0 if agent.code in scenario.target_countries else 0.42
        exposure = (
            agent.energy_dependency * chain_pressure.get("energy", 0) * 0.0024
            + agent.food_dependency * chain_pressure.get("food", 0) * 0.0016
            + agent.trade_exposure * chain_pressure.get("shipping", 0) * 0.002
            + agent.chip_dependency * chain_pressure.get("chips", 0) * 0.0022
            + agent.financial_stress * chain_pressure.get("settlement", 0) * 0.0015
        )
        deterrence = agent.military_pressure * scenario.intensity * targeted * 0.18
        opinion = scenario.intensity * (agent.public_opinion_pressure + exposure) * 0.16
        financial = chain_pressure.get("settlement", 0) * agent.trade_exposure * 0.0018
        risk_delta = exposure * scenario.propagation + deterrence + opinion + financial
        agent.military_pressure = round(min(100, agent.military_pressure + deterrence * 0.8), 1)
        agent.public_opinion_pressure = round(min(100, agent.public_opinion_pressure + opinion), 1)
        agent.financial_stress = round(min(100, agent.financial_stress + financial), 1)
        agent.stability = round(max(0, agent.stability - risk_delta * 0.22), 1)
        agent.risk_score = round(min(100, agent.risk_score + risk_delta), 1)
        out.append(agent)
    return sorted(out, key=lambda item: item.risk_score, reverse=True)


def _build_timeline(scenario: WarRoomScenario, chains: list[SupplyChainLink], agents: list[WarRoomCountryAgent]) -> list[WarRoomTimelinePoint]:
    duration = scenario.duration_days
    checkpoints = sorted({0, 3, 7, 14, 21, 30, duration})
    checkpoints = [day for day in checkpoints if day <= duration]
    max_risk = sum(agent.risk_score for agent in agents[:5]) / 5
    energy = _chain_score(chains, "energy")
    food = _chain_score(chains, "food")
    trade = _chain_score(chains, "shipping")
    settlement = _chain_score(chains, "settlement")
    opinion = sum(agent.public_opinion_pressure for agent in agents[:5]) / 5
    timeline = []
    for day in checkpoints:
        ramp = 0.18 + 0.82 * (day / max(duration, 1))
        wave = 1 + sin(day / max(duration, 1) * 3.14) * 0.08
        timeline.append(
            WarRoomTimelinePoint(
                day=day,
                global_risk=round(max_risk * ramp * wave, 1),
                energy_pressure=round(energy * ramp, 1),
                food_pressure=round(food * ramp, 1),
                trade_pressure=round(trade * ramp, 1),
                financial_pressure=round(settlement * ramp, 1),
                public_opinion_pressure=round(opinion * ramp, 1),
                key_development=_timeline_label(scenario, day),
                turning_point=day in _turning_point_days(scenario),
            )
        )
    return timeline


def _risk_heatmap(agents: list[WarRoomCountryAgent], chains: list[SupplyChainLink]) -> list[WarRoomHeatmapCell]:
    cells = []
    chain_pressure = {chain.key: chain.pressure_score for chain in chains}
    for agent in agents:
        channels = _risk_breakdown(agent, chain_pressure)
        cells.append(
            WarRoomHeatmapCell(
                country_code=agent.code,
                country_name=agent.name,
                region=agent.region,
                latitude=agent.latitude,
                longitude=agent.longitude,
                risk=agent.risk_score,
                dominant_channel=max(channels, key=channels.get),
                risk_breakdown=channels,
            )
        )
    return sorted(cells, key=lambda item: item.risk, reverse=True)


def _summary(scenario: WarRoomScenario, timeline: list[WarRoomTimelinePoint], agents: list[WarRoomCountryAgent], chains: list[SupplyChainLink]) -> str:
    top_agent = agents[0]
    top_chain = chains[0]
    end = timeline[-1]
    return (
        f"{scenario.name} strategy sandbox completed for {scenario.duration_days} days. "
        f"The highest simulated pressure is {top_chain.name} ({top_chain.pressure_score:.1f}/100), "
        f"the most exposed country agent is {top_agent.name} ({top_agent.risk_score:.1f}/100), "
        f"and end-state global risk reaches {end.global_risk:.1f}/100. "
        f"Policy actions: {', '.join(scenario.policy_actions) if scenario.policy_actions else 'none'}. {WAR_ROOM_DISCLAIMER}"
    )


def _chain_score(chains: list[SupplyChainLink], key: str) -> float:
    return next((chain.pressure_score for chain in chains if chain.key == key), 0.0)


def _timeline_label(scenario: WarRoomScenario, day: int) -> str:
    if day == 0:
        return "Scenario initialized; baseline dependencies and alliance posture locked."
    if day <= 3:
        return "First-order logistics, deterrence, and market repricing begin."
    if day <= 14:
        return "Supply-chain substitution and public narrative become dominant uncertainties."
    if day < scenario.duration_days:
        return "Second-order policy responses, sanctions, and financial stress propagate."
    return "End-state comparison: bottlenecks, agent actions, and risk heatmap stabilized."


def _apply_chain_override(chain: SupplyChainLink, fields: dict[str, float]) -> None:
    for field in ("capacity", "disruption", "substitution", "pressure_score"):
        if field in fields:
            setattr(chain, field, _clamp(fields[field], 0, 100))
    if "lag_days" in fields:
        chain.lag_days = int(_clamp(fields["lag_days"], 0, 60))


def _apply_country_override(agent: WarRoomCountryAgent, fields: dict[str, float]) -> None:
    for field in (
        "energy_dependency",
        "food_dependency",
        "trade_exposure",
        "chip_dependency",
        "military_pressure",
        "public_opinion_pressure",
        "financial_stress",
        "stability",
        "risk_score",
    ):
        if field in fields:
            setattr(agent, field, _clamp(fields[field], 0, 100))


def _policy_chain_delta(actions: list[str], chain_key: str) -> float:
    return sum(POLICY_ACTIONS[action]["chain_delta"].get(chain_key, 0) for action in actions if action in POLICY_ACTIONS)


def _apply_policy_agent_delta(agent: WarRoomCountryAgent, actions: list[str]) -> None:
    for action in actions:
        for field, delta in POLICY_ACTIONS[action]["agent_delta"].items():
            current = getattr(agent, field)
            setattr(agent, field, _clamp(current + delta, 0, 100))


def _risk_breakdown(agent: WarRoomCountryAgent, chain_pressure: dict[str, float]) -> dict[str, float]:
    return {
        "energy": round(agent.energy_dependency * chain_pressure.get("energy", 0) / 100, 1),
        "food": round(agent.food_dependency * chain_pressure.get("food", 0) / 100, 1),
        "trade": round(agent.trade_exposure * chain_pressure.get("shipping", 0) / 100, 1),
        "chips": round(agent.chip_dependency * chain_pressure.get("chips", 0) / 100, 1),
        "financial": round(agent.financial_stress * chain_pressure.get("settlement", 0) / 100, 1),
        "public_opinion": round(agent.public_opinion_pressure, 1),
        "military": round(agent.military_pressure, 1),
    }


def _turning_point_days(scenario: WarRoomScenario) -> set[int]:
    days = {3, min(14, scenario.duration_days), scenario.duration_days}
    if scenario.policy_actions:
        days.add(min(7, scenario.duration_days))
    return days


def _assumptions(scenario: WarRoomScenario) -> list[str]:
    action_notes = [
        f"{POLICY_ACTIONS[action]['label']}: {POLICY_ACTIONS[action]['summary']}"
        for action in scenario.policy_actions
        if action in POLICY_ACTIONS
    ]
    return [
        "Deterministic local rules produce numeric outputs; AI text does not drive scores.",
        "No live news, military intelligence, or real-time market data is used.",
        "Target countries and supply chains define first-order shock exposure; non-targeted nodes still receive propagation pressure.",
        *action_notes,
        WAR_ROOM_DISCLAIMER,
    ]

