from __future__ import annotations

import ast
import inspect
from types import ModuleType

from app.api import routes
from app.services import ai_analysis, calibration
from app.services.hybrid_simulation import runner as hybrid_runner
from app.services.negotiation import engine as negotiation_engine
from app.services.negotiation import replay as negotiation_replay
from app.services.project_app import service as workspace_service
from app.services.run_lifecycle import executor as lifecycle_executor
from app.services.simulation_runtime import (
    SimulationRuntimeApplicationPort,
    SimulationRuntimeApplicationService,
    simulation_runtime_service,
)
from app.services.simulation_runtime import application as runtime_application


def _imports(module: ModuleType) -> set[str]:
    tree = ast.parse(inspect.getsource(module))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.update(f"{node.module}.{alias.name}" for alias in node.names)
    return imported


def test_simulation_runtime_adapter_delegates_to_numeric_authorities(monkeypatch):
    captured = {}

    def run_simulation(request):
        captured["simulation"] = request
        return "simulation-result"

    def run_war_room(request):
        captured["war_room"] = request
        return "war-room-result"

    monkeypatch.setattr(runtime_application.legacy_simulation_engine, "run_simulation", run_simulation)
    monkeypatch.setattr(runtime_application.legacy_war_room_engine, "run_war_room", run_war_room)
    port: SimulationRuntimeApplicationPort = SimulationRuntimeApplicationService()

    assert port.run_simulation("simulation-request") == "simulation-result"
    assert port.run_war_room("war-room-request") == "war-room-result"
    assert captured == {
        "simulation": "simulation-request",
        "war_room": "war-room-request",
    }


def test_runtime_consumers_use_the_public_application_port():
    consumers = (
        routes,
        ai_analysis,
        calibration,
        hybrid_runner,
        negotiation_engine,
        negotiation_replay,
        workspace_service,
        lifecycle_executor,
    )
    assert all(module.simulation_runtime is simulation_runtime_service for module in consumers)

    for module in consumers:
        imports = _imports(module)
        assert not any(
            item == "app.services.simulation_engine" or item.startswith("app.services.simulation_engine.")
            for item in imports
        )
        assert not any(
            item == "app.services.war_room_engine" or item.startswith("app.services.war_room_engine.")
            for item in imports
        )


def test_runtime_adapter_does_not_import_agents_governance_or_storage():
    imports = _imports(runtime_application)
    forbidden = (
        "app.services.agent_runtime",
        "app.services.consistency",
        "app.services.hybrid_simulation",
        "app.services.negotiation",
        "app.services.project_store",
        "app.services.run_lifecycle",
    )
    assert not any(item.startswith(forbidden) for item in imports)
