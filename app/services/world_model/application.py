"""Compatibility read adapter for the World Model bounded context.

The adapter keeps the existing country-data cache, deterministic fixtures and
War Room catalog authoritative while callers migrate away from private data
modules.  It does not execute a simulation or an Agent runtime.
"""

from __future__ import annotations

from app.core.models import (
    CountryAgent,
    SimulationDataHealth,
    SimulationScenario,
    WarRoomPresetBundle,
)
from app.services import simulation_data as legacy_simulation_data
from app.services import simulation_health as legacy_simulation_health
from app.services.war_room import data as legacy_war_room_data

from .ports import WorldModelApplicationPort


class WorldModelApplicationService:
    def list_country_agents(self) -> list[CountryAgent]:
        return legacy_simulation_data.list_country_agents()

    def get_country_agent(self, code: str) -> CountryAgent | None:
        return legacy_simulation_data.get_country_agent(code)

    def explain_agent_state(self, agent: CountryAgent) -> dict[str, str]:
        return legacy_simulation_data.agent_state_explanations(agent)

    def list_simulation_scenarios(self) -> list[SimulationScenario]:
        return legacy_simulation_data.simulation_scenarios()

    def list_network_edges(self) -> list[dict[str, float | str]]:
        return legacy_simulation_data.network_edges()

    def simulation_data_health(self) -> list[SimulationDataHealth]:
        return legacy_simulation_health.build_simulation_data_health()

    def war_room_presets(self) -> WarRoomPresetBundle:
        return legacy_war_room_data.war_room_presets()


world_model_service: WorldModelApplicationPort = WorldModelApplicationService()
