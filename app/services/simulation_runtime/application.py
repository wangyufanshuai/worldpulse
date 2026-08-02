"""Compatibility adapter for deterministic Simulation Runtime entrypoints.

The existing engines remain the sole numeric authority.  This adapter only
stabilizes their application boundary; it does not reimplement formulas,
admit Agent proposals, persist results or invoke providers.
"""

from __future__ import annotations

from app.core.models import (
    SimulationRequest,
    SimulationResult,
    WarRoomRun,
    WarRoomScenarioRequest,
)
from app.services import simulation_engine as legacy_simulation_engine
from app.services import war_room_engine as legacy_war_room_engine

from .ports import SimulationRuntimeApplicationPort


class SimulationRuntimeApplicationService:
    def run_simulation(self, request: SimulationRequest) -> SimulationResult:
        return legacy_simulation_engine.run_simulation(request)

    def run_war_room(self, request: WarRoomScenarioRequest) -> WarRoomRun:
        return legacy_war_room_engine.run_war_room(request)


simulation_runtime_service: SimulationRuntimeApplicationPort = SimulationRuntimeApplicationService()
