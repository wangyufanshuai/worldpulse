"""Public deterministic execution contract for Simulation Runtime."""

from __future__ import annotations

from typing import Protocol

from app.core.models import (
    SimulationRequest,
    SimulationResult,
    WarRoomRun,
    WarRoomScenarioRequest,
)


class SimulationRuntimeApplicationPort(Protocol):
    def run_simulation(self, request: SimulationRequest) -> SimulationResult: ...

    def run_war_room(self, request: WarRoomScenarioRequest) -> WarRoomRun: ...
