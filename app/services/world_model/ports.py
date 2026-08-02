"""Public read contract for the World Model bounded context."""

from __future__ import annotations

from typing import Protocol

from app.core.models import (
    CountryAgent,
    SimulationDataHealth,
    SimulationScenario,
    WarRoomPresetBundle,
)


class WorldModelApplicationPort(Protocol):
    def list_country_agents(self) -> list[CountryAgent]: ...

    def get_country_agent(self, code: str) -> CountryAgent | None: ...

    def explain_agent_state(self, agent: CountryAgent) -> dict[str, str]: ...

    def list_simulation_scenarios(self) -> list[SimulationScenario]: ...

    def list_network_edges(self) -> list[dict[str, float | str]]: ...

    def simulation_data_health(self) -> list[SimulationDataHealth]: ...

    def war_room_presets(self) -> WarRoomPresetBundle: ...
