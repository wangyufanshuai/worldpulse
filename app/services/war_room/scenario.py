from __future__ import annotations

from .data import COUNTRIES, POLICY_ACTIONS, SCENARIOS, SUPPLY_CHAINS
from .utils import _clean_overrides, _valid_codes

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


def _resolve_scenario(request: WarRoomScenarioRequest) -> WarRoomScenario:
    base = next((item for item in SCENARIOS if item.key == request.scenario_key), SCENARIOS[0])
    target_countries = _valid_codes(request.target_countries, {agent.code for agent in COUNTRIES}) or base.target_countries
    target_chains = _valid_codes(request.target_chains, {chain.key for chain in SUPPLY_CHAINS}) or base.target_chains
    policy_actions = _valid_codes(request.policy_actions, set(POLICY_ACTIONS))
    return WarRoomScenario(
        key=base.key,
        name=base.name,
        description=base.description,
        duration_days=max(7, min(int(request.duration_days or base.duration_days), 90)),
        intensity=max(0.05, min(float(request.intensity), 1.0)),
        propagation=max(0.05, min(float(request.propagation), 0.9)),
        target_countries=target_countries,
        target_chains=target_chains,
        policy_actions=policy_actions,
        country_overrides=_clean_overrides(request.country_overrides, {agent.code for agent in COUNTRIES}),
        chain_overrides=_clean_overrides(request.chain_overrides, {chain.key for chain in SUPPLY_CHAINS}),
    )

