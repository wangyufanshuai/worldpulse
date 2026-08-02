from __future__ import annotations

import ast
import inspect
from types import ModuleType

from app.api import routes
from app.services import ai_analysis, event_digest, simulation_engine
from app.services.world_model import (
    WorldModelApplicationPort,
    WorldModelApplicationService,
    world_model_service,
)
from app.services.world_model import application as world_model_application


def _imports(module: ModuleType) -> set[str]:
    tree = ast.parse(inspect.getsource(module))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.update(f"{node.module}.{alias.name}" for alias in node.names)
    return imported


def test_world_model_adapter_delegates_to_legacy_read_models(monkeypatch):
    captured = {}

    def list_country_agents():
        captured["agents"] = True
        return []

    def network_edges():
        captured["edges"] = True
        return [{"source": "USA", "target": "EU", "channel": "trade", "weight": 0.4}]

    monkeypatch.setattr(world_model_application.legacy_simulation_data, "list_country_agents", list_country_agents)
    monkeypatch.setattr(world_model_application.legacy_simulation_data, "network_edges", network_edges)
    port: WorldModelApplicationPort = WorldModelApplicationService()

    assert port.list_country_agents() == []
    assert port.list_network_edges() == [
        {"source": "USA", "target": "EU", "channel": "trade", "weight": 0.4}
    ]
    assert captured == {"agents": True, "edges": True}


def test_api_and_read_consumers_use_the_world_model_application_port():
    assert routes.world_model is world_model_service
    assert ai_analysis.world_model is world_model_service
    assert event_digest.world_model is world_model_service
    assert simulation_engine.world_model is world_model_service

    for module in (routes, ai_analysis, event_digest, simulation_engine):
        imports = _imports(module)
        assert not any(
            item == "app.services.simulation_data" or item.startswith("app.services.simulation_data.")
            for item in imports
        )
        assert not any(
            item == "app.services.simulation_health" or item.startswith("app.services.simulation_health.")
            for item in imports
        )


def test_world_model_adapter_does_not_import_simulation_runtimes():
    imports = _imports(world_model_application)
    forbidden = (
        "app.services.simulation_engine",
        "app.services.war_room_engine",
        "app.services.agent_runtime",
        "app.services.hybrid_simulation",
        "app.services.negotiation",
    )
    assert not any(item.startswith(forbidden) for item in imports)
