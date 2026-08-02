from __future__ import annotations

import ast
import inspect
from types import ModuleType

from app.api import v7, v11
from app.services.evaluation import gates
from app.services.negotiation import (
    NegotiationReadApplicationPort,
    NegotiationReadApplicationService,
    negotiation_read_service,
)


def _imports(module: ModuleType) -> set[str]:
    tree = ast.parse(inspect.getsource(module))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.update(f"{node.module}.{alias.name}" for alias in node.names)
    return imported


def test_negotiation_read_adapter_delegates_to_repository(monkeypatch):
    captured = {}

    class Repository:
        def list_agent_packs(self):
            captured["called"] = True
            return []

    port: NegotiationReadApplicationPort = NegotiationReadApplicationService(Repository())
    assert port.list_agent_packs() == []
    assert captured == {"called": True}


def test_v7_and_evaluation_governance_use_public_read_contracts():
    assert v7.repository is negotiation_read_service
    assert gates.negotiation_read is negotiation_read_service
    assert callable(getattr(v11.service, "list_verification_results"))

    assert not any(
        item == "app.services.negotiation.repository" or item.startswith("app.services.negotiation.repository.")
        for item in _imports(v7)
    )
    assert not any(
        item == "app.services.evaluation.gates" or item.startswith("app.services.evaluation.gates.")
        for item in _imports(v11)
    )
